#!/usr/bin/env python3
"""Regression checks for package-first fresh install and release guides."""
from __future__ import annotations

from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]

APT_PACKAGES = [
    "build-essential",
    "cargo",
    "fbterm",
    "fonts-dejavu-mono",
    "fonts-noto-cjk",
    "git",
    "i2c-tools",
    "jq",
    "python3-aiohttp",
    "python3-dbus-next",
    "python3-numpy",
    "python3-opencv",
    "python3-pil",
    "python3-pip",
    "rfkill",
    "rustc",
    "socat",
]


def main() -> None:
    setup_path = ROOT / "system/install/setup_fresh_rpi.sh"
    setup = setup_path.read_text(encoding="utf-8")
    wrapper = (ROOT / "setup_fresh_rpi.sh").read_text(encoding="utf-8")
    guide = (ROOT / "FRESH_INSTALL.md").read_text(encoding="utf-8")
    release = (ROOT / "RELEASE_CHECKLIST.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    syntax = subprocess.run(
        ["bash", "-n", str(setup_path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert syntax.returncode == 0, syntax.stderr
    help_result = subprocess.run(
        [str(ROOT / "setup_fresh_rpi.sh"), "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert help_result.returncode == 0, help_result.stderr
    assert "--prepare-only" in help_result.stdout
    assert "split Debian" in help_result.stdout

    assert "system/install/setup_fresh_rpi.sh" in wrapper
    assert 'PREPARE_ONLY=0' in setup
    assert '--prepare-only)' in setup
    assert 'if [[ "$PREPARE_ONLY" -eq 0 ]]; then' in setup
    assert "Skipping project build, runtime initialization, and unit installation" in setup
    assert "platform preparation only" in setup
    assert "build split Debian packages on the x86_64 host" in setup
    assert "configure_late_service_policy" in setup
    assert "logicd.service logicd-companion.service" in setup
    assert 'logic_status_units="hidloom-uidd hidloom-outputd hidloom-logicd-core matrixd logicd-companion"' in setup
    assert 'logic_status_units="logicd"' in setup
    assert "i2cd logicd matrixd ledd" not in setup

    for package in APT_PACKAGES:
        assert package in setup, package

    for option in (
        "--no-reboot",
        "--no-bluetooth",
        "--no-matrixd",
        "--no-peripherals",
        "--touch-panel-only",
        "--touch-panel-profile",
        "--board-version",
        "--prototype",
    ):
        assert option in setup, option

    for contract in (
        "dtoverlay=dwc2,dr_mode=peripheral",
        "dtparam=i2c_arm=on",
        "i2c-dev",
        "libcomposite",
        "uinput",
        "NetworkManager available for Wi-Fi recovery",
        "RuntimeWatchdogSec=off",
        "Storage=persistent",
        "HIDLOOM_LATE_BLUETOOTH",
        "BTD_BACKEND=bluez",
        "BTD_GATT_SECURITY=encrypt",
        "LOGICD_OUTPUTS=auto",
    ):
        assert contract in setup, contract

    for phrase in (
        "x86_64 build host",
        "--prepare-only",
        "make core-deb-package",
        "make keyboard-ver1-profile-deb",
        "hidloom-core",
        "hidloom-profile-keyboard-ver1",
        "同じ apt transaction",
        "hidloom-profile keyboard-ver1 --apply --backup --restart",
        "/usr/lib/hidloom",
        "/mnt/p3/device_profile.json",
        "systemctl --failed",
        "/dev/hidg0",
        "/dev/hidg1",
        "/dev/hidg2",
        "/dev/hidg4",
        "input-ready",
        "legacy/recovery",
    ):
        assert phrase in guide, phrase

    assert "sudo ./setup_fresh_rpi.sh --prepare-only" in readme
    assert "hidloom-profile keyboard-ver1 --apply --backup --restart" in readme
    assert "引数なしの checkout bootstrap" in readme
    assert "Raspberry Pi 実機では build" in readme
    assert "cd ~/hidloom/daemon/matrixd" not in readme

    for phrase in (
        "python3 script/test_validation_suite.py",
        "tools/package/release_candidate_check.sh --split-profile keyboard-ver1",
        "hidloom-logicd-core",
        "logicd-companion",
        "/run/hidloom/hidd-status.json",
        "/run/hidloom/logicd-core-status.json",
        "/run/hidloom/outputd-status.json",
        "spid.service` は PAW sensor 搭載前提ではない",
        "optional `/dev/hidg2`",
        "`/dev/hidg4` Windows IME",
        "hidloom-ctrl output auto",
        "make public-export-check",
        "make buildroot-compliance-verify",
        "--require-hardware-pass",
    ):
        assert phrase in release, phrase

    stale_patterns = (
        "http/httpd.py",
        "http/static/keyboard.js",
        "logicd/logicd.py",
        "logicd/macro.py",
        "/dev/hidg3",
        "admin` / `admin",
        "test_getkeymap.sh",
        "test_setkeycode.sh",
    )
    for name, text in {
        "FRESH_INSTALL.md": guide,
        "RELEASE_CHECKLIST.md": release,
        "README.md": readme,
    }.items():
        for stale in stale_patterns:
            assert stale not in text, f"{name}: {stale}"
        assert "/home/" + "pi/" not in text, name
        assert "/home/" + "operator/" not in text, name
        assert not re.search(r"192\.168\.\d{1,3}\.\d{1,3}", text), name

    current_operational_docs = {
        "daemon/logicd/README.md": (ROOT / "daemon/logicd/README.md").read_text(encoding="utf-8"),
        "daemon/matrixd/README.md": (ROOT / "daemon/matrixd/README.md").read_text(encoding="utf-8"),
        "docs/bluetooth/implementation-plan.md": (
            ROOT / "docs/bluetooth/implementation-plan.md"
        ).read_text(encoding="utf-8"),
        "docs/ops/performance-tuning-plan.md": (
            ROOT / "docs/ops/performance-tuning-plan.md"
        ).read_text(encoding="utf-8"),
        "docs/policy/logging-status-policy.md": (
            ROOT / "docs/policy/logging-status-policy.md"
        ).read_text(encoding="utf-8"),
        "docs/daemon/specs/matrixd/real-device-stability-checklist.md": (
            ROOT / "docs/daemon/specs/matrixd/real-device-stability-checklist.md"
        ).read_text(encoding="utf-8"),
        "docs/ops/pty-terminal-mirror-smoke.md": (
            ROOT / "docs/ops/pty-terminal-mirror-smoke.md"
        ).read_text(encoding="utf-8"),
        "docs/ops/windows-ime-custom-hid-real-device-runbook.md": (
            ROOT / "docs/ops/windows-ime-custom-hid-real-device-runbook.md"
        ).read_text(encoding="utf-8"),
        "daemon/i2cd/README.md": (ROOT / "daemon/i2cd/README.md").read_text(encoding="utf-8"),
    }
    stale_logicd_unit = re.compile(
        r"(?:systemctl|journalctl)[^\n]*(?<![-\w])logicd(?:\.service)?(?=\s|$)"
    )
    for name, text in current_operational_docs.items():
        assert "hidloom-logicd-core" in text, name
        assert "logicd-companion" in text, name
        assert not stale_logicd_unit.search(text), name
        assert "/home/" + "operator/" not in text, name

    windows_ime = current_operational_docs[
        "docs/ops/windows-ime-custom-hid-real-device-runbook.md"
    ]
    assert "/dev/hidg3" not in windows_ime
    pty_smoke = current_operational_docs["docs/ops/pty-terminal-mirror-smoke.md"]
    assert "/usr/lib/hidloom" in pty_smoke
    assert "journalctl -u logicd-companion" in pty_smoke

    standard_runtime_docs = {
        "daemon/http/README.md": ROOT / "daemon/http/README.md",
        "docs/interaction/ui-plan.md": ROOT / "docs/interaction/ui-plan.md",
        "docs/ops/hidloom-hidd-deep-test-plan.md": ROOT / "docs/ops/hidloom-hidd-deep-test-plan.md",
        "docs/ops/buildroot-fast-boot-experiment.md": ROOT / "docs/ops/buildroot-fast-boot-experiment.md",
    }
    if (ROOT / "docs/CURRENT_STATUS.md").is_file():
        standard_runtime_docs["docs/ops/real-device-next-start.md"] = (
            ROOT / "docs/ops/real-device-next-start.md"
        )
    for name, path in standard_runtime_docs.items():
        text = path.read_text(encoding="utf-8")
        assert not stale_logicd_unit.search(text), name

    send_policy = (ROOT / "tools/hidloom_send/POLICY.md").read_text(encoding="utf-8")
    assert "daemon/logicd/macro.py" in send_policy
    assert "`logicd/macro.py`" not in send_policy

    print("ok: package-first fresh install and release guides match current runtime")


if __name__ == "__main__":
    main()
