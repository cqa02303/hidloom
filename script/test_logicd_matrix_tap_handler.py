#!/usr/bin/env python3
"""Regression checks for logicd matrix tap intake."""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))

from logicd import logicd  # noqa: E402


class FakeWriter:
    def __init__(self) -> None:
        self.closed = False

    def get_extra_info(self, name: str) -> str | None:
        return "<test-tap>" if name == "peername" else None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


async def _run() -> None:
    calls: list[tuple[int, int, bool]] = []
    old_push = logicd._push_ledd_key_event
    try:
        logicd._require_runtime().observed_pressed_matrix.clear()

        def record_ledd_key_event(row: int, col: int, is_press: bool) -> None:
            calls.append((row, col, is_press))

        logicd._push_ledd_key_event = record_ledd_key_event  # type: ignore[assignment]
        reader = asyncio.StreamReader()
        reader.feed_data(b"P12\nP34\nR12\n")
        reader.feed_eof()
        writer = FakeWriter()

        await logicd._handle_matrix_tap_client(reader, writer)  # type: ignore[arg-type]

        assert calls == [(1, 2, True), (3, 4, True)]
        assert logicd._require_runtime().observed_pressed_matrix == {(3, 4)}
        assert logicd._matrix_status_pressed() == {(3, 4)}
        assert writer.closed
    finally:
        logicd._push_ledd_key_event = old_push  # type: ignore[assignment]
        logicd._require_runtime().observed_pressed_matrix.clear()


def main() -> None:
    asyncio.run(_run())
    print("ok: logicd matrix tap handler")


if __name__ == "__main__":
    main()
