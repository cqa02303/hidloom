#!/usr/bin/env python3
"""Local regression tests for analog joystick handling."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd import config_loader, logicd  # noqa: E402
from logicd.hid_report import HidState  # noqa: E402
from logicd.input_events import InputEventContext, handle_analog_stick, process_matrix_event  # noqa: E402
from logicd.interaction_engine import InteractionEngine  # noqa: E402
from logicd.joystick import JoystickBinding, JoystickManager  # noqa: E402
from logicd.keymap import LayerManager  # noqa: E402
from logicd.macro import MacroExecutor  # noqa: E402


class EmptyEncoders:
    def handles(self, row: int, col: int) -> bool:
        return False


def _binding() -> JoystickBinding:
    return JoystickBinding(
        name="stick0",
        up=(0, 0),
        left=(1, 1),
        right=(2, 2),
        down=(3, 3),
    )


def test_config_loader_extracts_stick() -> None:
    cfg = config_loader.load()
    sticks = cfg.get("joysticks", [])
    assert sticks
    assert sticks[0]["up"] == [0, 0]
    assert sticks[0]["left"] == [1, 1]
    assert sticks[0]["right"] == [2, 2]
    assert sticks[0]["down"] == [3, 3]


def test_threshold_key_press_release() -> None:
    manager = JoystickManager([_binding()])
    actions = {
        (0, 0): "KC_UP",
        (1, 1): "KC_LEFT",
        (2, 2): "KC_RGHT",
        (3, 3): "KC_DOWN",
    }
    resolver = lambda row, col: actions[(row, col)]

    result = manager.process(0, 60, 0, resolver)
    assert [(e.direction, e.action, e.is_press) for e in result.key_events] == [
        ("right", "KC_RGHT", True)
    ]
    assert result.mouse_event is None

    result = manager.process(0, 10, 0, resolver)
    assert [(e.direction, e.action, e.is_press) for e in result.key_events] == [
        ("right", "KC_RGHT", False)
    ]


def test_release_uses_pressed_action() -> None:
    manager = JoystickManager([_binding()])
    current = {"action": "KC_A"}

    def resolver(row: int, col: int) -> str:
        return current["action"] if (row, col) == (2, 2) else "KC_NONE"

    result = manager.process(0, 60, 0, resolver)
    assert [(e.action, e.is_press) for e in result.key_events] == [("KC_A", True)]

    current["action"] = "KC_B"
    result = manager.process(0, 0, 0, resolver)
    assert [(e.action, e.is_press) for e in result.key_events] == [("KC_A", False)]


def test_mouse_action_uses_analog_amount() -> None:
    manager = JoystickManager([_binding()])

    def resolver(row: int, col: int) -> str:
        return "KC_MS_R" if (row, col) == (2, 2) else "KC_NONE"

    result = manager.process(0, 100, 0, resolver)
    assert result.key_events == []
    assert result.mouse_event is not None
    assert result.mouse_event.dx > 0
    assert result.mouse_event.dy == 0
    assert result.mouse_event.wheel == 0


def test_status_reports_active_direction() -> None:
    manager = JoystickManager([_binding()])
    actions = {
        (0, 0): "KC_UP",
        (1, 1): "KC_LEFT",
        (2, 2): "KC_MS_R",
        (3, 3): "KC_DOWN",
    }
    resolver = lambda row, col: actions[(row, col)]

    manager.process(0, 20, -60, resolver)
    status = manager.status(resolver)

    assert status["schema"] == "joystick.runtime_status.v1"
    stick = status["sticks"][0]
    assert stick["x"] == 20
    assert stick["y"] == -60
    directions = {item["direction"]: item for item in stick["directions"]}
    assert directions["up"]["active"] is True
    assert directions["up"]["held"] is True
    assert directions["right"]["active"] is True
    assert directions["right"]["held"] is False
    assert directions["right"]["action"] == "KC_MS_R"


async def test_logicd_ctrl_integration() -> None:
    calls: list[tuple[str, bool]] = []
    mouse_reports: list[bytes] = []
    led_events: list[tuple[int, int, bool]] = []

    class FakeMacros:
        async def handle(self, action: str, is_press: bool) -> None:
            calls.append((action, is_press))

    layers = LayerManager()
    layers.load([{
        "0,0": "KC_UP",
        "1,1": "KC_MS_L",
        "2,2": "KC_MS_R",
        "3,3": "KC_DOWN",
    }])

    logicd._runtime.layers = layers  # type: ignore[attr-defined]
    logicd._runtime.joysticks = JoystickManager([_binding()])  # type: ignore[attr-defined]
    logicd._runtime.macros = FakeMacros()  # type: ignore[attr-defined]
    logicd._runtime.mouse_write_fn = lambda report: mouse_reports.append(report)  # type: ignore[attr-defined]
    logicd._push_ledd_key_event = lambda row, col, press: led_events.append((row, col, press))  # type: ignore[assignment]

    await logicd._process_ctrl_json('{"t":"A","x":0,"y":-80}')  # type: ignore[attr-defined]
    await logicd._process_ctrl_json('{"t":"A","x":0,"y":0}')  # type: ignore[attr-defined]
    await logicd._process_ctrl_json('{"t":"A","x":80,"y":0}')  # type: ignore[attr-defined]

    assert calls == [("KC_UP", True), ("KC_UP", False)]
    assert led_events == [(0, 0, True), (0, 0, False)]
    assert mouse_reports


async def test_stick_mouse_motion_preserves_held_button() -> None:
    keyboard_reports: list[bytes] = []
    mouse_reports: list[bytes] = []
    layers = LayerManager()
    layers.load([{
        "0,0": "KC_BTN1",
        "2,2": "KC_MS_R",
    }])
    macros = MacroExecutor(
        HidState(),
        keyboard_reports.append,
        {},
        mouse_write_fn=mouse_reports.append,
    )
    ctx = InputEventContext(
        layers=layers,
        interactions=InteractionEngine(layers),
        macros=macros,
        encoders=EmptyEncoders(),
        joysticks=JoystickManager([_binding()]),
        pressed_matrix=set(),
        push_ledd_key_event=lambda *_args: None,
        push_ledd_status=lambda: None,
        push_i2cd_status=lambda: None,
        push_i2cd_alert=lambda *_args: None,
        push_ledd_anim=lambda *_args: None,
        apply_lighting_key_action=lambda *_args: False,
        mouse_write_fn=mouse_reports.append,
        bt_manager=None,
    )

    await process_matrix_event(("P", 0, 0), ctx)
    assert mouse_reports[-1] == bytes([0x01, 0, 0, 0])

    await handle_analog_stick(0, 80, 0, ctx)
    assert mouse_reports[-1][0] == 0x01
    assert mouse_reports[-1][1] > 0

    await process_matrix_event(("R", 0, 0), ctx)
    assert mouse_reports[-1] == bytes([0, 0, 0, 0])


def main() -> None:
    test_config_loader_extracts_stick()
    test_threshold_key_press_release()
    test_release_uses_pressed_action()
    test_mouse_action_uses_analog_amount()
    test_status_reports_active_direction()
    asyncio.run(test_logicd_ctrl_integration())
    asyncio.run(test_stick_mouse_motion_preserves_held_button())
    print("ok: analog joystick handling is coherent")


if __name__ == "__main__":
    main()
