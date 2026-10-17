from __future__ import annotations

import asyncio
import contextlib
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
            log.debug("Invalid compact WS matrix event")
            return
        await send_key_event_func(f"{raw[0]}{row_i:X}{col_i:X}\n")
        return

    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        log.debug("Invalid WS message")
        return
    if not isinstance(msg, dict):
        return
    event_type = msg.get("type", "")
    if event_type not in {"keydown", "keyup"}:
        return
    row = msg.get("row")
    col = msg.get("col")
    if row is None or col is None:
        return
    try:
        row_i, col_i = int(row), int(col)
    except (TypeError, ValueError):
        log.debug("Invalid WS matrix position")
        return
    if not (0 <= row_i <= 15 and 0 <= col_i <= 15):
        log.debug("Out-of-range WS matrix position")
        return
    prefix = "P" if event_type == "keydown" else "R"
    await send_key_event_func(f"{prefix}{row_i:X}{col_i:X}\n")


class InputSourceSession:
    """One acknowledged input source; uncertainty always terminates the stream."""

    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self.closed = asyncio.Event()
        self.pending = None
        self.lock = asyncio.Lock()
        self.reader_task = asyncio.create_task(self._read_responses())
        self.lease_seconds = 30.0

    @classmethod
    async def open(cls, path):
        reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(path, limit=65536), 2)
        session = cls(reader, writer)
        try:
            response = await session.request({"t": "source_open", "protocol": 1})
            lease = response.get("lease_ms")
            source = response.get("source")
            valid_source = (isinstance(source, str) and bool(source)) or (type(source) is int and source > 0)
            if (not valid_source
                    or not isinstance(response.get("owner_epoch"), str) or not response["owner_epoch"]
                    or isinstance(lease, bool) or not isinstance(lease, int) or not 3000 <= lease <= 300000):
                raise ConnectionError("invalid source session acknowledgement")
            session.lease_seconds = lease / 1000
            return session
        except BaseException:
            await session.close(notify=False)
            raise

    async def _read_responses(self):
        try:
            while line := await self.reader.readline():
                response = json.loads(line)
                pending = self.pending
                if pending is None or pending.done() or not isinstance(response, dict):
                    raise ConnectionError("unexpected source response")
                pending.set_result(response)
        except (OSError, ValueError):
            pass
        finally:
            self.closed.set()
            if self.pending is not None and not self.pending.done():
                self.pending.set_exception(ConnectionError("input source disconnected"))
            self.writer.close()

    async def request(self, value):
        async with asyncio.timeout(2):
            async with self.lock:
                if self.closed.is_set():
                    raise ConnectionError("input source disconnected")
                self.pending = asyncio.get_running_loop().create_future()
                try:
                    self.writer.write(json.dumps(value, separators=(",", ":")).encode() + b"\n")
                    await self.writer.drain()
                    response = await self.pending
                    if response.get("result") != "ok" or response.get("ok") is False:
                        raise ConnectionError("input source rejected operation")
                    return response
                finally:
                    self.pending = None

    async def send_event(self, compact):
        await self.request({"t": "source_event", "row": int(compact[1], 16),
                            "col": int(compact[2], 16), "is_press": compact[0] == "P"})

    async def maintain(self, ws):
        try:
            while not self.closed.is_set():
                try:
                    await asyncio.wait_for(self.closed.wait(), self.lease_seconds / 3)
                except asyncio.TimeoutError:
                    await self.request({"t": "source_ping"})
            await ws.close(code=1011, message=b"input source disconnected")
        except (OSError, asyncio.TimeoutError):
            await ws.close(code=1011, message=b"input source unavailable")

    async def close(self, notify=True):
        if notify and not self.closed.is_set():
            with contextlib.suppress(OSError, asyncio.TimeoutError):
                await self.request({"t": "source_close"})
        self.writer.close()
        with contextlib.suppress(OSError, asyncio.TimeoutError):
            await asyncio.wait_for(self.writer.wait_closed(), 2)
        self.reader_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.reader_task


async def handle_ws_response(
    request: web.Request,
    *,
    ws_clients: set[web.WebSocketResponse],
    process_message: Callable[[str], Awaitable[None]],
    log,
    source_socket_path: Optional[str] = None,
) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    ws_clients.add(ws)
    log.info("WS connected from %s", request.remote)
    session = None
    maintainer = None
    try:
        if source_socket_path is not None:
            session = await InputSourceSession.open(source_socket_path)
            maintainer = asyncio.create_task(session.maintain(ws))
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                if session is None:
                    await process_message(msg.data)
                else:
                    await process_ws_message(msg.data, send_key_event_func=session.send_event, log=log)
            elif msg.type == web.WSMsgType.ERROR:
                log.warning("WS error: %s", ws.exception())
    except (OSError, asyncio.TimeoutError):
        log.warning("WS input source unavailable; closing without replay")
        await ws.close(code=1011, message=b"input source unavailable")
    finally:
        if maintainer is not None:
            maintainer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await maintainer
        if session is not None:
            await session.close()
        ws_clients.discard(ws)
        log.info("WS disconnected from %s", request.remote)
    return ws
