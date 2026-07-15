"""Validation helpers for HTTP keymap action strings."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from logicd.shared_action_defs import (  # noqa: E402
    is_layer_action_in_range,
    is_wrapper_action,
)

_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_ACTION_WHITESPACE_RE = re.compile(r"\s+")
_LAYER_TAP_RE = re.compile(r"^LT\((\d+),\s*(KC_[A-Za-z0-9_]{1,64})\)$")
_INTERACTION_ACTION_RE = re.compile(r"^(TD|MORSE)\([A-Za-z0-9_.-]{1,64}\)$")
_TOUCH_FLICK_RE = re.compile(r"^KC_FLICK\((\d+),(\d+)\)$")


def _is_layer_tap_action(action: str) -> bool:
    match = _LAYER_TAP_RE.fullmatch(action)
    if not match:
        return False
    layer = int(match.group(1))
    tap_key = match.group(2)
    return 0 <= layer < 32 and tap_key not in {"KC_NONE", "KC_TRNS"}


def _is_touch_flick_action(action: str) -> bool:
    match = _TOUCH_FLICK_RE.fullmatch(action)
    if not match:
        return False
    layer = int(match.group(1))
    index = int(match.group(2))
    return 0 <= layer < 32 and 0 <= index < 256


def normalize_keymap_action(action: object) -> str | None:
    if not isinstance(action, str):
        return None
    return _ACTION_WHITESPACE_RE.sub("", action.strip())


def is_valid_keymap_action(action: object) -> bool:
    action = normalize_keymap_action(action)
    if action is None:
        return False
    if _SAFE_IDENTIFIER_RE.fullmatch(action):
        return True
    if is_layer_action_in_range(action, max_layers=32):
        return True
    if _is_layer_tap_action(action):
        return True
    if _INTERACTION_ACTION_RE.fullmatch(action):
        return True
    if _is_touch_flick_action(action):
        return True
    return is_wrapper_action(action)
