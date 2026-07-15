#!/usr/bin/env python3
"""Regression tests for HTTP Lighting lock-indicator config helpers."""
from __future__ import annotations

import sys
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon" / "http"))
sys.path.insert(0, str(ROOT))

from lighting_lock_indicators import (  # noqa: E402
    apply_reactive_update,
    apply_lock_indicator_update,
    build_lock_indicator_payload,
    _write_ledd,
    normalize_lock_indicator_update,
)


def main() -> None:
    ledd = {
        "semantic_roles": {
            "state_overlays": {
                "caps_lock": {"keys": ["KC_CAPS"], "color": [120, 80, 0], "priority": 45},
                "layer:1": {"keys": ["MO(1)"], "color": [0, 80, 0], "priority": 30},
            }
        },
        "leds": {"4,4": {"x": 0, "y": 0}},
    }
    payload = build_lock_indicator_payload(ledd)
    assert payload["states"]["caps_lock"]["enabled"] is True
    assert payload["states"]["caps_lock"]["color"] == [120, 80, 0]
    assert payload["states"]["num_lock"]["enabled"] is True
    assert payload["states"]["scroll_lock"]["enabled"] is True
    assert payload["states"]["compose"]["enabled"] is True
    assert payload["states"]["kana"]["enabled"] is True
    assert payload["states"]["num_lock"]["keys"] == ["KC_NUM", "KC_NUMLOCK", "KC_NLCK"]
    assert payload["states"]["scroll_lock"]["keys"] == ["KC_SCROLL", "KC_SCROLLLOCK", "KC_SLCK"]
    assert payload["states"]["kana"]["keys"] == ["KC_KANA", "KC_INT2"]
    assert payload["reactive"]["modifier_triggers_effects"] is False
    assert payload["default_keys"]["caps_lock"] == ["KC_CAPS", "KC_CAPSLOCK"]
    assert payload["led_positions"] == {"4,4": {"x": 0.0, "y": 0.0}}

    update = normalize_lock_indicator_update({
        "blend": "max",
        "states": {
            "caps_lock": {
                "enabled": True,
                "follow_keys": True,
                "keys": "KC_CAPS KC_CAPSLOCK",
                "extra_leds": "4,4",
                "color": [255, 0, 0],
            },
            "num_lock": {
                "enabled": True,
                "follow_keys": False,
                "extra_leds": ["4,4"],
                "color": [0, 0, 255],
            },
            "scroll_lock": {"enabled": False},
        },
    })
    assert update["states"]["caps_lock"]["extra_leds"] == ["4,4"]
    assert update["states"]["num_lock"]["follow_keys"] is False
    assert "scroll_lock" not in update["states"]

    applied = apply_lock_indicator_update(ledd, update)
    semantic = applied["semantic_roles"]
    assert "caps_lock" not in semantic["state_overlays"]
    assert "layer:1" in semantic["state_overlays"]
    assert semantic["lock_indicators"]["blend"] == "max"
    assert semantic["lock_indicators"]["states"]["num_lock"]["extra_leds"] == ["4,4"]
    saved_payload = build_lock_indicator_payload(applied)
    assert saved_payload["states"]["scroll_lock"]["enabled"] is False

    applied = apply_reactive_update(applied, {"reactive": {"modifier_triggers_effects": True}})
    assert applied["semantic_roles"]["reactive"]["modifier_triggers_effects"] is True
    assert "modifier" not in applied["semantic_roles"]["reactive"]["exclude_roles"]
    assert build_lock_indicator_payload(applied)["reactive"]["modifier_triggers_effects"] is True
    applied = apply_reactive_update(applied, {"reactive": {"modifier_triggers_effects": False}})
    assert applied["semantic_roles"]["reactive"]["modifier_triggers_effects"] is False
    assert applied["semantic_roles"]["reactive"]["exclude_roles"][0] == "modifier"
    assert build_lock_indicator_payload({
        "semantic_roles": {"reactive": {"exclude_roles": ["modifier"], "modifier_triggers_effects": True}}
    })["reactive"]["modifier_triggers_effects"] is True

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ledd.json"
        _write_ledd(applied, path)
        assert path.read_text(encoding="utf-8").endswith("\n")
        assert not list(Path(tmp).glob("*.tmp"))

    try:
        normalize_lock_indicator_update({"blend": "bad", "states": {}})
    except ValueError:
        pass
    else:
        raise AssertionError("invalid blend should fail")

    print("ok: HTTP Lighting lock indicator helpers")


if __name__ == "__main__":
    main()
