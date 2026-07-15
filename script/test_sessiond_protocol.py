#!/usr/bin/env python3
"""Regression tests for the sessiond JSON-line protocol helpers."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from sessiond.protocol import (  # noqa: E402
    DEFAULT_COLUMNS,
    DEFAULT_ROWS,
    SCHEMA,
    TYPE_PTY_STATUS,
    decode_message,
    default_runtime_options,
    encode_message,
    make_message,
    start_pty_mirror_message,
)


def main() -> None:
    options = default_runtime_options()
    assert options["columns"] == 120
    assert options["rows"] == 35
    assert options["flush_window_ms"] == 50
    assert options["max_flush_rate_fps"] == 20
    assert options["periodic_full_refresh"] is False

    start = start_pty_mirror_message()
    assert start["schema"] == SCHEMA
    assert start["type"] == "start_pty_mirror"
    assert start["source"] == "KC_SH7"
    assert start["command"] == "bash"
    assert start["columns"] == DEFAULT_COLUMNS
    assert start["rows"] == DEFAULT_ROWS

    decoded = decode_message(encode_message(start))
    assert decoded == start

    status = make_message(TYPE_PTY_STATUS, active=False, reason="exit")
    assert decode_message(encode_message(status))["reason"] == "exit"

    for bad in (b"", b"[]\n", b'{"type":"bad"}\n'):
        try:
            decode_message(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid sessiond message should fail: {bad!r}")

    print("ok: sessiond protocol defaults and JSON-line framing")


if __name__ == "__main__":
    main()

