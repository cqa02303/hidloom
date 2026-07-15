#!/usr/bin/env python3
"""Regression tests for Key Override suppression clear boundaries."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.input_events import InputEventContext, process_matrix_event  # noqa: E402
from logicd.interaction_engine import InteractionEngine, ResolvedActionEvent  # noqa: E402
from logicd.keymap import LayerManager  # noqa: E402


class FakeMacros:
    def __init__(self) -> None:
        self.events: list[tuple[str, bool]] = []

    async def handle(self, action: str, is_press: bool) -> None:
        self.events.append((action, is_press))


class FakeEncoders:
    def handles(self, row: int, col: int) -> bool:
        return False


class FakeJoysticks:
    pass


def resolved(events: list[ResolvedActionEvent]) -> list[tuple[str, bool, str]]:
    return [(event.action, event.is_press, event.source) for event in events]


def make_layers() -> LayerManager:
    layers = LayerManager()
    layers.load([{
        "0,0": "KC_LSFT",
        "0,1": "KC_1",
        "0,2": "KC_USB",
    }])
    return layers


def make_engine(layers: LayerManager) -> InteractionEngine:
    return InteractionEngine(
        layers,
        key_overrides=[{"trigger": "KC_LSFT", "key": "KC_1", "replacement": "KC_ESC"}],
    )


def make_ctx(layers: LayerManager, engine: InteractionEngine, macros: FakeMacros) -> InputEventContext:
    return InputEventContext(
        layers=layers,
        interactions=engine,
        macros=macros,
        encoders=FakeEncoders(),
        joysticks=FakeJoysticks(),
        pressed_matrix=set(),
        push_ledd_key_event=lambda row, col, is_press: None,
        push_ledd_status=lambda: None,
        push_i2cd_status=lambda: None,
        push_i2cd_alert=lambda *args, **kwargs: None,
        push_ledd_anim=lambda anim: None,
        apply_lighting_key_action=lambda action, is_press: False,
        mouse_write_fn=lambda report: None,
    )


async def test_output_switch_releases_override_replacement_without_restore() -> None:
    layers = make_layers()
    engine = make_engine(layers)
    macros = FakeMacros()
    ctx = make_ctx(layers, engine, macros)

    await process_matrix_event(("P", 0, 0), ctx)
    await process_matrix_event(("P", 0, 1), ctx)
    assert macros.events == [("KC_LSFT", True), ("KC_LSFT", False), ("KC_ESC", True)]

    await process_matrix_event(("P", 0, 2), ctx)
    assert macros.events[-2:] == [("KC_ESC", False), ("KC_USB", True)]
    assert set(engine.pressed) == {(0, 2)}

    await process_matrix_event(("R", 0, 1), ctx)
    await process_matrix_event(("R", 0, 0), ctx)
    assert macros.events[-2:] == [("KC_ESC", False), ("KC_USB", True)]


def test_clear_held_keys_does_not_restore_suppressed_trigger() -> None:
    layers = make_layers()
    engine = make_engine(layers)

    assert resolved(engine.on_key(0, 0, True, 1.000)) == [("KC_LSFT", True, "matrix")]
    assert resolved(engine.on_key(0, 1, True, 1.010)) == [
        ("KC_LSFT", False, "key_override"),
        ("KC_ESC", True, "matrix"),
    ]
    assert resolved(engine.clear_held_keys(reason="emergency_release")) == [
        ("KC_ESC", False, "emergency_release"),
    ]
    assert engine.pressed == {}
    assert engine.on_key(0, 1, False, 1.020) == []
    assert engine.on_key(0, 0, False, 1.030) == []


def test_reset_clears_override_suppression_state_without_restore() -> None:
    layers = make_layers()
    engine = make_engine(layers)

    engine.on_key(0, 0, True, 2.000)
    engine.on_key(0, 1, True, 2.010)
    assert engine.pressed
    engine.reset()
    assert engine.pressed == {}
    assert engine.on_key(0, 1, False, 2.020) == []
    assert engine.on_key(0, 0, False, 2.030) == []


def main() -> None:
    asyncio.run(test_output_switch_releases_override_replacement_without_restore())
    test_clear_held_keys_does_not_restore_suppressed_trigger()
    test_reset_clears_override_suppression_state_without_restore()
    print("ok: Key Override suppression clear boundaries")


if __name__ == "__main__":
    main()
