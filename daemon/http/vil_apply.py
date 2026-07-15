"""Apply helpers for HTTP .vil import routes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, Sequence

from aiohttp import web

from interaction_api import reload_logicd_service, save_interaction_settings
from vil_macro_import import apply_vial_macro_buffer

SendCtrl = Callable[[Dict[str, Any]], Awaitable[Optional[Dict[str, Any]]]]


async def apply_vil_remaps(remaps: Sequence[object], send_ctrl_command: SendCtrl) -> tuple[int, web.Response | None]:
    applied = 0
    for remap in remaps:
        resp = await send_ctrl_command({
            "t": "M",
            "l": getattr(remap, "layer"),
            "r": getattr(remap, "row"),
            "c": getattr(remap, "col"),
            "a": getattr(remap, "action"),
        })
        if resp is None:
            return applied, web.json_response({"result": "error", "msg": "logicd unavailable"}, status=503)
        if resp.get("result") != "ok":
            return applied, web.json_response({"result": "error", "msg": resp.get("msg", "remap failed")}, status=502)
        applied += 1
    resp = await send_ctrl_command({"t": "S"})
    if resp is None:
        return applied, web.json_response({"result": "error", "msg": "logicd unavailable"}, status=503)
    if resp.get("result") != "ok":
        return applied, web.json_response({"result": "error", "msg": resp.get("msg", "save failed")}, status=502)
    return applied, None


async def apply_vil_interaction_settings(
    interaction_settings: object,
    *,
    config_json: Path,
    vial_json: Path,
) -> web.Response | None:
    try:
        save_interaction_settings(config_json, vial_json, interaction_settings)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return web.json_response({"result": "error", "msg": f"interaction import failed: {exc}"}, status=500)
    reload_result = await reload_logicd_service()
    if reload_result.get("result") != "ok":
        return web.json_response({"result": "error", "msg": "logicd reload failed", "reload": reload_result}, status=502)
    return None


async def apply_vil_macro_settings(config_json: Path, vial_macro_buffer: object) -> web.Response | None:
    try:
        apply_vial_macro_buffer(config_json, vial_macro_buffer)
    except ValueError as exc:
        return web.json_response({"result": "error", "msg": str(exc)}, status=400)
    except RuntimeError as exc:
        return web.json_response({"result": "error", "msg": str(exc)}, status=500)
    reload_result = await reload_logicd_service()
    if reload_result.get("result") != "ok":
        return web.json_response({"result": "error", "msg": "logicd reload failed", "reload": reload_result}, status=502)
    return None
