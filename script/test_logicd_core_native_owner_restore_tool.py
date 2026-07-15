#!/usr/bin/env python3
"""Regression checks for logicd-core native owner restore helper."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import logicd_core_native_owner_restore as restore  # noqa: E402


def main() -> None:
    commands = restore.restore_commands(sudo=False)
    names = [name for name, _command in commands]
    assert names == [
        "stop matrixd",
        "stop legacy logicd",
        "disable legacy logicd",
        "unmask logicd-core",
        "restore native matrixd system unit",
        "remove python-owner runtime unit",
        "remove python-owner drop-in",
        "daemon reload",
        "enable native owner units",
        "start hidloom-hidd",
        "restart logicd-core",
        "restart matrixd",
        "restart logicd-companion",
        "reset failed legacy logicd",
    ]
    assert commands[0][1] == ["systemctl", "stop", restore.MATRIXD_UNIT]
    assert commands[3][1] == ["systemctl", "unmask", restore.CORE_UNIT]
    assert commands[4][1][:3] == ["sh", "-c", commands[4][1][2]]
    assert str(restore.MATRIXD_SYSTEM_UNIT) in commands[4][1][2]
    assert str(restore.MATRIXD_NATIVE_BACKUP) in commands[4][1][2]
    assert commands[5][1] == ["rm", "-f", str(restore.PYTHON_OWNER_RUNTIME_UNIT)]
    assert commands[6][1] == ["rm", "-f", str(restore.PYTHON_OWNER_DROPIN)]
    assert commands[8][1] == [
        "systemctl",
        "enable",
        restore.HIDD_UNIT,
        restore.CORE_UNIT,
        restore.MATRIXD_UNIT,
        restore.COMPANION_UNIT,
    ]
    assert "remove python-owner runtime unit" in restore.NON_FATAL_STEPS
    assert "remove python-owner drop-in" in restore.NON_FATAL_STEPS
    assert "unmask logicd-core" in restore.NON_FATAL_STEPS

    payload = restore.run_restore(apply=False, sudo=False, timeout=1.0)
    assert payload["schema"] == "logicd-core.native-owner-restore.v1"
    assert payload["mode"] == "dry-run"
    assert payload["ok"] is True
    assert payload["steps"]
    assert all(step["skipped"] is True for step in payload["steps"])

    ok, issues = restore.evaluate(
        {
            restore.HIDD_UNIT: {"active": "active", "enabled": "enabled"},
            restore.CORE_UNIT: {"active": "active", "enabled": "enabled"},
            restore.MATRIXD_UNIT: {"active": "active", "enabled": "enabled"},
            restore.COMPANION_UNIT: {"active": "active", "enabled": "enabled"},
            restore.LOGICD_UNIT: {"active": "inactive", "enabled": "disabled"},
        },
        dropin_exists=False,
    )
    assert ok is True
    assert issues == []

    ok, issues = restore.evaluate(
        {
            restore.HIDD_UNIT: {"active": "active", "enabled": "enabled"},
            restore.CORE_UNIT: {"active": "inactive", "enabled": "disabled"},
            restore.MATRIXD_UNIT: {"active": "active", "enabled": "enabled"},
            restore.COMPANION_UNIT: {"active": "active", "enabled": "enabled"},
            restore.LOGICD_UNIT: {"active": "active", "enabled": "enabled"},
        },
        dropin_exists=True,
    )
    assert ok is False
    assert str(restore.PYTHON_OWNER_DROPIN) + " still exists" in issues
    assert restore.CORE_UNIT + " is not active" in issues
    assert restore.CORE_UNIT + " is not enabled" in issues
    assert restore.LOGICD_UNIT + " is still active" in issues
    assert restore.LOGICD_UNIT + " is still enabled" in issues

    print("ok: logicd-core native owner restore helper")


if __name__ == "__main__":
    main()
