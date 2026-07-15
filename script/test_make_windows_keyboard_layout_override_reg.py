#!/usr/bin/env python3
"""Regression tests for Windows keyboard layout override .reg generator."""
from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "build" / "generators" / "make_windows_keyboard_layout_override_reg.py"

spec = importlib.util.spec_from_file_location("make_windows_keyboard_layout_override_reg", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def main() -> None:
    text = mod._reg_text(r"HID\VID_1D6B&PID_0105&MI_02\9&ABC&0&0000", "jp_106")
    assert r"[HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Enum\HID\VID_1D6B&PID_0105&MI_02\9&ABC&0&0000\Device Parameters]" in text
    assert '"OverrideKeyboardType"=dword:00000007' in text
    assert '"OverrideKeyboardSubtype"=dword:00000002' in text
    assert "KeyboardTypeOverride" not in text

    text = mod._reg_text(
        r"HKLM\SYSTEM\CurrentControlSet\Enum\HID\VID_1D6B&PID_0105&MI_00\9&ABC&0&0000\Device Parameters",
        "us_101",
    )
    assert r"\Device Parameters\Device Parameters" not in text
    assert '"OverrideKeyboardSubtype"=dword:00000000' in text

    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "layout.reg"
        text = mod._reg_text(r"HID\VID_1D6B&PID_0105&MI_02\9&ABC&0&0000", "jp_106")
        out.write_bytes(("\ufeff" + text).encode("utf-16le"))
        data = out.read_bytes()
        assert data.startswith(b"\xff\xfe")

    print("ok: Windows keyboard layout override .reg generator")


if __name__ == "__main__":
    main()
