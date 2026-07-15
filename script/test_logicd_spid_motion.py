#!/usr/bin/env python3
"""Regression tests for logicd spid motion event handling."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.spid_motion import (  # noqa: E402
    SpidMotionAccumulator,
    SpidMotionEvent,
    SpidMotionHandler,
    build_mouse_report_from_spid,
    parse_spid_motion,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, sec: float) -> None:
        self.now += sec


def main() -> None:
    event = parse_spid_motion(b'{"t":"motion","dx":3,"dy":-2,"wheel":1,"buttons":5,"sensor":"mock"}\n')
    assert event == SpidMotionEvent(dx=3, dy=-2, wheel=1, buttons=5, sensor="mock")
    assert build_mouse_report_from_spid(event) == bytes([5, 3, 0xFE, 1])

    clamped = build_mouse_report_from_spid(SpidMotionEvent(dx=200, dy=-200, wheel=300, buttons=0x1FF))
    assert clamped == bytes([0xFF, 127, 0x81, 127])

    assert parse_spid_motion('{"t":"status","sensor":"mock","ok":true}') is None

    acc = SpidMotionAccumulator(max_buffered_events=3)
    acc.add(SpidMotionEvent(dx=10, dy=1, buttons=1))
    acc.add(SpidMotionEvent(dx=20, dy=2, buttons=2))
    assert acc.buffered_events == 2
    assert acc.pop_report() == bytes([2, 30, 3, 0])
    assert acc.buffered_events == 0

    acc.add(SpidMotionEvent(dx=100, dy=100))
    acc.add(SpidMotionEvent(dx=100, dy=100))
    acc.add(SpidMotionEvent(dx=100, dy=100))
    acc.add(SpidMotionEvent(dx=100, dy=100, buttons=7))
    assert acc.dropped_events == 1
    assert acc.pop_report() == bytes([7, 127, 127, 0])

    reports: list[bytes] = []
    clock = FakeClock()
    handler = SpidMotionHandler(reports.append, output_hz=100.0, clock=clock)
    assert handler.handle_line('{"t":"status","sensor":"mock","ok":true}') is False
    assert handler.ignored == 1
    assert handler.handle_line('{"t":"motion","dx":0,"dy":0,"wheel":0,"buttons":0}') is False
    assert handler.events == 1
    assert handler.reports == 0

    # First motion flushes immediately because next_flush starts at current time.
    assert handler.handle_line('{"t":"motion","dx":1,"dy":2,"wheel":0,"buttons":1}') is True
    assert reports == [bytes([1, 1, 2, 0])]
    assert handler.reports == 1

    # High-rate events before next interval should be coalesced and not emitted yet.
    assert handler.handle_line('{"t":"motion","dx":3,"dy":0,"wheel":0,"buttons":1}') is False
    assert handler.handle_line('{"t":"motion","dx":4,"dy":0,"wheel":0,"buttons":1}') is False
    assert reports == [bytes([1, 1, 2, 0])]

    clock.advance(0.010)
    assert handler.flush_due() is True
    assert reports[-1] == bytes([1, 7, 0, 0])

    keep_zero_reports: list[bytes] = []
    keep_zero = SpidMotionHandler(keep_zero_reports.append, drop_zero_motion=False, clock=FakeClock())
    assert keep_zero.handle_line('{"t":"motion","dx":0,"dy":0,"wheel":0,"buttons":0}') is False
    assert keep_zero_reports == []

    print("ok: logicd spid motion")


if __name__ == "__main__":
    main()
