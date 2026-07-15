#!/usr/bin/env python3
"""Static checks for the Windows IME custom HID sender helper."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    sender = (ROOT / "script" / "send_windows_ime_custom_hid_report.py").read_text(encoding="utf-8")
    assert "DEFAULT_DEVICE = Path(\"/dev/hidg4\")" in sender
    assert "COMMAND_BY_ACTION" in sender
    assert "encode_windows_ime_custom_hid_report(command_id, is_press=True" in sender
    assert "encode_windows_ime_custom_hid_report(command_id, is_press=False" in sender
    assert "--press-only" in sender
    assert "--release-only" in sender
    assert "custom HID device is not available" in sender
    print("ok: Windows IME custom HID sender helper")


if __name__ == "__main__":
    main()
