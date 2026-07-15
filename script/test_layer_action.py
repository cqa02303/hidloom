#!/usr/bin/env python3
"""Regression tests for logicd.layer_action."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.interaction_engine import InteractionEngine  # noqa: E402
from logicd.keymap import LayerManager  # noqa: E402
from logicd.layer_action import handle_layer_action, parse_layer_action  # noqa: E402


def test_parse_layer_action() -> None:
    assert parse_layer_action("MO(2)") == ("MO", 2)
    assert parse_layer_action("TO(9)") == ("TO", 9)
    assert parse_layer_action("QK_LAYER_LOCK") == ("QK_LAYER_LOCK", -1)
    assert parse_layer_action("QK_LLCK") == ("QK_LLCK", -1)
    assert parse_layer_action("KC_A") is None


def test_momentary_layer() -> None:
    layers = LayerManager()
    layers.load([{"0,0": "KC_A"}, {"0,0": "KC_B"}, {"0,0": "KC_C"}])
    result = handle_layer_action(layers, "MO(2)", True)
    assert result and result.changed
    assert 2 in layers._momentary

    result = handle_layer_action(layers, "MO(2)", False)
    assert result is not None
    assert 2 not in layers._momentary


def test_toggle_layer() -> None:
    layers = LayerManager()
    layers.load([{"0,0": "KC_A"}, {"0,0": "KC_B"}, {"0,0": "KC_C"}, {"0,0": "KC_D"}])
    handle_layer_action(layers, "TG(3)", True)
    assert 3 in layers._toggled

    handle_layer_action(layers, "TG(3)", True)
    assert 3 not in layers._toggled


def test_to_layer() -> None:
    layers = LayerManager()
    layers.load([{"0,0": "KC_A"}, {"0,0": "KC_B"}, {"0,0": "KC_C"}, {}, {}, {"0,0": "KC_F"}])
    layers.toggle(5)
    handle_layer_action(layers, "TO(2)", True)
    assert 5 not in layers._toggled
    assert 2 in layers._toggled


def test_default_layer() -> None:
    layers = LayerManager()
    layers.load([{"0,0": "KC_A"}, {"0,0": "KC_B"}, {"0,0": "KC_C"}, {}, {"0,0": "KC_E"}])
    handle_layer_action(layers, "DF(4)", True)
    assert layers._default_layer == 4


def test_oneshot_layer() -> None:
    layers = LayerManager()
    layers.load([
        {"0,0": "KC_A"},
        {"0,0": "KC_B"},
    ])
    engine = InteractionEngine(layers)

    handle_layer_action(layers, "OSL(1)", True)
    assert layers.has_oneshot()
    assert layers.active_snapshot()["oneshot"] == [1]

    press = engine.on_key(0, 0, True, 1.0)[0]
    assert press.action == "KC_B"
    assert not layers.has_oneshot()
    assert layers.active_snapshot()["oneshot"] == []

    release = engine.on_key(0, 0, False, 1.1)[0]
    assert release.action == "KC_B"


def test_layer_lock_no_active_layer_is_noop() -> None:
    layers = LayerManager()
    layers.load([{"0,0": "KC_A"}, {"0,0": "KC_B"}])

    result = handle_layer_action(layers, "QK_LAYER_LOCK", True)

    assert result is not None
    assert not result.changed
    assert result.layer == -1
    assert layers.active_snapshot()["locked"] == []


def test_layer_lock_holds_momentary_layer_after_release() -> None:
    layers = LayerManager()
    layers.load([{"0,0": "KC_A"}, {"0,0": "KC_B"}, {"0,0": "KC_C"}])

    handle_layer_action(layers, "MO(2)", True)
    result = handle_layer_action(layers, "QK_LAYER_LOCK", True)
    assert result is not None and result.changed
    assert result.layer == 2
    assert layers.active_snapshot()["locked"] == [2]

    handle_layer_action(layers, "MO(2)", False)
    assert layers.active_snapshot()["momentary"] == []
    assert layers.active_snapshot()["locked"] == [2]
    assert layers.get_action(0, 0) == "KC_C"

    result = handle_layer_action(layers, "QK_LLCK", True)
    assert result is not None and result.changed
    assert result.layer == 2
    assert layers.active_snapshot()["locked"] == []


def test_layer_lock_moves_oneshot_to_locked() -> None:
    layers = LayerManager()
    layers.load([{"0,0": "KC_A"}, {"0,0": "KC_B"}])

    handle_layer_action(layers, "OSL(1)", True)
    result = handle_layer_action(layers, "QK_LAYER_LOCK", True)

    assert result is not None and result.changed
    assert layers.active_snapshot()["oneshot"] == []
    assert layers.active_snapshot()["locked"] == [1]
    assert layers.get_action(0, 0) == "KC_B"


def test_layer_lock_cleared_by_to_df_load_and_layer_remove() -> None:
    layers = LayerManager()
    layers.load([{"0,0": "KC_A"}, {"0,0": "KC_B"}, {"0,0": "KC_C"}])

    layers.momentary_on(2)
    handle_layer_action(layers, "QK_LAYER_LOCK", True)
    assert layers.active_snapshot()["locked"] == [2]

    handle_layer_action(layers, "TO(1)", True)
    assert layers.active_snapshot()["locked"] == []

    layers.momentary_on(2)
    handle_layer_action(layers, "QK_LAYER_LOCK", True)
    handle_layer_action(layers, "DF(1)", True)
    assert layers.active_snapshot()["locked"] == []

    layers.momentary_on(2)
    handle_layer_action(layers, "QK_LAYER_LOCK", True)
    layers.load([{"0,0": "KC_A"}])
    assert layers.active_snapshot()["locked"] == []

    layers.load([{"0,0": "KC_A"}, {"0,0": "KC_B"}])
    layers.momentary_on(1)
    handle_layer_action(layers, "QK_LAYER_LOCK", True)
    assert layers.active_snapshot()["locked"] == [1]
    layers.clear_layer(1)
    assert layers.active_snapshot()["locked"] == []


def main() -> None:
    test_parse_layer_action()
    test_momentary_layer()
    test_toggle_layer()
    test_to_layer()
    test_default_layer()
    test_oneshot_layer()
    test_layer_lock_no_active_layer_is_noop()
    test_layer_lock_holds_momentary_layer_after_release()
    test_layer_lock_moves_oneshot_to_locked()
    test_layer_lock_cleared_by_to_df_load_and_layer_remove()
    print("ok: logicd layer actions update LayerManager state")


if __name__ == "__main__":
    main()
