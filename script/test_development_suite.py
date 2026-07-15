#!/usr/bin/env python3
"""Run development-time smoke test suites that do not require hardware."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "script"))

from suite_runner import run_suite  # noqa: E402

SUITES = (
    "script/test_action_validation_suite.py",
    "script/test_btd_suite.py",
    "script/test_spid_suite.py",
    "script/test_logicd_ctrl_validation.py",
    "script/test_logicd_bt_alert.py",
    "script/test_logicd_bt_passkey.py",
    "script/test_logicd_mouse_output_mode.py",
    "script/test_output_router.py",
    "script/test_output_router_force.py",
    "script/test_output_switch_auto.py",
    "script/test_vialrgb_ledd.py",
    "script/test_http_system_status.py",
    "script/test_http_bluetooth_api.py",
    "script/test_http_interaction_ui_assets.py",
    "script/test_bt_reconnect_watch_tool.py",
)


def main() -> None:
    run_suite("all development smoke suites", SUITES)


if __name__ == "__main__":
    main()
