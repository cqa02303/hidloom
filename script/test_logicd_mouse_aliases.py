#!/usr/bin/env python3
"""Local smoke test for QMK mouse alias normalization."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.hid_report import KEYCODE  # noqa: E402
from logicd.macro import _MOUSE_ACTION_ALIASES, _MOUSE_ACCELERATION_PROFILES  # noqa: E402
from viald.keycode_codec import KeycodeCodec  # noqa: E402


def main() -> None:
    expected = {
        "MS_BTN1": "KC_BTN1",
        "MS_BTN2": "KC_BTN2",
        "MS_BTN3": "KC_BTN3",
        "MS_BTN4": "KC_BTN4",
        "MS_BTN5": "KC_BTN5",
        "MS_UP": "KC_MS_U",
        "MS_DOWN": "KC_MS_D",
        "MS_LEFT": "KC_MS_L",
        "MS_RGHT": "KC_MS_R",
        "MS_RIGHT": "KC_MS_R",
        "MS_WHLU": "KC_WH_U",
        "MS_WHLD": "KC_WH_D",
        "MS_WHLL": "KC_WH_L",
        "MS_WHLR": "KC_WH_R",
    }
    assert _MOUSE_ACTION_ALIASES == expected
    for alias, canonical in expected.items():
        assert KEYCODE[canonical] >= 0x200, alias
    assert _MOUSE_ACCELERATION_PROFILES == {
        "MS_ACL0": (2, 1),
        "MS_ACL1": (5, 3),
        "MS_ACL2": (12, 6),
    }
    codec = KeycodeCodec()
    for index, action in enumerate(("MS_BTN1", "MS_BTN2", "MS_BTN3", "MS_BTN4", "MS_BTN5"), start=1):
        canonical = f"KC_BTN{index}"
        assert KEYCODE[action] == KEYCODE[canonical], action
        assert codec.action_to_vial(action) == codec.action_to_vial(canonical), action
    for index, action in enumerate(("MS_ACL0", "MS_ACL1", "MS_ACL2")):
        assert KEYCODE[action] == 0x210 + index
        assert codec.action_to_vial(action) == 253 + index
        assert codec.vial_to_action(253 + index) == action

    print("ok: QMK mouse aliases and acceleration keys map to Mouse HID keycodes")


if __name__ == "__main__":
    main()
