"""Matrix, encoder, and joystick event processing for logicd."""
from __future__ import annotations

import asyncio
import inspect
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .action_expansion import expand_action_event
from .bt_manager import BtManager
from .encoder import EncoderEvent
from .host_led_output import DEFAULT_HOST_LED_OUTPUT_CONFIG, HostLedOutputConfig, toggle_host_led_state_for_action
from .joystick import JoystickKeyEvent, JoystickMouseEvent
from .hid_report import KEYCODE, MouseState
from .layer_action import handle_layer_action_with_status
from .wifi_manager import WifiManager

log = logging.getLogger(__name__)
# These small delays are intentional USB/BLE host-facing report spacing.  The
# physical keyboard missed rapid wrapper taps and mod-tap interruptions when
# press/release or press/press reports were emitted back-to-back.
_SYNTHETIC_TAP_HOLD_SEC = 0.060
_EXPANDED_ACTION_STEP_GAP_SEC = 0.020
_INTERACTION_PRESS_PRESS_GAP_SEC = 0.020
_MORSE_ALERT_DURATIONS = {
    "pending": 0.7,
    "commit": 1.1,
    "fallback": 1.2,
    "cancel": 0.8,
}
_OUTPUT_SWITCH_ACTIONS = {"KC_CONNAUTO", "KC_CONSOLE", "KC_USB", "KC_BT"}


@dataclass
class InputEventContext:
    layers: Any
    interactions: Any
    macros: Any
    encoders: Any
    joysticks: Any
    pressed_matrix: set[tuple[int, int]]
    push_ledd_key_event: Callable[[int, int, bool], None]
    push_ledd_status: Callable[[], None]
    push_i2cd_status: Callable[[], None]
    push_i2cd_alert: Callable[..., None]
    push_ledd_anim: Callable[[int], None]
    apply_lighting_key_action: Callable[[str, bool], bool]
    mouse_write_fn: Callable[[bytes], None]
    push_ledd_morse_feedback: Callable[[dict[str, Any]], None] | None = None
    led_overlay_states: dict[str, bool] = field(default_factory=dict)
    host_led_output: HostLedOutputConfig = DEFAULT_HOST_LED_OUTPUT_CONFIG
    push_ledd_overlay_state: Callable[[str, bool], None] | None = None
    bt_manager: Any = field(default_factory=BtManager)
    wifi_manager: Any = field(default_factory=WifiManager)
    push_bt_pairing_state: Callable[[str, str], None] | None = None
    bt_passkey: Any = None
    text_send: Any = None
    text_send_settings: dict[str, Any] = field(default_factory=dict)
    pty_mirror: Any = None
    pty_mirror_start_action: str = "KC_SH7"
    pty_mirror_prepare_output: Callable[[], Any] | None = None
    pty_mirror_set_capture: Callable[[bool], Any] | None = None
    pty_mirror_release_output: Callable[[], Any] | None = None
    pty_mirror_output_queue: asyncio.Queue | None = None
    pty_mirror_output_task: asyncio.Task | None = None
    core_key_event_fn: Callable[[str, bool, tuple[int, int] | None, str | None], Any] | None = None


async def dispatch_action_event(
    action: str,
    is_press: bool,
    ctx: InputEventContext,
    matrix_key: tuple[int, int] | None = None,
    source: str | None = None,
) -> None:
    """Expand wrapper/alias actions and dispatch concrete action steps."""
    steps = expand_action_event(action, is_press)
    for idx, step in enumerate(steps):
        await handle_resolved_action(step.action, step.is_press, ctx, matrix_key=matrix_key, source=source)
        if idx + 1 < len(steps):
            await asyncio.sleep(_EXPANDED_ACTION_STEP_GAP_SEC)


def _is_core_keyboard_action(action: str) -> bool:
    code = KEYCODE.get(action)
    return code is not None and 0 < int(code) < 0x200


async def _send_core_key_event_if_available(
    action: str,
    is_press: bool,
    ctx: InputEventContext,
    matrix_key: tuple[int, int] | None,
    source: str | None,
) -> bool:
    core_key_event_fn = getattr(ctx, "core_key_event_fn", None)
    if core_key_event_fn is None or not _is_core_keyboard_action(action):
        return False
    result = core_key_event_fn(action, is_press, matrix_key, source)
    if inspect.isawaitable(result):
        await result
    return True


def _resolved_event_gap_sec(current: Any, next_event: Any | None) -> float:
    if next_event is None or not current.is_press:
        return 0.0
    if not next_event.is_press and next_event.action == current.action:
        return _SYNTHETIC_TAP_HOLD_SEC
    if next_event.is_press:
        return _INTERACTION_PRESS_PRESS_GAP_SEC
    return 0.0


async def _dispatch_interaction_events(resolved_events: list[Any], ctx: InputEventContext, row: int | None = None, col: int | None = None) -> None:
    idx = 0
    while idx < len(resolved_events):
        resolved = resolved_events[idx]
        if row is None or col is None:
            log.debug(
                "%s tick -> %s",
                "P" if resolved.is_press else "R",
                resolved.action,
            )
        else:
            log.debug(
                "%s (%d,%d) -> %s",
                "P" if resolved.is_press else "R",
                row,
                col,
                resolved.action,
            )
        matrix_key = None
        if resolved.row is not None and resolved.col is not None:
            matrix_key = (resolved.row, resolved.col)
        await dispatch_action_event(
            resolved.action,
            resolved.is_press,
            ctx,
            matrix_key=matrix_key,
            source=resolved.source,
        )
        next_event = resolved_events[idx + 1] if idx + 1 < len(resolved_events) else None
        gap_sec = _resolved_event_gap_sec(resolved, next_event)
        if gap_sec > 0:
            await asyncio.sleep(gap_sec)
        idx += 1


def _morse_feedback_count(ctx: InputEventContext) -> int:
    feedback = getattr(getattr(ctx, "interactions", None), "morse_feedback_events", None)
    return len(feedback) if isinstance(feedback, list) else 0


def _morse_oled_alert(event: dict[str, Any]) -> tuple[str, float] | None:
    phase = str(event.get("phase", "")).lower()
    duration = _MORSE_ALERT_DURATIONS.get(phase)
    if duration is None:
        return None
    name = str(event.get("name") or "morse")
    sequence = str(event.get("sequence") or event.get("stroke") or "-")
    action = event.get("action") or event.get("pending_action")
    label = phase.upper()
    lines = [f"MORSE {name}", f"{sequence} {label}"]
    if action:
        lines.append(str(action))
    return "\n".join(lines), duration


def _push_morse_oled_alerts(ctx: InputEventContext, start_index: int) -> None:
    feedback = getattr(getattr(ctx, "interactions", None), "morse_feedback_events", None)
    if not isinstance(feedback, list):
        return
    for event in feedback[start_index:]:
        if not isinstance(event, dict):
            continue
        alert = _morse_oled_alert(event)
        if alert is None:
            continue
        if ctx.push_ledd_morse_feedback is not None:
            ctx.push_ledd_morse_feedback(dict(event))
        if ctx.push_i2cd_alert is None:
            continue
        message, duration = alert
        ctx.push_i2cd_alert(message, duration, immediate=True)


async def process_interaction_tick(ctx: InputEventContext) -> None:
    """Dispatch timeout-based interaction events even when no matrix event arrives."""
    feedback_start = _morse_feedback_count(ctx)
    resolved_events = ctx.interactions.on_tick(time.monotonic())
    _push_morse_oled_alerts(ctx, feedback_start)
    await _dispatch_interaction_events(resolved_events, ctx)


async def process_matrix_event(event: tuple, ctx: InputEventContext) -> None:
    kind, row, col = event
    is_press = kind == "P"

    if ctx.encoders.handles(row, col):
        encoder_result = ctx.encoders.process(row, col, is_press)
        if encoder_result == "invalid":
            log.warning("encoder transition ignored: row=%d col=%d press=%s", row, col, is_press)
        elif isinstance(encoder_result, EncoderEvent):
            await handle_encoder_event(encoder_result, ctx)
        return

    key = (row, col)
    already_pressed = key in ctx.pressed_matrix
    if is_press and already_pressed:
        log.debug("duplicate matrix press ignored: row=%d col=%d", row, col)
        return
    if not is_press and not already_pressed:
        log.debug("stray matrix release ignored: row=%d col=%d", row, col)
        return
    if is_press:
        ctx.pressed_matrix.add(key)
    else:
        ctx.pressed_matrix.discard(key)

    ctx.push_ledd_key_event(row, col, is_press)

    now = time.monotonic()
    feedback_start = _morse_feedback_count(ctx)
    resolved_events = ctx.interactions.on_key(row, col, is_press, now)
    resolved_events.extend(ctx.interactions.on_tick(now))
    _push_morse_oled_alerts(ctx, feedback_start)
    await _dispatch_interaction_events(resolved_events, ctx, row, col)


async def handle_encoder_event(event: EncoderEvent, ctx: InputEventContext) -> None:
    action = ctx.layers.get_action(event.row, event.col)
    log.info(
        "encoder %s %s -> (%d,%d) %s",
        event.name, event.direction, event.row, event.col, action,
    )
    ctx.push_ledd_key_event(event.row, event.col, True)
    await dispatch_action_event(action, True, ctx)
    await asyncio.sleep(0.030)
    ctx.push_ledd_key_event(event.row, event.col, False)
    await dispatch_action_event(action, False, ctx)


def _clear_layer_lock_for_output_switch(ctx: InputEventContext) -> None:
    """Clear transient Layer Lock state before changing output target."""
    locked_clear = getattr(ctx.layers, "locked_clear", None)
    active_snapshot = getattr(ctx.layers, "active_snapshot", None)
    if not callable(locked_clear):
        return
    had_locked = False
    if callable(active_snapshot):
        had_locked = bool(active_snapshot().get("locked", []))
    locked_clear()
    if had_locked:
        ctx.push_ledd_status()
        ctx.push_i2cd_status()


async def _clear_key_locks_for_output_switch(ctx: InputEventContext) -> None:
    """Release transient synthetic key locks before changing output target."""
    clear_key_locks = getattr(ctx.interactions, "clear_key_locks", None)
    if not callable(clear_key_locks):
        return
    for event in clear_key_locks(reason="output_switch"):
        await dispatch_action_event(event.action, event.is_press, ctx)


async def _clear_held_interactions_for_output_switch(
    ctx: InputEventContext,
    action: str,
    matrix_key: tuple[int, int] | None,
) -> None:
    """Release host-visible interaction-held keys before changing output target."""
    clear_held_keys = getattr(ctx.interactions, "clear_held_keys", None)
    if not callable(clear_held_keys):
        return
    for event in clear_held_keys(reason="output_switch", exclude_actions=(action,)):
        await dispatch_action_event(event.action, event.is_press, ctx)
    if matrix_key is None:
        ctx.pressed_matrix.clear()
    else:
        ctx.pressed_matrix.intersection_update({matrix_key})


async def _handle_pty_mirror_output_failure(exc: Exception, ctx: InputEventContext, pty_mirror: Any) -> None:
    log.warning("PTY mirror output dispatch failed: %s", exc)
    if pty_mirror is not None:
        stop = getattr(pty_mirror, "stop", None)
        if callable(stop):
            try:
                await stop(reason="output_dispatch_failed")
            except Exception as stop_exc:
                log.warning("PTY mirror stop after output dispatch failure failed: %s", stop_exc)
        setattr(pty_mirror, "active", False)
        active_modifiers = getattr(pty_mirror, "active_modifiers", None)
        if hasattr(active_modifiers, "clear"):
            active_modifiers.clear()
        setattr(pty_mirror, "last_reason", "output_dispatch_failed")
        setattr(pty_mirror, "last_error", str(exc))
    await _set_pty_mirror_capture(ctx, False)
    if ctx.push_i2cd_alert is not None:
        ctx.push_i2cd_alert("PTY ERROR", 3.0, immediate=True)


async def _set_pty_mirror_capture(ctx: InputEventContext, enabled: bool) -> bool:
    set_capture = getattr(ctx, "pty_mirror_set_capture", None)
    if not callable(set_capture):
        return True
    try:
        result = set_capture(enabled)
        if inspect.isawaitable(result):
            await result
    except Exception as exc:
        log.warning("PTY mirror matrix capture %s failed: %s", "enable" if enabled else "disable", exc)
        return False
    return True


async def _run_pty_mirror_output_queue(ctx: InputEventContext, pty_mirror: Any, queue: asyncio.Queue) -> None:
    from .pty_mirror_output_runner import dispatch_pty_mirror_text_plans

    while True:
        text_plans = await queue.get()
        try:
            result = await dispatch_pty_mirror_text_plans(text_plans, ctx)
            log.info(
                "PTY mirror output dispatch result=%s plans=%s taps=%s events=%s blocking=%s async=true",
                result.get("result"),
                result.get("plans"),
                result.get("taps"),
                result.get("events"),
                result.get("blocking_reasons"),
            )
        except Exception as exc:
            await _handle_pty_mirror_output_failure(exc, ctx, pty_mirror)
        finally:
            queue.task_done()


def _ensure_pty_mirror_output_queue(ctx: InputEventContext, pty_mirror: Any) -> asyncio.Queue:
    queue = getattr(pty_mirror, "output_dispatch_queue", None)
    if queue is None:
        queue = asyncio.Queue()
        setattr(pty_mirror, "output_dispatch_queue", queue)
    ctx.pty_mirror_output_queue = queue
    task = getattr(pty_mirror, "output_dispatch_task", None)
    if task is None or task.done():
        task = asyncio.create_task(_run_pty_mirror_output_queue(ctx, pty_mirror, queue))
        setattr(pty_mirror, "output_dispatch_task", task)
    ctx.pty_mirror_output_task = task
    return queue


async def _cancel_pty_mirror_output_queue(ctx: InputEventContext) -> None:
    pty_mirror = getattr(ctx, "pty_mirror", None)
    task = getattr(pty_mirror, "output_dispatch_task", None) if pty_mirror is not None else None
    if task is None:
        task = ctx.pty_mirror_output_task
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            log.warning("PTY mirror output queue cancel failed: %s", exc)
    if pty_mirror is not None:
        setattr(pty_mirror, "output_dispatch_task", None)
    ctx.pty_mirror_output_task = None
    queue = getattr(pty_mirror, "output_dispatch_queue", None) if pty_mirror is not None else None
    if queue is None:
        queue = ctx.pty_mirror_output_queue
    if queue is not None:
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            else:
                queue.task_done()
    if pty_mirror is not None:
        setattr(pty_mirror, "output_dispatch_queue", None)
    ctx.pty_mirror_output_queue = None
    release_output = getattr(ctx, "pty_mirror_release_output", None)
    if callable(release_output):
        try:
            result = release_output()
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            log.warning("PTY mirror output release failed: %s", exc)


async def _dispatch_pty_mirror_text_plans(
    text_plans: Any,
    ctx: InputEventContext,
    pty_mirror: Any,
    *,
    wait: bool = True,
) -> bool:
    if not text_plans:
        return True
    if not wait:
        queue = _ensure_pty_mirror_output_queue(ctx, pty_mirror)
        await queue.put(text_plans)
        return True
    try:
        from .pty_mirror_output_runner import dispatch_pty_mirror_text_plans

        result = await dispatch_pty_mirror_text_plans(text_plans, ctx)
        log.info(
            "PTY mirror output dispatch result=%s plans=%s taps=%s events=%s blocking=%s",
            result.get("result"),
            result.get("plans"),
            result.get("taps"),
            result.get("events"),
            result.get("blocking_reasons"),
        )
    except Exception as exc:
        await _handle_pty_mirror_output_failure(exc, ctx, pty_mirror)
        return False
    return True


async def _dispatch_pty_mirror_receiver_stop(ctx: InputEventContext, pty_mirror: Any) -> bool:
    try:
        from .pty_terminal_text import build_pty_terminal_receiver_stop_plan

        client = getattr(pty_mirror, "client", None)
        host_profile = getattr(client, "host_profile", None)
        plan = build_pty_terminal_receiver_stop_plan(host_profile=host_profile)
        if plan.get("available") is False and "pty_receiver_not_required" in plan.get("blocking_reasons", []):
            return True
        return await _dispatch_pty_mirror_text_plans([plan], ctx, pty_mirror)
    except Exception as exc:
        log.warning("PTY mirror receiver stop plan failed: %s", exc)
        return False


async def _handle_pty_mirror_background_stop(
    ctx: InputEventContext,
    pty_mirror: Any,
    status: dict[str, Any],
) -> None:
    reason = str(status.get("reason") or getattr(pty_mirror, "last_reason", "") or "exit")
    log.info("PTY mirror background stop detected reason=%s", reason)
    await _cancel_pty_mirror_output_queue(ctx)
    await _set_pty_mirror_capture(ctx, False)
    stop_output_polling = getattr(pty_mirror, "stop_output_polling", None)
    if callable(stop_output_polling):
        await stop_output_polling()
    if ctx.push_i2cd_alert is not None:
        ctx.push_i2cd_alert(f"PTY EXIT\n{reason}", 2.0, immediate=True)


async def handle_resolved_action(
    action: str,
    is_press: bool,
    ctx: InputEventContext,
    matrix_key: tuple[int, int] | None = None,
    source: str | None = None,
) -> None:
    pty_mirror = getattr(ctx, "pty_mirror", None)
    if (
        pty_mirror is not None
        and not is_press
        and action == getattr(ctx, "pty_mirror_start_action", "KC_SH7")
        and source != "pty_terminal_mirror"
        and getattr(pty_mirror, "_operator_escape_release_pending", False)
    ):
        setattr(pty_mirror, "_operator_escape_release_pending", False)
        return

    if (
        pty_mirror is not None
        and not getattr(pty_mirror, "active", False)
        and is_press
        and action == getattr(ctx, "pty_mirror_start_action", "KC_SH7")
        and source != "pty_terminal_mirror"
    ):
        prepare_output = getattr(ctx, "pty_mirror_prepare_output", None)
        if callable(prepare_output):
            try:
                result = prepare_output()
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                log.warning("PTY mirror output preparation failed: %s", exc)
                setattr(pty_mirror, "last_error", str(exc))
                setattr(pty_mirror, "last_reason", "output_prepare_failed")
                if ctx.push_i2cd_alert is not None:
                    ctx.push_i2cd_alert("PTY ERROR", 3.0, immediate=True)
                return
        result = await pty_mirror.start(source=action)
        log.info(
            "PTY mirror start requested action=%s active=%s reason=%s error=%s text_plans=%s",
            action,
            result.get("active"),
            result.get("last_reason"),
            result.get("last_error"),
            len(result.get("text_plans") or []),
        )
        if result.get("active"):
            if not await _set_pty_mirror_capture(ctx, True):
                await pty_mirror.stop(reason="capture_failed")
                setattr(pty_mirror, "active", False)
                setattr(pty_mirror, "last_reason", "capture_failed")
                if ctx.push_i2cd_alert is not None:
                    ctx.push_i2cd_alert("PTY ERROR", 3.0, immediate=True)
                return
        text_plans = result.get("text_plans")
        _ensure_pty_mirror_output_queue(ctx, pty_mirror)
        start_output_polling = getattr(pty_mirror, "start_output_polling", None)
        if callable(start_output_polling):
            start_output_polling(
                lambda plans: _ensure_pty_mirror_output_queue(ctx, pty_mirror).put_nowait(plans),
                lambda status: _handle_pty_mirror_background_stop(ctx, pty_mirror, status),
            )
        if not await _dispatch_pty_mirror_text_plans(text_plans, ctx, pty_mirror):
            return
        if result.get("active") is False:
            await _set_pty_mirror_capture(ctx, False)
        if ctx.push_i2cd_alert is not None:
            if result.get("active"):
                if getattr(pty_mirror, "active", False):
                    ctx.push_i2cd_alert("PTY START", 1.5, immediate=True)
            else:
                ctx.push_i2cd_alert("PTY ERROR", 3.0, immediate=True)
        return

    if (
        pty_mirror is not None
        and getattr(pty_mirror, "active", False)
        and source != "pty_terminal_mirror"
        and action == getattr(ctx, "pty_mirror_start_action", "KC_SH7")
    ):
        if is_press:
            await _cancel_pty_mirror_output_queue(ctx)
            await pty_mirror.stop(reason="operator_escape")
            await _set_pty_mirror_capture(ctx, False)
            setattr(pty_mirror, "_operator_escape_release_pending", True)
            await _dispatch_pty_mirror_receiver_stop(ctx, pty_mirror)
            if ctx.push_i2cd_alert is not None:
                ctx.push_i2cd_alert("PTY EXIT\noperator_escape", 2.0, immediate=True)
        return

    if (
        pty_mirror is not None
        and getattr(pty_mirror, "active", False)
        and source != "pty_terminal_mirror"
        and is_press
        and action in _OUTPUT_SWITCH_ACTIONS
    ):
        await _cancel_pty_mirror_output_queue(ctx)
        await pty_mirror.stop(reason="output_switch")
        await _set_pty_mirror_capture(ctx, False)
        await _dispatch_pty_mirror_receiver_stop(ctx, pty_mirror)
        if ctx.push_i2cd_alert is not None:
            ctx.push_i2cd_alert("PTY EXIT\noutput_switch", 2.0, immediate=True)

    if pty_mirror is not None and getattr(pty_mirror, "active", False) and source != "pty_terminal_mirror":
        is_interrupt_action = getattr(pty_mirror, "is_interrupt_action", None)
        if callable(is_interrupt_action) and is_interrupt_action(action, is_press):
            await _cancel_pty_mirror_output_queue(ctx)
        result = await pty_mirror.route_action(action, is_press)
        if result.get("clear_output_queue") and not (
            callable(is_interrupt_action) and is_interrupt_action(action, is_press)
        ):
            await _cancel_pty_mirror_output_queue(ctx)
        text_plans = result.get("text_plans")
        mirror_stopped = result.get("active") is False
        if mirror_stopped:
            await _cancel_pty_mirror_output_queue(ctx)
            stop_output_polling = getattr(pty_mirror, "stop_output_polling", None)
            if callable(stop_output_polling):
                await stop_output_polling()
        if not await _dispatch_pty_mirror_text_plans(text_plans, ctx, pty_mirror, wait=mirror_stopped):
            if result.get("consumed"):
                return
        if is_press and result.get("consumed") and result.get("active") is False:
            await _set_pty_mirror_capture(ctx, False)
            reason = str(result.get("reason") or "exit")
            if ctx.push_i2cd_alert is not None:
                if reason == "sessiond_unavailable" or reason.endswith("missing"):
                    ctx.push_i2cd_alert("PTY ERROR", 3.0, immediate=True)
                else:
                    ctx.push_i2cd_alert(f"PTY EXIT\n{reason}", 2.0, immediate=True)
        if result.get("consumed"):
            return

    if is_press and action in _OUTPUT_SWITCH_ACTIONS:
        await _clear_key_locks_for_output_switch(ctx)
        await _clear_held_interactions_for_output_switch(ctx, action, matrix_key)
        clear_shortcuts = getattr(ctx.interactions, "clear_runtime_shortcuts", None)
        if callable(clear_shortcuts):
            clear_shortcuts()
        _clear_layer_lock_for_output_switch(ctx)

    _handle_lock_led_overlay(action, is_press, ctx)

    if handle_layer_action_with_status(
        ctx.layers,
        action,
        is_press,
        ctx.push_ledd_status,
        ctx.push_i2cd_status,
    ):
        return

    anim_m = re.match(r"^ANIM\((\d+)\)$", action)
    if anim_m and is_press:
        ctx.push_ledd_anim(int(anim_m.group(1)))
        return

    if ctx.apply_lighting_key_action(action, is_press):
        return

    bt_passkey = getattr(ctx, "bt_passkey", None)
    if bt_passkey is not None:
        result = bt_passkey.handle_action(action, is_press)
        if result.consumed:
            if ctx.push_bt_pairing_state is not None:
                phase = "off" if result.submitted or result.canceled else result.phase
                ctx.push_bt_pairing_state(phase, result.digits)
            return

    if ctx.bt_manager is not None:
        handled = await ctx.bt_manager.handle_action(action, is_press)
        if handled:
            if is_press:
                await _push_bt_alert(action, ctx)
                await _push_bt_pairing_state(action, ctx)
            return

    if ctx.wifi_manager is not None:
        handled = await ctx.wifi_manager.handle_action(action, is_press)
        if handled:
            if is_press:
                await _push_wifi_alert(action, ctx)
            return

    if action == "KC_BT" and is_press:
        await _prepare_bt_output(ctx)

    if await _send_core_key_event_if_available(action, is_press, ctx, matrix_key, source):
        return

    await ctx.macros.handle(action, is_press)


def _handle_lock_led_overlay(action: str, is_press: bool, ctx: InputEventContext) -> None:
    if not is_press or ctx.push_ledd_overlay_state is None:
        return
    state = toggle_host_led_state_for_action(
        action,
        ctx.led_overlay_states,
        ctx.host_led_output,
        ctx.push_ledd_overlay_state,
    )
    if state is not None:
        log.info("LED overlay %s=%s via %s fallback", state, "on" if ctx.led_overlay_states[state] else "off", action)


async def _push_bt_alert(action: str, ctx: InputEventContext) -> None:
    if ctx.push_i2cd_alert is None:
        return
    try:
        status = await ctx.bt_manager.get_status()
    except Exception as exc:
        log.warning("Bluetooth status alert failed: %s", exc)
        ctx.push_i2cd_alert("BT ERROR", 2.0)
        return

    if action == "BT_DISCONNECT":
        message = "BT DISCONNECTED"
    elif action == "BT_FORGET_DEVICE":
        message = "BT FORGET"
    elif status.powered is False:
        message = "BT OFF"
    elif status.connected_devices:
        message = f"BT CONNECTED\n{len(status.connected_devices)} device"
    elif status.pairable or status.discoverable:
        message = "BT PAIRING"
    elif status.powered is True:
        message = "BT ON"
    else:
        message = "BT UNKNOWN"
    ctx.push_i2cd_alert(message, 2.0)


async def _push_wifi_alert(action: str, ctx: InputEventContext) -> None:
    if ctx.push_i2cd_alert is None:
        return
    try:
        status = await ctx.wifi_manager.get_status()
    except Exception as exc:
        log.warning("Wi-Fi status alert failed: %s", exc)
        ctx.push_i2cd_alert("Wi-Fi ERROR", 2.0)
        return

    if status.blocked is True:
        message = "Wi-Fi OFF\nuntil reboot"
    elif status.connected is True:
        message = f"Wi-Fi ON\n{status.ssid or 'connected'}"
    elif status.blocked is False:
        message = "Wi-Fi ON"
    else:
        message = "Wi-Fi UNKNOWN"
    ctx.push_i2cd_alert(message, 2.0)


async def _push_bt_pairing_state(action: str, ctx: InputEventContext) -> None:
    if ctx.push_bt_pairing_state is None:
        return
    if action not in {"BT_PAIRING_ON", "BT_PAIRING_OFF", "BT_PAIRING_TOGGLE"}:
        return
    try:
        status = await ctx.bt_manager.get_status()
    except Exception as exc:
        log.warning("Bluetooth pairing LED state failed: %s", exc)
        ctx.push_bt_pairing_state("failed", "")
        return
    if status.pairable or status.discoverable:
        if ctx.bt_passkey is not None:
            ctx.bt_passkey.begin()
        ctx.push_bt_pairing_state("pairing", "")
    else:
        if ctx.bt_passkey is not None:
            ctx.bt_passkey.cancel()
        ctx.push_bt_pairing_state("off", "")


async def _prepare_bt_output(ctx: InputEventContext) -> None:
    if ctx.bt_manager is None:
        return
    ensure_powered = getattr(ctx.bt_manager, "ensure_powered_for_output", None)
    if not callable(ensure_powered):
        return
    try:
        await ensure_powered()
    except Exception as exc:
        log.warning("Bluetooth output preparation failed: %s", exc)
        if ctx.push_i2cd_alert is not None:
            ctx.push_i2cd_alert("BT POWER ERROR", 2.0)


async def handle_analog_stick(index: int, x: int, y: int, ctx: InputEventContext) -> None:
    try:
        result = ctx.joysticks.process(index, x, y, ctx.layers.get_action)
    except IndexError as exc:
        log.warning("analog joystick ignored: %s", exc)
        return
    except Exception as exc:
        log.exception("analog joystick processing failed: index=%d x=%d y=%d error=%s", index, x, y, exc)
        return

    for event in result.key_events:
        await handle_joystick_key_event(event, ctx)
    if result.mouse_event is not None:
        handle_joystick_mouse_event(result.mouse_event, ctx)


async def handle_joystick_key_event(event: JoystickKeyEvent, ctx: InputEventContext) -> None:
    log.info(
        "joystick %s %s %s -> (%d,%d) %s",
        event.name, event.direction, "press" if event.is_press else "release",
        event.row, event.col, event.action,
    )
    ctx.push_ledd_key_event(event.row, event.col, event.is_press)
    await dispatch_action_event(event.action, event.is_press, ctx)


def handle_joystick_mouse_event(event: JoystickMouseEvent, ctx: InputEventContext) -> None:
    try:
        buttons = int(getattr(ctx.macros, "mouse_buttons", 0) or 0)
        ctx.mouse_write_fn(MouseState.merge_buttons(event.report, buttons))
        log.debug(
            "joystick %s mouse report dx=%d dy=%d wheel=%d",
            event.name, event.dx, event.dy, event.wheel,
        )
    except Exception as exc:
        log.warning("joystick %s mouse report failed: %s", exc)
