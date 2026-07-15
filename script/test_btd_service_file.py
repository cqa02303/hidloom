#!/usr/bin/env python3
"""Smoke test for btd systemd unit defaults."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "system" / "systemd" / "btd.service"


def main() -> None:
    text = SERVICE.read_text(encoding="utf-8")

    assert "Description=HIDloom Bluetooth HID daemon" in text
    assert "After=bluetooth.service" in text
    assert "Wants=bluetooth.service" in text
    assert "WorkingDirectory=@HIDLOOM_REPO_ROOT@" in text
    assert text.count("EnvironmentFile=-/etc/hidloom/usb-identity.env") == 1
    assert "ExecStart=/usr/bin/python3 -m btd.btd" in text
    assert "ExecStartPre=/bin/rm -f /tmp/btd_events.sock" in text
    assert "User=root" in text
    assert "Group=root" in text
    assert "Environment=PYTHONPATH=@HIDLOOM_REPO_ROOT@/daemon:@HIDLOOM_REPO_ROOT@" in text
    assert text.count("Environment=HIDLOOM_REPO_ROOT=@HIDLOOM_REPO_ROOT@") == 1
    assert "Environment=BTD_BACKEND=logging" in text
    assert "Environment=BTD_EVENTS_SOCK=/tmp/btd_events.sock" in text
    assert "Environment=BTD_REPORT_SIZE=8" in text
    assert "Environment=BTD_SOCKET_MODE=666" in text
    assert "Restart=on-failure" in text

    print("ok: btd service file")


if __name__ == "__main__":
    main()
