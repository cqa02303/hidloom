#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


def target_environment(target: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = ":".join(
        (
            str(target / "usr/share/hidloom/daemon"),
            str(target / "usr/share/hidloom"),
            str(target / "usr/lib/python3.14/site-packages"),
        )
    )
    environment["HIDLOOM_REPO_ROOT"] = str(target / "usr/share/hidloom")
    environment["HIDLOOM_RUNTIME_DIR"] = str(target / "mnt/p3")
    return environment


def smoke_split_routing(qemu: str, target: Path, temporary: Path) -> None:
    keymap = temporary / "keymap.json"
    keymap.write_text(json.dumps({"layers": [{"0,0": "KC_RO", "0,1": "KC_A"}]}), encoding="utf-8")
    replay = temporary / "matrix.bin"
    replay.write_bytes(b"P00\nR00\nP01\nR01\n")
    environment = target_environment(target)
    environment.update(
        {
            "LOGICD_CORE_KEYMAP_PATH": str(keymap),
            "LOGICD_CORE_DEFAULT_KEYMAP_PATH": str(keymap),
            "LOGICD_CORE_KEYCODES_PATH": str(target / "usr/share/hidloom/config/default/keycodes.json"),
            "LOGICD_CORE_DEFAULT_KEYCODES_PATH": str(target / "usr/share/hidloom/config/default/keycodes.json"),
            "LOGICD_USB_SPLIT_KEYBOARD": "1",
            "LOGICD_USB_SPLIT_KEYBOARD_ROUTE": "jis_special_us_default",
        }
    )
    result = subprocess.run(
        [qemu, "-L", str(target), str(target / "usr/bin/hidloom-logicd-core"), "--replay", str(replay)],
        check=True,
        cwd="/tmp",
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    presses = [(event.get("kind_name"), event.get("report")) for event in events if event.get("report") not in {None, "0000000000000000"}]
    if ("keyboard", "0000870000000000") not in presses:
        raise SystemExit(f"KC_RO did not route to the JIS main keyboard: {presses}")
    if ("us_sub_keyboard", "0000040000000000") not in presses:
        raise SystemExit(f"KC_A did not route to the US sub keyboard: {presses}")
    print("ok: M6 ARM split routing (KC_RO=JIS main, KC_A=US sub)")


def smoke_companion(qemu: str, target: Path, temporary: Path) -> None:
    environment = target_environment(target)
    environment.update(
        {
            "LOGICD_MATRIX_SOCKET": "none",
            "LOGICD_DELEGATE_SOCKET": str(temporary / "logicd_delegate_events.sock"),
            "LOGICD_CORE_KEY_EVENT_CTRL_SOCKET": str(temporary / "logicd_core_ctrl.sock"),
            "LOGICD_OUTPUTS": "debug",
            "LOGICD_NATIVE_OUTPUTD_CTRL": "1",
            "LOGICD_OUTPUTD_CTRL_SOCKET": str(temporary / "hidloom_output_ctrl.sock"),
            "LOGICD_USBD_HID_REPORT_BROKER": "0",
            "LOGICD_LEDD_SOCKET": str(temporary / "ledd_events.sock"),
            "LOGICD_I2C_SOCKET": str(temporary / "i2c_events.sock"),
            "LOGICD_SHUTDOWN_COMMAND": "true",
        }
    )
    process = subprocess.Popen(
        [qemu, "-L", str(target), str(target / "usr/bin/python3"), "-m", "logicd.logicd"],
        cwd="/tmp",
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    time.sleep(4.0)
    if process.poll() is not None:
        output = process.stdout.read() if process.stdout is not None else ""
        raise SystemExit(f"logicd companion exited during ARM runtime smoke ({process.returncode}):\n{output}")
    process.terminate()
    try:
        output, _ = process.communicate(timeout=3.0)
    except subprocess.TimeoutExpired:
        process.kill()
        output, _ = process.communicate()
    if "runtime initialized" not in output:
        raise SystemExit(f"logicd companion did not initialize during ARM runtime smoke:\n{output}")
    print("ok: M6 ARM logicd companion remained active after runtime initialization")


def main() -> None:
    parser = argparse.ArgumentParser(description="Exercise the M6 ARM runtime beyond imports")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--qemu", default="qemu-arm")
    args = parser.parse_args()
    target = args.output.resolve() / "target"
    qemu = shutil.which(args.qemu)
    if qemu is None:
        raise SystemExit(f"ARM emulator not found: {args.qemu}")
    with tempfile.TemporaryDirectory(prefix="m6-runtime-smoke-") as directory:
        temporary = Path(directory)
        smoke_split_routing(qemu, target, temporary)
        smoke_companion(qemu, target, temporary)


if __name__ == "__main__":
    main()
