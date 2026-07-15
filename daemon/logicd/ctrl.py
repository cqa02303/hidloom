"""Ctrl socket JSON-line helper functions for logicd."""
from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .ctrl_common import clamp_with_log, ctrl_error, ctrl_int, ctrl_response
from .ctrl_keymap import (
    process_active_layers_get_json,
    process_keymap_get_json,
    process_keymap_save_json,
    process_layer_add_json,
    process_layer_clear_json,
    process_layer_lock_clear_json,
    process_matrix_get_json,
    process_remap_json,
    process_reset_keymap_json,
)
from .ctrl_led import process_led_json
from .ctrl_runtime import process_bt_json, process_output_json, process_spid_json
from .caps_word_status import caps_word_status_from_engine
from .repeat_key_status import repeat_key_status_from_engine

log = logging.getLogger(__name__)


def script_dirs_from_config(cfg: dict, default_script_dir: str, fallback_script_dir: str) -> list[str]:
    script_dirs: list[str] = []
    configured = cfg.get("settings", {}).get("script_dir")
    if configured:
        script_dirs.append(str(configured))
    for path in (default_script_dir, fallback_script_dir):
        if path not in script_dirs:
            script_dirs.append(path)
    return script_dirs


@dataclass
class CtrlContext:
    matrix_in_range: Callable[[int, int], bool]
    handle_analog_stick: Callable[[int, int, int], Awaitable[None]]
    layers: Any
    current_hid_mode: str
    current_output_target: str
    pressed_matrix: set[tuple[int, int]]
    save_runtime_keymap: Callable[[], str]
    reset_runtime_keymap: Callable[[], dict]
    led_state: dict[str, int]
    normalize_led_state: Callable[[dict], dict[str, int]]
    load_led_state: Callable[[], None]
    save_led_state: Callable[[], str]
    cancel_led_state_save: Callable[[], None]
    push_ledd_vialrgb_direct: Callable[[int, list], None]
    push_ledd_vialrgb_direct_pattern: Callable[[str, float, int], None]
    normalize_vialrgb_mode: Callable[[int], int]
    remember_nonzero_led_mode: Callable[[], None]
    push_ledd_vialrgb: Callable[[], None]
    schedule_led_state_save: Callable[[], None]
    notify_i2cd_led_effect_if_changed: Callable[[int, int], None]
    interactions: Any | None = None
    # Optional spid control hooks.  ctrl_events.sock carries low-rate state /
    # connect requests; high-rate motion stays on spi_events.sock.
    handle_spid_connect: Callable[[str], Awaitable[None]] | None = None
    handle_spid_disconnect: Callable[[], Awaitable[None]] | None = None
    handle_bt_action: Callable[[str], Awaitable[None]] | None = None
    handle_output_target: Callable[[str], Awaitable[None]] | None = None
    handle_host_led_report: Callable[[int], Awaitable[dict[str, bool]]] | None = None
    push_ledd_semantic_reload: Callable[[], None] | None = None
    drain_morse_feedback: Callable[[], list[dict[str, Any]]] | None = None
    handle_touch_flick_event: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None
    cancel_text_send: Callable[[str], dict[str, Any]] | None = None
    joysticks: Any | None = None
    push_ledd_key_event: Callable[[int, int, bool], None] | None = None
    reload_native_core: Callable[[], Awaitable[dict[str, Any]]] | None = None


async def process_ctrl_json(line: str, ctx: CtrlContext, writer: Any = None) -> None:
    if not line:
        return
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        log.warning("ctrl: invalid JSON: %r", line)
        if writer is not None:
            await ctrl_response(writer, {"t": None, "result": "error", "msg": "invalid JSON"})
        return
    if not isinstance(msg, dict):
        await ctrl_error(writer, None, f"JSON root must be object: {type(msg).__name__}")
        return

    t = msg.get("t")
    if t == "A":
        try:
            stick = clamp_with_log("stick", ctrl_int(msg, "stick", default=0), 0, 31, "ctrl A")
            x = clamp_with_log("x", ctrl_int(msg, "x", default=0), -32768, 32767, "ctrl A")
            y = clamp_with_log("y", ctrl_int(msg, "y", default=0), -32768, 32767, "ctrl A")
        except (TypeError, ValueError) as exc:
            await ctrl_error(writer, t, f"invalid analog request: {exc}")
            return
        log.debug("Analog: stick=%d x=%d y=%d", stick, x, y)
        await ctx.handle_analog_stick(stick, x, y)
    elif t == "M":
        await process_remap_json(msg, ctx, writer)
    elif t == "G":
        await process_keymap_get_json(ctx, writer)
    elif t == "ACTIVE":
        await process_active_layers_get_json(ctx, writer)
    elif t == "K":
        await process_matrix_get_json(ctx, writer)
    elif t == "S":
        await process_keymap_save_json(ctx, writer)
    elif t == "LAYER_ADD":
        await process_layer_add_json(ctx, writer)
    elif t == "LAYER_CLEAR":
        await process_layer_clear_json(msg, ctx, writer)
    elif t == "LAYER_LOCK_CLEAR":
        await process_layer_lock_clear_json(ctx, writer)
    elif t == "RESET_KEYMAP":
        await process_reset_keymap_json(ctx, writer)
    elif t == "SPID_CONNECT" or (t == "SPID_STATUS" and msg.get("state") == "ready"):
        await process_spid_json(msg, ctx, writer)
    elif t == "SPID_DISCONNECT" or (t == "SPID_STATUS" and msg.get("state") in {"disabled", "no_device", "stopped"}):
        await process_spid_json(msg, ctx, writer)
    elif t == "LED":
        await process_led_json(msg, ctx, writer)
    elif t == "BT":
        await process_bt_json(msg, ctx, writer)
    elif t == "OUTPUT":
        await process_output_json(msg, ctx, writer)
    elif t == "HOST_LED":
        await process_host_led_json(msg, ctx, writer)
    elif t == "MORSE_FEEDBACK":
        await process_morse_feedback_json(ctx, writer)
    elif t == "TOUCH_FLICK":
        await process_touch_flick_json(msg, ctx, writer)
    elif t == "TEXT_SEND_CANCEL":
        await process_text_send_cancel_json(msg, ctx, writer)
    elif t == "INTERACTION_STATUS":
        await process_interaction_status_json(ctx, writer)
    elif t == "JOYSTICK_STATUS":
        await process_joystick_status_json(ctx, writer)
    elif t in {"LEDD_RELOAD", "LED_SEMANTIC_RELOAD"}:
        await process_ledd_reload_json(msg, ctx, writer)
    else:
        await ctrl_error(writer, t, f"unknown type: {t!r}", level=logging.INFO)


async def process_host_led_json(msg: dict, ctx: CtrlContext, writer: Any = None) -> None:
    if ctx.handle_host_led_report is None:
        await ctrl_error(writer, "HOST_LED", "host LED output report handling is not available")
        return
    try:
        field = "report" if "report" in msg else "value"
        report = ctrl_int(msg, field, default=0)
        if not 0 <= report <= 0xFF:
            raise ValueError(f"report must be 0..255: {report}")
    except (TypeError, ValueError) as exc:
        await ctrl_error(writer, "HOST_LED", f"invalid host LED report: {exc}")
        return
    changed = await ctx.handle_host_led_report(report)
    if writer is not None:
        await ctrl_response(writer, {"t": "HOST_LED", "result": "ok", "report": report, "changed": changed})


async def process_morse_feedback_json(ctx: CtrlContext, writer: Any = None) -> None:
    if ctx.drain_morse_feedback is None:
        await ctrl_error(writer, "MORSE_FEEDBACK", "morse feedback is not available")
        return
    events = ctx.drain_morse_feedback()
    if writer is not None:
        await ctrl_response(writer, {"t": "MORSE_FEEDBACK", "result": "ok", "events": events, "count": len(events)})


async def process_touch_flick_json(msg: dict, ctx: CtrlContext, writer: Any = None) -> None:
    if ctx.handle_touch_flick_event is None:
        await ctrl_error(writer, "TOUCH_FLICK", "touch flick dispatch is not available")
        return
    event = msg.get("event")
    if not isinstance(event, dict):
        await ctrl_error(writer, "TOUCH_FLICK", "event must be object")
        return
    result = await ctx.handle_touch_flick_event(event)
    if writer is not None:
        await ctrl_response(writer, {"t": "TOUCH_FLICK", **result})


async def process_text_send_cancel_json(msg: dict, ctx: CtrlContext, writer: Any = None) -> None:
    if ctx.cancel_text_send is None:
        await ctrl_error(writer, "TEXT_SEND_CANCEL", "text send cancel is not available")
        return
    reason = str(msg.get("reason") or "explicit_cancel")
    status = ctx.cancel_text_send(reason)
    if writer is not None:
        await ctrl_response(writer, {"t": "TEXT_SEND_CANCEL", "result": "ok", **status})


async def process_interaction_status_json(ctx: CtrlContext, writer: Any = None) -> None:
    engine = getattr(ctx, "interactions", None)
    if engine is None:
        await ctrl_error(writer, "INTERACTION_STATUS", "interaction runtime is not available")
        return
    caps_word = caps_word_status_from_engine(engine)
    repeat_key = repeat_key_status_from_engine(engine)
    key_locks = getattr(engine, "key_locks", None)
    key_lock = key_locks.status() if key_locks is not None and hasattr(key_locks, "status") else {"keys": []}
    layers = getattr(engine, "layers", None)
    active_snapshot = layers.active_snapshot() if layers is not None and hasattr(layers, "active_snapshot") else {}
    oneshot_layers = active_snapshot.get("oneshot") if isinstance(active_snapshot, dict) else []
    one_shot_layer = {
        "active_count": len(oneshot_layers) if isinstance(oneshot_layers, list) else 0,
        "source": "LayerManager.active_snapshot.oneshot",
    }
    if writer is not None:
        await ctrl_response(writer, {
            "t": "INTERACTION_STATUS",
            "result": "ok",
            "schema": "interaction.runtime_status.v1",
            "source": "logicd.interactions",
            "save_payload_includes_runtime_state": False,
            "caps_word": caps_word,
            "repeat_key": repeat_key,
            "key_lock": key_lock,
            "one_shot_layer": one_shot_layer,
            "snapshot": {
                "pressed_count": len(getattr(engine, "pressed", {}) or {}),
                "pending_timer_count": len(getattr(engine, "timers", []) or []),
                "clear_runtime_shortcuts_resets": ["caps_word.active", "repeat_key.history_available"],
                "clear_key_locks_resets": ["key_lock.keys"],
            },
        })


async def process_joystick_status_json(ctx: CtrlContext, writer: Any = None) -> None:
    joysticks = getattr(ctx, "joysticks", None)
    if joysticks is None or not hasattr(joysticks, "status"):
        await ctrl_error(writer, "JOYSTICK_STATUS", "joystick runtime is not available")
        return
    status = joysticks.status(ctx.layers.get_action)
    if writer is not None:
        await ctrl_response(writer, {"t": "JOYSTICK_STATUS", "result": "ok", **status})


async def process_ledd_reload_json(msg: dict, ctx: CtrlContext, writer: Any = None) -> None:
    if ctx.push_ledd_semantic_reload is None:
        await ctrl_error(writer, "LEDD_RELOAD", "ledd semantic reload is not available")
        return
    target = str(msg.get("target", "semantic_roles")).strip().lower()
    if target not in {"semantic_roles", "led_semantic_roles"}:
        await ctrl_error(writer, "LEDD_RELOAD", f"unsupported reload target: {target!r}")
        return
    ctx.push_ledd_semantic_reload()
    if writer is not None:
        await ctrl_response(writer, {"t": "LEDD_RELOAD", "result": "ok", "target": "semantic_roles"})
