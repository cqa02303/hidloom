#!/usr/bin/env python3
"""Local smoke test for media key aliases routed to Consumer Control."""
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


async def main() -> None:
    consumer_events: list[tuple[int, bool]] = []
    key_events: list[tuple[int, int, bool]] = []
    writes: list[bytes] = []

    executor = MacroExecutor(
        HidState(),
        lambda report: writes.append(bytes(report)),
        {},
        consumer_write_fn=lambda usage, pressed: consumer_events.append((usage, pressed)),
        key_event_broadcast=lambda keycode, modifier, pressed: key_events.append((keycode, modifier, pressed)),
    )

    expected = {
        "KC_KB_MUTE": 0x00E2,
        "KC_KB_VOLUME_UP": 0x00E9,
        "KC_KB_VOLUME_DOWN": 0x00EA,
        "KC_MUTE": 0x00E2,
        "KC_VOLU": 0x00E9,
        "KC_VOLD": 0x00EA,
        "KC_MNXT": 0x00B5,
        "KC_MPRV": 0x00B6,
        "KC_MSTP": 0x00B7,
        "KC_MPLY": 0x00CD,
        "KC_MFFD": 0x00B3,
        "KC_MRWD": 0x00B4,
        "KC_BRIU": 0x006F,
        "KC_BRID": 0x0070,
    }
    for action, usage in expected.items():
        await executor.handle(action, True)
        await executor.handle(action, False)
        assert consumer_events[-2:] == [(usage, True), (usage, False)], action

    assert key_events == []
    assert writes == []
    print("ok: KB media aliases are routed to Consumer Control")


if __name__ == "__main__":
    asyncio.run(main())
