#!/usr/bin/env python3
"""Regression test for key-driven Mouse HID acceleration profiles."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.hid_report import HidState, MouseState  # noqa: E402
from logicd.macro import MacroExecutor  # noqa: E402


async def _capture_move_after_profile(profile_action: str, movement_action: str) -> bytes:
    reports: list[bytes] = []
    executor = MacroExecutor(
        HidState(),
        lambda _report: None,
        {},
        mouse_write_fn=reports.append,
    )

    await executor.handle(profile_action, True)
    await executor.handle(movement_action, True)
    await asyncio.sleep(0.02)
    await executor.handle(movement_action, False)
    assert reports, (profile_action, movement_action)
    return reports[0]


async def _capture_button_reports(action: str) -> list[bytes]:
    reports: list[bytes] = []
    executor = MacroExecutor(
        HidState(),
        lambda _report: None,
        {},
        mouse_write_fn=reports.append,
    )

    await executor.handle(action, True)
    await executor.handle(action, False)
    return reports


def main() -> None:
    assert MouseState.move_delta(0x20B) == (5, 0, 0)
    assert MouseState.move_delta(0x20B, move_step=12, wheel_step=6) == (12, 0, 0)
    assert MouseState.move_delta(0x20C, move_step=12, wheel_step=6) == (0, 0, 6)
    assert MouseState.merge_buttons(bytes([0, 7, 0, 0]), 0x03) == bytes([0x03, 7, 0, 0])
    assert MouseState.merge_buttons(bytes([0x10, 7, 0, 0]), 0x03) == bytes([0x13, 7, 0, 0])

    slow_right = asyncio.run(_capture_move_after_profile("MS_ACL0", "KC_MS_R"))
    assert slow_right[:4] == bytes([0, 2, 0, 0])

    fast_right = asyncio.run(_capture_move_after_profile("MS_ACL2", "KC_MS_R"))
    assert fast_right[:4] == bytes([0, 12, 0, 0])

    fast_wheel = asyncio.run(_capture_move_after_profile("MS_ACL2", "KC_WH_U"))
    assert fast_wheel[:4] == bytes([0, 0, 0, 6])

    btn1 = asyncio.run(_capture_button_reports("MS_BTN1"))
    assert btn1 == [bytes([0x01, 0, 0, 0]), bytes([0, 0, 0, 0])]

    btn5 = asyncio.run(_capture_button_reports("MS_BTN5"))
    assert btn5 == [bytes([0x10, 0, 0, 0]), bytes([0, 0, 0, 0])]

    print("ok: Mouse HID acceleration profiles affect key-driven movement")


if __name__ == "__main__":
    main()
