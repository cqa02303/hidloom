"""Dispatch PTY mirror terminal output through the existing keyboard route."""
from __future__ import annotations

import asyncio
from typing import Any

from .pty_terminal_text import PTY_TERMINAL_SOURCE

PTY_MIRROR_OUTPUT_RUNNER_SCHEMA = "pty_mirror.output_runner.v1"
DEFAULT_PTY_MIRROR_TAP_HOLD_SEC = 0.006
DEFAULT_PTY_MIRROR_TAP_GAP_SEC = 0.020
PTY_MIRROR_OUTPUT_YIELD_EVERY_TAPS = 16


async def _dispatch_tap(tap: dict[str, Any], ctx: Any, hold_sec: float) -> int:
    from .input_events import dispatch_action_event

    key = tap.get("key")
    if not isinstance(key, str) or not key:
        return 0
    events = 0
    raw_modifiers = tap.get("modifiers", [])
    modifiers = [mod for mod in raw_modifiers if isinstance(mod, str) and mod] if isinstance(raw_modifiers, list) else []
    pressed: list[str] = []
    first_error: BaseException | None = None
    try:
        for mod in modifiers:
            pressed.append(mod)
            await dispatch_action_event(mod, True, ctx, source=PTY_TERMINAL_SOURCE)
            events += 1
        pressed.append(key)
        await dispatch_action_event(key, True, ctx, source=PTY_TERMINAL_SOURCE)
        events += 1
        if hold_sec > 0:
            await asyncio.sleep(hold_sec)
    except BaseException as exc:
        first_error = exc
    finally:
        for action in reversed(pressed):
            try:
                await dispatch_action_event(action, False, ctx, source=PTY_TERMINAL_SOURCE)
                events += 1
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
    if first_error is not None:
        raise first_error
    return events


def _plan_timing(plan: dict[str, Any], key: str, fallback: float) -> float:
    try:
        value = float(plan.get(key, fallback))
    except (TypeError, ValueError):
        return fallback
    if value < 0:
        return fallback
    return value


async def dispatch_pty_mirror_text_plans(
    plans: list[dict[str, Any]],
    ctx: Any,
    *,
    hold_sec: float = DEFAULT_PTY_MIRROR_TAP_HOLD_SEC,
    gap_sec: float = DEFAULT_PTY_MIRROR_TAP_GAP_SEC,
) -> dict[str, Any]:
    """Emit available PTY text plans as synthetic keyboard taps.

    The synthetic source is part of the logicd loop guard: generated output taps
    must reach the active HID route, but they must not be routed back into the
    PTY input path.
    """
    result: dict[str, Any] = {
        "schema": PTY_MIRROR_OUTPUT_RUNNER_SCHEMA,
        "result": "ok",
        "plans": 0,
        "events": 0,
        "taps": 0,
        "blocking_reasons": [],
    }
    available_plans = [plan for plan in plans if isinstance(plan, dict) and plan.get("available") is True]
    if plans and not available_plans:
        result["blocking_reasons"].append("no_available_pty_text_plan")
    for plan in available_plans:
        taps = plan.get("taps")
        if not isinstance(taps, list) or not taps:
            result["blocking_reasons"].append("pty_text_plan_taps_unavailable")
            continue
        result["plans"] += 1
        plan_hold_sec = _plan_timing(plan, "tap_hold_sec", hold_sec)
        plan_gap_sec = _plan_timing(plan, "tap_gap_sec", gap_sec)
        for tap_index, tap in enumerate(taps):
            if not isinstance(tap, dict):
                result["blocking_reasons"].append("invalid_pty_text_tap")
                continue
            key = tap.get("key")
            if not isinstance(key, str) or not key:
                result["blocking_reasons"].append("invalid_pty_text_tap_key")
                continue
            modifiers = tap.get("modifiers", [])
            if modifiers is not None and (
                not isinstance(modifiers, list)
                or any(not isinstance(mod, str) or not mod for mod in modifiers)
            ):
                result["blocking_reasons"].append("invalid_pty_text_tap_modifier")
                continue
            result["events"] += await _dispatch_tap(tap, ctx, plan_hold_sec)
            result["taps"] += 1
            if result["taps"] % PTY_MIRROR_OUTPUT_YIELD_EVERY_TAPS == 0:
                await asyncio.sleep(0)
            is_last = tap_index == len(taps) - 1 and plan is available_plans[-1]
            if not is_last and plan_gap_sec > 0:
                next_gap_sec = _plan_timing(tap, "post_gap_sec", plan_gap_sec)
                if tap_index == len(taps) - 1:
                    next_gap_sec = max(plan_gap_sec, _plan_timing(plan, "post_gap_sec", plan_gap_sec))
                await asyncio.sleep(next_gap_sec)
    if result["blocking_reasons"]:
        result["result"] = "blocked" if result["taps"] == 0 else "partial"
        result["blocking_reasons"] = list(dict.fromkeys(result["blocking_reasons"]))
    result["tap_hold_sec"] = hold_sec
    result["tap_gap_sec"] = gap_sec
    return result
