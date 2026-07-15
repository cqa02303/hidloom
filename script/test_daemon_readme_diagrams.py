#!/usr/bin/env python3
"""Regression checks for daemon-focused README diagrams."""
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

DAEMON_READMES = {
    "daemon/logicd/README.md": ["matrix_events.sock", "ctrl_events.sock", "config/default/config.json", "OutputRouter"],
    "daemon/matrixd/README.md": ["GPIO charlieplex matrix", "config/default/matrixd.json", "adaptive idle wait"],
    "daemon/ledd/README.md": ["config/default/ledd.json", "ledd_direct_frame.sock", "SK6812MINI-E"],
    "daemon/i2cd/README.md": ["config/default/i2cd.json", "ADS1115", "SH1107 OLED"],
    "daemon/http/README.md": ["HTTPS UI", "config/default/config.json", "http_basic_auth", "ctrl_events.sock"],
    "daemon/viald/README.md": ["config/default/vial.json", "viald_events.sock", "VIA/Vial protocol"],
    "daemon/usbd/README.md": ["USBD_RAW_HID_PATH", "/dev/hidg1", "viald_events.sock"],
    "daemon/btd/README.md": ["BTD_BACKEND", "BlueZ D-Bus", "Bluetooth host"],
    "daemon/spid/README.md": ["SPID_ENABLED", "SPI mouse sensor", "spi_events.sock"],
}


def main() -> None:
    for rel, required_terms in DAEMON_READMES.items():
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "## 担務 / 入出力 / config 図" in text, rel
        assert "```mermaid" in text, rel
        assert "flowchart LR" in text, rel
        for term in required_terms:
            assert term in text, f"{rel}: missing {term}"

    logicd = (ROOT / "daemon/logicd/README.md").read_text(encoding="utf-8")
    matrixd = (ROOT / "daemon/matrixd/README.md").read_text(encoding="utf-8")
    for text in (logicd, matrixd):
        assert "hidloom-logicd-core" in text
        assert "logicd-companion" in text
        assert not re.search(
            r"systemctl\s+(?:start|restart|status)\s+logicd(?:\.service)?(?:\s|$)",
            text,
        )

    print("ok: daemon README diagrams cover role/input/output/config")


if __name__ == "__main__":
    main()
