#!/usr/bin/env python3
"""Static checks for Bluetooth host rename / per-host forget design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "bluetooth" / "host-rename-forget-design.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")

    required_phrases = [
        "/mnt/p3/bluetooth_hosts.json",
        "display_name",
        "last_connected_at",
        "BlueZ Alias",
        "Bluetooth address",
        "POST /api/bluetooth/hosts/{address}/rename",
        "POST /api/bluetooth/hosts/{address}/forget",
        "CSRF",
        "audit",
        "bluetooth_host_rename",
        "bluetooth_host_forget",
        "destructive confirmation",
        "per-host forget helper sends one address",
        "corrupt metadata fallback",
        "all-device forget",
        "Real-device checks",
    ]
    for phrase in required_phrases:
        assert phrase in text, phrase
    print("ok: Bluetooth host rename/forget design keeps metadata and destructive operations explicit")


if __name__ == "__main__":
    main()
