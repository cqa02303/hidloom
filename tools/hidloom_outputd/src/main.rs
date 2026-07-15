use std::env;
use std::fs;
use std::io::{self, BufRead, BufReader, Write};
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::{UnixDatagram, UnixListener, UnixStream};
use std::path::Path;
use std::thread;
use std::time::Duration;

const FRAME_SIZE: usize = 64;
const CHECKSUM_OFFSET: usize = 63;
const PAYLOAD_OFFSET: usize = 8;

const KIND_KEYBOARD: u8 = 0x01;
const KIND_MOUSE: u8 = 0x02;
const KIND_CONSUMER: u8 = 0x03;
const KIND_US_SUB_KEYBOARD: u8 = 0x04;
const BTD_FRAME_TYPE_KEYBOARD: u8 = 0x01;
const BTD_FRAME_TYPE_MOUSE: u8 = 0x02;
const BTD_FRAME_TYPE_CONSUMER: u8 = 0x04;

#[derive(Clone)]
struct Config {
    report_socket: String,
    ctrl_socket: String,
    usb_socket: String,
    uidd_socket: String,
    bt_socket: String,
    status_path: String,
    socket_mode: u32,
    ctrl_socket_mode: u32,
    exit_after_frames: Option<u64>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Target {
    Usb,
    Uinput,
    Bt,
    Auto,
}

#[derive(Default)]
struct Counters {
    frames_received: u64,
    frames_to_usb: u64,
    frames_to_uinput: u64,
    frames_to_bt: u64,
    invalid_frames: u64,
    forward_errors: u64,
    release_frames: u64,
    ctrl_requests: u64,
}

struct RouterState {
    target: Target,
    last_error: String,
}

fn env_string(name: &str, default: &str) -> String {
    env::var(name)
        .ok()
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| default.to_string())
}

fn env_u32(name: &str, default: u32, min: u32, max: u32) -> u32 {
    env::var(name)
        .ok()
        .and_then(|raw| {
            u32::from_str_radix(
                raw.trim_start_matches("0o"),
                if raw.starts_with("0o") { 8 } else { 10 },
            )
            .ok()
        })
        .filter(|value| *value >= min && *value <= max)
        .unwrap_or(default)
}

fn target_name(target: Target) -> &'static str {
    match target {
        Target::Usb => "usb",
        Target::Uinput => "uinput",
        Target::Bt => "bt",
        Target::Auto => "auto",
    }
}

fn parse_target(value: &str) -> Option<Target> {
    match value {
        "usb" | "gadget" => Some(Target::Usb),
        "uinput" | "console" => Some(Target::Uinput),
        "bt" | "bluetooth" => Some(Target::Bt),
        "auto" => Some(Target::Auto),
        _ => None,
    }
}

fn load_config() -> Result<(Config, Target), String> {
    let mut exit_after_frames = None;
    let mut args = env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--frames" => {
                let raw = args.next().ok_or("--frames requires a value")?;
                exit_after_frames = Some(raw.parse::<u64>().map_err(|_| "invalid --frames value")?);
            }
            "--help" => {
                println!("usage: hidloom-outputd [--frames N]");
                std::process::exit(0);
            }
            _ => return Err(format!("unknown argument: {arg}")),
        }
    }
    let target_raw = env_string("OUTPUTD_TARGET", "usb");
    let target = parse_target(&target_raw).ok_or_else(|| format!("invalid OUTPUTD_TARGET: {target_raw}"))?;
    Ok((
        Config {
            report_socket: env_string("OUTPUTD_REPORT_SOCKET", "/tmp/hidloom_output_reports.sock"),
            ctrl_socket: env_string("OUTPUTD_CTRL_SOCKET", "/tmp/hidloom_output_ctrl.sock"),
            usb_socket: env_string("OUTPUTD_USB_SOCKET", "/tmp/usbd_hid_reports.sock"),
            uidd_socket: env_string("OUTPUTD_UIDD_SOCKET", "/tmp/uidd_reports.sock"),
            bt_socket: env_string("OUTPUTD_BT_SOCKET", "/tmp/btd_events.sock"),
            status_path: env_string("OUTPUTD_STATUS_PATH", "/run/hidloom/outputd-status.json"),
            socket_mode: env_u32("OUTPUTD_REPORT_SOCKET_MODE", 0o666, 0, 0o777),
            ctrl_socket_mode: env_u32("OUTPUTD_CTRL_SOCKET_MODE", 0o666, 0, 0o777),
            exit_after_frames,
        },
        target,
    ))
}

fn xor_checksum(data: &[u8]) -> u8 {
    data.iter().fold(0u8, |acc, byte| acc ^ byte)
}

fn validate_frame(frame: &[u8]) -> Result<u8, String> {
    if frame.len() != FRAME_SIZE {
        return Err("invalid frame size".to_string());
    }
    if &frame[0..4] != b"CQAU" {
        return Err("invalid magic".to_string());
    }
    if frame[4] != 1 {
        return Err("invalid version".to_string());
    }
    if frame[7] != 0 {
        return Err("reserved byte must be zero".to_string());
    }
    if xor_checksum(&frame[..CHECKSUM_OFFSET]) != frame[CHECKSUM_OFFSET] {
        return Err("invalid checksum".to_string());
    }
    let kind = frame[5];
    let expected = match kind {
        KIND_KEYBOARD | KIND_US_SUB_KEYBOARD => 8,
        KIND_MOUSE => 4,
        KIND_CONSUMER => 2,
        _ => return Err("unsupported kind".to_string()),
    };
    if frame[6] != expected {
        return Err("invalid payload length".to_string());
    }
    if frame[PAYLOAD_OFFSET + usize::from(expected)..CHECKSUM_OFFSET]
        .iter()
        .any(|byte| *byte != 0)
    {
        return Err("reserved payload bytes must be zero".to_string());
    }
    Ok(kind)
}

fn encode_frame(kind: u8, payload: &[u8]) -> [u8; FRAME_SIZE] {
    let mut frame = [0u8; FRAME_SIZE];
    frame[0..4].copy_from_slice(b"CQAU");
    frame[4] = 1;
    frame[5] = kind;
    frame[6] = payload.len() as u8;
    frame[PAYLOAD_OFFSET..PAYLOAD_OFFSET + payload.len()].copy_from_slice(payload);
    frame[CHECKSUM_OFFSET] = xor_checksum(&frame[..CHECKSUM_OFFSET]);
    frame
}

fn null_keyboard_frame(kind: u8) -> [u8; FRAME_SIZE] {
    encode_frame(kind, &[0u8; 8])
}

fn bind_datagram(path: &str, mode: u32) -> io::Result<UnixDatagram> {
    let socket_path = Path::new(path);
    if socket_path.exists() {
        let _ = fs::remove_file(socket_path);
    }
    if let Some(parent) = socket_path.parent() {
        fs::create_dir_all(parent)?;
    }
    let socket = UnixDatagram::bind(socket_path)?;
    let mut permissions = fs::metadata(socket_path)?.permissions();
    permissions.set_mode(mode);
    fs::set_permissions(socket_path, permissions)?;
    socket.set_nonblocking(true)?;
    Ok(socket)
}

fn bind_listener(path: &str, mode: u32) -> io::Result<UnixListener> {
    let socket_path = Path::new(path);
    if socket_path.exists() {
        let _ = fs::remove_file(socket_path);
    }
    if let Some(parent) = socket_path.parent() {
        fs::create_dir_all(parent)?;
    }
    let listener = UnixListener::bind(socket_path)?;
    let mut permissions = fs::metadata(socket_path)?.permissions();
    permissions.set_mode(mode);
    fs::set_permissions(socket_path, permissions)?;
    listener.set_nonblocking(true)?;
    Ok(listener)
}

fn json_escape(value: &str) -> String {
    value
        .replace('\\', "\\\\")
        .replace('"', "\\\"")
        .replace('\n', "\\n")
        .replace('\r', "\\r")
}

fn status_json(cfg: &Config, state: &RouterState, counters: &Counters) -> String {
    format!(
        concat!(
            "{{",
            "\"schema\":\"hidloom.outputd.status.v1\",",
            "\"process\":true,",
            "\"target\":\"{}\",",
            "\"sockets\":{{",
            "\"report\":\"{}\",",
            "\"ctrl\":\"{}\",",
            "\"usb\":\"{}\",",
            "\"uidd\":\"{}\",",
            "\"bt\":\"{}\"",
            "}},",
            "\"last_error\":\"{}\",",
            "\"counters\":{{",
            "\"frames_received\":{},",
            "\"frames_to_usb\":{},",
            "\"frames_to_uinput\":{},",
            "\"frames_to_bt\":{},",
            "\"invalid_frames\":{},",
            "\"forward_errors\":{},",
            "\"release_frames\":{},",
            "\"ctrl_requests\":{}",
            "}}",
            "}}\n"
        ),
        target_name(state.target),
        json_escape(&cfg.report_socket),
        json_escape(&cfg.ctrl_socket),
        json_escape(&cfg.usb_socket),
        json_escape(&cfg.uidd_socket),
        json_escape(&cfg.bt_socket),
        json_escape(&state.last_error),
        counters.frames_received,
        counters.frames_to_usb,
        counters.frames_to_uinput,
        counters.frames_to_bt,
        counters.invalid_frames,
        counters.forward_errors,
        counters.release_frames,
        counters.ctrl_requests
    )
}

fn write_status(cfg: &Config, state: &RouterState, counters: &Counters) {
    if cfg.status_path.is_empty() {
        return;
    }
    if let Some(parent) = Path::new(&cfg.status_path).parent() {
        let _ = fs::create_dir_all(parent);
    }
    let tmp = format!("{}.tmp", cfg.status_path);
    if fs::write(&tmp, status_json(cfg, state, counters)).is_ok() {
        let _ = fs::rename(tmp, &cfg.status_path);
    }
}

fn forward_frame(socket: &UnixDatagram, path: &str, frame: &[u8]) -> Result<(), String> {
    socket
        .send_to(frame, path)
        .map(|_| ())
        .map_err(|err| format!("failed to forward to {path}: {err}"))
}

fn btd_frame_type(kind: u8) -> Option<u8> {
    match kind {
        KIND_KEYBOARD | KIND_US_SUB_KEYBOARD => Some(BTD_FRAME_TYPE_KEYBOARD),
        KIND_MOUSE => Some(BTD_FRAME_TYPE_MOUSE),
        KIND_CONSUMER => Some(BTD_FRAME_TYPE_CONSUMER),
        _ => None,
    }
}

fn forward_bt_frame(path: &str, kind: u8, frame: &[u8]) -> Result<(), String> {
    let Some(frame_type) = btd_frame_type(kind) else {
        return Err(format!("unsupported btd frame kind: {kind}"));
    };
    let payload_len = usize::from(frame[6]);
    let payload = &frame[PAYLOAD_OFFSET..PAYLOAD_OFFSET + payload_len];
    let mut stream = UnixStream::connect(path).map_err(|err| format!("failed to connect to {path}: {err}"))?;
    stream
        .write_all(b"btd1")
        .and_then(|_| stream.write_all(&[frame_type, payload_len as u8]))
        .and_then(|_| stream.write_all(payload))
        .map_err(|err| format!("failed to forward to {path}: {err}"))
}

fn forward_to_target(
    socket: &UnixDatagram,
    cfg: &Config,
    state: &mut RouterState,
    counters: &mut Counters,
    frame: &[u8],
    kind: u8,
) {
    let target = match state.target {
        Target::Usb => Target::Usb,
        Target::Uinput => Target::Uinput,
        Target::Bt => Target::Bt,
        Target::Auto => Target::Usb,
    };
    let result = match target {
        Target::Usb => forward_frame(socket, &cfg.usb_socket, frame).map(|_| {
            counters.frames_to_usb += 1;
        }),
        Target::Uinput => forward_frame(socket, &cfg.uidd_socket, frame).map(|_| {
            counters.frames_to_uinput += 1;
        }),
        Target::Bt => forward_bt_frame(&cfg.bt_socket, kind, frame).map(|_| {
            counters.frames_to_bt += 1;
        }),
        Target::Auto => unreachable!(),
    };
    match result {
        Ok(()) => state.last_error.clear(),
        Err(err) => {
            counters.forward_errors += 1;
            state.last_error = err;
        }
    }
}

fn send_release_frames(
    socket: &UnixDatagram,
    cfg: &Config,
    old: Target,
    new: Target,
    counters: &mut Counters,
) {
    let mut paths = Vec::new();
    for target in [old, new] {
        match target {
            Target::Usb | Target::Auto => paths.push(cfg.usb_socket.as_str()),
            Target::Uinput => paths.push(cfg.uidd_socket.as_str()),
            Target::Bt => paths.push(cfg.bt_socket.as_str()),
        }
    }
    paths.sort_unstable();
    paths.dedup();
    for path in paths {
        for kind in [KIND_KEYBOARD, KIND_US_SUB_KEYBOARD] {
            let frame = null_keyboard_frame(kind);
            let sent = if path == cfg.bt_socket.as_str() {
                forward_bt_frame(path, kind, &frame).is_ok()
            } else {
                forward_frame(socket, path, &frame).is_ok()
            };
            if sent {
                counters.release_frames += 1;
            }
        }
    }
}

fn extract_target(line: &str) -> Option<Target> {
    for alias in ["usb", "gadget", "uinput", "console", "bt", "bluetooth", "auto"] {
        if line.contains(&format!("\"target\":\"{alias}\""))
            || line.contains(&format!("\"target\": \"{alias}\""))
        {
            return parse_target(alias);
        }
    }
    None
}

fn handle_ctrl_line(
    line: &str,
    cfg: &Config,
    state: &mut RouterState,
    counters: &mut Counters,
    forwarder: &UnixDatagram,
) -> String {
    counters.ctrl_requests += 1;
    if line.contains("\"status\"") || line.contains("\"t\":\"status\"") || line.contains("\"t\": \"status\"") {
        return status_json(cfg, state, counters);
    }
    if line.contains("set_output_target") {
        let Some(target) = extract_target(line) else {
            return "{\"result\":\"error\",\"error\":\"target_required\"}\n".to_string();
        };
        let old = state.target;
        if old != target {
            send_release_frames(forwarder, cfg, old, target, counters);
        }
        state.target = target;
        state.last_error.clear();
        return format!(
            "{{\"result\":\"ok\",\"target\":\"{}\"}}\n",
            target_name(state.target)
        );
    }
    if line.contains("release_all") {
        send_release_frames(forwarder, cfg, state.target, state.target, counters);
        return "{\"result\":\"ok\"}\n".to_string();
    }
    "{\"result\":\"error\",\"error\":\"unknown_command\"}\n".to_string()
}

fn handle_ctrl_clients(
    listener: &UnixListener,
    cfg: &Config,
    state: &mut RouterState,
    counters: &mut Counters,
    forwarder: &UnixDatagram,
) {
    loop {
        match listener.accept() {
            Ok((stream, _)) => handle_ctrl_stream(stream, cfg, state, counters, forwarder),
            Err(err) if err.kind() == io::ErrorKind::WouldBlock => break,
            Err(err) => {
                state.last_error = format!("failed to accept ctrl client: {err}");
                break;
            }
        }
    }
}

fn handle_ctrl_stream(
    stream: UnixStream,
    cfg: &Config,
    state: &mut RouterState,
    counters: &mut Counters,
    forwarder: &UnixDatagram,
) {
    let mut writer = match stream.try_clone() {
        Ok(writer) => writer,
        Err(err) => {
            state.last_error = format!("failed to clone ctrl stream: {err}");
            return;
        }
    };
    let mut reader = BufReader::new(stream);
    let mut line = String::new();
    loop {
        line.clear();
        match reader.read_line(&mut line) {
            Ok(0) => break,
            Ok(_) => {
                let response = handle_ctrl_line(line.trim(), cfg, state, counters, forwarder);
                if writer.write_all(response.as_bytes()).is_err() {
                    break;
                }
            }
            Err(err) => {
                state.last_error = format!("failed to read ctrl line: {err}");
                break;
            }
        }
    }
}

fn run() -> Result<(), String> {
    let (cfg, initial_target) = load_config()?;
    let reports = bind_datagram(&cfg.report_socket, cfg.socket_mode)
        .map_err(|err| format!("failed to bind {}: {err}", cfg.report_socket))?;
    let ctrl = bind_listener(&cfg.ctrl_socket, cfg.ctrl_socket_mode)
        .map_err(|err| format!("failed to bind {}: {err}", cfg.ctrl_socket))?;
    let forwarder = UnixDatagram::unbound().map_err(|err| format!("failed to create forwarder: {err}"))?;
    let mut state = RouterState {
        target: initial_target,
        last_error: String::new(),
    };
    let mut counters = Counters::default();
    let mut processed = 0u64;
    write_status(&cfg, &state, &counters);
    loop {
        handle_ctrl_clients(&ctrl, &cfg, &mut state, &mut counters, &forwarder);
        let mut frame = [0u8; FRAME_SIZE];
        match reports.recv(&mut frame) {
            Ok(size) => {
                match validate_frame(&frame[..size]) {
                    Ok(kind) => {
                        counters.frames_received += 1;
                        forward_to_target(&forwarder, &cfg, &mut state, &mut counters, &frame, kind);
                    }
                    Err(err) => {
                        counters.invalid_frames += 1;
                        state.last_error = err;
                    }
                }
                processed += 1;
                write_status(&cfg, &state, &counters);
                if cfg
                    .exit_after_frames
                    .is_some_and(|limit| processed >= limit)
                {
                    break;
                }
            }
            Err(err) if err.kind() == io::ErrorKind::WouldBlock => {
                write_status(&cfg, &state, &counters);
                thread::sleep(Duration::from_millis(1));
            }
            Err(err) => return Err(format!("failed to receive report frame: {err}")),
        }
    }
    let _ = fs::remove_file(&cfg.report_socket);
    let _ = fs::remove_file(&cfg.ctrl_socket);
    write_status(&cfg, &state, &counters);
    Ok(())
}

fn main() {
    if let Err(err) = run() {
        eprintln!("hidloom-outputd: {err}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn validates_keyboard_frame() {
        let frame = encode_frame(KIND_KEYBOARD, &[0, 0, 4, 0, 0, 0, 0, 0]);
        assert_eq!(validate_frame(&frame).unwrap(), KIND_KEYBOARD);
    }

    #[test]
    fn rejects_bad_checksum() {
        let mut frame = encode_frame(KIND_KEYBOARD, &[0, 0, 4, 0, 0, 0, 0, 0]);
        frame[10] ^= 1;
        assert_eq!(validate_frame(&frame).unwrap_err(), "invalid checksum");
    }

    #[test]
    fn parses_target_aliases() {
        assert_eq!(parse_target("gadget"), Some(Target::Usb));
        assert_eq!(parse_target("console"), Some(Target::Uinput));
    }
}
