"""
Configuration loader for logicd.

Search order:
  1. /mnt/p3/config.json   (primary – SD card P3 partition)
  2. config/default/config.json       (fallback – repo/development)
  3. built-in defaults      (empty layer 0, no macros)

Config JSON schema
------------------
{
    "version": "1.0",
    "settings": {
        "layout": "JIS",          // JIS | US
        "hidg":   "/dev/hidg0",   // HID gadget device path
        "socket": "/tmp/matrix_events.sock"
    },
    "layers": [
        {                         // layer 0 (base)
            "7,0": "KC_ESC",
            "8,0": "KC_F1",
            ...
        },
        {                         // layer 1 (Fn)
            "7,0": "KC_GRAVE",
            ...
        }
    ],
    "macros": {
        "HELLO": ["Hello, World!", "{IME_ON}", "{U+3042}", "{IME_OFF}"],
        "SIGN":  "Taro Yamada"
    }
}

Layer action format
-------------------
  "KC_*"         : standard keycode (see hid_report.KEYCODE)
  "MO(N)"        : momentary layer N (active while key held)
  "TG(N)"        : toggle layer N
  "TO(N)"        : move to layer N and clear transient/toggled layers
  "DF(N)"        : set runtime default layer N (not persisted)
  "MACRO:name"   : execute named macro
  "IME_ON"       : force IME on  (sends KC_KANA 0x88)
  "IME_OFF"      : toggle IME off (sends KC_GRAVE 0x35)
  "U+XXXX"       : Unicode input via Windows hex input
  "KC_NONE"      : do nothing
  "KC_TRNS"      : transparent (fall through to lower layer)
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from hidloom_paths import default_config_file, runtime_file

log = logging.getLogger(__name__)

_SEARCH_PATHS = [
    str(runtime_file("config.json")),
    str(default_config_file("config.json")),
]

# keymap.json の検索パス (config.json より優先)
_KEYMAP_SEARCH_PATHS = [
    str(runtime_file("keymap.json")),
    str(default_config_file("keymap.json")),
]


def _load_first_config_json() -> Dict[str, Any]:
    for candidate in _SEARCH_PATHS:
        if not candidate:
            continue
        try:
            with open(candidate, encoding="utf-8") as fh:
                raw = json.load(fh)
            log.info("Config loaded from %s", candidate)
            return raw
        except FileNotFoundError:
            continue
        except json.JSONDecodeError as exc:
            log.error("Config parse error in %s: %s", candidate, exc)
    return {}


def keymap_json_to_layers(keymap: Dict[str, Any]) -> List[Dict[str, str]]:
    """keymap.json 形式をフラットな layers リストに変換する。

    keymap.json の構造:
      _layout_def: {group: [[row, col, "SWxx"], ...], ...}
      layers:      [{_name, group: [kc, ...], ...}, ...]

    変換後:
      [{"row,col": "KC_*", ...}, ...]  (LayerManager が期待する形式)
    """
    layout_def = keymap.get("_layout_def", {})

    # グループ名 → [(row, col), ...] のマッピングを構築
    group_coords: Dict[str, List] = {}
    for group, entries in layout_def.items():
        if group.startswith("_") or not isinstance(entries, list):
            continue
        coords = []
        for entry in entries:
            if isinstance(entry, list) and len(entry) >= 2:
                coords.append((int(entry[0]), int(entry[1])))
        group_coords[group] = coords

    result: List[Dict[str, str]] = []
    for layer_data in keymap.get("layers", []):
        flat: Dict[str, str] = {}
        for group, coords in group_coords.items():
            kcs: List[str] = layer_data.get(group, [])
            for (row, col), kc in zip(coords, kcs):
                if kc:  # KC_TRNS もそのまま渡す (LayerManager がフォールスルー処理)
                    flat[f"{row},{col}"] = kc
        result.append(flat)

    log.info("keymap.json: %d layer(s), groups=%s",
             len(result), list(group_coords.keys()))
    return result


def _keymap_json_to_encoders(keymap: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract matrix-backed encoder A/B bindings from keymap.json."""
    explicit = keymap.get("encoders")
    if isinstance(explicit, list):
        return explicit

    layout_def = keymap.get("_layout_def", {})
    found: Dict[str, Dict[str, Any]] = {}
    for group, entries in layout_def.items():
        if not isinstance(group, str) or not group.startswith("encoder"):
            continue
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, list) or len(entry) < 3:
                continue
            row, col, label = int(entry[0]), int(entry[1]), str(entry[2])
            if label.endswith("A"):
                name = label[:-1]
                found.setdefault(name, {"name": name})["a"] = [row, col]
            elif label.endswith("B"):
                name = label[:-1]
                found.setdefault(name, {"name": name})["b"] = [row, col]

    encoders: List[Dict[str, Any]] = []
    for name in sorted(found):
        item = found[name]
        if "a" in item and "b" in item:
            item.setdefault("resolution", 4)
            item.setdefault("reverse", False)
            encoders.append(item)
        else:
            log.warning("encoder ignored: incomplete A/B binding for %s: %r", name, item)
    return encoders


def _keymap_json_to_joysticks(keymap: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract analog joystick virtual switch bindings from keymap.json."""
    explicit = keymap.get("joysticks")
    if isinstance(explicit, list):
        return explicit

    layout_def = keymap.get("_layout_def", {})
    entries = layout_def.get("stick")
    if not isinstance(entries, list):
        return []

    found: Dict[str, List[int]] = {}
    label_to_dir = {
        "UP": "up",
        "DOWN": "down",
        "LEFT": "left",
        "RIGHT": "right",
    }
    for entry in entries:
        if not isinstance(entry, list) or len(entry) < 3:
            continue
        row, col, label = int(entry[0]), int(entry[1]), str(entry[2]).upper()
        for suffix, direction in label_to_dir.items():
            if label.endswith(suffix):
                found[direction] = [row, col]
                break

    if all(direction in found for direction in ("up", "down", "left", "right")):
        return [{
            "name": "stick0",
            "up": found["up"],
            "down": found["down"],
            "left": found["left"],
            "right": found["right"],
        }]

    if found:
        log.warning("joystick ignored: incomplete stick binding: %r", found)
    return []


def layers_to_keymap_json(layers: List[Dict[str, str]], template: Dict[str, Any]) -> Dict[str, Any]:
    """Merge flat runtime layers back into a keymap.json-shaped document."""
    result = json.loads(json.dumps(template))
    layout_def = result.get("_layout_def", {})
    existing_layers = result.get("layers", [])
    rebuilt_layers: List[Dict[str, Any]] = []

    groups: Dict[str, List[tuple[int, int]]] = {}
    for group, entries in layout_def.items():
        if group.startswith("_") or not isinstance(entries, list):
            continue
        coords: List[tuple[int, int]] = []
        for entry in entries:
            if isinstance(entry, list) and len(entry) >= 2:
                coords.append((int(entry[0]), int(entry[1])))
        groups[group] = coords

    for idx, layer in enumerate(layers):
        base = existing_layers[idx] if idx < len(existing_layers) and isinstance(existing_layers[idx], dict) else {}
        rebuilt: Dict[str, Any] = {k: v for k, v in base.items() if k.startswith("_")}
        for group, coords in groups.items():
            rebuilt[group] = [layer.get(f"{row},{col}", "KC_TRNS") for row, col in coords]
        rebuilt_layers.append(rebuilt)

    result["layers"] = rebuilt_layers
    return result

_DEFAULTS: Dict[str, Any] = {
    "version": "1.0",
    "settings": {
        "layout":           "JIS",
        "hidg":             "/dev/hidg0",
        "mouse_hidg":       "/dev/hidg0",
        "consumer_hidg":    "/dev/hidg0",
        "socket":           "/tmp/matrix_events.sock",
        "ctrl_socket":      "/tmp/ctrl_events.sock",
        "ledd_socket":      "/tmp/ledd_events.sock",
        "key_event_socket": "/tmp/key_events.sock",
        "i2c_socket":       "/tmp/i2c_events.sock",
    },
    "layers": [{}],
    "macros": {},
    "encoders": [],
    "joysticks": [],
}


def load(path: Optional[str] = None) -> Dict[str, Any]:
    """Load configuration from *path* or the default search path.

    keymap.json が見つかった場合は config.json より優先して使用する。
    パスを明示した場合はそのファイルのみを読む (keymap.json 検索は行わない)。

    Returns a validated config dict.  Missing keys are filled from defaults.
    """
    # 明示パスが指定された場合は従来どおり
    if path:
        raw: Optional[Dict[str, Any]] = None
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
            log.info("Config loaded from %s", path)
        except FileNotFoundError:
            log.error("Config file not found: %s", path)
        except json.JSONDecodeError as exc:
            log.error("Config parse error in %s: %s", path, exc)
        return _merge_defaults(raw or {})

    # keymap.json を優先して検索
    for kp in _KEYMAP_SEARCH_PATHS:
        if not kp:
            continue
        try:
            with open(kp, encoding="utf-8") as fh:
                keymap = json.load(fh)
            log.info("keymap.json loaded from %s", kp)
            layers = keymap_json_to_layers(keymap)
            # keymap.json owns the physical layout, but runtime interaction
            # settings and macros still come from config.json on the device.
            cfg = _merge_defaults(_load_first_config_json())
            cfg["layers"] = layers
            cfg["encoders"] = _keymap_json_to_encoders(keymap)
            cfg["joysticks"] = _keymap_json_to_joysticks(keymap)
            return cfg
        except FileNotFoundError:
            continue
        except OSError as exc:
            log.warning("keymap.json load failed in %s: %s", kp, exc)
            continue
        except json.JSONDecodeError as exc:
            log.error("keymap.json parse error in %s: %s", kp, exc)

    # fallback: config.json
    raw = _load_first_config_json()

    if not raw:
        log.warning("No config file found, using built-in defaults")
        raw = {}

    return _merge_defaults(raw)


def _merge_defaults(raw: Dict[str, Any]) -> Dict[str, Any]:
    cfg: Dict[str, Any] = dict(_DEFAULTS)
    cfg["settings"] = {**_DEFAULTS["settings"], **raw.get("settings", {})}
    cfg["layers"]   = raw.get("layers", _DEFAULTS["layers"])
    cfg["macros"]   = raw.get("macros", _DEFAULTS["macros"])
    cfg["encoders"] = raw.get("encoders", _DEFAULTS["encoders"])
    cfg["joysticks"] = raw.get("joysticks", _DEFAULTS["joysticks"])
    cfg["version"]  = raw.get("version", _DEFAULTS["version"])

    # Validate layers is a list of dicts
    if not isinstance(cfg["layers"], list) or not cfg["layers"]:
        log.warning("Invalid 'layers' in config; using empty base layer")
        cfg["layers"] = [{}]
    for i, layer in enumerate(cfg["layers"]):
        if not isinstance(layer, dict):
            log.warning("Layer %d is not a dict; replacing with empty", i)
            cfg["layers"][i] = {}

    return cfg
