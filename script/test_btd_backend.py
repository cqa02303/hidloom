#!/usr/bin/env python3
"""Regression tests for btd backend helpers."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from btd.backend import LoggingBackend  # noqa: E402
from btd.protocol import null_keyboard_report, parse_raw_consumer_report, parse_raw_keyboard_report, parse_raw_mouse_report  # noqa: E402


class CaptureLoggingBackend(LoggingBackend):
    def __init__(self, send_null_on_stop: bool = True) -> None:
        super().__init__(send_null_on_stop=send_null_on_stop)
        self.sent: list[str] = []

    async def send_keyboard_report(self, report):  # type: ignore[override]
        self.sent.append(f"keyboard:{report.hex}")
        await super().send_keyboard_report(report)

    async def send_mouse_report(self, report):  # type: ignore[override]
        self.sent.append(f"mouse:{report.hex}")
        await super().send_mouse_report(report)

    async def send_consumer_report(self, report):  # type: ignore[override]
        self.sent.append(f"consumer:{report.hex}")
        await super().send_consumer_report(report)


async def main_async() -> None:
    backend = CaptureLoggingBackend(send_null_on_stop=True)
    await backend.start()
    await backend.send_keyboard_report(parse_raw_keyboard_report(bytes.fromhex("0000040000000000")))
    await backend.send_mouse_report(parse_raw_mouse_report(bytes.fromhex("00010200")))
    await backend.send_consumer_report(parse_raw_consumer_report(bytes.fromhex("e900")))
    await backend.stop()
    assert backend.sent == [
        "keyboard:0000040000000000",
        "mouse:00010200",
        "consumer:e900",
        "keyboard:0000000000000000",
        "mouse:00000000",
        "consumer:0000",
    ]

    backend_no_null = CaptureLoggingBackend(send_null_on_stop=False)
    await backend_no_null.start()
    await backend_no_null.stop()
    assert backend_no_null.sent == []

    assert null_keyboard_report().hex == "0000000000000000"
    print("ok: btd backend helpers")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
