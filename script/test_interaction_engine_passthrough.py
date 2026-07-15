#!/usr/bin/env python3
"""Regression tests for the pass-through InteractionEngine."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.interaction_engine import InteractionEngine, ResolvedActionEvent  # noqa: E402
from logicd.keymap import LayerManager  # noqa: E402


def make_layers() -> LayerManager:
    layers = LayerManager()
    layers.load([
        {
            "0,0": "KC_A",
            "0,1": "MO(1)",
            "0,2": "KC_B",
            "0,3": "OSL(1)",
        },
        {
            "0,2": "KC_C",
            "0,3": "KC_D",
        },
    ])
    return layers


def only_event(events: list[ResolvedActionEvent]) -> ResolvedActionEvent:
    assert len(events) == 1
    return events[0]


def test_normal_key_passthrough() -> None:
    engine = InteractionEngine(make_layers())

    ev = only_event(engine.on_key(0, 0, True, 1.0))
    assert ev.action == "KC_A"
    assert ev.is_press is True
    assert ev.row == 0
    assert ev.col == 0
    assert ev.source == "matrix"
    assert (0, 0) in engine.pressed

    ev = only_event(engine.on_key(0, 0, False, 1.1))
    assert ev.action == "KC_A"
    assert ev.is_press is False
    assert (0, 0) not in engine.pressed


def test_layer_state_passthrough_matches_current_lookup() -> None:
    layers = make_layers()
    engine = InteractionEngine(layers)

    ev = only_event(engine.on_key(0, 1, True, 2.0))
    assert ev.action == "MO(1)"
    layers.momentary_on(1)

    ev = only_event(engine.on_key(0, 2, True, 2.1))
    assert ev.action == "KC_C"

    ev = only_event(engine.on_key(0, 2, False, 2.2))
    assert ev.action == "KC_C"

    ev = only_event(engine.on_key(0, 1, False, 2.3))
    assert ev.action == "MO(1)"


def test_tick_noop_and_reset() -> None:
    layers = make_layers()
    engine = InteractionEngine(layers)
    engine.on_key(0, 0, True, 3.0)
    assert engine.on_tick(3.2) == []
    assert engine.pressed

    next_layers = make_layers()
    engine.reset(next_layers)
    assert engine.layers is next_layers
    assert engine.pressed == {}
    assert engine.timers == []


def test_oneshot_layer_is_consumed_by_next_non_layer_key() -> None:
    layers = make_layers()
    engine = InteractionEngine(layers)
    layers.oneshot_on(1)

    ev = only_event(engine.on_key(0, 2, True, 4.0))
    assert ev.action == "KC_C"
    assert layers.active_snapshot()["oneshot"] == []

    ev = only_event(engine.on_key(0, 2, False, 4.1))
    assert ev.action == "KC_C"

    ev = only_event(engine.on_key(0, 2, True, 4.2))
    assert ev.action == "KC_B"


def test_oneshot_layer_survives_layer_action() -> None:
    layers = make_layers()
    engine = InteractionEngine(layers)
    layers.oneshot_on(1)

    ev = only_event(engine.on_key(0, 3, True, 5.0))
    assert ev.action == "KC_D"
    assert layers.active_snapshot()["oneshot"] == []

    layers.oneshot_on(1)
    ev = only_event(engine.on_key(0, 1, True, 5.1))
    assert ev.action == "MO(1)"
    assert layers.active_snapshot()["oneshot"] == [1]


def main() -> None:
    test_normal_key_passthrough()
    test_layer_state_passthrough_matches_current_lookup()
    test_tick_noop_and_reset()
    test_oneshot_layer_is_consumed_by_next_non_layer_key()
    test_oneshot_layer_survives_layer_action()
    print("ok: interaction engine pass-through behavior")


if __name__ == "__main__":
    main()
