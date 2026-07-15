#!/usr/bin/env python3
"""Regression tests for logicd.host_profile_status."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.host_profile_status import (  # noqa: E402
    active_host_profile_status,
    host_profile_oled_label,
    merge_profile_status_into_host,
)


def profile_config():
    return {
        "version": 1,
        "hosts": {
            "AA:BB:CC:DD:EE:FF": {
                "label": "iPhone",
                "profile": "ios",
                "layout": "jis",
                "modifier_swap": "command_control",
                "enabled": True,
            },
            "11:22:33:44:55:66": {
                "label": "Old tablet",
                "profile": "android",
                "enabled": False,
            },
        },
        "profiles": {
            "ios": {"display_name": "iOS", "modifier_map": {"KC_LGUI": "KC_LCTL"}},
            "android": {"display_name": "Android"},
        },
    }


def test_no_active_host() -> None:
    status = active_host_profile_status(None, profile_config()).to_dict()

    assert status["active"] is False
    assert status["reason"] == "no_active_host"
    assert status["host_address"] is None


def test_unknown_host_has_no_profile() -> None:
    status = active_host_profile_status({"address": "00:00:00:00:00:01", "alias": "Unknown"}, profile_config()).to_dict()

    assert status["active"] is False
    assert status["reason"] == "profile_not_configured"
    assert status["host_address"] == "00:00:00:00:00:01"
    assert status["host_label"] == "Unknown"
    assert status["profile"] is None


def test_disabled_profile_is_reported_but_not_active() -> None:
    status = active_host_profile_status({"address": "11:22:33:44:55:66"}, profile_config()).to_dict()

    assert status["active"] is False
    assert status["enabled"] is False
    assert status["reason"] == "profile_disabled"
    assert status["profile"] == "android"
    assert status["profile_label"] == "Android"


def test_enabled_profile_metadata() -> None:
    status = active_host_profile_status({"address": "aa:bb:cc:dd:ee:ff", "alias": "Phone alias"}, profile_config()).to_dict()

    assert status == {
        "active": True,
        "host_address": "AA:BB:CC:DD:EE:FF",
        "host_label": "iPhone",
        "profile": "ios",
        "profile_label": "iOS",
        "layout": "jis",
        "enabled": True,
        "reason": "matched",
    }


def test_merge_profile_status_into_host_is_read_only_copy() -> None:
    host = {"address": "AA:BB:CC:DD:EE:FF", "alias": "Phone alias", "connected": True}
    merged = merge_profile_status_into_host(host, profile_config())

    assert "profile_status" not in host
    assert merged["connected"] is True
    assert merged["profile_active"] is True
    assert merged["profile"] == "ios"
    assert merged["profile_label"] == "iOS"
    assert merged["profile_layout"] == "jis"
    assert merged["profile_status"]["reason"] == "matched"


def test_oled_label_only_for_active_profile() -> None:
    active = active_host_profile_status({"address": "AA:BB:CC:DD:EE:FF"}, profile_config()).to_dict()
    disabled = active_host_profile_status({"address": "11:22:33:44:55:66"}, profile_config()).to_dict()
    unknown = active_host_profile_status({"address": "00:00:00:00:00:01"}, profile_config()).to_dict()

    assert host_profile_oled_label(active) == "Host iOS"
    assert host_profile_oled_label(disabled) == ""
    assert host_profile_oled_label(unknown) == ""


def main() -> None:
    test_no_active_host()
    test_unknown_host_has_no_profile()
    test_disabled_profile_is_reported_but_not_active()
    test_enabled_profile_metadata()
    test_merge_profile_status_into_host_is_read_only_copy()
    test_oled_label_only_for_active_profile()
    print("ok: host profile status is read-only and host metadata driven")


if __name__ == "__main__":
    main()
