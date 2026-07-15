#!/usr/bin/env python3
"""Regression tests for spid virtual direction mapping."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.spid_direction import SpidDirectionBinding, SpidDirectionMapper  # noqa: E402
from logicd.spid_motion import SpidMotionEvent  # noqa: E402


def resolver(row: int, col: int) -> str:
    return {
        (1, 0): "KC_UP",
        (1, 1): "KC_DOWN",
        (1, 2): "KC_LEFT",
        (1, 3): "KC_RIGHT",
    }[(row, col)]


def main() -> None:
    binding = SpidDirectionBinding(
        name="ball",
        up=(1, 0),
        down=(1, 1),
        left=(1, 2),
        right=(1, 3),
        threshold=10,
        max_taps_per_flush=3,
    )
    mapper = SpidDirectionMapper(binding)

    result = mapper.process(SpidMotionEvent(dx=9, dy=0), resolver)
    assert result.taps == []
    assert result.remaining_dx == 9

    result = mapper.process(SpidMotionEvent(dx=1, dy=0), resolver)
    assert len(result.taps) == 1
    assert result.taps[0].direction == "right"
    assert result.taps[0].row == 1
    assert result.taps[0].col == 3
    assert result.taps[0].action == "KC_RIGHT"
    assert result.taps[0].taps == 1
    assert result.remaining_dx == 0

    result = mapper.process(SpidMotionEvent(dx=-25, dy=25), resolver)
    assert [(tap.direction, tap.action, tap.taps) for tap in result.taps] == [
        ("left", "KC_LEFT", 2),
        ("down", "KC_DOWN", 2),
    ]
    assert result.remaining_dx == -5
    assert result.remaining_dy == 5

    result = mapper.process(SpidMotionEvent(dx=100, dy=-100), resolver)
    assert [(tap.direction, tap.taps) for tap in result.taps] == [("right", 3), ("up", 3)]
    assert result.dropped_taps > 0
    assert mapper.dropped_taps == result.dropped_taps

    mapper.reset()
    result = mapper.process(SpidMotionEvent(dx=0, dy=-10), resolver)
    assert [(tap.direction, tap.action, tap.taps) for tap in result.taps] == [("up", "KC_UP", 1)]

    print("ok: logicd spid direction")


if __name__ == "__main__":
    main()
