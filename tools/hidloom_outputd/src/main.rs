use std::env;
use std::fs;
use std::io::{self, Read, Write};
use std::os::fd::FromRawFd;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::{UnixDatagram, UnixListener, UnixStream};
use std::path::Path;
use std::thread;
use std::time::{Duration, Instant, SystemTime};

mod readiness;

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

#[derive(Clone, Default)]
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
    readiness_paths: readiness::Paths,
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
    release_errors: u64,
    ctrl_requests: u64,
}

#[derive(Default)]
struct ReleaseAck {
    attempted: u64,
    delivered: u64,
    errors: u64,
    last_error: String,
    failed: Vec<(Target, u8)>,
}

struct RouterState {
    target: Target,
    last_error: String,
    bt_reports: [[u8; 8]; 2],
    effective: Option<Target>,
    readiness: readiness::Sample,
    pending_usb_neutral: bool,
    usb_ready_samples: u8,
}

// Bounds limit control memory and work per loop; no timeout is needed for idle clients.
const MAX_CTRL_CLIENTS: usize = 32;
const MAX_CTRL_INPUT: usize = 8192;
const MAX_CTRL_OUTPUT: usize = 65536;
const CTRL_IO_BUDGET: usize = 4096;
const CTRL_LINES_PER_TICK: usize = 4;

struct CtrlClient {
    stream: UnixStream,
    input: Vec<u8>,
    output: Vec<u8>,
    written: usize,
    eof: bool,
}

fn merged_keyboard(reports: &[[u8; 8]; 2]) -> Result<[u8; 8], String> {
    let mut report = [0u8; 8];
    report[0] = reports[0][0] | reports[1][0];
    let mut count = 0;
    for usage in reports.iter().flat_map(|r| r[2..].iter()).copied() {
        if usage == 0 || report[2..2 + count].contains(&usage) {
            continue;
        }
        if count == 6 {
            return Err("BT keyboard endpoint union exceeds six keys".to_string());
        }
        report[2 + count] = usage;
        count += 1;
    }
    Ok(report)
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
    let target =
        parse_target(&target_raw).ok_or_else(|| format!("invalid OUTPUTD_TARGET: {target_raw}"))?;
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
            readiness_paths: readiness::Paths {
                gadget_udc: env_string(
                    "OUTPUTD_GADGET_UDC_PATH",
                    "/sys/kernel/config/usb_gadget/cqa02303v5/UDC",
                ),
                udc_root: env_string("OUTPUTD_UDC_ROOT", "/sys/class/udc"),
                hidd_status: env_string(
                    "OUTPUTD_HIDD_STATUS_PATH",
                    "/run/hidloom/hidd-status.json",
                ),
                uidd_status: env_string(
                    "OUTPUTD_UIDD_STATUS_PATH",
                    "/run/hidloom/uidd-status.json",
                ),
            },
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
            "\"pid\":{},",
            "\"target\":\"{}\",",
            "\"effective_target\":\"{}\",",
            "\"readiness\":{{\"reason\":\"{}\",\"usb\":\"{}\",\"uinput\":{},\"pending_usb_neutral\":{}}},",
            "\"release_confirmation\":\"ipc_delivery_only\",",
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
            "\"release_errors\":{},",
            "\"ctrl_requests\":{}",
            "}}",
            "}}\n"
        ),
        std::process::id(),
        target_name(state.target),
        state.effective.map(target_name).unwrap_or("unavailable"),
        state.readiness.reason,
        match state.readiness.usb {
            readiness::UsbReadiness::Ready => "ready",
            readiness::UsbReadiness::Detached => "detached",
            readiness::UsbReadiness::Unknown => "unknown",
        },
        state.readiness.uinput,
        state.pending_usb_neutral,
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
        counters.release_errors,
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
    let mut stream = connect_bt_nonblocking(path)
        .map_err(|err| format!("failed to connect to {path}: {err}"))?;
    stream
        .write_all(b"btd1")
        .and_then(|_| stream.write_all(&[frame_type, payload_len as u8]))
        .and_then(|_| stream.write_all(payload))
        .map_err(|err| format!("failed to forward to {path}: {err}"))
}

// Linux AF_UNIX connect can itself block when the server accept queue fills.
// Create with SOCK_NONBLOCK before connect, so an unavailable btd cannot stall
// keyboard/control processing. A failed/partial send remains a delivery error.
fn connect_bt_nonblocking(path: &str) -> io::Result<UnixStream> {
    #[repr(C)]
    struct SockAddrUn {
        family: u16,
        path: [u8; 108],
    }
    unsafe extern "C" {
        fn socket(domain: i32, kind: i32, protocol: i32) -> i32;
        fn connect(fd: i32, address: *const SockAddrUn, len: u32) -> i32;
    }
    if path.is_empty() || path.len() >= 108 || path.as_bytes().contains(&0) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "invalid btd socket path",
        ));
    }
    let mut address = SockAddrUn {
        family: 1,
        path: [0; 108],
    };
    address.path[..path.len()].copy_from_slice(path.as_bytes());
    let fd = unsafe { socket(1, 1 | 0o4000 | 0o2000000, 0) };
    if fd < 0 {
        return Err(io::Error::last_os_error());
    }
    let stream = unsafe { UnixStream::from_raw_fd(fd) };
    if unsafe { connect(fd, &address, (2 + path.len() + 1) as u32) } < 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(stream)
}

fn forward_to_target(
    socket: &UnixDatagram,
    cfg: &Config,
    state: &mut RouterState,
    counters: &mut Counters,
    frame: &[u8],
    kind: u8,
) {
    let Some(target) = state.effective else {
        counters.forward_errors += 1;
        state.last_error = "output unavailable".to_string();
        return;
    };
    if target == Target::Usb && state.pending_usb_neutral {
        counters.forward_errors += 1;
        state.last_error = "USB pending neutral before input".to_string();
        return;
    }
    let result = match target {
        Target::Usb => forward_frame(socket, &cfg.usb_socket, frame).map(|_| {
            counters.frames_to_usb += 1;
        }),
        Target::Uinput if !matches!(kind, KIND_KEYBOARD | KIND_US_SUB_KEYBOARD) => {
            Err(format!("uinput does not support report kind {kind}"))
        }
        Target::Uinput => forward_frame(socket, &cfg.uidd_socket, frame).map(|_| {
            counters.frames_to_uinput += 1;
        }),
        Target::Bt => {
            let result = if matches!(kind, KIND_KEYBOARD | KIND_US_SUB_KEYBOARD) {
                // This is desired input state, not an acknowledgement from btd.
                // Retain a release even when IPC fails, so a later endpoint
                // update cannot reintroduce the released usage from a stale snapshot.
                state.bt_reports[if kind == KIND_US_SUB_KEYBOARD { 1 } else { 0 }]
                    .copy_from_slice(&frame[PAYLOAD_OFFSET..PAYLOAD_OFFSET + 8]);
                merged_keyboard(&state.bt_reports).and_then(|report| {
                    forward_bt_frame(
                        &cfg.bt_socket,
                        KIND_KEYBOARD,
                        &encode_frame(KIND_KEYBOARD, &report),
                    )
                })
            } else {
                forward_bt_frame(&cfg.bt_socket, kind, frame)
            };
            result.map(|_| {
                counters.frames_to_bt += 1;
            })
        }
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
    state: &mut RouterState,
    counters: &mut Counters,
) -> ReleaseAck {
    let mut ack = ReleaseAck::default();
    let mut destinations = Vec::new();
    for target in [old, new] {
        let target = if target == Target::Auto {
            Target::Usb
        } else {
            target
        };
        if !destinations.contains(&target) {
            destinations.push(target);
        }
    }
    for target in destinations {
        let (path, kinds): (&str, &[u8]) = match target {
            Target::Usb => (
                &cfg.usb_socket,
                &[
                    KIND_KEYBOARD,
                    KIND_US_SUB_KEYBOARD,
                    KIND_MOUSE,
                    KIND_CONSUMER,
                ],
            ),
            Target::Uinput => (&cfg.uidd_socket, &[KIND_KEYBOARD, KIND_US_SUB_KEYBOARD]),
            Target::Bt => (&cfg.bt_socket, &[KIND_KEYBOARD, KIND_MOUSE, KIND_CONSUMER]),
            Target::Auto => unreachable!(),
        };
        for &kind in kinds {
            if target == Target::Bt && kind == KIND_KEYBOARD {
                // A failed neutral remains a failed delivery, but the desired
                // endpoint state is already released and must not be replayed.
                state.bt_reports = [[0; 8]; 2];
            }
            let frame = match kind {
                KIND_MOUSE => encode_frame(kind, &[0; 4]),
                KIND_CONSUMER => encode_frame(kind, &[0; 2]),
                _ => null_keyboard_frame(kind),
            };
            ack.attempted += 1;
            let result = if target == Target::Bt {
                forward_bt_frame(path, kind, &frame)
            } else {
                forward_frame(socket, path, &frame)
            };
            match result {
                Ok(()) => {
                    ack.delivered += 1;
                    counters.release_frames += 1;
                }
                Err(err) => {
                    ack.failed.push((target, kind));
                    ack.errors += 1;
                    ack.last_error = err;
                    counters.forward_errors += 1;
                    counters.release_errors += 1;
                }
            }
        }
    }
    ack
}

fn release_ack_json(ack: &ReleaseAck) -> String {
    let failures = if ack.failed.is_empty() {
        String::new()
    } else {
        format!(
            ",\"failed\":[{}]",
            ack.failed
                .iter()
                .map(|(target, kind)| {
                    format!(
                        "{{\"target\":\"{}\",\"kind\":{}}}",
                        target_name(*target),
                        kind
                    )
                })
                .collect::<Vec<_>>()
                .join(",")
        )
    };
    format!(
        "{{\"attempted\":{},\"delivered\":{},\"errors\":{}{}}}",
        ack.attempted, ack.delivered, ack.errors, failures
    )
}

fn refresh_auto(
    cfg: &Config,
    state: &mut RouterState,
    counters: &mut Counters,
    socket: &UnixDatagram,
) -> ReleaseAck {
    state.readiness = readiness::sample(
        &cfg.readiness_paths,
        &cfg.usb_socket,
        &cfg.uidd_socket,
        SystemTime::now(),
    );
    if state.target != Target::Auto {
        if state.effective == Some(Target::Usb)
            && state.pending_usb_neutral
            && state.readiness.usb == readiness::UsbReadiness::Ready
        {
            let ack = send_release_frames(socket, cfg, Target::Usb, Target::Usb, state, counters);
            if ack.errors == 0 {
                state.pending_usb_neutral = false;
            }
            return ack;
        }
        return ReleaseAck::default();
    }
    state.usb_ready_samples = if state.readiness.usb == readiness::UsbReadiness::Ready {
        state.usb_ready_samples.saturating_add(1)
    } else {
        0
    };
    // Two consecutive publications establish reconnect stability. Suspend or
    // stale status never redirects a possibly held modifier into the console.
    let next = match state.readiness.usb {
        readiness::UsbReadiness::Ready if state.usb_ready_samples >= 2 => Some(Target::Usb),
        readiness::UsbReadiness::Detached => {
            if state.effective == Some(Target::Usb) {
                state.pending_usb_neutral = true;
            }
            state.readiness.uinput.then_some(Target::Uinput)
        }
        _ => {
            if state.effective == Some(Target::Uinput) && !state.readiness.uinput {
                None
            } else {
                state.effective
            }
        }
    };
    if next == state.effective {
        return ReleaseAck::default();
    }
    let old = state.effective;
    let old_deliverable = old.filter(|target| {
        !(*target == Target::Usb && state.readiness.usb == readiness::UsbReadiness::Detached)
    });
    let release = match (old_deliverable, next) {
        (Some(old), Some(new)) => send_release_frames(socket, cfg, old, new, state, counters),
        (Some(target), None) | (None, Some(target)) => {
            send_release_frames(socket, cfg, target, target, state, counters)
        }
        (None, None) => ReleaseAck::default(),
    };
    if release.errors == 0 {
        state.effective = next;
        state.bt_reports = [[0; 8]; 2];
        if next == Some(Target::Usb) {
            state.pending_usb_neutral = false;
        }
        state.last_error.clear();
    } else {
        state.last_error = release.last_error.clone();
        if old_deliverable.is_none() {
            state.effective = None;
        }
    }
    release
}

fn extract_target(line: &str) -> Option<Target> {
    for alias in [
        "usb",
        "gadget",
        "uinput",
        "console",
        "bt",
        "bluetooth",
        "auto",
    ] {
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
    if line.contains("\"status\"")
        || line.contains("\"t\":\"status\"")
        || line.contains("\"t\": \"status\"")
    {
        return status_json(cfg, state, counters);
    }
    if line.contains("set_output_target") {
        let Some(target) = extract_target(line) else {
            return "{\"result\":\"error\",\"error\":\"target_required\"}\n".to_string();
        };
        let old = state.target;
        let release = if target == Target::Auto {
            state.target = target;
            refresh_auto(cfg, state, counters, forwarder)
        } else if state.effective != Some(target) {
            send_release_frames(
                forwarder,
                cfg,
                state.effective.unwrap_or(target),
                target,
                state,
                counters,
            )
        } else {
            ReleaseAck::default()
        };
        if release.errors == 0 {
            state.target = target;
            if target != Target::Auto {
                state.effective = Some(target);
                state.bt_reports = [[0; 8]; 2];
                if target == Target::Usb && state.readiness.usb == readiness::UsbReadiness::Ready {
                    state.pending_usb_neutral = false;
                }
            }
            state.last_error.clear();
            return format!(
                "{{\"result\":\"ok\",\"target\":\"{}\",\"release\":{}}}\n",
                target_name(state.target),
                release_ack_json(&release)
            );
        }
        state.last_error = release.last_error.clone();
        state.target = old;
        return format!(
            "{{\"result\":\"error\",\"error\":\"release_delivery_failed\",\"target\":\"{}\",\"release\":{}}}\n",
            target_name(state.target),
            release_ack_json(&release)
        );
    }
    if line.contains("release_all") {
        let Some(target) = state.effective else {
            return "{\"result\":\"error\",\"error\":\"output_unavailable\"}\n".to_string();
        };
        let release = send_release_frames(forwarder, cfg, target, target, state, counters);
        if release.errors == 0 {
            state.last_error.clear();
            return format!(
                "{{\"result\":\"ok\",\"release\":{}}}\n",
                release_ack_json(&release)
            );
        }
        state.last_error = release.last_error.clone();
        return format!(
            "{{\"result\":\"error\",\"error\":\"release_delivery_failed\",\"release\":{}}}\n",
            release_ack_json(&release)
        );
    }
    "{\"result\":\"error\",\"error\":\"unknown_command\"}\n".to_string()
}

fn handle_ctrl_clients(
    listener: &UnixListener,
    clients: &mut Vec<CtrlClient>,
    cfg: &Config,
    state: &mut RouterState,
    counters: &mut Counters,
    forwarder: &UnixDatagram,
) {
    for _ in 0..MAX_CTRL_CLIENTS {
        match listener.accept() {
            Ok((stream, _)) => {
                if clients.len() < MAX_CTRL_CLIENTS && stream.set_nonblocking(true).is_ok() {
                    clients.push(CtrlClient {
                        stream,
                        input: Vec::new(),
                        output: Vec::new(),
                        written: 0,
                        eof: false,
                    });
                }
            }
            Err(err) if err.kind() == io::ErrorKind::WouldBlock => break,
            Err(err) => {
                state.last_error = format!("failed to accept ctrl client: {err}");
                break;
            }
        }
    }
    clients.retain_mut(|client| handle_ctrl_stream(client, cfg, state, counters, forwarder));
}

fn handle_ctrl_stream(
    client: &mut CtrlClient,
    cfg: &Config,
    state: &mut RouterState,
    counters: &mut Counters,
    forwarder: &UnixDatagram,
) -> bool {
    let mut bytes = [0u8; CTRL_IO_BUDGET];
    if !client.eof {
        match client.stream.read(&mut bytes) {
            Ok(0) => client.eof = true,
            Ok(size) => client.input.extend_from_slice(&bytes[..size]),
            Err(err)
                if matches!(
                    err.kind(),
                    io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted
                ) => {}
            Err(_) => return false,
        }
        if client.input.len() > MAX_CTRL_INPUT {
            return false;
        }
    }
    if client.written > 0 {
        client.output.drain(..client.written);
        client.written = 0;
    }
    for _ in 0..CTRL_LINES_PER_TICK {
        // Backpressure the caller before executing another command.
        if client.output.len() > MAX_CTRL_OUTPUT - CTRL_IO_BUDGET {
            break;
        }
        let end = client
            .input
            .iter()
            .position(|byte| *byte == b'\n')
            .map(|position| position + 1)
            .or_else(|| (client.eof && !client.input.is_empty()).then_some(client.input.len()));
        let Some(end) = end else { break };
        let line = match std::str::from_utf8(&client.input[..end]) {
            Ok(line) => line,
            Err(_) => return false,
        };
        let response = handle_ctrl_line(line.trim(), cfg, state, counters, forwarder);
        if client.output.len() + response.len() > MAX_CTRL_OUTPUT {
            return false;
        }
        client.output.extend_from_slice(response.as_bytes());
        client.input.drain(..end);
    }
    if !client.output.is_empty() {
        let end = client.output.len().min(CTRL_IO_BUDGET);
        match client.stream.write(&client.output[..end]) {
            Ok(0) => return false,
            Ok(size) => client.written = size,
            Err(err)
                if matches!(
                    err.kind(),
                    io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted
                ) => {}
            Err(_) => return false,
        }
    }
    !(client.eof && client.input.is_empty() && client.written == client.output.len())
}

fn run() -> Result<(), String> {
    let (cfg, initial_target) = load_config()?;
    let reports = bind_datagram(&cfg.report_socket, cfg.socket_mode)
        .map_err(|err| format!("failed to bind {}: {err}", cfg.report_socket))?;
    let ctrl = bind_listener(&cfg.ctrl_socket, cfg.ctrl_socket_mode)
        .map_err(|err| format!("failed to bind {}: {err}", cfg.ctrl_socket))?;
    let forwarder =
        UnixDatagram::unbound().map_err(|err| format!("failed to create forwarder: {err}"))?;
    forwarder
        .set_nonblocking(true)
        .map_err(|err| format!("failed to configure forwarder: {err}"))?;
    let mut state = RouterState {
        target: initial_target,
        last_error: String::new(),
        bt_reports: [[0; 8]; 2],
        effective: (initial_target != Target::Auto).then_some(initial_target),
        readiness: readiness::Sample {
            usb: readiness::UsbReadiness::Unknown,
            uinput: false,
            reason: "not_sampled",
        },
        pending_usb_neutral: false,
        usb_ready_samples: 0,
    };
    let mut counters = Counters::default();
    let mut processed = 0u64;
    let mut clients = Vec::new();
    let mut last_readiness = Instant::now() - readiness::POLL_INTERVAL;
    write_status(&cfg, &state, &counters);
    loop {
        if last_readiness.elapsed() >= readiness::POLL_INTERVAL {
            refresh_auto(&cfg, &mut state, &mut counters, &forwarder);
            last_readiness = Instant::now();
        }
        handle_ctrl_clients(
            &ctrl,
            &mut clients,
            &cfg,
            &mut state,
            &mut counters,
            &forwarder,
        );
        let mut frame = [0u8; FRAME_SIZE];
        match reports.recv(&mut frame) {
            Ok(size) => {
                match validate_frame(&frame[..size]) {
                    Ok(kind) => {
                        counters.frames_received += 1;
                        forward_to_target(
                            &forwarder,
                            &cfg,
                            &mut state,
                            &mut counters,
                            &frame,
                            kind,
                        );
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
    fn bt_union_rejects_overflow_without_silent_truncation() {
        assert!(merged_keyboard(&[[0, 0, 4, 5, 6, 7, 8, 9], [0, 0, 10, 0, 0, 0, 0, 0]]).is_err());
        assert_eq!(
            merged_keyboard(&[[2, 0, 4, 0, 0, 0, 0, 0], [1, 0, 4, 5, 0, 0, 0, 0]]).unwrap(),
            [3, 0, 4, 5, 0, 0, 0, 0]
        );
    }

    #[test]
    fn partial_neutral_failure_identifies_kind_and_keeps_target() {
        let root = std::env::temp_dir().join(format!("output-partial-{}", std::process::id()));
        fs::create_dir_all(&root).unwrap();
        let path = root.join("usb.sock");
        let receiver = UnixDatagram::bind(&path).unwrap();
        let sender = UnixDatagram::unbound().unwrap();
        sender.set_nonblocking(true).unwrap();
        while sender.send_to(&[0], &path).is_ok() {}
        receiver.recv(&mut [0u8; 1]).unwrap();
        let cfg = Config {
            usb_socket: path.to_str().unwrap().to_string(),
            uidd_socket: root.join("missing.sock").to_str().unwrap().to_string(),
            ..Config::default()
        };
        let mut state = RouterState {
            target: Target::Usb,
            effective: Some(Target::Usb),
            last_error: String::new(),
            bt_reports: [[0; 8]; 2],
            readiness: readiness::Sample {
                usb: readiness::UsbReadiness::Ready,
                uinput: false,
                reason: "fixture",
            },
            pending_usb_neutral: false,
            usb_ready_samples: 2,
        };
        let response: serde_json::Value = serde_json::from_str(&handle_ctrl_line(
            "{\"t\":\"set_output_target\",\"target\":\"uinput\"}",
            &cfg,
            &mut state,
            &mut Counters::default(),
            &sender,
        ))
        .unwrap();
        assert_eq!(response["result"], "error");
        assert_eq!(response["release"]["delivered"], 1);
        assert_eq!(response["release"]["errors"], 5);
        assert_eq!(
            response["release"]["failed"][0]["kind"],
            KIND_US_SUB_KEYBOARD
        );
        assert_eq!(state.effective, Some(Target::Usb));
        assert_eq!(state.target, Target::Usb);
        fs::remove_dir_all(root).unwrap();
    }

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
