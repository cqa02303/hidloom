#!/usr/bin/env python3
"""Run touch-panel real-device smoke tests on <keyboard-host> style profiles."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TOUCH_PANEL_SMOKE = (
    ("python3", "script/test_touch_panel_flick_input.py"),
    ("python3", "script/test_touch_flick_composition_smoke.py"),
    ("python3", "script/test_touch_flick_dispatch.py"),
    ("python3", "script/test_text_send_safety.py"),
    ("python3", "script/test_http_system_status.py"),
    ("python3", "script/test_http_matrix_api.py"),
    ("python3", "script/test_http_keymap_active.py"),
    ("python3", "script/test_http_layout_controls.py"),
    ("python3", "script/test_http_keyboard_layout_labels.py"),
    ("python3", "script/test_i2cd_oled_icons.py"),
    ("python3", "script/test_i2cd_connectivity.py"),
    ("python3", "script/test_i2cd_output_mode_label.py"),
)


def run_command(command: tuple[str, ...]) -> bool:
    print("== " + " ".join(command), flush=True)
    return subprocess.run(command, cwd=ROOT).returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run touch-panel real-device smoke suite")
    parser.add_argument(
        "--include-keyboard-validation",
        action="store_true",
        help="also run script/test_validation_suite.py; this is expected to fail on profiles without SW91",
    )
    args = parser.parse_args()

    failed: list[str] = []
    if args.include_keyboard_validation and not run_command(("python3", "script/test_validation_suite.py")):
        failed.append("keyboard_validation")

    for command in TOUCH_PANEL_SMOKE:
        if not run_command(command):
            failed.append(" ".join(command))

    if failed:
        print("FAILED touch-panel real-device smoke suite:")
        for item in failed:
            print(f"- {item}")
        raise SystemExit(1)
    print("ok: touch-panel real-device smoke suite")


if __name__ == "__main__":
    main()
