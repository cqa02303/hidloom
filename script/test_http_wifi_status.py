#!/usr/bin/env python3
"""Regression tests for HTTP Wi-Fi status helpers and wiring."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon" / "http"))

from wifi_status import _parse_nmcli_wifi_status, _parse_rfkill_blocked  # noqa: E402


def main() -> None:
    httpd = (ROOT / "daemon" / "http" / "httpd.py").read_text(encoding="utf-8")
    assert "from wifi_status import wifi_status" in httpd
    assert "logicd_data, interaction_status, logicd_env, btd_env" in httpd
    assert "await asyncio.gather" in httpd
    assert "wifi_status()," in httpd
    assert '"wifi": wifi,' in httpd

    wifi_py = (ROOT / "daemon" / "http" / "wifi_status.py").read_text(encoding="utf-8")
    assert "side-effect free" in wifi_py
    assert "rfkill" in wifi_py
    assert "nmcli" in wifi_py
    assert "recovery_first" in wifi_py
    assert "persistent_power_off" in wifi_py
    assert "proc.kill()" in wifi_py

    assert _parse_rfkill_blocked("Soft blocked: yes\nHard blocked: no\n") is True
    assert _parse_rfkill_blocked("Soft blocked: no\nHard blocked: no\n") is False
    assert _parse_rfkill_blocked("Hard blocked: yes\n") is True
    assert _parse_rfkill_blocked("no rfkill output") is None

    assert _parse_nmcli_wifi_status("wlan0:wifi:connected:HomeAP\n", "wlan0") == (True, "HomeAP")
    assert _parse_nmcli_wifi_status("wlan0:wifi:disconnected:--\n", "wlan0") == (False, "")
    assert _parse_nmcli_wifi_status("wlan1:wifi:connected:Other\n", "wlan0") == (None, "")
    assert _parse_nmcli_wifi_status("eth0:ethernet:connected:lan\n", "wlan0") == (None, "")

    print("ok: HTTP Wi-Fi status helper and wiring")


if __name__ == "__main__":
    main()
