#!/usr/bin/env python3
"""Tests for KC_SH script safety metadata parsing."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from script_metadata import analyze_script_safety


def main() -> None:
    explicit = analyze_script_safety(
        "#!/bin/sh\n"
        "# @danger reboot\n"
        "# @confirm Reboot this keyboard now?\n"
        "logger safe-before-reboot\n"
    )
    assert explicit.dangerous
    assert explicit.dangers == ("reboot",)
    assert explicit.auto_dangers == ()
    assert explicit.confirm_message == "Reboot this keyboard now?"

    auto = analyze_script_safety("#!/bin/sh\nsudo systemctl reboot\n")
    assert auto.dangerous
    assert "reboot" in auto.auto_dangers

    shutdown = analyze_script_safety("poweroff\n")
    assert shutdown.dangerous
    assert "shutdown" in shutdown.auto_dangers

    destructive = analyze_script_safety("rm -rf / tmp\n")
    assert destructive.dangerous
    assert "destructive-rm" in destructive.auto_dangers

    safe = analyze_script_safety("#!/bin/sh\nlogger hello\nhidloom-oled alert ok 1\n")
    assert not safe.dangerous
    assert safe.as_dict()["dangerous"] is False

    flags = analyze_script_safety("# @pin\n# @hidden\n")
    assert flags.pinned
    assert flags.hidden

    print("ok: script safety metadata")


if __name__ == "__main__":
    main()
