#!/usr/bin/env python3
"""Regression tests for recovery-first Wi-Fi manager."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.wifi_manager import (  # noqa: E402
    WifiManager,
    _parse_nmcli_wifi_status,
    _parse_rfkill_blocked,
)


class FakeWifiManager(WifiManager):
    def __init__(self) -> None:
        super().__init__(command_timeout=0.1)
        self.commands: list[tuple[str, ...]] = []
        self.rfkill_text = "0: phy0: Wireless LAN\n\tSoft blocked: no\n\tHard blocked: no\n"
        self.nmcli_text = "wlan0:wifi:connected:HomeAP\n"
        self.available_commands = {"rfkill", "nmcli"}

    async def _run_text(self, *cmd: str, check: bool = True) -> str:  # noqa: ARG002
        self.commands.append(tuple(cmd))
        if cmd[:2] == ("rfkill", "list"):
            return self.rfkill_text
        if cmd[:1] == ("nmcli",):
            return self.nmcli_text
        return ""

    def _command_available(self, name: str) -> bool:
        return name in self.available_commands


async def main_async() -> None:
    assert _parse_rfkill_blocked("Soft blocked: yes\nHard blocked: no\n") is True
    assert _parse_rfkill_blocked("Soft blocked: no\nHard blocked: no\n") is False
    assert _parse_rfkill_blocked("") is None
    assert _parse_nmcli_wifi_status("wlan0:wifi:connected:HomeAP\n", "wlan0") == (True, "HomeAP")
    assert _parse_nmcli_wifi_status("wlan0:wifi:disconnected:--\n", "wlan0") == (False, "")
    assert _parse_nmcli_wifi_status("eth0:ethernet:connected:lan\n", "wlan0") == (None, "")

    wifi = FakeWifiManager()
    assert wifi.handles("WIFI_POWER_TOGGLE")
    assert not wifi.handles("BT_POWER_TOGGLE")

    status = await wifi.get_status()
    assert status.blocked is False
    assert status.connected is True
    assert status.ssid == "HomeAP"

    await wifi.power(False)
    assert ("rfkill", "block", "wifi") in wifi.commands
    assert not any(cmd[:1] == ("systemctl",) for cmd in wifi.commands)

    await wifi.power(True)
    assert ("rfkill", "unblock", "wifi") in wifi.commands

    wifi = FakeWifiManager()
    wifi.available_commands.remove("rfkill")
    status = await wifi.get_status()
    assert status.blocked is None
    assert status.connected is True
    await wifi.power(False)
    assert ("nmcli", "radio", "wifi", "off") in wifi.commands
    await wifi.power(True)
    assert ("nmcli", "radio", "wifi", "on") in wifi.commands
    assert not any(cmd[:1] == ("rfkill",) for cmd in wifi.commands)

    wifi = FakeWifiManager()
    wifi.rfkill_text = "0: phy0: Wireless LAN\n\tSoft blocked: yes\n\tHard blocked: no\n"
    await wifi.toggle_power()
    assert ("rfkill", "unblock", "wifi") in wifi.commands

    wifi = FakeWifiManager()
    wifi.rfkill_text = "0: phy0: Wireless LAN\n\tSoft blocked: no\n\tHard blocked: no\n"
    await wifi.toggle_power()
    assert ("rfkill", "block", "wifi") in wifi.commands

    print("ok: Wi-Fi manager recovery-first behavior")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
