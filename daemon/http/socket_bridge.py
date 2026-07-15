from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Awaitable, Callable, Dict, Optional

from aiohttp import web


async def get_sock_writer(
    current_writer: Optional[asyncio.StreamWriter],
    *,
    socket_path: str,
    log,
) -> Optional[asyncio.StreamWriter]:
    if current_writer is not None and not current_writer.is_closing():
        return current_writer
    if not os.path.exists(socket_path):
        log.warning("matrix_events.sock not found: %s", socket_path)
        return None
    try:
        _, writer = await asyncio.open_unix_connection(socket_path)
        log.info("Connected to %s", socket_path)
        return writer
    except OSError as exc:
        log.warning("Cannot connect to matrix_events.sock: %s", exc)
        return None


async def send_key_event(
    event_str: str,
    *,
    writer: Optional[asyncio.StreamWriter],
    get_writer: Callable[[], Awaitable[Optional[asyncio.StreamWriter]]],
    clear_writer: Callable[[], None],
    log,
) -> None:
    writer = writer if writer is not None and not writer.is_closing() else await get_writer()
    if writer is None:
        log.debug("drop event (no sock): %s", event_str.strip())
        return
    try:
        writer.write(event_str.encode())
        if writer.transport.get_write_buffer_size() > 256:
            await writer.drain()
    except OSError as exc:
        log.warning("Write to sock failed: %s", exc)
        clear_writer()


async def send_ctrl_command(
    cmd: Dict[str, Any],
    *,
    socket_path: str,
    timeout: float = 2.0,
    log,
) -> Optional[Dict[str, Any]]:
    if not os.path.exists(socket_path):
        log.debug("ctrl_events.sock not found: %s", socket_path)
        return None
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(socket_path), timeout=timeout)
        try:
            writer.write(json.dumps(cmd).encode() + b"\n")
            await asyncio.wait_for(writer.drain(), timeout=timeout)
            line = await asyncio.wait_for(reader.readline(), timeout=timeout)
            return json.loads(line.decode())
        finally:
            writer.close()
    except asyncio.TimeoutError:
        log.warning("ctrl command timeout: %r", cmd)
    except OSError as exc:
        log.warning("ctrl command error: %s", exc)
    except json.JSONDecodeError as exc:
        log.warning("ctrl command invalid response: %s", exc)
    return None


async def query_logicd_layers(
    send_ctrl: Callable[[Dict[str, Any]], Awaitable[Optional[Dict[str, Any]]]],
    *,
    log,
) -> Optional[Dict[str, Any]]:
    data = await send_ctrl({"t": "G"})
    if data is not None and data.get("t") == "keymap":
        return data
    if data is not None:
        log.warning("ctrl G: unexpected response type: %r", data.get("t"))
    return None


async def query_logicd_active_layers(
    send_ctrl: Callable[[Dict[str, Any]], Awaitable[Optional[Dict[str, Any]]]],
    *,
    log,
) -> Optional[Dict[str, Any]]:
    data = await send_ctrl({"t": "ACTIVE"})
    if data is not None and data.get("t") == "active":
        return data
    if data is not None:
        log.warning("ctrl ACTIVE: unexpected response type: %r", data.get("t"))
    return None


async def process_ws_message(
    raw: str,
    *,
    send_key_event_func: Callable[[str], Awaitable[None]],
    log,
) -> None:
    if len(raw) == 3 and raw[0] in {"P", "R"}:
        try:
            row_i = int(raw[1], 16)
            col_i = int(raw[2], 16)
        except ValueError:
            log.debug("Invalid compact WS matrix event: %s", raw)
            return
        await send_key_event_func(f"{raw[0]}{row_i:X}{col_i:X}\n")
        return

    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        log.debug("Invalid WS message: %s", raw)
        return
    event_type = msg.get("type", "")
    row = msg.get("row")
    col = msg.get("col")
    if row is None or col is None:
        return
    try:
        row_i, col_i = int(row), int(col)
    except (TypeError, ValueError):
        log.debug("Invalid WS matrix position: row=%r col=%r", row, col)
        return
    if not (0 <= row_i <= 15 and 0 <= col_i <= 15):
        log.debug("Out-of-range WS matrix position: row=%r col=%r", row, col)
        return
    prefix = "P" if event_type == "keydown" else "R"
    await send_key_event_func(f"{prefix}{row_i:X}{col_i:X}\n")


async def handle_ws_response(
    request: web.Request,
    *,
    ws_clients: set[web.WebSocketResponse],
    process_message: Callable[[str], Awaitable[None]],
    log,
) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    ws_clients.add(ws)
    log.info("WS connected from %s", request.remote)
    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                await process_message(msg.data)
            elif msg.type == web.WSMsgType.ERROR:
                log.warning("WS error: %s", ws.exception())
    finally:
        ws_clients.discard(ws)
        log.info("WS disconnected from %s", request.remote)
    return ws
