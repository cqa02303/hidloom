"""Shared action definition helpers.

This module centralizes small pieces of action metadata that are referenced
from multiple subsystems:

- logicd runtime parsing
- HTTP keymap validation
- Vial keycode codec
- tests

The goal is to reduce duplicated hardcoded action name lists.
"""
from __future__ import annotations

import re

from .action_expansion import is_modifier_wrapper, modifier_wrappers_snapshot
from .layer_action import parse_layer_action, layer_action_names


VIAL_LAYER_ACTION_BASES = {
    "MO": 0x5100,
    "TG": 0x5300,
    "DF": 0x5200,
}

CONNECTIVITY_ACTIONS = (
    "BT_STATUS",
    "BT_POWER_ON",
    "BT_POWER_OFF",
    "BT_POWER_TOGGLE",
    "BT_PAIRING_ON",
    "BT_PAIRING_OFF",
    "BT_PAIRING_TOGGLE",
    "BT_DISCONNECT",
    "BT_FORGET_DEVICE",
    "WIFI_STATUS",
    "WIFI_POWER_ON",
    "WIFI_POWER_OFF",
    "WIFI_POWER_TOGGLE",
)

# Vial GUI resolves USER00..USER63 only.  Do not add every connectivity action
# blindly here; WIFI_* is initially HTTP/runtime-only until the custom keycode
# space is redesigned.
VIAL_CUSTOM_ACTIONS = (
    "KC_SH0",
    "KC_SH1",
    "KC_SH2",
    "KC_SH3",
    "KC_SH4",
    "KC_SH5",
    "KC_SH6",
    "KC_SH7",
    "KC_SH8",
    "KC_SH9",
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
    *tuple(f"OSL({layer})" for layer in range(32)),
    "LT(2,KC_A)",
    "MT(KC_LSFT,KC_A)",
    "TT(2)",
    "TD(TD0)",
    "KC_SHUTDOWN",
    # Keep Vial custom names for actions the current Vial GUI shows poorly as
    # standard values. RGB_* actions use Vial/QMK's normal lighting keycode
    # space.
    "KC_BT",
    "CAPS_WORD",
    "REPEAT_KEY",
    "ALT_REPEAT_KEY",
)

_ANIMATION_ACTION_RE = re.compile(r"^ANIM\((\d+)\)$")
_UNICODE_ACTION_RE = re.compile(r"^U\+[0-9A-Fa-f]{1,6}$")
_MACRO_ACTION_RE = re.compile(r"^MACRO:[A-Za-z0-9_.-]{1,64}$")
_SCRIPT_ACTION_RE = re.compile(r"^SCRIPT\([A-Za-z0-9_.-]{1,64}\)$")


def shared_modifier_wrappers() -> tuple[str, ...]:
    """Return supported modifier wrapper names."""
    return tuple(sorted(modifier_wrappers_snapshot().keys()))


def shared_layer_actions() -> tuple[str, ...]:
    """Return supported layer action names."""
    return layer_action_names()


def shared_connectivity_actions() -> tuple[str, ...]:
    """Return runtime connectivity action names."""
    return CONNECTIVITY_ACTIONS


def shared_vial_layer_action_bases() -> dict[str, int]:
    """Return Vial base keycodes for layer actions using v5 encoding."""
    return dict(VIAL_LAYER_ACTION_BASES)


def shared_vial_custom_actions() -> tuple[str, ...]:
    """Return custom actions exposed through Vial user keycode space."""
    return VIAL_CUSTOM_ACTIONS


def shared_vial_custom_action_map(user_base: int) -> dict[str, int]:
    """Return action->keycode mapping for Vial custom action space."""
    return {
        action: user_base + idx
        for idx, action in enumerate(VIAL_CUSTOM_ACTIONS)
    }


def shared_vial_custom_action_reverse_map(user_base: int) -> dict[int, str]:
    """Return keycode->action mapping for Vial custom action space."""
    return {
        user_base + idx: action
        for idx, action in enumerate(VIAL_CUSTOM_ACTIONS)
    }


def parse_shared_layer_action(action: str) -> tuple[str, int] | None:
    """Return (operation, layer) for supported layer actions."""
    return parse_layer_action(action)


def is_layer_action(action: str) -> bool:
    """Return True when action is syntactically a supported layer action."""
    return parse_shared_layer_action(action) is not None


def is_layer_action_in_range(action: str, *, max_layers: int = 32) -> bool:
    """Return True when action is a supported layer action within range."""
    parsed = parse_shared_layer_action(action)
    if parsed is None:
        return False
    _, layer = parsed
    if layer == -1:
        return True
    return 0 <= layer < max_layers


def is_wrapper_action(action: str) -> bool:
    """Return True when action is a supported modifier wrapper action."""
    return is_modifier_wrapper(action)


def is_animation_action(action: str) -> bool:
    """Return True for ANIM(n) actions."""
    return bool(_ANIMATION_ACTION_RE.fullmatch(action))


def is_unicode_action(action: str) -> bool:
    """Return True for U+XXXX style unicode actions."""
    return bool(_UNICODE_ACTION_RE.fullmatch(action))


def is_macro_action(action: str) -> bool:
    """Return True for MACRO:name actions."""
    return bool(_MACRO_ACTION_RE.fullmatch(action))


def is_script_action(action: str) -> bool:
    """Return True for SCRIPT(name) actions."""
    return bool(_SCRIPT_ACTION_RE.fullmatch(action))
