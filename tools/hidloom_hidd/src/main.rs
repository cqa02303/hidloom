use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::os::unix::fs::{FileTypeExt, PermissionsExt};
use std::os::unix::net::{UnixDatagram, UnixStream};
use std::path::Path;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

const FRAME_SIZE: usize = 64;
const CHECKSUM_OFFSET: usize = 63;
const PAYLOAD_OFFSET: usize = 8;
const PAYLOAD_CAPACITY: usize = 24;

const KIND_KEYBOARD: u8 = 0x01;
const KIND_MOUSE: u8 = 0x02;
const KIND_CONSUMER: u8 = 0x03;
const KIND_US_SUB_KEYBOARD: u8 = 0x04;

const REPORT_ID_KEYBOARD: u8 = 0x01;
const REPORT_ID_MOUSE: u8 = 0x02;
const REPORT_ID_CONSUMER: u8 = 0x03;

#[derive(Clone)]
struct Config {
    socket_path: String,
    hidg0_path: String,
    hidg2_path: String,
    status_path: String,
    socket_mode: u32,
    write_retry_timeout: Duration,
    write_retry_interval: Duration,
    mouse_report_hz: f64,
    keyboard_report_hz: f64,
    keyboard_dedup: bool,
    keyboard_startup_release: bool,
    keyboard_startup_release_retry_interval: Duration,
    keyboard_release_merge_window: Duration,
    raw_hid_bridge_enabled: bool,
    raw_hid_path: String,
    viald_socket_path: String,
    raw_hid_report_size: usize,
    raw_hid_retry_interval: Duration,
    frame_log_path: String,
    exit_after_frames: Option<u64>,
}

#[derive(Default)]
struct Counters {
    frames_received: u64,
    keyboard_reports: u64,
    us_sub_keyboard_reports: u64,
    startup_release_reports: u64,
    mouse_reports: u64,
    consumer_reports: u64,
    invalid_frames: u64,
    write_errors: u64,
    dropped_reports: u64,
}

struct RawBridgeStatus {
    enabled: bool,
    path: String,
    viald_socket_path: String,
    open: bool,
    connected: bool,
    last_error: String,
    packets: u64,
    resets: u64,
}

struct Endpoint {
    path: String,
    file: Option<File>,
    last_error: String,
    reopens: u64,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum EndpointId {
    Hidg0,
    Hidg2,
}

fn endpoint_name(endpoint: EndpointId) -> &'static str {
    match endpoint {
        EndpointId::Hidg0 => "hidg0",
        EndpointId::Hidg2 => "hidg2",
    }
}

#[derive(Clone)]
struct UsbReport {
    endpoint: EndpointId,
    report: Vec<u8>,
    kind: u8,
}

struct HidRequest {
    kind: u8,
    payload: Vec<u8>,
}

struct KeyboardRoute {
    pending: Option<(UsbReport, Instant, [u8; 6], u8)>,
    last_keys: [u8; 6],
    last_modifiers: u8,
    last_report: Vec<u8>,
    next_write: Instant,
}

struct MouseScheduler {
    initialized: bool,
    endpoint: EndpointId,
    report_id: u8,
    buttons: u8,
    dx: i32,
    dy: i32,
    wheel: i32,
    next_flush: Instant,
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

fn env_usize(name: &str, default: usize, min: usize, max: usize) -> usize {
    env::var(name)
        .ok()
        .and_then(|raw| raw.parse::<usize>().ok())
        .filter(|value| *value >= min && *value <= max)
        .unwrap_or(default)
}

fn env_f64(name: &str, default: f64, min: f64) -> f64 {
    env::var(name)
        .ok()
        .and_then(|raw| raw.parse::<f64>().ok())
        .filter(|value| *value >= min)
        .unwrap_or(default)
}

fn duration_secs(value: f64) -> Duration {
    Duration::from_secs_f64(value.max(0.0))
}

fn now_unix_us() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_micros()
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn log_frame_event(cfg: &Config, event: &str, fields: &str) {
    if cfg.frame_log_path.is_empty() {
        return;
    }
    if let Some(parent) = Path::new(&cfg.frame_log_path).parent() {
        let _ = fs::create_dir_all(parent);
    }
    let line = if fields.is_empty() {
        format!(
            "{{\"t\":\"{}\",\"unix_us\":{}}}\n",
            json_escape(event),
            now_unix_us()
        )
    } else {
        format!(
            "{{\"t\":\"{}\",\"unix_us\":{}, {}}}\n",
            json_escape(event),
            now_unix_us(),
            fields
        )
    };
    if let Ok(mut file) = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&cfg.frame_log_path)
    {
        let _ = file.write_all(line.as_bytes());
    }
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
                println!("usage: hidloom-hidd [--frames N]");
                std::process::exit(0);
            }
            _ => return Err(format!("unknown argument: {arg}")),
        }
    }

    Ok(Config {
        socket_path: env_string("USBD_HID_REPORT_SOCKET", "/tmp/usbd_hid_reports.sock"),
        hidg0_path: env_string("USBD_HID_REPORT_PATH", "/dev/hidg0"),
        hidg2_path: env_string("USBD_US_SUB_HID_REPORT_PATH", "/dev/hidg2"),
        status_path: env_string("HIDD_STATUS_PATH", "/run/hidloom/hidd-status.json"),
        socket_mode: env_u32("HIDD_SOCKET_MODE", 0o666, 0, 0o777),
        write_retry_timeout: duration_secs(env_f64("USBD_HID_WRITE_RETRY_TIMEOUT_SEC", 0.25, 0.0)),
        write_retry_interval: duration_secs(env_f64(
            "USBD_HID_WRITE_RETRY_INTERVAL_SEC",
            0.002,
            0.0,
        )),
        mouse_report_hz: env_f64("USBD_MOUSE_REPORT_HZ", 125.0, 1.0),
        keyboard_report_hz: env_f64("USBD_KEYBOARD_REPORT_HZ", 500.0, 1.0),
        keyboard_dedup: env_u32("USBD_KEYBOARD_REPORT_DEDUP", 1, 0, 1) != 0,
        keyboard_startup_release: env_u32("USBD_KEYBOARD_STARTUP_RELEASE", 1, 0, 1) != 0,
        keyboard_startup_release_retry_interval: duration_secs(env_f64(
            "USBD_KEYBOARD_STARTUP_RELEASE_RETRY_SEC",
            0.05,
            0.001,
        )),
        keyboard_release_merge_window: duration_secs(env_f64(
            "USBD_KEYBOARD_RELEASE_MERGE_WINDOW_SEC",
            0.016,
            0.0,
        )),
        raw_hid_bridge_enabled: env_u32("HIDD_RAW_HID_BRIDGE_ENABLED", 1, 0, 1) != 0,
        raw_hid_path: env_string("USBD_RAW_HID_PATH", "/dev/hidg1"),
        viald_socket_path: env_string("VIALD_EVENTS_SOCK", "/tmp/viald_events.sock"),
        raw_hid_report_size: env_usize("USBD_REPORT_SIZE", 32, 1, 1024),
        raw_hid_retry_interval: duration_secs(env_f64("USBD_RETRY_SEC", 1.0, 0.05)),
        frame_log_path: env_string("HIDD_FRAME_LOG_PATH", ""),
        exit_after_frames,
    })
}

fn expected_payload_len(kind: u8) -> Option<usize> {
    match kind {
        KIND_KEYBOARD => Some(8),
        KIND_MOUSE => Some(4),
        KIND_CONSUMER => Some(2),
        KIND_US_SUB_KEYBOARD => Some(8),
        _ => None,
    }
}

fn xor_checksum(data: &[u8]) -> u8 {
    data.iter().fold(0u8, |acc, byte| acc ^ byte)
}

fn decode_frame(frame: &[u8]) -> Result<HidRequest, String> {
    if frame.len() != FRAME_SIZE {
        return Err(format!("invalid size: {}", frame.len()));
    }
    if &frame[0..4] != b"CQAU" {
        return Err("invalid magic".to_string());
    }
    if frame[4] != 0x01 {
        return Err("invalid version".to_string());
    }
    if xor_checksum(&frame[..CHECKSUM_OFFSET]) != frame[CHECKSUM_OFFSET] {
        return Err("invalid checksum".to_string());
    }
    let kind = frame[5];
    let payload_len = frame[6] as usize;
    let expected = expected_payload_len(kind).ok_or_else(|| "unsupported kind".to_string())?;
    if payload_len != expected || payload_len > PAYLOAD_CAPACITY {
        return Err("invalid payload length".to_string());
    }
    if frame[PAYLOAD_OFFSET + payload_len..CHECKSUM_OFFSET]
        .iter()
        .any(|byte| *byte != 0)
    {
        return Err("reserved bytes must be zero".to_string());
    }
    Ok(HidRequest {
        kind,
        payload: frame[PAYLOAD_OFFSET..PAYLOAD_OFFSET + payload_len].to_vec(),
    })
}

fn adapt_report(request: &HidRequest) -> UsbReport {
    match request.kind {
        KIND_KEYBOARD => {
            let mut report = vec![REPORT_ID_KEYBOARD];
            report.extend_from_slice(&request.payload);
            UsbReport {
                endpoint: EndpointId::Hidg0,
                report,
                kind: request.kind,
            }
        }
        KIND_MOUSE => {
            let mut report = vec![REPORT_ID_MOUSE];
            report.extend_from_slice(&request.payload);
            UsbReport {
                endpoint: EndpointId::Hidg0,
                report,
                kind: request.kind,
            }
        }
        KIND_CONSUMER => {
            let mut report = vec![REPORT_ID_CONSUMER];
            report.extend_from_slice(&request.payload);
            UsbReport {
                endpoint: EndpointId::Hidg0,
                report,
                kind: request.kind,
            }
        }
        KIND_US_SUB_KEYBOARD => UsbReport {
            endpoint: EndpointId::Hidg2,
            report: request.payload.clone(),
            kind: request.kind,
        },
        _ => unreachable!(),
    }
}

impl Endpoint {
    fn new(path: String) -> Self {
        Self {
            path,
            file: None,
            last_error: String::new(),
            reopens: 0,
        }
    }

    fn ensure_open(&mut self) -> io::Result<()> {
        if self.file.is_some() {
            return Ok(());
        }
        match OpenOptions::new().write(true).open(&self.path) {
            Ok(file) => {
                self.file = Some(file);
                self.last_error.clear();
                self.reopens += 1;
                Ok(())
            }
            Err(err) => {
                self.last_error = format!("open: {err}");
                Err(err)
            }
        }
    }

    fn close(&mut self) {
        self.file = None;
    }

    fn write_report(&mut self, report: &[u8], cfg: &Config, counters: &mut Counters) -> bool {
        let deadline = Instant::now() + cfg.write_retry_timeout;
        loop {
            match self.ensure_open().and_then(|_| {
                self.file
                    .as_mut()
                    .expect("file must be open")
                    .write_all(report)
            }) {
                Ok(()) => return true,
                Err(err) => {
                    self.last_error = format!("write: {err}");
                    self.close();
                    if Instant::now() >= deadline {
                        break;
                    }
                    if !cfg.write_retry_interval.is_zero() {
                        thread::sleep(cfg.write_retry_interval);
                    }
                }
            }
        }
        counters.write_errors += 1;
        counters.dropped_reports += 1;
        false
    }

    fn write_startup_release(&mut self, report: &[u8], cfg: &Config) {
        loop {
            match self.ensure_open().and_then(|_| {
                self.file
                    .as_mut()
                    .expect("file must be open")
                    .write_all(report)
            }) {
                Ok(()) => {
                    self.last_error.clear();
                    return;
                }
                Err(err) => {
                    self.last_error = format!("startup release write: {err}");
                    self.close();
                    thread::sleep(cfg.keyboard_startup_release_retry_interval);
                }
            }
        }
    }
}

impl KeyboardRoute {
    fn new() -> Self {
        Self {
            pending: None,
            last_keys: [0; 6],
            last_modifiers: 0,
            last_report: Vec::new(),
            next_write: Instant::now(),
        }
    }

    fn flush_if_due(
        &mut self,
        cfg: &Config,
        endpoints: &mut Endpoints,
        counters: &mut Counters,
        force: bool,
    ) {
        let Some((report, deadline, _, _)) = self.pending.clone() else {
            return;
        };
        if !force && Instant::now() < deadline {
            return;
        }
        self.pending = None;
        self.last_keys = [0; 6];
        self.last_modifiers = 0;
        log_frame_event(
            cfg,
            "hidd_keyboard_release_flush",
            &format!(
                "\"endpoint\":\"{}\",\"force\":{},\"report\":\"{}\"",
                endpoint_name(report.endpoint),
                force,
                hex(&report.report)
            ),
        );
        self.write_paced(&report, cfg, endpoints, counters);
    }

    fn enqueue(
        &mut self,
        report: UsbReport,
        cfg: &Config,
        endpoints: &mut Endpoints,
        counters: &mut Counters,
    ) {
        if keyboard_is_release(&report) {
            self.flush_if_due(cfg, endpoints, counters, false);
            log_frame_event(
                cfg,
                "hidd_keyboard_release_pending",
                &format!(
                    "\"endpoint\":\"{}\",\"report\":\"{}\",\"window_us\":{}",
                    endpoint_name(report.endpoint),
                    hex(&report.report),
                    cfg.keyboard_release_merge_window.as_micros()
                ),
            );
            self.pending = Some((
                report,
                Instant::now() + cfg.keyboard_release_merge_window,
                self.last_keys,
                self.last_modifiers,
            ));
            return;
        }

        let (new_keys, new_modifiers) = keyboard_keys_and_modifiers(&report);
        if let Some((pending_report, _, previous_keys, previous_modifiers)) = self.pending.take() {
            let modifier_only_overlap = previous_keys.iter().all(|key| *key == 0)
                && new_keys.iter().all(|key| *key == 0)
                && (previous_modifiers & new_modifiers) != 0;
            let key_overlap = previous_keys
                .iter()
                .any(|key| *key != 0 && new_keys.contains(key));
            if key_overlap || modifier_only_overlap {
                log_frame_event(
                    cfg,
                    "hidd_keyboard_release_preserved",
                    &format!(
                        "\"endpoint\":\"{}\",\"release\":\"{}\",\"next_report\":\"{}\",\"previous_modifiers\":{},\"next_modifiers\":{},\"previous_keys\":\"{}\",\"next_keys\":\"{}\"",
                        endpoint_name(report.endpoint),
                        hex(&pending_report.report),
                        hex(&report.report),
                        previous_modifiers,
                        new_modifiers,
                        hex(&previous_keys),
                        hex(&new_keys)
                    ),
                );
                self.write_paced(&pending_report, cfg, endpoints, counters);
            } else {
                log_frame_event(
                    cfg,
                    "hidd_keyboard_release_merged",
                    &format!(
                        "\"endpoint\":\"{}\",\"dropped_release\":\"{}\",\"next_report\":\"{}\",\"previous_modifiers\":{},\"next_modifiers\":{},\"previous_keys\":\"{}\",\"next_keys\":\"{}\"",
                        endpoint_name(report.endpoint),
                        hex(&pending_report.report),
                        hex(&report.report),
                        previous_modifiers,
                        new_modifiers,
                        hex(&previous_keys),
                        hex(&new_keys)
                    ),
                );
            }
        }

        self.write_paced(&report, cfg, endpoints, counters);
        self.last_keys = new_keys;
        self.last_modifiers = new_modifiers;
    }

    fn write_paced(
        &mut self,
        report: &UsbReport,
        cfg: &Config,
        endpoints: &mut Endpoints,
        counters: &mut Counters,
    ) {
        if cfg.keyboard_dedup && self.last_report == report.report {
            log_frame_event(
                cfg,
                "hidd_keyboard_dedup_drop",
                &format!(
                    "\"endpoint\":\"{}\",\"report\":\"{}\"",
                    endpoint_name(report.endpoint),
                    hex(&report.report)
                ),
            );
            return;
        }
        let now = Instant::now();
        if self.next_write > now {
            thread::sleep(self.next_write - now);
        }
        log_frame_event(
            cfg,
            "hidd_keyboard_write",
            &format!(
                "\"endpoint\":\"{}\",\"report\":\"{}\"",
                endpoint_name(report.endpoint),
                hex(&report.report)
            ),
        );
        write_usb_report(report, cfg, endpoints, counters);
        self.last_report = report.report.clone();
        self.next_write = Instant::now() + Duration::from_secs_f64(1.0 / cfg.keyboard_report_hz);
    }

    fn time_until_flush(&self) -> Duration {
        let Some((_, deadline, _, _)) = &self.pending else {
            return Duration::from_millis(500);
        };
        deadline.saturating_duration_since(Instant::now())
    }
}

impl MouseScheduler {
    fn new() -> Self {
        Self {
            initialized: false,
            endpoint: EndpointId::Hidg0,
            report_id: REPORT_ID_MOUSE,
            buttons: 0,
            dx: 0,
            dy: 0,
            wheel: 0,
            next_flush: Instant::now(),
        }
    }

    fn enqueue(
        &mut self,
        report: &UsbReport,
        cfg: &Config,
        endpoints: &mut Endpoints,
        counters: &mut Counters,
    ) {
        if report.report.len() != 5 {
            return;
        }
        let buttons = report.report[1];
        let dx = signed_i8(report.report[2]);
        let dy = signed_i8(report.report[3]);
        let wheel = signed_i8(report.report[4]);

        if !self.initialized {
            self.initialized = true;
            self.endpoint = report.endpoint;
            self.report_id = report.report[0];
            self.buttons = buttons;
            self.next_flush = Instant::now();
        } else if buttons != self.buttons {
            self.flush(cfg, endpoints, counters, true);
            self.buttons = buttons;
            let button_report = self.make_report(0, 0, 0);
            write_usb_report(&button_report, cfg, endpoints, counters);
            self.next_flush = Instant::now() + Duration::from_secs_f64(1.0 / cfg.mouse_report_hz);
        }

        self.endpoint = report.endpoint;
        self.report_id = report.report[0];
        self.dx += dx;
        self.dy += dy;
        self.wheel += wheel;
        self.flush(cfg, endpoints, counters, false);
    }

    fn flush(
        &mut self,
        cfg: &Config,
        endpoints: &mut Endpoints,
        counters: &mut Counters,
        force: bool,
    ) {
        if !self.initialized {
            return;
        }
        if !force && Instant::now() < self.next_flush {
            return;
        }
        if self.dx == 0 && self.dy == 0 && self.wheel == 0 {
            self.next_flush = Instant::now() + Duration::from_secs_f64(1.0 / cfg.mouse_report_hz);
            return;
        }
        let dx = self.dx.clamp(-127, 127);
        let dy = self.dy.clamp(-127, 127);
        let wheel = self.wheel.clamp(-127, 127);
        self.dx -= dx;
        self.dy -= dy;
        self.wheel -= wheel;
        let report = self.make_report(dx, dy, wheel);
        write_usb_report(&report, cfg, endpoints, counters);
        self.next_flush = Instant::now() + Duration::from_secs_f64(1.0 / cfg.mouse_report_hz);
    }

    fn make_report(&self, dx: i32, dy: i32, wheel: i32) -> UsbReport {
        UsbReport {
            endpoint: self.endpoint,
            report: vec![
                self.report_id,
                self.buttons,
                i8_byte(dx),
                i8_byte(dy),
                i8_byte(wheel),
            ],
            kind: KIND_MOUSE,
        }
    }

    fn time_until_flush(&self) -> Duration {
        if !self.initialized || (self.dx == 0 && self.dy == 0 && self.wheel == 0) {
            return Duration::from_millis(500);
        }
        self.next_flush.saturating_duration_since(Instant::now())
    }
}

struct Endpoints {
    hidg0: Endpoint,
    hidg2: Endpoint,
}

impl RawBridgeStatus {
    fn new(cfg: &Config) -> Self {
        Self {
            enabled: cfg.raw_hid_bridge_enabled,
            path: cfg.raw_hid_path.clone(),
            viald_socket_path: cfg.viald_socket_path.clone(),
            open: false,
            connected: false,
            last_error: String::new(),
            packets: 0,
            resets: 0,
        }
    }
}

fn write_usb_report(
    report: &UsbReport,
    cfg: &Config,
    endpoints: &mut Endpoints,
    counters: &mut Counters,
) -> bool {
    if report.kind != KIND_KEYBOARD && report.kind != KIND_US_SUB_KEYBOARD {
        log_frame_event(
            cfg,
            "hidd_usb_write",
            &format!(
                "\"kind\":{},\"endpoint\":\"{}\",\"report\":\"{}\"",
                report.kind,
                endpoint_name(report.endpoint),
                hex(&report.report)
            ),
        );
    }
    let endpoint = match report.endpoint {
        EndpointId::Hidg0 => &mut endpoints.hidg0,
        EndpointId::Hidg2 => &mut endpoints.hidg2,
    };
    if !endpoint.write_report(&report.report, cfg, counters) {
        return false;
    }
    match report.kind {
        KIND_KEYBOARD => counters.keyboard_reports += 1,
        KIND_US_SUB_KEYBOARD => counters.us_sub_keyboard_reports += 1,
        KIND_MOUSE => counters.mouse_reports += 1,
        KIND_CONSUMER => counters.consumer_reports += 1,
        _ => {}
    }
    true
}

fn send_startup_keyboard_releases(
    cfg: &Config,
    endpoints: &mut Endpoints,
    counters: &mut Counters,
) {
    if !cfg.keyboard_startup_release {
        return;
    }
    for kind in [KIND_KEYBOARD, KIND_US_SUB_KEYBOARD] {
        let report = adapt_report(&HidRequest {
            kind,
            payload: vec![0; 8],
        });
        log_frame_event(
            cfg,
            "hidd_startup_keyboard_release",
            &format!(
                "\"endpoint\":\"{}\",\"report\":\"{}\"",
                endpoint_name(report.endpoint),
                hex(&report.report)
            ),
        );
        let endpoint = match report.endpoint {
            EndpointId::Hidg0 => &mut endpoints.hidg0,
            EndpointId::Hidg2 => &mut endpoints.hidg2,
        };
        endpoint.write_startup_release(&report.report, cfg);
        match report.kind {
            KIND_KEYBOARD => counters.keyboard_reports += 1,
            KIND_US_SUB_KEYBOARD => counters.us_sub_keyboard_reports += 1,
            _ => unreachable!(),
        }
        counters.startup_release_reports += 1;
    }
}

fn keyboard_payload(report: &UsbReport) -> &[u8] {
    if report.kind == KIND_KEYBOARD && report.report.len() >= 9 {
        &report.report[1..9]
    } else {
        &report.report
    }
}

fn keyboard_is_release(report: &UsbReport) -> bool {
    let payload = keyboard_payload(report);
    payload.len() >= 8 && payload[0] == 0 && payload[2..8].iter().all(|byte| *byte == 0)
}

fn keyboard_keys_and_modifiers(report: &UsbReport) -> ([u8; 6], u8) {
    let payload = keyboard_payload(report);
    let mut keys = [0u8; 6];
    if payload.len() >= 8 {
        keys.copy_from_slice(&payload[2..8]);
        (keys, payload[0])
    } else {
        (keys, 0)
    }
}

fn signed_i8(value: u8) -> i32 {
    if value >= 128 {
        value as i32 - 256
    } else {
        value as i32
    }
}

fn i8_byte(value: i32) -> u8 {
    value.clamp(-127, 127) as i8 as u8
}

fn bind_socket(path: &str, mode: u32) -> io::Result<UnixDatagram> {
    let socket_path = Path::new(path);
    if let Ok(metadata) = fs::symlink_metadata(socket_path) {
        if metadata.file_type().is_socket() {
            fs::remove_file(socket_path)?;
        }
    }
    let socket = UnixDatagram::bind(socket_path)?;
    fs::set_permissions(socket_path, fs::Permissions::from_mode(mode))?;
    Ok(socket)
}

fn json_escape(value: &str) -> String {
    value.replace('\\', "\\\\").replace('"', "\\\"")
}

fn update_raw_status(
    raw_status: &Arc<Mutex<RawBridgeStatus>>,
    update: impl FnOnce(&mut RawBridgeStatus),
) {
    if let Ok(mut status) = raw_status.lock() {
        update(&mut status);
    }
}

fn write_status(
    cfg: &Config,
    endpoints: &Endpoints,
    counters: &Counters,
    raw_status: &Arc<Mutex<RawBridgeStatus>>,
) {
    if cfg.status_path.is_empty() {
        return;
    }
    let raw = raw_status.lock().ok();
    let status = format!(
        concat!(
            "{{\n",
            "  \"schema\":\"hidd.status.v1\",\n",
            "  \"process\":true,\n",
            "  \"protocol\":\"usbd-hid-report-broker.v1+raw-hid-bridge.v1\",\n",
            "  \"socket\":{{\"path\":\"{}\",\"listening\":true}},\n",
            "  \"endpoints\":{{\n",
            "    \"hidg0\":{{\"path\":\"{}\",\"open\":{},\"last_error\":\"{}\"}},\n",
            "    \"hidg1\":{{\"path\":\"{}\",\"open\":{},\"enabled\":{},\"connected\":{},\"viald_socket\":\"{}\",\"last_error\":\"{}\"}},\n",
            "    \"hidg2\":{{\"path\":\"{}\",\"open\":{},\"last_error\":\"{}\"}}\n",
            "  }},\n",
            "  \"counters\":{{\n",
            "    \"frames_received\":{},\n",
            "    \"keyboard_reports\":{},\n",
            "    \"us_sub_keyboard_reports\":{},\n",
            "    \"startup_release_reports\":{},\n",
            "    \"mouse_reports\":{},\n",
            "    \"consumer_reports\":{},\n",
            "    \"invalid_frames\":{},\n",
            "    \"write_errors\":{},\n",
            "    \"dropped_reports\":{},\n",
            "    \"raw_hid_packets\":{},\n",
            "    \"raw_hid_resets\":{}\n",
            "  }}\n",
            "}}\n"
        ),
        json_escape(&cfg.socket_path),
        json_escape(&endpoints.hidg0.path),
        endpoints.hidg0.file.is_some(),
        json_escape(&endpoints.hidg0.last_error),
        json_escape(
            raw.as_ref()
                .map(|status| status.path.as_str())
                .unwrap_or("")
        ),
        raw.as_ref().is_some_and(|status| status.open),
        raw.as_ref().is_some_and(|status| status.enabled),
        raw.as_ref().is_some_and(|status| status.connected),
        json_escape(
            raw.as_ref()
                .map(|status| status.viald_socket_path.as_str())
                .unwrap_or(""),
        ),
        json_escape(
            raw.as_ref()
                .map(|status| status.last_error.as_str())
                .unwrap_or("")
        ),
        json_escape(&endpoints.hidg2.path),
        endpoints.hidg2.file.is_some(),
        json_escape(&endpoints.hidg2.last_error),
        counters.frames_received,
        counters.keyboard_reports,
        counters.us_sub_keyboard_reports,
        counters.startup_release_reports,
        counters.mouse_reports,
        counters.consumer_reports,
        counters.invalid_frames,
        counters.write_errors,
        counters.dropped_reports,
        raw.as_ref().map(|status| status.packets).unwrap_or(0),
        raw.as_ref().map(|status| status.resets).unwrap_or(0),
    );
    let tmp_path = format!("{}.tmp", cfg.status_path);
    if let Some(parent) = Path::new(&cfg.status_path).parent() {
        let _ = fs::create_dir_all(parent);
    }
    if fs::write(&tmp_path, status).is_ok() {
        let _ = fs::rename(tmp_path, &cfg.status_path);
    }
}

fn min_timeout(hidg0: &KeyboardRoute, hidg2: &KeyboardRoute, mouse: &MouseScheduler) -> Duration {
    *[
        hidg0.time_until_flush(),
        hidg2.time_until_flush(),
        mouse.time_until_flush(),
        Duration::from_millis(500),
    ]
    .iter()
    .min()
    .expect("timeouts are non-empty")
}

fn flush_keyboard_routes(
    hidg0: &mut KeyboardRoute,
    hidg2: &mut KeyboardRoute,
    cfg: &Config,
    endpoints: &mut Endpoints,
    counters: &mut Counters,
    force: bool,
) {
    hidg0.flush_if_due(cfg, endpoints, counters, force);
    hidg2.flush_if_due(cfg, endpoints, counters, force);
}

fn start_raw_hid_bridge(cfg: Config, raw_status: Arc<Mutex<RawBridgeStatus>>) {
    if !cfg.raw_hid_bridge_enabled {
        update_raw_status(&raw_status, |status| {
            status.enabled = false;
            status.open = false;
            status.connected = false;
            status.last_error = "disabled".to_string();
        });
        return;
    }

    thread::spawn(move || {
        loop {
            update_raw_status(&raw_status, |status| {
                status.open = false;
                status.connected = false;
            });

            let mut raw_hid = match OpenOptions::new()
                .read(true)
                .write(true)
                .open(&cfg.raw_hid_path)
            {
                Ok(file) => {
                    update_raw_status(&raw_status, |status| {
                        status.open = true;
                        status.last_error.clear();
                    });
                    file
                }
                Err(err) => {
                    update_raw_status(&raw_status, |status| {
                        status.last_error = format!("open raw hid: {err}");
                        status.resets += 1;
                    });
                    thread::sleep(cfg.raw_hid_retry_interval);
                    continue;
                }
            };

            let mut viald = match UnixStream::connect(&cfg.viald_socket_path) {
                Ok(stream) => {
                    update_raw_status(&raw_status, |status| {
                        status.connected = true;
                        status.last_error.clear();
                    });
                    stream
                }
                Err(err) => {
                    update_raw_status(&raw_status, |status| {
                        status.connected = false;
                        status.last_error = format!("connect viald: {err}");
                        status.resets += 1;
                    });
                    thread::sleep(cfg.raw_hid_retry_interval);
                    continue;
                }
            };

            let mut request = vec![0u8; cfg.raw_hid_report_size];
            let mut response = vec![0u8; cfg.raw_hid_report_size];
            loop {
                if let Err(err) = raw_hid.read_exact(&mut request) {
                    update_raw_status(&raw_status, |status| {
                        status.open = false;
                        status.connected = false;
                        status.last_error = format!("read raw hid: {err}");
                        status.resets += 1;
                    });
                    break;
                }
                if let Err(err) = viald.write_all(&request) {
                    update_raw_status(&raw_status, |status| {
                        status.connected = false;
                        status.last_error = format!("write viald: {err}");
                        status.resets += 1;
                    });
                    break;
                }
                if let Err(err) = viald.read_exact(&mut response) {
                    update_raw_status(&raw_status, |status| {
                        status.connected = false;
                        status.last_error = format!("read viald: {err}");
                        status.resets += 1;
                    });
                    break;
                }
                if let Err(err) = raw_hid.write_all(&response) {
                    update_raw_status(&raw_status, |status| {
                        status.open = false;
                        status.connected = false;
                        status.last_error = format!("write raw hid: {err}");
                        status.resets += 1;
                    });
                    break;
                }
                update_raw_status(&raw_status, |status| {
                    status.packets += 1;
                    status.last_error.clear();
                });
            }

            thread::sleep(cfg.raw_hid_retry_interval);
        }
    });
}

fn run() -> Result<(), String> {
    let cfg = load_config()?;
    let raw_status = Arc::new(Mutex::new(RawBridgeStatus::new(&cfg)));
    start_raw_hid_bridge(cfg.clone(), raw_status.clone());
    let socket = bind_socket(&cfg.socket_path, cfg.socket_mode)
        .map_err(|err| format!("bind socket: {err}"))?;
    let mut endpoints = Endpoints {
        hidg0: Endpoint::new(cfg.hidg0_path.clone()),
        hidg2: Endpoint::new(cfg.hidg2_path.clone()),
    };
    let _ = endpoints.hidg0.ensure_open();
    let _ = endpoints.hidg2.ensure_open();

    let mut counters = Counters::default();
    let mut hidg0_route = KeyboardRoute::new();
    let mut hidg2_route = KeyboardRoute::new();
    let mut mouse = MouseScheduler::new();
    let mut processed_frames = 0u64;
    write_status(&cfg, &endpoints, &counters, &raw_status);
    send_startup_keyboard_releases(&cfg, &mut endpoints, &mut counters);
    write_status(&cfg, &endpoints, &counters, &raw_status);

    loop {
        flush_keyboard_routes(
            &mut hidg0_route,
            &mut hidg2_route,
            &cfg,
            &mut endpoints,
            &mut counters,
            false,
        );
        mouse.flush(&cfg, &mut endpoints, &mut counters, false);

        socket
            .set_read_timeout(Some(min_timeout(&hidg0_route, &hidg2_route, &mouse)))
            .map_err(|err| format!("set timeout: {err}"))?;
        let mut buffer = [0u8; 128];
        let status_dirty = match socket.recv(&mut buffer) {
            Ok(size) => {
                processed_frames += 1;
                match decode_frame(&buffer[..size]) {
                    Ok(request) => {
                        counters.frames_received += 1;
                        let report = adapt_report(&request);
                        log_frame_event(
                            &cfg,
                            "hidd_frame_received",
                            &format!(
                                "\"kind\":{},\"endpoint\":\"{}\",\"payload\":\"{}\",\"report\":\"{}\",\"keyboard_release\":{}",
                                request.kind,
                                endpoint_name(report.endpoint),
                                hex(&request.payload),
                                hex(&report.report),
                                keyboard_is_release(&report)
                            ),
                        );
                        if report.kind == KIND_KEYBOARD {
                            hidg0_route.enqueue(report, &cfg, &mut endpoints, &mut counters);
                        } else if report.kind == KIND_US_SUB_KEYBOARD {
                            hidg2_route.enqueue(report, &cfg, &mut endpoints, &mut counters);
                        } else {
                            flush_keyboard_routes(
                                &mut hidg0_route,
                                &mut hidg2_route,
                                &cfg,
                                &mut endpoints,
                                &mut counters,
                                true,
                            );
                            if report.kind == KIND_MOUSE {
                                mouse.enqueue(&report, &cfg, &mut endpoints, &mut counters);
                            } else {
                                write_usb_report(&report, &cfg, &mut endpoints, &mut counters);
                            }
                        }
                    }
                    Err(_) => {
                        counters.invalid_frames += 1;
                        log_frame_event(
                            &cfg,
                            "hidd_invalid_frame",
                            &format!("\"size\":{},\"raw\":\"{}\"", size, hex(&buffer[..size])),
                        );
                    }
                }
                true
            }
            Err(err)
                if err.kind() == io::ErrorKind::WouldBlock
                    || err.kind() == io::ErrorKind::TimedOut =>
            {
                write_status(&cfg, &endpoints, &counters, &raw_status);
                continue;
            }
            Err(err) => return Err(format!("recv: {err}")),
        };

        if status_dirty {
            write_status(&cfg, &endpoints, &counters, &raw_status);
        }

        if cfg
            .exit_after_frames
            .is_some_and(|limit| processed_frames >= limit)
        {
            break;
        }
    }

    flush_keyboard_routes(
        &mut hidg0_route,
        &mut hidg2_route,
        &cfg,
        &mut endpoints,
        &mut counters,
        true,
    );
    mouse.flush(&cfg, &mut endpoints, &mut counters, true);
    write_status(&cfg, &endpoints, &counters, &raw_status);
    let _ = fs::remove_file(&cfg.socket_path);
    Ok(())
}

fn main() {
    if let Err(err) = run() {
        eprintln!("hidloom-hidd: {err}");
        std::process::exit(1);
    }
}
