#!/usr/bin/env python3
"""Static checks for sessiond PTY terminal mirror design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "daemon" / "specs" / "sessiond" / "pty-terminal-mirror-design.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")

    required_phrases = [
        "sessiond",
        "PTY",
        "logicd",
        "usbd",
        "source=pty_terminal_mirror",
        "loop guard",
        "windows_terminal_wsl_cat_us_sub_keyboard",
        "base64 -d",
        "process output",
        "US sub keyboard endpoint",
        "kind=us_sub_keyboard",
        "/dev/hidg2",
        "jis_special_us_default",
        "helper app",
        "Raw HID / companion",
        "US ASCII printable",
        "control code",
        "user 権限",
        "`exit`",
        "row-level diff",
        "experimental",
        "uinput",
        "zero-report",
        "Decisions",
        "Working assumptions",
        "Alternatives considered",
        "M0 completion tests",
        "Open questions and thin areas",
        "backpressure",
        "sessiond-owned socket",
        "terminal parser",
        "完全 terminal emulator を目指さない",
        "screen size",
        "operator 任せ",
        "KC_SH7",
        "bash",
        "軽作業",
        "newline-delimited JSON",
        "120x35",
        "50 ms",
        "client only",
        "failure exits mirror mode",
        "自動復帰しない",
        "OLED feedback",
        "PTY START",
        "PTY EXIT",
        "時計の次の行",
        "payload log",
        "debug opt-in",
        "Risks",
    ]
    for phrase in required_phrases:
        assert phrase in text, phrase
    print("ok: sessiond PTY terminal mirror design keeps daemon, layout, and safety boundaries explicit")


if __name__ == "__main__":
    main()
