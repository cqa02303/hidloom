"""Optional btd mirror sink for keyboard HID reports.

This module wraps an existing synchronous HID writer.  The original output path
(USB gadget / uinput) is always called first.  When enabled, the same keyboard
HID report bytes are also sent to btd over a Unix domain socket.

The mirror is best-effort: connection failures are logged at debug level and do
not raise to callers.  This keeps logicd stable even when btd is not running.
"""
from __future__ import annotations

import logging
import socket
import time
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_BTD_SOCKET = "/tmp/btd_events.sock"


class BtdMirrorSink:
    def __init__(
        self,
        socket_path: str = DEFAULT_BTD_SOCKET,
        *,
        reconnect_interval: float = 1.0,
        timeout: float = 0.02,
    ) -> None:
        self.socket_path = socket_path
        self.reconnect_interval = reconnect_interval
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._last_connect_attempt = 0.0

    def close(self) -> None:
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def send(self, report: bytes) -> None:
        sock = self._socket()
        if sock is None:
            return
        try:
            sock.sendall(report)
        except OSError as exc:
            log.debug("btd mirror send failed: %s", exc)
            self.close()

    def _socket(self) -> socket.socket | None:
        if self._sock is not None:
            return self._sock
        now = time.monotonic()
        if now - self._last_connect_attempt < self.reconnect_interval:
            return None
        self._last_connect_attempt = now
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect(self.socket_path)
            self._sock = sock
            log.info("btd mirror connected: %s", self.socket_path)
            return sock
        except OSError as exc:
            log.debug("btd mirror unavailable: %s", exc)
            try:
                sock.close()
            except Exception:
                pass
            return None


def wrap_keyboard_writer_with_btd_mirror(
    write_fn: Callable[[bytes], None],
    *,
    enabled: bool,
    socket_path: str = DEFAULT_BTD_SOCKET,
) -> Callable[[bytes], None]:
    """Return write_fn wrapped with optional best-effort btd mirroring."""
    if not enabled:
        return write_fn

    sink = BtdMirrorSink(socket_path)

    def _write(report: bytes) -> None:
        write_fn(report)
        sink.send(report)

    # Preserve control hooks used by existing dynamic output switching code.
    for attr in ("check_and_switch", "force_gadget", "force_uinput", "force_auto"):
        value: Any = getattr(write_fn, attr, None)
        if value is not None:
            setattr(_write, attr, value)
    setattr(_write, "btd_mirror_sink", sink)
    log.info("btd mirror enabled: %s", socket_path)
    return _write
