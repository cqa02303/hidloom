"""Codec between internal action strings and the supported Vial keycode space."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from hidloom_paths import default_config_file
from logicd.shared_action_defs import (
    parse_shared_layer_action,
    shared_vial_custom_action_map,
    shared_vial_custom_action_reverse_map,
    shared_vial_layer_action_bases,
)

KEYCODES_PATH = Path(os.environ.get("VIALD_KEYCODES_PATH", str(default_config_file("keycodes.json"))))

# We currently advertise Vial protocol 0, so Vial GUI uses the v5 keycode table.
# These values intentionally mirror Vial/QMK's v5 layer-key ranges.
VIAL_KC_NO = 0x0000
VIAL_KC_TRNS = 0x0001
VIAL_QK_LAYER_TAP_BASE = 0x4000
VIAL_QK_LAYER_TAP_MAX = 0x4FFF
VIAL_V5_TO_BASE = 0x5010
VIAL_V5_MO_BASE = 0x5100
VIAL_V5_DF_BASE = 0x5200
VIAL_V5_TG_BASE = 0x5300
VIAL_V5_OSL_BASE = 0x5400
VIAL_V5_TAP_DANCE_BASE = 0x5700
VIAL_V5_USER_BASE = 0x5F80
VIAL_GUI_USER_BASE = 0x5CB3
VIAL_QK_MACRO_BASE = 0x7700
VIAL_QK_MACRO_MAX = 0x777F
VIAL_V5_MACRO_BASE = 0x5F12
VIAL_V5_MACRO_MAX = 0x5F91
VIAL_QK_OUTPUT_AUTO = 0x7C20
VIAL_QK_OUTPUT_USB = 0x7C21
VIAL_QK_OUTPUT_BLUETOOTH = 0x7C22

_VIAL_V5_SPECIAL_BY_ACTION = {
    "KC_MUTE": 168,
    "KC_VOLU": 169,
    "KC_VOLD": 170,
    "KC_MS_U": 240,
    "KC_MS_D": 241,
    "KC_MS_L": 242,
    "KC_MS_R": 243,
    "KC_BTN1": 244,
    "KC_BTN2": 245,
    "KC_BTN3": 246,
    "KC_BTN4": 247,
    "KC_BTN5": 248,
    "KC_WH_U": 249,
    "KC_WH_D": 250,
    "KC_WH_L": 251,
    "KC_WH_R": 252,
    "MS_ACL0": 253,
    "MS_ACL1": 254,
    "MS_ACL2": 255,
}

_ACTION_TO_VIAL_CUSTOM = shared_vial_custom_action_map(VIAL_V5_USER_BASE)
_VIAL_LAYER_ACTION_BASES = shared_vial_layer_action_bases()

_VIAL_LIGHTING_BY_ACTION = {
    # QMK underglow aliases often shown as RGB_* in Vial.
    "RGB_TOG": 0x7820,
    "RGB_MOD": 0x7821,
    "RGB_RMOD": 0x7822,
    "RGB_HUI": 0x7823,
    "RGB_HUD": 0x7824,
    "RGB_SAI": 0x7825,
    "RGB_SAD": 0x7826,
    "RGB_VAI": 0x7827,
    "RGB_VAD": 0x7828,
    "RGB_SPI": 0x7829,
    "RGB_SPD": 0x782A,
    # QMK RGB Matrix aliases.
    "RM_ON": 0x7840,
    "RM_OFF": 0x7841,
    "RM_TOGG": 0x7842,
    "RM_NEXT": 0x7843,
    "RM_PREV": 0x7844,
    "RM_HUEU": 0x7845,
    "RM_HUED": 0x7846,
    "RM_SATU": 0x7847,
    "RM_SATD": 0x7848,
    "RM_VALU": 0x7849,
    "RM_VALD": 0x784A,
    "RM_SPDU": 0x784B,
    "RM_SPDD": 0x784C,
}
_VIAL_LIGHTING_ALIASES = {
    "RGB_TOGGLE": "RGB_TOG",
    "RGB_MODE_FORWARD": "RGB_MOD",
    "RGB_MODE_REVERSE": "RGB_RMOD",
    "RGB_HUE_UP": "RGB_HUI",
    "RGB_HUE_DOWN": "RGB_HUD",
    "RGB_SAT_UP": "RGB_SAI",
    "RGB_SAT_DOWN": "RGB_SAD",
    "RGB_VAL_UP": "RGB_VAI",
    "RGB_VAL_DOWN": "RGB_VAD",
    "RGB_SPEED_UP": "RGB_SPI",
    "RGB_SPEED_DOWN": "RGB_SPD",
    "RM_TOG": "RM_TOGG",
}
_VIAL_MEDIA_ALIASES = {
    "KC_AUDIO_MUTE": "KC_MUTE",
    "KC_AUDIO_VOL_UP": "KC_VOLU",
    "KC_AUDIO_VOL_DOWN": "KC_VOLD",
    "KC_KB_MUTE": "KC_MUTE",
    "KC_KB_VOLUME_UP": "KC_VOLU",
    "KC_KB_VOLUME_DOWN": "KC_VOLD",
}
_VIAL_MOUSE_ALIASES = {
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
_ACTION_BY_VIAL_LIGHTING = {
    value: action
    for action, value in _VIAL_LIGHTING_BY_ACTION.items()
}
_VIAL_OUTPUT_BY_ACTION = {
    "KC_CONNAUTO": VIAL_QK_OUTPUT_AUTO,
    "KC_USB": VIAL_QK_OUTPUT_USB,
    "KC_BT": VIAL_QK_OUTPUT_BLUETOOTH,
}
_ACTION_BY_VIAL_OUTPUT = {
    value: action
    for action, value in _VIAL_OUTPUT_BY_ACTION.items()
}
_LAYER_TAP_RE = re.compile(r"^LT\((\d+),\s*([^)]+)\)$")


def _tap_dance_index_from_action(action: str) -> int | None:
    if not action.startswith("TD(") or not action.endswith(")"):
        return None
    name = action[3:-1].strip()
    if name.startswith("TD") and name[2:].isdigit():
        return int(name[2:])
    if name.isdigit():
        return int(name)
    return None


def _macro_index_from_action(action: str) -> int | None:
    if not action.startswith("MACRO:VIAL"):
        return None
    suffix = action[len("MACRO:VIAL"):]
    if suffix.isdigit():
        return int(suffix)
    return None


class KeycodeCodec:
    def __init__(self, keycodes_path: Path = KEYCODES_PATH) -> None:
        raw = json.loads(keycodes_path.read_text(encoding="utf-8"))
        self._hid_by_action = {
            action: int(meta["hid"])
            for action, meta in raw.items()
            if not action.startswith("_") and isinstance(meta, dict) and "hid" in meta
        }
        self._action_by_hid: dict[int, str] = {}
        for action, hid in self._hid_by_action.items():
            if action.startswith("KC_"):
                self._action_by_hid.setdefault(hid, action)
        self._action_by_vial_special = {value: action for action, value in _VIAL_V5_SPECIAL_BY_ACTION.items()}
        self._action_by_vial_custom = shared_vial_custom_action_reverse_map(VIAL_V5_USER_BASE)
        self._action_by_vial_custom.update(shared_vial_custom_action_reverse_map(VIAL_GUI_USER_BASE))

    def _basic_action_to_vial(self, action: str) -> int:
        action = _VIAL_MEDIA_ALIASES.get(action, action)
        action = _VIAL_MOUSE_ALIASES.get(action, action)
        action = _VIAL_LIGHTING_ALIASES.get(action, action)
        if action == "KC_NONE":
            return VIAL_KC_NO
        if action == "KC_TRNS":
            return VIAL_KC_TRNS
        if action in _VIAL_V5_SPECIAL_BY_ACTION:
            return _VIAL_V5_SPECIAL_BY_ACTION[action]
        if action.startswith("KC_"):
            return self._hid_by_action.get(action, VIAL_KC_NO)
        return VIAL_KC_NO

    def _basic_vial_to_action(self, keycode: int) -> str | None:
        if keycode == VIAL_KC_NO:
            return "KC_NONE"
        if keycode == VIAL_KC_TRNS:
            return "KC_TRNS"
        if keycode in self._action_by_vial_special:
            return self._action_by_vial_special[keycode]
        return self._action_by_hid.get(keycode)

    def action_to_vial(self, action: str) -> int:
        """Encode a currently supported internal action to a Vial keycode."""
        action = _VIAL_MEDIA_ALIASES.get(action, action)
        action = _VIAL_MOUSE_ALIASES.get(action, action)
        action = _VIAL_LIGHTING_ALIASES.get(action, action)
        if action == "KC_NONE":
            return VIAL_KC_NO
        if action == "KC_TRNS":
            return VIAL_KC_TRNS
        layer_tap = _LAYER_TAP_RE.fullmatch(action)
        if layer_tap:
            layer = int(layer_tap.group(1))
            tap_keycode = self._basic_action_to_vial(layer_tap.group(2).strip())
            if 0 <= layer < 16 and 0 < tap_keycode <= 0xFF:
                return VIAL_QK_LAYER_TAP_BASE | (layer << 8) | tap_keycode
            return VIAL_KC_NO
        macro_index = _macro_index_from_action(action)
        if macro_index is not None:
            if 0 <= macro_index <= 0x7F:
                return VIAL_QK_MACRO_BASE | macro_index
            return VIAL_KC_NO
        tap_dance_index = _tap_dance_index_from_action(action)
        if tap_dance_index is not None:
            if 0 <= tap_dance_index <= 0xFF:
                return VIAL_V5_TAP_DANCE_BASE | tap_dance_index
            return VIAL_KC_NO
        if action in _VIAL_V5_SPECIAL_BY_ACTION:
            return _VIAL_V5_SPECIAL_BY_ACTION[action]
        if action in _ACTION_TO_VIAL_CUSTOM:
            return _ACTION_TO_VIAL_CUSTOM[action]
        if action in _VIAL_LIGHTING_BY_ACTION:
            return _VIAL_LIGHTING_BY_ACTION[action]
        if action in _VIAL_OUTPUT_BY_ACTION:
            return _VIAL_OUTPUT_BY_ACTION[action]
        if action.startswith("KC_"):
            return self._hid_by_action.get(action, VIAL_KC_NO)
        parsed_layer_action = parse_shared_layer_action(action)
        if parsed_layer_action is not None:
            kind, layer = parsed_layer_action
            if kind == "TO":
                if 0 <= layer < 16:
                    return VIAL_V5_TO_BASE | layer
                return VIAL_KC_NO
            if kind in {"MO", "TG", "DF"} and 0 <= layer < 32:
                return _VIAL_LAYER_ACTION_BASES[kind] | layer
            if kind == "OSL" and 0 <= layer < 32:
                return VIAL_V5_OSL_BASE | layer
        return VIAL_KC_NO

    def vial_to_action(self, keycode: int) -> str | None:
        """Decode a supported Vial keycode to an internal action."""
        if keycode == VIAL_KC_NO:
            return "KC_NONE"
        if keycode == VIAL_KC_TRNS:
            return "KC_TRNS"
        if VIAL_QK_LAYER_TAP_BASE <= keycode <= VIAL_QK_LAYER_TAP_MAX:
            layer = (keycode >> 8) & 0x0F
            tap_action = self._basic_vial_to_action(keycode & 0xFF)
            if tap_action in {None, "KC_NONE"}:
                return None
            return f"LT({layer},{tap_action})"
        if VIAL_V5_TO_BASE <= keycode < VIAL_V5_TO_BASE + 16:
            return f"TO({keycode - VIAL_V5_TO_BASE})"
        if VIAL_V5_MO_BASE <= keycode < VIAL_V5_MO_BASE + 32:
            return f"MO({keycode - VIAL_V5_MO_BASE})"
        if VIAL_V5_DF_BASE <= keycode < VIAL_V5_DF_BASE + 32:
            return f"DF({keycode - VIAL_V5_DF_BASE})"
        if VIAL_V5_TG_BASE <= keycode < VIAL_V5_TG_BASE + 32:
            return f"TG({keycode - VIAL_V5_TG_BASE})"
        if VIAL_V5_OSL_BASE <= keycode < VIAL_V5_OSL_BASE + 32:
            return f"OSL({keycode - VIAL_V5_OSL_BASE})"
        if VIAL_V5_TAP_DANCE_BASE <= keycode < VIAL_V5_TAP_DANCE_BASE + 0x100:
            return f"TD(TD{keycode - VIAL_V5_TAP_DANCE_BASE})"
        if VIAL_QK_MACRO_BASE <= keycode <= VIAL_QK_MACRO_MAX:
            return f"MACRO:VIAL{keycode - VIAL_QK_MACRO_BASE}"
        if keycode in self._action_by_vial_special:
            return self._action_by_vial_special[keycode]
        if keycode in self._action_by_vial_custom:
            return self._action_by_vial_custom[keycode]
        if VIAL_V5_MACRO_BASE <= keycode <= VIAL_V5_MACRO_MAX:
            return f"MACRO:VIAL{keycode - VIAL_V5_MACRO_BASE}"
        if keycode in _ACTION_BY_VIAL_LIGHTING:
            return _ACTION_BY_VIAL_LIGHTING[keycode]
        if keycode in _ACTION_BY_VIAL_OUTPUT:
            return _ACTION_BY_VIAL_OUTPUT[keycode]
        return self._action_by_hid.get(keycode)
