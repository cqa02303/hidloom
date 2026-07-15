"""HTTP Lighting API route handlers."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from aiohttp import web

from lighting import build_lighting_update, lighting_metadata
from matrix_state import normalize_pressed_matrix

log = logging.getLogger(__name__)

SendCtrl = Callable[[Dict[str, Any]], Awaitable[Optional[Dict[str, Any]]]]


async def lighting_get_response(send_ctrl_command: SendCtrl) -> web.Response:
    metadata = lighting_metadata()
    fallback_state = {"mode": 2, "speed": 128, "h": 0, "s": 0, "v": 128}
    resp = await send_ctrl_command({"t": "LED", "op": "vialrgb_get"})
    if resp is None:
        return web.json_response({
            "result": "error",
            "msg": "logicd unavailable",
            **metadata,
            "state": fallback_state,
        }, status=503)
    if resp.get("result") != "ok":
        return web.json_response({**metadata, "state": fallback_state, **resp}, status=502)
    return web.json_response({"result": "ok", **metadata, "state": {
        "mode": resp.get("mode", 2),
        "speed": resp.get("speed", 128),
        "h": resp.get("h", 0),
        "s": resp.get("s", 0),
        "v": resp.get("v", 128),
    }})


async def lighting_set_response(request: web.Request, send_ctrl_command: SendCtrl) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"result": "error", "msg": "Invalid JSON"}, status=400)
    current_resp = await send_ctrl_command({"t": "LED", "op": "vialrgb_get"})
    if current_resp is None:
        return web.json_response({"result": "error", "msg": "logicd unavailable"}, status=503)
    if current_resp.get("result") != "ok":
        return web.json_response(current_resp, status=502)
    try:
        update = build_lighting_update(body, current_resp)
    except (TypeError, ValueError) as exc:
        return web.json_response({"result": "error", "msg": str(exc)}, status=400)
    resp = await send_ctrl_command({"t": "LED", "op": "vialrgb", **update})
    if resp is None:
        return web.json_response({"result": "error", "msg": "logicd unavailable"}, status=503)
    if resp.get("result") != "ok":
        return web.json_response(resp, status=502)
    log.info("lighting set mode=%d speed=%d hsv=(%d,%d,%d)", update["mode"], update["speed"], update["h"], update["s"], update["v"])
    return web.json_response({"result": "ok", "state": update, "save": "scheduled"})


async def lighting_reset_response(send_ctrl_command: SendCtrl) -> web.Response:
    resp = await send_ctrl_command({"t": "LED", "op": "vialrgb_reset"})
    if resp is None:
        return web.json_response({"result": "error", "msg": "logicd unavailable"}, status=503)
    if resp.get("result") != "ok":
        return web.json_response(resp, status=502)
    return web.json_response({"result": "ok", "state": {
        "mode": resp.get("mode", 2),
        "speed": resp.get("speed", 128),
        "h": resp.get("h", 0),
        "s": resp.get("s", 0),
        "v": resp.get("v", 128),
    }})


async def matrix_get_response(send_ctrl_command: SendCtrl) -> web.Response:
    resp = await send_ctrl_command({"t": "K"})
    if resp is None:
        return web.json_response({"result": "error", "msg": "logicd unavailable"}, status=503)
    if resp.get("t") != "matrix":
        return web.json_response({"result": "error", "msg": "unexpected logicd response"}, status=502)
    try:
        pressed = normalize_pressed_matrix(resp.get("pressed", []))
    except (TypeError, ValueError) as exc:
        return web.json_response({"result": "error", "msg": str(exc)}, status=502)
    joystick = resp.get("joystick")
    if not isinstance(joystick, dict):
        joystick = {"schema": "joystick.runtime_status.v1", "sticks": []}
    return web.json_response({"result": "ok", "pressed": pressed, "joystick": joystick})
