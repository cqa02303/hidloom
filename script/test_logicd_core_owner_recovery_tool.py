#!/usr/bin/env python3
"""Regression checks for logicd-core owner recovery helper."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import logicd_core_owner_recovery as recovery  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir)
        commands = recovery.recovery_commands(sudo=False, repo_root=repo_root)
    names = [name for name, _command in commands]
    assert names[:9] == [
        "stop matrixd",
        "stop logicd-companion",
        "disable logicd-companion",
        "stop logicd-core",
        "disable logicd-core",
        "mask logicd-core runtime",
        "reset failed logicd-core",
        "install matrixd python-owner system unit",
        "daemon reload",
    ]
    assert "mark logicd-core stopped" not in names
    assert names[-4:] == ["start hidloom-hidd", "start logicd", "start matrixd", "final stop logicd-core"]
    assert commands[0][1] == ["systemctl", "stop", recovery.MATRIXD_UNIT]
    assert commands[3][1] == ["systemctl", "stop", recovery.CORE_UNIT]
    assert commands[5][1] == ["systemctl", "mask", "--runtime", recovery.CORE_UNIT]
    assert commands[7][1][:3] == ["sh", "-c", commands[7][1][2]]
    assert str(recovery.MATRIXD_SYSTEM_UNIT) in commands[7][1][2]
    assert str(recovery.MATRIXD_NATIVE_BACKUP) in commands[7][1][2]
    unit = recovery.matrixd_python_owner_unit(ROOT)
    assert "Requires=logicd.service" in unit
    assert "After=logicd.service" in unit
    assert "hidloom-logicd-core.service" not in unit
    assert "stop logicd-companion" in recovery.NON_FATAL_STEPS
    assert "mask logicd-core runtime" in recovery.NON_FATAL_STEPS
    assert "reset failed logicd-core" in recovery.NON_FATAL_STEPS
    assert "mark logicd-core stopped" in recovery.NON_FATAL_STEPS
    assert "final stop logicd-core" in recovery.NON_FATAL_STEPS

    with tempfile.TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir)
        bin_dir = repo_root / "bin"
        bin_dir.mkdir()
        (bin_dir / "hidloom-logicd-core").write_text("#!/bin/sh\n", encoding="utf-8")
        commands = recovery.recovery_commands(sudo=False, repo_root=repo_root)
    assert ("mark logicd-core stopped", [str(bin_dir / "hidloom-logicd-core"), "--mark-stopped"]) in commands

    payload = recovery.run_recovery(apply=False, sudo=False, timeout=1.0, repo_root=ROOT)
    assert payload["schema"] == "logicd-core.owner-recovery.v1"
    assert payload["mode"] == "dry-run"
    assert payload["ok"] is True
    assert payload["steps"]
    assert all(step["skipped"] is True for step in payload["steps"])

    ok, issues = recovery.evaluate(
        {
            recovery.CORE_UNIT: {"active": "inactive", "enabled": "disabled"},
            recovery.COMPANION_UNIT: {"active": "inactive", "enabled": "disabled"},
            recovery.HIDD_UNIT: {"active": "active", "enabled": "enabled"},
            recovery.LOGICD_UNIT: {"active": "active", "enabled": "enabled"},
            recovery.MATRIXD_UNIT: {"active": "active", "enabled": "enabled"},
        }
    )
    assert ok is True
    assert issues == []

    ok, issues = recovery.evaluate(
        {
            recovery.CORE_UNIT: {"active": "active", "enabled": "enabled"},
            recovery.COMPANION_UNIT: {"active": "inactive", "enabled": "disabled"},
            recovery.HIDD_UNIT: {"active": "inactive", "enabled": "enabled"},
            recovery.LOGICD_UNIT: {"active": "active", "enabled": "enabled"},
            recovery.MATRIXD_UNIT: {"active": "active", "enabled": "enabled"},
        }
    )
    assert ok is False
    assert recovery.CORE_UNIT + " is still active" in issues
    assert recovery.CORE_UNIT + " is still enabled" in issues
    assert recovery.HIDD_UNIT + " is not active" in issues

    readme = (ROOT / "tools" / "README.md").read_text(encoding="utf-8")
    assert "logicd_core_owner_recovery.py" in readme

    print("ok: logicd-core owner recovery helper")


if __name__ == "__main__":
    main()
