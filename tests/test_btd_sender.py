from __future__ import annotations

import os
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import logicd.btd_sender as btd_sender
from logicd.btd_sender import BtdReportSender


class BtdReportSenderTest(unittest.TestCase):
    def test_send_report_to_unix_socket(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "btd.sock")
            received: list[bytes] = []
            ready = threading.Event()

            def server() -> None:
                srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    srv.bind(socket_path)
                    srv.listen(1)
                    ready.set()
                    conn, _ = srv.accept()
                    with conn:
                        received.append(conn.recv(14))
                finally:
                    srv.close()

            thread = threading.Thread(target=server, daemon=True)
            thread.start()
            self.assertTrue(ready.wait(timeout=1.0))

            sender = BtdReportSender(socket_path=socket_path, reconnect_interval_sec=0.0)
            report = bytes([0x00, 0x00, 0x04, 0, 0, 0, 0, 0])
            sender.send(report)
            sender.close()
            thread.join(timeout=1.0)

            self.assertEqual(received, [b"btd1" + bytes([1, 8]) + report])

    def test_unavailable_socket_does_not_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "missing.sock")
            sender = BtdReportSender(socket_path=socket_path, reconnect_interval_sec=0.0)
            sender.send(bytes(8))
            sender.close()

    def test_invalid_report_length_is_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "missing.sock")
            sender = BtdReportSender(socket_path=socket_path, reconnect_interval_sec=0.0)
            sender.send(b"short")
            sender.close()

    def test_check_closes_stale_connection_when_socket_path_disappears(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "btd.sock")
            sender = BtdReportSender(socket_path=socket_path, reconnect_interval_sec=0.0)
            sender.check()
            self.assertIsNone(sender._sock)

    def test_retries_current_report_once_after_broken_pipe(self) -> None:
        class BrokenSocket:
            def __init__(self) -> None:
                self.closed = False

            def sendall(self, _payload: bytes) -> None:
                raise BrokenPipeError("stale connection")

            def close(self) -> None:
                self.closed = True

        class ReconnectSocket:
            def __init__(self) -> None:
                self.sent: list[bytes] = []
                self.connected_path = ""
                self.closed = False

            def settimeout(self, _timeout: float) -> None:
                return None

            def connect(self, path: str) -> None:
                self.connected_path = path

            def sendall(self, payload: bytes) -> None:
                self.sent.append(payload)

            def close(self) -> None:
                self.closed = True

        created: list[ReconnectSocket] = []
        original_socket = btd_sender.socket.socket

        def fake_socket(_family: int, _kind: int) -> ReconnectSocket:
            sock = ReconnectSocket()
            created.append(sock)
            return sock

        sender = BtdReportSender(socket_path="/tmp/test-btd.sock", reconnect_interval_sec=60.0)
        stale = BrokenSocket()
        sender._sock = stale  # type: ignore[assignment]
        report = bytes([0x00, 0x00, 0x04, 0, 0, 0, 0, 0])
        try:
            btd_sender.socket.socket = fake_socket  # type: ignore[assignment]
            sender.send(report)
        finally:
            btd_sender.socket.socket = original_socket  # type: ignore[assignment]
            sender.close()

        self.assertTrue(stale.closed)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].connected_path, "/tmp/test-btd.sock")
        self.assertEqual(created[0].sent, [b"btd1" + bytes([1, 8]) + report])

    def test_send_consumer_usage_frames_usage_and_release(self) -> None:
        class CaptureSocket:
            def __init__(self) -> None:
                self.sent: list[bytes] = []

            def sendall(self, payload: bytes) -> None:
                self.sent.append(payload)

            def close(self) -> None:
                return None

        sender = BtdReportSender(socket_path="/tmp/test-btd.sock", reconnect_interval_sec=60.0)
        sock = CaptureSocket()
        sender._sock = sock  # type: ignore[assignment]
        sender.send_consumer_usage(0x00E9, True)
        sender.send_consumer_usage(0x00E9, False)
        sender.close()

        self.assertEqual(
            sock.sent,
            [
                b"btd1" + bytes([4, 2]) + bytes.fromhex("e900"),
                b"btd1" + bytes([4, 2]) + bytes.fromhex("0000"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
