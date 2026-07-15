#!/usr/bin/env python3
"""Static tests for i2cd connectivity icon row helpers."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from i2cd.connectivity import output_mode_icon_row, wifi_icon_entry, _parse_nmcli_wifi_status, _parse_rfkill_blocked  # noqa: E402


def main() -> None:
    assert output_mode_icon_row("") == []
    assert output_mode_icon_row("off") == []
    assert output_mode_icon_row("gadget") == [("usb", True)]
    assert output_mode_icon_row("bt") == [("bt", True)]
    assert output_mode_icon_row("uinput") == [("pi", True)]
    assert output_mode_icon_row("auto:gadget") == [("auto", True), ("usb", True)]
    assert output_mode_icon_row("auto:bt") == [("auto", True), ("bt", True)]
    assert output_mode_icon_row("auto:uinput") == [("auto", True), ("pi", True)]
    assert output_mode_icon_row("uinput", daemon_status={"hidd": True}) == [("usb", True)]
    assert output_mode_icon_row("uinput", daemon_status={"usbd": True}) == [("usb", True)]
    assert output_mode_icon_row("auto:uinput", daemon_status={"hidd": True}) == [("auto", True), ("usb", True)]
    assert output_mode_icon_row(
        "uinput",
        {"available": True, "powered": True, "connected": True},
        {"hidd": True},
    ) == [("usb", True), ("wifi3", True)]

    assert wifi_icon_entry({}) is None
    assert wifi_icon_entry({"available": False}) is None
    assert wifi_icon_entry({"available": True, "powered": False, "blocked": True}) is None
    assert wifi_icon_entry({"available": True, "powered": True, "connected": False}) == ("wifi0", False)
    assert wifi_icon_entry({"available": True, "powered": True, "connected": None}) == ("wifi0", False)
    assert wifi_icon_entry({"available": True, "powered": True, "connected": True}) == ("wifi3", True)
    assert output_mode_icon_row("gadget", {"available": True, "powered": True, "connected": True}) == [
        ("usb", True),
        ("wifi3", True),
    ]
    assert output_mode_icon_row("auto:bt", {"available": True, "powered": True, "connected": False}) == [
        ("auto", True),
        ("bt", True),
        ("wifi0", False),
    ]

    assert _parse_rfkill_blocked("Soft blocked: no\nHard blocked: no") is False
    assert _parse_rfkill_blocked("Soft blocked: yes\nHard blocked: no") is True
    assert _parse_rfkill_blocked("irrelevant") is None
    nmcli = "lo:loopback:connected:lo\nwlan0:wifi:connected:home\neth0:ethernet:connected:wired"
    assert _parse_nmcli_wifi_status(nmcli, "wlan0") == (True, "home")
    nmcli = "wlan0:wifi:disconnected:"
    assert _parse_nmcli_wifi_status(nmcli, "wlan0") == (False, "")
    assert _parse_nmcli_wifi_status("", "wlan0") == (None, "")
    print("ok: i2cd connectivity icon row helpers")


if __name__ == "__main__":
    main()
