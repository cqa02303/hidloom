"""Shared VialRGB effect metadata used by logicd, viald, httpd, and scripts."""
from __future__ import annotations

from typing import Dict, Tuple

VIALRGB_EFFECTS: Dict[int, str] = {
    0: "Disable",
    1: "Direct Control",
    2: "Solid Color",
    3: "Alphas Mods",
    4: "Gradient Up Down",
    5: "Gradient Left Right",
    6: "Breathing",
    7: "Band Sat",
    8: "Band Val",
    9: "Band Pinwheel Sat",
    10: "Band Pinwheel Val",
    11: "Band Spiral Sat",
    12: "Band Spiral Val",
    13: "Cycle All",
    14: "Cycle Left Right",
    15: "Cycle Up Down",
    16: "Rainbow Moving Chevron",
    17: "Cycle Out In",
    18: "Cycle Out In Dual",
    19: "Cycle Pinwheel",
    20: "Cycle Spiral",
    21: "Dual Beacon",
    22: "Rainbow Beacon",
    23: "Rainbow Pinwheels",
    24: "Raindrops",
    25: "Jellybean Raindrops",
    26: "Hue Breathing",
    27: "Hue Pendulum",
    28: "Hue Wave",
    29: "Typing Heatmap",
    30: "Digital Rain",
    31: "Solid Reactive Simple",
    32: "Solid Reactive",
    33: "Solid Reactive Wide",
    34: "Solid Reactive Multiwide",
    35: "Solid Reactive Cross",
    36: "Solid Reactive Multicross",
    37: "Solid Reactive Nexus",
    38: "Solid Reactive Multinexus",
    39: "Splash",
    40: "Multisplash",
    41: "Solid Splash",
    42: "Solid Multisplash",
    43: "Pixel Rain",
    44: "Pixel Fractal",
    1000: "Experimental Custom",
    1001: "LED Life Game",
    1002: "Direct Multisplash",
    1003: "Key Banner",
}

# Modes cycled by RGB_MOD / RGB_RMOD. Disable and direct-control are not part
# of the normal visual effect rotation.
VIALRGB_EFFECT_SEQUENCE: Tuple[int, ...] = (
    2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12,
    13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23,
    24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34,
    35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 1000, 1001,
)

VIALRGB_ALLOWED_MODES = frozenset(VIALRGB_EFFECTS)
VIALRGB_SUPPORTED_EFFECTS: Tuple[int, ...] = tuple(
    mode for mode in sorted(VIALRGB_EFFECTS) if mode != 0
)

VIALRGB_PREVIEW_DEFAULTS: Dict[int, tuple[int, int, int, int]] = {
    0: (128, 0, 0, 0),
    1: (128, 0, 0, 0),
    2: (128, 0, 255, 128),
    3: (128, 20, 255, 140),
    4: (96, 0, 255, 128),
    5: (96, 0, 255, 128),
    6: (96, 0, 255, 128),
    7: (128, 32, 255, 160),
    8: (128, 32, 255, 160),
    9: (128, 32, 255, 160),
    10: (128, 32, 255, 160),
    11: (128, 32, 255, 160),
    12: (128, 32, 255, 160),
    13: (96, 0, 255, 128),
    14: (96, 0, 255, 128),
    15: (96, 0, 255, 128),
    16: (128, 0, 255, 160),
    17: (96, 0, 255, 128),
    18: (96, 0, 255, 128),
    19: (96, 0, 255, 128),
    20: (96, 0, 255, 128),
    21: (128, 0, 255, 160),
    22: (128, 0, 255, 160),
    23: (128, 0, 255, 160),
    24: (96, 120, 255, 160),
    25: (96, 120, 255, 160),
    26: (96, 0, 255, 128),
    27: (96, 0, 255, 128),
    28: (96, 0, 255, 128),
    29: (128, 0, 255, 128),
    30: (112, 96, 255, 160),
    31: (128, 80, 255, 128),
    32: (128, 80, 255, 128),
    33: (128, 80, 255, 128),
    34: (128, 80, 255, 128),
    35: (128, 80, 255, 128),
    36: (128, 80, 255, 128),
    37: (128, 80, 255, 128),
    38: (128, 80, 255, 128),
    39: (128, 80, 255, 128),
    40: (128, 80, 255, 128),
    41: (128, 80, 255, 128),
    42: (128, 80, 255, 128),
    43: (96, 120, 255, 160),
    44: (96, 0, 255, 160),
    1000: (128, 180, 255, 160),
    1001: (32, 100, 255, 160),
    1002: (128, 80, 255, 128),
    1003: (180, 140, 255, 160),
}

VIALRGB_PREVIEW_EFFECTS: Tuple[tuple[int, str, int, int, int, int], ...] = tuple(
    (mode, VIALRGB_EFFECTS[mode], *VIALRGB_PREVIEW_DEFAULTS[mode])
    for mode in sorted(VIALRGB_EFFECTS)
)

VIALRGB_PREVIEW_GROUPS = {
    "control": {0, 1},
    "solid": {2, 3, 6},
    "gradient": {4, 5},
    "band": {7, 8, 9, 10, 11, 12, 22, 23},
    "cycle": {13, 14, 15, 16, 17, 18, 19, 20, 21, 26, 27, 28, 44},
    "reactive": {29, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42},
    "rain": {24, 25, 30, 43},
    "experimental": {1000, 1001, 1002, 1003},
}

VIALRGB_RENDER_GROUPS = {
    "gradient": {4, 5},
    "directional_cycle": {14, 15},
    "chevron_beacon": {16, 21},
    "radial_cycle": {17, 18, 19, 20},
    "position_pattern": {7, 8, 9, 10, 11, 12, 22, 23},
    "pixel_rain": {24, 25, 43},
    "typing_heatmap": {29},
    "solid_reactive_simple": {31},
    "solid_reactive": {32, 33, 34, 35, 36, 37, 38},
    "splash": {39, 40, 41, 42},
    "life_game": {1001},
    "direct_splash": {1002},
    "key_banner": {1003},
}

VIALRGB_REACTIVE_MODES = (
    VIALRGB_RENDER_GROUPS["typing_heatmap"]
    | VIALRGB_RENDER_GROUPS["solid_reactive_simple"]
    | VIALRGB_RENDER_GROUPS["solid_reactive"]
)
VIALRGB_SPLASH_MODES = VIALRGB_RENDER_GROUPS["splash"]
VIALRGB_DIRECT_SPLASH_MODES = VIALRGB_RENDER_GROUPS["direct_splash"]
VIALRGB_SOLID_SPLASH_MODES = {41, 42}
VIALRGB_MULTI_SPLASH_MODES = {40, 42}
VIALRGB_DIRECT_MULTI_SPLASH_MODES = {1002}
VIALRGB_WIDE_REACTIVE_MODES = {33, 34}
VIALRGB_CROSS_REACTIVE_MODES = {35, 36}
VIALRGB_SHORT_REACTIVE_MODES = {32, 33, 35, 37}
VIALRGB_MULTI_HUE_REACTIVE_MODES = {34, 36, 38}

# Real-device matrixd stability smoke on <keyboard-host> found intermittent
# idle key bursts around Multisplash v=170..180. Keep splash-style effects
# below that current/brightness region unless an internal tool explicitly
# bypasses the normal Lighting state path.
VIALRGB_SPLASH_VALUE_MAX = 160


def clamp_vialrgb_value_for_mode(mode: int, value: int, *, splash_value_max: int = VIALRGB_SPLASH_VALUE_MAX) -> int:
    value = max(0, min(255, int(value)))
    if int(mode) in VIALRGB_SPLASH_MODES | VIALRGB_DIRECT_SPLASH_MODES:
        return min(value, max(0, min(255, int(splash_value_max))))
    return value
