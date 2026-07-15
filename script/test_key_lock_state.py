#!/usr/bin/env python3
"""Regression tests for logicd.key_lock."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.key_lock import (  # noqa: E402
    KeyLockState,
    key_lock_supported_targets,
    normalize_key_lock_target,
    parse_key_lock_action,
    reject_unsafe_key_lock_targets,
)
from logicd.interaction_engine import InteractionEngine, ResolvedActionEvent  # noqa: E402
from logicd.interaction_config import validate_interaction_settings  # noqa: E402
from logicd.input_events import InputEventContext, process_matrix_event  # noqa: E402
from logicd.keymap import LayerManager  # noqa: E402


def events(result):
    return [(event.action, event.is_press, event.source) for event in result.events]


def resolved(events: list[ResolvedActionEvent]) -> list[tuple[str, bool, str]]:
    return [(event.action, event.is_press, event.source) for event in events]


def make_layers(mapping: dict[str, str]) -> LayerManager:
    layers = LayerManager()
    layers.load([mapping])
    return layers


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


def test_target_validation() -> None:
    assert normalize_key_lock_target("KC_LSFT").kind == "modifier"
    assert normalize_key_lock_target("KC_RGUI").kind == "modifier"
    assert normalize_key_lock_target("KC_BTN1").kind == "mouse_button"
    assert normalize_key_lock_target("KC_BTN5").kind == "mouse_button"
    assert normalize_key_lock_target("KC_A") is None
    assert normalize_key_lock_target("SCRIPT(foo)") is None
    assert normalize_key_lock_target("BT_STATUS") is None
    assert normalize_key_lock_target("KC_USB") is None

    rejected = reject_unsafe_key_lock_targets([
        "KC_LSFT",
        "KC_BTN1",
        "KC_A",
        "SCRIPT(foo)",
        "WIFI_POWER_OFF",
    ])
    assert rejected == ("KC_A", "SCRIPT(foo)", "WIFI_POWER_OFF")


def test_parse_commands() -> None:
    drag = parse_key_lock_action("DRAG_LOCK")
    assert drag is not None
    assert drag.op == "KEY_TOGGLE"
    assert drag.target.action == "KC_BTN1"
    assert drag.source == "DRAG_LOCK"

    toggle = parse_key_lock_action("KEY_TOGGLE(KC_LSFT)")
    assert toggle is not None
    assert toggle.op == "KEY_TOGGLE"
    assert toggle.target.kind == "modifier"

    unsupported = parse_key_lock_action("KEY_LOCK(KC_A)")
    assert unsupported is not None
    assert unsupported.target.kind == "unsupported"

    assert parse_key_lock_action("KC_A") is None


def test_drag_lock_toggles_mouse_button() -> None:
    state = KeyLockState()

    first = state.handle_action("DRAG_LOCK", is_press=True)
    assert first is not None and first.handled and first.changed
    assert events(first) == [("KC_BTN1", True, "key_lock")]
    assert state.active_actions() == ("KC_BTN1",)
    assert state.status()["keys"] == [{
        "action": "KC_BTN1",
        "mode": "locked",
        "source": "DRAG_LOCK",
        "kind": "mouse_button",
        "locked": True,
        "cancel_reason": None,
    }]

    release = state.handle_action("DRAG_LOCK", is_press=False)
    assert release is not None and release.handled and not release.changed
    assert state.active_actions() == ("KC_BTN1",)

    second = state.handle_action("DRAG_LOCK", is_press=True)
    assert second is not None and second.changed
    assert events(second) == [("KC_BTN1", False, "key_lock")]
    assert state.active_actions() == ()


def test_key_toggle_modifier_press_release() -> None:
    state = KeyLockState()

    first = state.handle_action("KEY_TOGGLE(KC_LSFT)", is_press=True)
    assert first is not None and first.changed
    assert events(first) == [("KC_LSFT", True, "key_lock")]
    assert state.is_locked("KC_LSFT")

    second = state.handle_action("KEY_TOGGLE(KC_LSFT)", is_press=True)
    assert second is not None and second.changed
    assert events(second) == [("KC_LSFT", False, "key_lock")]
    assert not state.is_locked("KC_LSFT")


def test_key_lock_unlock_and_clear() -> None:
    state = KeyLockState()

    lock = state.handle_action("KEY_LOCK(KC_BTN2)", is_press=True)
    assert lock is not None and lock.changed
    assert events(lock) == [("KC_BTN2", True, "key_lock")]

    duplicate = state.handle_action("KEY_LOCK(KC_BTN2)", is_press=True)
    assert duplicate is not None and not duplicate.changed
    assert events(duplicate) == []

    unlock = state.handle_action("KEY_UNLOCK(KC_BTN2)", is_press=True)
    assert unlock is not None and unlock.changed
    assert events(unlock) == [("KC_BTN2", False, "key_lock")]

    state.handle_action("KEY_LOCK(KC_BTN1)", is_press=True)
    state.handle_action("KEY_LOCK(KC_LCTL)", is_press=True)
    clear_events = state.clear(reason="output_switch")
    assert [(event.action, event.is_press) for event in clear_events] == [
        ("KC_BTN1", False),
        ("KC_LCTL", False),
    ]
    assert state.active_actions() == ()


def test_unsafe_targets_are_consumed_with_warning() -> None:
    state = KeyLockState()

    result = state.handle_action("KEY_TOGGLE(KC_A)", is_press=True)
    assert result is not None and result.handled
    assert not result.changed
    assert result.warning == "unsupported key lock target: KC_A"
    assert result.events == ()
    assert state.active_actions() == ()


def test_supported_targets_inventory() -> None:
    targets = key_lock_supported_targets()
    assert "KC_LSFT" in targets["modifier"]
    assert "KC_RGUI" in targets["modifier"]
    assert "KC_BTN1" in targets["mouse_button"]
    assert "KC_BTN5" in targets["mouse_button"]


def test_interaction_engine_dispatches_key_lock_commands() -> None:
    layers = make_layers({
        "0,0": "KEY_TOGGLE(KC_LSFT)",
        "0,1": "DRAG_LOCK",
    })
    engine = InteractionEngine(layers)

    assert resolved(engine.on_key(0, 0, True, 1.000)) == [("KC_LSFT", True, "key_lock")]
    assert engine.key_locks.active_actions() == ("KC_LSFT",)
    assert engine.on_key(0, 0, False, 1.010) == []
    assert engine.key_locks.active_actions() == ("KC_LSFT",)
    assert resolved(engine.on_key(0, 0, True, 1.100)) == [("KC_LSFT", False, "key_lock")]
    assert engine.key_locks.active_actions() == ()

    assert resolved(engine.on_key(0, 1, True, 1.200)) == [("KC_BTN1", True, "key_lock")]
    assert engine.key_locks.status()["keys"][0]["source"] == "DRAG_LOCK"


def test_key_lock_active_modifier_participates_in_key_override() -> None:
    layers = make_layers({
        "0,0": "KEY_LOCK(KC_LSFT)",
        "0,1": "KC_1",
    })
    engine = InteractionEngine(
        layers,
        key_overrides=[{"trigger": "KC_LSFT", "key": "KC_1", "replacement": "KC_EXLM"}],
    )

    assert resolved(engine.on_key(0, 0, True, 2.000)) == [("KC_LSFT", True, "key_lock")]
    assert resolved(engine.on_key(0, 1, True, 2.100)) == [("KC_EXLM", True, "matrix")]
    assert resolved(engine.on_key(0, 1, False, 2.110)) == [("KC_EXLM", False, "matrix")]


def test_output_switch_clears_key_lock_before_switch_action() -> None:
    layers = make_layers({
        "0,0": "KEY_LOCK(KC_LSFT)",
        "0,1": "KC_USB",
    })
    engine = InteractionEngine(layers)
    macros = FakeMacros()
    ctx = make_ctx(layers, engine, macros)

    import asyncio

    asyncio.run(process_matrix_event(("P", 0, 0), ctx))
    assert macros.events == [("KC_LSFT", True)]
    assert engine.key_locks.active_actions() == ("KC_LSFT",)

    asyncio.run(process_matrix_event(("P", 0, 1), ctx))
    assert macros.events[-2:] == [("KC_LSFT", False), ("KC_USB", True)]
    assert engine.key_locks.active_actions() == ()


def test_reset_releases_key_locks_and_held_interactions() -> None:
    layers = make_layers({
        "0,0": "KEY_LOCK(KC_LSFT)",
        "0,1": "KC_A",
    })
    engine = InteractionEngine(layers)

    assert resolved(engine.on_key(0, 0, True, 3.000)) == [("KC_LSFT", True, "key_lock")]
    assert resolved(engine.on_key(0, 1, True, 3.100)) == [("KC_A", True, "matrix")]

    reset_events = resolved(engine.reset())
    assert reset_events == [
        ("KC_LSFT", False, "key_lock"),
        ("KC_A", False, "reset"),
    ]
    assert engine.key_locks.active_actions() == ()
    assert engine.pressed == {}
    assert engine.on_key(0, 1, False, 3.200) == []


def test_interaction_validation_accepts_safe_key_lock_actions_only() -> None:
    validation = validate_interaction_settings(
        {
            "combos": [
                {"keys": [[0, 0], [0, 1]], "action": "KEY_TOGGLE(KC_LSFT)"},
                {"keys": [[1, 0], [1, 1]], "action": "DRAG_LOCK"},
                {"keys": [[2, 0], [2, 1]], "action": "KEY_LOCK(KC_A)"},
            ],
        },
        matrix_in_range=lambda row, col: True,
    )
    assert [item["action"] for item in validation.settings["combos"]] == [
        "KEY_TOGGLE(KC_LSFT)",
        "DRAG_LOCK",
    ]
    assert any("KEY_LOCK(KC_A)" in warning for warning in validation.warnings)


def main() -> None:
    test_target_validation()
    test_parse_commands()
    test_drag_lock_toggles_mouse_button()
    test_key_toggle_modifier_press_release()
    test_key_lock_unlock_and_clear()
    test_unsafe_targets_are_consumed_with_warning()
    test_supported_targets_inventory()
    test_interaction_engine_dispatches_key_lock_commands()
    test_key_lock_active_modifier_participates_in_key_override()
    test_output_switch_clears_key_lock_before_switch_action()
    test_reset_releases_key_locks_and_held_interactions()
    test_interaction_validation_accepts_safe_key_lock_actions_only()
    print("ok: key lock state validates targets and emits synthetic events")


if __name__ == "__main__":
    main()
