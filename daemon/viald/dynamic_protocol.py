"""Vial dynamic-entry handlers for macros and advanced interactions."""
from __future__ import annotations

import json
import logging
import os
import base64
import binascii
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from hidloom_paths import default_config_file
from .keycode_codec import KeycodeCodec
from .protocol_defs import (
    DEFAULT_TAP_DANCE_COUNT,
    CMD_VIA_MACRO_GET_BUFFER,
    CMD_VIA_MACRO_GET_BUFFER_SIZE,
    CMD_VIA_MACRO_GET_COUNT,
    CMD_VIA_MACRO_SET_BUFFER,
    DYNAMIC_VIAL_COMBO_GET,
    DYNAMIC_VIAL_COMBO_SET,
    DYNAMIC_VIAL_GET_NUMBER_OF_ENTRIES,
    DYNAMIC_VIAL_KEY_OVERRIDE_GET,
    DYNAMIC_VIAL_KEY_OVERRIDE_SET,
    DYNAMIC_VIAL_TAP_DANCE_GET,
    DYNAMIC_VIAL_TAP_DANCE_SET,
    REPORT_SIZE,
)

log = logging.getLogger(__name__)

CONFIG_JSON_PATH = Path(os.environ.get("VIALD_CONFIG_JSON_PATH", "/mnt/p3/config.json"))
FALLBACK_CONFIG_JSON_PATH = Path(os.environ.get("VIALD_FALLBACK_CONFIG_JSON_PATH", str(default_config_file("config.json"))))

_MOD_ACTION_TO_MASK = {
    "KC_LCTL": 0x01,
    "KC_LCTRL": 0x01,
    "KC_LSFT": 0x02,
    "KC_LSHIFT": 0x02,
    "KC_LALT": 0x04,
    "KC_LOPT": 0x04,
    "KC_LGUI": 0x08,
    "KC_LWIN": 0x08,
    "KC_LCMD": 0x08,
    "KC_RCTL": 0x10,
    "KC_RCTRL": 0x10,
    "KC_RSFT": 0x20,
    "KC_RSHIFT": 0x20,
    "KC_RALT": 0x40,
    "KC_ROPT": 0x40,
    "KC_RGUI": 0x80,
    "KC_RWIN": 0x80,
    "KC_RCMD": 0x80,
}
_MOD_MASK_TO_ACTION = {
    0x01: "KC_LCTL",
    0x02: "KC_LSFT",
    0x04: "KC_LALT",
    0x08: "KC_LGUI",
    0x10: "KC_RCTL",
    0x20: "KC_RSFT",
    0x40: "KC_RALT",
    0x80: "KC_RGUI",
}
_KEY_OVERRIDE_OPTION_ENABLED = 1 << 7
_KEY_OVERRIDE_OPTION_TRIGGER_DOWN = 1 << 0
_KEY_OVERRIDE_OPTION_REQUIRED_MOD_DOWN = 1 << 1
_SUPPORTED_QMK_SETTINGS = (2, 7, 23)
_SS_QMK_PREFIX = 0x01
_SS_TAP_CODE = 0x01
_SS_DOWN_CODE = 0x02
_SS_UP_CODE = 0x03
_SS_DELAY_CODE = 0x04
_VIAL_MACRO_EXT_TAP = 0x05
_VIAL_MACRO_EXT_DOWN = 0x06
_VIAL_MACRO_EXT_UP = 0x07


def vial_macros_from_buffer(
    data: bytes,
    *,
    macro_count: int,
    codec: KeycodeCodec | None = None,
) -> dict[str, Any]:
    codec = codec or KeycodeCodec()
    parts = _split_vial_macro_buffer(data, macro_count)
    parts += [b""] * max(0, macro_count - len(parts))
    return {f"VIAL{idx}": _vial_macro_tokens(part, codec) for idx, part in enumerate(parts) if part}


def _split_vial_macro_buffer(data: bytes, macro_count: int) -> list[bytes]:
    parts: list[bytes] = []
    current = bytearray()
    idx = 0
    while idx < len(data) and len(parts) < macro_count:
        value = data[idx]
        if value == 0:
            parts.append(bytes(current))
            current.clear()
            idx += 1
            continue
        if value != _SS_QMK_PREFIX:
            current.append(value)
            idx += 1
            continue
        if idx + 1 >= len(data):
            current.append(value)
            idx += 1
            continue
        action = data[idx + 1]
        width = 4 if action in {_SS_DELAY_CODE, _VIAL_MACRO_EXT_TAP, _VIAL_MACRO_EXT_DOWN, _VIAL_MACRO_EXT_UP} else 3
        chunk = data[idx:idx + width]
        current.extend(chunk)
        idx += len(chunk)
    if len(parts) < macro_count and current:
        parts.append(bytes(current))
    return parts


def _vial_macro_tokens(data: bytes, codec: KeycodeCodec) -> list[str]:
    tokens: list[str] = []
    text = bytearray()

    def flush_text() -> None:
        if text:
            tokens.append(text.decode("utf-8", errors="ignore"))
            text.clear()

    idx = 0
    while idx < len(data):
        value = data[idx]
        if value != _SS_QMK_PREFIX:
            text.append(value)
            idx += 1
            continue
        if idx + 1 >= len(data):
            break
        action = data[idx + 1]
        if action in {_SS_TAP_CODE, _SS_DOWN_CODE, _SS_UP_CODE} and idx + 2 < len(data):
            flush_text()
            kc_action = codec.vial_to_action(data[idx + 2])
            if kc_action:
                if action == _SS_TAP_CODE:
                    tokens.append(f"{{KC:{kc_action}}}")
                elif action == _SS_DOWN_CODE:
                    tokens.append(f"{{KC_DOWN:{kc_action}}}")
                elif action == _SS_UP_CODE:
                    tokens.append(f"{{KC_UP:{kc_action}}}")
            idx += 3
            continue
        if action in {_VIAL_MACRO_EXT_TAP, _VIAL_MACRO_EXT_DOWN, _VIAL_MACRO_EXT_UP} and idx + 3 < len(data):
            flush_text()
            keycode = struct.unpack("<H", data[idx + 2:idx + 4])[0]
            if keycode > 0xFF00:
                keycode = (keycode & 0xFF) << 8
            kc_action = codec.vial_to_action(keycode)
            if kc_action:
                if action == _VIAL_MACRO_EXT_TAP:
                    tokens.append(f"{{KC:{kc_action}}}")
                elif action == _VIAL_MACRO_EXT_DOWN:
                    tokens.append(f"{{KC_DOWN:{kc_action}}}")
                elif action == _VIAL_MACRO_EXT_UP:
                    tokens.append(f"{{KC_UP:{kc_action}}}")
            idx += 4
            continue
        if action == _SS_DELAY_CODE and idx + 3 < len(data):
            flush_text()
            delay_ms = struct.unpack("<H", data[idx + 2:idx + 4])[0]
            tokens.append(f"{{DELAY:{delay_ms}}}")
            idx += 4
            continue
        idx += 2
    flush_text()
    return tokens


def _pad(payload: bytes) -> bytes:
    return payload[:REPORT_SIZE].ljust(REPORT_SIZE, b"\x00")


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            fp.write(text)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


class VialDynamicMixin:
    tap_dance_count: int
    combo_count: int
    key_override_count: int
    macro_count: int
    macro_buffer_size: int

    def _config_path(self) -> Path:
        if CONFIG_JSON_PATH.exists():
            return CONFIG_JSON_PATH
        return FALLBACK_CONFIG_JSON_PATH

    def _load_config(self) -> dict[str, Any]:
        path = self._config_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = {}
        if not isinstance(data, dict):
            raise ValueError(f"{path} root must be object")
        data.setdefault("settings", {})
        if not isinstance(data["settings"], dict):
            data["settings"] = {}
        return data

    def _interaction_settings(self, cfg: dict[str, Any]) -> dict[str, Any]:
        settings = cfg.setdefault("settings", {})
        interaction = settings.setdefault("interaction", {})
        if not isinstance(interaction, dict):
            interaction = {}
            settings["interaction"] = interaction
        return interaction

    def _save_config(self, cfg: dict[str, Any]) -> Path:
        path = self._config_path()
        _atomic_write_json(path, cfg)
        self._reload_logicd_best_effort()
        return path

    def _qmk_setting_ms(self, interaction: dict[str, Any], key: str, default: float) -> int:
        try:
            return max(0, min(10000, int(round(float(interaction.get(key, default)) * 1000))))
        except (TypeError, ValueError):
            return int(default * 1000)

    def _qmk_setting_bool(self, interaction: dict[str, Any], key: str, default: bool) -> int:
        value = interaction.get(key, default)
        return 1 if bool(value) else 0

    def _qmk_setting_value(self, qsid: int) -> tuple[int, int]:
        cfg = self._load_config()
        interaction = self._interaction_settings(cfg)
        if qsid == 2:
            return self._qmk_setting_ms(interaction, "combo_term", 0.050), 2
        if qsid == 7:
            return self._qmk_setting_ms(interaction, "tapping_term", 0.200), 2
        if qsid == 23:
            return self._qmk_setting_bool(interaction, "hold_on_other_key_press", True), 1
        return 0, 0

    def _qmk_setting_set(self, qsid: int, value: int) -> bool:
        cfg = self._load_config()
        interaction = self._interaction_settings(cfg)
        if qsid == 2:
            interaction["combo_term"] = max(0, min(10000, value)) / 1000.0
        elif qsid == 7:
            interaction["tapping_term"] = max(0, min(10000, value)) / 1000.0
        elif qsid == 23:
            interaction["hold_on_other_key_press"] = bool(value & 0x01)
        else:
            return False
        self._save_config(cfg)
        return True

    def _qmk_settings_query(self, packet: bytes) -> bytes:
        cur = struct.unpack("<H", packet[2:4])[0]
        values = [qsid for qsid in _SUPPORTED_QMK_SETTINGS if qsid > cur]
        payload = b"".join(struct.pack("<H", qsid) for qsid in values)
        payload += struct.pack("<H", 0xFFFF)
        return payload[:REPORT_SIZE].ljust(REPORT_SIZE, b"\xFF")

    def _qmk_settings_get(self, packet: bytes) -> bytes:
        qsid = struct.unpack("<H", packet[2:4])[0]
        value, width = self._qmk_setting_value(qsid)
        if width == 0:
            return _pad(bytes([1]))
        return _pad(bytes([0]) + int(value).to_bytes(width, byteorder="little"))

    def _qmk_settings_set(self, packet: bytes) -> bytes:
        qsid = struct.unpack("<H", packet[2:4])[0]
        _current, width = self._qmk_setting_value(qsid)
        if width == 0:
            return _pad(bytes([1]))
        value = int.from_bytes(packet[4:4 + width], byteorder="little")
        return _pad(bytes([0 if self._qmk_setting_set(qsid, value) else 1]))

    def _qmk_settings_reset(self) -> bytes:
        cfg = self._load_config()
        interaction = self._interaction_settings(cfg)
        interaction["combo_term"] = 0.050
        interaction["tapping_term"] = 0.200
        interaction["hold_on_other_key_press"] = True
        self._save_config(cfg)
        return bytes(REPORT_SIZE)

    def _reload_logicd_best_effort(self) -> None:
        if os.environ.get("VIALD_RELOAD_LOGICD", "1") in {"0", "false", "False"}:
            return
        try:
            subprocess.run(
                ["systemctl", "reload", "logicd"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3.0,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            log.warning("logicd reload after Vial dynamic update skipped: %s", exc)

    def _macro_buffer(self, cfg: dict[str, Any] | None = None) -> bytes:
        cfg = cfg or self._load_config()
        settings = cfg.get("settings", {})
        raw = settings.get("vial_macro_buffer") if isinstance(settings, dict) else None
        if isinstance(raw, str):
            try:
                data = base64.b64decode(raw.encode("ascii"), validate=True)
            except (ValueError, binascii.Error, UnicodeEncodeError):  # type: ignore[name-defined]
                data = b""
        else:
            data = b""
        if len(data) < self.macro_buffer_size:
            data += b"\x00" * (self.macro_buffer_size - len(data))
        return data[:self.macro_buffer_size]

    def _store_macro_buffer(self, cfg: dict[str, Any], data: bytes) -> None:
        if len(data) < self.macro_buffer_size:
            data += b"\x00" * (self.macro_buffer_size - len(data))
        data = data[:self.macro_buffer_size]
        settings = cfg.setdefault("settings", {})
        settings["vial_macro_buffer"] = base64.b64encode(data).decode("ascii")
        existing_macros = cfg.get("macros", {})
        if not isinstance(existing_macros, dict):
            existing_macros = {}
        cfg["macros"] = {
            **{key: value for key, value in existing_macros.items() if not str(key).startswith("VIAL")},
            **vial_macros_from_buffer(data, macro_count=self.macro_count, codec=self._codec),
        }

    def _macro_get_count(self) -> bytes:
        return _pad(bytes([CMD_VIA_MACRO_GET_COUNT, self.macro_count]))

    def _macro_get_buffer_size(self) -> bytes:
        return _pad(bytes([CMD_VIA_MACRO_GET_BUFFER_SIZE]) + struct.pack(">H", self.macro_buffer_size))

    def _macro_get_buffer(self, packet: bytes) -> bytes:
        offset, size = struct.unpack(">HB", packet[1:4])
        data = self._macro_buffer()
        return _pad(bytes([CMD_VIA_MACRO_GET_BUFFER]) + struct.pack(">HB", offset, size) + data[offset:offset + size])

    def _macro_set_buffer(self, packet: bytes) -> bytes:
        offset, size = struct.unpack(">HB", packet[1:4])
        if offset >= self.macro_buffer_size:
            log.warning("macro set ignored: offset=%d size=%d buffer=%d", offset, size, self.macro_buffer_size)
            return bytes(REPORT_SIZE)
        chunk = packet[4:4 + size]
        cfg = self._load_config()
        data = bytearray(self._macro_buffer(cfg))
        end = min(self.macro_buffer_size, offset + len(chunk))
        data[offset:end] = chunk[:end - offset]
        self._store_macro_buffer(cfg, bytes(data))
        self._save_config(cfg)
        return bytes(REPORT_SIZE)

    def _dispatch_dynamic_entry_op(self, packet: bytes) -> bytes:
        operation = packet[2]
        if operation == DYNAMIC_VIAL_GET_NUMBER_OF_ENTRIES:
            return _pad(bytes([self.tap_dance_count, self.combo_count, self.key_override_count, 0]))
        if operation == DYNAMIC_VIAL_TAP_DANCE_GET:
            return self._get_tap_dance_entry(packet)
        if operation == DYNAMIC_VIAL_TAP_DANCE_SET:
            return self._set_tap_dance_entry(packet)
        if operation == DYNAMIC_VIAL_COMBO_GET:
            return self._get_combo_entry(packet)
        if operation == DYNAMIC_VIAL_COMBO_SET:
            return self._set_combo_entry(packet)
        if operation == DYNAMIC_VIAL_KEY_OVERRIDE_GET:
            return self._get_key_override_entry(packet)
        if operation == DYNAMIC_VIAL_KEY_OVERRIDE_SET:
            return self._set_key_override_entry(packet)
        log.warning("unsupported Vial dynamic op: 0x%02x payload=%s", operation, packet[:REPORT_SIZE].hex())
        return bytes(REPORT_SIZE)

    def _tap_dance_action_to_keycode(self, action: object) -> int:
        if not isinstance(action, str) or not action or action == "KC_NONE":
            return 0
        return self._codec.action_to_vial(action)

    def _tap_dance_keycode_to_action(self, keycode: int) -> str | None:
        if keycode == 0:
            return None
        action = self._codec.vial_to_action(keycode)
        if action in {None, "KC_NONE"}:
            return None
        return action

    def _get_tap_dance_entry(self, packet: bytes) -> bytes:
        idx = int(packet[3])
        if idx >= self.tap_dance_count:
            log.warning("tap dance get ignored: index out of range idx=%d count=%d", idx, self.tap_dance_count)
            return _pad(bytes([1]))
        cfg = self._load_config()
        interaction = self._interaction_settings(cfg)
        dances = interaction.get("tap_dances", {})
        if not isinstance(dances, dict):
            dances = {}
        entry = dances.get(f"TD{idx}", {})
        if not isinstance(entry, dict):
            entry = {}
        term_value = entry.get("term", interaction.get("tap_dance_term", 0.2))
        term_ms = int(round(float(term_value) * 1000))
        values = (
            self._tap_dance_action_to_keycode(entry.get("1")),
            self._tap_dance_action_to_keycode(entry.get("hold") or entry.get("on_hold")),
            self._tap_dance_action_to_keycode(entry.get("2")),
            self._tap_dance_action_to_keycode(entry.get("tap_hold") or entry.get("on_tap_hold")),
            max(0, min(10000, term_ms)),
        )
        return _pad(bytes([0]) + struct.pack("<HHHHH", *values))

    def _set_tap_dance_entry(self, packet: bytes) -> bytes:
        idx = int(packet[3])
        if idx >= self.tap_dance_count:
            log.warning("tap dance set ignored: index out of range idx=%d count=%d", idx, self.tap_dance_count)
            return _pad(bytes([1]))
        try:
            on_tap, on_hold, on_double_tap, on_tap_hold, term_ms = struct.unpack("<HHHHH", packet[4:14])
        except struct.error:
            log.warning("tap dance set ignored: malformed payload=%s", packet[:REPORT_SIZE].hex())
            return _pad(bytes([1]))

        cfg = self._load_config()
        interaction = self._interaction_settings(cfg)
        dances = interaction.setdefault("tap_dances", {})
        if not isinstance(dances, dict):
            dances = {}
            interaction["tap_dances"] = dances

        entry: dict[str, str] = {}
        tap_action = self._tap_dance_keycode_to_action(on_tap)
        hold_action = self._tap_dance_keycode_to_action(on_hold)
        double_action = self._tap_dance_keycode_to_action(on_double_tap)
        tap_hold_action = self._tap_dance_keycode_to_action(on_tap_hold)
        if tap_action:
            entry["1"] = tap_action
        if hold_action:
            entry["hold"] = hold_action
        if double_action:
            entry["2"] = double_action
        if tap_hold_action:
            entry["tap_hold"] = tap_hold_action
        entry["term"] = max(0, min(10000, int(term_ms))) / 1000.0
        if entry:
            dances[f"TD{idx}"] = entry
        else:
            dances.pop(f"TD{idx}", None)
        interaction["tap_dance_term"] = max(0, min(10000, int(term_ms))) / 1000.0
        path = self._save_config(cfg)
        log.info("Vial tap dance %d saved to %s", idx, path)
        return bytes(REPORT_SIZE)

    def _layer0_action_by_matrix(self) -> dict[tuple[int, int], str]:
        layers = self._fetch_logicd_layers()
        if not layers:
            return {}
        layer0 = layers[0]
        result: dict[tuple[int, int], str] = {}
        for key, action in layer0.items():
            try:
                row_s, col_s = str(key).split(",", 1)
                row, col = int(row_s), int(col_s)
            except (TypeError, ValueError):
                continue
            result[(row, col)] = str(action)
        return result

    def _matrix_by_layer0_keycode(self) -> dict[int, tuple[int, int]]:
        result: dict[int, tuple[int, int]] = {}
        for matrix, action in self._layer0_action_by_matrix().items():
            keycode = self._codec.action_to_vial(action)
            if keycode:
                result.setdefault(keycode, matrix)
        return result

    def _get_combo_entry(self, packet: bytes) -> bytes:
        idx = int(packet[3])
        if idx >= self.combo_count:
            log.warning("combo get ignored: index out of range idx=%d count=%d", idx, self.combo_count)
            return _pad(bytes([1]))
        cfg = self._load_config()
        interaction = self._interaction_settings(cfg)
        combos = interaction.get("combos", [])
        combo = combos[idx] if isinstance(combos, list) and idx < len(combos) and isinstance(combos[idx], dict) else {}
        action_by_matrix = self._layer0_action_by_matrix()

        key_values: list[int] = []
        for key in (combo.get("keys", []) if isinstance(combo, dict) else []):
            try:
                row, col = int(key[0]), int(key[1])
            except (TypeError, ValueError, IndexError):
                continue
            key_values.append(self._codec.action_to_vial(action_by_matrix.get((row, col), "KC_NONE")))
        key_values = (key_values + [0, 0, 0, 0])[:4]
        output = self._codec.action_to_vial(combo.get("action", "KC_NONE")) if isinstance(combo, dict) else 0
        return _pad(bytes([0]) + struct.pack("<HHHHH", *key_values, output))

    def _set_combo_entry(self, packet: bytes) -> bytes:
        idx = int(packet[3])
        if idx >= self.combo_count:
            log.warning("combo set ignored: index out of range idx=%d count=%d", idx, self.combo_count)
            return _pad(bytes([1]))
        try:
            key1, key2, key3, key4, output = struct.unpack("<HHHHH", packet[4:14])
        except struct.error:
            log.warning("combo set ignored: malformed payload=%s", packet[:REPORT_SIZE].hex())
            return _pad(bytes([1]))

        matrix_by_keycode = self._matrix_by_layer0_keycode()
        keys: list[list[int]] = []
        seen: set[tuple[int, int]] = set()
        for keycode in (key1, key2, key3, key4):
            if keycode == 0:
                continue
            matrix = matrix_by_keycode.get(keycode)
            if matrix is None:
                action = self._codec.vial_to_action(keycode)
                log.warning("combo key ignored: no layer0 matrix for keycode=0x%04x action=%r", keycode, action)
                continue
            if matrix in seen:
                continue
            seen.add(matrix)
            keys.append([matrix[0], matrix[1]])

        output_action = self._codec.vial_to_action(output)
        cfg = self._load_config()
        interaction = self._interaction_settings(cfg)
        combos = interaction.setdefault("combos", [])
        if not isinstance(combos, list):
            combos = []
            interaction["combos"] = combos
        while len(combos) <= idx:
            combos.append({"keys": [], "action": "KC_NONE"})
        if len(keys) >= 2 and output_action not in {None, "KC_NONE"}:
            combos[idx] = {"keys": keys, "action": output_action}
        else:
            combos[idx] = {"keys": [], "action": "KC_NONE"}
        path = self._save_config(cfg)
        log.info("Vial combo %d saved to %s", idx, path)
        return bytes(REPORT_SIZE)

    def _trigger_mod_mask(self, trigger: object) -> int:
        items = [trigger] if isinstance(trigger, str) else trigger
        mask = 0
        if not isinstance(items, list):
            return mask
        for item in items:
            mask |= _MOD_ACTION_TO_MASK.get(str(item), 0)
        return mask

    def _actions_from_mod_mask(self, mask: int) -> list[str]:
        return [action for bit, action in _MOD_MASK_TO_ACTION.items() if mask & bit]

    def _get_key_override_entry(self, packet: bytes) -> bytes:
        idx = int(packet[3])
        if idx >= self.key_override_count:
            log.warning("key override get ignored: index out of range idx=%d count=%d", idx, self.key_override_count)
            return _pad(bytes([1]))
        cfg = self._load_config()
        interaction = self._interaction_settings(cfg)
        overrides = interaction.get("key_overrides", [])
        override = (
            overrides[idx]
            if isinstance(overrides, list) and idx < len(overrides) and isinstance(overrides[idx], dict)
            else {}
        )
        trigger_keycode = self._codec.action_to_vial(override.get("key", "KC_NONE")) if override else 0
        replacement = self._codec.action_to_vial(override.get("replacement", "KC_NONE")) if override else 0
        trigger_mods = self._trigger_mod_mask(override.get("trigger", [])) if override else 0
        layers = int(override.get("layers", 0xFFFF)) if override else 0
        options = (
            int(override.get("options", (
                _KEY_OVERRIDE_OPTION_ENABLED
                | _KEY_OVERRIDE_OPTION_TRIGGER_DOWN
                | (_KEY_OVERRIDE_OPTION_REQUIRED_MOD_DOWN if trigger_mods else 0)
            )))
        ) if override else 0
        negative = self._trigger_mod_mask(override.get("negative_trigger", override.get("negative", []))) if override else 0
        suppressed = int(override.get("suppressed_mods", 0)) if override else 0
        return _pad(bytes([0]) + struct.pack(
            "<HHHBBBB",
            trigger_keycode,
            replacement,
            max(0, min(0xFFFF, layers)),
            trigger_mods,
            negative,
            max(0, min(0xFF, suppressed)),
            max(0, min(0xFF, options)),
        ))

    def _set_key_override_entry(self, packet: bytes) -> bytes:
        idx = int(packet[3])
        if idx >= self.key_override_count:
            log.warning("key override set ignored: index out of range idx=%d count=%d", idx, self.key_override_count)
            return _pad(bytes([1]))
        try:
            trigger_keycode, replacement_keycode, layers, trigger_mods, negative, suppressed, options = struct.unpack(
                "<HHHBBBB", packet[4:14]
            )
        except struct.error:
            log.warning("key override set ignored: malformed payload=%s", packet[:REPORT_SIZE].hex())
            return _pad(bytes([1]))

        key_action = self._codec.vial_to_action(trigger_keycode)
        replacement = self._codec.vial_to_action(replacement_keycode)
        trigger_actions = self._actions_from_mod_mask(trigger_mods)
        negative_actions = self._actions_from_mod_mask(negative)
        enabled = bool(options & _KEY_OVERRIDE_OPTION_ENABLED)

        cfg = self._load_config()
        interaction = self._interaction_settings(cfg)
        overrides = interaction.setdefault("key_overrides", [])
        if not isinstance(overrides, list):
            overrides = []
            interaction["key_overrides"] = overrides
        while len(overrides) <= idx:
            overrides.append({"trigger": [], "key": "KC_NONE", "replacement": "KC_NONE"})

        if enabled and trigger_actions and key_action not in {None, "KC_NONE"} and replacement not in {None, "KC_NONE"}:
            overrides[idx] = {
                "trigger": trigger_actions[0] if len(trigger_actions) == 1 else trigger_actions,
                "negative_trigger": negative_actions[0] if len(negative_actions) == 1 else negative_actions,
                "key": key_action,
                "replacement": replacement,
                "layers": layers,
                "suppressed_mods": suppressed,
                "options": options,
            }
        else:
            overrides[idx] = {"trigger": [], "key": "KC_NONE", "replacement": "KC_NONE"}
        path = self._save_config(cfg)
        log.info("Vial key override %d saved to %s", idx, path)
        return bytes(REPORT_SIZE)
