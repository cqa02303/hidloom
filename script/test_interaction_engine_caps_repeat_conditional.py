#!/usr/bin/env python3
"""Regression tests for Caps Word, Repeat Key, and Conditional Layers."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.interaction_config import validate_interaction_settings  # noqa: E402
from logicd.interaction_engine import InteractionEngine, ResolvedActionEvent  # noqa: E402
from logicd.keymap import LayerManager  # noqa: E402


def actions(events: list[ResolvedActionEvent]) -> list[tuple[str, bool, str]]:
    return [(event.action, event.is_press, event.source) for event in events]


def make_layers(mapping: dict[str, str]) -> LayerManager:
    layers = LayerManager()
    layers.load([mapping])
    return layers


def test_caps_word_shifts_letters_and_cancels_on_boundary() -> None:
    layers = make_layers({
        "0,0": "CAPS_WORD",
        "0,1": "KC_A",
        "0,2": "KC_MINS",
        "0,3": "KC_SPACE",
        "0,4": "KC_B",
    })
    engine = InteractionEngine(layers)

    assert engine.on_key(0, 0, True, 1.000) == []
    assert engine.caps_word_active
    assert engine.on_key(0, 0, False, 1.010) == []

    assert actions(engine.on_key(0, 1, True, 1.100)) == [("S(KC_A)", True, "matrix")]
    assert actions(engine.on_key(0, 1, False, 1.110)) == [("S(KC_A)", False, "matrix")]
    assert engine.caps_word_active

    assert actions(engine.on_key(0, 2, True, 1.200)) == [("KC_MINS", True, "matrix")]
    assert actions(engine.on_key(0, 2, False, 1.210)) == [("KC_MINS", False, "matrix")]
    assert engine.caps_word_active

    assert actions(engine.on_key(0, 3, True, 1.300)) == [("KC_SPACE", True, "matrix")]
    assert actions(engine.on_key(0, 3, False, 1.310)) == [("KC_SPACE", False, "matrix")]
    assert not engine.caps_word_active

    assert actions(engine.on_key(0, 4, True, 1.400)) == [("KC_B", True, "matrix")]


def test_repeat_key_replays_and_alternates_repeatable_actions() -> None:
    layers = make_layers({
        "0,0": "KC_A",
        "0,1": "REPEAT_KEY",
        "0,2": "KC_LEFT",
        "0,3": "ALT_REPEAT_KEY",
        "0,4": "BT_STATUS",
    })
    engine = InteractionEngine(layers)

    assert actions(engine.on_key(0, 0, True, 2.000)) == [("KC_A", True, "matrix")]
    assert actions(engine.on_key(0, 0, False, 2.010)) == [("KC_A", False, "matrix")]
    assert actions(engine.on_key(0, 1, True, 2.100)) == [
        ("KC_A", True, "repeat"),
        ("KC_A", False, "repeat"),
    ]
    assert engine.on_key(0, 1, False, 2.110) == []

    assert actions(engine.on_key(0, 2, True, 2.200)) == [("KC_LEFT", True, "matrix")]
    assert actions(engine.on_key(0, 2, False, 2.210)) == [("KC_LEFT", False, "matrix")]
    assert actions(engine.on_key(0, 3, True, 2.300)) == [
        ("KC_RGHT", True, "repeat"),
        ("KC_RGHT", False, "repeat"),
    ]

    assert actions(engine.on_key(0, 4, True, 2.400)) == [("BT_STATUS", True, "matrix")]
    assert actions(engine.on_key(0, 4, False, 2.410)) == [("BT_STATUS", False, "matrix")]
    assert actions(engine.on_key(0, 1, True, 2.500)) == [
        ("KC_RGHT", True, "repeat"),
        ("KC_RGHT", False, "repeat"),
    ]


def test_runtime_shortcut_reset_clears_caps_word_and_repeat_history() -> None:
    layers = make_layers({"0,0": "CAPS_WORD", "0,1": "KC_A", "0,2": "REPEAT_KEY"})
    engine = InteractionEngine(layers)
    engine.on_key(0, 0, True, 3.000)
    engine.on_key(0, 1, True, 3.100)
    assert engine.caps_word_active
    assert engine.repeat_history == "S(KC_A)"

    engine.clear_runtime_shortcuts()
    assert not engine.caps_word_active
    assert engine.repeat_history is None
    assert engine.on_key(0, 2, True, 3.200) == []


def test_conditional_layers_are_effective_but_not_chain_sources() -> None:
    layers = LayerManager()
    layers.load([
        {"0,0": "KC_A"},
        {"0,0": "KC_B"},
        {"0,0": "KC_C"},
        {"0,0": "KC_D"},
        {"0,0": "KC_E"},
    ])
    layers.set_conditional_rules([
        {"name": "tri", "if_all": [1, 2], "then": 3},
        {"name": "no_chain", "if_all": [1, 3], "then": 4},
    ])

    layers.momentary_on(1)
    assert layers.active_snapshot()["conditional"] == []
    layers.momentary_on(2)
    snapshot = layers.active_snapshot()
    assert snapshot["conditional"] == [3]
    assert snapshot["all"] == [3, 2, 1, 0]

    layers.momentary_off(2)
    assert layers.active_snapshot()["conditional"] == []
    layers.toggle(3)
    snapshot = layers.active_snapshot()
    assert snapshot["conditional"] == [4]
    assert snapshot["all"] == [4, 3, 1, 0]


def test_interaction_validation_accepts_new_settings() -> None:
    validation = validate_interaction_settings(
        {
            "caps_word": {"enabled": True, "continue_keys": ["KC_MINS"], "cancel_keys": ["KC_SPACE"]},
            "repeat_key": {"alternate_pairs": [["KC_LEFT", "KC_RGHT"]]},
            "conditional_layers": [{"name": "tri", "if_all": [1, 2], "then": 3}],
        },
        matrix_in_range=lambda row, col: True,
    )
    assert validation.warnings == []
    assert validation.settings["caps_word"]["continue_keys"] == ["KC_MINS"]
    assert validation.settings["repeat_key"]["alternate_pairs"] == [["KC_LEFT", "KC_RGHT"]]
    assert validation.settings["conditional_layers"] == [{"name": "tri", "if_all": [1, 2], "then": 3}]


def main() -> None:
    test_caps_word_shifts_letters_and_cancels_on_boundary()
    test_repeat_key_replays_and_alternates_repeatable_actions()
    test_runtime_shortcut_reset_clears_caps_word_and_repeat_history()
    test_conditional_layers_are_effective_but_not_chain_sources()
    test_interaction_validation_accepts_new_settings()
    print("ok: caps word, repeat key, and conditional layer behavior")


if __name__ == "__main__":
    main()
