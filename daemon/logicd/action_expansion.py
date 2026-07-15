"""Action expansion helpers.

This module converts wrapper/alias actions into concrete press/release action
sequences while keeping InteractionEngine focused on state and timing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_WRAPPER_RE = re.compile(r"^([A-Z0-9_]+)\((.+)\)$")
_SAFE_ACTION_RE = re.compile(r"^[A-Za-z0-9_]+$")

_MOD_WRAPPERS = {
    "C": "KC_LCTL",
    "CTL": "KC_LCTL",
    "CTRL": "KC_LCTL",
    "LCTL": "KC_LCTL",
    "LCTRL": "KC_LCTL",
    "S": "KC_LSFT",
    "LSFT": "KC_LSFT",
    "LSHIFT": "KC_LSFT",
    "A": "KC_LALT",
    "ALT": "KC_LALT",
    "LALT": "KC_LALT",
    "G": "KC_LGUI",
    "GUI": "KC_LGUI",
    "LGUI": "KC_LGUI",
    "RCTL": "KC_RCTL",
    "RCTRL": "KC_RCTL",
    "RSFT": "KC_RSFT",
    "RSHIFT": "KC_RSFT",
    "RALT": "KC_RALT",
    "RGUI": "KC_RGUI",
}

_SHIFTED_ALIASES = {
    "KC_EXLM": "KC_1",
    "KC_AT": "KC_2",
    "KC_HASH": "KC_3",
    "KC_DLR": "KC_4",
    "KC_DOLLAR": "KC_4",
    "KC_PERC": "KC_5",
    "KC_PERCENT": "KC_5",
    "KC_CIRC": "KC_6",
    "KC_CARET": "KC_6",
    "KC_AMPR": "KC_7",
    "KC_AMPERSAND": "KC_7",
    "KC_ASTR": "KC_8",
    "KC_ASTERISK": "KC_8",
    "KC_LPRN": "KC_9",
    "KC_RPRN": "KC_0",
    "KC_UNDS": "KC_MINS",
    "KC_UNDERSCORE": "KC_MINS",
    "KC_PLUS": "KC_EQL",
    "KC_LCBR": "KC_LBRC",
    "KC_RCBR": "KC_RBRC",
    "KC_LCURLY": "KC_LBRC",
    "KC_RCURLY": "KC_RBRC",
    "KC_PIPE": "KC_BSLS",
    "KC_COLN": "KC_SCLN",
    "KC_COLON": "KC_SCLN",
    "KC_DQUO": "KC_QUOT",
    "KC_DOUBLE_QUOTE": "KC_QUOT",
    "KC_LT": "KC_COMM",
    "KC_GT": "KC_DOT",
    "KC_QUES": "KC_SLSH",
    "KC_QUESTION": "KC_SLSH",
    "KC_TILD": "KC_GRV",
    "KC_TILDE": "KC_GRV",
}

_CANONICAL_ALIASES = {
    "KC_CAPS_LOCK": "KC_CAPSLOCK",
    "KC_NUM_LOCK": "KC_NUMLOCK",
    "KC_SCROLL_LOCK": "KC_SCROLLLOCK",
    "KC_PRINT_SCREEN": "KC_PSCREEN",
    "KC_PSCRN": "KC_PSCREEN",
    "KC_PAGE_UP": "KC_PGUP",
    "KC_PAGE_DOWN": "KC_PGDN",
    "KC_PG_UP": "KC_PGUP",
    "KC_PG_DOWN": "KC_PGDN",
    "KC_BACKSLASH": "KC_BSLASH",
    "KC_SEMICOLON": "KC_SCOLON",
    "KC_APOSTROPHE": "KC_QUOTE",
    "KC_RETURN": "KC_ENTER",
}

_SPACE_CADET = {
    "SC_LSPO": ("KC_LSFT", "KC_9"),
    "SC_RSPC": ("KC_RSFT", "KC_0"),
    "KC_LSPO": ("KC_LSFT", "KC_9"),
    "KC_RSPC": ("KC_RSFT", "KC_0"),
}


@dataclass(frozen=True)
class ActionStep:
    action: str
    is_press: bool


def is_shifted_alias(action: str) -> bool:
    return action in _SHIFTED_ALIASES


def is_canonical_alias(action: str) -> bool:
    return action in _CANONICAL_ALIASES


def canonicalize_action_alias(action: str) -> str:
    return _CANONICAL_ALIASES.get(action, action)


def is_modifier_wrapper(action: str, depth: int = 0) -> bool:
    m = _WRAPPER_RE.match(action)
    if not m or m.group(1) not in _MOD_WRAPPERS:
        return False
    inner = m.group(2).strip()
    if not inner:
        return False
    if _SAFE_ACTION_RE.fullmatch(inner):
        return True
    if depth >= 8:
        return False
    return is_modifier_wrapper(inner, depth + 1)


def is_expandable_action(action: str) -> bool:
    return is_shifted_alias(action) or is_canonical_alias(action) or is_modifier_wrapper(action)


def shifted_aliases_snapshot() -> dict[str, str]:
    return dict(_SHIFTED_ALIASES)


def canonical_aliases_snapshot() -> dict[str, str]:
    return dict(_CANONICAL_ALIASES)


def modifier_wrappers_snapshot() -> dict[str, str]:
    return dict(_MOD_WRAPPERS)


def space_cadet_tap_hold(action: str) -> tuple[str, str] | None:
    """Return (tap_action, hold_action) for Space Cadet aliases."""
    pair = _SPACE_CADET.get(action)
    if pair is None:
        return None
    mod, key = pair
    return f"{mod_wrapper_name(mod)}({key})", mod


def mod_wrapper_name(mod_action: str) -> str:
    for name, mod in _MOD_WRAPPERS.items():
        if mod == mod_action and len(name) > 1:
            return name
    return mod_action.removeprefix("KC_")


def _expanded_pair(action: str) -> tuple[str, str] | None:
    action = canonicalize_action_alias(action)
    if action in _SHIFTED_ALIASES:
        return "KC_LSFT", _SHIFTED_ALIASES[action]
    m = _WRAPPER_RE.match(action)
    if not m:
        return None
    wrapper, inner = m.group(1), m.group(2).strip()
    mod = _MOD_WRAPPERS.get(wrapper)
    if mod is None or not inner:
        return None
    return mod, inner


def _expand_press(action: str, depth: int) -> list[ActionStep]:
    if depth > 8:
        return [ActionStep(canonicalize_action_alias(action), True)]
    pair = _expanded_pair(action)
    if pair is None:
        return [ActionStep(canonicalize_action_alias(action), True)]
    mod, inner = pair
    return [ActionStep(mod, True), *_expand_press(inner, depth + 1)]


def _expand_release(action: str, depth: int) -> list[ActionStep]:
    if depth > 8:
        return [ActionStep(canonicalize_action_alias(action), False)]
    pair = _expanded_pair(action)
    if pair is None:
        return [ActionStep(canonicalize_action_alias(action), False)]
    mod, inner = pair
    return [*_expand_release(inner, depth + 1), ActionStep(mod, False)]


def expand_action_event(action: str, is_press: bool) -> list[ActionStep]:
    """Expand an action press/release into concrete action steps.

    Unknown actions pass through unchanged.
    """
    if is_press:
        return _expand_press(action, 0)
    return _expand_release(action, 0)


def expand_tap_action(action: str) -> list[ActionStep]:
    """Expand a tap action into press/release steps."""
    press = expand_action_event(action, True)
    release = expand_action_event(action, False)
    return [*press, *release]
