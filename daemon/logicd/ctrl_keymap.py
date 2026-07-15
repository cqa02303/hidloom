"""Keymap and layer ctrl JSON-line commands for logicd."""
from __future__ import annotations

import logging
from typing import Any

from .ctrl_common import ctrl_error, ctrl_int, ctrl_response

log = logging.getLogger(__name__)
_TRACE_LEVEL = 5


def _notify_ledd_semantic_reload(ctx: Any, reason: str) -> None:
    notify = getattr(ctx, "push_ledd_semantic_reload", None)
    if notify is None:
        return
    try:
        notify()
        log.debug("ctrl %s: requested ledd semantic reload", reason)
    except Exception as exc:
        log.warning("ctrl %s: failed to request ledd semantic reload: %s", reason, exc)


async def process_remap_json(msg: dict, ctx: Any, writer: Any = None) -> None:
    t = msg.get("t")
    try:
        layer = ctrl_int(msg, "l")
        row = ctrl_int(msg, "r")
        col = ctrl_int(msg, "c")
        action = str(msg["a"])
        if not (0 <= layer < 32):
            raise ValueError(f"layer out of range: {layer}")
        if not ctx.matrix_in_range(row, col):
            raise ValueError(f"matrix out of range: row={row} col={col}")
        if not action or action == "None":
            raise ValueError("action must be a non-empty string")

        ctx.layers.set_action(layer, row, col, action)
        if writer is not None:
            await ctrl_response(writer, {"t": "M", "result": "ok"})
            log.info("ctrl M: set layer=%d (%d,%d) -> %s", layer, row, col, action)
        else:
            log.debug("ctrl M: set layer=%d (%d,%d) -> %s (no response)", layer, row, col, action)
    except (KeyError, TypeError, ValueError) as exc:
        await ctrl_error(writer, t, f"invalid remap request: {exc}")


async def process_keymap_get_json(ctx: Any, writer: Any = None) -> None:
    if writer is None:
        log.log(_TRACE_LEVEL, "ctrl G: no writer to respond")
        return
    try:
        layers = ctx.layers.layers_snapshot()
        response = {
            "t": "keymap",
            "layers": layers,
            "mode": ctx.current_hid_mode,
            "output_target": getattr(ctx, "current_output_target", ""),
            "active": ctx.layers.active_snapshot(),
        }
        await ctrl_response(writer, response)
        log.log(_TRACE_LEVEL, "ctrl G: keymap sent (%d layers)", len(layers))
    except Exception as exc:
        log.warning("ctrl G: failed to send keymap: %s", exc)


async def process_active_layers_get_json(ctx: Any, writer: Any = None) -> None:
    if writer is None:
        log.log(_TRACE_LEVEL, "ctrl ACTIVE: no writer to respond")
        return
    try:
        response = {
            "t": "active",
            "active": ctx.layers.active_snapshot(),
        }
        await ctrl_response(writer, response)
        log.log(_TRACE_LEVEL, "ctrl ACTIVE: active layers sent")
    except Exception as exc:
        log.warning("ctrl ACTIVE: failed to send active layers: %s", exc)


async def process_matrix_get_json(ctx: Any, writer: Any = None) -> None:
    if writer is None:
        log.log(_TRACE_LEVEL, "ctrl K: no writer to respond")
        return
    try:
        joysticks = getattr(ctx, "joysticks", None)
        joystick_status = (
            joysticks.status(ctx.layers.get_action)
            if joysticks is not None and hasattr(joysticks, "status")
            else {
                "schema": "joystick.runtime_status.v1",
                "source": "logicd.joysticks",
                "save_payload_includes_runtime_state": False,
                "sticks": [],
            }
        )
        response = {
            "t": "matrix",
            "pressed": [[row, col] for row, col in sorted(ctx.pressed_matrix)],
            "joystick": joystick_status,
        }
        await ctrl_response(writer, response)
        log.log(_TRACE_LEVEL, "ctrl K: matrix pressed state sent (%d keys)", len(ctx.pressed_matrix))
    except Exception as exc:
        log.warning("ctrl K: failed to send matrix state: %s", exc)


async def process_keymap_save_json(ctx: Any, writer: Any = None) -> None:
    if writer is None:
        log.debug("ctrl S: no writer to respond")
        return
    try:
        result_path = ctx.save_runtime_keymap()
        reload_native_core = getattr(ctx, "reload_native_core", None)
        if reload_native_core is not None:
            await reload_native_core()
        _notify_ledd_semantic_reload(ctx, "S")
        await ctrl_response(writer, {"t": "S", "result": "ok", "path": result_path})
        log.info("ctrl S: keymap saved to %s", result_path)
    except Exception as exc:
        await ctrl_response(writer, {"t": "S", "result": "error", "msg": str(exc)})
        log.warning("ctrl S: failed to save keymap: %s", exc)


async def process_layer_add_json(ctx: Any, writer: Any = None) -> None:
    if writer is None:
        log.debug("ctrl LAYER_ADD: no writer to respond")
        return
    try:
        layer = ctx.layers.add_layer()
        path = ctx.save_runtime_keymap()
        _notify_ledd_semantic_reload(ctx, "LAYER_ADD")
        layers = ctx.layers.layers_snapshot()
        await ctrl_response(writer, {
            "t": "LAYER_ADD",
            "result": "ok",
            "layer": layer,
            "layers": len(layers),
            "path": path,
        })
        log.info("ctrl LAYER_ADD: added layer=%d saved=%s", layer, path)
    except Exception as exc:
        await ctrl_response(writer, {"t": "LAYER_ADD", "result": "error", "msg": str(exc)})
        log.warning("ctrl LAYER_ADD: failed: %s", exc)


async def process_layer_clear_json(msg: dict, ctx: Any, writer: Any = None) -> None:
    if writer is None:
        log.debug("ctrl LAYER_CLEAR: no writer to respond")
        return
    try:
        layer = ctrl_int(msg, "l")
        if not (0 <= layer < 32):
            raise ValueError(f"layer out of range: {layer}")
        operation, keys = ctx.layers.clear_layer(layer)
        path = ctx.save_runtime_keymap()
        _notify_ledd_semantic_reload(ctx, "LAYER_CLEAR")
        layers = ctx.layers.layers_snapshot()
        await ctrl_response(writer, {
            "t": "LAYER_CLEAR",
            "result": "ok",
            "layer": layer,
            "operation": operation,
            "keys": keys,
            "layers": len(layers),
            "path": path,
        })
        log.info("ctrl LAYER_CLEAR: %s layer=%d keys=%d saved=%s", operation, layer, keys, path)
    except (KeyError, TypeError, ValueError) as exc:
        await ctrl_response(writer, {"t": "LAYER_CLEAR", "result": "error", "msg": str(exc)})
        log.warning("ctrl LAYER_CLEAR: failed: %s", exc)


async def process_layer_lock_clear_json(ctx: Any, writer: Any = None) -> None:
    if writer is None:
        log.debug("ctrl LAYER_LOCK_CLEAR: no writer to respond")
        return
    try:
        before = ctx.layers.active_snapshot()
        locked_before = list(before.get("locked", []) or [])
        ctx.layers.locked_clear()
        after = ctx.layers.active_snapshot()
        changed = bool(locked_before)
        if changed:
            push_ledd = getattr(ctx, "push_ledd_semantic_reload", None)
            if callable(push_ledd):
                push_ledd()
        await ctrl_response(writer, {
            "t": "LAYER_LOCK_CLEAR",
            "result": "ok",
            "changed": changed,
            "locked_before": locked_before,
            "active": after,
        })
        log.info("ctrl LAYER_LOCK_CLEAR: changed=%s locked_before=%s", changed, locked_before)
    except Exception as exc:
        await ctrl_response(writer, {"t": "LAYER_LOCK_CLEAR", "result": "error", "msg": str(exc)})
        log.warning("ctrl LAYER_LOCK_CLEAR: failed: %s", exc)


async def process_reset_keymap_json(ctx: Any, writer: Any = None) -> None:
    if writer is None:
        log.debug("ctrl RESET_KEYMAP: no writer to respond")
        return
    try:
        result = ctx.reset_runtime_keymap()
        _notify_ledd_semantic_reload(ctx, "RESET_KEYMAP")
        await ctrl_response(writer, {"t": "RESET_KEYMAP", "result": "ok", **result})
        log.info(
            "ctrl RESET_KEYMAP: loaded %d default layer(s), removed_runtime=%s",
            result["layers"],
            result["removed_runtime"],
        )
    except Exception as exc:
        await ctrl_response(writer, {"t": "RESET_KEYMAP", "result": "error", "msg": str(exc)})
        log.warning("ctrl RESET_KEYMAP: failed to reset keymap: %s", exc)
