#!/usr/bin/env python3
"""Regression tests for logicd.mod_morph."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.mod_morph import (  # noqa: E402
    is_safe_mod_morph_output,
    mod_morph_conflicts_for_key_overrides,
    normalize_mod_morph_config,
    parse_mod_morph_action,
    resolve_mod_morph_action,
)
from logicd.interaction_config import validate_interaction_settings  # noqa: E402
from logicd.interaction_engine import InteractionEngine, ResolvedActionEvent  # noqa: E402
from logicd.keymap import LayerManager  # noqa: E402


def warning_messages(config):
    return [(warning.name, warning.message) for warning in config.warnings]


def actions(events: list[ResolvedActionEvent]) -> list[tuple[str, bool, str]]:
    return [(event.action, event.is_press, event.source) for event in events]


def make_layers(mapping: dict[str, str]) -> LayerManager:
    layers = LayerManager()
    layers.load([mapping])
    return layers


def test_parse_actions() -> None:
    assert parse_mod_morph_action("GRAVE_ESCAPE").name == "grave_escape"
    assert parse_mod_morph_action("MOD_MORPH(grave_escape)").name == "grave_escape"
    assert parse_mod_morph_action("MOD_MORPH(nav.symbols-1)").name == "nav.symbols-1"
    assert parse_mod_morph_action("MOD_MORPH()") is None
    assert parse_mod_morph_action("KC_ESC") is None


def test_grave_escape_builtin_resolves_by_held_modifier() -> None:
    config = normalize_mod_morph_config({})
    assert config.warnings == ()

    assert resolve_mod_morph_action(
        "GRAVE_ESCAPE",
        config,
        held_actions=[],
        active_layers=[0],
    ) == "KC_ESC"
    assert resolve_mod_morph_action(
        "GRAVE_ESCAPE",
        config,
        held_actions=["KC_LSFT"],
        active_layers=[0],
    ) == "KC_GRV"
    assert resolve_mod_morph_action(
        "MOD_MORPH(grave_escape)",
        config,
        held_actions=["KC_RGUI"],
        active_layers=[0],
    ) == "KC_GRV"
    assert resolve_mod_morph_action("KC_A", config, held_actions=["KC_LSFT"]) == "KC_A"


def test_custom_rule_and_layer_filter() -> None:
    config = normalize_mod_morph_config({
        "symbol_escape": {
            "trigger_mods": ["KC_LALT"],
            "default_action": "KC_ESC",
            "morphed_action": "S(KC_GRV)",
            "layers": [2, 3],
        }
    })
    assert config.warnings == ()

    assert resolve_mod_morph_action(
        "MOD_MORPH(symbol_escape)",
        config,
        held_actions=["KC_LALT"],
        active_layers=[1],
    ) == "KC_ESC"
    assert resolve_mod_morph_action(
        "MOD_MORPH(symbol_escape)",
        config,
        held_actions=[],
        active_layers=[2],
    ) == "KC_ESC"
    assert resolve_mod_morph_action(
        "MOD_MORPH(symbol_escape)",
        config,
        held_actions=["KC_LALT"],
        active_layers=[2],
    ) == "S(KC_GRV)"


def test_modifier_aliases_are_canonicalized() -> None:
    config = normalize_mod_morph_config({
        "alias": {
            "trigger_mods": ["KC_LSHIFT", "KC_RWIN"],
            "default_action": "KC_ESC",
            "morphed_action": "KC_GRV",
        }
    })
    assert config.warnings == ()

    assert resolve_mod_morph_action(
        "MOD_MORPH(alias)",
        config,
        held_actions=["KC_LSFT"],
    ) == "KC_GRV"
    assert resolve_mod_morph_action(
        "MOD_MORPH(alias)",
        config,
        held_actions=["KC_RGUI"],
    ) == "KC_GRV"


def test_safe_output_scope() -> None:
    assert is_safe_mod_morph_output("KC_ESC")
    assert is_safe_mod_morph_output("KC_GRV")
    assert is_safe_mod_morph_output("S(KC_GRV)")
    assert is_safe_mod_morph_output("LCTL(KC_A)")

    for unsafe in [
        "KC_NO",
        "KC_TRNS",
        "MO(1)",
        "MACRO:hello",
        "SCRIPT(foo)",
        "ANIM(1)",
        "U+3042",
        "BT_STATUS",
        "WIFI_POWER_OFF",
        "KC_USB",
        "KC_SHUTDOWN",
        "KC_SH0",
        "KC_BTN1",
        "KC_WH_U",
        "MS_LEFT",
        "RGB_TOG",
        "MOD_MORPH(foo)",
    ]:
        assert not is_safe_mod_morph_output(unsafe), unsafe


def test_invalid_rules_are_skipped_with_warnings() -> None:
    config = normalize_mod_morph_config({
        "bad_mod": {
            "trigger_mods": ["KC_A"],
            "default_action": "KC_ESC",
            "morphed_action": "KC_GRV",
        },
        "bad_default": {
            "trigger_mods": ["KC_LSFT"],
            "default_action": "SCRIPT(foo)",
            "morphed_action": "KC_GRV",
        },
        "bad_morph": {
            "trigger_mods": ["KC_LSFT"],
            "default_action": "KC_ESC",
            "morphed_action": "BT_STATUS",
        },
        "bad_layers": {
            "trigger_mods": ["KC_LSFT"],
            "default_action": "KC_ESC",
            "morphed_action": "KC_GRV",
            "layers": "base-only",
        },
    })
    messages = warning_messages(config)
    assert ("bad_mod", "invalid trigger_mods: ['KC_A']") in messages
    assert ("bad_default", "unsafe default_action: SCRIPT(foo)") in messages
    assert ("bad_morph", "unsafe morphed_action: BT_STATUS") in messages
    assert ("bad_layers", "invalid layers") in messages
    assert "bad_mod" not in config.rules
    assert "bad_default" not in config.rules
    assert "bad_morph" not in config.rules
    assert "bad_layers" not in config.rules
    assert "grave_escape" in config.rules


def test_key_override_conflict_candidates() -> None:
    config = normalize_mod_morph_config({
        "grave_escape": {
            "trigger_mods": ["KC_LSFT"],
            "default_action": "KC_ESC",
            "morphed_action": "KC_GRV",
        },
        "other": {
            "trigger_mods": ["KC_LALT"],
            "default_action": "KC_TAB",
            "morphed_action": "KC_BSPC",
        },
    })

    conflicts = mod_morph_conflicts_for_key_overrides(config, ["KC_GRV", "KC_ENTER"])
    assert conflicts == ("MOD_MORPH(grave_escape)",)


def test_interaction_engine_dispatches_grave_escape_and_pins_release() -> None:
    layers = make_layers({
        "0,0": "KC_LSFT",
        "0,1": "GRAVE_ESCAPE",
        "0,2": "MOD_MORPH(symbol_escape)",
    })
    engine = InteractionEngine(
        layers,
        mod_morphs={
            "symbol_escape": {
                "trigger_mods": ["KC_LSFT"],
                "default_action": "KC_ESC",
                "morphed_action": "S(KC_GRV)",
            }
        },
    )

    assert actions(engine.on_key(0, 1, True, 1.000)) == [("KC_ESC", True, "matrix")]
    assert actions(engine.on_key(0, 1, False, 1.010)) == [("KC_ESC", False, "matrix")]

    assert actions(engine.on_key(0, 0, True, 1.100)) == [("KC_LSFT", True, "matrix")]
    assert actions(engine.on_key(0, 1, True, 1.110)) == [("KC_GRV", True, "matrix")]
    assert actions(engine.on_key(0, 0, False, 1.120)) == [("KC_LSFT", False, "matrix")]
    assert actions(engine.on_key(0, 1, False, 1.130)) == [("KC_GRV", False, "matrix")]

    assert actions(engine.on_key(0, 0, True, 1.200)) == [("KC_LSFT", True, "matrix")]
    assert actions(engine.on_key(0, 2, True, 1.210)) == [("S(KC_GRV)", True, "matrix")]
    assert actions(engine.on_key(0, 2, False, 1.220)) == [("S(KC_GRV)", False, "matrix")]


def test_key_override_has_priority_over_mod_morph_trigger() -> None:
    layers = make_layers({
        "0,0": "KC_LSFT",
        "0,1": "GRAVE_ESCAPE",
    })
    engine = InteractionEngine(
        layers,
        key_overrides=[{"trigger": "KC_LSFT", "key": "GRAVE_ESCAPE", "replacement": "KC_TAB"}],
    )

    assert actions(engine.on_key(0, 0, True, 2.000)) == [("KC_LSFT", True, "matrix")]
    assert actions(engine.on_key(0, 1, True, 2.010)) == [
        ("KC_LSFT", False, "key_override"),
        ("KC_TAB", True, "matrix"),
    ]
    assert actions(engine.on_key(0, 1, False, 2.020)) == [
        ("KC_TAB", False, "matrix"),
        ("KC_LSFT", True, "key_override"),
    ]


def test_interaction_validation_accepts_mod_morphs() -> None:
    validation = validate_interaction_settings(
        {
            "combos": [{"keys": [[0, 0], [0, 1]], "action": "GRAVE_ESCAPE"}],
            "mod_morphs": {
                "symbol_escape": {
                    "trigger_mods": ["KC_LSHIFT"],
                    "default_action": "KC_ESC",
                    "morphed_action": "S(KC_GRV)",
                    "layers": [2],
                },
                "bad": {
                    "trigger_mods": ["KC_A"],
                    "default_action": "KC_ESC",
                    "morphed_action": "KC_GRV",
                },
            },
        },
        matrix_in_range=lambda row, col: True,
    )
    assert validation.settings["combos"][0]["action"] == "GRAVE_ESCAPE"
    assert validation.settings["mod_morphs"] == {
        "symbol_escape": {
            "trigger_mods": ["KC_LSFT"],
            "default_action": "KC_ESC",
            "morphed_action": "S(KC_GRV)",
            "layers": [2],
        }
    }
    assert any("settings.interaction.mod_morphs.bad ignored" in warning for warning in validation.warnings)


def main() -> None:
    test_parse_actions()
    test_grave_escape_builtin_resolves_by_held_modifier()
    test_custom_rule_and_layer_filter()
    test_modifier_aliases_are_canonicalized()
    test_safe_output_scope()
    test_invalid_rules_are_skipped_with_warnings()
    test_key_override_conflict_candidates()
    test_interaction_engine_dispatches_grave_escape_and_pins_release()
    test_key_override_has_priority_over_mod_morph_trigger()
    test_interaction_validation_accepts_mod_morphs()
    print("ok: mod morph helper validates and resolves safe rules")


if __name__ == "__main__":
    main()
