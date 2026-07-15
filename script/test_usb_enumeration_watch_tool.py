#!/usr/bin/env python3
"""Regression checks for host-side USB enumeration watcher."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import usb_enumeration_watch as watch  # noqa: E402


def main() -> None:
    result = watch.CommandResult(
        title="post lsusb",
        command=["lsusb"],
        returncode=0,
        stdout="Bus 001 Device 002: ID 1d6b:0105 CQA02303v5 M1 Keyboard\n",
        stderr="",
        elapsed_sec=0.01,
    )
    report = watch.render_report([result], duration=5.0, include_kernel_log=False)
    assert "# USB Enumeration Watch" in report
    assert "duration_sec: `5.0`" in report
    assert "kernel_log: `skipped`" in report
    assert "Start this watcher on the USB host" in report
    assert "### post lsusb" in report
    assert "1d6b:0105" in report

    timed = watch.CommandResult(
        title="udev usb/hid monitor",
        command=["udevadm", "monitor"],
        returncode=0,
        stdout="[+0.250s] KERNEL[1.0] add /devices/example\n",
        stderr="",
        elapsed_sec=5.0,
    )
    timed_report = watch.render_report([timed], duration=5.0, include_kernel_log=False)
    assert "[+0.250s] KERNEL" in timed_report

    readme = (ROOT / "tools" / "README.md").read_text(encoding="utf-8")
    assert "usb_enumeration_watch.py" in readme
    assert "udevadm monitor" in readme
    assert "+seconds" in readme

    plan = (ROOT / "docs" / "ops" / "buildroot-fast-boot-experiment.md").read_text(encoding="utf-8")
    assert "tools/usb_enumeration_watch.py" in plan
    assert "/tmp/hidloom-usb-enumeration-m1.md" in plan
    assert "`+seconds`" in plan

    print("ok: USB enumeration watch helper")


if __name__ == "__main__":
    main()
