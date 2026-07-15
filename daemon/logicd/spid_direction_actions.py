"""Dispatch spid virtual direction taps through the normal action pipeline.

`spid_direction.SpidDirectionMapper` converts relative motion into bounded
virtual direction tap requests. This module is the bridge from those tap
requests to logicd's existing key action handling.

Design intent:
- spid remains hardware-only and emits normalized motion.
- spid_direction owns relative-motion thresholding.
- this module turns resulting virtual taps into press/release action events.
- keymap, layers, macros, mouse keys, lighting, and BT actions are still handled
  by the same pipeline as physical matrix keys.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from .input_events import dispatch_action_event
from .spid_direction import SpidDirectionResult, SpidDirectionTap

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpidDirectionDispatchStats:
    """Summary of dispatched virtual direction taps."""

    tap_events: int = 0
    action_events: int = 0
    dropped_taps: int = 0


async def dispatch_spid_direction_tap(
    tap: SpidDirectionTap,
    ctx: Any,
    *,
    hold_sec: float = 0.010,
    gap_sec: float = 0.0,
) -> SpidDirectionDispatchStats:
    """Dispatch one virtual direction tap request as press/release actions."""
    tap_count = max(0, int(tap.taps))
    if tap_count == 0:
        return SpidDirectionDispatchStats()

    action_events = 0
    for _ in range(tap_count):
        ctx.push_ledd_key_event(tap.row, tap.col, True)
        await dispatch_action_event(tap.action, True, ctx)
        action_events += 1
        if hold_sec > 0:
            await asyncio.sleep(hold_sec)
        ctx.push_ledd_key_event(tap.row, tap.col, False)
        await dispatch_action_event(tap.action, False, ctx)
        action_events += 1
        if gap_sec > 0:
            await asyncio.sleep(gap_sec)
    log.debug(
        "spid direction tap dispatched name=%s direction=%s row=%d col=%d action=%s taps=%d",
        tap.name,
        tap.direction,
        tap.row,
        tap.col,
        tap.action,
        tap_count,
    )
    return SpidDirectionDispatchStats(tap_events=tap_count, action_events=action_events)


async def dispatch_spid_direction_result(
    result: SpidDirectionResult,
    ctx: Any,
    *,
    hold_sec: float = 0.010,
    gap_sec: float = 0.0,
) -> SpidDirectionDispatchStats:
    """Dispatch all virtual taps produced from one spid motion flush."""
    tap_events = 0
    action_events = 0
    for tap in result.taps:
        stats = await dispatch_spid_direction_tap(tap, ctx, hold_sec=hold_sec, gap_sec=gap_sec)
        tap_events += stats.tap_events
        action_events += stats.action_events
    return SpidDirectionDispatchStats(
        tap_events=tap_events,
        action_events=action_events,
        dropped_taps=int(result.dropped_taps),
    )
