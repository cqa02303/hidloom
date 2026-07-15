#!/usr/bin/env python3
"""Static checks for Buildroot fast boot M1 assets."""
from __future__ import annotations

import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
BR = ROOT / "build" / "buildroot"
EXTERNAL = BR / "hidloom-external"
BOARD = EXTERNAL / "board" / "hidloom"
OVERLAY = BOARD / "rootfs_overlay"
M2_OVERLAY = BOARD / "rootfs_overlay_m2"
M4_OVERLAY = BOARD / "rootfs_overlay_m4"
M6_OVERLAY = BOARD / "rootfs_overlay_m6"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def assert_executable(path: Path) -> None:
    assert path.exists(), path
    assert os.access(path, os.X_OK), f"{path.relative_to(ROOT)} should be executable"


def main() -> None:
    assert (BR / "README.md").exists()
    assert "name: HIDLOOM" in read(EXTERNAL / "external.desc")
    assert "package/hidloom-matrixd/Config.in" in read(EXTERNAL / "Config.in")
    assert "package/hidloom-m3-router/Config.in" in read(EXTERNAL / "Config.in")
    assert "package/python-luma-core/Config.in" in read(EXTERNAL / "Config.in")
    assert "package/python-luma-oled/Config.in" in read(EXTERNAL / "Config.in")
    assert "package/*/*.mk" in read(EXTERNAL / "external.mk")

    for milestone_defconfig in sorted((EXTERNAL / "configs").glob("hidloom_m*_defconfig")):
        for relative in re.findall(
            r"\$\(BR2_EXTERNAL_HIDLOOM_PATH\)/([^\" ]+)", read(milestone_defconfig)
        ):
            assert (EXTERNAL / relative).exists(), f"dangling reference in {milestone_defconfig}: {relative}"

    defconfig = read(EXTERNAL / "configs" / "hidloom_m1_defconfig")
    assert "BR2_ROOTFS_OVERLAY=\"$(BR2_EXTERNAL_HIDLOOM_PATH)/board/hidloom/rootfs_overlay\"" in defconfig
    assert "BR2_LINUX_KERNEL_CONFIG_FRAGMENT_FILES=\"$(BR2_EXTERNAL_HIDLOOM_PATH)/board/hidloom/linux-m1-usb-gadget.fragment\"" in defconfig
    assert "BR2_PACKAGE_RPI_FIRMWARE_CONFIG_FILE=\"$(BR2_EXTERNAL_HIDLOOM_PATH)/board/hidloom/config_zero2w_m1.txt\"" in defconfig
    assert "BR2_PACKAGE_RPI_FIRMWARE_CMDLINE_FILE=\"$(BR2_EXTERNAL_HIDLOOM_PATH)/board/hidloom/cmdline_m1.txt\"" in defconfig

    m2_defconfig = read(EXTERNAL / "configs" / "hidloom_m2_defconfig")
    assert "rootfs_overlay_m2" in m2_defconfig
    assert "hidloom_m1_defconfig" not in m2_defconfig

    kernel_fragment = read(BOARD / "linux-m1-usb-gadget.fragment")
    assert "CONFIG_USB_DWC2_PERIPHERAL=y" in kernel_fragment
    assert "CONFIG_USB_CONFIGFS_HID=y" in kernel_fragment
    assert "CONFIG_USB_F_HID=y" in kernel_fragment

    firmware_config = read(BOARD / "config_zero2w_m1.txt")
    assert "dtoverlay=dwc2,dr_mode=peripheral" in firmware_config
    assert "enable_uart=1" in firmware_config

    cmdline = read(BOARD / "cmdline_m1.txt")
    assert "modules-load=dwc2,libcomposite" in cmdline

    init_script = OVERLAY / "etc" / "init.d" / "S20hidloom-hid-gadget"
    gadget_script = OVERLAY / "usr" / "bin" / "hidloom-hid-gadget-m1"
    tap_script = OVERLAY / "usr" / "bin" / "hidloom-hid-key-tap-m1"
    for path in [init_script, gadget_script, tap_script]:
        assert_executable(path)
        assert read(path).startswith("#!/bin/sh"), path

    init_text = read(init_script)
    assert "/usr/bin/hidloom-hid-gadget-m1 start" in init_text
    assert "hidloom-hid-key-tap-m1" not in init_text, "M1 boot must not send keys automatically"

    gadget_text = read(gadget_script)
    assert "Minimal Buildroot M1 USB HID keyboard gadget" in gadget_text
    assert "functions/hid.usb0" in gadget_text
    assert "printf '1\\n' > protocol" in gadget_text
    assert "printf '1\\n' > subclass" in gadget_text
    assert "printf '8\\n' > report_length" in gadget_text
    assert "hidg_ready" in gadget_text
    assert "m1_udc_bound" in gadget_text
    assert "hid.usb1" not in gadget_text, "M1 must not add Raw HID / Vial"
    assert "logicd" not in gadget_text
    assert "python" not in gadget_text

    tap_text = read(tap_script)
    assert "Manual M2 smoke helper" in tap_text
    assert "printf '\\000\\000\\000\\000\\000\\000\\000\\000'" in tap_text
    assert "sleep \"$HOLD_SEC\"" in tap_text

    m2_init = M2_OVERLAY / "etc" / "init.d" / "S30hidloom-hid-one-shot"
    m2_gadget_init = M2_OVERLAY / "etc" / "init.d" / "S20hidloom-hid-gadget"
    m2_one_shot = M2_OVERLAY / "usr" / "bin" / "hidloom-hid-one-shot-m2"
    for path in [m2_init, m2_gadget_init, m2_one_shot]:
        assert_executable(path)
        assert read(path).startswith("#!/bin/sh"), path

    assert "CQA02303v5 M2 One-shot Keyboard" in read(m2_gadget_init)
    m2_one_shot_text = read(m2_one_shot)
    assert 'DELAY_SEC="${HIDLOOM_M2_DELAY_SEC:-10}"' in m2_one_shot_text
    assert 'marker "m2_wait_start"' in m2_one_shot_text
    assert 'marker "m2_tap_start"' in m2_one_shot_text
    assert 'marker "m2_tap_done"' in m2_one_shot_text
    assert '/usr/bin/hidloom-hid-key-tap-m1 "$DEVICE" 04 0.08' in m2_one_shot_text
    assert "hidloom-hid-one-shot-m2" not in init_text, "M1 must not run the M2 one-shot helper"

    m3_defconfig = read(EXTERNAL / "configs" / "hidloom_m3_defconfig")
    assert "BR2_PACKAGE_HIDLOOM_MATRIXD=y" in m3_defconfig
    assert "BR2_PACKAGE_HIDLOOM_M3_ROUTER=y" in m3_defconfig
    assert "rootfs_overlay_m3" in m3_defconfig
    assert "linux-m3-matrix.fragment" in m3_defconfig
    assert "CONFIG_RASPBERRYPI_GPIOMEM=y" in read(BOARD / "linux-m3-matrix.fragment")
    m3_router = read(EXTERNAL / "package" / "hidloom-m3-router" / "src" / "hidloom-m3-router.c")
    matrixd_package = read(EXTERNAL / "package" / "hidloom-matrixd" / "hidloom-matrixd.mk")
    m3_router_package = read(EXTERNAL / "package" / "hidloom-m3-router" / "hidloom-m3-router.mk")
    for package in (matrixd_package, m3_router_package):
        assert "_LICENSE = GPL-3.0-or-later" in package
        assert "_LICENSE_FILES = COPYING" in package
    assert (ROOT / "daemon" / "matrixd" / "COPYING").read_bytes() == (ROOT / "LICENSE").read_bytes()
    assert (
        EXTERNAL / "package" / "hidloom-m3-router" / "src" / "COPYING"
    ).read_bytes() == (ROOT / "LICENSE").read_bytes()
    license_sha256 = "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986"
    assert license_sha256 in read(EXTERNAL / "package" / "hidloom-matrixd" / "hidloom-matrixd.hash")
    assert license_sha256 in read(
        EXTERNAL / "package" / "hidloom-m3-router" / "hidloom-m3-router.hash"
    )
    assert 'marker("m3_router_ready")' in m3_router
    assert 'marker("m3_physical_press")' in m3_router
    assert 'report(hid, 0x04)' in m3_router
    assert "rootfs_overlay_m2" not in m3_defconfig

    m4_gadget = M4_OVERLAY / "usr" / "bin" / "hidloom-hid-gadget-m4"
    m4_init = M4_OVERLAY / "etc" / "init.d" / "S20hidloom-hid-gadget"
    for path in [m4_gadget, m4_init]:
        assert_executable(path)
        assert read(path).startswith("#!/bin/sh"), path
    m4_gadget_text = read(m4_gadget)
    assert "printf '9\\n' > report_length" in m4_gadget_text
    assert "\\x85\\x01" in m4_gadget_text
    assert "functions/hid.usb1" in m4_gadget_text
    assert "printf '32\\n' > report_length" in m4_gadget_text
    assert "functions/hid.usb2" in m4_gadget_text
    assert "printf '8\\n' > report_length" in m4_gadget_text
    assert "ln -s functions/hid.usb2 configs/c.1/" in m4_gadget_text

    m6_defconfig = read(EXTERNAL / "configs" / "hidloom_m6_defconfig")
    assert "rootfs_overlay_m6" in m6_defconfig
    assert "post-build-m6.sh" in m6_defconfig
    assert "users_m6.txt" in m6_defconfig
    assert "BR2_PACKAGE_PYTHON3_XZ=y" in m6_defconfig
    assert "BR2_PACKAGE_SUDO=y" in m6_defconfig
    assert "BR2_PACKAGE_PYTHON_LUMA_OLED=y" in m6_defconfig
    assert "BR2_PACKAGE_HIDLOOM_M3_ROUTER" not in m6_defconfig
    m6_firmware_config = read(BOARD / "config_zero2w_m6.txt")
    assert "dtparam=i2c_arm=on" in m6_firmware_config
    assert "dtparam=i2c_arm=on" not in firmware_config
    assert "config_zero2w_m6.txt" in m6_defconfig
    assert "cmdline_m6.txt" in m6_defconfig
    assert "linux-m6-fastboot.fragment" in m6_defconfig
    assert "$5$hidloomm6$E544iRmfDdnA5yk7y2r97myRckfbFeUmbai8M3Mx.K." in read(
        BOARD / "users_m6.txt"
    )

    m6_cmdline = read(BOARD / "cmdline_m6.txt")
    assert "console=tty1" in m6_cmdline
    assert "console=ttyAMA" not in m6_cmdline
    assert "root=/dev/mmcblk0p2" in m6_cmdline
    assert "rootfstype=ext4" in m6_cmdline
    assert "logo.nologo" in m6_cmdline
    assert "quiet" in m6_cmdline
    assert "modules-load=dwc2,libcomposite" in m6_cmdline
    for setting in [
        "boot_delay=0",
        "disable_splash=1",
        "enable_uart=0",
        "hdmi_force_hotplug=1",
        "hdmi_ignore_edid=0xa5000080",
        "hdmi_group=2",
        "hdmi_mode=82",
        "framebuffer_width=1920",
        "framebuffer_height=1080",
    ]:
        assert setting in m6_firmware_config
    m6_kernel_fragment = read(BOARD / "linux-m6-fastboot.fragment")
    for disabled in [
        "CONFIG_BLK_DEV_INITRD",
        "CONFIG_USB_STORAGE",
        "CONFIG_LOGO",
        "CONFIG_SERIAL_8250_CONSOLE",
        "CONFIG_SERIAL_AMBA_PL011_CONSOLE",
    ]:
        assert f"# {disabled} is not set" in m6_kernel_fragment

    m6_services = {
        "S19viald": "VIALD_LAYER_COUNT=3",
        "S21hidloom-hidd": "HIDD_RAW_HID_BRIDGE_ENABLED=1",
        "S22hidloom-outputd": "OUTPUTD_TARGET=usb",
        "S23hidloom-uidd": "UIDD_UINPUT_PATH=/dev/uinput",
        "S25hidloom-logicd-core": "LOGICD_CORE_OUTPUT_ENABLED=1",
        "S26logicd-companion": "LOGICD_NATIVE_OUTPUTD_CTRL=1",
        "S27hidloom-i2c-modules": "modprobe i2c-dev",
        "S31i2cd": "-m i2cd.i2cd",
        "S32ledd": "-m ledd.ledd",
    }
    for name, marker in m6_services.items():
        service = M6_OVERLAY / "etc" / "init.d" / name
        assert_executable(service)
        assert marker in read(service)
    sudoers = M6_OVERLAY / "etc" / "sudoers.d" / "pi"
    assert "%wheel ALL=(ALL:ALL) ALL" in read(sudoers)

    post_build = BOARD / "post-build-m6.sh"
    m6_build = ROOT / "tools" / "buildroot_m6_build.sh"
    m6_verify = ROOT / "tools" / "buildroot_m6_verify.py"
    m6_import_smoke = ROOT / "tools" / "buildroot_m6_import_smoke.py"
    m6_runtime_smoke = ROOT / "tools" / "buildroot_m6_runtime_smoke.py"
    for path in [post_build, m6_build, m6_verify, m6_import_smoke, m6_runtime_smoke]:
        assert_executable(path)
    post_build_text = read(post_build)
    for binary in ["hidloom-hidd", "hidloom-logicd-core", "hidloom-outputd", "hidloom-uidd"]:
        assert binary in post_build_text
    assert "daemon/http" not in post_build_text
    assert "daemon/btd" not in post_build_text
    assert 'chmod 0440 "$TARGET_DIR/etc/sudoers.d/pi"' in post_build_text
    assert '"$ROOT/hidloom_paths.py"' in post_build_text
    assert "logicd viald i2cd ledd usbd" in post_build_text
    assert 'rm -f "$TARGET_DIR/etc/init.d/S25hidloom-m3-router"' in post_build_text
    native_build = read(ROOT / "tools" / "buildroot_m4_native_build.sh")
    assert "hidloom_uidd" in native_build
    assert "cargo build --locked" in native_build
    m6_build_text = read(m6_build)
    assert "buildroot_m6_verify.py" in m6_build_text
    assert "buildroot_legal_info.py" in m6_build_text
    assert "summarize_buildroot_legal_info.py" in read(ROOT / "tools" / "buildroot_legal_info.py")
    assert "buildroot_m6_import_smoke.py" in m6_build_text
    assert "buildroot_m6_runtime_smoke.py" in m6_build_text
    assert "--legal-info" in m6_build_text
    assert "EXPECTED_RELEASE_SHA256" in read(m6_verify)
    assert "microsd-uart-off-hdmi-1080p" in read(m6_verify)
    assert "hidloom_paths.py" in read(m6_verify)
    import_smoke_text = read(m6_import_smoke)
    for module in ["hidloom_paths", "luma.core", "luma.oled", "viald.viald", "logicd.logicd", "logicd.config_runtime", "usbd.hid_report_broker", "i2cd.i2cd", "ledd.ledd"]:
        assert f'"{module}"' in import_smoke_text
    runtime_smoke_text = read(m6_runtime_smoke)
    assert "KC_RO" in runtime_smoke_text
    assert "KC_A" in runtime_smoke_text
    assert "logicd companion remained active" in runtime_smoke_text

    luma_core = read(EXTERNAL / "package" / "python-luma-core" / "python-luma-core.mk")
    luma_oled = read(EXTERNAL / "package" / "python-luma-oled" / "python-luma-oled.mk")
    assert "PYTHON_LUMA_CORE_VERSION = 2.5.3" in luma_core
    assert "PYTHON_LUMA_OLED_VERSION = 3.15.0" in luma_oled
    assert "PYTHON_LUMA_CORE_LICENSE = MIT" in luma_core
    assert "PYTHON_LUMA_OLED_LICENSE = MIT" in luma_oled
    assert "select BR2_PACKAGE_PYTHON_LUMA_CORE" in read(
        EXTERNAL / "package" / "python-luma-oled" / "Config.in"
    )

    plan = read(ROOT / "docs" / "ops" / "buildroot-fast-boot-experiment.md")
    assert "hidloom_m1_defconfig" in plan
    assert "build/buildroot/hidloom-external" in plan
    assert "hidloom-hid-gadget-m1" in plan
    assert "hidloom-hid-key-tap-m1" in plan

    build_readme = read(ROOT / "build" / "README.md")
    assert "[`buildroot/`](buildroot/README.md)" in build_readme

    print("ok: Buildroot fast boot M1 assets are coherent")


if __name__ == "__main__":
    main()
