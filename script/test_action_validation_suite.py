#!/usr/bin/env python3
"""Run action validation and codec-related smoke tests."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "script"))

from suite_runner import run_suite  # noqa: E402

TESTS = (
    "script/test_action_expansion.py",
    "script/test_shared_action_defs.py",
    "script/test_http_keymap_action_validation.py",
    "script/test_vial_keycode_codec.py",
)


def main() -> None:
    run_suite("all action validation tests", TESTS)


if __name__ == "__main__":
    main()
