#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import stat
from pathlib import Path

EXPECTED_RELEASE_SHA256 = "c862b3a0a598e0d59f202d3ec87181089202b28c896813bf57ff5c43ea4914a8"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expect-release-sha", action="store_true")
    args = parser.parse_args()
    target = args.output / "target"
    image = args.output / "images" / "sdcard.img"
    required = [
        target / "usr/bin/hidloom-hidd",
        target / "usr/bin/hidloom-logicd-core",
        target / "usr/bin/hidloom-outputd",
        target / "usr/bin/hidloom-uidd",
        target / "etc/init.d/S19viald",
        target / "etc/init.d/S31i2cd",
        target / "etc/init.d/S32ledd",
        target / "mnt/p3/vial.json",
        target / "usr/share/hidloom/hidloom_paths.py",
        target / "usr/share/hidloom/daemon/usbd/hid_report_broker.py",
        target / "usr/lib/python3.14/site-packages/luma/core/__init__.pyc",
        target / "usr/lib/python3.14/site-packages/luma/oled/__init__.pyc",
        image,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit("missing M6 artifacts: " + ", ".join(missing))
    sudoers = target / "etc/sudoers.d/pi"
    if stat.S_IMODE(sudoers.stat().st_mode) != 0o440:
        raise SystemExit(f"invalid sudoers mode: {oct(stat.S_IMODE(sudoers.stat().st_mode))}")
    stale_router = target / "etc/init.d/S25hidloom-m3-router"
    if stale_router.exists():
        raise SystemExit(f"stale M3 router init script remains: {stale_router}")
    firmware = (args.output / "images/rpi-firmware/config.txt").read_text(encoding="utf-8")
    cmdline = (args.output / "images/rpi-firmware/cmdline.txt").read_text(encoding="utf-8")
    for setting in ("disable_splash=1", "enable_uart=0", "hdmi_mode=82"):
        if setting not in firmware:
            raise SystemExit(f"missing firmware setting: {setting}")
    if "root=/dev/mmcblk0p2" not in cmdline or "console=ttyAMA" in cmdline:
        raise SystemExit("M6 cmdline is not microSD-only/UART-off")
    image_sha = sha256(image)
    if args.expect_release_sha and image_sha != EXPECTED_RELEASE_SHA256:
        raise SystemExit(f"release SHA mismatch: {image_sha}")
    print(json.dumps({"schema": "hidloom.buildroot-m6.verify.v1", "image": str(image), "sha256": image_sha, "required_files": len(required), "sudoers_mode": "0440", "boot_policy": "microsd-uart-off-hdmi-1080p", "python_path_module": "hidloom_paths.py"}, indent=2))


if __name__ == "__main__":
    main()
