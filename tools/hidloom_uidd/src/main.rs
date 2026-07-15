use std::collections::HashSet;
use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::os::fd::AsRawFd;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixDatagram;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

const FRAME_SIZE: usize = 64;
const CHECKSUM_OFFSET: usize = 63;
const PAYLOAD_OFFSET: usize = 8;
const KIND_KEYBOARD: u8 = 0x01;
const KIND_US_SUB_KEYBOARD: u8 = 0x04;

const EV_KEY: u16 = 0x01;
const EV_SYN: u16 = 0x00;
const EV_REP: u16 = 0x14;
const SYN_REPORT: u16 = 0x00;
const BUS_USB: u16 = 0x03;

const UI_SET_EVBIT: usize = 0x40045564;
const UI_SET_KEYBIT: usize = 0x40045565;
const UI_DEV_CREATE: usize = 0x5501;
const UI_DEV_DESTROY: usize = 0x5502;

unsafe extern "C" {
    fn ioctl(fd: i32, request: usize, ...) -> i32;
}

#[derive(Clone)]
struct Config {
    socket_path: String,
    socket_mode: u32,
    status_path: String,
    event_log_path: String,
    uinput_path: String,
    device_name: String,
    vendor_id: u16,
    product_id: u16,
    repeat_delay_ms: i32,
    repeat_period_ms: i32,
    dry_run: bool,
    exit_after_frames: Option<u64>,
}

#[derive(Default)]
struct Counters {
    frames_received: u64,
    keyboard_reports: u64,
    us_sub_keyboard_reports: u64,
    invalid_frames: u64,
    unsupported_frames: u64,
    key_events: u64,
    sync_events: u64,
    dropped_events: u64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct InputEvent {
    event_type: u16,
    code: u16,
    value: i32,
}

#[derive(Default)]
struct KeyboardDiff {
    pressed: HashSet<u16>,
}

struct EventSink {
    file: Option<File>,
    open: bool,
    last_error: String,
}

impl KeyboardDiff {
    fn apply_report(&mut self, report: &[u8; 8]) -> Vec<InputEvent> {
        let mut current = HashSet::new();
        for bit in 0..8 {
            if report[0] & (1 << bit) != 0 {
                if let Some(code) = modifier_bit_to_linux(bit) {
                    current.insert(code);
                }
            }
        }
        for usage in report[2..8].iter().copied().filter(|usage| *usage != 0) {
            if let Some(code) = hid_usage_to_linux(usage) {
                current.insert(code);
            }
        }

        let mut events = Vec::new();
        let mut releases: Vec<u16> = self.pressed.difference(&current).copied().collect();
        let mut presses: Vec<u16> = current.difference(&self.pressed).copied().collect();
        releases.sort_by_key(|code| (if is_modifier_linux_key(*code) { 1 } else { 0 }, *code));
        presses.sort_by_key(|code| (if is_modifier_linux_key(*code) { 0 } else { 1 }, *code));
        for code in releases {
            events.push(InputEvent {
                event_type: EV_KEY,
                code,
                value: 0,
            });
        }
        for code in presses {
            events.push(InputEvent {
                event_type: EV_KEY,
                code,
                value: 1,
            });
        }
        if !events.is_empty() {
            events.push(InputEvent {
                event_type: EV_SYN,
                code: SYN_REPORT,
                value: 0,
            });
        }
        self.pressed = current;
        events
    }
}

fn modifier_bit_to_linux(bit: u8) -> Option<u16> {
    match bit {
        0 => Some(29),  // KEY_LEFTCTRL
        1 => Some(42),  // KEY_LEFTSHIFT
        2 => Some(56),  // KEY_LEFTALT
        3 => Some(125), // KEY_LEFTMETA
        4 => Some(97),  // KEY_RIGHTCTRL
        5 => Some(54),  // KEY_RIGHTSHIFT
        6 => Some(100), // KEY_RIGHTALT
        7 => Some(126), // KEY_RIGHTMETA
        _ => None,
    }
}

fn hid_usage_to_linux(usage: u8) -> Option<u16> {
    match usage {
        0x04 => Some(30),
        0x05 => Some(48),
        0x06 => Some(46),
        0x07 => Some(32),
        0x08 => Some(18),
        0x09 => Some(33),
        0x0a => Some(34),
        0x0b => Some(35),
        0x0c => Some(23),
        0x0d => Some(36),
        0x0e => Some(37),
        0x0f => Some(38),
        0x10 => Some(50),
        0x11 => Some(49),
        0x12 => Some(24),
        0x13 => Some(25),
        0x14 => Some(16),
        0x15 => Some(19),
        0x16 => Some(31),
        0x17 => Some(20),
        0x18 => Some(22),
        0x19 => Some(47),
        0x1a => Some(17),
        0x1b => Some(45),
        0x1c => Some(21),
        0x1d => Some(44),
        0x1e => Some(2),
        0x1f => Some(3),
        0x20 => Some(4),
        0x21 => Some(5),
        0x22 => Some(6),
        0x23 => Some(7),
        0x24 => Some(8),
        0x25 => Some(9),
        0x26 => Some(10),
        0x27 => Some(11),
        0x28 => Some(28),
        0x29 => Some(1),
        0x2a => Some(14),
        0x2b => Some(15),
        0x2c => Some(57),
        0x2d => Some(12),
        0x2e => Some(13),
        0x2f => Some(26),
        0x30 => Some(27),
        0x31 | 0x32 => Some(43),
        0x33 => Some(39),
        0x34 => Some(40),
        0x35 => Some(41),
        0x36 => Some(51),
        0x37 => Some(52),
        0x38 => Some(53),
        0x39 => Some(58),
        0x3a..=0x41 => Some(59 + u16::from(usage - 0x3a)),
        0x42 => Some(66),
        0x43 => Some(67),
        0x44 => Some(68),
        0x45 => Some(87),
        0x46 => Some(88),
        0x49 => Some(110),
        0x4a => Some(102),
        0x4b => Some(104),
        0x4c => Some(111),
        0x4d => Some(107),
        0x4e => Some(109),
        0x4f => Some(106),
        0x50 => Some(105),
        0x51 => Some(108),
        0x52 => Some(103),
        _ => None,
    }
}

fn supported_linux_keys() -> Vec<u16> {
    let mut keys = HashSet::new();
    for bit in 0..8 {
        if let Some(code) = modifier_bit_to_linux(bit) {
            keys.insert(code);
        }
    }
    for usage in 0u8..=0xff {
        if let Some(code) = hid_usage_to_linux(usage) {
            keys.insert(code);
        }
    }
    let mut keys: Vec<u16> = keys.into_iter().collect();
    keys.sort_unstable();
    keys
}

fn is_modifier_linux_key(code: u16) -> bool {
    matches!(code, 29 | 42 | 56 | 125 | 97 | 54 | 100 | 126)
}

fn env_string(name: &str, default: &str) -> String {
    env::var(name)
        .ok()
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| default.to_string())
}

fn env_bool(name: &str, default: bool) -> bool {
    env::var(name)
        .ok()
        .map(|value| matches!(value.as_str(), "1" | "true" | "TRUE" | "yes" | "on"))
        .unwrap_or(default)
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

fn env_i32(name: &str, default: i32, min: i32, max: i32) -> i32 {
    env::var(name)
        .ok()
        .and_then(|raw| raw.parse::<i32>().ok())
        .filter(|value| *value >= min && *value <= max)
        .unwrap_or(default)
}

fn load_config() -> Result<Config, String> {
    let mut exit_after_frames = None;
    let mut args = env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--frames" => {
                let raw = args.next().ok_or("--frames requires a value")?;
                exit_after_frames = Some(raw.parse::<u64>().map_err(|_| "invalid --frames value")?);
            }
            "--help" => {
                println!("usage: hidloom-uidd [--frames N]");
                std::process::exit(0);
            }
            _ => return Err(format!("unknown argument: {arg}")),
        }
    }
    Ok(Config {
        socket_path: env_string("UIDD_REPORT_SOCKET", "/tmp/uidd_reports.sock"),
        socket_mode: env_u32("UIDD_REPORT_SOCKET_MODE", 0o666, 0, 0o777),
        status_path: env_string("UIDD_STATUS_PATH", "/run/hidloom/uidd-status.json"),
        event_log_path: env_string("UIDD_EVENT_LOG_PATH", ""),
        uinput_path: env_string("UIDD_UINPUT_PATH", "/dev/uinput"),
        device_name: env_string("UIDD_DEVICE_NAME", "CQA02303v5 Local Console Keyboard"),
        vendor_id: env_u32("UIDD_VENDOR_ID", 0x1234, 0, 0xffff) as u16,
        product_id: env_u32("UIDD_PRODUCT_ID", 0x5678, 0, 0xffff) as u16,
        repeat_delay_ms: env_i32("UIDD_REPEAT_DELAY_MS", 500, 0, 60_000),
        repeat_period_ms: env_i32("UIDD_REPEAT_PERIOD_MS", 100, 1, 60_000),
        dry_run: env_bool("UIDD_DRY_RUN", true),
        exit_after_frames,
    })
}

fn ioctl_result(fd: i32, request: usize, value: i32) -> io::Result<()> {
    let result = unsafe { ioctl(fd, request, value) };
    if result < 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(())
    }
}

fn ioctl_no_arg(fd: i32, request: usize) -> io::Result<()> {
    let result = unsafe { ioctl(fd, request) };
    if result < 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(())
    }
}

fn push_u16(out: &mut Vec<u8>, value: u16) {
    out.extend_from_slice(&value.to_ne_bytes());
}

fn push_i32(out: &mut Vec<u8>, value: i32) {
    out.extend_from_slice(&value.to_ne_bytes());
}

fn build_uinput_user_dev(cfg: &Config) -> Vec<u8> {
    let mut out = Vec::with_capacity(1116);
    let mut name = [0u8; 80];
    let bytes = cfg.device_name.as_bytes();
    let len = bytes.len().min(79);
    name[..len].copy_from_slice(&bytes[..len]);
    out.extend_from_slice(&name);
    push_u16(&mut out, BUS_USB);
    push_u16(&mut out, cfg.vendor_id);
    push_u16(&mut out, cfg.product_id);
    push_u16(&mut out, 1);
    push_i32(&mut out, 0);
    for _ in 0..(64 * 4) {
        push_i32(&mut out, 0);
    }
    out
}

impl EventSink {
    fn new(cfg: &Config) -> Self {
        if cfg.dry_run {
            return Self {
                file: None,
                open: false,
                last_error: "dry_run".to_string(),
            };
        }
        match Self::open_uinput(cfg) {
            Ok(file) => Self {
                file: Some(file),
                open: true,
                last_error: String::new(),
            },
            Err(err) => Self {
                file: None,
                open: false,
                last_error: err,
            },
        }
    }

    fn open_uinput(cfg: &Config) -> Result<File, String> {
        let mut file = OpenOptions::new()
            .write(true)
            .open(&cfg.uinput_path)
            .map_err(|err| format!("failed to open {}: {err}", cfg.uinput_path))?;
        let fd = file.as_raw_fd();
        ioctl_result(fd, UI_SET_EVBIT, i32::from(EV_KEY))
            .map_err(|err| format!("UI_SET_EVBIT EV_KEY failed: {err}"))?;
        ioctl_result(fd, UI_SET_EVBIT, i32::from(EV_SYN))
            .map_err(|err| format!("UI_SET_EVBIT EV_SYN failed: {err}"))?;
        ioctl_result(fd, UI_SET_EVBIT, i32::from(EV_REP))
            .map_err(|err| format!("UI_SET_EVBIT EV_REP failed: {err}"))?;
        for key in supported_linux_keys() {
            ioctl_result(fd, UI_SET_KEYBIT, i32::from(key))
                .map_err(|err| format!("UI_SET_KEYBIT {key} failed: {err}"))?;
        }
        let dev = build_uinput_user_dev(cfg);
        file.write_all(&dev)
            .map_err(|err| format!("failed to write uinput_user_dev: {err}"))?;
        ioctl_no_arg(fd, UI_DEV_CREATE).map_err(|err| format!("UI_DEV_CREATE failed: {err}"))?;
        let _ = write_input_event(&mut file, EV_REP, 0, cfg.repeat_delay_ms);
        let _ = write_input_event(&mut file, EV_REP, 1, cfg.repeat_period_ms);
        let _ = write_input_event(&mut file, EV_SYN, SYN_REPORT, 0);
        Ok(file)
    }

    fn write(&mut self, event: InputEvent) -> Result<(), String> {
        let Some(file) = self.file.as_mut() else {
            return Ok(());
        };
        write_input_event(file, event.event_type, event.code, event.value)
            .map_err(|err| format!("failed to write uinput event: {err}"))
    }
}

impl Drop for EventSink {
    fn drop(&mut self) {
        if let Some(file) = self.file.as_ref() {
            let _ = ioctl_no_arg(file.as_raw_fd(), UI_DEV_DESTROY);
        }
    }
}

fn write_input_event(file: &mut File, event_type: u16, code: u16, value: i32) -> io::Result<()> {
    let mut bytes = Vec::with_capacity(if cfg!(target_pointer_width = "32") { 16 } else { 24 });
    #[cfg(target_pointer_width = "32")]
    {
        bytes.extend_from_slice(&0i32.to_ne_bytes());
        bytes.extend_from_slice(&0i32.to_ne_bytes());
    }
    #[cfg(not(target_pointer_width = "32"))]
    {
        bytes.extend_from_slice(&0i64.to_ne_bytes());
        bytes.extend_from_slice(&0i64.to_ne_bytes());
    }
    bytes.extend_from_slice(&event_type.to_ne_bytes());
    bytes.extend_from_slice(&code.to_ne_bytes());
    bytes.extend_from_slice(&value.to_ne_bytes());
    file.write_all(&bytes)
}

fn xor_checksum(data: &[u8]) -> u8 {
    data.iter().fold(0u8, |acc, byte| acc ^ byte)
}

fn decode_frame(frame: &[u8]) -> Result<(u8, [u8; 8]), String> {
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
    if kind != KIND_KEYBOARD && kind != KIND_US_SUB_KEYBOARD {
        return Err("unsupported kind".to_string());
    }
    if frame[6] != 8 {
        return Err("invalid keyboard payload length".to_string());
    }
    if frame[PAYLOAD_OFFSET + 8..CHECKSUM_OFFSET]
        .iter()
        .any(|byte| *byte != 0)
    {
        return Err("reserved payload bytes must be zero".to_string());
    }
    let mut report = [0u8; 8];
    report.copy_from_slice(&frame[PAYLOAD_OFFSET..PAYLOAD_OFFSET + 8]);
    Ok((kind, report))
}

fn now_unix_us() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_micros()
}

fn json_escape(value: &str) -> String {
    value
        .replace('\\', "\\\\")
        .replace('"', "\\\"")
        .replace('\n', "\\n")
        .replace('\r', "\\r")
}

fn log_event(cfg: &Config, event: InputEvent) {
    if cfg.event_log_path.is_empty() {
        return;
    }
    if let Some(parent) = Path::new(&cfg.event_log_path).parent() {
        let _ = fs::create_dir_all(parent);
    }
    let line = format!(
        "{{\"t\":\"uidd_input_event\",\"unix_us\":{},\"type\":{},\"code\":{},\"value\":{}}}\n",
        now_unix_us(),
        event.event_type,
        event.code,
        event.value
    );
    if let Ok(mut file) = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&cfg.event_log_path)
    {
        let _ = file.write_all(line.as_bytes());
    }
}

fn write_status(cfg: &Config, counters: &Counters, sink: &EventSink, last_error: &str) {
    if cfg.status_path.is_empty() {
        return;
    }
    if let Some(parent) = Path::new(&cfg.status_path).parent() {
        let _ = fs::create_dir_all(parent);
    }
    let payload = format!(
        concat!(
            "{{",
            "\"schema\":\"hidloom.uidd.status.v1\",",
            "\"process\":true,",
            "\"dry_run\":{},",
            "\"socket\":{{\"path\":\"{}\",\"listening\":true}},",
            "\"uinput\":{{\"path\":\"{}\",\"open\":{},\"last_error\":\"{}\"}},",
            "\"counters\":{{",
            "\"frames_received\":{},",
            "\"keyboard_reports\":{},",
            "\"us_sub_keyboard_reports\":{},",
            "\"invalid_frames\":{},",
            "\"unsupported_frames\":{},",
            "\"key_events\":{},",
            "\"sync_events\":{},",
            "\"dropped_events\":{}",
            "}}",
            "}}\n"
        ),
        if cfg.dry_run { "true" } else { "false" },
        json_escape(&cfg.socket_path),
        json_escape(&cfg.uinput_path),
        if sink.open { "true" } else { "false" },
        json_escape(if last_error.is_empty() {
            &sink.last_error
        } else {
            last_error
        }),
        counters.frames_received,
        counters.keyboard_reports,
        counters.us_sub_keyboard_reports,
        counters.invalid_frames,
        counters.unsupported_frames,
        counters.key_events,
        counters.sync_events,
        counters.dropped_events
    );
    let tmp_path = format!("{}.tmp", cfg.status_path);
    if fs::write(&tmp_path, payload).is_ok() {
        let _ = fs::rename(tmp_path, &cfg.status_path);
    }
}

fn bind_socket(path: &str, mode: u32) -> io::Result<UnixDatagram> {
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
    Ok(socket)
}

fn run() -> Result<(), String> {
    let cfg = load_config()?;
    let socket = bind_socket(&cfg.socket_path, cfg.socket_mode)
        .map_err(|err| format!("failed to bind {}: {err}", cfg.socket_path))?;
    let mut counters = Counters::default();
    let mut diff = KeyboardDiff::default();
    let mut sink = EventSink::new(&cfg);
    let mut processed = 0u64;
    let mut last_error = String::new();
    write_status(&cfg, &counters, &sink, &last_error);

    loop {
        let mut frame = [0u8; FRAME_SIZE];
        let size = socket
            .recv(&mut frame)
            .map_err(|err| format!("failed to receive frame: {err}"))?;
        match decode_frame(&frame[..size]) {
            Ok((kind, report)) => {
                counters.frames_received += 1;
                if kind == KIND_KEYBOARD {
                    counters.keyboard_reports += 1;
                } else {
                    counters.us_sub_keyboard_reports += 1;
                }
                for event in diff.apply_report(&report) {
                    if event.event_type == EV_SYN {
                        counters.sync_events += 1;
                    } else {
                        counters.key_events += 1;
                    }
                    log_event(&cfg, event);
                    if let Err(err) = sink.write(event) {
                        counters.dropped_events += 1;
                        sink.last_error = err;
                    }
                }
                last_error.clear();
            }
            Err(err) if err == "unsupported kind" => {
                counters.unsupported_frames += 1;
                last_error = err;
            }
            Err(err) => {
                counters.invalid_frames += 1;
                last_error = err;
            }
        }
        processed += 1;
        write_status(&cfg, &counters, &sink, &last_error);
        if cfg
            .exit_after_frames
            .is_some_and(|limit| processed >= limit)
        {
            break;
        }
    }
    let _ = fs::remove_file(&cfg.socket_path);
    write_status(&cfg, &counters, &sink, &last_error);
    Ok(())
}

fn main() {
    if let Err(err) = run() {
        eprintln!("hidloom-uidd: {err}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn report_diff_presses_and_releases_keys() {
        let mut diff = KeyboardDiff::default();
        assert_eq!(
            diff.apply_report(&[0, 0, 4, 0, 0, 0, 0, 0]),
            vec![
                InputEvent {
                    event_type: EV_KEY,
                    code: 30,
                    value: 1,
                },
                InputEvent {
                    event_type: EV_SYN,
                    code: SYN_REPORT,
                    value: 0,
                },
            ]
        );
        assert_eq!(diff.apply_report(&[0, 0, 4, 0, 0, 0, 0, 0]), Vec::new());
        assert_eq!(
            diff.apply_report(&[0, 0, 0, 0, 0, 0, 0, 0]),
            vec![
                InputEvent {
                    event_type: EV_KEY,
                    code: 30,
                    value: 0,
                },
                InputEvent {
                    event_type: EV_SYN,
                    code: SYN_REPORT,
                    value: 0,
                },
            ]
        );
    }

    #[test]
    fn modifier_only_report_is_diffed() {
        let mut diff = KeyboardDiff::default();
        assert_eq!(
            diff.apply_report(&[0x02, 0, 0, 0, 0, 0, 0, 0]),
            vec![
                InputEvent {
                    event_type: EV_KEY,
                    code: 42,
                    value: 1,
                },
                InputEvent {
                    event_type: EV_SYN,
                    code: SYN_REPORT,
                    value: 0,
                },
            ]
        );
    }
}
