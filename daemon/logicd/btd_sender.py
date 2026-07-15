"""Best-effort sender from logicd OutputRouter to btd.

Design intent:
- Bluetooth HID transport should live behind btd, not inside logicd.
- logicd sends canonical keyboard and mouse HID reports to btd.
- btd availability is a connection state, not a reason to fail key processing.

This sender is deliberately synchronous and non-blocking-ish from logicd's point
of view: it opens a Unix socket only when needed, writes one report, and drops
reports while btd is unavailable.  The output router isolates failures so other
backends such as gadget/uinput/debug still receive the same report.
"""
from __future__ import annotations

import logging
import os
import json
import socket
import struct
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

DEFAULT_BTD_SOCKET = "/tmp/btd_events.sock"
DEFAULT_RECONNECT_INTERVAL_SEC = 1.0
KEYBOARD_REPORT_SIZE = 8
MOUSE_REPORT_SIZE = 4
CONSUMER_REPORT_SIZE = 2
FRAME_MAGIC = b"btd1"
FRAME_TYPE_KEYBOARD = 1
FRAME_TYPE_MOUSE = 2
FRAME_TYPE_CONTROL = 3
FRAME_TYPE_CONSUMER = 4


@dataclass
class BtdReportSender:
    """Callable keyboard report sender for BluetoothHidOutputBackend.

    Common I/F expected by OutputRouter backends:
    ``sender(report: bytes) -> None``.

    The sender keeps a short-lived persistent Unix socket when possible.  If btd
    is stopped or the socket is missing, it drops reports until the reconnect
    interval expires.  This prevents repeated connect attempts on every scan
    event while keeping reconnection automatic.
    """

    socket_path: str = DEFAULT_BTD_SOCKET
    reconnect_interval_sec: float = DEFAULT_RECONNECT_INTERVAL_SEC
    timeout_sec: float = 0.05

    def __post_init__(self) -> None:
        self._sock: socket.socket | None = None
        self._last_connect_attempt = 0.0

    def __call__(self, report: bytes) -> None:
        self.send(report)

    def send(self, report: bytes) -> None:
        if len(report) != KEYBOARD_REPORT_SIZE:
            log.debug("drop invalid btd keyboard report len=%d", len(report))
            return
        self._send_frame(FRAME_TYPE_KEYBOARD, report)

    def send_mouse(self, report: bytes) -> None:
        if len(report) != MOUSE_REPORT_SIZE:
            log.debug("drop invalid btd mouse report len=%d", len(report))
            return
        self._send_frame(FRAME_TYPE_MOUSE, report)

    def send_consumer_report(self, report: bytes) -> None:
        if len(report) != CONSUMER_REPORT_SIZE:
            log.debug("drop invalid btd consumer report len=%d", len(report))
            return
        self._send_frame(FRAME_TYPE_CONSUMER, report)

    def send_consumer_usage(self, usage_id: int, is_press: bool) -> None:
        report = struct.pack("<H", int(usage_id) if is_press else 0)
        self.send_consumer_report(report)

    def set_reconnect_advertising(self, enabled: bool) -> None:
        payload = json.dumps(
            {"command": "reconnect_advertising", "enabled": bool(enabled)},
            separators=(",", ":"),
        ).encode("utf-8")
        self._send_control_payload(payload)

    def sync_pairing_advertising(self) -> None:
        payload = json.dumps(
            {"command": "sync_pairing_advertising"},
            separators=(",", ":"),
        ).encode("utf-8")
        self._send_control_payload(payload)

    def _send_control_payload(self, payload: bytes) -> None:
        if len(payload) > 255:
            log.debug("drop oversized btd control frame len=%d", len(payload))
            return
        self._send_frame(FRAME_TYPE_CONTROL, payload, force_connect=True)

    def _send_frame(self, report_type: int, report: bytes, *, force_connect: bool = False) -> None:
        sock = self._ensure_connected(force=force_connect)
        if sock is None:
            return
        frame = FRAME_MAGIC + bytes([report_type, len(report)]) + report
        try:
            sock.sendall(frame)
        except OSError as exc:
            log.debug("btd send failed; retrying once after reconnect: %s", exc)
            self.close()
            retry_sock = self._ensure_connected(force=True)
            if retry_sock is None:
                return
            try:
                retry_sock.sendall(frame)
            except OSError as retry_exc:
                log.debug("btd retry send failed; will reconnect later: %s", retry_exc)
                self.close()

    def _ensure_connected(self, *, force: bool = False) -> socket.socket | None:
        if self._sock is not None:
            return self._sock

        now = time.monotonic()
        if not force and now - self._last_connect_attempt < self.reconnect_interval_sec:
            return None
        self._last_connect_attempt = now

        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(self.timeout_sec)
            sock.connect(self.socket_path)
            self._sock = sock
            log.info("connected to btd socket: %s", self.socket_path)
            return sock
        except OSError as exc:
            log.debug("btd socket unavailable: %s: %s", self.socket_path, exc)
            try:
                sock.close()
            except Exception:
                pass
            return None

    def close(self) -> None:
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def check(self) -> None:
        """Connection probe hook used by OutputRouter-compatible code."""
        if not os.path.exists(self.socket_path):
            self.close()
