"""Async socket handlers for logicd."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from .protocol import parse_key_event_packet, parse_matrix_event_packet

log = logging.getLogger(__name__)
_TRACE_LEVEL = 5


async def close_writer(writer: asyncio.StreamWriter) -> None:
    try:
        writer.close()
        await writer.wait_closed()
    except OSError:
        pass


async def handle_matrix_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    queue: asyncio.Queue,
    matrix_in_range: Callable[[int, int], bool],
) -> None:
    peer = writer.get_extra_info("peername") or "<unix>"
    log.info("Client connected: %s", peer)
    try:
        while True:
            pkt = await reader.readexactly(4)
            parsed = parse_matrix_event_packet(pkt)
            if parsed is None:
                log.debug("Bad packet bytes: %r", pkt)
                continue
            kind, row, col = parsed
            if not matrix_in_range(row, col):
                log.warning("matrix event ignored: out-of-range kind=%s row=%d col=%d", kind, row, col)
                continue
            await queue.put((kind, row, col))
            log.debug("Received key event: %s row=%d col=%d", kind, row, col)
    except asyncio.IncompleteReadError:
        pass
    except ConnectionResetError:
        pass
    finally:
        log.info("Client disconnected: %s", peer)
        await close_writer(writer)


async def handle_ctrl_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    process_line: Callable[[str, asyncio.StreamWriter], Awaitable[None]],
) -> None:
    peer = writer.get_extra_info("peername") or "<ctrl>"
    log.log(_TRACE_LEVEL, "Ctrl client connected: %s", peer)
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            await process_line(line.decode(errors="ignore").strip(), writer)
    except asyncio.IncompleteReadError:
        pass
    except ConnectionResetError:
        pass
    finally:
        log.log(_TRACE_LEVEL, "Ctrl client disconnected: %s", peer)
        await close_writer(writer)


async def handle_ledd_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    writers: list,
    send_initial: Callable[[], None],
) -> None:
    peer = writer.get_extra_info("peername") or "<ledd>"
    log.info("ledd client connected: %s", peer)
    writers.append(writer)
    send_initial()
    try:
        await reader.read(1)
    except Exception:
        pass
    finally:
        if writer in writers:
            writers.remove(writer)
        log.info("ledd client disconnected: %s", peer)
        await close_writer(writer)


async def handle_key_event_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    writers: list,
    queue: asyncio.Queue,
) -> None:
    peer = writer.get_extra_info("peername") or "<key_event>"
    log.info("Key event client connected: %s", peer)
    writers.append(writer)
    try:
        while True:
            pkt = await reader.readexactly(4)
            parsed = parse_key_event_packet(pkt)
            if parsed is None:
                log.debug("Bad key event packet: %r", pkt)
                continue
            keycode, modifier, is_press = parsed
            await queue.put((keycode, modifier, is_press))
            log.debug(
                "Received key event: %s keycode=0x%02x modifier=0x%02x",
                "P" if is_press else "R", keycode, modifier,
            )
    except asyncio.IncompleteReadError:
        pass
    except ConnectionResetError:
        pass
    finally:
        if writer in writers:
            writers.remove(writer)
        log.info("Key event client disconnected: %s", peer)
        await close_writer(writer)
