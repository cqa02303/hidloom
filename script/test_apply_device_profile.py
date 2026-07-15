#!/usr/bin/env python3
"""Regression checks for device profile apply planning."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "script" / "apply_device_profile.py"


def load_module():
    spec = importlib.util.spec_from_file_location("apply_device_profile", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        runtime = Path(td) / "runtime"
        runtime.mkdir()
        (runtime / "flick.json").write_text("{}\n", encoding="utf-8")
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "touch-waveshare-8.8",
                "--profile-dir",
                str(ROOT / "config" / "device-profiles"),
                "--runtime-dir",
                str(runtime),
                "--dry-run",
                "--backup",
                "--restart",
            ],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    assert "copy" in proc.stdout
    assert "config/default/touch-panel/keymap.json" in proc.stdout
    assert "remove" in proc.stdout
    assert "flick.json" in proc.stdout
    assert "write-marker" in proc.stdout
    assert "write-dropin" in proc.stdout
    assert "httpd.service.d/10-hidloom-device-profile.conf" in proc.stdout
    assert "systemctl daemon-reload" in proc.stdout
    assert "systemctl disable matrixd.service" in proc.stdout
    assert "systemctl stop matrixd.service" in proc.stdout
    assert "systemctl mask matrixd.service" in proc.stdout
    assert "systemctl restart hidloom-usb-gadget.service" in proc.stdout

    module = load_module()
    content = module.render_dropin(
        "httpd.service",
        {
            "Unit": {
                "After": ["logicd.service"],
                "Wants": ["logicd.service"],
            }
        },
    )
    assert "[Unit]" in content
    assert "After=\nAfter=logicd.service" in content
    assert "Wants=\nWants=logicd.service" in content

    logicd = module.render_dropin(
        "logicd.service",
        {
            "Service": {
                "Environment": {
                    "LOGICD_MATRIX_ROWS": "16",
                    "LOGICD_MATRIX_COLS": "16",
                }
            }
        },
    )
    assert 'Environment="LOGICD_MATRIX_ROWS=16"' in logicd
    assert 'Environment="LOGICD_MATRIX_COLS=16"' in logicd

    print("ok: device profile apply dry-run")


if __name__ == "__main__":
    main()
