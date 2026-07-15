"""Socket notification payload helpers for logicd status sinks."""
from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)


def broadcast_json(writers: list, payload: dict[str, Any]) -> None:
    data = (json.dumps(payload) + "\n").encode()
    dead = []
    for writer in writers:
        try:
            writer.write(data)
        except Exception:
            dead.append(writer)
    for writer in dead:
        writers.remove(writer)


def write_json(writer: Any, payload: dict[str, Any], *, on_error: str) -> bool:
    if writer is None:
        return False
    try:
        writer.write((json.dumps(payload) + "\n").encode())
        return True
    except Exception:
        log.warning("%s", on_error)
        return False


def layer_payload(momentary: set[int], toggled: set[int], default_layer: int = 0) -> dict[str, Any]:
    active = sorted(momentary | toggled | {default_layer, 0}, reverse=True)
    return {
        "t": "layer",
        "layer": active[0],
        "active": active,
    }
