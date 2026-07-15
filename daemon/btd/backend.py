"""Backend interface for btd Bluetooth HID implementations.

The logging and BlueZ BLE HID implementations share this small interface.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from .protocol import (
    ConsumerReport,
    KeyboardReport,
    MouseReport,
    null_consumer_report,
    null_keyboard_report,
    null_mouse_report,
)

log = logging.getLogger("btd.backend")


class BtdBackend(Protocol):
    """Minimal interface used by the btd socket server."""

    async def start(self) -> None:
        """Initialize backend resources."""

    async def stop(self) -> None:
        """Release backend resources."""

    async def send_keyboard_report(self, report: KeyboardReport) -> None:
        """Send one keyboard HID report."""

    async def send_mouse_report(self, report: MouseReport) -> None:
        """Send one mouse HID report."""

    async def send_consumer_report(self, report: ConsumerReport) -> None:
        """Send one Consumer Control HID report."""

    async def set_reconnect_advertising(self, enabled: bool) -> None:
        """Enable reconnect advertising while BT output is selected."""


@dataclass
class LoggingBackend:
    """Diagnostic backend that logs validated reports without using BlueZ."""

    send_null_on_stop: bool = True

    async def start(self) -> None:
        log.info("logging backend started")

    async def stop(self) -> None:
        if self.send_null_on_stop:
            await self.send_keyboard_report(null_keyboard_report())
            await self.send_mouse_report(null_mouse_report())
            await self.send_consumer_report(null_consumer_report())
        log.info("logging backend stopped")

    async def send_keyboard_report(self, report: KeyboardReport) -> None:
        log.info("backend keyboard report null=%s bytes=%s", report.is_null, report.hex)

    async def send_mouse_report(self, report: MouseReport) -> None:
        log.info("backend mouse report null=%s bytes=%s", report.is_null, report.hex)

    async def send_consumer_report(self, report: ConsumerReport) -> None:
        log.info("backend consumer report null=%s bytes=%s", report.is_null, report.hex)

    async def set_reconnect_advertising(self, enabled: bool) -> None:
        log.info("backend reconnect advertising %s", "enabled" if enabled else "disabled")
