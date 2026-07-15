"""Helpers for consuming spid mouse motion events in logicd.

`spid` is optional and owns SPI mouse sensor details. logicd should only care
about normalized dx/dy/wheel/buttons events and translate them into either the
existing mouse HID report shape used by the configured mouse output handler
such as virtual direction mapping.

Design constraints:
- Do not open SPI here.
- Do not require spid to be running on boards without a mouse sensor.
- Treat spid reports like i2cd analog-stick reports: external device daemon
  produces normalized events; logicd consumes them.
- spid can be high-rate, so logicd must not try to synchronously emit one HID
  report for every incoming packet. Coalesce, rate-limit, and drop stale motion
  to keep keyboard processing stable.
- Keep transport selection in the output router rather than this SPID adapter.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, Callable

log = logging.getLogger(__name__)

MOUSE_REPORT_SIZE = 4
DEFAULT_SPID_SOCKET = "/tmp/spi_events.sock"
DEFAULT_OUTPUT_HZ = 125.0
DEFAULT_MAX_BUFFERED_EVENTS = 64
SpidMotionEventHandler = Callable[["SpidMotionEvent"], Awaitable[None]]


def _clamp_i8(value: int) -> int:
    return max(-127, min(127, int(value)))


@dataclass(frozen=True)
class SpidMotionEvent:
    dx: int = 0
    dy: int = 0
    wheel: int = 0
    buttons: int = 0
    sensor: str = ""

    @property
    def is_zero(self) -> bool:
        return self.dx == 0 and self.dy == 0 and self.wheel == 0 and self.buttons == 0


def parse_spid_motion(payload: bytes | str | dict[str, Any]) -> SpidMotionEvent | None:
    """Parse one spid JSON Lines payload.

    Returns None for non-motion events such as status/error. This lets logicd
    ignore optional spid status chatter while still accepting motion reports.
    """
    if isinstance(payload, dict):
        data = payload
    else:
        text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("spid payload must be a JSON object")
    if data.get("t") != "motion":
        return None
    return SpidMotionEvent(
        dx=int(data.get("dx", 0)),
        dy=int(data.get("dy", 0)),
        wheel=int(data.get("wheel", 0)),
        buttons=int(data.get("buttons", 0)) & 0xFF,
        sensor=str(data.get("sensor", "")),
    )


def build_mouse_report_from_spid(event: SpidMotionEvent) -> bytes:
    """Build the existing 4-byte mouse report from a spid event.

    Current MouseState reports are 4 bytes:
    [buttons, dx, dy, wheel]

    dx/dy/wheel are clamped to signed 8-bit HID range and encoded as bytes.
    """
    dx = _clamp_i8(event.dx)
    dy = _clamp_i8(event.dy)
    wheel = _clamp_i8(event.wheel)
    return bytes([
        event.buttons & 0xFF,
        dx & 0xFF,
        dy & 0xFF,
        wheel & 0xFF,
    ])


@dataclass
class SpidMotionAccumulator:
    """Coalesce high-rate spid motion into bounded HID output reports.

    We intentionally prefer stable keyboard processing over perfect mouse motion
    fidelity. When incoming SPI motion is faster than logicd can output, we
    merge deltas, clamp accumulated motion, and count dropped samples instead of
    allowing an unbounded queue to grow.
    """

    max_buffered_events: int = DEFAULT_MAX_BUFFERED_EVENTS
    dx: int = 0
    dy: int = 0
    wheel: int = 0
    buttons: int = 0
    buffered_events: int = 0
    dropped_events: int = 0

    def add(self, event: SpidMotionEvent) -> None:
        if self.buffered_events >= self.max_buffered_events:
            self.dx = _clamp_i8(self.dx)
            self.dy = _clamp_i8(self.dy)
            self.wheel = _clamp_i8(self.wheel)
            self.buttons = event.buttons
            self.dropped_events += 1
            return
        self.dx += event.dx
        self.dy += event.dy
        self.wheel += event.wheel
        self.buttons = event.buttons
        self.buffered_events += 1

    def has_motion(self) -> bool:
        return self.buffered_events > 0 and (self.dx != 0 or self.dy != 0 or self.wheel != 0 or self.buttons != 0)

    def pop_report(self) -> bytes | None:
        if not self.has_motion():
            self.clear()
            return None
        event = SpidMotionEvent(dx=self.dx, dy=self.dy, wheel=self.wheel, buttons=self.buttons)
        report = build_mouse_report_from_spid(event)
        self.clear(keep_buttons=True)
        return report

    def clear(self, *, keep_buttons: bool = False) -> None:
        buttons = self.buttons if keep_buttons else 0
        self.dx = 0
        self.dy = 0
        self.wheel = 0
        self.buttons = buttons
        self.buffered_events = 0


class SpidMotionHandler:
    """Adapter from high-rate spid JSON Lines to rate-limited mouse_write_fn."""

    def __init__(
        self,
        mouse_write_fn: Callable[[bytes], None],
        *,
        drop_zero_motion: bool = True,
        output_hz: float = DEFAULT_OUTPUT_HZ,
        max_buffered_events: int = DEFAULT_MAX_BUFFERED_EVENTS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._mouse_write = mouse_write_fn
        self.drop_zero_motion = bool(drop_zero_motion)
        self.output_interval = 1.0 / max(1.0, float(output_hz))
        self._clock = clock
        self._next_flush = self._clock()
        self._acc = SpidMotionAccumulator(max_buffered_events=max_buffered_events)
        self.events = 0
        self.reports = 0
        self.ignored = 0

    @property
    def dropped_events(self) -> int:
        return self._acc.dropped_events

    def handle_event(self, event: SpidMotionEvent, *, flush: bool = True) -> bool:
        self.events += 1
        if self.drop_zero_motion and event.is_zero:
            return False
        self._acc.add(event)
        if flush:
            return self.flush_due()
        return False

    def handle_line(self, line: bytes | str, *, flush: bool = True) -> bool:
        event = parse_spid_motion(line)
        if event is None:
            self.ignored += 1
            return False
        return self.handle_event(event, flush=flush)

    def flush_due(self) -> bool:
        now = self._clock()
        if now < self._next_flush:
            return False
        self._next_flush = now + self.output_interval
        return self.flush()

    def flush(self) -> bool:
        report = self._acc.pop_report()
        if report is None:
            return False
        self._mouse_write(report)
        self.reports += 1
        log.debug("spid coalesced mouse report=%s dropped=%d", report.hex(), self.dropped_events)
        return True


async def spid_motion_connect_loop(
    socket_path: str,
    mouse_write_fn: Callable[[bytes], None],
    *,
    enabled: bool = False,
    reconnect_interval: float = 1.0,
    drop_zero_motion: bool = True,
    output_hz: float = DEFAULT_OUTPUT_HZ,
    max_buffered_events: int = DEFAULT_MAX_BUFFERED_EVENTS,
    event_handler: SpidMotionEventHandler | None = None,
) -> None:
    """Maintain an optional connection from logicd to spid.

    If `event_handler` is provided, parsed motion events are passed to that
    async handler instead of the default mouse HID accumulator. This is used for
    virtual direction mode while preserving the same spid socket boundary.
    """
    if not enabled:
        log.info("spid motion input disabled")
        return
    handler = SpidMotionHandler(
        mouse_write_fn,
        drop_zero_motion=drop_zero_motion,
        output_hz=output_hz,
        max_buffered_events=max_buffered_events,
    )
    while True:
        if not os.path.exists(socket_path):
            log.debug("spid socket not found: %s", socket_path)
            await asyncio.sleep(reconnect_interval)
            continue
        try:
            reader, writer = await asyncio.open_unix_connection(socket_path)
            log.info("connected to spid socket: %s", socket_path)
            try:
                while True:
                    line = await reader.readline()
                    if not line:
                        break
                    try:
                        event = parse_spid_motion(line)
                        if event is None:
                            handler.ignored += 1
                            continue
                        if event_handler is not None:
                            await event_handler(event)
                        else:
                            handler.handle_event(event)
                    except Exception as exc:
                        log.warning("invalid spid event ignored: %s", exc)
            finally:
                if event_handler is None:
                    handler.flush()
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
                log.info("disconnected from spid socket")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.debug("spid connection error: %s", exc)
        await asyncio.sleep(reconnect_interval)
