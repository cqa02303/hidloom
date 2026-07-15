#!/usr/bin/env python3
"""Regression tests for Vial .vil import/export helpers."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from viald.keycode_codec import KeycodeCodec  # noqa: E402
from vil_layout import (  # noqa: E402
    HIDLOOM_EXPORT_WARNINGS_KEY,
    HIDLOOM_INTERACTION_SETTINGS_KEY,
    HIDLOOM_VIAL_MACRO_BUFFER_KEY,
    build_vil_document,
    encode_vil,
    load_encoder_map,
    load_keymap_layers,
    main,
    parse_vil_import,
)


def test_document_roundtrip() -> None:
    codec = KeycodeCodec(ROOT / "config" / "default" / "keycodes.json")
    layers = [
        {"0,0": "KC_A", "0,1": "MO(1)", "6,1": "KC_WH_D", "7,1": "KC_WH_U"},
        {"0,0": "KC_TRNS", "0,1": "KC_B", "6,1": "KC_MS_U", "7,1": "RGB_TOG"},
    ]
    encoders = [((6, 1), (7, 1))]
    doc = build_vil_document(
        uid=1234,
        rows=8,
        cols=2,
        layers=layers,
        encoder_map=encoders,
        codec=codec,
    )
    assert doc["version"] == 1
    assert doc["uid"] == 1234
    assert doc["layout"][0][0][0] == codec.action_to_vial("KC_A")
    assert doc["layout"][0][0][1] == codec.action_to_vial("MO(1)")
    assert doc["encoder_layout"][0][0] == [
        codec.action_to_vial("KC_WH_D"),
        codec.action_to_vial("KC_WH_U"),
    ]

    plan = parse_vil_import(
        encode_vil(doc),
        expected_uid=1234,
        rows=8,
        cols=2,
        encoder_map=encoders,
        codec=codec,
    )
    assert not plan.uid_mismatch
    assert any(r.layer == 0 and r.row == 0 and r.col == 0 and r.action == "KC_A" for r in plan.remaps)
    assert any(r.layer == 1 and r.row == 7 and r.col == 1 and r.action == "RGB_TOG" for r in plan.remaps)


def test_interaction_settings_roundtrip() -> None:
    codec = KeycodeCodec(ROOT / "config" / "default" / "keycodes.json")
    layers = [{"0,0": "KC_A", "0,1": "KC_ESC", "0,2": "KC_1", "0,3": "KC_LSFT"}]
    interaction = {
        "combo_term": 0.05,
        "tapping_term": 0.2,
        "hold_on_other_key_press": True,
        "tap_dance_term": 0.25,
        "tap_dances": {"TD0": {"1": "KC_A", "hold": "KC_LSHIFT", "2": "KC_ESC", "tap_hold": "KC_LCTRL"}},
        "combos": [{"keys": [[0, 0], [0, 1]], "action": "KC_TAB"}],
        "key_overrides": [{"trigger": "KC_LSFT", "key": "KC_1", "replacement": "KC_ESC"}],
    }
    doc = build_vil_document(
        uid=1234,
        rows=1,
        cols=4,
        layers=layers,
        encoder_map=[],
        codec=codec,
        interaction_settings=interaction,
        vial_macro_buffer="SGkA",
    )
    assert doc["settings"][HIDLOOM_INTERACTION_SETTINGS_KEY] == interaction
    assert doc["settings"][HIDLOOM_VIAL_MACRO_BUFFER_KEY] == "SGkA"
    assert doc["tap_dance"][0] == [
        codec.action_to_vial("KC_A"),
        codec.action_to_vial("KC_LSHIFT"),
        codec.action_to_vial("KC_ESC"),
        codec.action_to_vial("KC_LCTRL"),
        250,
    ]
    assert doc["combo"][0] == [
        codec.action_to_vial("KC_A"),
        codec.action_to_vial("KC_ESC"),
        0,
        0,
        codec.action_to_vial("KC_TAB"),
    ]
    assert doc["key_override"][0]["trigger_mods"] == 0x02

    plan = parse_vil_import(
        encode_vil(doc),
        expected_uid=1234,
        rows=1,
        cols=4,
        encoder_map=[],
        codec=codec,
    )
    assert plan.interaction_settings == interaction
    assert plan.vial_macro_buffer == "SGkA"


def test_export_warnings_for_unrepresentable_actions() -> None:
    codec = KeycodeCodec(ROOT / "config" / "default" / "keycodes.json")
    layers = [
        {"0,0": "KC_A", "0,1": "SCRIPT(foo)", "0,2": "MACRO:hello"},
    ]
    doc = build_vil_document(
        uid=1234,
        rows=1,
        cols=3,
        layers=layers,
        encoder_map=[],
        codec=codec,
    )
    warnings = doc["settings"][HIDLOOM_EXPORT_WARNINGS_KEY]
    assert len(warnings) == 2
    assert "SCRIPT(foo)" in warnings[0]
    assert "MACRO:hello" in warnings[1]
    assert doc["layout"][0][0][0] == codec.action_to_vial("KC_A")
    assert doc["layout"][0][0][1] == 0
    assert doc["layout"][0][0][2] == 0

    plan = parse_vil_import(
        encode_vil(doc),
        expected_uid=1234,
        rows=1,
        cols=3,
        encoder_map=[],
        codec=codec,
    )
    assert plan.warnings == warnings


def test_uid_mismatch_requires_force() -> None:
    doc = {"version": 1, "uid": 222, "layout": [[[4]]], "encoder_layout": []}
    plan = parse_vil_import(json.dumps(doc), expected_uid=111, rows=1, cols=1, encoder_map=[])
    assert plan.uid_mismatch
    assert plan.remaps == []

    forced = parse_vil_import(
        json.dumps(doc),
        expected_uid=111,
        rows=1,
        cols=1,
        encoder_map=[],
        force_uid=True,
    )
    assert forced.uid_mismatch
    assert len(forced.remaps) == 1


def test_project_keymap_exports() -> None:
    layers = load_keymap_layers(ROOT / "config" / "default" / "keymap.json")
    encoders = load_encoder_map(ROOT / "config" / "default" / "keymap.json")
    assert layers
    assert encoders
    doc = build_vil_document(
        uid=4850729948911185980,
        rows=10,
        cols=10,
        layers=layers,
        encoder_map=encoders,
    )
    assert len(doc["layout"]) == len(layers)
    assert len(doc["layout"][0]) == 10
    assert len(doc["layout"][0][0]) == 10
    assert len(doc["encoder_layout"][0]) == len(encoders)


def test_cli_export_and_check() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "layout.vil"
        assert main(["export", "-o", str(out)]) == 0
        assert out.exists()
        assert main(["check", str(out)]) == 0


def main_test() -> None:
    test_document_roundtrip()
    test_interaction_settings_roundtrip()
    test_export_warnings_for_unrepresentable_actions()
    test_uid_mismatch_requires_force()
    test_project_keymap_exports()
    test_cli_export_and_check()
    print("ok: .vil layout codec behaves as expected")


if __name__ == "__main__":
    main_test()
