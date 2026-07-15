"""Confirmed key event socket and output pipeline for logicd."""
from __future__ import annotations

import asyncio

from .output import process_key_event_output
from .sockets import handle_key_event_client as socket_handle_key_event_client
from .state import LogicdRuntime


async def handle_key_event_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    runtime: LogicdRuntime,
) -> None:
    await socket_handle_key_event_client(
        reader,
        writer,
        writers=runtime.key_event_writers,
        queue=runtime.key_event_queue,
    )


async def output_processor(runtime: LogicdRuntime) -> None:
    """Write confirmed key events to the active HID/uinput backend."""
    await process_key_event_output(
        runtime.key_event_queue,
        runtime.state,
        lambda: runtime.macros._write,
    )
