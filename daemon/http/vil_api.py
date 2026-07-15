"""HTTP .vil import/export route handlers."""
from __future__ import annotations

import json
import logging
import socket
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from aiohttp import web

from layout_api import current_keymap_layers
from vil_apply import apply_vil_interaction_settings, apply_vil_macro_settings, apply_vil_remaps
from vil_layout import (
    HIDLOOM_EXPORT_WARNINGS_KEY,
    build_vil_from_files,
    encode_vil,
    parse_vil_from_files,
)
from vil_macro_import import apply_vial_macro_buffer
from vil_response import attachment_content_disposition, safe_header_filename_part

log = logging.getLogger(__name__)

SendCtrl = Callable[[Dict[str, Any]], Awaitable[Optional[Dict[str, Any]]]]
QueryLayers = Callable[[], Awaitable[Optional[Dict[str, Any]]]]
AuditLog = Callable[..., None]


async def vil_export_response(
    *,
    query_logicd_layers: QueryLayers,
    vial_json: Path,
    keymap_json: Path,
    config_json: Path,
) -> web.Response:
    layers = await current_keymap_layers(query_logicd_layers)
    document = build_vil_from_files(vial_json=vial_json, keymap_json=keymap_json, layers=layers, config_json=config_json)
    payload = encode_vil(document)
    try:
        uid = json.loads(vial_json.read_text(encoding="utf-8")).get("uid", "layout")
    except (OSError, json.JSONDecodeError):
        uid = "layout"
    hostname = safe_header_filename_part(socket.gethostname(), "cqa02303v5")
    uid_text = safe_header_filename_part(uid, "layout")
    filename = f"{hostname}-{uid_text}.vil"
    export_warnings = document.get("settings", {}).get(HIDLOOM_EXPORT_WARNINGS_KEY, [])
    return web.Response(
        body=payload,
        content_type="application/json",
        headers={
            "Content-Disposition": attachment_content_disposition(filename),
            "X-HIDLOOM-VIL-Warnings": str(len(export_warnings) if isinstance(export_warnings, list) else 0),
        },
    )


async def vil_import_response(
    request: web.Request,
    *,
    send_ctrl_command: SendCtrl,
    vial_json: Path,
    keymap_json: Path,
    config_json: Path,
    audit_log: AuditLog,
) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"result": "error", "msg": "Invalid JSON"}, status=400)
    content = body.get("content")
    if not isinstance(content, str):
        return web.json_response({"result": "error", "msg": "Missing content"}, status=400)
    force_uid = bool(body.get("force_uid"))
    try:
        plan = parse_vil_from_files(content, vial_json=vial_json, keymap_json=keymap_json, force_uid=force_uid)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return web.json_response({"result": "error", "msg": str(exc)}, status=400)
    if plan.uid_mismatch and not force_uid:
        return web.json_response({"result": "uid_mismatch", "uid": plan.uid, "msg": "uid differs from this keyboard"}, status=409)

    applied, error_response = await apply_vil_remaps(plan.remaps, send_ctrl_command)
    if error_response is not None:
        return error_response

    interaction_applied = False
    if plan.interaction_settings is not None:
        error_response = await apply_vil_interaction_settings(
            plan.interaction_settings,
            config_json=config_json,
            vial_json=vial_json,
        )
        if error_response is not None:
            return error_response
        interaction_applied = True

    macro_applied = False
    if plan.vial_macro_buffer is not None:
        error_response = await apply_vil_macro_settings(config_json, plan.vial_macro_buffer)
        if error_response is not None:
            return error_response
        macro_applied = True

    log.info("vil import applied %d remaps (warnings=%d)", applied, len(plan.warnings))
    audit_log(
        request,
        "vil_import",
        result="ok",
        applied=applied,
        interaction_applied=interaction_applied,
        macro_applied=macro_applied,
        warnings=len(plan.warnings),
    )
    return web.json_response({
        "result": "ok",
        "applied": applied,
        "interaction_applied": interaction_applied,
        "macro_applied": macro_applied,
        "warnings": plan.warnings,
        "uid": plan.uid,
        "uid_mismatch": plan.uid_mismatch,
    })
