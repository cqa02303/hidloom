#!/usr/bin/env python3
"""Regression checks for device profile inventory metadata."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "script" / "device_profile_inventory.py"


def main() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    payload = json.loads(proc.stdout)
    profiles = {profile["id"]: profile for profile in payload["profiles"]}
    assert set(profiles) == {
        "keyboard-ver0-prototype",
        "keyboard-ver1",
        "touch-osoyoo-4.3",
        "touch-waveshare-8.8",
    }

    keyboard = profiles["keyboard-ver1"]
    assert keyboard["kind"] == "keyboard"
    assert keyboard["source"]["board_profile"] == "ver1.0"
    assert "matrixd.service" in keyboard["services"]["enable"]
    assert "logicd.service" in keyboard["services"]["disable"]
    assert set(keyboard["runtime_files"]) == {"keymap.json", "keyboard-layout.json", "vial.json"}
    assert "matrixd.json" in keyboard["config_files"]

    prototype = profiles["keyboard-ver0-prototype"]
    assert prototype["prototype"] is True
    assert prototype["source"]["board_profile"] == "ver0.1"

    touch = profiles["touch-waveshare-8.8"]
    assert touch["kind"] == "touch-panel"
    assert "480x1920" in touch["display"]["match"]
    assert "logicd.service" in touch["services"]["enable"]
    assert "httpd.service" in touch["services"]["enable"]
    assert "viald.service" in touch["services"]["enable"]
    assert "matrixd.service" in touch["services"]["disable"]
    assert "hidloom-logicd-core.service" in touch["services"]["disable"]
    assert "usbd.service" in touch["services"]["disable"]
    assert "logicd-companion.service" in touch["services"]["mask"]
    logicd_env = touch["dropins"]["logicd.service"]["Service"]["Environment"]
    assert logicd_env["LOGICD_MATRIX_ROWS"] == "16"
    assert touch["dropins"]["httpd.service"]["Unit"]["Wants"] == ["logicd.service"]
    assert "flick.json" not in touch["runtime_files"]

    osoyoo = profiles["touch-osoyoo-4.3"]
    assert "800x480" in osoyoo["display"]["match"]
    assert "flick.json" in osoyoo["runtime_files"]

    plan = (ROOT / "docs" / "ops" / "package-profile-split-plan.md").read_text(encoding="utf-8")
    assert "M1: profile inventory helper" in plan
    assert "touch-waveshare-8.8" in plan
    assert "script/apply_device_profile.py" in plan

    print("ok: device profile inventory metadata")


if __name__ == "__main__":
    main()
