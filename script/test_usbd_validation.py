#!/usr/bin/env python3
"""Local smoke test for usbd validation helpers and one report bridge."""
from __future__ import annotations

import sys
import socket
import tempfile
import threading
import time
import errno
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from usbd import usbd  # noqa: E402
from usbd.hid_report_broker import KIND_KEYBOARD, KIND_MOUSE, KIND_US_SUB_KEYBOARD, UsbReport, encode_hid_report_request  # noqa: E402


class FakeSocket:
    def __init__(self, response_chunks: list[bytes]) -> None:
        self.response_chunks = list(response_chunks)
        self.sent = bytearray()

    def sendall(self, data: bytes) -> None:
        self.sent.extend(data)

    def recv(self, size: int) -> bytes:
        if not self.response_chunks:
            return b""
        chunk = self.response_chunks.pop(0)
        if len(chunk) > size:
            self.response_chunks.insert(0, chunk[size:])
            return chunk[:size]
        return chunk


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, sec: float) -> None:
        self.now += sec


def main() -> None:
    old_env = {
        key: usbd.os.environ.get(key)  # type: ignore[attr-defined]
        for key in ("USBD_TEST_BAD_INT", "USBD_TEST_BAD_FLOAT", "USBD_TEST_BOOL")
    }
    old_read = usbd.os.read  # type: ignore[attr-defined]
    old_write = usbd.os.write  # type: ignore[attr-defined]
    old_ime_enabled = usbd.WINDOWS_IME_SOCKET_ENABLED  # type: ignore[attr-defined]
    old_ime_socket = usbd.WINDOWS_IME_SOCKET  # type: ignore[attr-defined]
    old_hid_report_enabled = usbd.HID_REPORT_SOCKET_ENABLED  # type: ignore[attr-defined]
    old_hid_report_socket = usbd.HID_REPORT_SOCKET  # type: ignore[attr-defined]
    old_hid_report_path = usbd.HID_REPORT_PATH  # type: ignore[attr-defined]
    old_us_sub_hid_report_path = usbd.US_SUB_HID_REPORT_PATH  # type: ignore[attr-defined]
    old_raw_hid_bridge_enabled = usbd.RAW_HID_BRIDGE_ENABLED  # type: ignore[attr-defined]
    old_open_hid_report_endpoint = usbd._open_hid_report_endpoint  # type: ignore[attr-defined]
    try:
        usbd.os.environ["USBD_TEST_BAD_INT"] = "bad"  # type: ignore[attr-defined]
        usbd.os.environ["USBD_TEST_BAD_FLOAT"] = "bad"  # type: ignore[attr-defined]
        assert usbd._env_int("USBD_TEST_BAD_INT", 32, min_value=1, max_value=64) == 32  # type: ignore[attr-defined]
        assert usbd._env_float("USBD_TEST_BAD_FLOAT", 1.5, min_value=0.1) == 1.5  # type: ignore[attr-defined]
        usbd.os.environ["USBD_TEST_BOOL"] = "2"  # type: ignore[attr-defined]
        assert usbd._env_int("USBD_TEST_BOOL", 1, min_value=0, max_value=1) == 1  # type: ignore[attr-defined]
        usbd.os.environ["USBD_TEST_BAD_INT"] = "0"  # type: ignore[attr-defined]
        usbd.os.environ["USBD_TEST_BAD_FLOAT"] = "-1"  # type: ignore[attr-defined]
        assert usbd._env_int("USBD_TEST_BAD_INT", 32, min_value=1, max_value=64) == 32  # type: ignore[attr-defined]
        assert usbd._env_float("USBD_TEST_BAD_FLOAT", 1.5, min_value=0.1) == 1.5  # type: ignore[attr-defined]

        reads = [b"ab", b"cd"]
        written: list[bytes] = []
        usbd.os.read = lambda _fd, _size: reads.pop(0)  # type: ignore[assignment]
        usbd.os.write = lambda _fd, data: written.append(bytes(data)) or len(data)  # type: ignore[assignment]
        sock = FakeSocket([b"wx", b"yz"])
        usbd._bridge_once(123, sock, 4)  # type: ignore[attr-defined]
        assert bytes(sock.sent) == b"abcd"
        assert written == [b"wxyz"]

        written.clear()
        usbd._write_exact(123, b"1234")  # type: ignore[attr-defined]
        assert written == [b"1234"]

        written.clear()
        eagain_seen = [False]

        def write_after_eagain(_fd: int, data: bytes) -> int:
            if not eagain_seen[0]:
                eagain_seen[0] = True
                raise BlockingIOError(errno.EAGAIN, "temporarily unavailable")
            written.append(bytes(data))
            return len(data)

        usbd.os.write = write_after_eagain  # type: ignore[assignment]
        usbd._write_exact(123, b"retry")  # type: ignore[attr-defined]
        assert eagain_seen == [True]
        assert written == [b"retry"]

        clock = FakeClock()
        scheduler = usbd.MouseReportScheduler(output_hz=100.0, clock=clock)  # type: ignore[attr-defined]
        first = UsbReport("/tmp/fake-hidg0", bytes.fromhex("0201030000"), KIND_MOUSE)
        assert [report.report for report in scheduler.enqueue(first)] == [bytes.fromhex("0201030000")]
        second = UsbReport("/tmp/fake-hidg0", bytes.fromhex("0201040000"), KIND_MOUSE)
        third = UsbReport("/tmp/fake-hidg0", bytes.fromhex("0201050000"), KIND_MOUSE)
        assert scheduler.enqueue(second) == []
        assert scheduler.enqueue(third) == []
        clock.advance(0.010)
        due = scheduler.flush_due()
        assert due is not None
        assert due.report == bytes.fromhex("0201090000")

        large = UsbReport("/tmp/fake-hidg0", bytes([0x02, 0x01, 100, 0, 0]), KIND_MOUSE)
        assert scheduler.enqueue(large) == []
        assert scheduler.enqueue(large) == []
        clock.advance(0.010)
        due = scheduler.flush_due()
        assert due is not None
        assert due.report == bytes([0x02, 0x01, 0x7F, 0x00, 0x00])
        clock.advance(0.010)
        due = scheduler.flush_due()
        assert due is not None
        assert due.report == bytes([0x02, 0x01, 0x49, 0x00, 0x00])

        pending = UsbReport("/tmp/fake-hidg0", bytes.fromhex("02010a0000"), KIND_MOUSE)
        button_change = UsbReport("/tmp/fake-hidg0", bytes.fromhex("0203000000"), KIND_MOUSE)
        assert scheduler.enqueue(pending) == []
        flushed = scheduler.enqueue(button_change)
        assert [report.report for report in flushed] == [
            bytes.fromhex("02010a0000"),
            bytes.fromhex("0203000000"),
        ]

        clock = FakeClock()
        keyboard_coalescer = usbd.KeyboardReleaseCoalescer(merge_window_sec=0.020, clock=clock)  # type: ignore[attr-defined]
        key_a = UsbReport("/tmp/fake-hidg0", bytes.fromhex("010000040000000000"), KIND_KEYBOARD)
        key_b = UsbReport("/tmp/fake-hidg0", bytes.fromhex("010000050000000000"), KIND_KEYBOARD)
        key_release = UsbReport("/tmp/fake-hidg0", bytes.fromhex("010000000000000000"), KIND_KEYBOARD)
        assert keyboard_coalescer.enqueue(key_a) == [key_a]
        assert keyboard_coalescer.enqueue(key_release) == []
        clock.advance(0.010)
        assert keyboard_coalescer.enqueue(key_b) == [key_b]
        assert keyboard_coalescer.coalesced_releases == 1

        assert keyboard_coalescer.enqueue(key_release) == []
        clock.advance(0.010)
        assert keyboard_coalescer.enqueue(key_a) == [key_a]
        assert keyboard_coalescer.coalesced_releases == 2

        assert keyboard_coalescer.enqueue(key_release) == []
        clock.advance(0.020)
        assert keyboard_coalescer.flush_due() == [key_release]

        same_key_coalescer = usbd.KeyboardReleaseCoalescer(merge_window_sec=0.020, clock=FakeClock())  # type: ignore[attr-defined]
        assert same_key_coalescer.enqueue(key_a) == [key_a]
        assert same_key_coalescer.enqueue(key_release) == []
        assert same_key_coalescer.enqueue(key_a) == [key_release, key_a]
        assert same_key_coalescer.coalesced_releases == 0

        modifier_coalescer = usbd.KeyboardReleaseCoalescer(merge_window_sec=0.020, clock=FakeClock())  # type: ignore[attr-defined]
        shift_press = UsbReport("/tmp/fake-hidg0", bytes.fromhex("010200000000000000"), KIND_KEYBOARD)
        shift_release = UsbReport("/tmp/fake-hidg0", bytes.fromhex("010000000000000000"), KIND_KEYBOARD)
        assert modifier_coalescer.enqueue(shift_press) == [shift_press]
        assert modifier_coalescer.enqueue(shift_release) == []
        assert modifier_coalescer.enqueue(shift_press) == [shift_release, shift_press]

        order_coalescer = usbd.KeyboardReleaseCoalescer(merge_window_sec=0.020, clock=FakeClock())  # type: ignore[attr-defined]
        mouse_report = UsbReport("/tmp/fake-hidg0", bytes.fromhex("0201010000"), KIND_MOUSE)
        assert order_coalescer.enqueue(key_a) == [key_a]
        assert order_coalescer.enqueue(key_release) == []
        assert order_coalescer.flush_all() + [mouse_report] == [key_release, mouse_report]

        clock = FakeClock()
        burst_coalescer = usbd.KeyboardReleaseCoalescer(merge_window_sec=0.020, clock=clock)  # type: ignore[attr-defined]
        burst_reports: list[UsbReport] = []
        for keycode in range(0x04, 0x0B):
            press = UsbReport("/tmp/fake-hidg0", bytes([0x01, 0x00, 0x00, keycode, 0, 0, 0, 0, 0]), KIND_KEYBOARD)
            release = UsbReport("/tmp/fake-hidg0", bytes.fromhex("010000000000000000"), KIND_KEYBOARD)
            burst_reports.extend(burst_coalescer.enqueue(press))
            burst_reports.extend(burst_coalescer.enqueue(release))
        burst_reports.extend(burst_coalescer.flush_all())
        assert [report.report for report in burst_reports] == [
            bytes([0x01, 0x00, 0x00, keycode, 0, 0, 0, 0, 0])
            for keycode in range(0x04, 0x0B)
        ] + [bytes.fromhex("010000000000000000")]

        clock = FakeClock()
        sleeps: list[float] = []

        def sleep_and_advance(sec: float) -> None:
            sleeps.append(sec)
            clock.advance(sec)

        pacer = usbd.KeyboardReportPacer(output_hz=1000.0, clock=clock, sleeper=sleep_and_advance)  # type: ignore[attr-defined]
        written.clear()
        usbd.os.write = lambda _fd, data: written.append(bytes(data)) or len(data)  # type: ignore[assignment]
        for report in burst_reports:
            assert pacer.prepare(report) is True
            usbd._write_exact(123, report.report)  # type: ignore[attr-defined]
        assert written == [report.report for report in burst_reports]
        assert len(written) == 8
        assert len(sleeps) == 7

        reads = [b""]
        try:
            usbd._read_exact(123, 1)  # type: ignore[attr-defined]
        except EOFError:
            pass
        else:
            raise AssertionError("_read_exact should raise EOFError on empty read")

        try:
            usbd._recv_exact(FakeSocket([b""]), 1)  # type: ignore[attr-defined]
        except EOFError:
            pass
        else:
            raise AssertionError("_recv_exact should raise EOFError on empty recv")

        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "usbd_windows_ime.sock")
            usbd.WINDOWS_IME_SOCKET_ENABLED = 1  # type: ignore[attr-defined]
            usbd.WINDOWS_IME_SOCKET = path  # type: ignore[attr-defined]
            received: list[bytes] = []
            usbd.os.write = lambda _fd, data: received.append(bytes(data)) or len(data)  # type: ignore[assignment]
            stop_event = threading.Event()
            lock = threading.Lock()
            thread = threading.Thread(
                target=usbd._windows_ime_socket_loop,  # type: ignore[attr-defined]
                args=(456, stop_event, lock),
                daemon=True,
            )
            thread.start()
            deadline = time.time() + 2.0
            while not Path(path).exists() and time.time() < deadline:
                time.sleep(0.01)
            sender = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            try:
                sender.sendto(b"x" * usbd.REPORT_SIZE, path)  # type: ignore[attr-defined]
            finally:
                sender.close()
            deadline = time.time() + 2.0
            while not received and time.time() < deadline:
                time.sleep(0.01)
            stop_event.set()
            thread.join(timeout=1.0)
            assert received == [b"x" * usbd.REPORT_SIZE]  # type: ignore[attr-defined]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "usbd_hid_reports.sock")
            usbd.HID_REPORT_SOCKET_ENABLED = 1  # type: ignore[attr-defined]
            usbd.HID_REPORT_SOCKET = path  # type: ignore[attr-defined]
            usbd.HID_REPORT_PATH = "/tmp/fake-hidg0"  # type: ignore[attr-defined]
            usbd.US_SUB_HID_REPORT_PATH = "/tmp/fake-hidg2"  # type: ignore[attr-defined]
            received = []
            endpoint_fds: dict[str, int] = {}

            def open_endpoint(endpoint: str) -> int:
                fd = len(endpoint_fds) + 789
                endpoint_fds[endpoint] = fd
                return fd

            usbd._open_hid_report_endpoint = open_endpoint  # type: ignore[assignment]
            usbd.os.write = lambda _fd, data: received.append(bytes(data)) or len(data)  # type: ignore[assignment]
            stop_event = threading.Event()
            thread = threading.Thread(
                target=usbd._hid_report_socket_loop,  # type: ignore[attr-defined]
                args=(stop_event,),
                daemon=True,
            )
            thread.start()
            deadline = time.time() + 2.0
            while not Path(path).exists() and time.time() < deadline:
                time.sleep(0.01)
            sender = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            try:
                frame = encode_hid_report_request(KIND_KEYBOARD, bytes.fromhex("0000040000000000"))
                sender.sendto(frame, path)
                us_sub_frame = encode_hid_report_request(KIND_US_SUB_KEYBOARD, bytes.fromhex("0000900000000000"))
                sender.sendto(us_sub_frame, path)
            finally:
                sender.close()
            deadline = time.time() + 2.0
            while len(received) < 2 and time.time() < deadline:
                time.sleep(0.01)
            stop_event.set()
            thread.join(timeout=1.0)
            assert endpoint_fds == {"/tmp/fake-hidg0": 789, "/tmp/fake-hidg2": 790}
            assert received == [
                bytes.fromhex("010000040000000000"),
                bytes.fromhex("0000900000000000"),
            ]
    finally:
        usbd.os.read = old_read  # type: ignore[assignment]
        usbd.os.write = old_write  # type: ignore[assignment]
        usbd.WINDOWS_IME_SOCKET_ENABLED = old_ime_enabled  # type: ignore[attr-defined]
        usbd.WINDOWS_IME_SOCKET = old_ime_socket  # type: ignore[attr-defined]
        usbd.HID_REPORT_SOCKET_ENABLED = old_hid_report_enabled  # type: ignore[attr-defined]
        usbd.HID_REPORT_SOCKET = old_hid_report_socket  # type: ignore[attr-defined]
        usbd.HID_REPORT_PATH = old_hid_report_path  # type: ignore[attr-defined]
        usbd.US_SUB_HID_REPORT_PATH = old_us_sub_hid_report_path  # type: ignore[attr-defined]
        usbd.RAW_HID_BRIDGE_ENABLED = old_raw_hid_bridge_enabled  # type: ignore[attr-defined]
        usbd._open_hid_report_endpoint = old_open_hid_report_endpoint  # type: ignore[attr-defined]
        for key, value in old_env.items():
            if value is None:
                usbd.os.environ.pop(key, None)  # type: ignore[attr-defined]
            else:
                usbd.os.environ[key] = value  # type: ignore[attr-defined]

    print("ok: usbd validation helpers and bridge framing are coherent")


if __name__ == "__main__":
    main()
