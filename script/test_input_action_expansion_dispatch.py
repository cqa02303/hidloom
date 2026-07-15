#!/usr/bin/env python3
"""Regression tests for action expansion in the input dispatch pipeline."""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

import logicd.input_events as input_events  # noqa: E402
from logicd.input_events import InputEventContext, dispatch_action_event  # noqa: E402
from logicd.host_led_output import HostLedOutputConfig  # noqa: E402
from logicd.keymap import LayerManager  # noqa: E402


class FakeMacros:
    def __init__(self) -> None:
        self.events: list[tuple[str, bool]] = []
        self.timestamps: list[float] = []

    async def handle(self, action: str, is_press: bool) -> None:
        self.events.append((action, is_press))
        self.timestamps.append(time.monotonic())


class FakeInteractions:
    pass


class FakeEncoders:
    pass


class FakeJoysticks:
    pass


def make_ctx(macros: FakeMacros, *, fallback_internal_toggle: bool = False) -> InputEventContext:
    layers = LayerManager()
    layers.load([{}])
    overlay_events: list[tuple[str, bool]] = []
    return InputEventContext(
        layers=layers,
        interactions=FakeInteractions(),
        macros=macros,
        encoders=FakeEncoders(),
        joysticks=FakeJoysticks(),
        pressed_matrix=set(),
        push_ledd_key_event=lambda row, col, is_press: None,
        push_ledd_status=lambda: None,
        push_i2cd_status=lambda: None,
        push_i2cd_alert=lambda _msg, _sec=2.0: None,
        push_ledd_anim=lambda anim: None,
        apply_lighting_key_action=lambda action, is_press: False,
        mouse_write_fn=lambda report: None,
        led_overlay_states={},
        host_led_output=HostLedOutputConfig(frozenset({"caps_lock"}), fallback_internal_toggle),
        push_ledd_overlay_state=lambda state, enabled: overlay_events.append((state, enabled)),
    )


async def dispatch_pair(action: str) -> list[tuple[str, bool]]:
    macros = FakeMacros()
    ctx = make_ctx(macros)
    await dispatch_action_event(action, True, ctx)
    await dispatch_action_event(action, False, ctx)
    return macros.events


def test_modifier_wrapper_dispatch() -> None:
    assert asyncio.run(dispatch_pair("S(KC_1)")) == [
        ("KC_LSFT", True),
        ("KC_1", True),
        ("KC_1", False),
        ("KC_LSFT", False),
    ]


def test_modifier_wrapper_dispatch_spacing() -> None:
    macros = FakeMacros()
    ctx = make_ctx(macros)
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    original_sleep = input_events.asyncio.sleep
    input_events.asyncio.sleep = fake_sleep
    try:
        asyncio.run(dispatch_action_event("S(KC_1)", True, ctx))
    finally:
        input_events.asyncio.sleep = original_sleep
    assert macros.events == [
        ("KC_LSFT", True),
        ("KC_1", True),
    ]
    assert sleeps == [0.020]


def test_shifted_alias_dispatch() -> None:
    assert asyncio.run(dispatch_pair("KC_EXLM")) == [
        ("KC_LSFT", True),
        ("KC_1", True),
        ("KC_1", False),
        ("KC_LSFT", False),
    ]


def test_canonical_alias_dispatch() -> None:
    assert asyncio.run(dispatch_pair("KC_CAPS_LOCK")) == [
        ("KC_CAPSLOCK", True),
        ("KC_CAPSLOCK", False),
    ]
    assert asyncio.run(dispatch_pair("LCTL(KC_RETURN)")) == [
        ("KC_LCTL", True),
        ("KC_ENTER", True),
        ("KC_ENTER", False),
        ("KC_LCTL", False),
    ]


def test_passthrough_dispatch() -> None:
    assert asyncio.run(dispatch_pair("KC_A")) == [
        ("KC_A", True),
        ("KC_A", False),
    ]


def test_caps_lock_overlay_does_not_toggle_without_fallback() -> None:
    macros = FakeMacros()
    ctx = make_ctx(macros)
    asyncio.run(dispatch_action_event("KC_CAPS", True, ctx))
    asyncio.run(dispatch_action_event("KC_CAPS", False, ctx))
    assert ctx.led_overlay_states == {}
    assert macros.events == [
        ("KC_CAPS", True),
        ("KC_CAPS", False),
    ]


def test_caps_lock_overlay_fallback_toggles_on_press_only() -> None:
    macros = FakeMacros()
    ctx = make_ctx(macros, fallback_internal_toggle=True)
    asyncio.run(dispatch_action_event("KC_CAPS", True, ctx))
    asyncio.run(dispatch_action_event("KC_CAPS", False, ctx))
    asyncio.run(dispatch_action_event("KC_CAPS", True, ctx))
    assert ctx.led_overlay_states == {"caps_lock": False}
    assert macros.events == [
        ("KC_CAPS", True),
        ("KC_CAPS", False),
        ("KC_CAPS", True),
    ]


def main() -> None:
    test_modifier_wrapper_dispatch()
    test_modifier_wrapper_dispatch_spacing()
    test_shifted_alias_dispatch()
    test_canonical_alias_dispatch()
    test_passthrough_dispatch()
    test_caps_lock_overlay_does_not_toggle_without_fallback()
    test_caps_lock_overlay_fallback_toggles_on_press_only()
    print("ok: input action expansion dispatch")


if __name__ == "__main__":
    main()
