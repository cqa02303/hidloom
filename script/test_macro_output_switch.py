#!/usr/bin/env python3
"""Regression tests for output target key actions handled by MacroExecutor."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.hid_report import HidState  # noqa: E402
from logicd.macro import MacroExecutor  # noqa: E402


class OutputSwitchRecorder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, report: bytes) -> None:
        self.calls.append(report.hex())

    def force_auto(self) -> None:
        self.calls.append("force_auto")

    def force_uinput(self) -> None:
        self.calls.append("force_uinput")

    def force_gadget(self) -> None:
        self.calls.append("force_gadget")

    def force_bt(self) -> None:
        self.calls.append("force_bt")


async def main_async() -> None:
    writer = OutputSwitchRecorder()
    executor = MacroExecutor(HidState(), writer, {})

    await executor.handle("KC_CONNAUTO", True)
    await executor.handle("KC_CONSOLE", True)
    await executor.handle("KC_USB", True)
    await executor.handle("KC_BT", True)
    await executor.handle("KC_BT", False)

    assert writer.calls == ["force_auto", "force_uinput", "force_gadget", "force_bt"]
    print("ok: macro output switch actions")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
