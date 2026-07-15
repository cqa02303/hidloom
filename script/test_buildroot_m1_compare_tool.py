#!/usr/bin/env python3
"""Regression checks for Buildroot M1 comparison report helper."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import buildroot_m1_compare as compare  # noqa: E402


RPI_OS_REPORT = """# Boot Marker Baseline

## Systemd Unit Markers

| unit | active | sub | exec_start_sec | active_enter_sec |
| --- | --- | --- | ---: | ---: |
| hidloom-usb-gadget.service | active | exited | 15.280 | 15.558 |
| hidloom-hidd.service | active | running | 15.606 | 15.607 |
| hidloom-logicd-core.service | active | running | 15.628 | 15.630 |
| matrixd.service | active | running | 15.640 | 15.649 |
| ledd.service | active | running | 15.780 | 15.782 |
"""

M1_BOOT_REPORT = """# Boot Marker Baseline

## Systemd Unit Markers

| unit | active | sub | exec_start_sec | active_enter_sec |
| --- | --- | --- | ---: | ---: |
| hidloom-usb-gadget.service | active | exited | 3.100 | 3.250 |
"""

USB_WATCH_REPORT = """# USB Enumeration Watch

stdout:

```text
[+0.100s] unrelated line
[+3.420s] KERNEL add /devices/platform/soc/usb HID CQA02303v5 M1
```
"""


def main() -> None:
    timings = compare.parse_unit_timings(RPI_OS_REPORT)
    assert timings["hidloom-usb-gadget.service"].active_enter_sec == 15.558
    assert compare.parse_usb_first_event_sec(USB_WATCH_REPORT) == 3.420

    report = compare.render_report(
        rpi_os_text=RPI_OS_REPORT,
        m1_boot_text=M1_BOOT_REPORT,
        m1_usb_text=USB_WATCH_REPORT,
        rpi_os_label="rpi-os",
        m1_label="m1",
    )
    assert "# Buildroot M1 Boot Comparison" in report
    assert "| usb gadget active | 15.558 | 3.250 | -12.308 |" in report
    assert "| hidd active | 15.607 |  |  |" in report
    assert "| host USB first matching event |  | 3.420 |  |" in report

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        rpi = tmp_path / "rpi.md"
        m1 = tmp_path / "m1.md"
        usb = tmp_path / "usb.md"
        out = tmp_path / "compare.md"
        rpi.write_text(RPI_OS_REPORT, encoding="utf-8")
        m1.write_text(M1_BOOT_REPORT, encoding="utf-8")
        usb.write_text(USB_WATCH_REPORT, encoding="utf-8")
        proc = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "buildroot_m1_compare.py"),
                "--rpi-os",
                str(rpi),
                "--m1-boot",
                str(m1),
                "--m1-usb-watch",
                str(usb),
                "--output",
                str(out),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        assert out.exists()
        assert "3.420" in out.read_text(encoding="utf-8")

    readme = (ROOT / "tools" / "README.md").read_text(encoding="utf-8")
    assert "buildroot_m1_compare.py" in readme

    plan = (ROOT / "docs" / "ops" / "buildroot-fast-boot-experiment.md").read_text(encoding="utf-8")
    assert "buildroot_m1_compare.py" in plan

    print("ok: Buildroot M1 compare helper")


if __name__ == "__main__":
    main()
