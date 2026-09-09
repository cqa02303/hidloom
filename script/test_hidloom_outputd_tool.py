#!/usr/bin/env python3
"""Regression tests for the native hidloom-outputd report router."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
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
UIDD_TOOL_DIR = ROOT / "tools" / "hidloom_uidd"
UIDD_BIN = UIDD_TOOL_DIR / "target" / "release" / "hidloom-uidd"


def build_tool() -> None:
    subprocess.run(["make", "-C", str(TOOL_DIR)], check=True)
    subprocess.run(["make", "-C", str(UIDD_TOOL_DIR)], check=True)


def wait_for_path(path: Path) -> None:
    deadline = time.time() + 2.0
    while time.time() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    raise AssertionError(f"path did not appear: {path}")


def wait_for_json(path: Path, predicate) -> dict:
    deadline = time.time() + 2.0
    while time.time() < deadline:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(0.01)
            continue
        if predicate(payload):
            return payload
        time.sleep(0.01)
    raise AssertionError(f"JSON state did not converge: {path}")


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


def usb_neutrals() -> list[bytes]:
    return [encode_hid_report_request(kind, bytes(size)) for kind, size in
            ((KIND_KEYBOARD, 8), (KIND_US_SUB_KEYBOARD, 8), (KIND_MOUSE, 4), (KIND_CONSUMER, 2))]


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


def run_outputd(tmp: Path, *, target: str = "usb", frames: int = 1, extra_env: dict | None = None) -> tuple[subprocess.Popen, dict[str, Path]]:
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
    env.update(extra_env or {})
    proc = subprocess.Popen([str(BIN), "--frames", str(frames)], env=env)
    wait_for_path(paths["report"])
    wait_for_path(paths["ctrl"])
    return proc, paths


def run_uidd(tmp: Path, *, frames: int) -> tuple[subprocess.Popen, dict[str, Path]]:
    paths = {
        "socket": tmp / "uidd_reports.sock",
        "status": tmp / "uidd-status.json",
        "events": tmp / "uidd-events.ndjson",
    }
    env = os.environ.copy()
    env.update(
        {
            "UIDD_REPORT_SOCKET": str(paths["socket"]),
            "UIDD_STATUS_PATH": str(paths["status"]),
            "UIDD_EVENT_LOG_PATH": str(paths["events"]),
            "UIDD_DRY_RUN": "1",
        }
    )
    proc = subprocess.Popen([str(UIDD_BIN), "--frames", str(frames)], env=env)
    wait_for_path(paths["socket"])
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


def test_idle_and_partial_control_clients_do_not_stall_reports() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        usb = bind_receiver(tmp / "usbd_hid_reports.sock")
        proc, paths = run_outputd(tmp, frames=2)
        clients = []
        try:
            for prefix in (b'{"t":"status"}\n', b'{"t":'):
                client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                client.settimeout(2)
                client.connect(str(paths["ctrl"]))
                client.sendall(prefix)
                clients.append(client)
                if prefix.endswith(b"\n"):
                    assert json.loads(client.recv(4096))["target"] == "usb"
            assert ctrl_request(paths["ctrl"], {"t": "status"})["target"] == "usb"
            for payload in (bytes.fromhex("0200040000000000"), bytes(8)):
                frame = encode_hid_report_request(KIND_KEYBOARD, payload)
                send_frame(paths["report"], frame)
                assert usb.recv(128) == frame
            wait_proc(proc)
        finally:
            for client in clients:
                client.close()
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            usb.close()


def test_bt_endpoint_union_preserves_key_edges() -> None:
    sequence = [
        (KIND_US_SUB_KEYBOARD, "0200040000000000"),
        (KIND_KEYBOARD, "0200050000000000"),
        (KIND_KEYBOARD, "0000000000000000"),
        (KIND_US_SUB_KEYBOARD, "0000000000000000"),
    ]
    expected = ["0200040000000000", "0200050400000000", "0200040000000000", "0000000000000000"]
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        bt = bind_stream_receiver(tmp / "btd_events.sock")
        proc, paths = run_outputd(tmp, target="bt", frames=len(sequence))
        try:
            for (kind, payload), merged in zip(sequence, expected):
                send_frame(paths["report"], encode_hid_report_request(kind, bytes.fromhex(payload)))
                assert recv_stream_frame(bt) == b"btd1" + bytes([1, 8]) + bytes.fromhex(merged)
            wait_proc(proc)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            bt.close()


def test_control_slow_reader_and_half_close_preserve_fairness() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        usb = bind_receiver(tmp / "usbd_hid_reports.sock")
        proc, paths = run_outputd(tmp, frames=2)
        slow = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        slow.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
        slow.settimeout(2)
        slow.connect(str(paths["ctrl"]))
        try:
            # Remain connected without draining responses; keep input within its bound.
            slow.sendall(b'{"t":"status"}\n' * 200)
            time.sleep(0.05)
            normal = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            normal.settimeout(2)
            normal.connect(str(paths["ctrl"]))
            normal.sendall(b'{"t":"sta')
            normal.sendall(b'tus"}\n{"t":"status"}\n')
            normal.shutdown(socket.SHUT_WR)
            with normal.makefile("rb") as reader:
                assert json.loads(reader.readline())["target"] == "usb"
                assert json.loads(reader.readline())["target"] == "usb"
                assert reader.readline() == b""
            normal.close()
            for payload in (bytes.fromhex("0000040000000000"), bytes(8)):
                frame = encode_hid_report_request(KIND_KEYBOARD, payload)
                send_frame(paths["report"], frame)
                assert usb.recv(128) == frame
            wait_proc(proc)
        finally:
            slow.close()
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            usb.close()


def test_bt_failed_release_does_not_resurrect_old_endpoint_state() -> None:
    for explicit_release in (False, True):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            bt_path = tmp / "btd_events.sock"
            bt = bind_stream_receiver(bt_path)
            proc, paths = run_outputd(tmp, target="bt", frames=2 if explicit_release else 3)
            try:
                send_frame(paths["report"], encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000040000000000")))
                assert recv_stream_frame(bt)[6:] == bytes.fromhex("0000040000000000")
                bt.close()
                bt_path.unlink()
                if explicit_release:
                    response = ctrl_request(paths["ctrl"], {"t": "release_all"})
                    assert response["result"] == "error"
                    assert response["release"]["errors"] == 3
                else:
                    send_frame(paths["report"], encode_hid_report_request(KIND_KEYBOARD, bytes(8)))
                failed = wait_for_json(paths["status"], lambda s: s["counters"]["forward_errors"] > 0)
                assert failed["counters"]["frames_to_bt"] == 1
                bt = bind_stream_receiver(bt_path)
                send_frame(paths["report"], encode_hid_report_request(KIND_US_SUB_KEYBOARD, bytes.fromhex("0000050000000000")))
                recovered = recv_stream_frame(bt)[6:]
                assert recovered == bytes.fromhex("0000050000000000"), (explicit_release, recovered.hex())
                wait_proc(proc)
            finally:
                bt.close()
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()


def test_switch_releases_mouse_consumer_and_clears_bt_snapshot() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        usb = bind_receiver(tmp / "usbd_hid_reports.sock")
        bt = bind_stream_receiver(tmp / "btd_events.sock")
        bt_frames = []
        done = threading.Event()

        def capture() -> None:
            while not done.is_set():
                try:
                    bt_frames.append(recv_stream_frame(bt))
                except TimeoutError:
                    continue

        thread = threading.Thread(target=capture, daemon=True)
        thread.start()
        proc, paths = run_outputd(tmp, target="bt", frames=5)
        try:
            for kind, payload in [(1, bytes.fromhex("0000040000000000")), (2, bytes([1, 0, 0, 0])), (3, bytes([0xe9, 0]))]:
                send_frame(paths["report"], encode_hid_report_request(kind, payload))
            wait_for_json(paths["status"], lambda s: s["counters"]["frames_received"] == 3)
            assert ctrl_request(paths["ctrl"], {"t": "set_output_target", "target": "usb"})["release"] == {"attempted": 7, "delivered": 7, "errors": 0}
            assert recv_all(usb, 4) == usb_neutrals()
            assert ctrl_request(paths["ctrl"], {"t": "set_output_target", "target": "bt"})["result"] == "ok"
            assert recv_all(usb, 4) == usb_neutrals()
            send_frame(paths["report"], encode_hid_report_request(4, bytes.fromhex("0000050000000000")))
            send_frame(paths["report"], encode_hid_report_request(4, bytes(8)))
            wait_proc(proc)
            deadline = time.monotonic() + 2
            while len(bt_frames) < 11 and time.monotonic() < deadline:
                time.sleep(0.01)
            neutral = [b"btd1" + bytes([kind, size]) + bytes(size) for kind, size in ((1, 8), (2, 4), (4, 2))]
            assert bt_frames[3:6] == neutral
            assert bt_frames[6:9] == neutral
            assert bt_frames[9:] == [b"btd1" + bytes([1, 8]) + bytes.fromhex("0000050000000000"), b"btd1" + bytes([1, 8]) + bytes(8)]
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            done.set()
            thread.join(timeout=3)
            bt.close()
            usb.close()


def test_auto_uses_bound_udc_and_recovers_with_neutral_before_new_input() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        usb = bind_receiver(tmp / "usbd_hid_reports.sock")
        uidd = bind_receiver(tmp / "uidd_reports.sock")
        gadget_udc = tmp / "UDC"
        gadget_udc.write_text("hidloom-controller")
        udc = tmp / "udc" / "hidloom-controller"
        udc.mkdir(parents=True)
        (udc / "state").write_text("configured")
        hs, us = tmp / "hidd.json", tmp / "uidd.json"
        hs.write_text(json.dumps({"schema": "hidd.status.v1", "process": True,
            "socket": {"listening": True, "path": str(tmp / "usbd_hid_reports.sock")},
            "endpoints": {"hidg0": {"open": True}, "hidg2": {"open": True}}}))
        us.write_text(json.dumps({"schema": "hidloom.uidd.status.v1", "process": True,
            "socket": {"listening": True, "path": str(tmp / "uidd_reports.sock")},
            "dry_run": False, "uinput": {"open": True}}))
        done = threading.Event()

        def heartbeat() -> None:
            while not done.wait(0.2):
                hs.touch()
                us.touch()

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        proc, paths = run_outputd(tmp, target="auto", frames=4, extra_env={
            "OUTPUTD_GADGET_UDC_PATH": str(gadget_udc), "OUTPUTD_UDC_ROOT": str(tmp / "udc"),
            "OUTPUTD_HIDD_STATUS_PATH": str(hs), "OUTPUTD_UIDD_STATUS_PATH": str(us),
        })
        try:
            wait_for_json(paths["status"], lambda s: s["effective_target"] == "usb")
            assert recv_all(usb, 4) == usb_neutrals()
            frame = encode_hid_report_request(1, bytes.fromhex("0200040000000000"))
            send_frame(paths["report"], frame)
            assert usb.recv(128) == frame
            (udc / "state").write_text("suspended")
            state = wait_for_json(paths["status"], lambda s: s["readiness"]["usb"] == "unknown")
            assert state["effective_target"] == "usb"
            (udc / "state").write_text("not attached")
            state = wait_for_json(paths["status"], lambda s: s["effective_target"] == "uinput")
            assert state["target"] == "auto" and state["readiness"]["pending_usb_neutral"]
            assert recv_all(uidd, 2) == usb_neutrals()[:2]
            # No old held report is replayed into the new sink.
            uidd.settimeout(0.05)
            try:
                uidd.recv(128)
                raise AssertionError("held snapshot replayed")
            except TimeoutError:
                pass
            uidd.settimeout(2)
            null = encode_hid_report_request(1, bytes(8))
            send_frame(paths["report"], null)
            assert uidd.recv(128) == null
            (udc / "state").write_text("configured")
            state = wait_for_json(paths["status"], lambda s: s["effective_target"] == "usb")
            assert not state["readiness"]["pending_usb_neutral"]
            assert recv_all(uidd, 2) == usb_neutrals()[:2]
            assert recv_all(usb, 4) == usb_neutrals()
            assert ctrl_request(paths["ctrl"], {"t": "set_output_target", "target": "uinput"})["result"] == "ok"
            assert recv_all(usb, 4) == usb_neutrals()
            assert recv_all(uidd, 2) == usb_neutrals()[:2]
            # Explicit target is unaffected by configured USB samples.
            time.sleep(0.6)
            assert ctrl_request(paths["ctrl"], {"t": "status"})["effective_target"] == "uinput"
            for payload in (bytes.fromhex("0000050000000000"), bytes(8)):
                frame = encode_hid_report_request(4, payload)
                send_frame(paths["report"], frame)
                assert uidd.recv(128) == frame
            wait_proc(proc)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            done.set()
            thread.join(timeout=1)
            usb.close()
            uidd.close()


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
        assert recv_stream_frame(bt) == b"btd1" + bytes([1, 8]) + bytes.fromhex("0000040500000000")
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
        assert response == {
            "result": "ok",
            "target": "uinput",
            "release": {"attempted": 6, "delivered": 6, "errors": 0},
        }
        assert recv_all(usb, 4) == usb_neutrals()
        assert recv_all(uidd, 2) == [null_keyboard, null_us_sub]
        send_frame(paths["report"], frame)
        assert recv_all(uidd, 1) == [frame]
        wait_proc(proc)
        status = json.loads(paths["status"].read_text(encoding="utf-8"))
    assert status["target"] == "uinput"
    assert status["counters"]["release_frames"] == 6
    assert status["counters"]["frames_to_uinput"] == 1


def test_ctrl_switch_keeps_old_target_when_release_delivery_fails() -> None:
    frame = encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000050000000000"))
    null_keyboard = encode_hid_report_request(KIND_KEYBOARD, bytes(8))
    null_us_sub = encode_hid_report_request(KIND_US_SUB_KEYBOARD, bytes(8))
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        usb = bind_receiver(tmp / "usbd_hid_reports.sock")
        proc, paths = run_outputd(tmp, target="usb")
        response = ctrl_request(paths["ctrl"], {"t": "set_output_target", "target": "uinput"})
        assert response == {
            "result": "error",
            "error": "release_delivery_failed",
            "target": "usb",
            "release": {"attempted": 6, "delivered": 4, "errors": 2,
                        "failed": [{"target": "uinput", "kind": 1}, {"target": "uinput", "kind": 4}]},
        }
        assert recv_all(usb, 4) == usb_neutrals()
        live_status = ctrl_request(paths["ctrl"], {"t": "status"})
        assert live_status["target"] == "usb"
        assert live_status["counters"]["release_errors"] == 2
        send_frame(paths["report"], frame)
        assert recv_all(usb, 1) == [frame]
        wait_proc(proc)
        status = json.loads(paths["status"].read_text(encoding="utf-8"))
    assert status["target"] == "usb"
    assert status["counters"]["frames_to_usb"] == 1
    assert status["counters"]["frames_to_uinput"] == 0


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
        assert response == {
            "result": "ok",
            "release": {"attempted": 2, "delivered": 2, "errors": 0},
        }
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
    assert status["counters"]["release_errors"] == 0
    assert status["counters"]["frames_to_uinput"] == 1


def test_ctrl_release_all_reports_delivery_failures() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        proc, paths = run_outputd(tmp, target="usb")
        response = ctrl_request(paths["ctrl"], {"t": "release_all"})
        assert response == {
            "result": "error",
            "error": "release_delivery_failed",
            "release": {"attempted": 4, "delivered": 0, "errors": 4,
                        "failed": [{"target": "usb", "kind": kind} for kind in (1, 4, 2, 3)]},
        }
        live_status = ctrl_request(paths["ctrl"], {"t": "status"})
        assert live_status["last_error"].startswith("failed to forward to ")
        assert live_status["counters"]["release_frames"] == 0
        assert live_status["counters"]["release_errors"] == 4
        assert live_status["counters"]["forward_errors"] == 4
        send_frame(paths["report"], b"invalid")
        wait_proc(proc)


def test_console_switch_login_sequence_round_trip() -> None:
    null_keyboard = encode_hid_report_request(KIND_KEYBOARD, bytes(8))
    null_us_sub = encode_hid_report_request(KIND_US_SUB_KEYBOARD, bytes(8))
    login_frames = [
        encode_hid_report_request(KIND_US_SUB_KEYBOARD, bytes.fromhex(payload))
        for payload in (
            "0000130000000000",
            "0000000000000000",
            "00000c0000000000",
            "0000000000000000",
            "0000280000000000",
            "0000000000000000",
        )
    ]
    final_usb = encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000040000000000"))
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        usb = bind_receiver(tmp / "usbd_hid_reports.sock")
        uidd_proc, uidd_paths = run_uidd(tmp, frames=10)
        outputd_proc, outputd_paths = run_outputd(tmp, target="usb", frames=7)

        assert ctrl_request(
            outputd_paths["ctrl"], {"t": "set_output_target", "target": "uinput"}
        ) == {
            "result": "ok",
            "target": "uinput",
            "release": {"attempted": 6, "delivered": 6, "errors": 0},
        }
        assert recv_all(usb, 4) == usb_neutrals()
        for frame in login_frames:
            send_frame(outputd_paths["report"], frame)
        wait_for_json(
            uidd_paths["status"],
            lambda status: status["counters"]["frames_received"] >= 8,
        )

        assert ctrl_request(
            outputd_paths["ctrl"], {"t": "set_output_target", "target": "usb"}
        ) == {
            "result": "ok",
            "target": "usb",
            "release": {"attempted": 6, "delivered": 6, "errors": 0},
        }
        assert recv_all(usb, 4) == usb_neutrals()
        send_frame(outputd_paths["report"], final_usb)
        assert recv_all(usb, 1) == [final_usb]

        wait_proc(outputd_proc)
        wait_proc(uidd_proc)
        outputd_status = json.loads(outputd_paths["status"].read_text(encoding="utf-8"))
        uidd_status = json.loads(uidd_paths["status"].read_text(encoding="utf-8"))
        events = [
            json.loads(line)
            for line in uidd_paths["events"].read_text(encoding="utf-8").splitlines()
        ]

    assert outputd_status["target"] == "usb"
    assert outputd_status["counters"]["frames_to_uinput"] == 6
    assert outputd_status["counters"]["frames_to_usb"] == 1
    assert outputd_status["counters"]["release_frames"] == 12
    assert uidd_status["counters"]["frames_received"] == 10
    assert uidd_status["counters"]["key_events"] == 6
    assert [(event["type"], event["code"], event["value"]) for event in events] == [
        (1, 25, 1),
        (0, 0, 0),
        (1, 25, 0),
        (0, 0, 0),
        (1, 23, 1),
        (0, 0, 0),
        (1, 23, 0),
        (0, 0, 0),
        (1, 28, 1),
        (0, 0, 0),
        (1, 28, 0),
        (0, 0, 0),
    ]


def main() -> None:
    build_tool()
    test_idle_and_partial_control_clients_do_not_stall_reports()
    test_bt_endpoint_union_preserves_key_edges()
    test_bt_failed_release_does_not_resurrect_old_endpoint_state()
    test_control_slow_reader_and_half_close_preserve_fairness()
    test_switch_releases_mouse_consumer_and_clears_bt_snapshot()
    test_auto_uses_bound_udc_and_recovers_with_neutral_before_new_input()
    test_usb_target_forwards_to_hidd_socket()
    test_uinput_target_forwards_to_uidd_socket()
    test_bt_target_forwards_to_btd_socket()
    test_ctrl_switch_sends_release_to_old_and_new_targets()
    test_ctrl_switch_keeps_old_target_when_release_delivery_fails()
    test_ctrl_status_reports_schema_and_socket_paths()
    test_ctrl_release_all_sends_null_reports_to_current_target()
    test_ctrl_release_all_reports_delivery_failures()
    test_console_switch_login_sequence_round_trip()
    print("ok: hidloom-outputd native report router")


if __name__ == "__main__":
    main()
