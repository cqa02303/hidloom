#!/usr/bin/env python3
"""Regression tests for synthetic tap output timing."""
from __future__ import annotations

import asyncio
import time
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.hid_report import HidState  # noqa: E402
from logicd import input_events  # noqa: E402
from logicd.input_events import InputEventContext, process_matrix_event  # noqa: E402
from logicd.interaction_engine import InteractionEngine  # noqa: E402
from logicd.key_event_pipeline import output_processor  # noqa: E402
from logicd.keymap import LayerManager  # noqa: E402
from logicd.macro import MacroExecutor  # noqa: E402


class EmptyEncoders:
    def handles(self, row: int, col: int) -> bool:
        return False


class RecordingMacros:
    def __init__(self) -> None:
        self.events: list[tuple[str, bool, float]] = []

    async def handle(self, action: str, is_press: bool) -> None:
        self.events.append((action, is_press, time.monotonic()))


async def test_lt_tap_reaches_output_before_release() -> None:
    layers = LayerManager()
    layers.load([{"0,0": "LT(1,KC_1)"}, {"0,0": "KC_A"}])
    reports: list[bytes] = []
    state = HidState()
    queue: asyncio.Queue = asyncio.Queue()
    macros = MacroExecutor(
        state,
        reports.append,
        {},
        key_event_broadcast=lambda _code, _mod, _press: queue.put_nowait(None),
    )
    ctx = InputEventContext(
        layers=layers,
        interactions=InteractionEngine(layers),
        macros=macros,
        encoders=EmptyEncoders(),
        joysticks=SimpleNamespace(process=lambda *_args: None),
        pressed_matrix=set(),
        push_ledd_key_event=lambda *_args: None,
        push_ledd_status=lambda: None,
        push_i2cd_status=lambda: None,
        push_i2cd_alert=lambda *_args: None,
        push_ledd_anim=lambda *_args: None,
        apply_lighting_key_action=lambda *_args: False,
        mouse_write_fn=lambda _report: None,
        bt_manager=None,
    )
    task = asyncio.create_task(output_processor(SimpleNamespace(
        key_event_queue=queue,
        state=state,
        macros=macros,
    )))
    try:
        start = time.monotonic()
        await process_matrix_event(("P", 0, 0), ctx)
        await process_matrix_event(("R", 0, 0), ctx)
        elapsed = time.monotonic() - start
        await queue.join()
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    assert reports.count(bytes.fromhex("00001e0000000000")) >= 1
    assert reports[-1] == bytes(8)
    assert elapsed >= 0.018


async def test_interrupted_mod_tap_gaps_modifier_before_next_key() -> None:
    original_gap = input_events._INTERACTION_PRESS_PRESS_GAP_SEC
    input_events._INTERACTION_PRESS_PRESS_GAP_SEC = 0.060
    layers = LayerManager()
    layers.load([{"0,0": "MT(KC_LSFT,KC_A)", "0,1": "KC_Q"}])
    macros = RecordingMacros()
    try:
        ctx = InputEventContext(
            layers=layers,
            interactions=InteractionEngine(layers),
            macros=macros,
            encoders=EmptyEncoders(),
            joysticks=SimpleNamespace(process=lambda *_args: None),
            pressed_matrix=set(),
            push_ledd_key_event=lambda *_args: None,
            push_ledd_status=lambda: None,
            push_i2cd_status=lambda: None,
            push_i2cd_alert=lambda *_args: None,
            push_ledd_anim=lambda *_args: None,
            apply_lighting_key_action=lambda *_args: False,
            mouse_write_fn=lambda _report: None,
            bt_manager=None,
        )

        await process_matrix_event(("P", 0, 0), ctx)
        await process_matrix_event(("P", 0, 1), ctx)

        assert [(action, press) for action, press, _ts in macros.events] == [
            ("KC_LSFT", True),
            ("KC_Q", True),
        ]
        assert macros.events[1][2] - macros.events[0][2] >= 0.045
    finally:
        input_events._INTERACTION_PRESS_PRESS_GAP_SEC = original_gap


async def test_duplicate_matrix_edges_are_ignored() -> None:
    layers = LayerManager()
    layers.load([{"0,0": "LT(1,KC_1)"}, {"0,0": "KC_A"}])
    reports: list[bytes] = []
    state = HidState()
    queue: asyncio.Queue = asyncio.Queue()
    macros = MacroExecutor(
        state,
        reports.append,
        {},
        key_event_broadcast=lambda _code, _mod, _press: queue.put_nowait(None),
    )
    ctx = InputEventContext(
        layers=layers,
        interactions=InteractionEngine(layers),
        macros=macros,
        encoders=EmptyEncoders(),
        joysticks=SimpleNamespace(process=lambda *_args: None),
        pressed_matrix=set(),
        push_ledd_key_event=lambda *_args: None,
        push_ledd_status=lambda: None,
        push_i2cd_status=lambda: None,
        push_i2cd_alert=lambda *_args: None,
        push_ledd_anim=lambda *_args: None,
        apply_lighting_key_action=lambda *_args: False,
        mouse_write_fn=lambda _report: None,
        bt_manager=None,
    )
    task = asyncio.create_task(output_processor(SimpleNamespace(
        key_event_queue=queue,
        state=state,
        macros=macros,
    )))
    try:
        await process_matrix_event(("P", 0, 0), ctx)
        await process_matrix_event(("P", 0, 0), ctx)
        await process_matrix_event(("R", 0, 0), ctx)
        await process_matrix_event(("R", 0, 0), ctx)
        await queue.join()
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    assert reports.count(bytes.fromhex("00001e0000000000")) >= 1
    assert reports[-1] == bytes(8)
    assert ctx.pressed_matrix == set()
    assert ctx.interactions.pressed == {}


async def test_mouse_button_matrix_press_holds_until_release() -> None:
    layers = LayerManager()
    layers.load([{"0,0": "KC_BTN1", "0,1": "MS_BTN5"}])
    keyboard_reports: list[bytes] = []
    mouse_reports: list[bytes] = []
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
        joysticks=SimpleNamespace(process=lambda *_args: None),
        pressed_matrix=set(),
        push_ledd_key_event=lambda *_args: None,
        push_ledd_status=lambda: None,
        push_i2cd_status=lambda: None,
        push_i2cd_alert=lambda *_args: None,
        push_ledd_anim=lambda *_args: None,
        apply_lighting_key_action=lambda *_args: False,
        mouse_write_fn=lambda _report: None,
        bt_manager=None,
    )

    await process_matrix_event(("P", 0, 0), ctx)
    assert mouse_reports == [bytes([0x01, 0, 0, 0])]
    assert ctx.pressed_matrix == {(0, 0)}
    assert keyboard_reports == []

    await process_matrix_event(("P", 0, 1), ctx)
    assert mouse_reports[-1] == bytes([0x11, 0, 0, 0])
    assert ctx.pressed_matrix == {(0, 0), (0, 1)}

    await process_matrix_event(("R", 0, 0), ctx)
    assert mouse_reports[-1] == bytes([0x10, 0, 0, 0])
    assert ctx.pressed_matrix == {(0, 1)}

    await process_matrix_event(("R", 0, 1), ctx)
    assert mouse_reports[-1] == bytes([0, 0, 0, 0])
    assert ctx.pressed_matrix == set()


async def test_delegate_keyboard_actions_return_to_core_hook() -> None:
    layers = LayerManager()
    layers.load([{"0,0": "KC_A", "0,1": "KC_BTN1"}])
    macros = RecordingMacros()
    core_events: list[tuple[str, bool, tuple[int, int] | None, str | None]] = []
    ctx = InputEventContext(
        layers=layers,
        interactions=InteractionEngine(layers),
        macros=macros,
        encoders=EmptyEncoders(),
        joysticks=SimpleNamespace(process=lambda *_args: None),
        pressed_matrix=set(),
        push_ledd_key_event=lambda *_args: None,
        push_ledd_status=lambda: None,
        push_i2cd_status=lambda: None,
        push_i2cd_alert=lambda *_args: None,
        push_ledd_anim=lambda *_args: None,
        apply_lighting_key_action=lambda *_args: False,
        mouse_write_fn=lambda _report: None,
        bt_manager=None,
        core_key_event_fn=lambda action, press, matrix_key, source: core_events.append(
            (action, press, matrix_key, source)
        ),
    )

    await process_matrix_event(("P", 0, 0), ctx)
    await process_matrix_event(("R", 0, 0), ctx)
    assert core_events == [
        ("KC_A", True, (0, 0), "matrix"),
        ("KC_A", False, (0, 0), "matrix"),
    ]
    assert macros.events == []

    await process_matrix_event(("P", 0, 1), ctx)
    assert macros.events[0][:2] == ("KC_BTN1", True)


async def test_lt_tap_returns_tap_key_to_core_hook() -> None:
    layers = LayerManager()
    layers.load([{"0,0": "LT(1,KC_1)"}, {"0,1": "KC_A"}])
    macros = RecordingMacros()
    core_events: list[tuple[str, bool, tuple[int, int] | None, str | None]] = []
    ctx = InputEventContext(
        layers=layers,
        interactions=InteractionEngine(layers),
        macros=macros,
        encoders=EmptyEncoders(),
        joysticks=SimpleNamespace(process=lambda *_args: None),
        pressed_matrix=set(),
        push_ledd_key_event=lambda *_args: None,
        push_ledd_status=lambda: None,
        push_i2cd_status=lambda: None,
        push_i2cd_alert=lambda *_args: None,
        push_ledd_anim=lambda *_args: None,
        apply_lighting_key_action=lambda *_args: False,
        mouse_write_fn=lambda _report: None,
        bt_manager=None,
        core_key_event_fn=lambda action, press, matrix_key, source: core_events.append(
            (action, press, matrix_key, source)
        ),
    )

    await process_matrix_event(("P", 0, 0), ctx)
    await process_matrix_event(("R", 0, 0), ctx)

    assert core_events == [
        ("KC_1", True, (0, 0), "matrix"),
        ("KC_1", False, (0, 0), "matrix"),
    ]
    assert macros.events == []


async def test_lt_hold_routes_layer_key_to_core_hook_without_direct_output() -> None:
    layers = LayerManager()
    layers.load([{"0,0": "LT(1,KC_1)", "0,1": "KC_Q"}, {"0,1": "KC_A"}])
    macros = RecordingMacros()
    core_events: list[tuple[str, bool, tuple[int, int] | None, str | None]] = []
    ctx = InputEventContext(
        layers=layers,
        interactions=InteractionEngine(layers),
        macros=macros,
        encoders=EmptyEncoders(),
        joysticks=SimpleNamespace(process=lambda *_args: None),
        pressed_matrix=set(),
        push_ledd_key_event=lambda *_args: None,
        push_ledd_status=lambda: None,
        push_i2cd_status=lambda: None,
        push_i2cd_alert=lambda *_args: None,
        push_ledd_anim=lambda *_args: None,
        apply_lighting_key_action=lambda *_args: False,
        mouse_write_fn=lambda _report: None,
        bt_manager=None,
        core_key_event_fn=lambda action, press, matrix_key, source: core_events.append(
            (action, press, matrix_key, source)
        ),
    )

    await process_matrix_event(("P", 0, 0), ctx)
    await process_matrix_event(("P", 0, 1), ctx)
    await process_matrix_event(("R", 0, 1), ctx)
    await process_matrix_event(("R", 0, 0), ctx)

    assert core_events == [
        ("KC_A", True, (0, 1), "matrix"),
        ("KC_A", False, (0, 1), "matrix"),
    ]
    assert macros.events == []
    assert layers.active_snapshot()["all"] == [0]


async def test_interrupted_mod_tap_returns_modifier_and_key_to_core_hook() -> None:
    original_gap = input_events._INTERACTION_PRESS_PRESS_GAP_SEC
    input_events._INTERACTION_PRESS_PRESS_GAP_SEC = 0.060
    layers = LayerManager()
    layers.load([{"0,0": "MT(KC_LSFT,KC_A)", "0,1": "KC_Q"}])
    macros = RecordingMacros()
    core_events: list[tuple[str, bool, tuple[int, int] | None, str | None, float]] = []
    try:
        ctx = InputEventContext(
            layers=layers,
            interactions=InteractionEngine(layers),
            macros=macros,
            encoders=EmptyEncoders(),
            joysticks=SimpleNamespace(process=lambda *_args: None),
            pressed_matrix=set(),
            push_ledd_key_event=lambda *_args: None,
            push_ledd_status=lambda: None,
            push_i2cd_status=lambda: None,
            push_i2cd_alert=lambda *_args: None,
            push_ledd_anim=lambda *_args: None,
            apply_lighting_key_action=lambda *_args: False,
            mouse_write_fn=lambda _report: None,
            bt_manager=None,
            core_key_event_fn=lambda action, press, matrix_key, source: core_events.append(
                (action, press, matrix_key, source, time.monotonic())
            ),
        )

        await process_matrix_event(("P", 0, 0), ctx)
        await process_matrix_event(("P", 0, 1), ctx)

        assert [(action, press, matrix_key, source) for action, press, matrix_key, source, _ts in core_events] == [
            ("KC_LSFT", True, (0, 0), "matrix"),
            ("KC_Q", True, (0, 1), "matrix"),
        ]
        assert core_events[1][4] - core_events[0][4] >= 0.045
        assert macros.events == []
    finally:
        input_events._INTERACTION_PRESS_PRESS_GAP_SEC = original_gap


def test_invalid_layers_are_not_reported_active() -> None:
    layers = LayerManager()
    layers.load([{"0,0": "KC_A"}, {"0,0": "KC_B"}])
    layers.toggle(2)
    assert layers.active_snapshot()["all"] == [0]
    layers.momentary_on(1)
    assert layers.active_snapshot()["all"] == [1, 0]


def main() -> None:
    asyncio.run(test_lt_tap_reaches_output_before_release())
    asyncio.run(test_interrupted_mod_tap_gaps_modifier_before_next_key())
    asyncio.run(test_duplicate_matrix_edges_are_ignored())
    asyncio.run(test_mouse_button_matrix_press_holds_until_release())
    asyncio.run(test_delegate_keyboard_actions_return_to_core_hook())
    asyncio.run(test_lt_tap_returns_tap_key_to_core_hook())
    asyncio.run(test_lt_hold_routes_layer_key_to_core_hook_without_direct_output())
    asyncio.run(test_interrupted_mod_tap_returns_modifier_and_key_to_core_hook())
    test_invalid_layers_are_not_reported_active()
    print("ok: synthetic tap output timing")


if __name__ == "__main__":
    main()
