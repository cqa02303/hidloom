"""Validation guard for touch-panel flick dispatch envelopes.

The HTTP/browser flick UI may preview gestures freely, but logicd-facing
payloads must contain only the final action selected by the resolver.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any

from .touch_flick_composition import TOUCH_FLICK_COMPOSITION_MODE, romaji_taps_for_text_action
from .text_send_runner import dispatch_text_send_action

_FORBIDDEN_PREVIEW_FIELDS = {
    "preview_state",
    "requested_direction",
    "resolved_direction",
    "requestedDirection",
    "resolvedDirection",
}
_ALLOWED_OUTPUTS = {"keycode", "preview", "text"}
_ALLOWED_DISPATCH = {"preview_noop", "tap_action"}
_UNICODE_ACTION_RE = re.compile(r"^U\+[0-9A-Fa-f]{4,6}$")
_SEND_STRING_ACTION_RE = re.compile(r"^(?:TEXT|SEND_STRING)\([A-Za-z0-9_.-]{1,48}\)$")
_COMPOSITION_TAP_HOLD_SEC = 0.006
_COMPOSITION_TAP_GAP_SEC = 0.012


@dataclass(frozen=True)
class TouchFlickDispatchPlan:
    result: str
    action: str | None = None
    output: str | None = None
    dispatch: str | None = None
    reason: str | None = None
    enabled: bool = False

    @property
    def dispatchable(self) -> bool:
        return self.result == "ok" and self.enabled and self.dispatch == "tap_action"

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "result": self.result,
            "dispatchable": self.dispatchable,
            "enabled": self.enabled,
        }
        if self.action is not None:
            data["action"] = self.action
        if self.output is not None:
            data["output"] = self.output
        if self.dispatch is not None:
            data["dispatch"] = self.dispatch
        if self.reason is not None:
            data["reason"] = self.reason
        return data


def _blocked(reason: str, *, action: str | None = None, output: str | None = None, dispatch: str | None = None) -> TouchFlickDispatchPlan:
    return TouchFlickDispatchPlan(
        result="blocked",
        action=action,
        output=output,
        dispatch=dispatch,
        reason=reason,
        enabled=False,
    )


def _error(reason: str) -> TouchFlickDispatchPlan:
    return TouchFlickDispatchPlan(result="error", reason=reason)


def validate_touch_flick_dispatch_event(payload: Any) -> TouchFlickDispatchPlan:
    """Return a dispatch plan for a resolver-created touch flick event.

    Preview payloads return ``blocked``. Runtime dispatch is allowed only when
    the resolver explicitly enables the event and selects ``tap_action``.
    """
    if not isinstance(payload, dict):
        return _error("event_must_be_object")
    forbidden = sorted(_FORBIDDEN_PREVIEW_FIELDS.intersection(payload))
    if forbidden:
        return _error(f"preview_state_not_allowed:{','.join(forbidden)}")
    if payload.get("source") != "touch_panel_flick":
        return _error("source_must_be_touch_panel_flick")
    action = payload.get("action")
    if not isinstance(action, str) or not action:
        return _error("missing_action")
    output = payload.get("output", "preview")
    if not isinstance(output, str) or output not in _ALLOWED_OUTPUTS:
        return _error("invalid_output")
    dispatch = payload.get("dispatch", "preview_noop")
    if not isinstance(dispatch, str) or dispatch not in _ALLOWED_DISPATCH:
        return _error("invalid_dispatch")
    enabled = payload.get("enabled")
    if enabled is not True:
        return _blocked(
            "disabled_by_resolver",
            action=action,
            output=output,
            dispatch=dispatch,
        )
    if dispatch != "tap_action":
        return _blocked(
            "dispatch_not_enabled",
            action=action,
            output=output,
            dispatch=dispatch,
        )
    if output == "text" and not (_UNICODE_ACTION_RE.fullmatch(action) or _SEND_STRING_ACTION_RE.fullmatch(action)):
        return _blocked(
            "unknown_text_action",
            action=action,
            output=output,
            dispatch=dispatch,
        )
    if output not in {"keycode", "text"}:
        return _blocked(
            "output_not_dispatchable",
            action=action,
            output=output,
            dispatch=dispatch,
        )
    return TouchFlickDispatchPlan(
        result="ok",
        action=action,
        output=output,
        dispatch=dispatch,
        enabled=True,
    )


def _composition_blocking_reason(action: str) -> str | None:
    _taps, reasons = romaji_taps_for_text_action(action, "text")
    if reasons:
        return str(reasons[0])
    return None


async def _tap_action(action: str, ctx: Any, hold_sec: float) -> int:
    from .input_events import dispatch_action_event

    await dispatch_action_event(action, True, ctx)
    if hold_sec > 0:
        await asyncio.sleep(hold_sec)
    await dispatch_action_event(action, False, ctx)
    return 2


async def _tap_composition_sequence(action: str, ctx: Any, hold_sec: float) -> dict[str, Any]:
    from .input_events import dispatch_action_event

    text_taps, reasons = romaji_taps_for_text_action(action, "text")
    if reasons:
        return {"result": "blocked", "reason": reasons[0], "events": 0}
    if not text_taps:
        return {"result": "blocked", "reason": "romaji_sequence_unavailable", "events": 0}

    runtime = getattr(ctx, "text_send", None)
    if runtime is not None and getattr(runtime, "active", False):
        return {"result": "blocked", "reason": "touch_flick_composition_busy", "events": 0}
    if runtime is not None and hasattr(runtime, "begin"):
        runtime.begin("touch_flick_composition", timeout_sec=2.0)

    events = 0
    emitted_taps = 0
    try:
        for index, tap in enumerate(text_taps):
            key = tap.get("key")
            if not isinstance(key, str) or not key:
                continue
            modifiers = [mod for mod in tap.get("modifiers", []) if isinstance(mod, str)]
            for mod in modifiers:
                await dispatch_action_event(mod, True, ctx)
                events += 1
            events += await _tap_action(key, ctx, _COMPOSITION_TAP_HOLD_SEC)
            emitted_taps += 1
            for mod in reversed(modifiers):
                await dispatch_action_event(mod, False, ctx)
                events += 1
            if index < len(text_taps) - 1 and _COMPOSITION_TAP_GAP_SEC > 0:
                await asyncio.sleep(_COMPOSITION_TAP_GAP_SEC)
        if runtime is not None and hasattr(runtime, "finish"):
            runtime.finish()
    except Exception:
        if runtime is not None and hasattr(runtime, "cancel"):
            runtime.cancel("explicit_cancel")
        raise
    return {
        "result": "ok",
        "events": events,
        "composition_mode": TOUCH_FLICK_COMPOSITION_MODE,
        "composition_hold_sec": _COMPOSITION_TAP_HOLD_SEC,
        "composition_tap_gap_sec": _COMPOSITION_TAP_GAP_SEC,
        "composition_taps": emitted_taps,
    }


async def dispatch_touch_flick_event(payload: Any, ctx: Any, hold_sec: float = 0.060) -> dict[str, Any]:
    """Tap a validated touch flick action through the normal input dispatcher."""
    plan = validate_touch_flick_dispatch_event(payload)
    result = plan.as_dict()
    result["events"] = 0
    if not plan.dispatchable or not plan.action:
        return result
    if plan.output == "text":
        text_result = await dispatch_text_send_action(plan.action, ctx)
        if text_result.get("result") == "ok":
            result.update(text_result)
            return result
        if plan.action and _SEND_STRING_ACTION_RE.fullmatch(plan.action):
            result.update(text_result)
            result["dispatchable"] = False
            result["enabled"] = False
            return result
        reason = _composition_blocking_reason(plan.action)
        if reason is not None:
            result.update({"result": "blocked", "dispatchable": False, "enabled": False, "reason": reason})
            return result
        text_result = await _tap_composition_sequence(plan.action, ctx, hold_sec)
        result.update(text_result)
        if text_result.get("result") != "ok":
            result["dispatchable"] = False
            result["enabled"] = False
        return result

    result["events"] = await _tap_action(plan.action, ctx, hold_sec)
    return result
