#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import stat
import subprocess
import tempfile
from pathlib import Path

EXPECTED_RELEASE_SHA256 = "c862b3a0a598e0d59f202d3ec87181089202b28c896813bf57ff5c43ea4914a8"
ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def filesystem_file(debugfs: Path, rootfs: Path, path: str) -> str:
    result = subprocess.run(
        [str(debugfs), "-R", f"cat {path}", str(rootfs)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"failed to read {path} from {rootfs}: {result.stderr.strip()}")
    return result.stdout


def filesystem_bytes(debugfs: Path, rootfs: Path, path: str) -> bytes:
    with tempfile.TemporaryDirectory(prefix="hidloom-m6-verify-") as temporary:
        output = Path(temporary) / "payload"
        result = subprocess.run(
            [str(debugfs), "-R", f"dump -p {path} {output}", str(rootfs)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not output.exists():
            raise SystemExit(f"failed to extract {path} from {rootfs}: {result.stderr.strip()}")
        return output.read_bytes()


def embedded_partition_sha256(image: Path, partition_index: int, payload_size: int) -> str:
    if partition_index < 0 or partition_index > 3:
        raise SystemExit(f"invalid MBR partition index: {partition_index}")
    with image.open("rb") as stream:
        mbr = stream.read(512)
        if len(mbr) != 512 or mbr[510:512] != b"\x55\xaa":
            raise SystemExit(f"invalid MBR signature: {image}")
        entry_offset = 446 + partition_index * 16
        entry = mbr[entry_offset : entry_offset + 16]
        start_lba = int.from_bytes(entry[8:12], "little")
        sectors = int.from_bytes(entry[12:16], "little")
        partition_size = sectors * 512
        if start_lba == 0 or sectors == 0 or payload_size > partition_size:
            raise SystemExit(
                f"invalid MBR partition {partition_index + 1}: "
                f"start_lba={start_lba} sectors={sectors} payload_size={payload_size}"
            )
        stream.seek(start_lba * 512)
        digest = hashlib.sha256()
        remaining = payload_size
        while remaining:
            chunk = stream.read(min(1024 * 1024, remaining))
            if not chunk:
                raise SystemExit(f"truncated partition {partition_index + 1} in {image}")
            digest.update(chunk)
            remaining -= len(chunk)
        return digest.hexdigest()


def account_fields(content: str, account: str, source: str) -> list[str]:
    for line in content.splitlines():
        fields = line.split(":")
        if fields[0] == account:
            return fields
    raise SystemExit(f"missing account {account!r} in {source}")


def active_getty_entries(content: str) -> list[str]:
    return [
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "/sbin/getty" in line
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expect-release-sha", action="store_true")
    args = parser.parse_args()
    target = args.output / "target"
    image = args.output / "images" / "sdcard.img"
    rootfs = args.output / "images" / "rootfs.ext2"
    debugfs = args.output / "host/sbin/debugfs"
    required = [
        target / "usr/bin/hidloom-hidd",
        target / "usr/bin/hidloom-logicd-core",
        target / "usr/bin/hidloom-outputd",
        target / "usr/bin/hidloom-uidd",
        target / "usr/bin/hidloom-hid-gadget-m4",
        target / "etc/init.d/S19viald",
        target / "etc/init.d/S20hidloom-hid-gadget",
        target / "etc/init.d/S31i2cd",
        target / "etc/init.d/S32ledd",
        target / "mnt/p3/vial.json",
        target / "usr/share/hidloom/hidloom_paths.py",
        target / "usr/share/hidloom/config/default/oled-layout.json",
        target / "usr/share/hidloom/daemon/oled_text.py",
        target / "usr/share/hidloom/daemon/i2cd/connectivity_icon_bitmaps.txt",
        target / "usr/share/hidloom/daemon/i2cd/oled_customization.py",
        target / "usr/share/hidloom/daemon/usbd/hid_report_broker.py",
        target / "usr/lib/python3.14/site-packages/luma/core/__init__.pyc",
        target / "usr/lib/python3.14/site-packages/luma/oled/__init__.pyc",
        debugfs,
        rootfs,
        image,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit("missing M6 artifacts: " + ", ".join(missing))
    sudoers = target / "etc/sudoers.d/pi"
    if stat.S_IMODE(sudoers.stat().st_mode) != 0o440:
        raise SystemExit(f"invalid sudoers mode: {oct(stat.S_IMODE(sudoers.stat().st_mode))}")
    passwd_fields = account_fields(
        filesystem_file(debugfs, rootfs, "/etc/passwd"),
        "pi",
        f"{rootfs}:/etc/passwd",
    )
    if passwd_fields[2:4] != ["1001", "1001"] or passwd_fields[5:] != ["/home/pi", "/bin/sh"]:
        raise SystemExit("invalid M6 pi passwd entry")
    expected_password_hash = (
        ROOT / "build/buildroot/hidloom-external/board/hidloom/users_m6.txt"
    ).read_text(encoding="utf-8").split()[4]
    shadow_fields = account_fields(
        filesystem_file(debugfs, rootfs, "/etc/shadow"),
        "pi",
        f"{rootfs}:/etc/shadow",
    )
    if not expected_password_hash.startswith("$5$") or shadow_fields[1] != expected_password_hash:
        raise SystemExit("M6 pi password hash does not match the SHA-256 users table")
    wheel_fields = account_fields(
        filesystem_file(debugfs, rootfs, "/etc/group"),
        "wheel",
        f"{rootfs}:/etc/group",
    )
    if "pi" not in wheel_fields[3].split(","):
        raise SystemExit("M6 pi account is not in wheel")
    inittab = filesystem_file(debugfs, rootfs, "/etc/inittab")
    getty_entries = active_getty_entries(inittab)
    if len(getty_entries) != 1 or not getty_entries[0].startswith("tty1::respawn:/sbin/getty "):
        raise SystemExit(f"M6 must have exactly one tty1 getty: {getty_entries}")
    if getty_entries[0].split()[:5] != [
        "tty1::respawn:/sbin/getty",
        "-L",
        "tty1",
        "0",
        "vt100",
    ]:
        raise SystemExit(f"M6 tty1 getty has unexpected arguments: {getty_entries[0]}")
    stale_router = target / "etc/init.d/S25hidloom-m3-router"
    if stale_router.exists():
        raise SystemExit(f"stale M3 router init script remains: {stale_router}")
    gadget = (target / "usr/bin/hidloom-hid-gadget-m4").read_text(encoding="utf-8")
    if "vial:f64c2b3c" not in gadget or "m4-native-split" in gadget:
        raise SystemExit("M6 USB gadget does not expose the Vial serial magic")
    main_keyboard = gadget.split("mkdir -p functions/hid.usb0", 1)[-1].split(
        "mkdir -p functions/hid.usb1", 1
    )[0]
    sub_keyboard = gadget.split("mkdir -p functions/hid.usb2", 1)[-1].split(
        "mkdir -p configs/c.1", 1
    )[0]
    if "printf '9\\n' > report_length" not in main_keyboard or "\\x85\\x01" not in main_keyboard.lower():
        raise SystemExit("M6 main keyboard descriptor must use 9-byte Report-ID 0x01 reports")
    if "printf '8\\n' > report_length" not in sub_keyboard or "\\x85" in sub_keyboard.lower():
        raise SystemExit("M6 US sub keyboard descriptor must use 8-byte reports without a Report ID")
    hidd_binary = (target / "usr/bin/hidloom-hidd").read_bytes()
    if b"USBD_KEYBOARD_STARTUP_RELEASE" not in hidd_binary:
        raise SystemExit("M6 hidloom-hidd does not contain the startup keyboard release guard")
    if filesystem_bytes(debugfs, rootfs, "/usr/bin/hidloom-hidd") != hidd_binary:
        raise SystemExit("M6 rootfs hidloom-hidd differs from the verified target binary")
    if filesystem_bytes(debugfs, rootfs, "/usr/bin/hidloom-hid-gadget-m4") != gadget.encode():
        raise SystemExit("M6 rootfs HID gadget script differs from the verified target script")
    rootfs_sha = sha256(rootfs)
    embedded_rootfs_sha = embedded_partition_sha256(image, 1, rootfs.stat().st_size)
    if embedded_rootfs_sha != rootfs_sha:
        raise SystemExit("M6 image rootfs partition differs from the verified rootfs image")
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
    print(json.dumps({"schema": "hidloom.buildroot-m6.verify.v1", "image": str(image), "sha256": image_sha, "rootfs_sha256": rootfs_sha, "rootfs_partition_embedded": True, "required_files": len(required), "sudoers_mode": "0440", "console_account": "pi", "console_password_hash": "sha256-crypt", "console_sudo_group": "wheel", "console_getty": "tty1-single", "boot_policy": "microsd-uart-off-hdmi-1080p", "python_path_module": "hidloom_paths.py", "vial_serial_magic": "vial:f64c2b3c", "usb_keyboard_contract": "hidg0-report-id-01-9-byte+hidg2-no-report-id-8-byte"}, indent=2))


if __name__ == "__main__":
    main()
