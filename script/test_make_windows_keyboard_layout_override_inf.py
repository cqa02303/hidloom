#!/usr/bin/env python3
"""Regression tests for Windows keyboard layout override extension INF generator."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "build" / "generators" / "make_windows_keyboard_layout_override_inf.py"

spec = importlib.util.spec_from_file_location("make_windows_keyboard_layout_override_inf", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def main() -> None:
    text = mod._inf_text(
        hardware_id=r"HID\VID_1D6B&PID_0105&MI_02",
        layout="jp_106",
        extension_id="11111111-2222-3333-4444-555555555555",
        driver_ver="06/11/2026,1.0.0.0",
        provider="HIDloom Project",
        manufacturer="HIDloom Project",
        device_desc="HIDloom US Sub Keyboard Layout Override",
        catalog_file="hidloom-keyboard-layout-override.cat",
    )
    assert "Class=Extension" in text
    assert "ClassGuid={e2f84ce7-8efa-411c-aa69-97454ca4cb57}" in text
    assert "ExtensionId={11111111-2222-3333-4444-555555555555}" in text
    assert r"%DeviceExtensionDesc%=CqaKeyboardLayout_Install, HID\VID_1D6B&PID_0105&MI_02" in text
    assert "HKR,,OverrideKeyboardType,0x00010001,7" in text
    assert "HKR,,OverrideKeyboardSubtype,0x00010001,2" in text
    assert "KeyboardTypeOverride" not in text
    assert "SPSVCINST_ASSOCSERVICE" not in text

    text = mod._inf_text(
        hardware_id=r"HID\VID_1D6B&PID_0105&MI_00",
        layout="us_101",
        extension_id="11111111-2222-3333-4444-555555555555",
        driver_ver="06/11/2026,1.0.0.0",
        provider="HIDloom Project",
        manufacturer="HIDloom Project",
        device_desc="HIDloom US Keyboard Layout Override",
        catalog_file="hidloom-keyboard-layout-override.cat",
    )
    assert "HKR,,OverrideKeyboardSubtype,0x00010001,0" in text

    try:
        mod._normalize_hardware_id(r"HKLM\SYSTEM\CurrentControlSet\Enum\HID\VID_1D6B")
    except ValueError:
        pass
    else:
        raise AssertionError("registry path should be rejected as hardware ID")

    print("ok: Windows keyboard layout override extension INF generator")


if __name__ == "__main__":
    main()
