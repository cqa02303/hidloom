#!/usr/bin/env python3
"""Regression tests for logicd.caps_word_status."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.caps_word_status import (  # noqa: E402
    caps_word_led_overlay_name,
    caps_word_oled_label,
    caps_word_status,
    caps_word_status_from_engine,
)


class DummyEngine:
    def __init__(self, active: bool, enabled: bool = True):
        self.caps_word_active = active
        self.caps_word = {"enabled": enabled}


def test_caps_word_status_is_distinct_from_host_caps_lock() -> None:
    status = caps_word_status(enabled=True, active=True, host_caps_lock=False).to_dict()

    assert status == {
        "enabled": True,
        "active": True,
        "label": "Caps Word",
        "lock_type": "caps_word",
        "host_caps_lock": False,
    }
    assert status["lock_type"] != "caps_lock"
    assert status["label"] != "Caps Lock"


def test_disabled_caps_word_is_not_active() -> None:
    status = caps_word_status(enabled=False, active=True, host_caps_lock=True).to_dict()

    assert status["enabled"] is False
    assert status["active"] is False
    assert status["host_caps_lock"] is True


def test_caps_word_status_from_engine() -> None:
    active = caps_word_status_from_engine(DummyEngine(active=True), host_caps_lock=None)
    assert active["enabled"] is True
    assert active["active"] is True
    assert active["host_caps_lock"] is None

    disabled = caps_word_status_from_engine(DummyEngine(active=True, enabled=False), host_caps_lock=False)
    assert disabled["enabled"] is False
    assert disabled["active"] is False


def test_oled_labels_are_short_and_not_caps_lock() -> None:
    assert caps_word_oled_label({"enabled": True, "active": True}) == "CW on"
    assert caps_word_oled_label({"enabled": True, "active": False}) == "CW"
    assert caps_word_oled_label({"enabled": False, "active": True}) == "CW off"
    assert "Caps Lock" not in caps_word_oled_label({"enabled": True, "active": True})


def test_led_overlay_name_is_separate() -> None:
    assert caps_word_led_overlay_name() == "caps_word"
    assert caps_word_led_overlay_name() != "caps_lock"
    assert caps_word_led_overlay_name() != "host_caps_lock"


def main() -> None:
    test_caps_word_status_is_distinct_from_host_caps_lock()
    test_disabled_caps_word_is_not_active()
    test_caps_word_status_from_engine()
    test_oled_labels_are_short_and_not_caps_lock()
    test_led_overlay_name_is_separate()
    print("ok: caps word status is distinct from host caps lock")


if __name__ == "__main__":
    main()
