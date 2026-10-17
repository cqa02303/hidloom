#!/usr/bin/env python3
"""Regression checks for the cross-build host preflight helper."""
from __future__ import annotations

from pathlib import Path
import os
import shlex
import subprocess
import tempfile

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


def active_sysroot_fixture() -> None:
    """An overridden/linked toolchain may live outside the default rustup home."""
    with tempfile.TemporaryDirectory(prefix="hidloom-rustup-check-") as directory:
        root = Path(directory)
        commands = root / "bin"
        commands.mkdir()
        sysroot = root / "selected toolchain"
        linker = sysroot / "lib/rustlib/x86_64-unknown-linux-gnu/bin/rust-lld"
        linker.parent.mkdir(parents=True)

        def executable(path: Path, content: str) -> None:
            path.write_text("#!/bin/sh\n" + content, encoding="utf-8")
            path.chmod(0o755)

        executable(linker, "exit 0\n")
        executable(commands / "rustc", "case \"$*\" in\n"
            "  -Vv) printf 'host: x86_64-unknown-linux-gnu\\n' ;;\n"
            f"  '--print sysroot') printf '%s\\n' {shlex.quote(str(sysroot))} ;;\n"
            "  *) exit 2 ;;\nesac\n")
        executable(commands / "rustup", "case \"$*\" in\n"
            f"  'show active-toolchain') printf '%s\\n' {shlex.quote('fixture-' + root.name)} ;;\n"
            "  'target list --installed') printf 'aarch64-unknown-linux-musl\\n' ;;\n"
            "  *) exit 2 ;;\nesac\n")
        for name in ("cargo", "rsync", "ssh"):
            executable(commands / name, "exit 0\n")
        env = dict(os.environ, PATH=str(commands) + os.pathsep + os.environ.get("PATH", ""),
                   RUSTUP_HOME=str(root / "isolated-rustup"), HIDLOOM_RPI_RUST_TARGET="aarch64-unknown-linux-musl")
        result = subprocess.run(["sh", str(HELPER), "--no-ssh"], cwd=ROOT,
                                env=env, capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stdout + result.stderr
        assert f"ok: rust-lld {linker}" in result.stdout
        # Keep the negative gate: a real missing linker must still fail.
        linker.unlink()
        missing = subprocess.run(["sh", str(HELPER), "--no-ssh"], cwd=ROOT,
                                 env=env, capture_output=True, text=True, check=False)
        assert missing.returncode != 0, missing.stdout + missing.stderr
        assert "missing: rust-lld under active rustup toolchain" in missing.stdout


def main() -> None:
    assert HELPER.exists(), HELPER
    assert SYNC_HELPER.exists(), SYNC_HELPER
    assert BUILD_HELPER.exists(), BUILD_HELPER
    assert MAKEFILE.exists(), MAKEFILE
    active_sysroot_fixture()

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
