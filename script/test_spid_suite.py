#!/usr/bin/env python3
"""Run spid-related tests that do not require SPI hardware."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "script"))

from suite_runner import run_suite  # noqa: E402

SUITES = (
    "script/test_spid_protocol.py",
    "script/test_spid_backend.py",
    "script/test_spid_daemon.py",
    "script/test_logicd_spid_motion.py",
    "script/test_logicd_ctrl_spid.py",
    "script/test_logicd_spid_direction.py",
    "script/test_logicd_spid_direction_actions.py",
    "script/test_logicd_spid_runtime.py",
)


def main() -> None:
    run_suite("all spid suites", SUITES)


if __name__ == "__main__":
    main()
