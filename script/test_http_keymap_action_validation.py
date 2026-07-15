#!/usr/bin/env python3
"""Local smoke test for HTTP keymap action validation."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon" / "http"))

from keymap_actions import is_valid_keymap_action, normalize_keymap_action  # noqa: E402


def main() -> None:
    for action in (
        "KC_A",
        "KC_TRNS",
        "KC_SH10",
        "KC_BT",
        "KC_ZKHK",
        "RGB_TOG",
        "MO(0)",
        "MO(1)",
        "MO(31)",
        "TG(0)",
        "TG(7)",
        "TG(31)",
        "TO(0)",
        "TO(7)",
        "TO(31)",
        "DF(0)",
        "DF(7)",
        "DF(31)",
        "OSL(0)",
        "OSL(1)",
        "OSL(31)",
        "LT(0,KC_A)",
        "LT(1,KC_1)",
        "LT(31,KC_SPACE)",
        "MS_UP",
        "MS_BTN1",
        "MS_BTN5",
        "MS_WHLR",
        "KC_MPLY",
        "KC_BRIU",
        "KC_CAPS_LOCK",
        "KC_PAGE_UP",
        "KC_PAGE_DOWN",
        "KC_RETURN",
        "BT_STATUS",
        "BT_POWER_TOGGLE",
        "BT_PAIRING_TOGGLE",
        "BT_DISCONNECT",
        "BT_FORGET_DEVICE",
        "S(KC_1)",
        "LCTL(KC_A)",
        "LSFT(LGUI(KC_F23))",
        "LSFT(LGUI(KC_F23))　",
        "LSFT( LGUI(KC_F23) )",
        "LALT(LGUI(KC_TAB))",
        "RCTRL(RSFT(KC_ESC))",
        "TD(TD0)",
        "TD(nav.layer-1)",
        "MORSE(main)",
        "MORSE(nav.layer-1)",
        "CAPS_WORD",
        "REPEAT_KEY",
        "ALT_REPEAT_KEY",
        "QK_LAYER_LOCK",
        "QK_LLCK",
        "DRAG_LOCK",
    ):
        assert is_valid_keymap_action(action), action

    for action in (
        "",
        None,
        "MO(32)",
        "TG(99)",
        "TO(32)",
        "DF(99)",
        "OSL(32)",
        "LT(32,KC_A)",
        "LT(1,KC_NONE)",
        "LT(1,KC_TRNS)",
        "LT(1,SCRIPT(foo))",
        "MACRO:name",
        "U+3042",
        "KC_A;rm",
        "BT_POWER_TOGGLE;rm",
        "MO(-1)",
        "S()",
        "S(KC_A;rm)",
        "BAD(KC_A)",
        "LCTL(",
        "TD()",
        "TD(KC_A;rm)",
        "MORSE()",
        "MORSE(main;rm)",
    ):
        assert not is_valid_keymap_action(action), action

    assert normalize_keymap_action(" LSFT( LGUI(KC_F23) )　") == "LSFT(LGUI(KC_F23))"

    print("ok: HTTP keymap action validation accepts safe wrapper and BT actions")


if __name__ == "__main__":
    main()
