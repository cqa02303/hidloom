#!/usr/bin/env python3
"""Local smoke test for the Vial keycode codec."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from viald.keycode_codec import (  # noqa: E402
    VIAL_KC_NO,
    VIAL_KC_TRNS,
    VIAL_QK_LAYER_TAP_BASE,
    VIAL_V5_DF_BASE,
    VIAL_V5_MO_BASE,
    VIAL_V5_OSL_BASE,
    VIAL_V5_TAP_DANCE_BASE,
    VIAL_V5_TG_BASE,
    VIAL_V5_TO_BASE,
    VIAL_GUI_USER_BASE,
    VIAL_QK_OUTPUT_AUTO,
    VIAL_QK_OUTPUT_BLUETOOTH,
    VIAL_QK_OUTPUT_USB,
    VIAL_V5_USER_BASE,
    KeycodeCodec,
)


def assert_roundtrip(codec: KeycodeCodec, action: str) -> None:
    keycode = codec.action_to_vial(action)
    decoded = codec.vial_to_action(keycode)
    assert decoded == action, f"{action}: encoded 0x{keycode:04x}, decoded {decoded!r}"


def main() -> None:
    codec = KeycodeCodec()

    assert codec.action_to_vial("KC_NONE") == VIAL_KC_NO
    assert codec.vial_to_action(VIAL_KC_NO) == "KC_NONE"
    assert codec.action_to_vial("KC_TRNS") == VIAL_KC_TRNS
    assert codec.vial_to_action(VIAL_KC_TRNS) == "KC_TRNS"

    for action in (
        "KC_A",
        "KC_ESC",
        "KC_F12",
        "KC_EXECUTE",
        "KC_HELP",
        "KC_MENU",
        "KC_SELECT",
        "KC_STOP",
        "KC_AGAIN",
        "KC_ALTERNATE_ERASE",
        "KC_SYSTEM_REQUEST",
        "KC_KP_EQUAL_AS400",
        "KC_CANCEL",
        "KC_CLEAR",
        "KC_PRIOR",
        "KC_SEPARATOR",
        "KC_OUT",
        "KC_OPER",
        "KC_CLEAR_AGAIN",
        "KC_CRSEL",
        "KC_EXSEL",
        "KC_LANG6",
        "KC_LANG7",
        "KC_LANG8",
        "KC_LANG9",
        "KC_LOCKING_CAPS_LOCK",
        "KC_LOCKING_NUM_LOCK",
        "KC_LOCKING_SCROLL_LOCK",
        "KC_MUTE",
        "KC_VOLU",
        "KC_VOLD",
        "KC_MS_U",
        "KC_WH_R",
        "MS_ACL0",
        "MS_ACL1",
        "MS_ACL2",
    ):
        assert_roundtrip(codec, action)

    assert codec.action_to_vial("KC_LANGUAGE_6") == codec.action_to_vial("KC_LANG6")
    assert codec.action_to_vial("KC_LANGUAGE_7") == codec.action_to_vial("KC_LANG7")
    assert codec.action_to_vial("KC_LANGUAGE_8") == codec.action_to_vial("KC_LANG8")
    assert codec.action_to_vial("KC_LANGUAGE_9") == codec.action_to_vial("KC_LANG9")
    assert codec.action_to_vial("KC_HENK") == codec.action_to_vial("KC_HENKAN")
    assert codec.action_to_vial("KC_MHEN") == codec.action_to_vial("KC_MUHENKAN")

    assert codec.action_to_vial("KC_AUDIO_MUTE") == codec.action_to_vial("KC_MUTE")
    assert codec.action_to_vial("KC_AUDIO_VOL_UP") == codec.action_to_vial("KC_VOLU")
    assert codec.action_to_vial("KC_AUDIO_VOL_DOWN") == codec.action_to_vial("KC_VOLD")
    assert codec.action_to_vial("KC_KB_MUTE") == codec.action_to_vial("KC_MUTE")
    assert codec.action_to_vial("KC_KB_VOLUME_UP") == codec.action_to_vial("KC_VOLU")
    assert codec.action_to_vial("KC_KB_VOLUME_DOWN") == codec.action_to_vial("KC_VOLD")
    assert codec.action_to_vial("MS_BTN1") == codec.action_to_vial("KC_BTN1")
    assert codec.action_to_vial("MS_BTN2") == codec.action_to_vial("KC_BTN2")
    assert codec.action_to_vial("MS_BTN3") == codec.action_to_vial("KC_BTN3")
    assert codec.action_to_vial("MS_BTN4") == codec.action_to_vial("KC_BTN4")
    assert codec.action_to_vial("MS_BTN5") == codec.action_to_vial("KC_BTN5")
    assert codec.action_to_vial("MS_UP") == codec.action_to_vial("KC_MS_U")
    assert codec.action_to_vial("MS_DOWN") == codec.action_to_vial("KC_MS_D")
    assert codec.action_to_vial("MS_LEFT") == codec.action_to_vial("KC_MS_L")
    assert codec.action_to_vial("MS_RGHT") == codec.action_to_vial("KC_MS_R")
    assert codec.action_to_vial("MS_RIGHT") == codec.action_to_vial("KC_MS_R")
    assert codec.action_to_vial("MS_WHLU") == codec.action_to_vial("KC_WH_U")
    assert codec.action_to_vial("MS_WHLD") == codec.action_to_vial("KC_WH_D")
    assert codec.action_to_vial("MS_WHLL") == codec.action_to_vial("KC_WH_L")
    assert codec.action_to_vial("MS_WHLR") == codec.action_to_vial("KC_WH_R")

    lighting_actions = (
        "RGB_TOG",
        "RGB_MOD",
        "RGB_RMOD",
        "RGB_HUI",
        "RGB_HUD",
        "RGB_SAI",
        "RGB_SAD",
        "RGB_VAI",
        "RGB_VAD",
        "RGB_SPI",
        "RGB_SPD",
        "RM_ON",
        "RM_OFF",
        "RM_TOGG",
        "RM_NEXT",
        "RM_PREV",
        "RM_HUEU",
        "RM_HUED",
        "RM_SATU",
        "RM_SATD",
        "RM_VALU",
        "RM_VALD",
        "RM_SPDU",
        "RM_SPDD",
    )
    for action in lighting_actions:
        assert_roundtrip(codec, action)

    assert codec.action_to_vial("RGB_TOGGLE") == codec.action_to_vial("RGB_TOG")
    assert codec.action_to_vial("RGB_MODE_FORWARD") == codec.action_to_vial("RGB_MOD")
    assert codec.action_to_vial("RM_TOG") == codec.action_to_vial("RM_TOGG")

    for action in (
        "MO(0)", "MO(1)", "MO(31)",
        "TG(0)", "TG(1)", "TG(31)",
        "TO(0)", "TO(1)", "TO(15)",
        "DF(0)", "DF(1)", "DF(31)",
        "OSL(0)", "OSL(1)", "OSL(31)",
        "KC_CONNAUTO", "KC_USB", "KC_BT",
        "CAPS_WORD", "REPEAT_KEY", "ALT_REPEAT_KEY",
        "LT(1,KC_1)", "LT(2,KC_A)",
    ):
        assert_roundtrip(codec, action)

    assert codec.action_to_vial("MO(32)") == VIAL_KC_NO
    assert codec.action_to_vial("TG(32)") == VIAL_KC_NO
    assert codec.action_to_vial("TO(16)") == VIAL_KC_NO
    assert codec.action_to_vial("DF(32)") == VIAL_KC_NO
    assert codec.action_to_vial("OSL(32)") == VIAL_KC_NO
    assert codec.action_to_vial("LT(16,KC_A)") == VIAL_KC_NO
    assert codec.action_to_vial("LT(1,SCRIPT(foo))") == VIAL_KC_NO
    assert codec.action_to_vial("LT(1,KC_1)") == VIAL_QK_LAYER_TAP_BASE | (1 << 8) | 0x1E
    assert codec.vial_to_action(VIAL_QK_LAYER_TAP_BASE | (1 << 8) | 0x1E) == "LT(1,KC_1)"
    assert codec.vial_to_action(VIAL_V5_TO_BASE + 16) is None
    assert codec.vial_to_action(VIAL_V5_MO_BASE + 32) is None
    assert codec.vial_to_action(VIAL_V5_DF_BASE + 32) is None
    assert codec.vial_to_action(VIAL_V5_TG_BASE + 32) is None
    assert codec.vial_to_action(VIAL_V5_OSL_BASE + 32) is None
    assert codec.vial_to_action(VIAL_QK_OUTPUT_AUTO) == "KC_CONNAUTO"
    assert codec.vial_to_action(VIAL_QK_OUTPUT_USB) == "KC_USB"
    assert codec.vial_to_action(VIAL_QK_OUTPUT_BLUETOOTH) == "KC_BT"

    custom_actions = (
        "KC_SH0",
        "KC_SH1",
        "KC_SH10",
        "KC_CONNAUTO",
        "KC_CONSOLE",
        "KC_USB",
        "BT_STATUS",
        "BT_POWER_ON",
        "BT_POWER_OFF",
        "BT_POWER_TOGGLE",
        "BT_PAIRING_ON",
        "BT_PAIRING_OFF",
        "BT_PAIRING_TOGGLE",
        "BT_DISCONNECT",
        "BT_FORGET_DEVICE",
        "OSL(0)",
        "OSL(1)",
        "OSL(31)",
        "MT(KC_LSFT,KC_A)",
        "TT(2)",
        "TD(TD0)",
        "KC_SHUTDOWN",
        "KC_BT",
        "CAPS_WORD",
        "REPEAT_KEY",
        "ALT_REPEAT_KEY",
    )
    for action in custom_actions:
        assert_roundtrip(codec, action)

    assert codec.vial_to_action(VIAL_V5_USER_BASE) == "KC_SH0"
    assert codec.vial_to_action(VIAL_V5_USER_BASE + 14) == "BT_STATUS"
    assert codec.vial_to_action(VIAL_V5_USER_BASE + 22) == "BT_FORGET_DEVICE"
    assert codec.vial_to_action(VIAL_V5_USER_BASE + 23) == "OSL(0)"
    assert codec.vial_to_action(VIAL_V5_USER_BASE + 54) == "OSL(31)"
    assert codec.vial_to_action(VIAL_V5_USER_BASE + 55) == "LT(2,KC_A)"
    assert codec.vial_to_action(VIAL_V5_USER_BASE + 56) == "MT(KC_LSFT,KC_A)"
    assert codec.vial_to_action(VIAL_V5_USER_BASE + 57) == "TT(2)"
    assert codec.vial_to_action(VIAL_V5_USER_BASE + 58) == "TD(TD0)"
    assert codec.vial_to_action(VIAL_V5_USER_BASE + 59) == "KC_SHUTDOWN"
    assert codec.vial_to_action(VIAL_V5_USER_BASE + 60) == "KC_BT"
    assert codec.vial_to_action(VIAL_V5_USER_BASE + 61) == "CAPS_WORD"
    assert codec.vial_to_action(VIAL_V5_USER_BASE + 62) == "REPEAT_KEY"
    assert codec.vial_to_action(VIAL_V5_USER_BASE + 63) == "ALT_REPEAT_KEY"
    assert codec.vial_to_action(VIAL_V5_OSL_BASE) == "OSL(0)"
    assert codec.vial_to_action(VIAL_V5_OSL_BASE + 31) == "OSL(31)"
    assert codec.action_to_vial("TD(TD0)") == VIAL_V5_TAP_DANCE_BASE
    assert codec.action_to_vial("TD(1)") == VIAL_V5_TAP_DANCE_BASE + 1
    assert codec.vial_to_action(VIAL_V5_TAP_DANCE_BASE + 1) == "TD(TD1)"
    assert codec.action_to_vial("MACRO:VIAL0") == 0x7700
    assert codec.action_to_vial("MACRO:VIAL31") == 0x771F
    assert codec.vial_to_action(0x7701) == "MACRO:VIAL1"
    assert codec.vial_to_action(0x5F13) == "MACRO:VIAL1"
    assert codec.vial_to_action(VIAL_GUI_USER_BASE) == "KC_SH0"
    assert codec.vial_to_action(VIAL_GUI_USER_BASE + 14) == "BT_STATUS"
    assert codec.vial_to_action(VIAL_GUI_USER_BASE + 23) == "OSL(0)"
    assert codec.vial_to_action(VIAL_GUI_USER_BASE + 59) == "KC_SHUTDOWN"
    assert codec.vial_to_action(VIAL_GUI_USER_BASE + 60) == "KC_BT"
    assert codec.vial_to_action(VIAL_GUI_USER_BASE + 61) == "CAPS_WORD"
    assert codec.vial_to_action(VIAL_GUI_USER_BASE + 62) == "REPEAT_KEY"
    assert codec.vial_to_action(VIAL_GUI_USER_BASE + 63) == "ALT_REPEAT_KEY"
    assert codec.action_to_vial("SCRIPT(foo)") == VIAL_KC_NO
    assert codec.action_to_vial("MACRO:hello") == VIAL_KC_NO

    print("ok: Vial keycode codec mappings are coherent")


if __name__ == "__main__":
    main()
