#!/usr/bin/env python3
"""Regression tests for logicd.action_expansion."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.action_expansion import (  # noqa: E402
    ActionStep,
    canonical_aliases_snapshot,
    canonicalize_action_alias,
    expand_action_event,
    expand_tap_action,
    space_cadet_tap_hold,
)


def steps(items: list[ActionStep]) -> list[tuple[str, bool]]:
    return [(item.action, item.is_press) for item in items]


def test_unknown_action_passthrough() -> None:
    assert steps(expand_action_event("KC_A", True)) == [("KC_A", True)]
    assert steps(expand_action_event("KC_A", False)) == [("KC_A", False)]


def test_modifier_wrapper_press_release() -> None:
    assert steps(expand_action_event("S(KC_1)", True)) == [
        ("KC_LSFT", True),
        ("KC_1", True),
    ]
    assert steps(expand_action_event("S(KC_1)", False)) == [
        ("KC_1", False),
        ("KC_LSFT", False),
    ]

    assert steps(expand_action_event("LCTL(KC_A)", True)) == [
        ("KC_LCTL", True),
        ("KC_A", True),
    ]
    assert steps(expand_action_event("LCTL(KC_A)", False)) == [
        ("KC_A", False),
        ("KC_LCTL", False),
    ]


def test_nested_modifier_wrappers() -> None:
    assert steps(expand_action_event("LCTL(S(KC_A))", True)) == [
        ("KC_LCTL", True),
        ("KC_LSFT", True),
        ("KC_A", True),
    ]
    assert steps(expand_action_event("LCTL(S(KC_A))", False)) == [
        ("KC_A", False),
        ("KC_LSFT", False),
        ("KC_LCTL", False),
    ]

    assert steps(expand_tap_action("LALT(LGUI(KC_TAB))")) == [
        ("KC_LALT", True),
        ("KC_LGUI", True),
        ("KC_TAB", True),
        ("KC_TAB", False),
        ("KC_LGUI", False),
        ("KC_LALT", False),
    ]

    assert steps(expand_tap_action("LSFT(LGUI(KC_F23))")) == [
        ("KC_LSFT", True),
        ("KC_LGUI", True),
        ("KC_F23", True),
        ("KC_F23", False),
        ("KC_LGUI", False),
        ("KC_LSFT", False),
    ]


def test_shifted_aliases() -> None:
    assert steps(expand_action_event("KC_EXLM", True)) == [
        ("KC_LSFT", True),
        ("KC_1", True),
    ]
    assert steps(expand_action_event("KC_EXLM", False)) == [
        ("KC_1", False),
        ("KC_LSFT", False),
    ]

    assert steps(expand_action_event("KC_PLUS", True)) == [
        ("KC_LSFT", True),
        ("KC_EQL", True),
    ]
    assert steps(expand_action_event("KC_PIPE", False)) == [
        ("KC_BSLS", False),
        ("KC_LSFT", False),
    ]


def test_canonical_aliases() -> None:
    aliases = canonical_aliases_snapshot()
    assert aliases["KC_CAPS_LOCK"] == "KC_CAPSLOCK"
    assert aliases["KC_PAGE_UP"] == "KC_PGUP"
    assert aliases["KC_RETURN"] == "KC_ENTER"
    assert canonicalize_action_alias("KC_APOSTROPHE") == "KC_QUOTE"
    assert canonicalize_action_alias("KC_A") == "KC_A"
    assert steps(expand_action_event("KC_CAPS_LOCK", True)) == [("KC_CAPSLOCK", True)]
    assert steps(expand_action_event("KC_PAGE_DOWN", False)) == [("KC_PGDN", False)]
    assert steps(expand_tap_action("LCTL(KC_RETURN)")) == [
        ("KC_LCTL", True),
        ("KC_ENTER", True),
        ("KC_ENTER", False),
        ("KC_LCTL", False),
    ]


def test_tap_expansion_order() -> None:
    assert steps(expand_tap_action("S(KC_9)")) == [
        ("KC_LSFT", True),
        ("KC_9", True),
        ("KC_9", False),
        ("KC_LSFT", False),
    ]


def test_space_cadet_mapping() -> None:
    assert space_cadet_tap_hold("SC_LSPO") == ("LSFT(KC_9)", "KC_LSFT")
    assert space_cadet_tap_hold("KC_RSPC") == ("RSFT(KC_0)", "KC_RSFT")
    assert space_cadet_tap_hold("KC_A") is None


def main() -> None:
    test_unknown_action_passthrough()
    test_modifier_wrapper_press_release()
    test_nested_modifier_wrappers()
    test_shifted_aliases()
    test_canonical_aliases()
    test_tap_expansion_order()
    test_space_cadet_mapping()
    print("ok: action expansion")


if __name__ == "__main__":
    main()
