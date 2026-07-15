#!/usr/bin/env python3
"""Static checks for the Windows IME Raw HID receiver PoC."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    source = (ROOT / "script" / "windows_ime_raw_hid_receiver_poc.py").read_text(encoding="utf-8")
    assert "python -m pip install hidapi" in source
    assert "decode_windows_ime_raw_hid_frame" in source
    assert "SendInput" in source
    assert "TSF" in source
    assert "RAW_HID_INTERFACE = 1" in source
    assert "COMMAND_LABELS" in source
    assert "dev.read(RAW_HID_REPORT_SIZE" in source
    assert "ignored raw=" in source
    print("ok: Windows IME Raw HID receiver PoC")


if __name__ == "__main__":
    main()
