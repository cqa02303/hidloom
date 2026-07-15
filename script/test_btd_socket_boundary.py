#!/usr/bin/env python3
"""Smoke test for the btd daemon Unix socket boundary."""
from __future__ import annotations

import asyncio
import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from btd.btd import BtdServer, _backend_status_fields  # noqa: E402
from btd.protocol import FRAME_MAGIC, ConsumerReport, KeyboardReport, MouseReport, encode_hid_frame, parse_raw_consumer_report, parse_raw_mouse_report  # noqa: E402
from socket_test_helpers import assert_socket_mode  # noqa: E402


class CaptureBackend:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.reports: list[KeyboardReport] = []
        self.mouse_reports: list[MouseReport] = []
        self.consumer_reports: list[ConsumerReport] = []
        self.reconnect_advertising: list[bool] = []

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send_keyboard_report(self, report: KeyboardReport) -> None:
        self.reports.append(report)

    async def send_mouse_report(self, report: MouseReport) -> None:
        self.mouse_reports.append(report)

    async def send_consumer_report(self, report: ConsumerReport) -> None:
        self.consumer_reports.append(report)

    async def set_reconnect_advertising(self, enabled: bool) -> None:
        self.reconnect_advertising.append(enabled)

    def status(self) -> dict[str, object]:
        return {"started": self.started, "reports": len(self.reports), "note": ""}


async def _send(socket_path: str, payload: bytes) -> None:
    def _blocking_send() -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(2.0)
            sock.connect(socket_path)
            sock.sendall(payload)

    await asyncio.to_thread(_blocking_send)


async def _request_status(socket_path: str) -> dict:
    def _blocking_request() -> dict:
        import json

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(2.0)
            sock.connect(socket_path)
            payload = b'{"command":"status"}'
            sock.sendall(FRAME_MAGIC + bytes([3, len(payload)]) + payload)
            line = bytearray()
            while not line.endswith(b"\n"):
                chunk = sock.recv(1)
                if not chunk:
                    break
                line.extend(chunk)
            return json.loads(line.decode("utf-8"))

    return await asyncio.to_thread(_blocking_request)


async def main_async() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        socket_path = str(Path(tmp) / "btd_events.sock")
        backend = CaptureBackend()
        server = BtdServer(socket_path=socket_path, report_size=8, socket_mode=0o666, backend=backend)
        await server.start()
        serve_task = asyncio.create_task(server.serve_forever())
        try:
            await _send(socket_path, bytes.fromhex("0000000000000000"))
            await _send(socket_path, bytes.fromhex("0000040000000000"))
            await _send(socket_path, encode_hid_frame(parse_raw_mouse_report(bytes.fromhex("0001ff00"))))
            await _send(socket_path, encode_hid_frame(parse_raw_consumer_report(bytes.fromhex("e900"))))
            await _send(socket_path, FRAME_MAGIC + bytes([3, 50]) + b'{"command":"reconnect_advertising","enabled":true}')
            await asyncio.sleep(0.05)
            status = await _request_status(socket_path)
            assert Path(socket_path).exists()
            assert_socket_mode(Path(socket_path), 0o666)
            assert backend.started
            assert len(backend.reports) == 2
            assert len(backend.mouse_reports) == 1
            assert len(backend.consumer_reports) == 1
            assert backend.reconnect_advertising == [True]
            assert status == {"result": "ok", "status": {"started": True, "reports": 2, "note": ""}}
            assert backend.reports[0].is_null
            assert backend.reports[1].hex == "0000040000000000"
            assert backend.mouse_reports[0].hex == "0001ff00"
            assert backend.consumer_reports[0].hex == "e900"
            fields = _backend_status_fields(backend)
            assert "note=\"\"" in fields
            assert "reports=2" in fields
            assert "started=true" in fields
        finally:
            serve_task.cancel()
            try:
                await serve_task
            except asyncio.CancelledError:
                pass
            await server.stop()
            assert backend.stopped
            assert not Path(socket_path).exists()

    print("ok: btd socket boundary")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
