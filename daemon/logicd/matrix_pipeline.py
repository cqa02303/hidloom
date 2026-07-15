"""Matrix event socket and processing pipeline for logicd."""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

from .input_events import InputEventContext, process_interaction_tick, process_matrix_event
from .sockets import handle_matrix_client as socket_handle_matrix_client
from .state import LogicdRuntime

log = logging.getLogger(__name__)


def _next_interaction_timeout(runtime: LogicdRuntime) -> float | None:
    """Return queue wait timeout for the next interaction deadline."""
    due = runtime.interactions.next_timer_due()
    if due is None:
        return None
    return max(0.0, due - time.monotonic())


async def handle_matrix_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    runtime: LogicdRuntime,
    matrix_in_range: Callable[[int, int], bool],
) -> None:
    await socket_handle_matrix_client(
        reader,
        writer,
        queue=runtime.queue,
        matrix_in_range=matrix_in_range,
    )


async def event_processor(
    runtime: LogicdRuntime,
    input_event_context: Callable[[], InputEventContext],
) -> None:
    while True:
        timeout = _next_interaction_timeout(runtime)
        if timeout == 0.0:
            try:
                await process_interaction_tick(input_event_context())
            except Exception:
                log.exception("Error processing interaction tick")
            continue
        try:
            if timeout is None:
                event = await runtime.queue.get()
            else:
                event = await asyncio.wait_for(runtime.queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                await process_interaction_tick(input_event_context())
            except Exception:
                log.exception("Error processing interaction tick")
            continue
        try:
            await process_matrix_event(event, input_event_context())
        except Exception:
            log.exception("Error processing event %r", event)
        finally:
            runtime.queue.task_done()
