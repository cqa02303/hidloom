#!/usr/bin/env python3
"""Regression test for the Basic HID runtime completion slices."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "daemon" / "http"))

from layout_api import build_layout_payload  # noqa: E402
from logicd.hid_report import KEYCODE, HID_TO_LINUX, HidState  # noqa: E402
from viald.keycode_codec import KeycodeCodec  # noqa: E402


COMMAND_KEYS = {
    "KC_EXECUTE": 0x74,
    "KC_HELP": 0x75,
    "KC_MENU": 0x76,
    "KC_SELECT": 0x77,
    "KC_STOP": 0x78,
    "KC_AGAIN": 0x79,
    "KC_ALTERNATE_ERASE": 0x99,
    "KC_SYSTEM_REQUEST": 0x9A,
    "KC_CANCEL": 0x9B,
    "KC_CLEAR": 0x9C,
    "KC_PRIOR": 0x9D,
    "KC_SEPARATOR": 0x9F,
    "KC_OUT": 0xA0,
    "KC_OPER": 0xA1,
    "KC_CLEAR_AGAIN": 0xA2,
    "KC_CRSEL": 0xA3,
    "KC_EXSEL": 0xA4,
}

BASIC_HID_COMPLETION_KEYS = {
    **COMMAND_KEYS,
    "KC_KP_EQUAL_AS400": 0x86,
    "KC_HENK": 0x8A,
    "KC_MHEN": 0x8B,
    "KC_LANG6": 0x95,
    "KC_LANGUAGE_6": 0x95,
    "KC_LANG7": 0x96,
    "KC_LANGUAGE_7": 0x96,
    "KC_LANG8": 0x97,
    "KC_LANGUAGE_8": 0x97,
    "KC_LANG9": 0x98,
    "KC_LANGUAGE_9": 0x98,
    "KC_LOCKING_CAPS_LOCK": 0x82,
    "KC_LOCKING_NUM_LOCK": 0x83,
    "KC_LOCKING_SCROLL_LOCK": 0x84,
}

CANONICAL_BY_USAGE = {
    0x8A: "KC_INT4",
    0x8B: "KC_INT5",
    0x95: "KC_LANG6",
    0x96: "KC_LANG7",
    0x97: "KC_LANG8",
    0x98: "KC_LANG9",
}


async def _no_logicd_layers():
    return None


def main() -> None:
    raw = json.loads((ROOT / "config" / "default" / "keycodes.json").read_text(encoding="utf-8"))
    codec = KeycodeCodec()
    layout_payload = asyncio.run(build_layout_payload(_no_logicd_layers))

    for action, usage in BASIC_HID_COMPLETION_KEYS.items():
        assert raw[action]["hid"] == usage, action
        assert KEYCODE[action] == usage, action
        assert codec.action_to_vial(action) == usage, action
        assert codec.vial_to_action(usage) == CANONICAL_BY_USAGE.get(usage, action), action
        assert action in layout_payload["keycodes"], action

        state = HidState()
        state.press(usage)
        assert state.build() == bytes([0, 0, usage, 0, 0, 0, 0, 0]), action
        state.release(usage)
        assert state.build() == bytes(8), action

    assert 0x9A not in HID_TO_LINUX
    assert KEYCODE["KC_CAPSLOCK"] == 0x39
    assert KEYCODE["KC_NUMLOCK"] == 0x53
    assert KEYCODE["KC_SCROLLLOCK"] == 0x47
    assert KEYCODE["KC_LOCKING_CAPS_LOCK"] == 0x82
    assert KEYCODE["KC_LOCKING_NUM_LOCK"] == 0x83
    assert KEYCODE["KC_LOCKING_SCROLL_LOCK"] == 0x84
    assert "KC_SYSTEM_POWER" not in KEYCODE

    print("ok: Basic HID runtime completion slices are mapped")


if __name__ == "__main__":
    main()
