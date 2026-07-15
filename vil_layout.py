"""Vial .vil layout import/export helpers."""
from __future__ import annotations

import json
import argparse
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent
_DAEMON_ROOT = _REPO_ROOT / "daemon"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_DAEMON_ROOT) not in sys.path:
    sys.path.insert(0, str(_DAEMON_ROOT))

from viald.keycode_codec import KeycodeCodec, VIAL_KC_NO  # noqa: E402
from hidloom_paths import default_config_file  # noqa: E402


VIL_VERSION = 1
VIAL_PROTOCOL_VERSION = 6
VIA_PROTOCOL_VERSION = 9
DEFAULT_VIAL_JSON = default_config_file("vial.json", _REPO_ROOT)
DEFAULT_KEYMAP_JSON = default_config_file("keymap.json", _REPO_ROOT)
DEFAULT_CTRL_SOCKET = Path("/tmp/ctrl_events.sock")
HIDLOOM_EXPORT_WARNINGS_KEY = "hidloom_export_warnings"
HIDLOOM_INTERACTION_SETTINGS_KEY = "hidloom_interaction_settings"
HIDLOOM_VIAL_MACRO_BUFFER_KEY = "hidloom_vial_macro_buffer"
KNOWN_VIL_TOP_LEVEL_KEYS = {
    "version",
    "uid",
    "layout",
    "encoder_layout",
    "layout_options",
    "macro",
    "vial_protocol",
    "via_protocol",
    "tap_dance",
    "combo",
    "key_override",
    "alt_repeat_key",
    "settings",
}
KNOWN_VIL_SETTINGS_KEYS = {HIDLOOM_EXPORT_WARNINGS_KEY, HIDLOOM_INTERACTION_SETTINGS_KEY, HIDLOOM_VIAL_MACRO_BUFFER_KEY}


@dataclass(frozen=True)
class VilRemap:
    layer: int
    row: int
    col: int
    action: str


@dataclass(frozen=True)
class VilImportPlan:
    uid: int | None
    remaps: list[VilRemap]
    warnings: list[str]
    uid_mismatch: bool
    interaction_settings: dict[str, Any] | None = None
    vial_macro_buffer: str | None = None


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def keyboard_uid(vial: dict[str, Any]) -> int:
    return int(vial.get("uid", 0))


def matrix_size(vial: dict[str, Any]) -> tuple[int, int]:
    matrix = vial.get("matrix", {})
    return int(matrix.get("rows", 0)), int(matrix.get("cols", 0))


def load_keymap_layers(path: Path) -> list[dict[str, str]]:
    """Load config/default/keymap.json layers as {"row,col": "KC_*"} maps."""
    keymap = load_json(path)
    layout_def = keymap.get("_layout_def", {})
    layers = keymap.get("layers", [])
    if not isinstance(layout_def, dict) or not isinstance(layers, list):
        return []

    out: list[dict[str, str]] = []
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        flattened: dict[str, str] = {}
        for group, positions in layout_def.items():
            if not isinstance(group, str) or group.startswith("_"):
                continue
            if not isinstance(positions, list):
                continue
            keycodes = layer.get(group, [])
            if not isinstance(keycodes, list):
                continue
            for idx, pos in enumerate(positions):
                if idx >= len(keycodes) or not isinstance(pos, list) or len(pos) < 2:
                    continue
                try:
                    row, col = int(pos[0]), int(pos[1])
                except (TypeError, ValueError):
                    continue
                flattened[f"{row},{col}"] = str(keycodes[idx])
        out.append(flattened)
    return out


def load_encoder_map(path: Path) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """Return encoder targets as [(ccw_row_col, cw_row_col), ...]."""
    keymap = load_json(path)
    explicit = keymap.get("encoders")
    if isinstance(explicit, list):
        result: list[tuple[tuple[int, int], tuple[int, int]]] = []
        for item in explicit:
            try:
                a = (int(item["a"][0]), int(item["a"][1]))
                b = (int(item["b"][0]), int(item["b"][1]))
            except (TypeError, ValueError, KeyError, IndexError):
                continue
            result.append((b, a))
        return result

    layout_def = keymap.get("_layout_def", {})
    found: dict[str, dict[str, tuple[int, int]]] = {}
    if not isinstance(layout_def, dict):
        return []

    for group, entries in layout_def.items():
        if not isinstance(group, str) or not group.startswith("encoder"):
            continue
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, list) or len(entry) < 3:
                continue
            try:
                row, col, label = int(entry[0]), int(entry[1]), str(entry[2])
            except (TypeError, ValueError):
                continue
            if label.endswith("A"):
                found.setdefault(label[:-1], {})["a"] = (row, col)
            elif label.endswith("B"):
                found.setdefault(label[:-1], {})["b"] = (row, col)

    result = []
    for name in sorted(found):
        item = found[name]
        if "a" in item and "b" in item:
            result.append((item["b"], item["a"]))
    return result


def build_vil_document(
    *,
    uid: int,
    rows: int,
    cols: int,
    layers: list[dict[str, str]],
    encoder_map: list[tuple[tuple[int, int], tuple[int, int]]],
    codec: KeycodeCodec | None = None,
    interaction_settings: dict[str, Any] | None = None,
    vial_macro_buffer: str | None = None,
) -> dict[str, Any]:
    codec = codec or KeycodeCodec()
    warnings: list[str] = []
    layout: list[list[list[int]]] = []
    for layer in layers:
        layer_idx = len(layout)
        layer_rows: list[list[int]] = []
        for row in range(rows):
            layer_rows.append([
                _encode_action(codec, str(layer.get(f"{row},{col}", "KC_NONE")), warnings, f"L{layer_idx} ({row},{col})")
                for col in range(cols)
            ])
        layout.append(layer_rows)

    encoder_layout: list[list[list[int]]] = []
    for layer in layers:
        layer_idx = len(encoder_layout)
        layer_encoders: list[list[int]] = []
        for enc_idx, targets in enumerate(encoder_map):
            layer_encoders.append([
                _encode_action(
                    codec,
                    str(layer.get(f"{row},{col}", "KC_NONE")),
                    warnings,
                    f"L{layer_idx} encoder {enc_idx}.{action_idx}",
                )
                for action_idx, (row, col) in enumerate(targets)
            ])
        encoder_layout.append(layer_encoders)

    settings: dict[str, Any] = {}
    if warnings:
        settings[HIDLOOM_EXPORT_WARNINGS_KEY] = warnings
    if isinstance(interaction_settings, dict):
        settings[HIDLOOM_INTERACTION_SETTINGS_KEY] = interaction_settings
    if isinstance(vial_macro_buffer, str):
        settings[HIDLOOM_VIAL_MACRO_BUFFER_KEY] = vial_macro_buffer

    return {
        "version": VIL_VERSION,
        "uid": uid,
        "layout": layout,
        "encoder_layout": encoder_layout,
        "layout_options": 0,
        "macro": [],
        "vial_protocol": VIAL_PROTOCOL_VERSION,
        "via_protocol": VIA_PROTOCOL_VERSION,
        "tap_dance": _build_tap_dance_entries(codec, interaction_settings),
        "combo": _build_combo_entries(codec, layers[0] if layers else {}, interaction_settings),
        "key_override": _build_key_override_entries(codec, interaction_settings),
        "alt_repeat_key": [],
        "settings": settings,
    }


def encode_vil(document: dict[str, Any]) -> bytes:
    return json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _tap_dance_sort_key(name: str) -> tuple[int, str]:
    if name.startswith("TD") and name[2:].isdigit():
        return (int(name[2:]), name)
    return (9999, name)


def _build_tap_dance_entries(codec: KeycodeCodec, interaction_settings: dict[str, Any] | None) -> list[list[int]]:
    if not isinstance(interaction_settings, dict):
        return []
    dances = interaction_settings.get("tap_dances", {})
    if not isinstance(dances, dict):
        return []
    entries: list[list[int]] = []
    for name in sorted(dances, key=_tap_dance_sort_key):
        entry = dances.get(name)
        if not isinstance(entry, dict):
            continue
        term_value = entry.get("term", interaction_settings.get("tap_dance_term", 0.2))
        term_ms = int(round(float(term_value) * 1000))
        entries.append([
            codec.action_to_vial(str(entry.get("1", "KC_NONE"))),
            codec.action_to_vial(str(entry.get("hold") or entry.get("on_hold") or "KC_NONE")),
            codec.action_to_vial(str(entry.get("2", "KC_NONE"))),
            codec.action_to_vial(str(entry.get("tap_hold") or entry.get("on_tap_hold") or "KC_NONE")),
            max(0, min(10000, term_ms)),
        ])
    return entries


def _build_combo_entries(
    codec: KeycodeCodec,
    layer0: dict[str, str],
    interaction_settings: dict[str, Any] | None,
) -> list[list[int]]:
    if not isinstance(interaction_settings, dict):
        return []
    combos = interaction_settings.get("combos", [])
    if not isinstance(combos, list):
        return []
    action_by_matrix: dict[tuple[int, int], str] = {}
    for key, action in layer0.items():
        try:
            row_s, col_s = str(key).split(",", 1)
            action_by_matrix[(int(row_s), int(col_s))] = str(action)
        except (TypeError, ValueError):
            continue
    entries: list[list[int]] = []
    for combo in combos:
        if not isinstance(combo, dict):
            continue
        keys: list[int] = []
        for key in combo.get("keys", []):
            try:
                row, col = int(key[0]), int(key[1])
            except (TypeError, ValueError, IndexError):
                continue
            keys.append(codec.action_to_vial(action_by_matrix.get((row, col), "KC_NONE")))
        keys = (keys + [0, 0, 0, 0])[:4]
        entries.append(keys + [codec.action_to_vial(str(combo.get("action", "KC_NONE")))])
    return entries


_MOD_ACTION_TO_MASK = {
    "KC_LCTL": 0x01, "KC_LCTRL": 0x01,
    "KC_LSFT": 0x02, "KC_LSHIFT": 0x02,
    "KC_LALT": 0x04, "KC_LGUI": 0x08, "KC_LWIN": 0x08, "KC_LCMD": 0x08,
    "KC_RCTL": 0x10, "KC_RCTRL": 0x10,
    "KC_RSFT": 0x20, "KC_RSHIFT": 0x20,
    "KC_RALT": 0x40, "KC_RGUI": 0x80, "KC_RWIN": 0x80, "KC_RCMD": 0x80,
}


def _trigger_mask(trigger: Any) -> int:
    items = [trigger] if isinstance(trigger, str) else trigger
    if not isinstance(items, list):
        return 0
    mask = 0
    for item in items:
        mask |= _MOD_ACTION_TO_MASK.get(str(item), 0)
    return mask


def _build_key_override_entries(codec: KeycodeCodec, interaction_settings: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(interaction_settings, dict):
        return []
    overrides = interaction_settings.get("key_overrides", [])
    if not isinstance(overrides, list):
        return []
    result: list[dict[str, Any]] = []
    for override in overrides:
        if not isinstance(override, dict):
            continue
        trigger_mods = _trigger_mask(override.get("trigger", []))
        negative_mods = _trigger_mask(override.get("negative_trigger", override.get("negative", [])))
        options = int(override.get("options", 0x83 if trigger_mods else 0x81))
        result.append({
            "trigger": codec.action_to_vial(str(override.get("key", "KC_NONE"))),
            "replacement": codec.action_to_vial(str(override.get("replacement", "KC_NONE"))),
            "layers": int(override.get("layers", 0xFFFF)),
            "trigger_mods": trigger_mods,
            "negative_mod_mask": negative_mods,
            "suppressed_mods": int(override.get("suppressed_mods", 0)),
            "options": options,
        })
    return result


def build_vil_from_files(
    *,
    vial_json: Path = DEFAULT_VIAL_JSON,
    keymap_json: Path = DEFAULT_KEYMAP_JSON,
    layers: list[dict[str, str]] | None = None,
    codec: KeycodeCodec | None = None,
    config_json: Path | None = None,
) -> dict[str, Any]:
    vial = load_json(vial_json)
    rows, cols = matrix_size(vial)
    if layers is None:
        layers = load_keymap_layers(keymap_json)
    codec = codec or KeycodeCodec(vial_json.with_name("keycodes.json"))
    interaction_settings = None
    vial_macro_buffer = None
    if config_json is not None:
        try:
            cfg = load_json(config_json)
            raw = cfg.get("settings", {}).get("interaction")
            if isinstance(raw, dict):
                interaction_settings = raw
            raw_macro = cfg.get("settings", {}).get("vial_macro_buffer")
            if isinstance(raw_macro, str):
                vial_macro_buffer = raw_macro
        except (OSError, json.JSONDecodeError):
            interaction_settings = None
            vial_macro_buffer = None
    return build_vil_document(
        uid=keyboard_uid(vial),
        rows=rows,
        cols=cols,
        layers=layers,
        encoder_map=load_encoder_map(keymap_json),
        codec=codec,
        interaction_settings=interaction_settings,
        vial_macro_buffer=vial_macro_buffer,
    )


def parse_vil_from_files(
    data: bytes | str,
    *,
    vial_json: Path = DEFAULT_VIAL_JSON,
    keymap_json: Path = DEFAULT_KEYMAP_JSON,
    force_uid: bool = False,
    codec: KeycodeCodec | None = None,
) -> VilImportPlan:
    vial = load_json(vial_json)
    rows, cols = matrix_size(vial)
    codec = codec or KeycodeCodec(vial_json.with_name("keycodes.json"))
    return parse_vil_import(
        data,
        expected_uid=keyboard_uid(vial),
        rows=rows,
        cols=cols,
        encoder_map=load_encoder_map(keymap_json),
        force_uid=force_uid,
        codec=codec,
    )


def send_ctrl_command(ctrl_socket: Path, command: dict[str, Any], timeout: float = 2.0) -> dict[str, Any]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(ctrl_socket))
        client.sendall(json.dumps(command).encode("utf-8") + b"\n")
        chunks: list[bytes] = []
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\n" in chunk:
                break
    if not chunks:
        raise RuntimeError(f"no response from {ctrl_socket}")
    return json.loads(b"".join(chunks).splitlines()[0].decode("utf-8"))


def apply_import_plan(plan: VilImportPlan, *, ctrl_socket: Path = DEFAULT_CTRL_SOCKET) -> int:
    applied = 0
    for remap in plan.remaps:
        resp = send_ctrl_command(ctrl_socket, {
            "t": "M",
            "l": remap.layer,
            "r": remap.row,
            "c": remap.col,
            "a": remap.action,
        })
        if resp.get("result") != "ok":
            raise RuntimeError(f"remap failed at L{remap.layer} ({remap.row},{remap.col}): {resp}")
        applied += 1
    resp = send_ctrl_command(ctrl_socket, {"t": "S"})
    if resp.get("result") != "ok":
        raise RuntimeError(f"save failed: {resp}")
    return applied


def parse_vil_import(
    data: bytes | str,
    *,
    expected_uid: int,
    rows: int,
    cols: int,
    encoder_map: list[tuple[tuple[int, int], tuple[int, int]]],
    force_uid: bool = False,
    codec: KeycodeCodec | None = None,
) -> VilImportPlan:
    codec = codec or KeycodeCodec()
    if isinstance(data, bytes):
        raw = data.decode("utf-8")
    else:
        raw = data
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid .vil JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError(".vil root must be an object")
    if int(document.get("version", 0)) != VIL_VERSION:
        raise ValueError(f"unsupported .vil version: {document.get('version')}")

    warnings: list[str] = []
    _warn_unknown_fields(document, KNOWN_VIL_TOP_LEVEL_KEYS, warnings, ".vil root")

    uid = document.get("uid")
    uid_int = int(uid) if uid is not None else None
    uid_mismatch = uid_int is not None and uid_int != expected_uid
    if uid_mismatch and not force_uid:
        return VilImportPlan(uid=uid_int, remaps=[], warnings=[], uid_mismatch=True)
    if uid_mismatch and force_uid:
        warnings.append(f"uid mismatch forced: file={uid_int} expected={expected_uid}")

    settings = document.get("settings", {})
    if isinstance(settings, dict):
        _warn_unknown_fields(settings, KNOWN_VIL_SETTINGS_KEYS, warnings, ".vil settings")
        export_warnings = settings.get(HIDLOOM_EXPORT_WARNINGS_KEY, [])
        if isinstance(export_warnings, list):
            warnings.extend(str(warning) for warning in export_warnings if isinstance(warning, str))
        raw_interaction_settings = settings.get(HIDLOOM_INTERACTION_SETTINGS_KEY)
        interaction_settings = raw_interaction_settings if isinstance(raw_interaction_settings, dict) else None
        raw_vial_macro_buffer = settings.get(HIDLOOM_VIAL_MACRO_BUFFER_KEY)
        vial_macro_buffer = raw_vial_macro_buffer if isinstance(raw_vial_macro_buffer, str) else None
    elif settings is not None:
        warnings.append(".vil settings ignored: not an object")
        interaction_settings = None
        vial_macro_buffer = None
    else:
        interaction_settings = None
        vial_macro_buffer = None

    remaps: list[VilRemap] = []
    layout = document.get("layout", [])
    if not isinstance(layout, list):
        raise ValueError(".vil layout must be an array")

    for layer_idx, layer_rows in enumerate(layout):
        if not isinstance(layer_rows, list):
            warnings.append(f"layout layer {layer_idx} ignored: not an array")
            continue
        if len(layer_rows) > rows:
            warnings.append(f"layout layer {layer_idx}: {len(layer_rows) - rows} row(s) beyond matrix rows ignored")
        for row_idx, row_values in enumerate(layer_rows[:rows]):
            if not isinstance(row_values, list):
                warnings.append(f"layout layer {layer_idx} row {row_idx} ignored: not an array")
                continue
            if len(row_values) > cols:
                warnings.append(f"layout layer {layer_idx} row {row_idx}: {len(row_values) - cols} column(s) beyond matrix cols ignored")
            for col_idx, keycode in enumerate(row_values[:cols]):
                action = _decode_keycode(codec, keycode, warnings, f"L{layer_idx} ({row_idx},{col_idx})")
                if action is not None:
                    remaps.append(VilRemap(layer_idx, row_idx, col_idx, action))

    encoder_layout = document.get("encoder_layout", [])
    if isinstance(encoder_layout, list):
        for layer_idx, layer_encoders in enumerate(encoder_layout):
            if not isinstance(layer_encoders, list):
                warnings.append(f"encoder_layout layer {layer_idx} ignored: not an array")
                continue
            if len(layer_encoders) > len(encoder_map):
                warnings.append(f"encoder_layout layer {layer_idx}: {len(layer_encoders) - len(encoder_map)} encoder(s) beyond config ignored")
            for enc_idx, values in enumerate(layer_encoders[:len(encoder_map)]):
                if not isinstance(values, list):
                    warnings.append(f"encoder_layout layer {layer_idx} encoder {enc_idx} ignored: not an array")
                    continue
                if len(values) > 2:
                    warnings.append(f"encoder_layout layer {layer_idx} encoder {enc_idx}: {len(values) - 2} extra value(s) ignored")
                for action_idx, keycode in enumerate(values[:2]):
                    row, col = encoder_map[enc_idx][action_idx]
                    action = _decode_keycode(codec, keycode, warnings, f"L{layer_idx} encoder {enc_idx}.{action_idx}")
                    if action is not None:
                        remaps.append(VilRemap(layer_idx, row, col, action))
    elif encoder_layout is not None:
        warnings.append("encoder_layout ignored: not an array")

    return VilImportPlan(
        uid=uid_int,
        remaps=remaps,
        warnings=warnings,
        uid_mismatch=uid_mismatch,
        interaction_settings=interaction_settings,
        vial_macro_buffer=vial_macro_buffer,
    )


def _warn_unknown_fields(document: dict[str, Any], known_keys: set[str], warnings: list[str], label: str) -> None:
    for key in sorted(document):
        if key not in known_keys:
            warnings.append(f"{label}: unknown field {key!r} ignored")


def _encode_action(codec: KeycodeCodec, action: str, warnings: list[str], label: str) -> int:
    keycode = codec.action_to_vial(action)
    if keycode == VIAL_KC_NO and action not in {"KC_NONE", "KC_NO"}:
        warnings.append(f"{label}: unsupported action {action!r}; exported as KC_NONE")
    return keycode


def _decode_keycode(codec: KeycodeCodec, raw: Any, warnings: list[str], label: str) -> str | None:
    try:
        keycode = int(raw)
    except (TypeError, ValueError):
        warnings.append(f"{label}: invalid keycode {raw!r}")
        return None
    if keycode < 0:
        warnings.append(f"{label}: negative keycode {keycode} ignored")
        return None
    action = codec.vial_to_action(keycode)
    if action is None:
        warnings.append(f"{label}: unsupported keycode 0x{keycode:04x}")
    return action


def _default_export_filename(vial_json: Path) -> str:
    try:
        uid = keyboard_uid(load_json(vial_json))
    except (OSError, json.JSONDecodeError, ValueError):
        uid = 0
    hostname = socket.gethostname() or "keyboard"
    return f"{hostname}-{uid:x}.vil"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export or inspect Vial .vil layout files.")
    parser.add_argument("--vial-json", type=Path, default=DEFAULT_VIAL_JSON)
    parser.add_argument("--keymap-json", type=Path, default=DEFAULT_KEYMAP_JSON)
    sub = parser.add_subparsers(dest="command", required=True)

    export_p = sub.add_parser("export", help="Export config/default/keymap.json as a .vil JSON file.")
    export_p.add_argument("-o", "--output", type=Path)

    check_p = sub.add_parser("check", help="Validate a .vil file and print the import summary.")
    check_p.add_argument("input", type=Path)
    check_p.add_argument("--force-uid", action="store_true")

    import_p = sub.add_parser("import", help="Import a .vil file through logicd ctrl socket.")
    import_p.add_argument("input", type=Path)
    import_p.add_argument("--force-uid", action="store_true")
    import_p.add_argument("--dry-run", action="store_true")
    import_p.add_argument("--ctrl-socket", type=Path, default=DEFAULT_CTRL_SOCKET)

    args = parser.parse_args(argv)
    if args.command == "export":
        payload = encode_vil(build_vil_from_files(vial_json=args.vial_json, keymap_json=args.keymap_json))
        output = args.output or Path(_default_export_filename(args.vial_json))
        output.write_bytes(payload)
        print(f"wrote {output} ({len(payload)} bytes)")
        return 0

    if args.command == "check":
        plan = parse_vil_from_files(
            args.input.read_text(encoding="utf-8"),
            vial_json=args.vial_json,
            keymap_json=args.keymap_json,
            force_uid=args.force_uid,
        )
        print(f"uid: {plan.uid}")
        print(f"uid_mismatch: {plan.uid_mismatch}")
        print(f"remaps: {len(plan.remaps)}")
        if plan.warnings:
            print("warnings:")
            for warning in plan.warnings:
                print(f"- {warning}")
        return 2 if plan.uid_mismatch and not args.force_uid else 0

    if args.command == "import":
        plan = parse_vil_from_files(
            args.input.read_text(encoding="utf-8"),
            vial_json=args.vial_json,
            keymap_json=args.keymap_json,
            force_uid=args.force_uid,
        )
        print(f"uid: {plan.uid}")
        print(f"uid_mismatch: {plan.uid_mismatch}")
        print(f"remaps: {len(plan.remaps)}")
        if plan.uid_mismatch and not args.force_uid:
            print("refusing import because uid differs; rerun with --force-uid to apply")
            return 2
        if plan.warnings:
            print("warnings:")
            for warning in plan.warnings:
                print(f"- {warning}")
        if args.dry_run:
            print("dry-run: no changes applied")
            return 0
        applied = apply_import_plan(plan, ctrl_socket=args.ctrl_socket)
        print(f"applied {applied} remap(s)")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
