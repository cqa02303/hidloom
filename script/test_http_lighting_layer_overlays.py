#!/usr/bin/env python3
"""Local smoke test for HTTP layer LED overlay helpers."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon" / "http"))

from lighting_layer_overlays import (  # noqa: E402
    apply_layer_overlay_update,
    build_layer_overlay_payload,
    default_layer_color,
    normalize_layer_overlay_update,
)


def main() -> None:
    ledd = {
        "semantic_roles": {
            "state_overlays": {
                "layer_1": {
                    "keys": ["LT(1,KC_LANG2)"],
                    "include_layer_changes": True,
                    "color": [0, 80, 0],
                    "effect_blend": "max",
                    "priority": 30,
                },
                "caps_lock": {"keys": ["KC_CAPS"], "color": [120, 80, 0]},
            }
        }
    }
    payload = build_layer_overlay_payload(ledd)
    assert payload["layers"][0]["layer"] == 1
    assert payload["layers"][0]["enabled"] is True
    assert payload["layers"][0]["color"] == [0, 80, 0]
    assert payload["layers"][1]["enabled"] is False
    assert payload["layers"][1]["color"] == default_layer_color(2)
    assert payload["blend_modes"] == ["replace", "max", "add", "alpha"]

    update = normalize_layer_overlay_update({
        "layers": [
            {
                "layer": 1,
                "enabled": True,
                "color": [0, 96, 0],
                "effect_blend": "alpha",
                "effect_alpha": 0.5,
                "include_layer_changes": True,
            },
            {
                "layer": 2,
                "enabled": True,
                "color": [0, 48, 120],
                "effect_blend": "max",
                "include_layer_changes": True,
            },
            {"layer": 3, "enabled": False},
        ]
    }, ledd)
    assert update["layer:1"]["keys"] == ["LT(1,KC_LANG2)"]
    assert update["layer:1"]["color"] == [0, 96, 0]
    assert update["layer:1"]["effect_blend"] == "alpha"
    assert update["layer:1"]["effect_alpha"] == 0.5
    assert update["layer:2"]["include_layer_changes"] is True
    assert "layer:3" not in update

    applied = apply_layer_overlay_update(ledd, update)
    overlays = applied["semantic_roles"]["state_overlays"]
    assert "layer_1" not in overlays
    assert overlays["layer:1"]["color"] == [0, 96, 0]
    assert overlays["layer:2"]["color"] == [0, 48, 120]
    assert overlays["caps_lock"]["color"] == [120, 80, 0]

    invalid_bodies = [
        {"layers": [{"layer": 8, "enabled": True}]},
        {"layers": [{"layer": 1, "enabled": True, "color": [999, 0, 0]}]},
        {"layers": [{"layer": 1, "enabled": True, "effect_blend": "bad"}]},
        {"layers": [{"layer": 1, "enabled": True}, {"layer": 1, "enabled": True}]},
    ]
    for body in invalid_bodies:
        try:
            normalize_layer_overlay_update(body, ledd)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid layer overlay body accepted: {body!r}")

    print("ok: HTTP layer overlay helpers")


if __name__ == "__main__":
    main()
