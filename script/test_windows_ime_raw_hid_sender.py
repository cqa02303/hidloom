#!/usr/bin/env python3
"""Static checks for the Windows IME Raw HID sender helper."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    sender = (ROOT / "script" / "send_windows_ime_raw_hid_frame.py").read_text(encoding="utf-8")
    assert "DEFAULT_SOCKET = Path(\"/tmp/usbd_windows_ime.sock\")" in sender
    assert "encode_windows_ime_raw_hid_frame" in sender
    assert "socket.SOCK_DGRAM" in sender
    assert "COMMAND_BY_ACTION" in sender
    assert "usbd Windows IME socket is not available" in sender
    assert "--press-only" in sender
    assert "--release-only" in sender
    print("ok: Windows IME Raw HID sender helper")


if __name__ == "__main__":
    main()
