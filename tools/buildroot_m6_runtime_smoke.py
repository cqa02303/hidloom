#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time


FRAME_SIZE = 64
CHECKSUM_OFFSET = 63
PAYLOAD_OFFSET = 8
KIND_KEYBOARD = 0x01
KIND_US_SUB_KEYBOARD = 0x04


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


def encode_frame(kind: int, payload: bytes) -> bytes:
    frame = bytearray(FRAME_SIZE)
    frame[0:4] = b"CQAU"
    frame[4] = 1
    frame[5] = kind
    frame[6] = len(payload)
    frame[PAYLOAD_OFFSET : PAYLOAD_OFFSET + len(payload)] = payload
    checksum = 0
    for byte in frame[:CHECKSUM_OFFSET]:
        checksum ^= byte
    frame[CHECKSUM_OFFSET] = checksum
    return bytes(frame)


def wait_for_path(path: Path) -> None:
    deadline = time.time() + 3.0
    while time.time() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    raise SystemExit(f"M6 runtime path did not appear: {path}")


def wait_for_json(path: Path, predicate) -> dict:
    deadline = time.time() + 3.0
    while time.time() < deadline:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(0.01)
            continue
        if predicate(payload):
            return payload
        time.sleep(0.01)
    raise SystemExit(f"M6 runtime JSON state did not converge: {path}")


def ctrl_request(path: Path, payload: dict) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(3.0)
        client.connect(str(path))
        client.sendall((json.dumps(payload, separators=(",", ":")) + "\n").encode())
        response = b""
        while not response.endswith(b"\n"):
            chunk = client.recv(4096)
            if not chunk:
                break
            response += chunk
    return json.loads(response.decode())


def send_frame(path: Path, frame: bytes) -> None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sender:
        sender.sendto(frame, str(path))


def wait_process(process: subprocess.Popen, label: str) -> None:
    try:
        stdout, stderr = process.communicate(timeout=5.0)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        raise SystemExit(f"{label} did not exit:\n{stdout}\n{stderr}")
    if process.returncode != 0:
        raise SystemExit(f"{label} failed ({process.returncode}):\n{stdout}\n{stderr}")


def smoke_hidd_startup_release(qemu: str, target: Path, temporary: Path) -> None:
    report_socket = temporary / "hidd_reports.sock"
    hidg0 = temporary / "hidg0"
    hidg2 = temporary / "hidg2"
    status_path = temporary / "hidd-status.json"
    hidg0.write_bytes(b"")
    hidg2.write_bytes(b"")
    environment = target_environment(target)
    environment.update(
        {
            "USBD_HID_REPORT_SOCKET": str(report_socket),
            "USBD_HID_REPORT_PATH": str(hidg0),
            "USBD_US_SUB_HID_REPORT_PATH": str(hidg2),
            "HIDD_STATUS_PATH": str(status_path),
            "HIDD_RAW_HID_BRIDGE_ENABLED": "0",
            "USBD_KEYBOARD_STARTUP_RELEASE": "1",
            "USBD_HID_WRITE_RETRY_TIMEOUT_SEC": "0.02",
            "USBD_HID_WRITE_RETRY_INTERVAL_SEC": "0.001",
        }
    )
    process = subprocess.Popen(
        [qemu, "-L", str(target), str(target / "usr/bin/hidloom-hidd"), "--frames", "1"],
        cwd="/tmp",
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        wait_for_path(report_socket)
        send_frame(report_socket, b"not-a-valid-frame")
        wait_process(process, "M6 ARM hidloom-hidd startup release")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    if hidg0.read_bytes() != bytes.fromhex("010000000000000000"):
        raise SystemExit("M6 ARM hidd main keyboard startup release is not Report-ID 0x01 + 8 zero bytes")
    if hidg2.read_bytes() != bytes(8):
        raise SystemExit("M6 ARM hidd US sub keyboard startup release is not 8 zero bytes without a Report ID")
    status = json.loads(status_path.read_text(encoding="utf-8"))
    if status["counters"]["startup_release_reports"] != 2:
        raise SystemExit(f"M6 ARM hidd startup release count differs: {status}")
    print("ok: M6 ARM hidd startup release uses endpoint-specific report shapes")


def smoke_console_route(qemu: str, target: Path, temporary: Path) -> None:
    uidd_socket = temporary / "uidd_reports.sock"
    uidd_status_path = temporary / "uidd-status.json"
    uidd_events_path = temporary / "uidd-events.ndjson"
    outputd_report_socket = temporary / "output_reports.sock"
    outputd_ctrl_socket = temporary / "output_ctrl.sock"
    outputd_status_path = temporary / "outputd-status.json"
    usb_socket_path = temporary / "usb_reports.sock"

    usb = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    usb.bind(str(usb_socket_path))
    usb.settimeout(3.0)
    uidd_environment = target_environment(target)
    uidd_environment.update(
        {
            "UIDD_REPORT_SOCKET": str(uidd_socket),
            "UIDD_STATUS_PATH": str(uidd_status_path),
            "UIDD_EVENT_LOG_PATH": str(uidd_events_path),
            "UIDD_DRY_RUN": "1",
        }
    )
    uidd = subprocess.Popen(
        [qemu, "-L", str(target), str(target / "usr/bin/hidloom-uidd"), "--frames", "10"],
        cwd="/tmp",
        env=uidd_environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    outputd = None
    try:
        wait_for_path(uidd_socket)
        outputd_environment = target_environment(target)
        outputd_environment.update(
            {
                "OUTPUTD_REPORT_SOCKET": str(outputd_report_socket),
                "OUTPUTD_CTRL_SOCKET": str(outputd_ctrl_socket),
                "OUTPUTD_USB_SOCKET": str(usb_socket_path),
                "OUTPUTD_UIDD_SOCKET": str(uidd_socket),
                "OUTPUTD_BT_SOCKET": str(temporary / "btd_events.sock"),
                "OUTPUTD_STATUS_PATH": str(outputd_status_path),
                "OUTPUTD_TARGET": "usb",
            }
        )
        outputd = subprocess.Popen(
            [qemu, "-L", str(target), str(target / "usr/bin/hidloom-outputd"), "--frames", "7"],
            cwd="/tmp",
            env=outputd_environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        wait_for_path(outputd_ctrl_socket)

        null_keyboard = encode_frame(KIND_KEYBOARD, bytes(8))
        null_us_sub = encode_frame(KIND_US_SUB_KEYBOARD, bytes(8))
        if ctrl_request(outputd_ctrl_socket, {"t": "set_output_target", "target": "uinput"}) != {
            "result": "ok",
            "target": "uinput",
        }:
            raise SystemExit("M6 ARM outputd rejected the uinput target")
        if [usb.recv(128), usb.recv(128)] != [null_keyboard, null_us_sub]:
            raise SystemExit("M6 ARM outputd did not release USB before uinput")

        for payload in (
            "0000130000000000",
            "0000000000000000",
            "00000c0000000000",
            "0000000000000000",
            "0000280000000000",
            "0000000000000000",
        ):
            send_frame(outputd_report_socket, encode_frame(KIND_US_SUB_KEYBOARD, bytes.fromhex(payload)))
        wait_for_json(
            uidd_status_path,
            lambda status: status["counters"]["frames_received"] >= 8,
        )

        if ctrl_request(outputd_ctrl_socket, {"t": "set_output_target", "target": "usb"}) != {
            "result": "ok",
            "target": "usb",
        }:
            raise SystemExit("M6 ARM outputd rejected the USB return target")
        if [usb.recv(128), usb.recv(128)] != [null_keyboard, null_us_sub]:
            raise SystemExit("M6 ARM outputd did not release uinput before USB return")
        final_usb = encode_frame(KIND_KEYBOARD, bytes.fromhex("0000040000000000"))
        send_frame(outputd_report_socket, final_usb)
        if usb.recv(128) != final_usb:
            raise SystemExit("M6 ARM outputd did not restore USB forwarding")

        wait_process(outputd, "M6 ARM hidloom-outputd")
        wait_process(uidd, "M6 ARM hidloom-uidd")
        outputd_status = json.loads(outputd_status_path.read_text(encoding="utf-8"))
        uidd_status = json.loads(uidd_status_path.read_text(encoding="utf-8"))
        events = [
            json.loads(line)
            for line in uidd_events_path.read_text(encoding="utf-8").splitlines()
        ]
        expected_events = [
            (1, 25, 1), (0, 0, 0), (1, 25, 0), (0, 0, 0),
            (1, 23, 1), (0, 0, 0), (1, 23, 0), (0, 0, 0),
            (1, 28, 1), (0, 0, 0), (1, 28, 0), (0, 0, 0),
        ]
        actual_events = [(event["type"], event["code"], event["value"]) for event in events]
        if actual_events != expected_events:
            raise SystemExit(f"M6 ARM console login events differ: {actual_events}")
        if outputd_status["target"] != "usb" or outputd_status["counters"]["release_frames"] != 8:
            raise SystemExit(f"M6 ARM output route did not complete the round trip: {outputd_status}")
        if uidd_status["counters"]["frames_received"] != 10:
            raise SystemExit(f"M6 ARM uinput frame count differs: {uidd_status}")
    finally:
        usb.close()
        for process in (outputd, uidd):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    print("ok: M6 ARM USB/uinput console login route round trip")


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
        smoke_hidd_startup_release(qemu, target, temporary)
        smoke_split_routing(qemu, target, temporary)
        smoke_console_route(qemu, target, temporary)
        smoke_companion(qemu, target, temporary)


if __name__ == "__main__":
    main()
