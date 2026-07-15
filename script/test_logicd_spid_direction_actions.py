#!/usr/bin/env python3
"""Regression tests for dispatching spid virtual direction taps."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.input_events import InputEventContext  # noqa: E402
from logicd.spid_direction import SpidDirectionResult, SpidDirectionTap  # noqa: E402
from logicd.spid_direction_actions import dispatch_spid_direction_result, dispatch_spid_direction_tap  # noqa: E402


class DummyLayers:
    def active_snapshot(self):
        return [0]

    def set_momentary(self, layer: int, enabled: bool) -> None:
        return None

    def toggle(self, layer: int) -> None:
        return None

    def to_layer(self, layer: int) -> None:
        return None

    def set_default(self, layer: int) -> None:
        return None


class RecordingMacros:
    def __init__(self) -> None:
        self.events: list[tuple[str, bool]] = []

    async def handle(self, action: str, is_press: bool) -> None:
        self.events.append((action, is_press))


def make_context() -> tuple[InputEventContext, RecordingMacros, list[tuple[int, int, bool]]]:
    macros = RecordingMacros()
    ledd_events: list[tuple[int, int, bool]] = []
    return (
        InputEventContext(
            layers=DummyLayers(),
            interactions=None,
            macros=macros,
            encoders=None,
            joysticks=None,
            pressed_matrix=set(),
            push_ledd_key_event=lambda row, col, is_press: ledd_events.append((row, col, is_press)),
            push_ledd_status=lambda: None,
            push_i2cd_status=lambda: None,
            push_i2cd_alert=lambda message, sec: None,
            push_ledd_anim=lambda anim_id: None,
            apply_lighting_key_action=lambda action, is_press: False,
            mouse_write_fn=lambda report: None,
            bt_manager=None,
            wifi_manager=None,
        ),
        macros,
        ledd_events,
    )


async def main_async() -> None:
    ctx, macros, ledd_events = make_context()
    tap = SpidDirectionTap(name="ball", direction="right", row=1, col=3, action="KC_A", taps=2)
    stats = await dispatch_spid_direction_tap(tap, ctx, hold_sec=0.0, gap_sec=0.0)
    assert stats.tap_events == 2
    assert stats.action_events == 4
    assert ledd_events == [(1, 3, True), (1, 3, False), (1, 3, True), (1, 3, False)]
    assert macros.events == [("KC_A", True), ("KC_A", False), ("KC_A", True), ("KC_A", False)]

    ctx2, macros2, _ = make_context()
    result = SpidDirectionResult(
        taps=[
            SpidDirectionTap(name="ball", direction="up", row=1, col=0, action="KC_UP", taps=1),
            SpidDirectionTap(name="ball", direction="down", row=1, col=1, action="KC_DOWN", taps=1),
        ],
        dropped_taps=3,
    )
    stats2 = await dispatch_spid_direction_result(result, ctx2, hold_sec=0.0, gap_sec=0.0)
    assert stats2.tap_events == 2
    assert stats2.action_events == 4
    assert stats2.dropped_taps == 3
    assert macros2.events == [("KC_UP", True), ("KC_UP", False), ("KC_DOWN", True), ("KC_DOWN", False)]

    print("ok: logicd spid direction actions")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
