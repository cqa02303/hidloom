"""JSON-line protocol helpers for sessiond M0."""
from __future__ import annotations

import json
from typing import Any, Final

DEFAULT_SESSIOND_SOCKET: Final[str] = "/tmp/sessiond.sock"

SCHEMA: Final[str] = "sessiond.protocol.v1"

TYPE_START_PTY_MIRROR: Final[str] = "start_pty_mirror"
TYPE_STOP_PTY_MIRROR: Final[str] = "stop_pty_mirror"
TYPE_PTY_KEY_INPUT: Final[str] = "pty_key_input"
TYPE_POLL_PTY_OUTPUT: Final[str] = "poll_pty_output"
TYPE_WATCH_PTY_OUTPUT: Final[str] = "watch_pty_output"
TYPE_PTY_TEXT_STREAM: Final[str] = "pty_text_stream"
TYPE_PTY_STATUS: Final[str] = "pty_status"

MESSAGE_TYPES: Final[frozenset[str]] = frozenset({
    TYPE_START_PTY_MIRROR,
    TYPE_STOP_PTY_MIRROR,
    TYPE_PTY_KEY_INPUT,
    TYPE_POLL_PTY_OUTPUT,
    TYPE_WATCH_PTY_OUTPUT,
    TYPE_PTY_TEXT_STREAM,
    TYPE_PTY_STATUS,
})

DEFAULT_COLUMNS: Final[int] = 120
DEFAULT_ROWS: Final[int] = 35
DEFAULT_FLUSH_WINDOW_MS: Final[int] = 50
DEFAULT_MAX_FLUSH_RATE_FPS: Final[int] = 20
DEFAULT_KEY_TAP_HOLD_MS: Final[int] = 6
DEFAULT_ASCII_TAP_GAP_MS: Final[int] = 20
DEFAULT_ESC_CHUNK_GAP_MS: Final[int] = 50
DEFAULT_MAX_QUEUED_ROW_UPDATES: Final[int] = DEFAULT_ROWS


def default_runtime_options() -> dict[str, Any]:
    """Return M0 defaults chosen for the first PTY mirror smoke."""
    return {
        "columns": DEFAULT_COLUMNS,
        "rows": DEFAULT_ROWS,
        "flush_window_ms": DEFAULT_FLUSH_WINDOW_MS,
        "max_flush_rate_fps": DEFAULT_MAX_FLUSH_RATE_FPS,
        "key_tap_hold_ms": DEFAULT_KEY_TAP_HOLD_MS,
        "ascii_tap_gap_ms": DEFAULT_ASCII_TAP_GAP_MS,
        "esc_chunk_gap_ms": DEFAULT_ESC_CHUNK_GAP_MS,
        "max_queued_row_updates": DEFAULT_MAX_QUEUED_ROW_UPDATES,
        "idle_timeout_sec": None,
        "startup_full_refresh": True,
        "periodic_full_refresh": False,
    }


def make_message(message_type: str, **fields: Any) -> dict[str, Any]:
    if message_type not in MESSAGE_TYPES:
        raise ValueError(f"unsupported sessiond message type: {message_type!r}")
    return {"schema": SCHEMA, "type": message_type, **fields}


def encode_message(message: dict[str, Any]) -> bytes:
    message_type = message.get("type")
    if message_type not in MESSAGE_TYPES:
        raise ValueError(f"unsupported sessiond message type: {message_type!r}")
    payload = dict(message)
    payload.setdefault("schema", SCHEMA)
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def decode_message(line: bytes | str) -> dict[str, Any]:
    raw = line.decode("utf-8") if isinstance(line, bytes) else line
    raw = raw.strip()
    if not raw:
        raise ValueError("empty sessiond message")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid sessiond JSON message") from exc
    if not isinstance(payload, dict):
        raise ValueError("sessiond message must be a JSON object")
    if payload.get("schema") not in (None, SCHEMA):
        raise ValueError(f"unsupported sessiond schema: {payload.get('schema')!r}")
    message_type = payload.get("type")
    if message_type not in MESSAGE_TYPES:
        raise ValueError(f"unsupported sessiond message type: {message_type!r}")
    payload["schema"] = SCHEMA
    return payload


def start_pty_mirror_message(
    *,
    command: str = "bash",
    columns: int = DEFAULT_COLUMNS,
    rows: int = DEFAULT_ROWS,
    source: str = "KC_SH7",
) -> dict[str, Any]:
    return make_message(
        TYPE_START_PTY_MIRROR,
        command=command,
        columns=columns,
        rows=rows,
        source=source,
        options=default_runtime_options(),
    )


def pty_status_message(active: bool, *, reason: str = "", rows: int = DEFAULT_ROWS, columns: int = DEFAULT_COLUMNS) -> dict[str, Any]:
    return make_message(
        TYPE_PTY_STATUS,
        active=bool(active),
        reason=reason,
        rows=rows,
        columns=columns,
    )

