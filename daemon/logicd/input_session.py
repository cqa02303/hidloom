"""Explicit leased input sessions; raw matrix producers keep their old lifetime."""
from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager

from .input_events import process_matrix_event, _dispatch_interaction_events

_active_sessions = set()
_cleanup_completions = {}
_draining = 0


def invalidate_input_sessions():
    """Stop old owner contexts before a synchronous configuration replacement."""
    for ended in tuple(_active_sessions):
        ended.set()


async def drain_input_sessions(timeout=5.0):
    """Finish old-source output cleanup before replacing the runtime owner."""
    completions = tuple(_cleanup_completions.values())
    invalidate_input_sessions()
    if completions:
        await asyncio.wait_for(asyncio.gather(*(done.wait() for done in completions)), timeout=timeout)
        if any(getattr(done, "cleanup_error", None) for done in completions):
            raise RuntimeError("input source cleanup failed; owner reload was not applied")


@asynccontextmanager
async def quiesce_input_sessions(timeout=5.0):
    """Keep new sources closed through cleanup and owner replacement."""
    global _draining
    _draining += 1
    try:
        await drain_input_sessions(timeout)
        yield
    finally:
        _draining -= 1


async def _reply(writer, result):
    writer.write(json.dumps(result, separators=(",", ":")).encode() + b"\n")
    await writer.drain()


async def handle_source_session(reader, writer, *, context, matrix_in_range, native_socket=None, lease_seconds=30.0):
    """Called only after the first source_open line has been validated."""
    if _draining:
        await _reply(writer, {"t": "source_open", "result": "error", "error": "owner configuration reload in progress"})
        return
    if native_socket:
        upstream = None
        ended = asyncio.Event()
        completed = asyncio.Event()
        _active_sessions.add(ended)
        _cleanup_completions[ended] = completed
        try:
            upstream_reader, upstream = await asyncio.open_unix_connection(native_socket)
            upstream.write(b'{"t":"source_open","protocol":1}\n')
            await upstream.drain()
            async def copy(source, destination):
                while data := await source.read(16384):
                    destination.write(data)
                    await destination.drain()
            tasks = [asyncio.create_task(copy(reader, upstream)), asyncio.create_task(copy(upstream_reader, writer)), asyncio.create_task(ended.wait())]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            try:
                if upstream is not None:
                    upstream.close()
                    await upstream.wait_closed()
            except BaseException as exc:
                completed.cleanup_error = type(exc).__name__
                raise
            finally:
                _active_sessions.discard(ended)
                _cleanup_completions.pop(ended, None)
                completed.set()
        return

    source = "web:" + uuid.uuid4().hex
    ctx = context()
    explicit_close = False
    queue = asyncio.Queue(maxsize=64)
    ended = asyncio.Event()
    completed = asyncio.Event()
    _active_sessions.add(ended)
    _cleanup_completions[ended] = completed
    try:
        await _reply(writer, {"t": "source_open", "result": "ok", "source": source, "owner_epoch": "python", "lease_ms": int(lease_seconds * 1000)})
    except BaseException:
        _active_sessions.discard(ended)
        _cleanup_completions.pop(ended, None)
        completed.set()
        raise

    async def receive():
        nonlocal explicit_close
        try:
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=lease_seconds)
                if not line:
                    break
                msg = json.loads(line)
                current = context()
                if _draining or ended.is_set() or any(getattr(current, field) is not getattr(ctx, field) for field in ("layers", "interactions", "macros")):
                    raise ValueError("source owner context replaced; reconnect required")
                kind = msg.get("t")
                if kind == "source_close":
                    explicit_close = True
                    break
                if kind == "source_ping":
                    await _reply(writer, {"t": kind, "result": "ok"})
                    continue
                if kind != "source_event" or "source" in msg or type(msg.get("is_press")) is not bool:
                    raise ValueError("invalid source session event")
                row, col = msg.get("row"), msg.get("col")
                if type(row) is not int or type(col) is not int or not matrix_in_range(row, col):
                    raise ValueError("source session coordinate out of range")
                queue.put_nowait(("P" if msg["is_press"] else "R", row, col))
                await _reply(writer, {"t": kind, "result": "ok", "state": "accepted"})
        except (OSError, ValueError, asyncio.TimeoutError, asyncio.QueueFull):
            pass
        finally:
            ended.set()

    receiver = asyncio.create_task(receive())
    stopped = asyncio.create_task(ended.wait())
    active = None
    next_event = None
    try:
        while not ended.is_set():
            next_event = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait((next_event, stopped), return_when=asyncio.FIRST_COMPLETED)
            if stopped in done:
                next_event.cancel()
                await asyncio.gather(next_event, return_exceptions=True)
                break
            active = asyncio.create_task(process_matrix_event(next_event.result(), ctx, owner=source))
            done, _ = await asyncio.wait((active, stopped), return_when=asyncio.FIRST_COMPLETED)
            if stopped in done:
                active.cancel()
                await asyncio.gather(active, return_exceptions=True)
                active = None
                break
            await active
            active = None
    finally:
        receiver.cancel()
        stopped.cancel()
        if active is not None:
            active.cancel()
        if next_event is not None:
            next_event.cancel()
        await asyncio.gather(receiver, stopped, *([active] if active is not None else []),
            *([next_event] if next_event is not None else []), return_exceptions=True)
        try:
            cancel_output = getattr(ctx.macros, "cancel_output_source", None)
            if cancel_output:
                cancel_output(source)
            events = ctx.interactions.clear_owner(source)
            ctx.pressed_matrix_owners.pop(source, None)
            await _dispatch_interaction_events(events, ctx)
        except BaseException as exc:
            completed.cleanup_error = type(exc).__name__
            raise
        finally:
            _active_sessions.discard(ended)
            _cleanup_completions.pop(ended, None)
            completed.set()
    if explicit_close and not writer.is_closing():
        await _reply(writer, {"t": "source_close", "result": "ok"})
