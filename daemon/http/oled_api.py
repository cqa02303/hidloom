"""HTTP API for persistent OLED icon and Ready-screen customization."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from aiohttp import web

from i2cd.icons import default_icon_payload
from i2cd.oled_customization import (
    READY_ITEM_CATALOG,
    atomic_write_document,
    default_document,
    icon_group_catalog,
    load_effective_document,
    normalize_document,
    reset_document,
)


log = logging.getLogger(__name__)
NotifyI2cd = Callable[[str], Awaitable[dict[str, Any]]]


def _i2cd_settings(i2cd_json: Path) -> tuple[dict[str, int], str]:
    fallback_display = {"width": 64, "height": 128}
    fallback_socket = "/tmp/i2c_events.sock"
    try:
        config = json.loads(i2cd_json.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return fallback_display, fallback_socket
    oled = config.get("oled") if isinstance(config, dict) else None
    ipc = config.get("ipc") if isinstance(config, dict) else None
    if not isinstance(oled, dict):
        oled = {}
    if not isinstance(ipc, dict):
        ipc = {}
    try:
        width = int(oled.get("width", 64))
        height = int(oled.get("height", 128))
    except (TypeError, ValueError):
        width, height = 64, 128
    return {
        "width": max(1, width),
        "height": max(1, height),
    }, str(ipc.get("i2c_socket", fallback_socket))


def oled_get_response(customization_file: Path, i2cd_json: Path) -> web.Response:
    icons = default_icon_payload()
    document, source, errors = load_effective_document(icons, customization_file)
    display, _socket_path = _i2cd_settings(i2cd_json)
    return web.json_response({
        "result": "ok",
        "source": source,
        "errors": errors,
        "display": display,
        "item_catalog": list(READY_ITEM_CATALOG),
        "icon_groups": icon_group_catalog(icons),
        "defaults": default_document(icons),
        "customization": document,
    })


async def _notify_i2cd(socket_path: str) -> dict[str, Any]:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(socket_path),
            timeout=0.75,
        )
        del reader
        writer.write(b'{"t":"oled_config_reload"}\n')
        await asyncio.wait_for(writer.drain(), timeout=0.75)
        writer.close()
        await writer.wait_closed()
        return {"result": "ok", "mode": "socket"}
    except (OSError, asyncio.TimeoutError) as exc:
        return {"result": "deferred", "mode": "periodic-refresh", "error": str(exc)}


async def oled_put_response(
    request: web.Request,
    customization_file: Path,
    i2cd_json: Path,
    *,
    notify_i2cd: NotifyI2cd = _notify_i2cd,
) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"result": "error", "msg": "Invalid JSON"}, status=400)
    try:
        document = normalize_document(body, default_icon_payload())
    except (TypeError, ValueError) as exc:
        return web.json_response({"result": "error", "msg": str(exc)}, status=400)
    try:
        atomic_write_document(customization_file, document)
    except OSError as exc:
        log.warning("OLED customization write failed: %s", exc)
        return web.json_response({"result": "error", "msg": str(exc)}, status=500)
    _display, socket_path = _i2cd_settings(i2cd_json)
    applied = await notify_i2cd(socket_path)
    log.info("OLED customization saved apply=%s", applied.get("result"))
    return web.json_response({
        "result": "ok",
        "source": "runtime",
        "customization": document,
        "apply": applied,
    })


async def oled_reset_response(
    customization_file: Path,
    i2cd_json: Path,
    *,
    notify_i2cd: NotifyI2cd = _notify_i2cd,
) -> web.Response:
    try:
        removed = reset_document(customization_file)
    except OSError as exc:
        log.warning("OLED customization reset failed: %s", exc)
        return web.json_response({"result": "error", "msg": str(exc)}, status=500)
    _display, socket_path = _i2cd_settings(i2cd_json)
    applied = await notify_i2cd(socket_path)
    defaults = default_document(default_icon_payload())
    log.info("OLED customization reset removed=%s apply=%s", removed, applied.get("result"))
    return web.json_response({
        "result": "ok",
        "source": "default",
        "removed": removed,
        "customization": defaults,
        "apply": applied,
    })
