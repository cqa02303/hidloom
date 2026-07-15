#!/usr/bin/env python3
"""Compatibility guard for SequenceEngine refactor entry points."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.interaction_engine import InteractionEngine, ResolvedActionEvent  # noqa: E402
from logicd.keymap import LayerManager  # noqa: E402


def actions(events: list[ResolvedActionEvent]) -> list[tuple[str, bool, str]]:
    return [(event.action, event.is_press, event.source) for event in events]


def make_layers() -> LayerManager:
    layers = LayerManager()
    layers.load([
        {
            "0,0": "LT(1,KC_A)",
            "0,1": "MT(LCTL,KC_B)",
            "0,2": "TT(1)",
            "0,3": "TD(seq)",
            "0,4": "MORSE(seq)",
        }
    ])
    return layers


def test_existing_action_names_still_resolve_without_sequence_engine_exposure() -> None:
    engine = InteractionEngine(
        make_layers(),
        tapping_term=0.200,
        tap_dance_term=0.200,
        tap_dances={"seq": {1: "KC_C", 2: "KC_D", "hold": "KC_LSFT"}},
        morse_behaviors={
            "seq": {
                "dot_threshold": 0.180,
                "sequence_timeout": 0.500,
                "max_depth": 1,
                "map": {".": "KC_E"},
            }
        },
    )

    assert actions(engine.on_key(0, 0, True, 1.000)) == []
    assert actions(engine.on_key(0, 0, False, 1.040)) == [
        ("KC_A", True, "matrix"),
        ("KC_A", False, "matrix"),
    ]

    assert actions(engine.on_key(0, 1, True, 2.000)) == []
    assert actions(engine.on_tick(2.250)) == [("KC_LCTL", True, "matrix")]
    assert actions(engine.on_key(0, 1, False, 2.300)) == [("KC_LCTL", False, "matrix")]

    assert actions(engine.on_key(0, 2, True, 3.000)) == []
    assert actions(engine.on_key(0, 2, False, 3.040)) == [
        ("TG(1)", True, "matrix"),
        ("TG(1)", False, "matrix"),
    ]

    assert actions(engine.on_key(0, 3, True, 4.000)) == []
    assert actions(engine.on_key(0, 3, False, 4.040)) == []
    assert actions(engine.on_tick(4.300)) == [
        ("KC_C", True, "tapdance"),
        ("KC_C", False, "tapdance"),
    ]

    assert actions(engine.on_key(0, 4, True, 5.000)) == []
    assert actions(engine.on_key(0, 4, False, 5.080)) == [
        ("KC_E", True, "morse"),
        ("KC_E", False, "morse"),
    ]


def test_sequence_engine_is_not_in_save_payload_paths_yet() -> None:
    interaction_engine = (ROOT / "daemon" / "logicd" / "interaction_engine.py").read_text(encoding="utf-8")
    interaction_config = (ROOT / "daemon" / "logicd" / "interaction_config.py").read_text(encoding="utf-8")
    http_assets = (ROOT / "daemon" / "http" / "static" / "interaction_panel.js").read_text(encoding="utf-8")

    assert "sequence_engine" not in interaction_engine
    assert "SequenceEmission" not in interaction_config
    assert "SequenceEngine" not in http_assets


def main() -> None:
    test_existing_action_names_still_resolve_without_sequence_engine_exposure()
    test_sequence_engine_is_not_in_save_payload_paths_yet()
    print("ok: sequence engine compatibility guard")


if __name__ == "__main__":
    main()
