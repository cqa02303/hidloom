#!/usr/bin/env python3
"""Regression test for routing keyboard, mouse, and consumer reports to hidg0."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.config_runtime import apply_runtime_config  # noqa: E402
from logicd.state import LogicdRuntime  # noqa: E402


async def _run() -> None:
    opened: list[tuple[str, int]] = []
    writes: list[tuple[int, bytes]] = []

    orig_open = os.open
    orig_write = os.write
    orig_close = os.close
    try:
        os.open = lambda path, flags: opened.append((path, flags)) or len(opened)  # type: ignore[assignment]
        os.write = lambda fd, data: writes.append((fd, bytes(data))) or len(data)  # type: ignore[assignment]
        os.close = lambda _fd: None  # type: ignore[assignment]

        runtime = LogicdRuntime()
        runtime.current_hid_mode = "gadget"
        apply_runtime_config(
            {
                "settings": {
                    "hidg": "/dev/hidg0",
                    "mouse_hidg": "/dev/hidg0",
                    "consumer_hidg": "/dev/hidg0",
                    "console_fallback": False,
                    "outputs": ["auto"],
                },
                "layers": [{}],
                "macros": {},
            },
            runtime,
            default_script_dir="config/default/script",
            fallback_script_dir="config/default/script",
            matrix_in_range=lambda _row, _col: True,
            push_ledd_mode=lambda _mode: None,
            push_i2cd_mode=lambda _mode: None,
            broadcast_key_event=lambda _row, _col, _pressed: None,
            push_i2cd_script_exit=lambda _name, _code: None,
        )
        runtime.current_hid_mode = "gadget"

        # Let async_hid_init run once, then clear its null report.
        await asyncio.sleep(0)
        writes.clear()

        runtime.macros._write(bytes([0, 0, 0x04, 0, 0, 0, 0, 0]))
        runtime.mouse_write_fn(bytes([0x01, 0x02, 0x03, 0x04]))
        runtime.macros._consumer(0x00E9, True)

        assert all(path == "/dev/hidg0" for path, _flags in opened), opened
        assert writes == [
            (1, bytes([0x01, 0, 0, 0x04, 0, 0, 0, 0, 0])),
            (2, bytes([0x02, 0x01, 0x02, 0x03, 0x04])),
            (3, bytes([0x03, 0xE9, 0x00])),
        ]
    finally:
        os.open = orig_open  # type: ignore[assignment]
        os.write = orig_write  # type: ignore[assignment]
        os.close = orig_close  # type: ignore[assignment]


def main() -> None:
    asyncio.run(_run())
    print("ok: logicd routes keyboard, mouse, and consumer reports to hidg0")


if __name__ == "__main__":
    main()
