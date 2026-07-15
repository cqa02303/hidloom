#!/usr/bin/env python3
"""Regression checks for the cross-build host preflight helper."""
from __future__ import annotations

from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "tools" / "cross_build_host_check.sh"
SYNC_HELPER = ROOT / "tools" / "sync_rpi_checkout.sh"
BUILD_HELPER = ROOT / "tools" / "build_rpi_rust.sh"
MAKEFILE = ROOT / "Makefile"


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def main() -> None:
    assert HELPER.exists(), HELPER
    assert SYNC_HELPER.exists(), SYNC_HELPER
    assert BUILD_HELPER.exists(), BUILD_HELPER
    assert MAKEFILE.exists(), MAKEFILE

    syntax = run_command(["sh", "-n", str(HELPER)])
    assert syntax.returncode == 0, syntax.stderr
    sync_syntax = run_command(["sh", "-n", str(SYNC_HELPER)])
    assert sync_syntax.returncode == 0, sync_syntax.stderr
    build_syntax = run_command(["sh", "-n", str(BUILD_HELPER)])
    assert build_syntax.returncode == 0, build_syntax.stderr
    assert '"$CARGO" build --locked' in BUILD_HELPER.read_text(encoding="utf-8")

    help_result = run_command([str(HELPER), "--help"])
    assert help_result.returncode == 0
    assert "usage: tools/cross_build_host_check.sh" in help_result.stdout
    assert "--no-ssh" in help_result.stdout
    sync_help = run_command([str(SYNC_HELPER), "--help"])
    assert sync_help.returncode == 0
    assert "usage: tools/sync_rpi_checkout.sh" in sync_help.stdout
    assert "Fast-forward a Raspberry Pi checkout" in sync_help.stdout

    dry = run_command([str(HELPER), "--no-ssh"])
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert "ok: command cargo" in dry.stdout
    assert "ok: rust target aarch64-unknown-linux-musl is installed" in dry.stdout
    assert "checking SSH target" not in dry.stdout

    make_dry = run_command(
        [
            "make",
            "-n",
            "cross-build-host-check",
            "sync-02",
            "smoke-02",
            "boot-report",
            "boot-report-reboot",
        ]
    )
    assert make_dry.returncode == 0, make_dry.stderr
    assert "tools/cross_build_host_check.sh --target aarch64-unknown-linux-musl" in make_dry.stdout
    assert "tools/sync_rpi_checkout.sh --device 02" in make_dry.stdout
    assert "tools/deploy_rpi_rust.sh --device 02 --target aarch64-unknown-linux-musl --smoke" in make_dry.stdout
    assert "tools/remote_boot_baseline_collect.py pi@<keyboard-ip>" in make_dry.stdout
    assert "--label hidloom-02" in make_dry.stdout
    assert "--reboot-before-sample" in make_dry.stdout

    make_01 = run_command(["make", "-n", "DEVICE=01", "boot-report", "boot-report-reboot"])
    assert make_01.returncode == 0, make_01.stderr
    assert "tools/remote_boot_baseline_collect.py operator@<keyboard-ip>" in make_01.stdout
    assert "--label hidloom-01" in make_01.stdout

    make_override = run_command(
        [
            "make",
            "-n",
            "DEVICE=custom",
            "BOOT_REPORT_REMOTE=user@example.local",
            "BOOT_REPORT_LABEL=bench",
            "boot-report-reboot",
        ]
    )
    assert make_override.returncode == 0, make_override.stderr
    assert "tools/remote_boot_baseline_collect.py user@example.local" in make_override.stdout
    assert "--label bench" in make_override.stdout

    print("ok: cross-build host preflight helper")


if __name__ == "__main__":
    main()
