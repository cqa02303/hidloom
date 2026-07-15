#!/usr/bin/env python3
"""Regression tests for logicd.power_preset_status."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.power_preset_status import (  # noqa: E402
    default_power_presets,
    power_preset_oled_label,
    power_preset_status,
    power_preset_status_payload,
)


def test_default_low_preset_is_safe_and_does_not_touch_radios() -> None:
    status = power_preset_status("low").to_dict()

    assert status["defined"] is True
    assert status["risk"] == "low"
    assert status["requires_confirmation"] is False
    assert status["touches_radios"] is False
    assert status["wifi"] == "unchanged"
    assert status["bt"] == "unchanged"
    assert status["warnings"] == []


def test_display_off_is_medium_risk_without_radios() -> None:
    status = power_preset_status("display_off").to_dict()

    assert status["risk"] == "medium"
    assert status["requires_confirmation"] is False
    assert status["touches_radios"] is False
    assert status["oled"] == "off"
    assert status["led"] == "off"


def test_radios_off_requires_confirmation_and_recovery_guidance() -> None:
    status = power_preset_status("radios_off").to_dict()

    assert status["risk"] == "high"
    assert status["requires_confirmation"] is True
    assert status["touches_radios"] is True
    assert status["wifi"] == "runtime_off"
    assert status["bt"] == "off"
    assert "radio changes can disconnect HTTP/SSH or Bluetooth input" in status["warnings"]
    assert "Wi-Fi runtime off must use recovery-first behavior and return on reboot" in status["warnings"]
    assert "Bluetooth off requires paired-host reconnect testing before default use" in status["warnings"]
    assert "power cycle / reboot" in status["recovery_routes"]


def test_persistent_preset_is_blocked_even_if_defined() -> None:
    status = power_preset_status(
        "bad_persist",
        {"bad_persist": {"oled": "off", "led": "off", "bt": "unchanged", "wifi": "unchanged", "persist": True}},
    ).to_dict()

    assert status["defined"] is True
    assert status["risk"] == "blocked"
    assert status["requires_confirmation"] is True
    assert status["persistent"] is True
    assert "persistent power preset state is not allowed in the initial implementation" in status["warnings"]


def test_unknown_and_unsupported_actions_are_visible() -> None:
    unknown = power_preset_status("missing").to_dict()
    assert unknown["defined"] is False
    assert unknown["risk"] == "unknown"
    assert unknown["requires_confirmation"] is True

    unsupported = power_preset_status(
        "bad",
        {"bad": {"oled": "dim", "led": "off", "wifi": "persistent_off", "bt": "sleep"}},
    ).to_dict()
    assert unsupported["requires_confirmation"] is True
    assert "unsupported wifi action: persistent_off" in unsupported["warnings"]
    assert "unsupported bt action: sleep" in unsupported["warnings"]


def test_payload_is_read_only_and_has_default_presets() -> None:
    payload = power_preset_status_payload()

    assert payload["schema"] == "power_preset.status.v1"
    assert payload["read_only"] is True
    assert payload["current_preset"] is None
    assert payload["restore_available"] is False
    assert payload["active_state_persistent"] is False
    assert payload["default_safe_preset"] == "low"
    assert set(default_power_presets()) <= set(payload["presets"])
    assert payload["presets"]["radios_off"]["requires_confirmation"] is True


def test_oled_labels() -> None:
    assert power_preset_oled_label("low") == "Power Low"
    assert power_preset_oled_label("display_off") == "Display Off"
    assert power_preset_oled_label("radios_off") == "Radios Off"
    assert power_preset_oled_label("restore") == "Power Restore"
    assert power_preset_oled_label("custom") == "Power Preset"


def main() -> None:
    test_default_low_preset_is_safe_and_does_not_touch_radios()
    test_display_off_is_medium_risk_without_radios()
    test_radios_off_requires_confirmation_and_recovery_guidance()
    test_persistent_preset_is_blocked_even_if_defined()
    test_unknown_and_unsupported_actions_are_visible()
    test_payload_is_read_only_and_has_default_presets()
    test_oled_labels()
    print("ok: power preset status is recovery-first and read-only")


if __name__ == "__main__":
    main()
