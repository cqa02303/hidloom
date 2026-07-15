#!/usr/bin/env python3
"""Regression tests for InteractionEngine tap-hold handling."""
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
            "0,0": "LT(1,KC_A)",
            "0,1": "KC_B",
            "0,2": "MT(LCTL,KC_C)",
            "0,3": "TT(1)",
            "0,4": "SC_LSPO",
            "0,5": "SC_RSPC",
            "0,6": "KC_E",
            "0,7": "TD(TD0)",
            "0,8": "KC_LSFT",
            "0,9": "KC_1",
            "1,0": "KC_LCTL",
        },
        {
            "0,1": "KC_D",
        },
    ])
    return layers


def make_tap_dance_engine() -> InteractionEngine:
    return InteractionEngine(
        make_layers(),
        tap_dance_term=0.200,
        tap_dances={"TD0": {1: "KC_A", 2: "KC_ESC", 3: "KC_TAB", "hold": "KC_LSFT", "tap_hold": "KC_LCTL"}},
    )


def actions(events: list[ResolvedActionEvent]) -> list[tuple[str, bool]]:
    return [(ev.action, ev.is_press) for ev in events]


def test_lt_tap_on_quick_release() -> None:
    engine = InteractionEngine(make_layers(), tapping_term=0.200)

    assert engine.on_key(0, 0, True, 1.000) == []
    assert actions(engine.on_key(0, 0, False, 1.050)) == [
        ("KC_A", True),
        ("KC_A", False),
    ]


def test_lt_hold_after_timeout_tick() -> None:
    engine = InteractionEngine(make_layers(), tapping_term=0.200)

    assert engine.on_key(0, 0, True, 2.000) == []
    assert engine.next_timer_due() == 2.200
    assert actions(engine.on_tick(2.250)) == [("MO(1)", True)]
    assert engine.next_timer_due() is None
    assert actions(engine.on_tick(2.300)) == []
    assert actions(engine.on_key(0, 0, False, 2.400)) == [("MO(1)", False)]


def test_lt_delayed_release_processing_still_taps_without_prior_hold() -> None:
    engine = InteractionEngine(make_layers(), tapping_term=0.200)

    assert engine.on_key(0, 0, True, 2.500) == []
    assert actions(engine.on_key(0, 0, False, 2.750)) == [
        ("KC_A", True),
        ("KC_A", False),
    ]
    assert actions(engine.on_tick(2.750)) == []


def test_lt_hold_on_other_key_press_and_layer_lookup() -> None:
    layers = make_layers()
    engine = InteractionEngine(layers, tapping_term=0.200)

    assert engine.on_key(0, 0, True, 3.000) == []
    events = engine.on_key(0, 1, True, 3.050)
    assert actions(events) == [
        ("MO(1)", True),
        ("KC_D", True),
    ]
    assert 1 in layers._momentary

    assert actions(engine.on_key(0, 1, False, 3.060)) == [("KC_D", False)]
    assert actions(engine.on_key(0, 0, False, 3.070)) == [("MO(1)", False)]


def test_interrupt_hold_can_be_disabled() -> None:
    engine = InteractionEngine(
        make_layers(),
        tapping_term=0.200,
        hold_on_other_key_press=False,
    )

    assert engine.on_key(0, 0, True, 3.100) == []
    assert actions(engine.on_key(0, 1, True, 3.150)) == [("KC_B", True)]
    assert actions(engine.on_key(0, 1, False, 3.160)) == [("KC_B", False)]
    assert actions(engine.on_key(0, 0, False, 3.170)) == [
        ("KC_A", True),
        ("KC_A", False),
    ]


def test_mt_tap_and_hold() -> None:
    engine = InteractionEngine(make_layers(), tapping_term=0.200)

    assert engine.on_key(0, 2, True, 4.000) == []
    assert actions(engine.on_key(0, 2, False, 4.050)) == [
        ("KC_C", True),
        ("KC_C", False),
    ]

    assert engine.on_key(0, 2, True, 5.000) == []
    assert actions(engine.on_tick(5.250)) == [("KC_LCTL", True)]
    assert actions(engine.on_key(0, 2, False, 5.260)) == [("KC_LCTL", False)]


def test_tap_hold_clear_before_timeout_drops_stale_hold_timer() -> None:
    engine = InteractionEngine(make_layers(), tapping_term=0.200)

    assert engine.on_key(0, 2, True, 5.500) == []
    assert actions(engine.clear_held_keys(reason="output_switch")) == []
    assert actions(engine.on_tick(5.750)) == []
    assert actions(engine.on_key(0, 2, False, 5.800)) == []


def test_tap_hold_output_switch_releases_active_hold_once() -> None:
    engine = InteractionEngine(make_layers(), tapping_term=0.200)

    assert engine.on_key(0, 2, True, 5.900) == []
    assert actions(engine.on_tick(6.150)) == [("KC_LCTL", True)]
    assert actions(engine.clear_held_keys(reason="output_switch")) == [("KC_LCTL", False)]
    assert actions(engine.on_key(0, 2, False, 6.200)) == []
    assert actions(engine.on_tick(6.300)) == []


def test_tt_tap_toggles_layer() -> None:
    engine = InteractionEngine(make_layers(), tapping_term=0.200)

    assert engine.on_key(0, 3, True, 6.000) == []
    assert actions(engine.on_key(0, 3, False, 6.050)) == [
        ("TG(1)", True),
        ("TG(1)", False),
    ]


def test_tt_hold_is_momentary_layer() -> None:
    engine = InteractionEngine(make_layers(), tapping_term=0.200)

    assert engine.on_key(0, 3, True, 7.000) == []
    assert actions(engine.on_tick(7.250)) == [("MO(1)", True)]
    assert actions(engine.on_key(0, 3, False, 7.300)) == [("MO(1)", False)]


def test_tt_interrupt_uses_momentary_layer_for_next_key() -> None:
    layers = make_layers()
    engine = InteractionEngine(layers, tapping_term=0.200)

    assert engine.on_key(0, 3, True, 8.000) == []
    assert actions(engine.on_key(0, 1, True, 8.050)) == [
        ("MO(1)", True),
        ("KC_D", True),
    ]
    assert actions(engine.on_key(0, 1, False, 8.060)) == [("KC_D", False)]
    assert actions(engine.on_key(0, 3, False, 8.070)) == [("MO(1)", False)]


def test_space_cadet_tap_parentheses() -> None:
    engine = InteractionEngine(make_layers(), tapping_term=0.200)

    assert engine.on_key(0, 4, True, 9.000) == []
    assert actions(engine.on_key(0, 4, False, 9.050)) == [
        ("LSFT(KC_9)", True),
        ("LSFT(KC_9)", False),
    ]

    assert engine.on_key(0, 5, True, 9.100) == []
    assert actions(engine.on_key(0, 5, False, 9.150)) == [
        ("RSFT(KC_0)", True),
        ("RSFT(KC_0)", False),
    ]


def test_space_cadet_hold_shift() -> None:
    engine = InteractionEngine(make_layers(), tapping_term=0.200)

    assert engine.on_key(0, 4, True, 10.000) == []
    assert actions(engine.on_tick(10.250)) == [("KC_LSFT", True)]
    assert actions(engine.on_key(0, 4, False, 10.300)) == [("KC_LSFT", False)]

    assert engine.on_key(0, 5, True, 10.400) == []
    assert actions(engine.on_tick(10.650)) == [("KC_RSFT", True)]
    assert actions(engine.on_key(0, 5, False, 10.700)) == [("KC_RSFT", False)]


def test_combo_suppresses_source_keys() -> None:
    engine = InteractionEngine(
        make_layers(),
        combo_term=0.050,
        combos=[{"keys": [(0, 1), (0, 6)], "action": "KC_ESC"}],
    )

    assert actions(engine.on_key(0, 1, True, 11.000)) == []
    assert actions(engine.on_key(0, 6, True, 11.030)) == [("KC_ESC", True)]
    assert actions(engine.on_key(0, 1, False, 11.040)) == []
    assert actions(engine.on_key(0, 6, False, 11.050)) == [("KC_ESC", False)]


def test_combo_term_miss_keeps_source_keys() -> None:
    engine = InteractionEngine(
        make_layers(),
        combo_term=0.050,
        combos=[{"keys": [(0, 1), (0, 6)], "action": "KC_ESC"}],
    )

    assert actions(engine.on_key(0, 1, True, 12.000)) == []
    assert actions(engine.on_key(0, 6, True, 12.100)) == [("KC_B", True)]
    assert actions(engine.on_key(0, 6, False, 12.110)) == [
        ("KC_E", True),
        ("KC_E", False),
    ]
    assert actions(engine.on_key(0, 1, False, 12.120)) == [("KC_B", False)]


def test_combo_prefers_longest_match() -> None:
    engine = InteractionEngine(
        make_layers(),
        combo_term=0.050,
        combos=[
            {"keys": [(0, 1), (0, 6)], "action": "KC_ESC"},
            {"keys": [(0, 1), (0, 5), (0, 6)], "action": "KC_TAB"},
        ],
    )

    assert actions(engine.on_key(0, 1, True, 13.000)) == []
    assert actions(engine.on_key(0, 5, True, 13.010)) == []
    assert actions(engine.on_key(0, 6, True, 13.020)) == [("KC_TAB", True)]
    assert actions(engine.on_key(0, 1, False, 13.030)) == []
    assert actions(engine.on_key(0, 5, False, 13.040)) == []
    assert actions(engine.on_key(0, 6, False, 13.050)) == [("KC_TAB", False)]


def test_combo_suppresses_tap_hold_source() -> None:
    engine = InteractionEngine(
        make_layers(),
        combo_term=0.050,
        combos=[{"keys": [(0, 0), (0, 6)], "action": "KC_ESC"}],
    )

    assert engine.on_key(0, 0, True, 14.000) == []
    assert actions(engine.on_key(0, 6, True, 14.020)) == [("KC_ESC", True)]
    assert actions(engine.on_tick(14.300)) == []
    assert actions(engine.on_key(0, 0, False, 14.310)) == []
    assert actions(engine.on_key(0, 6, False, 14.320)) == [("KC_ESC", False)]


def test_combo_source_key_is_delayed_until_term() -> None:
    engine = InteractionEngine(
        make_layers(),
        combo_term=0.050,
        combos=[{"keys": [(0, 1), (0, 6)], "action": "KC_ESC"}],
    )

    assert actions(engine.on_key(0, 1, True, 14.500)) == []
    assert actions(engine.on_tick(14.560)) == [("KC_B", True)]
    assert actions(engine.on_key(0, 1, False, 14.570)) == [("KC_B", False)]


def test_tap_dance_single_tap() -> None:
    engine = make_tap_dance_engine()

    assert engine.on_key(0, 7, True, 15.000) == []
    assert engine.on_key(0, 7, False, 15.020) == []
    assert actions(engine.on_tick(15.250)) == [
        ("KC_A", True),
        ("KC_A", False),
    ]


def test_tap_dance_double_tap_and_stale_timer() -> None:
    engine = make_tap_dance_engine()

    assert engine.on_key(0, 7, True, 16.000) == []
    assert engine.on_key(0, 7, False, 16.020) == []
    assert engine.on_key(0, 7, True, 16.100) == []
    assert engine.on_key(0, 7, False, 16.120) == []
    assert actions(engine.on_tick(16.230)) == []
    assert actions(engine.on_tick(16.350)) == [
        ("KC_ESC", True),
        ("KC_ESC", False),
    ]


def test_tap_dance_clamps_to_max_defined_count() -> None:
    engine = make_tap_dance_engine()

    for base in (17.000, 17.050, 17.100, 17.150):
        assert engine.on_key(0, 7, True, base) == []
        assert engine.on_key(0, 7, False, base + 0.010) == []
    assert actions(engine.on_tick(17.400)) == [
        ("KC_TAB", True),
        ("KC_TAB", False),
    ]


def test_tap_dance_hold() -> None:
    engine = make_tap_dance_engine()

    assert engine.on_key(0, 7, True, 17.500) == []
    assert actions(engine.on_tick(17.750)) == [("KC_LSFT", True)]
    assert actions(engine.on_key(0, 7, False, 17.800)) == [("KC_LSFT", False)]
    assert actions(engine.on_tick(18.000)) == []


def test_tap_dance_per_entry_term() -> None:
    engine = InteractionEngine(
        make_layers(),
        tap_dance_term=0.500,
        tap_dances={"TD0": {1: "KC_A", "hold": "KC_LSFT", "term": 0.050}},
    )

    assert engine.on_key(0, 7, True, 17.000) == []
    assert actions(engine.on_tick(17.060)) == [("KC_LSFT", True)]
    assert actions(engine.on_key(0, 7, False, 17.070)) == [("KC_LSFT", False)]


def test_tap_dance_tap_hold_and_quick_double_tap() -> None:
    engine = make_tap_dance_engine()

    assert engine.on_key(0, 7, True, 17.900) == []
    assert engine.on_key(0, 7, False, 17.920) == []
    assert engine.on_key(0, 7, True, 18.000) == []
    assert actions(engine.on_tick(18.250)) == [("KC_LCTL", True)]
    assert actions(engine.on_key(0, 7, False, 18.300)) == [("KC_LCTL", False)]

    engine = make_tap_dance_engine()
    assert engine.on_key(0, 7, True, 18.400) == []
    assert engine.on_key(0, 7, False, 18.420) == []
    assert engine.on_key(0, 7, True, 18.500) == []
    assert engine.on_key(0, 7, False, 18.520) == []
    assert actions(engine.on_tick(18.750)) == [
        ("KC_ESC", True),
        ("KC_ESC", False),
    ]


def test_tap_dance_tap_hold_ignores_stale_single_tap_timer() -> None:
    engine = make_tap_dance_engine()

    assert engine.on_key(0, 7, True, 18.800) == []
    assert engine.on_key(0, 7, False, 18.820) == []
    assert engine.on_key(0, 7, True, 18.900) == []
    assert actions(engine.on_tick(19.030)) == []
    assert actions(engine.on_tick(19.110)) == [("KC_LCTL", True)]
    assert actions(engine.on_key(0, 7, False, 19.140)) == [("KC_LCTL", False)]
    assert actions(engine.on_tick(19.400)) == []


def test_tap_dance_quick_double_tap_uses_second_release_timeout() -> None:
    engine = make_tap_dance_engine()

    assert engine.on_key(0, 7, True, 19.500) == []
    assert engine.on_key(0, 7, False, 19.520) == []
    assert engine.on_key(0, 7, True, 19.600) == []
    assert engine.on_key(0, 7, False, 19.620) == []
    assert actions(engine.on_tick(19.730)) == []
    assert actions(engine.on_tick(19.830)) == [
        ("KC_ESC", True),
        ("KC_ESC", False),
    ]
    assert actions(engine.on_tick(20.000)) == []


def test_key_override_single_trigger_and_release_pinning() -> None:
    engine = InteractionEngine(
        make_layers(),
        key_overrides=[{"trigger": "KC_LSFT", "key": "KC_1", "replacement": "KC_ESC"}],
    )

    assert actions(engine.on_key(0, 8, True, 18.000)) == [("KC_LSFT", True)]
    assert actions(engine.on_key(0, 9, True, 18.010)) == [("KC_LSFT", False), ("KC_ESC", True)]
    assert engine.repeat_history == "KC_ESC"
    assert actions(engine.on_key(0, 9, False, 18.020)) == [("KC_ESC", False), ("KC_LSFT", True)]
    assert engine.repeat_history == "KC_ESC"
    assert actions(engine.on_key(0, 8, False, 18.030)) == [("KC_LSFT", False)]

    engine = InteractionEngine(
        make_layers(),
        key_overrides=[{"trigger": "KC_LSFT", "key": "KC_1", "replacement": "KC_ESC"}],
    )
    assert actions(engine.on_key(0, 8, True, 18.100)) == [("KC_LSFT", True)]
    assert actions(engine.on_key(0, 9, True, 18.110)) == [("KC_LSFT", False), ("KC_ESC", True)]
    assert actions(engine.on_key(0, 8, False, 18.120)) == []
    assert actions(engine.on_key(0, 9, False, 18.130)) == [("KC_ESC", False)]


def test_key_override_requires_all_triggers() -> None:
    engine = InteractionEngine(
        make_layers(),
        key_overrides=[{
            "trigger": ["KC_LSFT", "KC_LCTL"],
            "key": "KC_1",
            "replacement": "KC_TAB",
        }],
    )

    assert actions(engine.on_key(0, 8, True, 19.000)) == [("KC_LSFT", True)]
    assert actions(engine.on_key(0, 9, True, 19.010)) == [("KC_1", True)]
    assert actions(engine.on_key(0, 9, False, 19.020)) == [("KC_1", False)]
    assert actions(engine.on_key(1, 0, True, 19.030)) == [("KC_LCTL", True)]
    assert actions(engine.on_key(0, 9, True, 19.040)) == [("KC_LCTL", False), ("KC_LSFT", False), ("KC_TAB", True)]
    assert actions(engine.on_key(0, 9, False, 19.050)) == [("KC_TAB", False), ("KC_LCTL", True), ("KC_LSFT", True)]


def test_key_override_negative_trigger_and_layer_mask() -> None:
    engine = InteractionEngine(
        make_layers(),
        key_overrides=[{
            "trigger": "KC_LSFT",
            "negative_trigger": "KC_LCTL",
            "key": "KC_1",
            "replacement": "KC_TAB",
            "layers": 0x0001,
        }],
    )

    assert actions(engine.on_key(0, 8, True, 20.000)) == [("KC_LSFT", True)]
    assert actions(engine.on_key(0, 9, True, 20.010)) == [("KC_LSFT", False), ("KC_TAB", True)]
    assert actions(engine.on_key(0, 9, False, 20.020)) == [("KC_TAB", False), ("KC_LSFT", True)]
    assert actions(engine.on_key(1, 0, True, 20.030)) == [("KC_LCTL", True)]
    assert actions(engine.on_key(0, 9, True, 20.040)) == [("KC_1", True)]
    assert actions(engine.on_key(0, 9, False, 20.050)) == [("KC_1", False)]


def main() -> None:
    test_lt_tap_on_quick_release()
    test_lt_hold_after_timeout_tick()
    test_lt_delayed_release_processing_still_taps_without_prior_hold()
    test_lt_hold_on_other_key_press_and_layer_lookup()
    test_interrupt_hold_can_be_disabled()
    test_mt_tap_and_hold()
    test_tap_hold_clear_before_timeout_drops_stale_hold_timer()
    test_tap_hold_output_switch_releases_active_hold_once()
    test_tt_tap_toggles_layer()
    test_tt_hold_is_momentary_layer()
    test_tt_interrupt_uses_momentary_layer_for_next_key()
    test_space_cadet_tap_parentheses()
    test_space_cadet_hold_shift()
    test_combo_suppresses_source_keys()
    test_combo_term_miss_keeps_source_keys()
    test_combo_prefers_longest_match()
    test_combo_suppresses_tap_hold_source()
    test_tap_dance_single_tap()
    test_tap_dance_double_tap_and_stale_timer()
    test_tap_dance_clamps_to_max_defined_count()
    test_tap_dance_hold()
    test_tap_dance_per_entry_term()
    test_tap_dance_tap_hold_and_quick_double_tap()
    test_tap_dance_tap_hold_ignores_stale_single_tap_timer()
    test_tap_dance_quick_double_tap_uses_second_release_timeout()
    test_key_override_single_trigger_and_release_pinning()
    test_key_override_requires_all_triggers()
    test_key_override_negative_trigger_and_layer_mask()
    print("ok: interaction engine tap-hold behavior")


if __name__ == "__main__":
    main()
