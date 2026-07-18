#!/usr/bin/env python3
"""Static tests for i2cd connectivity icon row helpers."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from i2cd.connectivity import (  # noqa: E402
    _parse_nmcli_wifi_status,
    _parse_rfkill_blocked,
    effective_output_display_mode,
    load_outputd_status,
    output_mode_icon_row,
    outputd_display_mode,
    wifi_icon_entry,
)


def main() -> None:
    assert output_mode_icon_row("") == []
    assert output_mode_icon_row("off") == []
    assert output_mode_icon_row("gadget") == [("usb", True)]
    assert output_mode_icon_row("bt") == [("bt", True)]
    assert output_mode_icon_row("uinput") == [("pi", True)]
    assert output_mode_icon_row("auto:gadget") == [("auto", True), ("usb", True)]
    assert output_mode_icon_row("auto:bt") == [("auto", True), ("bt", True)]
    assert output_mode_icon_row("auto:uinput") == [("auto", True), ("pi", True)]
    assert output_mode_icon_row("uinput", daemon_status={"hidd": True}) == [("pi", True)]
    assert output_mode_icon_row("uinput", daemon_status={"usbd": True}) == [("pi", True)]
    assert output_mode_icon_row("auto:uinput", daemon_status={"hidd": True}) == [("auto", True), ("pi", True)]
    assert output_mode_icon_row(
        "uinput",
        {"available": True, "powered": True, "connected": True},
        {"hidd": True},
    ) == [("pi", True), ("wifi3", True)]

    assert outputd_display_mode({}) == ""
    assert outputd_display_mode({"schema": "wrong", "process": True, "target": "auto"}) == ""
    assert outputd_display_mode({"schema": "hidloom.outputd.status.v1", "process": False, "target": "auto"}) == ""
    assert outputd_display_mode({"schema": "hidloom.outputd.status.v1", "process": True, "target": "auto"}) == "auto:gadget"
    assert outputd_display_mode({"schema": "hidloom.outputd.status.v1", "process": True, "target": "usb"}) == "gadget"
    assert outputd_display_mode({"schema": "hidloom.outputd.status.v1", "process": True, "target": "uinput"}) == "uinput"
    assert outputd_display_mode({"schema": "hidloom.outputd.status.v1", "process": True, "target": "bt"}) == "bt"
    auto_status = {"schema": "hidloom.outputd.status.v1", "process": True, "target": "auto"}
    assert effective_output_display_mode("uinput", auto_status) == "auto:gadget"
    assert effective_output_display_mode("uinput", {}) == "uinput"
    with tempfile.TemporaryDirectory() as tmpdir:
        status_path = Path(tmpdir) / "outputd-status.json"
        status_path.write_text(json.dumps(auto_status), encoding="utf-8")
        assert load_outputd_status(status_path) == auto_status
        old = time.time() - 10
        os.utime(status_path, (old, old))
        assert load_outputd_status(status_path, max_age_sec=2.0) == {}
    config = json.loads((ROOT / "config" / "default" / "i2cd.json").read_text(encoding="utf-8"))
    assert config["ipc"]["outputd_status"] == "/run/hidloom/outputd-status.json"
    assert config["display"]["output_status_poll_interval_sec"] == 0.5

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
