"""Shared VialRGB Lighting metadata and validation for httpd."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from vialrgb_effects import VIALRGB_ALLOWED_MODES, VIALRGB_EFFECTS, VIALRGB_PREVIEW_GROUPS, clamp_vialrgb_value_for_mode  # noqa: E402

VIALRGB_VALUE_FIELDS = ("speed", "h", "s", "v")

VIALRGB_EFFECT_CATEGORY_LABELS = {
    "control": "Control",
    "solid": "Solid / Breathing",
    "gradient": "Gradient",
    "band": "Band / Pattern",
    "cycle": "Cycle / Rainbow",
    "reactive": "Reactive / Splash",
    "rain": "Rain / Pixel",
    "experimental": "Custom",
}

VIALRGB_EFFECT_CATEGORY_ORDER = (
    "control",
    "solid",
    "gradient",
    "band",
    "cycle",
    "reactive",
    "rain",
    "experimental",
)


def _coerce_u8_field(body: Dict[str, Any], field: str, current: Dict[str, Any]) -> int:
    raw = body.get(field, current.get(field, 0))
    value = int(raw)
    if not (0 <= value <= 255):
        raise ValueError(f"{field} out of range: {value}")
    return value


def build_lighting_update(body: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, int]:
    if not isinstance(body, dict):
        raise ValueError(f"JSON root must be object: {type(body).__name__}")

    raw_mode = body.get("mode", current.get("mode", 2))
    mode = int(raw_mode)
    if mode not in VIALRGB_ALLOWED_MODES:
        raise ValueError(f"unsupported mode: {mode}")

    update = {"mode": mode}
    for field in VIALRGB_VALUE_FIELDS:
        update[field] = _coerce_u8_field(body, field, current)
    update["v"] = clamp_vialrgb_value_for_mode(mode, update["v"])
    return update


def lighting_metadata() -> Dict[str, Any]:
    categories = []
    for category_id in VIALRGB_EFFECT_CATEGORY_ORDER:
        effect_ids = sorted(
            mode for mode in VIALRGB_PREVIEW_GROUPS.get(category_id, set())
            if mode in VIALRGB_EFFECTS
        )
        if not effect_ids:
            continue
        categories.append({
            "id": category_id,
            "label": VIALRGB_EFFECT_CATEGORY_LABELS.get(category_id, category_id.title()),
            "effects": effect_ids,
        })

    categorized = {mode for category in categories for mode in category["effects"]}
    other = sorted(mode for mode in VIALRGB_EFFECTS if mode not in categorized)
    if other:
        categories.append({"id": "other", "label": "Other", "effects": other})

    return {
        "effects": [
            {"id": mode, "name": name}
            for mode, name in sorted(VIALRGB_EFFECTS.items())
        ],
        "effect_categories": categories,
        "range": {"speed": [0, 255], "h": [0, 255], "s": [0, 255], "v": [0, 255]},
    }
