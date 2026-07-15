"""HTTP handler and route registration for temporary LED role preview.

This module keeps the low-frequency role-preview route out of httpd.py.
It does not save VialRGB settings or edit persistent LED config.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Optional

from aiohttp import web

from led_role_preview import build_role_preview_frame
from lighting import build_lighting_update

SendCtrlCommand = Callable[[Dict[str, Any]], Awaitable[Optional[Dict[str, Any]]]]
ROLE_PREVIEW_ROUTE = "/api/lighting/role-preview"


def _state_from_response(resp: Dict[str, Any]) -> dict[str, int]:
    return {
        "mode": int(resp.get("mode", 2)),
        "speed": int(resp.get("speed", 128)),
        "h": int(resp.get("h", 0)),
        "s": int(resp.get("s", 0)),
        "v": int(resp.get("v", 128)),
    }


async def _restore_lighting(send_ctrl_command: SendCtrlCommand, body: Dict[str, Any]) -> web.Response:
    state = body.get("state")
    if not isinstance(state, dict):
        return web.json_response({"result": "error", "msg": "restore requires state object"}, status=400)
    try:
        update = build_lighting_update(state, {"mode": 2, "speed": 128, "h": 0, "s": 0, "v": 128})
    except (TypeError, ValueError) as exc:
        return web.json_response({"result": "error", "msg": str(exc)}, status=400)
    resp = await send_ctrl_command({"t": "LED", "op": "vialrgb", "save": False, **update})
    if resp is None:
        return web.json_response({"result": "error", "msg": "logicd unavailable"}, status=503)
    if resp.get("result") != "ok":
        return web.json_response(resp, status=502)
    return web.json_response({"result": "ok", "action": "restore", "state": update})


async def _preview_roles(send_ctrl_command: SendCtrlCommand, body: Dict[str, Any]) -> web.Response:
    current_resp = await send_ctrl_command({"t": "LED", "op": "vialrgb_get"})
    if current_resp is None:
        return web.json_response({"result": "error", "msg": "logicd unavailable"}, status=503)
    if current_resp.get("result") != "ok":
        return web.json_response(current_resp, status=502)
    try:
        brightness = int(body.get("brightness", 96))
        frame = build_role_preview_frame(brightness=brightness)
    except (OSError, ValueError, TypeError) as exc:
        return web.json_response({"result": "error", "msg": str(exc)}, status=400)
    pixels = frame["pixels"]
    resp = await send_ctrl_command({"t": "LED", "op": "vialrgb_direct", "first": 0, "pixels": pixels})
    if resp is None:
        return web.json_response({"result": "error", "msg": "logicd unavailable"}, status=503)
    if resp.get("result") != "ok":
        return web.json_response(resp, status=502)
    return web.json_response({
        "result": "ok",
        "action": "preview",
        "restore_state": _state_from_response(current_resp),
        "count": frame["count"],
        "counts": frame["counts"],
    })


def make_lighting_role_preview_handler(send_ctrl_command: SendCtrlCommand):
    async def handle_lighting_role_preview(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"result": "error", "msg": "Invalid JSON"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"result": "error", "msg": "Invalid JSON"}, status=400)
        action = str(body.get("action", "preview")).strip().lower()
        if action == "preview":
            return await _preview_roles(send_ctrl_command, body)
        if action == "restore":
            return await _restore_lighting(send_ctrl_command, body)
        return web.json_response({"result": "error", "msg": f"unknown action: {action}"}, status=400)

    return handle_lighting_role_preview


def register_lighting_role_preview_route(app: web.Application, send_ctrl_command: SendCtrlCommand) -> None:
    """Register the low-frequency role-preview route without growing httpd.py.

    Keeping the route wiring here lets httpd.py stay focused on app assembly.
    """
    app.router.add_post(ROLE_PREVIEW_ROUTE, make_lighting_role_preview_handler(send_ctrl_command))
