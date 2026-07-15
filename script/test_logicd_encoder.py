#!/usr/bin/env python3
"""Local regression tests for matrix-backed rotary encoder handling."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd import config_loader  # noqa: E402
from logicd.encoder import EncoderBinding, EncoderEvent, EncoderManager  # noqa: E402
from logicd.input_events import InputEventContext, process_matrix_event  # noqa: E402
from logicd.keymap import LayerManager  # noqa: E402


def test_decoder() -> None:
    manager = EncoderManager([EncoderBinding(name="SW91", a=(7, 1), b=(6, 1))])
    assert manager.handles(7, 1)
    assert manager.handles(6, 1)

    sequence = [
        (6, 1, True),   # 00 -> 01
        (7, 1, True),   # 01 -> 11
        (6, 1, False),  # 11 -> 10
        (7, 1, False),  # 10 -> 00
    ]
    result = None
    for row, col, is_press in sequence:
        result = manager.process(row, col, is_press)
    assert isinstance(result, EncoderEvent)
    assert result.direction == "cw"
    assert (result.row, result.col) == (7, 1)

    sequence = [
        (7, 1, True),   # 00 -> 10
        (6, 1, True),   # 10 -> 11
        (7, 1, False),  # 11 -> 01
        (6, 1, False),  # 01 -> 00
    ]
    result = None
    for row, col, is_press in sequence:
        result = manager.process(row, col, is_press)
    assert isinstance(result, EncoderEvent)
    assert result.direction == "ccw"
    assert (result.row, result.col) == (6, 1)


async def test_logicd_integration() -> None:
    calls: list[tuple[str, bool]] = []
    led_events: list[tuple[int, int, bool]] = []

    class FakeMacros:
        async def handle(self, action: str, is_press: bool) -> None:
            calls.append((action, is_press))

    layers = LayerManager()
    layers.load([{"7,1": "KC_WH_U", "6,1": "KC_WH_D"}])

    ctx = InputEventContext(
        layers=layers,
        interactions=None,
        macros=FakeMacros(),
        encoders=EncoderManager([EncoderBinding(name="SW91", a=(7, 1), b=(6, 1))]),
        joysticks=None,
        pressed_matrix=set(),
        push_ledd_key_event=lambda row, col, press: led_events.append((row, col, press)),
        push_ledd_status=lambda: None,
        push_i2cd_status=lambda: None,
        push_i2cd_alert=lambda _msg, _sec=2.0: None,
        push_ledd_anim=lambda _anim_id: None,
        apply_lighting_key_action=lambda _action, _is_press: False,
        mouse_write_fn=lambda _report: None,
    )

    for event in (("P", 6, 1), ("P", 7, 1), ("R", 6, 1), ("R", 7, 1)):
        await process_matrix_event(event, ctx)

    assert calls == [("KC_WH_U", True), ("KC_WH_U", False)]
    assert led_events == [(7, 1, True), (7, 1, False)]


def test_config_loader_extracts_sw91() -> None:
    cfg = config_loader.load()
    assert any(item.get("name") == "SW91" and item.get("a") == [7, 1] and item.get("b") == [6, 1]
               for item in cfg.get("encoders", []))


def main() -> None:
    test_decoder()
    asyncio.run(test_logicd_integration())
    test_config_loader_extracts_sw91()
    print("ok: matrix-backed encoder decoding is coherent")


if __name__ == "__main__":
    main()
