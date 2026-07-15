"""Runtime keyboard-tap runner for validated text-send actions."""
from __future__ import annotations

import asyncio
import time
from typing import Any

from .text_send_safety import (
    DEFAULT_TEXT_SEND_RUNNER_TIMEOUT_SEC,
    build_text_send_real_send_plan,
    normalize_text_send_runner_timeout,
)

TEXT_SEND_RUNNER_SCHEMA = "text_send.runtime_runner.v1"
DEFAULT_TEXT_SEND_TAP_HOLD_SEC = 0.006
DEFAULT_TEXT_SEND_TAP_GAP_SEC = 0.180


def _runtime_busy(runtime: Any) -> bool:
    return bool(runtime is not None and getattr(runtime, "active", False))


async def _dispatch_tap(tap: dict[str, Any], ctx: Any, hold_sec: float) -> int:
    from .input_events import dispatch_action_event

    key = tap.get("key")
    if not isinstance(key, str) or not key:
        return 0
    events = 0
    modifiers = [mod for mod in tap.get("modifiers", []) if isinstance(mod, str) and mod]
    for mod in modifiers:
        await dispatch_action_event(mod, True, ctx)
        events += 1
    await dispatch_action_event(key, True, ctx)
    events += 1
    if hold_sec > 0:
        await asyncio.sleep(hold_sec)
    await dispatch_action_event(key, False, ctx)
    events += 1
    for mod in reversed(modifiers):
        await dispatch_action_event(mod, False, ctx)
        events += 1
    return events


async def dispatch_text_send_action(
    action: object,
    ctx: Any,
    *,
    hold_sec: float = DEFAULT_TEXT_SEND_TAP_HOLD_SEC,
    gap_sec: float = DEFAULT_TEXT_SEND_TAP_GAP_SEC,
    now: float | None = None,
) -> dict[str, Any]:
    """Execute a text-send action through keyboard tap reports.

    The action must pass ``text_send.real_send_plan.v1`` first.  This runner
    emits only normal key tap actions through the existing active keyboard
    output path and shares ``TextSendRuntimeState`` for cancel / timeout state.
    """
    settings = getattr(ctx, "text_send_settings", None) or {}
    runtime = getattr(ctx, "text_send", None)
    plan = build_text_send_real_send_plan(action, settings)
    result: dict[str, Any] = {
        "schema": TEXT_SEND_RUNNER_SCHEMA,
        "result": "blocked",
        "action": plan.get("action"),
        "plan_schema": plan.get("schema"),
        "real_send_allowed": bool(plan.get("real_send_allowed")),
        "blocking_reasons": list(plan.get("blocking_reasons") or []),
        "events": 0,
        "text_send_taps": 0,
    }
    if not plan.get("real_send_allowed"):
        return result
    if runtime is None or not hasattr(runtime, "begin"):
        result["blocking_reasons"] = ["text_send_runtime_state_missing"]
        return result
    if _runtime_busy(runtime):
        result["blocking_reasons"] = ["text_send_runner_busy"]
        return result

    tap_dry_run = plan.get("tap_dry_run") if isinstance(plan.get("tap_dry_run"), dict) else {}
    sequences = tap_dry_run.get("sequences") if isinstance(tap_dry_run, dict) else []
    if not isinstance(sequences, list) or not sequences:
        result["blocking_reasons"] = ["text_send_tap_sequence_unavailable"]
        return result

    runner_settings = settings.get("text_send_runner") if isinstance(settings.get("text_send_runner"), dict) else {}
    timeout_sec = normalize_text_send_runner_timeout(
        runner_settings.get("timeout_sec", DEFAULT_TEXT_SEND_RUNNER_TIMEOUT_SEC)
    )
    started_at = time.monotonic() if now is None else now
    runtime.begin(str(action), now=started_at, timeout_sec=timeout_sec)

    events = 0
    taps = 0
    try:
        for seq_index, sequence in enumerate(sequences):
            seq_taps = sequence.get("taps") if isinstance(sequence, dict) else []
            if not isinstance(seq_taps, list):
                continue
            for tap_index, tap in enumerate(seq_taps):
                if hasattr(runtime, "timeout_due") and runtime.timeout_due(time.monotonic()):
                    status = runtime.cancel("runner_timeout")
                    result.update({
                        "result": "blocked",
                        "blocking_reasons": ["text_send_runner_timeout"],
                        "runtime": status,
                        "events": events,
                        "text_send_taps": taps,
                    })
                    return result
                if not _runtime_busy(runtime):
                    result.update({
                        "result": "blocked",
                        "blocking_reasons": ["text_send_runner_canceled"],
                        "events": events,
                        "text_send_taps": taps,
                    })
                    return result
                events += await _dispatch_tap(tap, ctx, hold_sec)
                taps += 1
                is_last_tap = seq_index == len(sequences) - 1 and tap_index == len(seq_taps) - 1
                if not is_last_tap and gap_sec > 0:
                    await asyncio.sleep(gap_sec)
        finished = runtime.finish()
    except Exception:
        if hasattr(runtime, "cancel"):
            runtime.cancel("explicit_cancel")
        raise

    result.update({
        "result": "ok",
        "blocking_reasons": [],
        "events": events,
        "text_send_taps": taps,
        "text_send_tap_gap_sec": gap_sec,
        "text_send_tap_hold_sec": hold_sec,
        "runtime": finished,
    })
    return result
