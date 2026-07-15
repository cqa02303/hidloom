#!/usr/bin/env python3
"""
generate_config.py – Generate config/default/config.json from vial.json + keyboard-layout.json.

Usage:
    python logicd/generate_config.py [--out config/default/config.json]

Reads:
    config/default/vial.json           – vial keymap (matrix coords per key slot)
    config/default/keyboard-layout.json – KLE labels (display labels per key slot)

Both files share the same KLE cursor structure so they can be iterated in
parallel to build a row,col → keycode mapping for layer 0.

Run this once after first wiring up the keyboard to generate a working
default config.  Edit the resulting config.json to customize layers/macros.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from hidloom_paths import default_config_file

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_VIAL_JSON   = str(default_config_file("vial.json"))
_KLE_JSON    = str(default_config_file("keyboard-layout.json"))
_OUT_DEFAULT = str(default_config_file("config.json"))

# ---------------------------------------------------------------------------
# KLE label → HID keycode name
# The lookup uses the LAST non-empty "\n"-separated token of the label.
# ---------------------------------------------------------------------------
_LABEL_TO_KC: Dict[str, str] = {
    # Control
    "Esc":       "KC_ESC",
    "BackSpace": "KC_BSPACE",
    "BS":        "KC_BSPACE",
    "Tab":       "KC_TAB",
    "Caps Lock": "KC_CAPSLOCK",
    "Enter":     "KC_ENTER",
    "Space":     "KC_SPACE",
    "Delete":    "KC_DELETE",
    "Insert":    "KC_INSERT",
    "Home":      "KC_HOME",
    "End":       "KC_END",
    "Page Up":   "KC_PGUP",
    "Page Down": "KC_PGDN",
    "↑": "KC_UP",   "UP":    "KC_UP",
    "↓": "KC_DOWN", "DOWN":  "KC_DOWN",
    "←": "KC_LEFT", "LEFT":  "KC_LEFT",
    "→": "KC_RIGHT","RIGHT": "KC_RIGHT",
    # Modifiers
    "Shift": "KC_LSHIFT",
    "Ctrl":  "KC_LCTRL",
    "Alt":   "KC_LALT",
    "Win":   "KC_LWIN",
    "Fn":    "MO(1)",
    # Function
    "F1": "KC_F1", "F2": "KC_F2", "F3": "KC_F3",  "F4": "KC_F4",
    "F5": "KC_F5", "F6": "KC_F6", "F7": "KC_F7",  "F8": "KC_F8",
    "F9": "KC_F9", "F10":"KC_F10","F11":"KC_F11", "F12":"KC_F12",
    # Number row (JIS)
    "`": "KC_GRAVE",   # 半角/全角
    "1": "KC_1", "2": "KC_2", "3": "KC_3", "4": "KC_4", "5": "KC_5",
    "6": "KC_6", "7": "KC_7", "8": "KC_8", "9": "KC_9", "0": "KC_0",
    "-": "KC_MINUS",   # JIS: - =
    "=": "KC_EQUAL",   # JIS: ^ ~
    # QWERTY
    "Q":"KC_Q","W":"KC_W","E":"KC_E","R":"KC_R","T":"KC_T",
    "Y":"KC_Y","U":"KC_U","I":"KC_I","O":"KC_O","P":"KC_P",
    "[":"KC_LBRACKET", # JIS: @ `
    "]":"KC_RBRACKET", # JIS: [ {
    "\\":"KC_BSLASH",
    # Home row
    "A":"KC_A","S":"KC_S","D":"KC_D","F":"KC_F","G":"KC_G",
    "H":"KC_H","J":"KC_J","K":"KC_K","L":"KC_L",
    ";": "KC_SCOLON",  # JIS: ; +
    "'": "KC_QUOTE",   # JIS: : *
    # Bottom row
    "Z":"KC_Z","X":"KC_X","C":"KC_C","V":"KC_V","B":"KC_B",
    "N":"KC_N","M":"KC_M",
    ",": "KC_COMMA",
    ".": "KC_DOT",
    "/": "KC_SLASH",
    # Special / ignored
    "wheel": "KC_NONE",  # rotary encoder wheel (handled elsewhere)
    "LCD":   "KC_NONE",  # display area
    "stick": "KC_NONE",  # joystick axis (handled elsewhere)
}


def _label_to_kc(label: str) -> str:
    """Return a keycode name from a KLE label string."""
    # Try full label first
    if label in _LABEL_TO_KC:
        return _LABEL_TO_KC[label]
    # Fall back to last non-empty token (e.g. "~\n`" → "`")
    tokens = [t for t in label.split("\n") if t.strip()]
    if tokens:
        last = tokens[-1].strip()
        if last in _LABEL_TO_KC:
            return _LABEL_TO_KC[last]
    return "KC_NONE"


# ---------------------------------------------------------------------------
# Parallel KLE parse
# ---------------------------------------------------------------------------

def _iter_strings(kle: List[Any]):
    """Yield string items from a KLE layout array in cursor order."""
    for row in kle:
        if not isinstance(row, list):
            continue
        for item in row:
            if isinstance(item, str):
                yield item


def _build_layer(kle_labels: List[Any], vial_keymap: List[Any]) -> Dict[str, str]:
    """Pair KLE labels with vial matrix coords to build a layer dict."""
    layer: Dict[str, str] = {}
    coord_re = __import__("re").compile(r'^(\d+),(\d+)$')

    for label, coord in zip(_iter_strings(kle_labels), _iter_strings(vial_keymap)):
        m = coord_re.match(coord.strip())
        if not m:
            continue
        key = coord.strip()          # "row,col"
        kc  = _label_to_kc(label)
        if kc != "KC_NONE":
            layer[key] = kc

    return layer


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(out_path: str) -> None:
    for path, name in [(_VIAL_JSON, "vial.json"), (_KLE_JSON, "keyboard-layout.json")]:
        if not os.path.exists(path):
            print(f"ERROR: {name} not found at {path}", file=sys.stderr)
            sys.exit(1)

    with open(_VIAL_JSON, encoding="utf-8") as fh:
        vial = json.load(fh)
    with open(_KLE_JSON, encoding="utf-8") as fh:
        kle  = json.load(fh)

    # vial.json structure: {"layouts": {"keymap": [...]}, ...}
    vial_keymap = vial.get("layouts", {}).get("keymap", vial)

    layer0 = _build_layer(kle, vial_keymap)
    print(f"Layer 0: {len(layer0)} key(s) mapped")

    config: Dict[str, Any] = {
        "version": "1.0",
        "settings": {
            "layout": "JIS",
            "hidg":   "/dev/hidg0",
            "socket": "/tmp/matrix_events.sock",
        },
        "layers": [
            layer0,
            {},  # layer 1 – Fn layer (customise as needed)
        ],
        "macros": {
            # "MY_MACRO": ["Hello!", "{IME_ON}", "{U+3042}"]
        },
    }

    # Don't overwrite without warning if file already exists
    if os.path.exists(out_path):
        print(f"WARNING: {out_path} already exists – overwriting")

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2, ensure_ascii=False)
    print(f"Written: {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=_OUT_DEFAULT, help="Output config.json path")
    args = parser.parse_args()
    main(args.out)
