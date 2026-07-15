#!/usr/bin/env python3
"""Run keyboard real-device smoke tests on cqa02303v5 keyboard profiles."""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from viald.keycode_codec import KeycodeCodec  # noqa: E402

VALIDATION = ("python3", "script/test_validation_suite.py")

LIVE_SMOKE = (
    ("sudo", "python3", "script/test_vial_protocol.py"),
    ("sudo", "python3", "script/test_vialrgb_protocol.py"),
    ("sudo", "python3", "script/test_vialrgb_persistence.py"),
    ("sudo", "python3", "script/test_vial_set_keycode.py", "KC_ESC", "--row", "7", "--col", "0"),
)

PYTHON_OWNER_SMOKE = (
    ("sudo", "python3", "script/test_vial_unlock_runtime.py"),
    ("sudo", "python3", "script/test_vial_matrix_state_runtime.py"),
)

MATRIXD_STABILITY = (
    "sudo", "python3", "tools/matrixd_stability_smoke.py",
    "--duration", "60",
    "--speed", "32",
    "--hue", "183",
    "--saturation", "163",
    "--value", "160",
)


def run_command(command: tuple[str, ...]) -> bool:
    print("== " + " ".join(command), flush=True)
    return subprocess.run(command, cwd=ROOT).returncode == 0


def service_active(unit: str) -> bool:
    return subprocess.run(
        ("systemctl", "is-active", "--quiet", unit),
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0


def native_owner_active() -> bool:
    return service_active("hidloom-logicd-core.service")


def ctrl_message(msg: dict[str, object], socket_path: str = "/tmp/ctrl_events.sock") -> dict[str, object]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(socket_path)
        sock.sendall((json.dumps(msg) + "\n").encode())
        data = b""
        while not data.endswith(b"\n"):
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
    return json.loads(data.decode()) if data else {}


def release_matrix_key(row: int, col: int, socket_path: str = "/tmp/matrix_events.sock") -> None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(socket_path)
        sock.sendall(bytes([ord("R"), ord(format(row, "X")), ord(format(col, "X")), 0]))


def clear_pressed_matrix_state() -> None:
    pressed = ctrl_message({"t": "K"}).get("pressed", [])
    if not pressed:
        return
    print(f"clearing pressed matrix state before smoke: {pressed}", flush=True)
    for row, col in pressed:
        release_matrix_key(int(row), int(col))


def choose_runtime_slot() -> tuple[int, int, int, str]:
    pressed = {
        (int(row), int(col))
        for row, col in ctrl_message({"t": "K"}).get("pressed", [])
        if isinstance(row, int) and isinstance(col, int)
    }
    keymap = ctrl_message({"t": "G"}).get("layers", [{}])
    layer0 = keymap[0] if isinstance(keymap, list) and keymap and isinstance(keymap[0], dict) else {}
    codec = KeycodeCodec()
    candidates: list[tuple[int, int, int, str]] = []
    for key, action in layer0.items():
        try:
            row_s, col_s = str(key).split(",", 1)
            row, col = int(row_s), int(col_s)
        except ValueError:
            continue
        if (row, col) in pressed:
            continue
        if not isinstance(action, str) or action in {"KC_NO", "KC_TRNS"}:
            continue
        keycode = codec.action_to_vial(action)
        if keycode == 0 and action != "KC_NONE":
            continue
        candidates.append((row, col, keycode, action))
    if not candidates:
        raise RuntimeError(f"no unpressed Vial-compatible runtime slot found; pressed={sorted(pressed)}")
    candidates.sort(key=lambda item: (item[0], item[1]))
    row, col, keycode, action = candidates[0]
    print(f"selected runtime smoke slot: row={row} col={col} action={action} keycode=0x{keycode:04x}", flush=True)
    return row, col, keycode, action


def main() -> None:
    parser = argparse.ArgumentParser(description="Run keyboard real-device smoke suite")
    parser.add_argument("--skip-validation", action="store_true")
    parser.add_argument("--skip-matrixd-stability", action="store_true")
    parser.add_argument("--no-clear-pressed", action="store_true")
    parser.add_argument(
        "--include-python-owner-smoke",
        action="store_true",
        help="also run legacy Python-owner Vial matrix/key_events runtime smoke tests",
    )
    parser.add_argument("--matrixd-output", default="/tmp/hidloom-smoke/matrixd-current-effect-suite.md")
    args = parser.parse_args()

    failed: list[str] = []
    native_owner = native_owner_active()
    if native_owner:
        print("native owner active: skipping Python-owner runtime smoke unless explicitly requested", flush=True)
    if not args.no_clear_pressed:
        clear_pressed_matrix_state()

    if not args.skip_validation and not run_command(VALIDATION):
        failed.append("validation")

    for command in LIVE_SMOKE:
        if not run_command(command):
            failed.append(" ".join(command))

    if args.include_python_owner_smoke or not native_owner:
        for command in PYTHON_OWNER_SMOKE:
            if not run_command(command):
                failed.append(" ".join(command))

    try:
        row, col, keycode, _action = choose_runtime_slot()
        if args.include_python_owner_smoke or not native_owner:
            runtime_path = (
                "sudo", "python3", "script/test_vial_runtime_path.py",
                "--row", str(row),
                "--col", str(col),
                "--expected-original", f"0x{keycode:04x}",
            )
            if not run_command(runtime_path):
                failed.append(" ".join(runtime_path))
        else:
            print(
                "skip Python-owner runtime path smoke on native owner: "
                f"row={row} col={col} action={_action} keycode=0x{keycode:04x}",
                flush=True,
            )

        row, col, _keycode, _action = choose_runtime_slot()
        lighting = ("sudo", "python3", "script/test_lighting_key_runtime.py", "--row", str(row), "--col", str(col))
        if not run_command(lighting):
            failed.append(" ".join(lighting))
    except RuntimeError as exc:
        print(f"runtime slot selection failed: {exc}")
        failed.append("runtime_slot_selection")

    if not args.skip_matrixd_stability:
        command = MATRIXD_STABILITY + ("--output", args.matrixd_output)
        if not run_command(command):
            failed.append("matrixd_stability")

    if failed:
        print("FAILED keyboard real-device smoke suite:")
        for item in failed:
            print(f"- {item}")
        raise SystemExit(1)
    print("ok: keyboard real-device smoke suite")


if __name__ == "__main__":
    main()
