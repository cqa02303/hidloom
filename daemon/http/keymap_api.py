"""HTTP keymap API route handlers."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from aiohttp import web

from keymap_actions import is_valid_keymap_action, normalize_keymap_action

log = logging.getLogger(__name__)

SendCtrl = Callable[[Dict[str, Any]], Awaitable[Optional[Dict[str, Any]]]]
AuditLog = Callable[..., None]
ScheduleSave = Callable[[], None]
ACTIVE_LAYER_FALLBACK = {"momentary": [], "toggled": [], "oneshot": [], "locked": [], "conditional": [], "all": [0]}


class DebouncedKeymapSaver:
    """Coalesce frequent keymap remaps into one delayed persistent save."""

    def __init__(
        self,
        send_ctrl_command: SendCtrl,
        *,
        delay_seconds: float = 20.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self._send_ctrl_command = send_ctrl_command
        self.delay_seconds = delay_seconds
        self._log = logger or log
        self._task: asyncio.Task[None] | None = None

    def schedule(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = asyncio.create_task(self._save_later())

    async def _save_later(self) -> None:
        try:
            await asyncio.sleep(self.delay_seconds)
            await self._save_now()
        except asyncio.CancelledError:
            raise
        except Exception:
            self._log.exception("keymap debounced save failed")

    async def _save_now(self) -> Optional[Dict[str, Any]]:
        resp = await self._send_ctrl_command({"t": "S"})
        if resp is None:
            self._log.warning("keymap debounced save skipped: logicd unavailable")
            return None
        if resp.get("result") != "ok":
            self._log.warning("keymap debounced save failed: %s", resp)
            return resp
        self._log.info("keymap debounced save completed: %s", resp.get("path", ""))
        return resp

    async def flush(self) -> Optional[Dict[str, Any]]:
        task = self._task
        if task is None or task.done():
            return None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self._task = None
        return await self._save_now()

    async def close(self) -> None:
        await self.flush()


def _normalized_active_layers(active: Any) -> dict[str, Any]:
    if not isinstance(active, dict):
        return dict(ACTIVE_LAYER_FALLBACK)
    return {
        **ACTIVE_LAYER_FALLBACK,
        **{key: active[key] for key in ACTIVE_LAYER_FALLBACK if key in active},
    }


async def keymap_active_response(query_active_layers: Callable[[], Awaitable[Optional[Dict[str, Any]]]]) -> web.Response:
    logicd_data = await query_active_layers()
    if logicd_data is None:
        return web.json_response({
            "result": "error",
            "msg": "logicd unavailable",
            "active": dict(ACTIVE_LAYER_FALLBACK),
        }, status=503)
    return web.json_response({
        "result": "ok",
        "active": _normalized_active_layers(logicd_data.get("active")),
    })


async def keymap_set_response(
    request: web.Request,
    send_ctrl_command: SendCtrl,
    schedule_save: ScheduleSave | None = None,
) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"result": "error", "msg": "Invalid JSON"}, status=400)
    layer, row, col, action = body.get("layer"), body.get("row"), body.get("col"), body.get("action")
    if any(v is None for v in [layer, row, col, action]):
        return web.json_response({"result": "error", "msg": "Missing fields"}, status=400)
    action = normalize_keymap_action(action)
    if not is_valid_keymap_action(action):
        return web.json_response({"result": "error", "msg": "Invalid action"}, status=400)
    try:
        layer, row, col = int(layer), int(row), int(col)
    except (ValueError, TypeError):
        return web.json_response({"result": "error", "msg": "Invalid params"}, status=400)
    resp = await send_ctrl_command({"t": "M", "l": layer, "r": row, "c": col, "a": action})
    if resp is None:
        return web.json_response({"result": "error", "msg": "logicd unavailable"}, status=503)
    if resp.get("result") == "ok":
        if schedule_save is not None:
            schedule_save()
            resp = {**resp, "save": "scheduled"}
        else:
            save_resp = await send_ctrl_command({"t": "S"})
            if save_resp is None:
                return web.json_response({"result": "error", "msg": "logicd unavailable during save"}, status=503)
            if save_resp.get("result") != "ok":
                return web.json_response(save_resp, status=500)
            resp = {**resp, "saved": save_resp.get("path", "")}
    log.info("keymap set layer=%d (%d,%d) -> %s : %s", layer, row, col, action, resp.get("result"))
    return web.json_response(resp)


async def keymap_reset_response(request: web.Request, send_ctrl_command: SendCtrl, audit_log: AuditLog) -> web.Response:
    resp = await send_ctrl_command({"t": "RESET_KEYMAP"})
    if resp is None:
        audit_log(request, "keymap_reset", result="error", status=503)
        return web.json_response({"result": "error", "msg": "logicd unavailable"}, status=503)
    status = 200 if resp.get("result") == "ok" else 500
    audit_log(request, "keymap_reset", result=resp.get("result", "unknown"), status=status)
    return web.json_response(resp, status=status)


async def keymap_layer_add_response(request: web.Request, send_ctrl_command: SendCtrl, audit_log: AuditLog) -> web.Response:
    resp = await send_ctrl_command({"t": "LAYER_ADD"})
    if resp is None:
        audit_log(request, "keymap_layer_add", result="error", status=503)
        return web.json_response({"result": "error", "msg": "logicd unavailable"}, status=503)
    audit_log(request, "keymap_layer_add", result=resp.get("result", "unknown"), layer=resp.get("layer", "-"))
    return web.json_response(resp, status=200 if resp.get("result") == "ok" else 500)


async def keymap_layer_clear_response(request: web.Request, send_ctrl_command: SendCtrl, audit_log: AuditLog) -> web.Response:
    try:
        layer = int(request.match_info.get("layer", ""))
    except (TypeError, ValueError):
        return web.json_response({"result": "error", "msg": "invalid layer"}, status=400)
    if layer <= 0:
        return web.json_response({"result": "error", "msg": "layer 0 cannot be deleted"}, status=400)
    if layer >= 32:
        return web.json_response({"result": "error", "msg": "layer out of range"}, status=400)
    resp = await send_ctrl_command({"t": "LAYER_CLEAR", "l": layer})
    if resp is None:
        audit_log(request, "keymap_layer_clear", layer=layer, result="error", status=503)
        return web.json_response({"result": "error", "msg": "logicd unavailable"}, status=503)
    audit_log(request, "keymap_layer_clear", layer=layer, result=resp.get("result", "unknown"))
    return web.json_response(resp, status=200 if resp.get("result") == "ok" else 500)


async def keymap_layer_lock_clear_response(
    request: web.Request,
    send_ctrl_command: SendCtrl,
    audit_log: AuditLog,
) -> web.Response:
    resp = await send_ctrl_command({"t": "LAYER_LOCK_CLEAR"})
    if resp is None:
        audit_log(request, "layer_lock_clear", result="error", status=503)
        return web.json_response({"result": "error", "msg": "logicd unavailable"}, status=503)
    audit_log(
        request,
        "layer_lock_clear",
        result=resp.get("result", "unknown"),
        changed=str(bool(resp.get("changed"))).lower(),
    )
    return web.json_response(resp, status=200 if resp.get("result") == "ok" else 500)
