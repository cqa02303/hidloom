"""USB HID keyboard LED Output Report reader."""
from __future__ import annotations

import asyncio
import errno
import logging
import os
from collections.abc import Awaitable, Callable

from .hid_report import HID_REPORT_ID_KEYBOARD

log = logging.getLogger(__name__)


def host_led_report_from_payload(payload: bytes) -> int:
    """Return the keyboard LED bitfield from a HID Output Report payload."""
    if not payload:
        raise ValueError("empty host LED output report")
    if len(payload) >= 2 and payload[0] == HID_REPORT_ID_KEYBOARD:
        return int(payload[1]) & 0xFF
    return int(payload[0]) & 0xFF


async def host_led_output_report_loop(
    hidg_path: str,
    handle_report: Callable[[int], Awaitable[dict[str, bool]]],
    *,
    retry_sec: float = 1.0,
    idle_sec: float = 0.05,
) -> None:
    """Read USB keyboard LED Output Reports from ``hidg_path`` forever."""
    fd: int | None = None
    try:
        while True:
            if fd is None:
                try:
                    fd = os.open(hidg_path, os.O_RDONLY | os.O_NONBLOCK)
                    log.info("opened host LED output report reader: %s", hidg_path)
                except OSError as exc:
                    log.debug("host LED output report reader unavailable (%s): %s", hidg_path, exc)
                    await asyncio.sleep(retry_sec)
                    continue

            try:
                payload = os.read(fd, 8)
            except BlockingIOError:
                await asyncio.sleep(idle_sec)
                continue
            except OSError as exc:
                if exc.errno in {errno.ENODEV, errno.EIO, errno.EBADF, errno.ENXIO}:
                    log.info("host LED output report reader disconnected (%s): %s", hidg_path, exc)
                else:
                    log.warning("host LED output report read failed (%s): %s", hidg_path, exc)
                try:
                    os.close(fd)
                except OSError:
                    pass
                fd = None
                await asyncio.sleep(retry_sec)
                continue

            if not payload:
                await asyncio.sleep(idle_sec)
                continue

            try:
                report = host_led_report_from_payload(payload)
            except ValueError as exc:
                log.debug("invalid host LED output report payload ignored: %s payload=%r", exc, payload)
                continue
            await handle_report(report)
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
