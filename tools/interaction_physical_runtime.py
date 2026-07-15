#!/usr/bin/env python3
"""Prepare and restore runtime entries for InteractionEngine physical tests."""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable


TEST_ASSIGNMENTS = [
    (1, 0, 2, "OSL(2)", "Layer 1: 1 -> one-shot Layer 2"),
    (1, 0, 3, "LT(2,KC_A)", "Layer 1: 2 -> tap A / hold Layer 2"),
    (1, 0, 4, "MT(KC_LSFT,KC_A)", "Layer 1: 3 -> tap A / hold Left Shift"),
    (1, 0, 5, "TT(2)", "Layer 1: 4 -> tap toggle Layer 2 / hold Layer 2"),
    (1, 0, 6, "TD(TD0)", "Layer 1: 5 -> tap dance TD0"),
    (1, 0, 7, "SC_LSPO", "Layer 1: 6 -> Space Cadet left shift / ("),
    (1, 0, 8, "SC_RSPC", "Layer 1: 7 -> Space Cadet right shift / )"),
    (2, 1, 2, "KC_ESC", "Layer 2: Q -> ESC"),
    (2, 1, 3, "KC_TAB", "Layer 2: W -> TAB"),
]

RESTORE_ASSIGNMENTS = [
    (1, 0, 2, "KC_TRNS"),
    (1, 0, 3, "KC_TRNS"),
    (1, 0, 4, "KC_TRNS"),
    (1, 0, 5, "KC_TRNS"),
    (1, 0, 6, "KC_TRNS"),
    (1, 0, 7, "KC_TRNS"),
    (1, 0, 8, "KC_TRNS"),
    (2, 1, 2, "KC_TRNS"),
    (2, 1, 3, "KC_TRNS"),
]

TEST_TAP_DANCE_NAME = "TD0"
TEST_TAP_DANCE = {
    "1": "KC_A",
    "2": "KC_ESC",
    "3": "KC_TAB",
}
TEST_COMBO = {"keys": [[0, 1], [0, 2]], "action": "KC_ESC"}
TEST_KEY_OVERRIDE = {"trigger": "KC_LSFT", "key": "KC_1", "replacement": "KC_ESC"}

DEFAULT_CONFIG_CANDIDATES = (
    Path("/mnt/p3/config.json"),
    Path(__file__).resolve().parents[1] / "config" / "default" / "config.json",
)
DEFAULT_BACKUP = Path("/tmp/hidloom-interaction-physical-runtime-backup.json")


def json_request(sock_path: str, msg: dict) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(3.0)
        sock.connect(sock_path)
        sock.sendall((json.dumps(msg, separators=(",", ":")) + "\n").encode())
        data = b""
        while not data.endswith(b"\n"):
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
    return json.loads(data.decode()) if data else {}


def set_action(ctrl_sock: str, layer: int, row: int, col: int, action: str) -> dict:
    return json_request(ctrl_sock, {"t": "M", "l": layer, "r": row, "c": col, "a": action})


def get_keymap(ctrl_sock: str) -> dict:
    return json_request(ctrl_sock, {"t": "G"})


def get_pressed(ctrl_sock: str) -> dict:
    return json_request(ctrl_sock, {"t": "K"})


def default_config_path() -> Path:
    for candidate in DEFAULT_CONFIG_CANDIDATES:
        if candidate.exists():
            return candidate
    return DEFAULT_CONFIG_CANDIDATES[-1]


def load_config(config_path: Path) -> dict:
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"settings": {}}
    if not isinstance(data, dict):
        raise SystemExit(f"config root must be an object: {config_path}")
    data.setdefault("settings", {})
    if not isinstance(data["settings"], dict):
        data["settings"] = {}
    return data


def atomic_write_json(path: Path, data: dict) -> None:
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


def interaction_settings(config: dict) -> dict:
    settings = config.setdefault("settings", {})
    if not isinstance(settings, dict):
        config["settings"] = settings = {}
    interaction = settings.setdefault("interaction", {})
    if not isinstance(interaction, dict):
        settings["interaction"] = interaction = {}
    return interaction


def ensure_backup(config_path: Path, backup_path: Path) -> None:
    if backup_path.exists():
        print(f"keep existing backup: {backup_path}")
        return
    cfg = load_config(config_path)
    backup = {
        "schema": "interaction_physical_runtime.backup.v1",
        "config_path": str(config_path),
        "interaction": interaction_settings(cfg),
    }
    atomic_write_json(backup_path, backup)
    try:
        backup_path.chmod(0o600)
    except OSError:
        pass
    print(f"backup interaction settings -> {backup_path}")


def _same_combo(left: dict, right: dict) -> bool:
    return left.get("action") == right.get("action") and left.get("keys") == right.get("keys")


def _same_key_override(left: dict, right: dict) -> bool:
    return (
        left.get("trigger") == right.get("trigger")
        and left.get("key") == right.get("key")
        and left.get("replacement") == right.get("replacement")
    )


def apply_test_definitions(config_path: Path, backup_path: Path) -> None:
    ensure_backup(config_path, backup_path)
    cfg = load_config(config_path)
    interaction = interaction_settings(cfg)

    tap_dances = interaction.setdefault("tap_dances", {})
    if not isinstance(tap_dances, dict):
        tap_dances = {}
        interaction["tap_dances"] = tap_dances
    tap_dances[TEST_TAP_DANCE_NAME] = dict(TEST_TAP_DANCE)

    combos = interaction.setdefault("combos", [])
    if not isinstance(combos, list):
        combos = []
        interaction["combos"] = combos
    if not any(isinstance(item, dict) and _same_combo(item, TEST_COMBO) for item in combos):
        combos.append({"keys": [list(key) for key in TEST_COMBO["keys"]], "action": TEST_COMBO["action"]})

    key_overrides = interaction.setdefault("key_overrides", [])
    if not isinstance(key_overrides, list):
        key_overrides = []
        interaction["key_overrides"] = key_overrides
    if not any(isinstance(item, dict) and _same_key_override(item, TEST_KEY_OVERRIDE) for item in key_overrides):
        key_overrides.append(dict(TEST_KEY_OVERRIDE))

    atomic_write_json(config_path, cfg)
    print(f"ok: interaction physical test definitions applied -> {config_path}")


def restore_test_definitions(config_path: Path, backup_path: Path) -> None:
    if not backup_path.exists():
        raise SystemExit(f"backup not found: {backup_path}")
    backup = json.loads(backup_path.read_text(encoding="utf-8"))
    if not isinstance(backup, dict) or backup.get("schema") != "interaction_physical_runtime.backup.v1":
        raise SystemExit(f"unsupported backup file: {backup_path}")
    cfg = load_config(config_path)
    settings = cfg.setdefault("settings", {})
    if not isinstance(settings, dict):
        cfg["settings"] = settings = {}
    interaction = backup.get("interaction", {})
    settings["interaction"] = interaction if isinstance(interaction, dict) else {}
    atomic_write_json(config_path, cfg)
    backup_path.unlink()
    print(f"ok: interaction physical test definitions restored -> {config_path}")


def definition_status(config_path: Path) -> dict:
    cfg = load_config(config_path)
    interaction = interaction_settings(cfg)
    tap_dances = interaction.get("tap_dances", {})
    combos = interaction.get("combos", [])
    key_overrides = interaction.get("key_overrides", [])
    has_td0 = isinstance(tap_dances, dict) and TEST_TAP_DANCE_NAME in tap_dances
    has_combo = isinstance(combos, list) and any(
        isinstance(item, dict) and _same_combo(item, TEST_COMBO) for item in combos
    )
    has_override = isinstance(key_overrides, list) and any(
        isinstance(item, dict) and _same_key_override(item, TEST_KEY_OVERRIDE) for item in key_overrides
    )
    return {
        "config": str(config_path),
        "tap_dance": {"name": TEST_TAP_DANCE_NAME, "ready": has_td0},
        "combo": {"keys": TEST_COMBO["keys"], "action": TEST_COMBO["action"], "ready": has_combo},
        "key_override": {
            "trigger": TEST_KEY_OVERRIDE["trigger"],
            "key": TEST_KEY_OVERRIDE["key"],
            "replacement": TEST_KEY_OVERRIDE["replacement"],
            "ready": has_override,
        },
        "ready": has_td0 and has_combo and has_override,
    }


def reload_logicd(*, enabled: bool, run_command=None) -> None:
    if not enabled:
        print("skip: logicd runtime reload")
        return
    runner = run_command or subprocess.run
    unit = ""
    for candidate in ("logicd-companion", "logicd"):
        active = runner(
            ["systemctl", "is-active", "--quiet", candidate],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=8,
        )
        if active.returncode == 0:
            unit = candidate
            break
    if not unit:
        raise SystemExit("no active logicd runtime service (checked logicd-companion, logicd)")
    proc = runner(
        ["systemctl", "reload", unit],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=8,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"systemctl reload {unit} failed"
            f"\nstdout:\n{proc.stdout}"
            f"\nstderr:\n{proc.stderr}"
        )
    print(f"ok: systemctl reload {unit}")


def apply_assignments(ctrl_sock: str, assignments: Iterable[tuple[int, int, int, str]]) -> None:
    for layer, row, col, action in assignments:
        resp = set_action(ctrl_sock, layer, row, col, action)
        if resp.get("result") != "ok":
            raise SystemExit(f"remap failed layer={layer} row={row} col={col}: {resp}")
        print(f"set L{layer} ({row},{col}) -> {action}")


def print_status(ctrl_sock: str) -> None:
    keymap = get_keymap(ctrl_sock)
    print(json.dumps({"active": keymap.get("active"), "mode": keymap.get("mode")}, ensure_ascii=False))
    layers = keymap.get("layers", [])
    for layer, row, col, action, note in TEST_ASSIGNMENTS:
        actual = "KC_NONE"
        if isinstance(layers, list) and layer < len(layers) and isinstance(layers[layer], dict):
            actual = str(layers[layer].get(f"{row},{col}", "KC_NONE"))
        marker = "ok" if actual == action else "diff"
        print(f"{marker}: {note}: expected={action} actual={actual}")
    print(json.dumps(get_pressed(ctrl_sock), ensure_ascii=False))


def print_definition_status(config_path: Path) -> None:
    status = definition_status(config_path)
    print(json.dumps({"interaction_definitions": status}, ensure_ascii=False))
    for key in ("tap_dance", "combo", "key_override"):
        marker = "ok" if status[key]["ready"] else "missing"
        print(f"{marker}: {key}: {json.dumps(status[key], ensure_ascii=False)}")


def run_preflight(ctrl_sock: str, config_path: Path) -> None:
    print_status(ctrl_sock)
    print_definition_status(config_path)
    status = definition_status(config_path)
    if not status["ready"]:
        raise SystemExit("preflight failed: interaction definitions are incomplete")
    print("ok: interaction physical runtime preflight")


def print_plan() -> None:
    print("Physical test sequence:")
    print("0. Run preflight; Tap Dance / Combo / Key Override require settings.interaction definitions")
    print("1. Fn hold -> 1 tap -> Fn release -> Q: OSL(2), expect Q resolves to KC_ESC")
    print("2. Fn hold -> tap 2 -> Fn release: LT tap, expect KC_A")
    print("3. Fn hold -> hold 2, press Q, release Q, release 2, release Fn: LT hold, expect Q resolves to KC_ESC")
    print("4. Fn hold -> tap 3 -> Fn release: MT tap, expect KC_A")
    print("5. Fn hold -> hold 3, release Fn, press 1, release 1, release 3: MT hold, expect shifted key behavior")
    print("6. Fn hold -> quick tap 4, release Fn, then Q: TT tap toggles Layer 2, expect Q resolves to KC_ESC")
    print("7. Fn hold -> hold 4, press Q, release Q, release 4, release Fn: TT hold, expect momentary Layer 2")
    print("8. Fn hold -> tap 5 once/twice/three times -> Fn release: TD0, expect KC_A / KC_ESC / KC_TAB")
    print("9. Layer 0: hold Left Shift, press 1: key override, expect KC_ESC")
    print("10. Layer 0: press grave + 1 together: combo, expect KC_ESC")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply/restore runtime keymap entries used for InteractionEngine physical tests.",
    )
    parser.add_argument(
        "command",
        choices=(
            "apply",
            "restore",
            "status",
            "plan",
            "preflight",
            "apply-definitions",
            "restore-definitions",
            "apply-all",
            "restore-all",
        ),
    )
    parser.add_argument("--ctrl", default="/tmp/ctrl_events.sock")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--backup", type=Path, default=DEFAULT_BACKUP)
    parser.add_argument("--no-reload", action="store_true", help="do not reload the active logicd runtime after config writes")
    args = parser.parse_args()

    if args.command == "plan":
        print_plan()
        return

    config_path = args.config or default_config_path()
    needs_ctrl = args.command in {"apply", "restore", "status", "preflight", "apply-all", "restore-all"}
    if needs_ctrl and not Path(args.ctrl).exists():
        raise SystemExit(f"socket not found: {args.ctrl}")

    if args.command == "apply":
        apply_assignments(args.ctrl, ((layer, row, col, action) for layer, row, col, action, _ in TEST_ASSIGNMENTS))
        print("ok: interaction physical test mappings applied")
    elif args.command == "restore":
        apply_assignments(args.ctrl, RESTORE_ASSIGNMENTS)
        print("ok: interaction physical test mappings restored")
    elif args.command == "status":
        print_status(args.ctrl)
        print_definition_status(config_path)
    elif args.command == "preflight":
        run_preflight(args.ctrl, config_path)
    elif args.command == "apply-definitions":
        apply_test_definitions(config_path, args.backup)
        reload_logicd(enabled=not args.no_reload)
    elif args.command == "restore-definitions":
        restore_test_definitions(config_path, args.backup)
        reload_logicd(enabled=not args.no_reload)
    elif args.command == "apply-all":
        apply_test_definitions(config_path, args.backup)
        reload_logicd(enabled=not args.no_reload)
        apply_assignments(args.ctrl, ((layer, row, col, action) for layer, row, col, action, _ in TEST_ASSIGNMENTS))
        print("ok: interaction physical test mappings and definitions applied")
        run_preflight(args.ctrl, config_path)
    elif args.command == "restore-all":
        apply_assignments(args.ctrl, RESTORE_ASSIGNMENTS)
        print("ok: interaction physical test mappings restored")
        restore_test_definitions(config_path, args.backup)
        reload_logicd(enabled=not args.no_reload)
        print_status(args.ctrl)


if __name__ == "__main__":
    main()
