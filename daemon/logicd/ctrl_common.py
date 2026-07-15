"""Shared helpers for logicd ctrl JSON-line handlers."""
from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)


async def ctrl_response(writer: Any, response: dict) -> None:
    if writer is None:
        return
    writer.write((json.dumps(response, ensure_ascii=False) + "\n").encode())
    await writer.drain()


async def ctrl_error(
    writer: Any,
    t: object,
    msg: str,
    *,
    level: int = logging.WARNING,
) -> None:
    log.log(level, "ctrl %r: %s", t, msg)
    if writer is not None:
        await ctrl_response(writer, {"t": t, "result": "error", "msg": msg})


def ctrl_int(msg: dict, key: str, *, default: object = None) -> int:
    raw = msg[key] if default is None else msg.get(key, default)
    return int(raw)


def clamp_with_log(name: str, value: int, lo: int, hi: int, context: str) -> int:
    clamped = max(lo, min(hi, value))
    if clamped != value:
        log.warning("%s clamped: %s=%d -> %d", context, name, value, clamped)
    return clamped
