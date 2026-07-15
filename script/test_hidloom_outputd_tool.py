#!/usr/bin/env python3
"""Regression tests for the native hidloom-outputd report router."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from usbd.hid_report_broker import (  # noqa: E402
    KIND_KEYBOARD,
    KIND_MOUSE,
    KIND_CONSUMER,
    KIND_US_SUB_KEYBOARD,
    encode_hid_report_request,
)

TOOL_DIR = ROOT / "tools" / "hidloom_outputd"
BIN = TOOL_DIR / "target" / "release" / "hidloom-outputd"


def build_tool() -> None:
    subprocess.run(["make", "-C", str(TOOL_DIR)], check=True)


def wait_for_path(path: Path) -> None:
    deadline = time.time() + 2.0
    while time.time() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    raise AssertionError(f"path did not appear: {path}")


def bind_receiver(path: Path) -> socket.socket:
    if path.exists():
        path.unlink()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(str(path))
    sock.settimeout(2.0)
    return sock


def bind_stream_receiver(path: Path) -> socket.socket:
    if path.exists():
        path.unlink()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(path))
    sock.listen(4)
    sock.settimeout(2.0)
    return sock


def recv_all(sock: socket.socket, count: int) -> list[bytes]:
    return [sock.recv(128) for _ in range(count)]


def recv_stream_frame(sock: socket.socket) -> bytes:
    conn, _ = sock.accept()
    try:
        conn.settimeout(2.0)
        data = b""
        while len(data) < 6:
            data += conn.recv(6 - len(data))
        payload_len = data[5]
        while len(data) < 6 + payload_len:
            data += conn.recv(6 + payload_len - len(data))
        return data
    finally:
        conn.close()


def ctrl_request(path: Path, payload: dict) -> dict:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(2.0)
    client.connect(str(path))
    client.sendall((json.dumps(payload) + "\n").encode())
    data = b""
    while not data.endswith(b"\n"):
        chunk = client.recv(4096)
        if not chunk:
            break
        data += chunk
    client.close()
    return json.loads(data.decode())


def run_outputd(tmp: Path, *, target: str = "usb", frames: int = 1) -> tuple[subprocess.Popen, dict[str, Path]]:
    paths = {
        "report": tmp / "hidloom_output_reports.sock",
        "ctrl": tmp / "hidloom_output_ctrl.sock",
        "usb": tmp / "usbd_hid_reports.sock",
        "uidd": tmp / "uidd_reports.sock",
        "bt": tmp / "btd_events.sock",
        "status": tmp / "outputd-status.json",
    }
    env = os.environ.copy()
    env.update(
        {
            "OUTPUTD_REPORT_SOCKET": str(paths["report"]),
            "OUTPUTD_CTRL_SOCKET": str(paths["ctrl"]),
            "OUTPUTD_USB_SOCKET": str(paths["usb"]),
            "OUTPUTD_UIDD_SOCKET": str(paths["uidd"]),
            "OUTPUTD_BT_SOCKET": str(paths["bt"]),
            "OUTPUTD_STATUS_PATH": str(paths["status"]),
            "OUTPUTD_TARGET": target,
        }
    )
    proc = subprocess.Popen([str(BIN), "--frames", str(frames)], env=env)
    wait_for_path(paths["report"])
    wait_for_path(paths["ctrl"])
    return proc, paths


def send_frame(path: Path, frame: bytes) -> None:
    sender = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        sender.sendto(frame, str(path))
    finally:
        sender.close()


def wait_proc(proc: subprocess.Popen) -> None:
    try:
        proc.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise
    assert proc.returncode == 0


def test_usb_target_forwards_to_hidd_socket() -> None:
    frame = encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000040000000000"))
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        usb = bind_receiver(tmp / "usbd_hid_reports.sock")
        uidd = bind_receiver(tmp / "uidd_reports.sock")
        proc, paths = run_outputd(tmp, target="usb")
        send_frame(paths["report"], frame)
        assert recv_all(usb, 1) == [frame]
        uidd.settimeout(0.05)
        try:
            uidd.recv(128)
            raise AssertionError("uinput receiver should not get usb target frame")
        except TimeoutError:
            pass
        wait_proc(proc)
        status = json.loads(paths["status"].read_text(encoding="utf-8"))
    assert status["target"] == "usb"
    assert status["counters"]["frames_to_usb"] == 1
    assert status["counters"]["frames_to_uinput"] == 0


def test_uinput_target_forwards_to_uidd_socket() -> None:
    frame = encode_hid_report_request(KIND_US_SUB_KEYBOARD, bytes.fromhex("0000040000000000"))
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        usb = bind_receiver(tmp / "usbd_hid_reports.sock")
        uidd = bind_receiver(tmp / "uidd_reports.sock")
        proc, paths = run_outputd(tmp, target="uinput")
        send_frame(paths["report"], frame)
        assert recv_all(uidd, 1) == [frame]
        usb.settimeout(0.05)
        try:
            usb.recv(128)
            raise AssertionError("usb receiver should not get uinput target frame")
        except TimeoutError:
            pass
        wait_proc(proc)
        status = json.loads(paths["status"].read_text(encoding="utf-8"))
    assert status["target"] == "uinput"
    assert status["counters"]["frames_to_usb"] == 0
    assert status["counters"]["frames_to_uinput"] == 1


def test_bt_target_forwards_to_btd_socket() -> None:
    keyboard = encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000040000000000"))
    us_sub = encode_hid_report_request(KIND_US_SUB_KEYBOARD, bytes.fromhex("0000050000000000"))
    mouse = encode_hid_report_request(KIND_MOUSE, bytes.fromhex("0102ff00"))
    consumer = encode_hid_report_request(KIND_CONSUMER, bytes.fromhex("e900"))
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        bind_receiver(tmp / "usbd_hid_reports.sock")
        bind_receiver(tmp / "uidd_reports.sock")
        bt = bind_stream_receiver(tmp / "btd_events.sock")
        proc, paths = run_outputd(tmp, target="bt", frames=4)
        send_frame(paths["report"], keyboard)
        assert recv_stream_frame(bt) == b"btd1" + bytes([1, 8]) + bytes.fromhex("0000040000000000")
        send_frame(paths["report"], us_sub)
        assert recv_stream_frame(bt) == b"btd1" + bytes([1, 8]) + bytes.fromhex("0000050000000000")
        send_frame(paths["report"], mouse)
        assert recv_stream_frame(bt) == b"btd1" + bytes([2, 4]) + bytes.fromhex("0102ff00")
        send_frame(paths["report"], consumer)
        assert recv_stream_frame(bt) == b"btd1" + bytes([4, 2]) + bytes.fromhex("e900")
        wait_proc(proc)
        status = json.loads(paths["status"].read_text(encoding="utf-8"))
    assert status["target"] == "bt"
    assert status["counters"]["frames_to_bt"] == 4
    assert status["counters"]["frames_to_usb"] == 0
    assert status["counters"]["frames_to_uinput"] == 0


def test_ctrl_switch_sends_release_to_old_and_new_targets() -> None:
    frame = encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000050000000000"))
    null_keyboard = encode_hid_report_request(KIND_KEYBOARD, bytes(8))
    null_us_sub = encode_hid_report_request(KIND_US_SUB_KEYBOARD, bytes(8))
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        usb = bind_receiver(tmp / "usbd_hid_reports.sock")
        uidd = bind_receiver(tmp / "uidd_reports.sock")
        proc, paths = run_outputd(tmp, target="usb")
        response = ctrl_request(paths["ctrl"], {"t": "set_output_target", "target": "uinput"})
        assert response == {"result": "ok", "target": "uinput"}
        assert recv_all(usb, 2) == [null_keyboard, null_us_sub]
        assert recv_all(uidd, 2) == [null_keyboard, null_us_sub]
        send_frame(paths["report"], frame)
        assert recv_all(uidd, 1) == [frame]
        wait_proc(proc)
        status = json.loads(paths["status"].read_text(encoding="utf-8"))
    assert status["target"] == "uinput"
    assert status["counters"]["release_frames"] == 4
    assert status["counters"]["frames_to_uinput"] == 1


def test_ctrl_status_reports_schema_and_socket_paths() -> None:
    frame = encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000040000000000"))
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        usb = bind_receiver(tmp / "usbd_hid_reports.sock")
        bind_receiver(tmp / "uidd_reports.sock")
        proc, paths = run_outputd(tmp, target="usb")
        status = ctrl_request(paths["ctrl"], {"t": "status"})
        send_frame(paths["report"], frame)
        assert recv_all(usb, 1) == [frame]
        wait_proc(proc)
    assert status["schema"] == "hidloom.outputd.status.v1"
    assert status["process"] is True
    assert status["target"] == "usb"
    assert status["sockets"] == {
        "report": str(paths["report"]),
        "ctrl": str(paths["ctrl"]),
        "usb": str(paths["usb"]),
        "uidd": str(paths["uidd"]),
        "bt": str(paths["bt"]),
    }
    assert status["last_error"] == ""
    assert status["counters"]["frames_received"] == 0
    assert status["counters"]["ctrl_requests"] == 1


def test_ctrl_release_all_sends_null_reports_to_current_target() -> None:
    frame = encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000040000000000"))
    null_keyboard = encode_hid_report_request(KIND_KEYBOARD, bytes(8))
    null_us_sub = encode_hid_report_request(KIND_US_SUB_KEYBOARD, bytes(8))
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        usb = bind_receiver(tmp / "usbd_hid_reports.sock")
        uidd = bind_receiver(tmp / "uidd_reports.sock")
        proc, paths = run_outputd(tmp, target="uinput")
        response = ctrl_request(paths["ctrl"], {"t": "release_all"})
        assert response == {"result": "ok"}
        assert recv_all(uidd, 2) == [null_keyboard, null_us_sub]
        usb.settimeout(0.05)
        try:
            usb.recv(128)
            raise AssertionError("usb receiver should not get uinput release_all frames")
        except TimeoutError:
            pass
        send_frame(paths["report"], frame)
        assert recv_all(uidd, 1) == [frame]
        wait_proc(proc)
        status = json.loads(paths["status"].read_text(encoding="utf-8"))
    assert status["target"] == "uinput"
    assert status["counters"]["release_frames"] == 2
    assert status["counters"]["frames_to_uinput"] == 1


def main() -> None:
    build_tool()
    test_usb_target_forwards_to_hidd_socket()
    test_uinput_target_forwards_to_uidd_socket()
    test_bt_target_forwards_to_btd_socket()
    test_ctrl_switch_sends_release_to_old_and_new_targets()
    test_ctrl_status_reports_schema_and_socket_paths()
    test_ctrl_release_all_sends_null_reports_to_current_target()
    print("ok: hidloom-outputd native report router")


if __name__ == "__main__":
    main()
