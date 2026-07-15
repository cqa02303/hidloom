#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess


MODULES = (
    "hidloom_paths",
    "luma.core",
    "luma.oled",
    "viald.viald",
    "logicd.logicd",
    "logicd.config_runtime",
    "usbd.hid_report_broker",
    "i2cd.i2cd",
    "ledd.ledd",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import M6 Python runtime with the ARM target interpreter")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--qemu", default="qemu-arm")
    args = parser.parse_args()
    target = args.output.resolve() / "target"
    qemu = shutil.which(args.qemu)
    if qemu is None:
        raise SystemExit(f"ARM emulator not found: {args.qemu}")
    python = target / "usr/bin/python3"
    if not python.exists():
        raise SystemExit(f"target Python missing: {python}")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = ":".join(
        (
            str(target / "usr/share/hidloom"),
            str(target / "usr/share/hidloom/daemon"),
            str(target / "usr/lib/python3.14/site-packages"),
        )
    )
    script = "\n".join(f"import {module}" for module in MODULES)
    subprocess.run(
        [qemu, "-L", str(target), str(python), "-c", script],
        check=True,
        cwd="/tmp",
        env=environment,
    )
    print(f"ok: M6 ARM Python imports ({', '.join(MODULES)})")


if __name__ == "__main__":
    main()
