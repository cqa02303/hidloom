#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.windows_host_profile import (  # noqa: E402
    WINDOWS_US_CUSTOM_HID_IME_PROFILE,
    normalize_windows_ime_host_profile,
    profile_to_custom_hid_route_kwargs,
)
from logicd.windows_ime_custom_hid import build_windows_ime_custom_hid_plan  # noqa: E402


def main() -> None:
    empty = normalize_windows_ime_host_profile(None)
    assert empty.name == ""
    assert not empty.custom_hid_ime_enabled

    wrong = normalize_windows_ime_host_profile({"name": "windows_us", "custom_hid_ime": {"enabled": True}})
    assert wrong.name == "windows_us"
    assert not wrong.custom_hid_ime_enabled

    disabled = normalize_windows_ime_host_profile({"name": WINDOWS_US_CUSTOM_HID_IME_PROFILE})
    plan = build_windows_ime_custom_hid_plan("KC_LANG1", **profile_to_custom_hid_route_kwargs(disabled))
    assert plan.blocked_reason == "custom_hid_route_disabled"

    ready = normalize_windows_ime_host_profile({
        "name": WINDOWS_US_CUSTOM_HID_IME_PROFILE,
        "custom_hid_ime": {"enabled": True, "receiver_available": True},
    })
    plan = build_windows_ime_custom_hid_plan("KC_LANG1", **profile_to_custom_hid_route_kwargs(ready))
    assert plan.enabled is True


if __name__ == "__main__":
    main()
