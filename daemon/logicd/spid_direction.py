"""Virtual direction mapping for spid motion.

spid produces relative motion deltas, unlike the analog stick's absolute x/y
samples. This module converts accumulated relative motion into virtual
up/down/left/right tap requests that logicd routes through keymap,
macro, layer, or mouse-key handling.

Design intent:
- spid remains hardware-only and does not know layers or keymaps.
- logicd owns the mapping from motion to actions.
- Relative motion is accumulated and consumed in thresholds, so high-rate sensor
  packets can be coalesced without creating unbounded key-tap queues.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

from .spid_motion import SpidMotionEvent

Direction = Literal["up", "down", "left", "right"]
ActionResolver = Callable[[int, int], str]


@dataclass(frozen=True)
class SpidDirectionBinding:
    """Matrix coordinates used as virtual directions for spid motion."""

    name: str
    up: tuple[int, int]
    down: tuple[int, int]
    left: tuple[int, int]
    right: tuple[int, int]
    threshold: int = 24
    max_taps_per_flush: int = 4

    def coord(self, direction: Direction) -> tuple[int, int]:
        return getattr(self, direction)


@dataclass(frozen=True)
class SpidDirectionTap:
    name: str
    direction: Direction
    row: int
    col: int
    action: str
    taps: int = 1


@dataclass
class SpidDirectionResult:
    taps: list[SpidDirectionTap] = field(default_factory=list)
    remaining_dx: int = 0
    remaining_dy: int = 0
    dropped_taps: int = 0


class SpidDirectionMapper:
    """Convert relative spid motion to bounded virtual direction tap requests."""

    def __init__(self, binding: SpidDirectionBinding) -> None:
        self.binding = binding
        self._dx = 0
        self._dy = 0
        self.dropped_taps = 0

    def process(self, event: SpidMotionEvent, resolver: ActionResolver) -> SpidDirectionResult:
        self._dx += int(event.dx)
        self._dy += int(event.dy)
        result = SpidDirectionResult()
        threshold = max(1, int(self.binding.threshold))
        max_taps = max(1, int(self.binding.max_taps_per_flush))

        self._process_axis(result, axis="x", negative="left", positive="right", threshold=threshold, max_taps=max_taps, resolver=resolver)
        self._process_axis(result, axis="y", negative="up", positive="down", threshold=threshold, max_taps=max_taps, resolver=resolver)

        result.remaining_dx = self._dx
        result.remaining_dy = self._dy
        return result

    def _process_axis(
        self,
        result: SpidDirectionResult,
        *,
        axis: Literal["x", "y"],
        negative: Direction,
        positive: Direction,
        threshold: int,
        max_taps: int,
        resolver: ActionResolver,
    ) -> None:
        value = self._dx if axis == "x" else self._dy
        original_abs = abs(value)
        direction: Direction | None = None
        taps = 0
        if value <= -threshold:
            direction = negative
            taps = min(max_taps, original_abs // threshold)
            value += taps * threshold
        elif value >= threshold:
            direction = positive
            taps = min(max_taps, original_abs // threshold)
            value -= taps * threshold

        if direction is not None and taps > 0:
            row, col = self.binding.coord(direction)
            action = resolver(row, col)
            result.taps.append(SpidDirectionTap(self.binding.name, direction, row, col, action, taps))
            overflow = (original_abs // threshold) - taps
            if overflow > 0:
                self.dropped_taps += overflow
                result.dropped_taps += overflow

        if axis == "x":
            self._dx = value
        else:
            self._dy = value

    def reset(self) -> None:
        self._dx = 0
        self._dy = 0
        self.dropped_taps = 0
