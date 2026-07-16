use serde::Deserialize;
use serde_json::{Value, json};
use std::collections::{HashMap, HashSet};
use std::env;
use std::fs::{self, OpenOptions};
use std::io::{self, BufRead, BufReader, ErrorKind, Read, Write};
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::{UnixDatagram, UnixListener, UnixStream};
use std::path::{Path, PathBuf};
use std::thread;
use std::time::Duration;

const KIND_KEYBOARD: u8 = 0x01;
const KIND_US_SUB_KEYBOARD: u8 = 0x04;
const FRAME_SIZE: usize = 64;
const CHECKSUM_OFFSET: usize = 63;
const PAYLOAD_OFFSET: usize = 8;
const PAYLOAD_CAPACITY: usize = 24;
const JIS_ZENKAKU_HANKAKU_INTERNAL_MARKER: u8 = 0x5a;
const JIS_ZENKAKU_HANKAKU_HID_USAGE: u8 = 0x35;

struct Config {
    matrix_socket: PathBuf,
    ctrl_socket: PathBuf,
    delegate_socket: Option<PathBuf>,
    matrix_tap_socket: Option<PathBuf>,
    hid_report_socket: PathBuf,
    status_path: PathBuf,
    output_enabled: bool,
    matrix_socket_mode: u32,
    ctrl_socket_mode: u32,
    preview_log_path: Option<PathBuf>,
    idle_poll_interval: Duration,
    exit_after_packets: Option<u64>,
}

struct StreamClient {
    stream: UnixStream,
    input: Vec<u8>,
    output: Vec<u8>,
    read_closed: bool,
}

impl StreamClient {
    fn new(stream: UnixStream) -> Self {
        Self {
            stream,
            input: Vec::new(),
            output: Vec::new(),
            read_closed: false,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum Action {
    NoOp,
    Key(KeyAction),
    Layer(LayerAction),
    Delegated(String),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum LayerOp {
    Momentary,
    Toggle,
    To,
    Default,
    OneShot,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct LayerAction {
    op: LayerOp,
    layer: usize,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct KeyAction {
    code: u16,
    reserved: u8,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct MatrixEvent {
    press: bool,
    row: u8,
    col: u8,
}

#[derive(Clone, Default)]
struct HidState {
    modifiers: u8,
    modifier_counts: [u16; 8],
    reserved: u8,
    keys: [u8; 6],
    key_counts: HashMap<u8, u16>,
    rollover_drops: u64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum RouteMode {
    Disabled,
    ImeKeys,
    All,
    JisSpecialUsDefault,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct RoutingConfig {
    split_keyboard_enabled: bool,
    route_mode: RouteMode,
}

impl Default for RoutingConfig {
    fn default() -> Self {
        Self {
            split_keyboard_enabled: false,
            route_mode: RouteMode::ImeKeys,
        }
    }
}

#[derive(Clone, Copy, Debug, Default)]
struct RouteState {
    us_sub_key_active: bool,
    primary_key_active: bool,
    primary_modifier_mirror_active: bool,
    zenkaku_hankaku_active: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct RoutedReport {
    kind: u8,
    report: [u8; 8],
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum InjectedRoute {
    Normal,
    Keyboard,
    UsSubKeyboard,
}

#[derive(Default)]
struct EventOutcome {
    reports: Vec<RoutedReport>,
    delegate_packet: Option<[u8; 4]>,
    tap_packet: Option<[u8; 4]>,
}

#[derive(Default)]
struct Counters {
    matrix_events: u64,
    ignored_duplicates: u64,
    unsupported_actions: u64,
    delegated_actions: u64,
    delegate_errors: u64,
    matrix_tap_events: u64,
    matrix_tap_errors: u64,
    injected_key_events: u64,
    injected_duplicates: u64,
    rollover_drops: u64,
    reports_emitted: u64,
    broker_frames_sent: u64,
}

struct Core {
    keycodes: HashMap<String, u16>,
    layers: Vec<HashMap<String, String>>,
    routing: RoutingConfig,
    route_state: RouteState,
    pressed_matrix: HashMap<(u8, u8), Action>,
    injected_keys: HashMap<String, KeyAction>,
    force_delegate_all: bool,
    momentary_layers: HashSet<usize>,
    toggled_layers: HashSet<usize>,
    oneshot_layers: HashSet<usize>,
    default_layer: usize,
    hid: HidState,
    counters: Counters,
}

#[derive(Deserialize)]
struct KeycodeObject {
    hid: u16,
    #[serde(default)]
    page: Option<String>,
}

fn env_path(name: &str, default: PathBuf) -> PathBuf {
    env::var(name)
        .ok()
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .unwrap_or(default)
}

fn env_optional_path(name: &str, default: Option<PathBuf>) -> Option<PathBuf> {
    match env::var(name) {
        Ok(value) => {
            let normalized = value.trim().to_ascii_lowercase();
            if normalized.is_empty()
                || matches!(
                    normalized.as_str(),
                    "0" | "false" | "no" | "none" | "off" | "disabled"
                )
            {
                None
            } else {
                Some(PathBuf::from(value))
            }
        }
        Err(_) => default,
    }
}

fn env_bool(name: &str, default: bool) -> bool {
    env::var(name)
        .ok()
        .and_then(|raw| match raw.as_str() {
            "1" | "true" | "TRUE" | "yes" | "YES" | "on" | "ON" => Some(true),
            "0" | "false" | "FALSE" | "no" | "NO" | "off" | "OFF" => Some(false),
            _ => None,
        })
        .unwrap_or(default)
}

fn parse_bool_value(value: &Value) -> Option<bool> {
    if let Some(flag) = value.as_bool() {
        return Some(flag);
    }
    value.as_str().and_then(parse_bool_str)
}

fn parse_bool_str(raw: &str) -> Option<bool> {
    match raw {
        "1" | "true" | "TRUE" | "yes" | "YES" | "on" | "ON" => Some(true),
        "0" | "false" | "FALSE" | "no" | "NO" | "off" | "OFF" => Some(false),
        _ => None,
    }
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

fn repo_root() -> PathBuf {
    env::var("HIDLOOM_REPO_ROOT")
        .ok()
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../.."))
}

fn load_json_with_fallback(runtime: &Path, default: &Path) -> Result<(Value, PathBuf), String> {
    match fs::read_to_string(runtime) {
        Ok(raw) => match serde_json::from_str::<Value>(&raw) {
            Ok(value) => return Ok((value, runtime.to_path_buf())),
            Err(err) => eprintln!(
                "warning: invalid runtime json {}, falling back to {}: {err}",
                runtime.display(),
                default.display()
            ),
        },
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => {}
        Err(err) => eprintln!(
            "warning: failed to read {}, falling back to {}: {err}",
            runtime.display(),
            default.display()
        ),
    }

    let raw = fs::read_to_string(default)
        .map_err(|err| format!("failed to read default json {}: {err}", default.display()))?;
    let value = serde_json::from_str::<Value>(&raw)
        .map_err(|err| format!("invalid default json {}: {err}", default.display()))?;
    Ok((value, default.to_path_buf()))
}

fn load_keycodes(runtime: &Path, default: &Path) -> Result<HashMap<String, u16>, String> {
    let (value, _source) = load_json_with_fallback(runtime, default)?;
    let object = value
        .as_object()
        .ok_or_else(|| "keycodes json must be an object".to_string())?;
    let mut result = HashMap::new();
    for (name, raw) in object {
        if name.starts_with('_') {
            continue;
        }
        if let Some(number) = raw.as_u64() {
            result.insert(name.clone(), number as u16);
            continue;
        }
        if raw.is_object() {
            let entry: KeycodeObject = serde_json::from_value(raw.clone())
                .map_err(|err| format!("invalid keycode entry {name}: {err}"))?;
            if entry.page.as_deref() == Some("consumer") {
                continue;
            }
            result.insert(name.clone(), entry.hid);
        }
    }
    Ok(result)
}

fn value_to_layers(value: &Value) -> Result<Vec<HashMap<String, String>>, String> {
    let layers = value
        .get("layers")
        .and_then(Value::as_array)
        .ok_or_else(|| "keymap json must contain layers array".to_string())?;

    if value.get("_layout_def").is_none() {
        return layers
            .iter()
            .map(|layer| {
                let object = layer
                    .as_object()
                    .ok_or_else(|| "flat layer must be an object".to_string())?;
                let mut flat = HashMap::new();
                for (key, raw) in object {
                    if key.starts_with('_') {
                        continue;
                    }
                    if let Some(action) = raw.as_str() {
                        flat.insert(key.clone(), action.to_string());
                    }
                }
                Ok(flat)
            })
            .collect();
    }

    let layout_def = value
        .get("_layout_def")
        .and_then(Value::as_object)
        .ok_or_else(|| "_layout_def must be an object".to_string())?;
    let mut group_coords: Vec<(String, Vec<(u8, u8)>)> = Vec::new();
    for (group, entries) in layout_def {
        if group.starts_with('_') {
            continue;
        }
        let Some(items) = entries.as_array() else {
            continue;
        };
        let mut coords = Vec::new();
        for entry in items {
            let Some(parts) = entry.as_array() else {
                continue;
            };
            if parts.len() < 2 {
                continue;
            }
            let row = parts[0]
                .as_i64()
                .ok_or_else(|| format!("invalid row in group {group}"))?;
            let col = parts[1]
                .as_i64()
                .ok_or_else(|| format!("invalid col in group {group}"))?;
            if !(0..=15).contains(&row) || !(0..=15).contains(&col) {
                return Err(format!("matrix coordinate out of M0 range: {row},{col}"));
            }
            coords.push((row as u8, col as u8));
        }
        group_coords.push((group.clone(), coords));
    }

    let mut result = Vec::new();
    for layer in layers {
        let object = layer
            .as_object()
            .ok_or_else(|| "keymap layer must be an object".to_string())?;
        let mut flat = HashMap::new();
        for (group, coords) in &group_coords {
            let Some(actions) = object.get(group).and_then(Value::as_array) else {
                continue;
            };
            for ((row, col), raw_action) in coords.iter().zip(actions.iter()) {
                if let Some(action) = raw_action.as_str() {
                    if !action.is_empty() {
                        flat.insert(format!("{row},{col}"), action.to_string());
                    }
                }
            }
        }
        result.push(flat);
    }
    if result.is_empty() {
        result.push(HashMap::new());
    }
    Ok(result)
}

fn load_layers(runtime: &Path, default: &Path) -> Result<Vec<HashMap<String, String>>, String> {
    let (value, _source) = load_json_with_fallback(runtime, default)?;
    value_to_layers(&value)
}

fn parse_route_mode(raw: &str) -> RouteMode {
    let normalized = raw.trim().to_ascii_lowercase().replace('-', "_");
    match normalized.as_str() {
        "all" | "all_keys" => RouteMode::All,
        "jis_special_us_default"
        | "jis_specials_us_default"
        | "us_default_jis_special"
        | "us_default_jis_specials"
        | "jis_special"
        | "jis_specials" => RouteMode::JisSpecialUsDefault,
        _ => RouteMode::ImeKeys,
    }
}

fn load_routing_config(runtime: &Path, default: &Path) -> Result<RoutingConfig, String> {
    let (value, _source) = load_json_with_fallback(runtime, default)?;
    let settings = value.get("settings").and_then(Value::as_object);
    let split = settings.and_then(|settings| settings.get("usb_split_keyboard"));
    let mut enabled = split
        .and_then(|raw| {
            raw.as_object()
                .and_then(|object| object.get("enabled"))
                .or(Some(raw))
        })
        .and_then(parse_bool_value)
        .unwrap_or(false);
    if let Some(raw) = env::var("LOGICD_USB_SPLIT_KEYBOARD")
        .ok()
        .and_then(|raw| parse_bool_str(&raw))
    {
        enabled = raw;
    }

    let mut route = split
        .and_then(Value::as_object)
        .and_then(|object| object.get("route"))
        .and_then(Value::as_str)
        .map(parse_route_mode)
        .unwrap_or(RouteMode::ImeKeys);
    if let Ok(raw) = env::var("LOGICD_USB_SPLIT_KEYBOARD_ROUTE") {
        route = parse_route_mode(&raw);
    }

    Ok(RoutingConfig {
        split_keyboard_enabled: enabled,
        route_mode: if enabled { route } else { RouteMode::Disabled },
    })
}

fn parse_matrix_packet(packet: &[u8]) -> Result<MatrixEvent, String> {
    if packet.len() != 4 {
        return Err(format!("invalid matrix packet length: {}", packet.len()));
    }
    let press = match packet[0] {
        b'P' => true,
        b'R' => false,
        other => return Err(format!("invalid matrix event type: 0x{other:02x}")),
    };
    if packet[3] != b'\n' && packet[3] != 0 {
        return Err("matrix packet must end with newline or NUL".to_string());
    }
    let row = hex_nibble(packet[1]).ok_or_else(|| "invalid matrix row".to_string())?;
    let col = hex_nibble(packet[2]).ok_or_else(|| "invalid matrix col".to_string())?;
    Ok(MatrixEvent { press, row, col })
}

fn hex_nibble(byte: u8) -> Option<u8> {
    match byte {
        b'0'..=b'9' => Some(byte - b'0'),
        b'A'..=b'F' => Some(byte - b'A' + 10),
        b'a'..=b'f' => Some(byte - b'a' + 10),
        _ => None,
    }
}

fn parse_layer_action(action: &str) -> Option<LayerAction> {
    let (op, inner) = if let Some(inner) = action.strip_prefix("MO(") {
        (LayerOp::Momentary, inner)
    } else if let Some(inner) = action.strip_prefix("TG(") {
        (LayerOp::Toggle, inner)
    } else if let Some(inner) = action.strip_prefix("TO(") {
        (LayerOp::To, inner)
    } else if let Some(inner) = action.strip_prefix("DF(") {
        (LayerOp::Default, inner)
    } else if let Some(inner) = action.strip_prefix("OSL(") {
        (LayerOp::OneShot, inner)
    } else {
        return None;
    };
    let layer = inner.strip_suffix(')')?.parse::<usize>().ok()?;
    Some(LayerAction { op, layer })
}

fn sorted_layers(layers: &HashSet<usize>) -> Vec<usize> {
    let mut values: Vec<usize> = layers.iter().copied().collect();
    values.sort_unstable();
    values
}

fn is_delegated_action(action: &str) -> bool {
    if action == "KC_NONE" || action == "KC_TRNS" || action == "KC_ZKHK" {
        return false;
    }
    action.contains('(')
        || action.starts_with("MS_")
        || action.starts_with("KC_MS_")
        || action.starts_with("KC_BTN")
        || action.starts_with("KC_WH_")
        || action.starts_with("KC_SH")
        || matches!(action, "KC_USB" | "KC_BT" | "KC_CONNAUTO" | "KC_CONSOLE")
        || action.starts_with("MACRO:")
        || action.starts_with("TEXT(")
        || action.starts_with("SEND_STRING(")
}

fn matrix_packet(event: MatrixEvent) -> [u8; 4] {
    const HEX: &[u8; 16] = b"0123456789ABCDEF";
    [
        if event.press { b'P' } else { b'R' },
        HEX[event.row as usize],
        HEX[event.col as usize],
        b'\n',
    ]
}

impl HidState {
    fn pressed_key_count(&self) -> usize {
        self.keys.iter().filter(|key| **key != 0).count()
    }

    fn press(&mut self, key: KeyAction) {
        let code = key.code;
        if code == 0 {
            return;
        }
        if (0xE0..=0xE7).contains(&code) {
            let index = (code - 0xE0) as usize;
            self.modifier_counts[index] = self.modifier_counts[index].saturating_add(1);
            self.modifiers |= 1 << index;
        } else if code < 0xE0 {
            let usage = code as u8;
            if let Some(count) = self.key_counts.get_mut(&usage) {
                *count = count.saturating_add(1);
            } else {
                if let Some(slot) = self.keys.iter().position(|value| *value == 0) {
                    self.keys[slot] = usage;
                    self.key_counts.insert(usage, 1);
                    if key.reserved != 0 {
                        self.reserved = key.reserved;
                    }
                } else {
                    self.rollover_drops += 1;
                }
            }
        }
    }

    fn release(&mut self, key: KeyAction) {
        let code = key.code;
        if code == 0 {
            return;
        }
        if (0xE0..=0xE7).contains(&code) {
            let index = (code - 0xE0) as usize;
            if self.modifier_counts[index] > 0 {
                self.modifier_counts[index] -= 1;
            }
            if self.modifier_counts[index] == 0 {
                self.modifiers &= !(1 << index);
            }
        } else if code < 0xE0 {
            let usage = code as u8;
            if let Some(count) = self.key_counts.get_mut(&usage) {
                if *count > 0 {
                    *count -= 1;
                }
                if *count == 0 {
                    self.key_counts.remove(&usage);
                    if let Some(slot) = self.keys.iter().position(|value| *value == usage) {
                        self.keys[slot] = 0;
                    }
                    if key.reserved != 0 {
                        self.reserved = 0;
                    }
                }
            }
        }
    }

    fn build(&self) -> [u8; 8] {
        let mut report = [0u8; 8];
        report[0] = self.modifiers;
        report[1] = self.reserved;
        report[2..8].copy_from_slice(&self.keys);
        report
    }
}

impl Core {
    fn new(
        keycodes: HashMap<String, u16>,
        layers: Vec<HashMap<String, String>>,
        routing: RoutingConfig,
    ) -> Self {
        Self {
            keycodes,
            layers,
            routing,
            route_state: RouteState::default(),
            pressed_matrix: HashMap::new(),
            injected_keys: HashMap::new(),
            force_delegate_all: false,
            momentary_layers: HashSet::new(),
            toggled_layers: HashSet::new(),
            oneshot_layers: HashSet::new(),
            default_layer: 0,
            hid: HidState::default(),
            counters: Counters::default(),
        }
    }

    fn active_layers(&self) -> Vec<usize> {
        let mut active = HashSet::new();
        active.insert(0);
        if self.default_layer < self.layers.len() {
            active.insert(self.default_layer);
        }
        for layer in self
            .momentary_layers
            .iter()
            .chain(self.toggled_layers.iter())
            .chain(self.oneshot_layers.iter())
        {
            if *layer < self.layers.len() {
                active.insert(*layer);
            }
        }
        let mut layers: Vec<usize> = active.into_iter().collect();
        layers.sort_unstable_by(|a, b| b.cmp(a));
        layers
    }

    fn resolve(&self, row: u8, col: u8) -> Action {
        let key = format!("{row},{col}");
        for layer in self.active_layers() {
            let Some(actions) = self.layers.get(layer) else {
                continue;
            };
            let action = actions.get(&key).map(String::as_str).unwrap_or("KC_TRNS");
            if action == "KC_TRNS" {
                continue;
            }
            return self.action_from_str(action);
        }
        Action::NoOp
    }

    fn action_from_str(&self, action: &str) -> Action {
        if action == "KC_NONE" || action == "KC_TRNS" {
            return Action::NoOp;
        }
        if let Some(layer_action) = parse_layer_action(action) {
            return Action::Layer(layer_action);
        }
        if is_delegated_action(action) {
            return Action::Delegated(action.to_string());
        }
        if action == "KC_ZKHK" {
            return Action::Key(KeyAction {
                code: JIS_ZENKAKU_HANKAKU_HID_USAGE as u16,
                reserved: JIS_ZENKAKU_HANKAKU_INTERNAL_MARKER,
            });
        }
        if let Some(code) = self.keycodes.get(action) {
            if *code == 0 || *code >= 0x200 {
                return Action::Delegated(action.to_string());
            }
            return Action::Key(KeyAction {
                code: *code,
                reserved: 0,
            });
        }
        Action::Delegated(action.to_string())
    }

    fn valid_layer(&self, layer: usize) -> bool {
        layer < self.layers.len()
    }

    fn clear_invalid_layer_state(&mut self) {
        let len = self.layers.len();
        self.momentary_layers.retain(|layer| *layer < len);
        self.toggled_layers.retain(|layer| *layer < len);
        self.oneshot_layers.retain(|layer| *layer < len);
        if self.default_layer >= len {
            self.default_layer = 0;
        }
    }

    fn clear_oneshot_layers(&mut self) {
        if !self.oneshot_layers.is_empty() {
            self.oneshot_layers.clear();
        }
    }

    fn apply_layer_action(&mut self, action: LayerAction, is_press: bool) {
        self.clear_invalid_layer_state();
        match action.op {
            LayerOp::Momentary => {
                if is_press {
                    if self.valid_layer(action.layer) {
                        self.momentary_layers.insert(action.layer);
                    }
                } else {
                    self.momentary_layers.remove(&action.layer);
                }
            }
            LayerOp::Toggle => {
                if is_press && self.valid_layer(action.layer) {
                    if !self.toggled_layers.remove(&action.layer) {
                        self.toggled_layers.insert(action.layer);
                    }
                }
            }
            LayerOp::To => {
                if is_press && self.valid_layer(action.layer) {
                    self.momentary_layers.clear();
                    self.toggled_layers.clear();
                    self.oneshot_layers.clear();
                    if action.layer != self.default_layer {
                        self.toggled_layers.insert(action.layer);
                    }
                }
            }
            LayerOp::Default => {
                if is_press && self.valid_layer(action.layer) {
                    self.default_layer = action.layer;
                    self.momentary_layers.clear();
                    self.oneshot_layers.clear();
                }
            }
            LayerOp::OneShot => {
                if is_press && self.valid_layer(action.layer) {
                    self.oneshot_layers.insert(action.layer);
                }
            }
        }
    }

    fn delegate_active(&self) -> bool {
        self.pressed_matrix
            .values()
            .any(|action| matches!(action, Action::Delegated(_)))
    }

    fn apply_event(&mut self, event: MatrixEvent) -> EventOutcome {
        self.counters.matrix_events += 1;
        if self.force_delegate_all {
            self.counters.delegated_actions += 1;
            return EventOutcome {
                reports: Vec::new(),
                delegate_packet: Some(matrix_packet(event)),
                tap_packet: None,
            };
        }
        let key = (event.row, event.col);
        let before = self.hid.build();
        let tap_packet = Some(matrix_packet(event));
        if event.press {
            if self.pressed_matrix.contains_key(&key) {
                self.counters.ignored_duplicates += 1;
                return EventOutcome::default();
            }
            let action = if self.delegate_active() {
                Action::Delegated("delegate-context".to_string())
            } else {
                self.resolve(event.row, event.col)
            };
            if !self.oneshot_layers.is_empty() && !matches!(action, Action::NoOp | Action::Layer(_))
            {
                self.clear_oneshot_layers();
            }
            match &action {
                Action::NoOp => {}
                Action::Key(key) => self.hid.press(*key),
                Action::Layer(layer) => self.apply_layer_action(*layer, true),
                Action::Delegated(_) => self.counters.delegated_actions += 1,
            }
            let delegated = matches!(action, Action::Delegated(_));
            self.pressed_matrix.insert(key, action);
            if delegated {
                return EventOutcome {
                    reports: Vec::new(),
                    delegate_packet: Some(matrix_packet(event)),
                    tap_packet: None,
                };
            }
        } else {
            let Some(action) = self.pressed_matrix.remove(&key) else {
                self.counters.ignored_duplicates += 1;
                return EventOutcome::default();
            };
            match action {
                Action::NoOp => {}
                Action::Key(key) => self.hid.release(key),
                Action::Layer(layer) => self.apply_layer_action(layer, false),
                Action::Delegated(_) => {
                    self.counters.delegated_actions += 1;
                    return EventOutcome {
                        reports: Vec::new(),
                        delegate_packet: Some(matrix_packet(event)),
                        tap_packet: None,
                    };
                }
            }
        }
        let after = self.hid.build();
        self.counters.rollover_drops = self.hid.rollover_drops;
        if before != after {
            let reports = self.route_report(after);
            self.counters.reports_emitted += reports.len() as u64;
            EventOutcome {
                reports,
                delegate_packet: None,
                tap_packet,
            }
        } else {
            EventOutcome {
                reports: Vec::new(),
                delegate_packet: None,
                tap_packet,
            }
        }
    }

    fn release_all(&mut self) -> Vec<RoutedReport> {
        let before = self.hid.build();
        let route_state_before = self.route_state;
        self.pressed_matrix.clear();
        self.injected_keys.clear();
        self.momentary_layers.clear();
        self.toggled_layers.clear();
        self.oneshot_layers.clear();
        self.default_layer = 0;
        self.hid.modifiers = 0;
        self.hid.modifier_counts = [0; 8];
        self.hid.reserved = 0;
        self.hid.keys = [0; 6];
        self.hid.key_counts.clear();
        let after = self.hid.build();
        if before != after {
            let mut reports = self.route_report(after);
            if self.route_state.us_sub_key_active
                || self.route_state.primary_key_active
                || self.route_state.primary_modifier_mirror_active
                || self.route_state.zenkaku_hankaku_active
            {
                reports.extend(self.release_active_routes(self.route_state));
            }
            self.counters.reports_emitted += reports.len() as u64;
            reports
        } else if route_state_before.us_sub_key_active
            || route_state_before.primary_key_active
            || route_state_before.primary_modifier_mirror_active
            || route_state_before.zenkaku_hankaku_active
        {
            let reports = self.release_active_routes(route_state_before);
            self.counters.reports_emitted += reports.len() as u64;
            reports
        } else {
            Vec::new()
        }
    }

    fn release_active_routes(&mut self, route_state: RouteState) -> Vec<RoutedReport> {
        let mut reports = Vec::new();
        if route_state.primary_key_active
            || route_state.primary_modifier_mirror_active
            || route_state.zenkaku_hankaku_active
        {
            reports.push(routed(KIND_KEYBOARD, [0; 8]));
        }
        if route_state.us_sub_key_active || route_state.primary_modifier_mirror_active {
            reports.push(routed(KIND_US_SUB_KEYBOARD, [0; 8]));
        }
        self.route_state = RouteState::default();
        reports
    }

    fn remove_unique_injected_key_by_action(&mut self, action: &str) -> Option<KeyAction> {
        let Action::Key(target) = self.action_from_str(action) else {
            return None;
        };
        let mut matches = self.injected_keys.iter().filter_map(|(id, key)| {
            if *key == target {
                Some(id.clone())
            } else {
                None
            }
        });
        let first = matches.next()?;
        if matches.next().is_some() {
            return None;
        }
        self.injected_keys.remove(&first)
    }

    #[allow(dead_code)]
    fn apply_injected_key_event(
        &mut self,
        id: &str,
        action: &str,
        is_press: bool,
    ) -> Result<Vec<RoutedReport>, String> {
        self.apply_injected_key_event_with_route(id, action, is_press, InjectedRoute::Normal)
    }

    fn apply_injected_key_event_with_route(
        &mut self,
        id: &str,
        action: &str,
        is_press: bool,
        route: InjectedRoute,
    ) -> Result<Vec<RoutedReport>, String> {
        if id.is_empty() {
            return Err("id_required".to_string());
        }
        let before = self.hid.build();
        self.counters.injected_key_events += 1;
        if is_press {
            if self.injected_keys.contains_key(id) {
                self.counters.injected_duplicates += 1;
                return Ok(Vec::new());
            }
            match self.action_from_str(action) {
                Action::Key(key) => {
                    self.hid.press(key);
                    self.injected_keys.insert(id.to_string(), key);
                }
                Action::NoOp => {}
                Action::Layer(_) => return Err("unsupported_injected_action".to_string()),
                Action::Delegated(_) => return Err("unsupported_injected_action".to_string()),
            }
        } else {
            let Some(key) = self
                .injected_keys
                .remove(id)
                .or_else(|| self.remove_unique_injected_key_by_action(action))
            else {
                self.counters.injected_duplicates += 1;
                return Ok(Vec::new());
            };
            self.hid.release(key);
        }
        let after = self.hid.build();
        self.counters.rollover_drops = self.hid.rollover_drops;
        if before == after {
            return Ok(Vec::new());
        }
        let reports = match route {
            InjectedRoute::Normal => self.route_report(after),
            InjectedRoute::Keyboard => {
                self.route_state.primary_key_active = after != [0; 8];
                vec![routed(KIND_KEYBOARD, after)]
            }
            InjectedRoute::UsSubKeyboard => {
                self.route_state.us_sub_key_active = after != [0; 8];
                vec![routed(KIND_US_SUB_KEYBOARD, after)]
            }
        };
        self.counters.reports_emitted += reports.len() as u64;
        Ok(reports)
    }

    fn route_report(&mut self, report: [u8; 8]) -> Vec<RoutedReport> {
        if !self.routing.split_keyboard_enabled || self.routing.route_mode == RouteMode::Disabled {
            return vec![routed(KIND_KEYBOARD, report)];
        }
        match self.routing.route_mode {
            RouteMode::Disabled => vec![routed(KIND_KEYBOARD, report)],
            RouteMode::All => {
                if report_is_internal_zenkaku_hankaku(&report) {
                    vec![routed(
                        KIND_US_SUB_KEYBOARD,
                        clear_report_reserved_byte(report),
                    )]
                } else {
                    vec![routed(KIND_US_SUB_KEYBOARD, report)]
                }
            }
            RouteMode::JisSpecialUsDefault => self.route_jis_special_us_default(report),
            RouteMode::ImeKeys => self.route_ime_keys(report),
        }
    }

    fn route_ime_keys(&mut self, report: [u8; 8]) -> Vec<RoutedReport> {
        if report_has_split_keyboard_switch_key(&report) {
            self.route_state.us_sub_key_active = true;
            return vec![routed(KIND_US_SUB_KEYBOARD, report)];
        }
        if report == [0u8; 8] && self.route_state.us_sub_key_active {
            self.route_state.us_sub_key_active = false;
            return vec![routed(KIND_US_SUB_KEYBOARD, report)];
        }
        self.route_state.us_sub_key_active = false;
        vec![routed(KIND_KEYBOARD, report)]
    }

    fn route_jis_special_us_default(&mut self, report: [u8; 8]) -> Vec<RoutedReport> {
        if report_is_internal_zenkaku_hankaku(&report) {
            self.route_state.primary_key_active = false;
            self.route_state.primary_modifier_mirror_active = report[0] != 0;
            self.route_state.us_sub_key_active = false;
            self.route_state.zenkaku_hankaku_active = true;
            return vec![routed(KIND_KEYBOARD, clear_report_reserved_byte(report))];
        }
        if report == [0u8; 8] && self.route_state.zenkaku_hankaku_active {
            self.route_state.zenkaku_hankaku_active = false;
            self.route_state.primary_modifier_mirror_active = false;
            return vec![routed(KIND_KEYBOARD, report)];
        }
        self.route_state.zenkaku_hankaku_active = false;
        if report_has_jis_special_on_main_key(&report) {
            self.route_state.primary_key_active = true;
            self.route_state.primary_modifier_mirror_active = report[0] != 0;
            self.route_state.us_sub_key_active = false;
            return vec![routed(KIND_KEYBOARD, report)];
        }
        if report_is_modifier_only(&report) {
            self.route_state.primary_key_active = false;
            self.route_state.primary_modifier_mirror_active = report[0] != 0;
            self.route_state.us_sub_key_active = report[0] != 0;
            return vec![
                routed(KIND_KEYBOARD, report),
                routed(KIND_US_SUB_KEYBOARD, report),
            ];
        }
        let mut reports = Vec::new();
        if self.route_state.primary_key_active {
            self.route_state.primary_key_active = false;
            self.route_state.primary_modifier_mirror_active = report[0] != 0;
            reports.push(routed(KIND_KEYBOARD, primary_modifier_report(&report)));
            if report == [0u8; 8] {
                return reports;
            }
        } else if self.route_state.primary_modifier_mirror_active {
            self.route_state.primary_modifier_mirror_active = report[0] != 0;
            reports.push(routed(KIND_KEYBOARD, primary_modifier_report(&report)));
        }
        self.route_state.primary_key_active = false;
        self.route_state.us_sub_key_active = report != [0; 8];
        reports.push(routed(KIND_US_SUB_KEYBOARD, report));
        reports
    }
}

fn routed(kind: u8, report: [u8; 8]) -> RoutedReport {
    RoutedReport { kind, report }
}

fn report_has_usage(report: &[u8; 8], usage: u8) -> bool {
    report[2..8].iter().any(|key| *key == usage)
}

fn report_is_internal_zenkaku_hankaku(report: &[u8; 8]) -> bool {
    report[1] == JIS_ZENKAKU_HANKAKU_INTERNAL_MARKER
        && report_has_usage(report, JIS_ZENKAKU_HANKAKU_HID_USAGE)
}

fn clear_report_reserved_byte(mut report: [u8; 8]) -> [u8; 8] {
    report[1] = 0;
    report
}

fn report_has_split_keyboard_switch_key(report: &[u8; 8]) -> bool {
    report[2..8].iter().any(|key| (0x87..0x99).contains(key))
}

fn report_has_jis_special_on_main_key(report: &[u8; 8]) -> bool {
    report[2..8].iter().any(|key| {
        matches!(
            *key,
            0x87 | 0x88 | 0x89 | 0x8a | 0x8b | 0x8c | 0x8d | 0x8e | 0x8f
        )
    })
}

fn report_is_modifier_only(report: &[u8; 8]) -> bool {
    report[0] != 0 && report[1] == 0 && report[2..8].iter().all(|key| *key == 0)
}

fn primary_modifier_report(report: &[u8; 8]) -> [u8; 8] {
    [report[0], 0, 0, 0, 0, 0, 0, 0]
}

fn xor_checksum(data: &[u8]) -> u8 {
    data.iter().fold(0u8, |acc, byte| acc ^ byte)
}

fn encode_broker_frame(kind: u8, payload: &[u8]) -> Result<[u8; FRAME_SIZE], String> {
    if payload.len() > PAYLOAD_CAPACITY {
        return Err("payload too large".to_string());
    }
    let expected = match kind {
        KIND_KEYBOARD | KIND_US_SUB_KEYBOARD => 8,
        _ => return Err(format!("unsupported broker kind: {kind}")),
    };
    if payload.len() != expected {
        return Err(format!(
            "invalid payload length: got={} expected={expected}",
            payload.len()
        ));
    }
    let mut frame = [0u8; FRAME_SIZE];
    frame[0..4].copy_from_slice(b"CQAU");
    frame[4] = 0x01;
    frame[5] = kind;
    frame[6] = payload.len() as u8;
    frame[7] = 0;
    frame[PAYLOAD_OFFSET..PAYLOAD_OFFSET + payload.len()].copy_from_slice(payload);
    frame[CHECKSUM_OFFSET] = xor_checksum(&frame[..CHECKSUM_OFFSET]);
    Ok(frame)
}

fn kind_name(kind: u8) -> &'static str {
    match kind {
        KIND_KEYBOARD => "keyboard",
        KIND_US_SUB_KEYBOARD => "us_sub_keyboard",
        _ => "unknown",
    }
}

fn route_mode_name(route: RouteMode) -> &'static str {
    match route {
        RouteMode::Disabled => "disabled",
        RouteMode::ImeKeys => "ime_keys",
        RouteMode::All => "all",
        RouteMode::JisSpecialUsDefault => "jis_special_us_default",
    }
}

fn injected_route_from_request(value: Option<&str>) -> Result<InjectedRoute, String> {
    match value.unwrap_or("") {
        "" | "normal" | "auto" | "split" => Ok(InjectedRoute::Normal),
        "keyboard" | "main_keyboard" | "jis_keyboard" => Ok(InjectedRoute::Keyboard),
        "us_sub_keyboard" | "us_sub" => Ok(InjectedRoute::UsSubKeyboard),
        other => Err(format!("unsupported injected route: {other}")),
    }
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn load_core_from_env() -> Result<Core, String> {
    let root = repo_root();
    let keymap_path = env_path(
        "LOGICD_CORE_KEYMAP_PATH",
        PathBuf::from("/mnt/p3/keymap.json"),
    );
    let default_keymap_path = env_path(
        "LOGICD_CORE_DEFAULT_KEYMAP_PATH",
        root.join("config/default/keymap.json"),
    );
    let keycodes_path = env_path(
        "LOGICD_CORE_KEYCODES_PATH",
        PathBuf::from("/mnt/p3/keycodes.json"),
    );
    let default_keycodes_path = env_path(
        "LOGICD_CORE_DEFAULT_KEYCODES_PATH",
        root.join("config/default/keycodes.json"),
    );
    let keycodes = load_keycodes(&keycodes_path, &default_keycodes_path)?;
    let layers = load_layers(&keymap_path, &default_keymap_path)?;
    let config_path = env_path(
        "LOGICD_CORE_CONFIG_PATH",
        PathBuf::from("/mnt/p3/config.json"),
    );
    let default_config_path = env_path(
        "LOGICD_CORE_DEFAULT_CONFIG_PATH",
        root.join("config/default/config.json"),
    );
    let routing = load_routing_config(&config_path, &default_config_path)?;
    Ok(Core::new(keycodes, layers, routing))
}

fn load_config_from_env(exit_after_packets: Option<u64>) -> Config {
    Config {
        matrix_socket: env_path(
            "LOGICD_CORE_MATRIX_SOCKET",
            PathBuf::from("/tmp/matrix_events_shadow.sock"),
        ),
        ctrl_socket: env_path(
            "LOGICD_CORE_CTRL_SOCKET",
            PathBuf::from("/tmp/logicd_core_ctrl.sock"),
        ),
        delegate_socket: env_optional_path(
            "LOGICD_CORE_DELEGATE_SOCKET",
            Some(PathBuf::from("/tmp/logicd_delegate_events.sock")),
        ),
        matrix_tap_socket: env_optional_path(
            "LOGICD_CORE_MATRIX_TAP_SOCKET",
            Some(PathBuf::from("/tmp/matrix_tap_events.sock")),
        ),
        hid_report_socket: env_path(
            "LOGICD_CORE_HID_REPORT_SOCKET",
            PathBuf::from("/tmp/usbd_hid_reports.sock"),
        ),
        status_path: env_path(
            "LOGICD_CORE_STATUS_PATH",
            PathBuf::from("/run/hidloom/logicd-core-status.json"),
        ),
        output_enabled: env_bool("LOGICD_CORE_OUTPUT_ENABLED", false),
        matrix_socket_mode: env_u32("LOGICD_CORE_MATRIX_SOCKET_MODE", 0o666, 0, 0o777),
        ctrl_socket_mode: env_u32("LOGICD_CORE_CTRL_SOCKET_MODE", 0o660, 0, 0o777),
        preview_log_path: env::var("LOGICD_CORE_PREVIEW_LOG_PATH")
            .ok()
            .filter(|value| !value.is_empty())
            .map(PathBuf::from),
        idle_poll_interval: Duration::from_millis(u64::from(env_u32(
            "LOGICD_CORE_IDLE_POLL_MS",
            1,
            0,
            100,
        ))),
        exit_after_packets,
    }
}

fn status_payload(core: &Core, config: &Config, broker_available: bool, last_error: &str) -> Value {
    json!({
        "schema": "logicd-core.status.v1",
        "process": true,
        "mode": "shadow",
        "output_enabled": config.output_enabled,
        "matrix_socket": {
            "path": config.matrix_socket,
            "listening": true,
        },
        "ctrl_socket": {
            "path": config.ctrl_socket,
            "listening": true,
        },
        "delegate_socket": {
            "path": config.delegate_socket,
            "enabled": config.delegate_socket.is_some(),
        },
        "matrix_tap_socket": {
            "path": config.matrix_tap_socket,
            "enabled": config.matrix_tap_socket.is_some(),
        },
        "broker_socket": {
            "path": config.hid_report_socket,
            "available": broker_available,
            "last_error": last_error,
        },
        "preview_log": {
            "path": config.preview_log_path,
        },
        "runtime": {
            "idle_poll_ms": config.idle_poll_interval.as_millis(),
        },
        "keymap": {
            "layers": core.layers.len(),
            "warnings": [],
        },
        "state": {
            "pressed_matrix": core.pressed_matrix.len(),
            "injected_keys": core.injected_keys.len(),
            "force_delegate_all": core.force_delegate_all,
            "pressed_keys": core.hid.pressed_key_count(),
            "modifier": core.hid.modifiers,
            "active_layers": core.active_layers(),
            "layers": {
                "default": core.default_layer,
                "momentary": sorted_layers(&core.momentary_layers),
                "toggled": sorted_layers(&core.toggled_layers),
                "oneshot": sorted_layers(&core.oneshot_layers),
                "all": core.active_layers(),
            },
        },
        "routing": {
            "matrix_delegate_all": core.force_delegate_all,
            "usb_split_keyboard": core.routing.split_keyboard_enabled,
            "route": route_mode_name(core.routing.route_mode),
            "state": {
                "us_sub_key_active": core.route_state.us_sub_key_active,
                "primary_key_active": core.route_state.primary_key_active,
                "primary_modifier_mirror_active": core.route_state.primary_modifier_mirror_active,
                "zenkaku_hankaku_active": core.route_state.zenkaku_hankaku_active,
            },
        },
        "counters": {
            "matrix_events": core.counters.matrix_events,
            "ignored_duplicates": core.counters.ignored_duplicates,
            "unsupported_actions": core.counters.unsupported_actions,
            "delegated_actions": core.counters.delegated_actions,
            "delegate_errors": core.counters.delegate_errors,
            "matrix_tap_events": core.counters.matrix_tap_events,
            "matrix_tap_errors": core.counters.matrix_tap_errors,
            "injected_key_events": core.counters.injected_key_events,
            "injected_duplicates": core.counters.injected_duplicates,
            "rollover_drops": core.counters.rollover_drops,
            "report_previews": core.counters.reports_emitted,
            "broker_frames_sent": core.counters.broker_frames_sent,
        }
    })
}

fn write_status(core: &Core, config: &Config, broker_available: bool, last_error: &str) {
    let payload = status_payload(core, config, broker_available, last_error);
    write_json_atomic(&config.status_path, &payload);
}

fn write_json_atomic(path: &Path, payload: &Value) {
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let tmp = path.with_extension("json.tmp");
    if fs::write(&tmp, payload.to_string()).is_ok() {
        let _ = fs::rename(tmp, path);
    }
}

fn write_preview_log(
    config: &Config,
    seq: u64,
    event: &MatrixEvent,
    routed_report: &RoutedReport,
) -> Result<(), String> {
    let Some(path) = &config.preview_log_path else {
        return Ok(());
    };
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|err| format!("failed to create preview log directory: {err}"))?;
    }
    let frame = encode_broker_frame(routed_report.kind, &routed_report.report)?;
    let line = json!({
        "t": "shadow_report",
        "seq": seq,
        "kind": routed_report.kind,
        "kind_name": kind_name(routed_report.kind),
        "event": {
            "kind": if event.press { "P" } else { "R" },
            "row": event.row,
            "col": event.col,
        },
        "report": hex(&routed_report.report),
        "frame": hex(&frame),
    });
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .map_err(|err| format!("failed to open preview log {}: {err}", path.display()))?;
    writeln!(file, "{line}")
        .map_err(|err| format!("failed to write preview log {}: {err}", path.display()))
}

fn send_broker_frame(
    socket: &UnixDatagram,
    config: &Config,
    routed_report: &RoutedReport,
) -> Result<(), String> {
    if !config.output_enabled {
        return Ok(());
    }
    let frame = encode_broker_frame(routed_report.kind, &routed_report.report)?;
    socket
        .send_to(&frame, &config.hid_report_socket)
        .map(|_| ())
        .map_err(|err| format!("failed to send broker frame: {err}"))
}

fn emit_report(
    broker: &UnixDatagram,
    config: &Config,
    core: &mut Core,
    routed_report: &RoutedReport,
    last_broker_error: &mut String,
) {
    match send_broker_frame(broker, config, routed_report) {
        Ok(()) => {
            if config.output_enabled {
                core.counters.broker_frames_sent += 1;
            }
            last_broker_error.clear()
        }
        Err(err) => {
            *last_broker_error = err;
            eprintln!("warning: {}", last_broker_error);
        }
    }
}

fn delegate_matrix_packet(core: &mut Core, config: &Config, packet: [u8; 4]) {
    let Some(path) = config.delegate_socket.as_ref() else {
        core.counters.delegate_errors += 1;
        return;
    };
    match UnixStream::connect(path) {
        Ok(mut stream) => {
            if let Err(err) = stream.write_all(&packet) {
                core.counters.delegate_errors += 1;
                eprintln!(
                    "warning: failed to write delegated matrix event to {}: {err}",
                    path.display()
                );
            }
        }
        Err(err) => {
            core.counters.delegate_errors += 1;
            eprintln!(
                "warning: failed to connect delegated matrix socket {}: {err}",
                path.display()
            );
        }
    }
}

fn tap_matrix_packet(core: &mut Core, config: &Config, packet: [u8; 4]) {
    let Some(path) = config.matrix_tap_socket.as_ref() else {
        return;
    };
    match UnixStream::connect(path) {
        Ok(mut stream) => {
            if let Err(err) = stream.write_all(&packet) {
                core.counters.matrix_tap_errors += 1;
                eprintln!(
                    "warning: failed to write matrix tap event to {}: {err}",
                    path.display()
                );
            } else {
                core.counters.matrix_tap_events += 1;
            }
        }
        Err(err) => {
            core.counters.matrix_tap_errors += 1;
            eprintln!(
                "warning: failed to connect matrix tap socket {}: {err}",
                path.display()
            );
        }
    }
}

fn handle_ctrl_line(
    line: &[u8],
    core: &mut Core,
    config: &mut Config,
    broker: &UnixDatagram,
    last_broker_error: &mut String,
) -> Value {
    let parsed = serde_json::from_slice::<Value>(line);
    let Ok(request) = parsed else {
        return json!({"result": "error", "error": "invalid_json"});
    };
    let command = request.get("t").and_then(Value::as_str).unwrap_or("");
    match command {
        "status" => status_payload(
            core,
            config,
            config.output_enabled && last_broker_error.is_empty(),
            last_broker_error,
        ),
        "release_all" => {
            let emitted = core.release_all();
            for report in &emitted {
                emit_report(broker, config, core, report, last_broker_error);
            }
            json!({"result": "ok", "released": !emitted.is_empty()})
        }
        "set_output" => {
            let Some(enabled) = request.get("enabled").and_then(Value::as_bool) else {
                return json!({"result": "error", "error": "enabled_required"});
            };
            config.output_enabled = enabled;
            json!({"result": "ok", "output_enabled": config.output_enabled})
        }
        "set_matrix_delegate_all" => {
            let Some(enabled) = request.get("enabled").and_then(Value::as_bool) else {
                return json!({"result": "error", "error": "enabled_required"});
            };
            let emitted = core.release_all();
            for report in &emitted {
                emit_report(broker, config, core, report, last_broker_error);
            }
            core.force_delegate_all = enabled;
            json!({
                "result": "ok",
                "matrix_delegate_all": core.force_delegate_all,
                "released": !emitted.is_empty(),
            })
        }
        "key_event" => {
            let Some(action) = request.get("action").and_then(Value::as_str) else {
                return json!({"result": "error", "error": "action_required"});
            };
            let Some(is_press) = request
                .get("is_press")
                .or_else(|| request.get("pressed"))
                .and_then(Value::as_bool)
            else {
                return json!({"result": "error", "error": "is_press_required"});
            };
            let id = request.get("id").and_then(Value::as_str).unwrap_or("");
            let route =
                match injected_route_from_request(request.get("route").and_then(Value::as_str)) {
                    Ok(route) => route,
                    Err(err) => return json!({"result": "error", "error": err}),
                };
            match core.apply_injected_key_event_with_route(id, action, is_press, route) {
                Ok(reports) => {
                    let emitted_count = reports.len();
                    for report in &reports {
                        emit_report(broker, config, core, report, last_broker_error);
                    }
                    json!({"result": "ok", "emitted": emitted_count})
                }
                Err(err) => json!({"result": "error", "error": err}),
            }
        }
        "reload" => match load_core_from_env() {
            Ok(new_core) => {
                for report in core.release_all() {
                    emit_report(broker, config, core, &report, last_broker_error);
                }
                let counters = std::mem::take(&mut core.counters);
                *core = new_core;
                core.counters = counters;
                json!({"result": "ok", "layers": core.layers.len(), "keycodes": core.keycodes.len()})
            }
            Err(err) => json!({"result": "error", "error": err}),
        },
        _ => json!({"result": "error", "error": "unknown_command"}),
    }
}

fn flush_pending<W: Write>(writer: &mut W, pending: &mut Vec<u8>) -> io::Result<bool> {
    while !pending.is_empty() {
        match writer.write(pending) {
            Ok(0) => {
                return Err(io::Error::new(
                    ErrorKind::WriteZero,
                    "control response write returned zero",
                ));
            }
            Ok(written) => {
                pending.drain(..written);
            }
            Err(err) if err.kind() == ErrorKind::Interrupted => continue,
            Err(err) if err.kind() == ErrorKind::WouldBlock => return Ok(false),
            Err(err) => return Err(err),
        }
    }
    Ok(true)
}

fn accept_pending(listener: &UnixListener, clients: &mut Vec<StreamClient>, label: &str) {
    loop {
        match listener.accept() {
            Ok((stream, _addr)) => {
                let _ = stream.set_nonblocking(true);
                clients.push(StreamClient::new(stream));
            }
            Err(err) if err.kind() == ErrorKind::WouldBlock => break,
            Err(err) => {
                eprintln!("warning: failed to accept {label} client: {err}");
                break;
            }
        }
    }
}

fn serve(mut config: Config) -> Result<(), String> {
    let mut core = load_core_from_env()?;
    let _ = fs::remove_file(&config.matrix_socket);
    let _ = fs::remove_file(&config.ctrl_socket);
    let matrix_listener = UnixListener::bind(&config.matrix_socket)
        .map_err(|err| format!("failed to bind {}: {err}", config.matrix_socket.display()))?;
    matrix_listener
        .set_nonblocking(true)
        .map_err(|err| format!("failed to set matrix listener nonblocking: {err}"))?;
    let _ = fs::set_permissions(
        &config.matrix_socket,
        fs::Permissions::from_mode(config.matrix_socket_mode),
    );
    let ctrl_listener = UnixListener::bind(&config.ctrl_socket)
        .map_err(|err| format!("failed to bind {}: {err}", config.ctrl_socket.display()))?;
    ctrl_listener
        .set_nonblocking(true)
        .map_err(|err| format!("failed to set ctrl listener nonblocking: {err}"))?;
    let _ = fs::set_permissions(
        &config.ctrl_socket,
        fs::Permissions::from_mode(config.ctrl_socket_mode),
    );
    let broker =
        UnixDatagram::unbound().map_err(|err| format!("failed to open datagram socket: {err}"))?;
    let mut last_broker_error = String::new();
    write_status(&core, &config, false, "");

    let mut processed = 0u64;
    let mut matrix_clients: Vec<StreamClient> = Vec::new();
    let mut ctrl_clients: Vec<StreamClient> = Vec::new();
    let mut should_exit = false;
    while !should_exit {
        accept_pending(&matrix_listener, &mut matrix_clients, "matrix");
        accept_pending(&ctrl_listener, &mut ctrl_clients, "ctrl");

        let mut index = 0;
        while index < matrix_clients.len() {
            let mut remove = false;
            let mut buf = [0u8; 256];
            loop {
                match matrix_clients[index].stream.read(&mut buf) {
                    Ok(0) => {
                        remove = true;
                        break;
                    }
                    Ok(n) => {
                        matrix_clients[index].input.extend_from_slice(&buf[..n]);
                        while matrix_clients[index].input.len() >= 4 {
                            let packet: Vec<u8> = matrix_clients[index].input.drain(..4).collect();
                            let event = match parse_matrix_packet(&packet) {
                                Ok(event) => event,
                                Err(err) => {
                                    eprintln!("warning: dropping invalid matrix packet: {err}");
                                    continue;
                                }
                            };
                            let outcome = core.apply_event(event);
                            if let Some(packet) = outcome.delegate_packet {
                                delegate_matrix_packet(&mut core, &config, packet);
                            }
                            if let Some(packet) = outcome.tap_packet {
                                tap_matrix_packet(&mut core, &config, packet);
                            }
                            let reports = outcome.reports;
                            let preview_start = core
                                .counters
                                .reports_emitted
                                .saturating_sub(reports.len() as u64)
                                + 1;
                            for (offset, report) in reports.iter().enumerate() {
                                let preview_seq = preview_start + offset as u64;
                                if let Err(err) =
                                    write_preview_log(&config, preview_seq, &event, report)
                                {
                                    eprintln!("warning: {err}");
                                }
                                emit_report(
                                    &broker,
                                    &config,
                                    &mut core,
                                    report,
                                    &mut last_broker_error,
                                );
                            }
                            processed += 1;
                            write_status(
                                &core,
                                &config,
                                config.output_enabled && last_broker_error.is_empty(),
                                &last_broker_error,
                            );
                            if config
                                .exit_after_packets
                                .is_some_and(|limit| processed >= limit)
                            {
                                should_exit = true;
                                break;
                            }
                        }
                    }
                    Err(err) if err.kind() == ErrorKind::WouldBlock => break,
                    Err(err) => {
                        eprintln!("warning: failed to read matrix event: {err}");
                        remove = true;
                        break;
                    }
                }
                if should_exit {
                    break;
                }
            }
            if remove {
                let _ = matrix_clients.remove(index);
            } else {
                index += 1;
            }
        }

        let mut ctrl_index = 0;
        while ctrl_index < ctrl_clients.len() {
            let mut remove = false;
            let mut buf = [0u8; 256];
            while !ctrl_clients[ctrl_index].read_closed {
                match ctrl_clients[ctrl_index].stream.read(&mut buf) {
                    Ok(0) => {
                        ctrl_clients[ctrl_index].read_closed = true;
                        break;
                    }
                    Ok(n) => {
                        ctrl_clients[ctrl_index].input.extend_from_slice(&buf[..n]);
                        while let Some(pos) = ctrl_clients[ctrl_index]
                            .input
                            .iter()
                            .position(|byte| *byte == b'\n')
                        {
                            let mut line: Vec<u8> =
                                ctrl_clients[ctrl_index].input.drain(..=pos).collect();
                            if line.ends_with(b"\n") {
                                line.pop();
                            }
                            let response = handle_ctrl_line(
                                &line,
                                &mut core,
                                &mut config,
                                &broker,
                                &mut last_broker_error,
                            );
                            let mut encoded = response.to_string().into_bytes();
                            encoded.push(b'\n');
                            ctrl_clients[ctrl_index].output.extend_from_slice(&encoded);
                            write_status(
                                &core,
                                &config,
                                config.output_enabled && last_broker_error.is_empty(),
                                &last_broker_error,
                            );
                        }
                    }
                    Err(err) if err.kind() == ErrorKind::WouldBlock => break,
                    Err(err) => {
                        eprintln!("warning: failed to read ctrl command: {err}");
                        remove = true;
                        break;
                    }
                }
            }
            if !remove && !ctrl_clients[ctrl_index].output.is_empty() {
                let flush_result = {
                    let client = &mut ctrl_clients[ctrl_index];
                    flush_pending(&mut client.stream, &mut client.output)
                };
                if let Err(err) = flush_result {
                    eprintln!("warning: failed to write ctrl response: {err}");
                    remove = true;
                }
            }
            if !remove
                && ctrl_clients[ctrl_index].read_closed
                && ctrl_clients[ctrl_index].output.is_empty()
            {
                remove = true;
            }
            if remove {
                let _ = ctrl_clients.remove(ctrl_index);
            } else {
                ctrl_index += 1;
            }
        }

        if !should_exit && !config.idle_poll_interval.is_zero() {
            thread::sleep(config.idle_poll_interval);
        }
    }
    let _ = fs::remove_file(&config.matrix_socket);
    let _ = fs::remove_file(&config.ctrl_socket);
    write_status(
        &core,
        &config,
        config.output_enabled && last_broker_error.is_empty(),
        &last_broker_error,
    );
    Ok(())
}

fn replay_file(path: &Path) -> Result<(), String> {
    let mut core = load_core_from_env()?;
    let data = fs::read(path).map_err(|err| format!("failed to read {}: {err}", path.display()))?;
    if data.len() % 4 != 0 {
        return Err(format!(
            "matrix replay length must be multiple of 4: {}",
            data.len()
        ));
    }
    for packet in data.chunks_exact(4) {
        let event = parse_matrix_packet(packet)?;
        let outcome = core.apply_event(event);
        if let Some(packet) = outcome.delegate_packet {
            println!(
                "{}",
                json!({
                    "t": "delegated_matrix_event",
                    "packet": hex(&packet),
                    "event": {
                        "kind": if event.press { "P" } else { "R" },
                        "row": event.row,
                        "col": event.col,
                    },
                })
            );
        }
        for report in outcome.reports {
            let frame = encode_broker_frame(report.kind, &report.report)?;
            println!(
                "{}",
                json!({
                    "t": "keyboard_report",
                    "kind": report.kind,
                    "kind_name": kind_name(report.kind),
                    "report": hex(&report.report),
                    "frame": hex(&frame),
                })
            );
        }
    }
    eprintln!(
        "{}",
        json!({
            "t": "summary",
            "matrix_events": core.counters.matrix_events,
            "ignored_duplicates": core.counters.ignored_duplicates,
            "unsupported_actions": core.counters.unsupported_actions,
            "delegated_actions": core.counters.delegated_actions,
            "delegate_errors": core.counters.delegate_errors,
            "rollover_drops": core.counters.rollover_drops,
            "reports_emitted": core.counters.reports_emitted,
        })
    );
    Ok(())
}

fn check_config() -> Result<(), String> {
    let core = load_core_from_env()?;
    println!(
        "{}",
        json!({
            "schema": "logicd-core.status.v1",
            "mode": "fixture",
            "layers": core.layers.len(),
            "keycodes": core.keycodes.len(),
            "routing": {
                "usb_split_keyboard": core.routing.split_keyboard_enabled,
                "route": route_mode_name(core.routing.route_mode),
            },
        })
    );
    Ok(())
}

fn send_ctrl_command(socket_path: &Path, command: Value) -> Result<(), String> {
    let mut stream = UnixStream::connect(socket_path).map_err(|err| {
        format!(
            "failed to connect ctrl socket {}: {err}",
            socket_path.display()
        )
    })?;
    writeln!(stream, "{command}").map_err(|err| format!("failed to write ctrl command: {err}"))?;
    let mut reader = BufReader::new(stream);
    let mut response = String::new();
    reader
        .read_line(&mut response)
        .map_err(|err| format!("failed to read ctrl response: {err}"))?;
    if response.trim().is_empty() {
        return Err("empty ctrl response".to_string());
    }
    let value = serde_json::from_str::<Value>(response.trim())
        .map_err(|err| format!("invalid ctrl response: {err}: {response}"))?;
    if value.get("result").and_then(Value::as_str) == Some("error") {
        return Err(format!("ctrl command failed: {value}"));
    }
    println!("{value}");
    Ok(())
}

fn upsert_socket_stopped(payload: &mut Value, name: &str, path: &Path) {
    let Some(object) = payload.as_object_mut() else {
        return;
    };
    let socket = object
        .entry(name.to_string())
        .or_insert_with(|| json!({}))
        .as_object_mut();
    if let Some(socket_object) = socket {
        socket_object.insert(
            "path".to_string(),
            Value::String(path.to_string_lossy().to_string()),
        );
        socket_object.insert("listening".to_string(), Value::Bool(false));
    }
}

fn mark_stopped(config: &Config) -> Result<(), String> {
    let _ = fs::remove_file(&config.matrix_socket);
    let _ = fs::remove_file(&config.ctrl_socket);
    let mut payload = fs::read_to_string(&config.status_path)
        .ok()
        .and_then(|raw| serde_json::from_str::<Value>(&raw).ok())
        .filter(Value::is_object)
        .unwrap_or_else(|| json!({}));
    let object = payload
        .as_object_mut()
        .ok_or_else(|| "failed to build stopped status".to_string())?;
    object.insert(
        "schema".to_string(),
        Value::String("logicd-core.status.v1".to_string()),
    );
    object.insert("process".to_string(), Value::Bool(false));
    object.insert("mode".to_string(), Value::String("shadow".to_string()));
    upsert_socket_stopped(&mut payload, "matrix_socket", &config.matrix_socket);
    upsert_socket_stopped(&mut payload, "ctrl_socket", &config.ctrl_socket);
    write_json_atomic(&config.status_path, &payload);
    println!("{}", json!({"result": "ok", "marked_stopped": true}));
    Ok(())
}

fn usage() {
    println!(
        "usage: hidloom-logicd-core --check-config | --replay MATRIX_PACKET_FILE | --serve [--packets N] | --ctrl-release-all | --mark-stopped"
    );
}

fn main() {
    let mut args = env::args().skip(1);
    let result = match args.next().as_deref() {
        Some("--check-config") => check_config(),
        Some("--replay") => {
            let Some(path) = args.next() else {
                usage();
                std::process::exit(2);
            };
            replay_file(Path::new(&path))
        }
        Some("--serve") => {
            let mut packets = None;
            while let Some(arg) = args.next() {
                match arg.as_str() {
                    "--packets" => {
                        let Some(raw) = args.next() else {
                            usage();
                            std::process::exit(2);
                        };
                        match raw.parse::<u64>() {
                            Ok(value) => packets = Some(value),
                            Err(_) => {
                                eprintln!("error: invalid --packets value");
                                std::process::exit(2);
                            }
                        }
                    }
                    other => {
                        eprintln!("error: unknown argument: {other}");
                        usage();
                        std::process::exit(2);
                    }
                }
            }
            serve(load_config_from_env(packets))
        }
        Some("--ctrl-release-all") => {
            let config = load_config_from_env(None);
            send_ctrl_command(&config.ctrl_socket, json!({"t": "release_all"}))
        }
        Some("--mark-stopped") => {
            let config = load_config_from_env(None);
            mark_stopped(&config)
        }
        Some("--help") | None => {
            usage();
            Ok(())
        }
        Some(other) => Err(format!("unknown argument: {other}")),
    };
    if let Err(err) = result {
        eprintln!("error: {err}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct SequencedWriter {
        output: Vec<u8>,
        calls: usize,
    }

    impl Write for SequencedWriter {
        fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
            self.calls += 1;
            if self.calls == 2 {
                return Err(io::Error::from(ErrorKind::WouldBlock));
            }
            let limit = if self.calls == 1 { 1245 } else { 257 };
            let written = buf.len().min(limit);
            self.output.extend_from_slice(&buf[..written]);
            Ok(written)
        }

        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }

    fn test_core(layers: Vec<HashMap<String, String>>) -> Core {
        let mut keycodes = HashMap::new();
        keycodes.insert("KC_A".to_string(), 4);
        keycodes.insert("KC_B".to_string(), 5);
        keycodes.insert("KC_C".to_string(), 6);
        keycodes.insert("KC_D".to_string(), 7);
        keycodes.insert("KC_E".to_string(), 8);
        keycodes.insert("KC_F".to_string(), 9);
        keycodes.insert("KC_G".to_string(), 10);
        keycodes.insert("KC_LSHIFT".to_string(), 0xE1);
        Core::new(keycodes, layers, RoutingConfig::default())
    }

    fn one_report(outcome: EventOutcome) -> [u8; 8] {
        assert!(outcome.delegate_packet.is_none());
        assert_eq!(outcome.reports.len(), 1);
        assert_eq!(outcome.reports[0].kind, KIND_KEYBOARD);
        outcome.reports[0].report
    }

    fn no_output(outcome: EventOutcome) -> bool {
        outcome.reports.is_empty()
            && outcome.delegate_packet.is_none()
            && outcome.tap_packet.is_none()
    }

    fn no_report_with_tap(outcome: EventOutcome) -> [u8; 4] {
        assert!(outcome.reports.is_empty());
        assert!(outcome.delegate_packet.is_none());
        outcome.tap_packet.expect("expected matrix tap packet")
    }

    fn one_delegate(outcome: EventOutcome) -> [u8; 4] {
        assert!(outcome.reports.is_empty());
        assert!(outcome.tap_packet.is_none());
        outcome
            .delegate_packet
            .expect("expected delegated matrix packet")
    }

    fn layer(items: &[(&str, &str)]) -> HashMap<String, String> {
        items
            .iter()
            .map(|(key, value)| ((*key).to_string(), (*value).to_string()))
            .collect()
    }

    fn event(press: bool, row: u8, col: u8) -> MatrixEvent {
        MatrixEvent { press, row, col }
    }

    #[test]
    fn ctrl_response_flush_survives_partial_write_and_would_block() {
        let expected = vec![b'x'; 4097];
        let mut pending = expected.clone();
        let mut writer = SequencedWriter {
            output: Vec::new(),
            calls: 0,
        };

        assert!(!flush_pending(&mut writer, &mut pending).unwrap());
        assert_eq!(writer.output.len(), 1245);
        assert_eq!(pending.len(), expected.len() - 1245);
        assert!(flush_pending(&mut writer, &mut pending).unwrap());
        assert!(pending.is_empty());
        assert_eq!(writer.output, expected);
    }

    #[test]
    fn parses_matrix_packet() {
        assert_eq!(
            parse_matrix_packet(b"P1A\n").unwrap(),
            MatrixEvent {
                press: true,
                row: 1,
                col: 10
            }
        );
        assert!(parse_matrix_packet(b"X1A\n").is_err());
        assert!(parse_matrix_packet(b"P1A!").is_err());
        assert_eq!(
            parse_matrix_packet(b"R0F\0").unwrap(),
            MatrixEvent {
                press: false,
                row: 0,
                col: 15
            }
        );
    }

    #[test]
    fn emits_basic_press_release_reports() {
        let mut core = test_core(vec![layer(&[("0,0", "KC_A")])]);
        assert_eq!(
            one_report(core.apply_event(event(true, 0, 0))),
            [0, 0, 4, 0, 0, 0, 0, 0]
        );
        assert_eq!(one_report(core.apply_event(event(false, 0, 0))), [0; 8]);
    }

    #[test]
    fn handles_modifier_bits() {
        let mut core = test_core(vec![layer(&[("0,0", "KC_LSHIFT"), ("0,1", "KC_A")])]);
        assert_eq!(
            one_report(core.apply_event(event(true, 0, 0))),
            [2, 0, 0, 0, 0, 0, 0, 0]
        );
        assert_eq!(
            one_report(core.apply_event(event(true, 0, 1))),
            [2, 0, 4, 0, 0, 0, 0, 0]
        );
        assert_eq!(
            one_report(core.apply_event(event(false, 0, 0))),
            [0, 0, 4, 0, 0, 0, 0, 0]
        );
    }

    #[test]
    fn qmk_layer_actions_are_native_except_timed_variants() {
        let mut core = test_core(vec![
            layer(&[("0,0", "KC_A"), ("0,1", "MO(1)"), ("0,2", "LT(1,KC_A)")]),
            layer(&[("0,0", "KC_B")]),
        ]);
        assert_eq!(
            no_report_with_tap(core.apply_event(event(true, 0, 1))),
            *b"P01\n"
        );
        assert_eq!(core.active_layers(), vec![1, 0]);
        assert_eq!(
            one_report(core.apply_event(event(true, 0, 0))),
            [0, 0, 5, 0, 0, 0, 0, 0]
        );
        assert_eq!(one_report(core.apply_event(event(false, 0, 0))), [0; 8]);
        assert_eq!(
            no_report_with_tap(core.apply_event(event(false, 0, 1))),
            *b"R01\n"
        );
        assert_eq!(core.active_layers(), vec![0]);
        assert_eq!(one_delegate(core.apply_event(event(true, 0, 2))), *b"P02\n");
        assert_eq!(
            one_delegate(core.apply_event(event(false, 0, 2))),
            *b"R02\n"
        );
        assert_eq!(core.counters.delegated_actions, 2);
    }

    #[test]
    fn delegate_context_sends_following_keys_to_companion() {
        let mut core = test_core(vec![
            layer(&[("0,0", "KC_A"), ("0,1", "LT(1,KC_A)")]),
            layer(&[("0,0", "KC_B")]),
        ]);
        assert_eq!(one_delegate(core.apply_event(event(true, 0, 1))), *b"P01\n");
        assert_eq!(one_delegate(core.apply_event(event(true, 0, 0))), *b"P00\n");
        assert_eq!(
            one_delegate(core.apply_event(event(false, 0, 0))),
            *b"R00\n"
        );
        assert_eq!(
            one_delegate(core.apply_event(event(false, 0, 1))),
            *b"R01\n"
        );
        assert_eq!(core.hid.build(), [0; 8]);
    }

    #[test]
    fn toggle_to_default_and_oneshot_layers_affect_resolution() {
        let layers = vec![
            layer(&[
                ("0,0", "KC_A"),
                ("0,1", "TG(1)"),
                ("0,2", "TO(2)"),
                ("0,3", "DF(1)"),
                ("0,4", "OSL(2)"),
            ]),
            layer(&[("0,0", "KC_B")]),
            layer(&[("0,0", "KC_C")]),
        ];

        let mut core = test_core(layers.clone());
        assert_eq!(
            no_report_with_tap(core.apply_event(event(true, 0, 1))),
            *b"P01\n"
        );
        assert_eq!(core.active_layers(), vec![1, 0]);
        assert_eq!(
            no_report_with_tap(core.apply_event(event(false, 0, 1))),
            *b"R01\n"
        );
        assert_eq!(
            one_report(core.apply_event(event(true, 0, 0))),
            [0, 0, 5, 0, 0, 0, 0, 0]
        );
        assert_eq!(one_report(core.apply_event(event(false, 0, 0))), [0; 8]);

        let mut core = test_core(layers.clone());
        assert_eq!(
            no_report_with_tap(core.apply_event(event(true, 0, 2))),
            *b"P02\n"
        );
        assert_eq!(core.active_layers(), vec![2, 0]);
        assert_eq!(
            no_report_with_tap(core.apply_event(event(false, 0, 2))),
            *b"R02\n"
        );
        assert_eq!(
            one_report(core.apply_event(event(true, 0, 0))),
            [0, 0, 6, 0, 0, 0, 0, 0]
        );
        assert_eq!(one_report(core.apply_event(event(false, 0, 0))), [0; 8]);

        let mut core = test_core(layers.clone());
        assert_eq!(
            no_report_with_tap(core.apply_event(event(true, 0, 3))),
            *b"P03\n"
        );
        assert_eq!(core.active_layers(), vec![1, 0]);
        assert_eq!(
            no_report_with_tap(core.apply_event(event(false, 0, 3))),
            *b"R03\n"
        );
        assert_eq!(
            one_report(core.apply_event(event(true, 0, 0))),
            [0, 0, 5, 0, 0, 0, 0, 0]
        );
        assert_eq!(one_report(core.apply_event(event(false, 0, 0))), [0; 8]);

        let mut core = test_core(layers);
        assert_eq!(
            no_report_with_tap(core.apply_event(event(true, 0, 4))),
            *b"P04\n"
        );
        assert_eq!(core.active_layers(), vec![2, 0]);
        assert_eq!(
            no_report_with_tap(core.apply_event(event(false, 0, 4))),
            *b"R04\n"
        );
        assert_eq!(
            one_report(core.apply_event(event(true, 0, 0))),
            [0, 0, 6, 0, 0, 0, 0, 0]
        );
        assert_eq!(core.active_layers(), vec![0]);
        assert_eq!(one_report(core.apply_event(event(false, 0, 0))), [0; 8]);
    }

    #[test]
    fn injected_key_events_merge_with_core_held_keys() {
        let mut core = test_core(vec![layer(&[("0,0", "KC_A")])]);
        assert_eq!(
            one_report(core.apply_event(event(true, 0, 0))),
            [0, 0, 4, 0, 0, 0, 0, 0]
        );
        let reports = core
            .apply_injected_key_event("helper:0,1:KC_B", "KC_B", true)
            .unwrap();
        assert_eq!(reports.len(), 1);
        assert_eq!(reports[0].report, [0, 0, 4, 5, 0, 0, 0, 0]);
        let reports = core
            .apply_injected_key_event("helper:0,1:KC_B", "KC_B", false)
            .unwrap();
        assert_eq!(reports.len(), 1);
        assert_eq!(reports[0].report, [0, 0, 4, 0, 0, 0, 0, 0]);
    }

    #[test]
    fn injected_same_usage_release_preserves_core_source() {
        let mut core = test_core(vec![layer(&[("0,0", "KC_A")])]);
        assert_eq!(
            one_report(core.apply_event(event(true, 0, 0))),
            [0, 0, 4, 0, 0, 0, 0, 0]
        );
        assert!(
            core.apply_injected_key_event("helper:0,1:KC_A", "KC_A", true)
                .unwrap()
                .is_empty()
        );
        assert!(
            core.apply_injected_key_event("helper:0,1:KC_A", "KC_A", false)
                .unwrap()
                .is_empty()
        );
        assert_eq!(core.hid.build(), [0, 0, 4, 0, 0, 0, 0, 0]);
    }

    #[test]
    fn release_all_clears_injected_keys_together_with_matrix_keys() {
        let mut core = test_core(vec![layer(&[("0,0", "KC_A")])]);
        assert_eq!(
            one_report(core.apply_event(event(true, 0, 0))),
            [0, 0, 4, 0, 0, 0, 0, 0]
        );
        assert_eq!(
            core.apply_injected_key_event("helper:0,1:KC_B", "KC_B", true)
                .unwrap()[0]
                .report,
            [0, 0, 4, 5, 0, 0, 0, 0]
        );
        let reports = core.release_all();
        assert_eq!(reports.len(), 1);
        assert_eq!(reports[0].report, [0; 8]);
        assert!(core.pressed_matrix.is_empty());
        assert!(core.injected_keys.is_empty());
        assert_eq!(core.hid.build(), [0; 8]);
    }

    #[test]
    fn duplicate_injected_edges_do_not_toggle_host_state() {
        let mut core = test_core(vec![layer(&[])]);
        let reports = core
            .apply_injected_key_event("helper:0,1:KC_B", "KC_B", true)
            .unwrap();
        assert_eq!(reports[0].report, [0, 0, 5, 0, 0, 0, 0, 0]);
        assert!(
            core.apply_injected_key_event("helper:0,1:KC_B", "KC_B", true)
                .unwrap()
                .is_empty()
        );
        let reports = core
            .apply_injected_key_event("helper:0,1:KC_B", "KC_B", false)
            .unwrap();
        assert_eq!(reports[0].report, [0; 8]);
        assert!(
            core.apply_injected_key_event("helper:0,1:KC_B", "KC_B", false)
                .unwrap()
                .is_empty()
        );
        assert_eq!(core.counters.injected_duplicates, 2);
    }

    #[test]
    fn injected_modifiers_merge_with_core_keys() {
        let mut core = test_core(vec![layer(&[("0,0", "KC_A")])]);
        assert_eq!(
            one_report(core.apply_event(event(true, 0, 0))),
            [0, 0, 4, 0, 0, 0, 0, 0]
        );
        let reports = core
            .apply_injected_key_event("helper:0,1:KC_LSHIFT", "KC_LSHIFT", true)
            .unwrap();
        assert_eq!(reports[0].report, [2, 0, 4, 0, 0, 0, 0, 0]);
        let reports = core
            .apply_injected_key_event("helper:0,1:KC_LSHIFT", "KC_LSHIFT", false)
            .unwrap();
        assert_eq!(reports[0].report, [0, 0, 4, 0, 0, 0, 0, 0]);
    }

    #[test]
    fn injected_key_event_can_force_us_sub_keyboard_route() {
        let mut core = test_core(vec![layer(&[])]);
        core.routing = RoutingConfig {
            split_keyboard_enabled: true,
            route_mode: RouteMode::JisSpecialUsDefault,
        };
        let reports = core
            .apply_injected_key_event_with_route(
                "pty_terminal_mirror:none:KC_A",
                "KC_A",
                true,
                InjectedRoute::UsSubKeyboard,
            )
            .unwrap();
        assert_eq!(reports.len(), 1);
        assert_eq!(reports[0].kind, KIND_US_SUB_KEYBOARD);
        assert_eq!(reports[0].report, [0, 0, 4, 0, 0, 0, 0, 0]);
        let reports = core
            .apply_injected_key_event_with_route(
                "pty_terminal_mirror:none:KC_A",
                "KC_A",
                false,
                InjectedRoute::UsSubKeyboard,
            )
            .unwrap();
        assert_eq!(reports.len(), 1);
        assert_eq!(reports[0].kind, KIND_US_SUB_KEYBOARD);
        assert_eq!(reports[0].report, [0; 8]);
    }

    #[test]
    fn release_all_clears_stale_us_sub_injected_route() {
        let mut core = test_core(vec![layer(&[])]);
        core.routing = RoutingConfig {
            split_keyboard_enabled: true,
            route_mode: RouteMode::JisSpecialUsDefault,
        };
        let reports = core
            .apply_injected_key_event_with_route(
                "pty_terminal_mirror:none:KC_B",
                "KC_B",
                true,
                InjectedRoute::UsSubKeyboard,
            )
            .unwrap();
        assert_eq!(reports.len(), 1);
        assert_eq!(reports[0].kind, KIND_US_SUB_KEYBOARD);
        assert_eq!(reports[0].report, [0, 0, 5, 0, 0, 0, 0, 0]);
        assert!(core.route_state.us_sub_key_active);

        let reports = core.release_all();
        assert_eq!(reports.len(), 1);
        assert_eq!(reports[0].kind, KIND_US_SUB_KEYBOARD);
        assert_eq!(reports[0].report, [0; 8]);
        assert!(!core.route_state.us_sub_key_active);
        assert!(core.injected_keys.is_empty());
        assert_eq!(core.hid.build(), [0; 8]);
    }

    #[test]
    fn jis_default_us_sub_release_clears_route_state() {
        let mut core = test_core(vec![layer(&[("0,0", "KC_A")])]);
        core.routing = RoutingConfig {
            split_keyboard_enabled: true,
            route_mode: RouteMode::JisSpecialUsDefault,
        };

        let reports = core.apply_event(event(true, 0, 0)).reports;
        assert_eq!(reports.len(), 1);
        assert_eq!(reports[0].kind, KIND_US_SUB_KEYBOARD);
        assert!(core.route_state.us_sub_key_active);

        let reports = core.apply_event(event(false, 0, 0)).reports;
        assert_eq!(reports.len(), 1);
        assert_eq!(reports[0].kind, KIND_US_SUB_KEYBOARD);
        assert_eq!(reports[0].report, [0; 8]);
        assert!(!core.route_state.us_sub_key_active);
        assert_eq!(core.hid.build(), [0; 8]);
    }

    #[test]
    fn force_delegate_all_routes_normal_keys_to_companion() {
        let mut core = test_core(vec![layer(&[("0,0", "KC_A")])]);
        core.force_delegate_all = true;
        assert_eq!(one_delegate(core.apply_event(event(true, 0, 0))), *b"P00\n");
        assert_eq!(
            one_delegate(core.apply_event(event(false, 0, 0))),
            *b"R00\n"
        );
        assert_eq!(core.hid.build(), [0; 8]);
        assert_eq!(core.counters.delegated_actions, 2);
    }

    #[test]
    fn duplicate_edges_are_ignored() {
        let mut core = test_core(vec![layer(&[("0,0", "KC_A")])]);
        assert!(no_output(core.apply_event(event(false, 0, 0))));
        assert_eq!(
            one_report(core.apply_event(event(true, 0, 0))),
            [0, 0, 4, 0, 0, 0, 0, 0]
        );
        assert!(no_output(core.apply_event(event(true, 0, 0))));
        assert_eq!(core.counters.ignored_duplicates, 2);
    }

    #[test]
    fn held_key_keeps_slot_when_earlier_key_releases() {
        let mut core = test_core(vec![layer(&[("0,0", "KC_A"), ("0,1", "KC_B")])]);
        assert_eq!(
            one_report(core.apply_event(event(true, 0, 0))),
            [0, 0, 4, 0, 0, 0, 0, 0]
        );
        assert_eq!(
            one_report(core.apply_event(event(true, 0, 1))),
            [0, 0, 4, 5, 0, 0, 0, 0]
        );
        assert_eq!(
            one_report(core.apply_event(event(false, 0, 0))),
            [0, 0, 0, 5, 0, 0, 0, 0]
        );
    }

    #[test]
    fn six_key_rollover_limit_is_counted() {
        let mut core = test_core(vec![layer(&[
            ("0,0", "KC_A"),
            ("0,1", "KC_B"),
            ("0,2", "KC_C"),
            ("0,3", "KC_D"),
            ("0,4", "KC_E"),
            ("0,5", "KC_F"),
            ("0,6", "KC_G"),
        ])]);
        for col in 0..7 {
            core.apply_event(event(true, 0, col));
        }
        assert_eq!(core.hid.build(), [0, 0, 4, 5, 6, 7, 8, 9]);
        assert_eq!(core.counters.rollover_drops, 1);
    }

    #[test]
    fn encodes_keyboard_broker_frame() {
        let frame = encode_broker_frame(KIND_KEYBOARD, &[0, 0, 4, 0, 0, 0, 0, 0]).unwrap();
        assert_eq!(&frame[0..4], b"CQAU");
        assert_eq!(frame[4], 1);
        assert_eq!(frame[5], KIND_KEYBOARD);
        assert_eq!(frame[6], 8);
        assert_eq!(
            &frame[PAYLOAD_OFFSET..PAYLOAD_OFFSET + 8],
            &[0, 0, 4, 0, 0, 0, 0, 0]
        );
        assert_eq!(
            xor_checksum(&frame[..CHECKSUM_OFFSET]),
            frame[CHECKSUM_OFFSET]
        );
    }
}
