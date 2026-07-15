#!/usr/bin/env python3
"""Run PTY mirror checks that do not require a focused Windows host."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "script"))

from suite_runner import run_suite  # noqa: E402

TESTS = [
    "script/test_sessiond_protocol.py",
    "script/test_sessiond_pty_mirror.py",
    "script/test_sessiond_pty_session.py",
    "script/test_sessiond_pty_terminal_mirror_design_doc.py",
    "script/test_sessiond_socket.py",
    "script/test_sessiond_ctl.py",
    "script/test_logicd_pty_terminal_text.py",
    "script/test_logicd_sessiond_client_text_profiles.py",
    "script/test_logicd_sessiond_client.py",
    "script/test_logicd_pty_mirror_runtime.py",
    "script/test_logicd_sessiond_pty_mirror_integration.py",
]


def main() -> None:
    run_suite("PTY mirror remote/no-HID suite passed", TESTS, stop_on_failure=True)


if __name__ == "__main__":
    main()
