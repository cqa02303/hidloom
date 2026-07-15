#!/usr/bin/env python3
"""Regression checks for logicd-core active-owner preflight helper."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import logicd_core_active_owner_preflight as preflight  # noqa: E402
import logicd_core_owner_recovery as recovery  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir)
        bin_dir = repo_root / "bin"
        bin_dir.mkdir()
        core_bin = bin_dir / "hidloom-logicd-core"
        core_bin.write_text("#!/bin/sh\n", encoding="utf-8")
        core_bin.chmod(0o755)
        unit_dir = repo_root / "system" / "systemd"
        unit_dir.mkdir(parents=True)
        (unit_dir / "hidloom-logicd-core.service").write_text("[Service]\n", encoding="utf-8")

        payload = {
            "files": {
                "core_binary": preflight.file_mode(core_bin),
                "boot_marker_tool": {"exists": True},
            },
            "units": {
                recovery.CORE_UNIT: {"active": "inactive", "enabled": "disabled"},
                recovery.HIDD_UNIT: {"active": "active", "enabled": "enabled"},
                recovery.LOGICD_UNIT: {"active": "active", "enabled": "enabled"},
                recovery.MATRIXD_UNIT: {"active": "active", "enabled": "enabled"},
            },
            "check_config": {
                "ok": True,
                "payload": {
                    "routing": {
                        "usb_split_keyboard": True,
                        "route": "jis_special_us_default",
                    },
                },
            },
            "recovery_dry_run": {
                "steps": [
                    {"name": "stop logicd-core"},
                    {"name": "disable logicd-core"},
                    {"name": "start logicd"},
                    {"name": "start matrixd"},
                ],
            },
            "status_files": {
                "logicd_core": {
                    "exists": True,
                    "payload": {"process": False},
                },
            },
        }
        ok, issues, warnings = preflight.evaluate(payload)
        assert ok is True
        assert issues == []
        assert warnings == []

    bad_payload = {
        "files": {
            "core_binary": {"exists": False},
            "boot_marker_tool": {"exists": False},
        },
        "units": {
            recovery.CORE_UNIT: {"active": "active", "enabled": "enabled"},
            recovery.HIDD_UNIT: {"active": "inactive", "enabled": "enabled"},
            recovery.LOGICD_UNIT: {"active": "active", "enabled": "enabled"},
            recovery.MATRIXD_UNIT: {"active": "active", "enabled": "enabled"},
        },
        "check_config": {"ok": False},
        "recovery_dry_run": {"steps": [{"name": "stop logicd-core"}]},
        "status_files": {},
    }
    ok, issues, warnings = preflight.evaluate(bad_payload)
    assert ok is False
    assert "hidloom-logicd-core binary is missing" in issues
    assert "boot marker helper is missing" in issues
    assert recovery.CORE_UNIT + " is active; expected inactive before rehearsal" in issues
    assert recovery.CORE_UNIT + " is enabled; expected disabled before reboot rehearsal" in issues
    assert recovery.HIDD_UNIT + " is not active" in issues
    assert "hidloom-logicd-core --check-config failed" in issues
    assert "rollback dry-run is missing step: disable logicd-core" in issues
    assert warnings == []

    text = preflight.render_text(
        {
            "schema": "logicd-core.active-owner-preflight.v1",
            "ok": True,
            "issues": [],
            "warnings": ["sample warning"],
            "next_required": ["next step"],
        }
    )
    assert "sample warning" in text
    assert "next step" in text

    readme = (ROOT / "tools" / "README.md").read_text(encoding="utf-8")
    assert "logicd_core_active_owner_preflight.py" in readme

    print("ok: logicd-core active-owner preflight helper")


if __name__ == "__main__":
    main()
