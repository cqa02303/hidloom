#!/usr/bin/env python3
"""Static checks for Consumer Control GATT opt-in design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "bluetooth" / "consumer-control-gatt-opt-in-design.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")

    assert "BTD_CONSUMER_CONTROL=1" in text
    assert "default は `0`" in text
    assert "Report ID: `3`" in text
    assert "Report ID 1 / 2 を変更しない" in text
    assert "Keyboard / Mouse BLE HID" in text
    assert "flag off で Consumer Control frame を受けても GATT notify しない" in text
    assert "consumer_control_gatt_enabled" in text
    assert "iOS" in text and "macOS" in text and "Windows" in text and "Linux" in text and "Android" in text
    assert "BTD_CONSUMER_CONTROL=0" in text
    assert "HTTP から systemd environment を直接書き換えない" in text
    assert "既存 bond" in text
    print("ok: Consumer Control GATT opt-in design keeps BLE compatibility boundaries explicit")


if __name__ == "__main__":
    main()
