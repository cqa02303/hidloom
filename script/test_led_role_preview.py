#!/usr/bin/env python3
"""Regression tests for side-effect-free LED role preview frame builder."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "daemon" / "http"))

from led_role_preview import ROLE_PREVIEW_HSV, build_role_preview_frame, role_for_preview_keycode  # noqa: E402
from ledd.semantic_roles import normalize_led_semantic_role_config  # noqa: E402


def main() -> None:
    assert role_for_preview_keycode("KC_A") == "normal"
    assert role_for_preview_keycode("KC_LCTL") == "modifier"
    assert role_for_preview_keycode("KC_F12") == "function"
    assert role_for_preview_keycode("MO(1)") == "layer"
    assert role_for_preview_keycode("KC_CAPS") == "lock"
    assert role_for_preview_keycode("KC_SH10") == "script"
    assert role_for_preview_keycode("BT_POWER_OFF") == "system"

    semantic = normalize_led_semantic_role_config({"roles": {"KC_A": "function"}})
    assert role_for_preview_keycode("KC_A", semantic) == "function"

    frame = build_role_preview_frame(brightness=96)
    assert frame["count"] > 0
    assert frame["count"] == len(frame["pixels"])
    assert frame["count"] == len(frame["roles_by_position"])
    assert set(frame["counts"]).issuperset(ROLE_PREVIEW_HSV)
    assert sum(frame["counts"].values()) == frame["count"]
    for pixel in frame["pixels"]:
        assert isinstance(pixel, list)
        assert len(pixel) == 3
        assert all(isinstance(component, int) for component in pixel)
        assert all(0 <= component <= 255 for component in pixel)

    bright = build_role_preview_frame(brightness=180)
    assert bright["count"] == frame["count"]
    assert sum(bright["counts"].values()) == bright["count"]

    print("ok: LED role preview frame")


if __name__ == "__main__":
    main()
