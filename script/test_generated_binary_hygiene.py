#!/usr/bin/env python3
"""Regression tests for retired generated-binary cleanup and deploy isolation."""
from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/generated_binary_hygiene.py"
RETIRED_PREFIX = "c" + "qa-"


def run(*args: str, check: bool) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def touch_executable(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fixture\n", encoding="utf-8")
    path.chmod(0o755)


def write_command(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nset -eu\n" + content, encoding="utf-8")
    path.chmod(0o755)


def main() -> None:
    current = run("--root", str(ROOT), check=True)
    assert "no retired software names" in current.stdout

    with tempfile.TemporaryDirectory() as temporary:
        fixture = Path(temporary) / "repository"
        external = Path(temporary) / "external-bin"
        retired_paths = (
            fixture / "bin" / f"{RETIRED_PREFIX}key",
            fixture
            / "build/rpi-rust/aarch64-unknown-linux-musl/bin"
            / f"{RETIRED_PREFIX}hidd",
            fixture
            / "build/rpi-hidloom-send/aarch64-static/bin"
            / f"{RETIRED_PREFIX}notify",
            fixture
            / "build/rpi-usb-gadget-fast/aarch64-static/bin"
            / f"{RETIRED_PREFIX}usb-gadget-fast",
            external / f"{RETIRED_PREFIX}outputd",
        )
        for path in retired_paths:
            touch_executable(path)
        canonical = fixture / "bin/hidloom-key"
        unrelated = external / "operator-helper"
        touch_executable(canonical)
        touch_executable(unrelated)

        failed = run(
            "--root",
            str(fixture),
            "--extra-bin-dir",
            str(external),
            check=False,
        )
        assert failed.returncode == 1
        for path in retired_paths:
            assert path.name in failed.stderr

        cleaned = run(
            "--root",
            str(fixture),
            "--extra-bin-dir",
            str(external),
            "--clean",
            check=True,
        )
        assert cleaned.stdout.count("removed:") == len(retired_paths)
        assert all(not path.exists() for path in retired_paths)
        assert canonical.is_file()
        assert unrelated.is_file()
        assert not any(fixture.rglob("__pycache__"))

        retired_directory = fixture / "bin" / f"{RETIRED_PREFIX}directory"
        retired_directory.mkdir()
        refused = run("--root", str(fixture), "--clean", check=False)
        assert refused.returncode == 1
        assert "retired_generated_directory" in refused.stderr
        assert retired_directory.is_dir()

    wrappers = (
        "tools/build_rpi_rust.sh",
        "tools/deploy_rpi_rust.sh",
        "tools/hidloom_hidd/build.sh",
        "tools/hidloom_uidd/build.sh",
        "tools/hidloom_outputd/build.sh",
        "tools/hidloom_logicd_core/build.sh",
        "tools/hidloom_send/build.sh",
        "tools/hidloom_usb_gadget_fast/build.sh",
    )
    for relative in wrappers:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "generated_binary_hygiene.py" in text, relative
        assert "--clean" in text, relative

    deploy = (ROOT / "tools/deploy_rpi_rust.sh").read_text(encoding="utf-8")
    assert 'rsync -az --info=stats1 "$BIN_DIR"/' not in deploy
    assert 'set -- "$@" "$BIN_DIR/$bin"' in deploy
    assert 'rsync -az --info=stats1 -- "$@"' in deploy

    with tempfile.TemporaryDirectory() as temporary:
        fixture = Path(temporary)
        bin_dir = fixture / "rust-bin"
        command_dir = fixture / "commands"
        rsync_trace = fixture / "rsync-args.txt"
        ssh_trace = fixture / "ssh-args.txt"
        canonical_names = (
            "hidloom-hidd",
            "hidloom-uidd",
            "hidloom-outputd",
            "hidloom-logicd-core",
        )
        for name in canonical_names:
            touch_executable(bin_dir / name)
        retired = bin_dir / f"{RETIRED_PREFIX}hidd"
        unrelated = bin_dir / "operator-helper"
        touch_executable(retired)
        touch_executable(unrelated)
        write_command(
            command_dir / "rsync",
            'printf "%s\\n" "$@" >"$RSYNC_TRACE"\n',
        )
        write_command(
            command_dir / "ssh",
            'printf "%s\\n" "$*" >>"$SSH_TRACE"\n',
        )
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{command_dir}:{environment['PATH']}",
                "RSYNC_TRACE": str(rsync_trace),
                "SSH_TRACE": str(ssh_trace),
            }
        )
        deployed = subprocess.run(
            [
                str(ROOT / "tools/deploy_rpi_rust.sh"),
                "--no-build",
                "--host",
                "operator@keyboard",
                "--repo",
                "/srv/hidloom",
                "--bin-dir",
                str(bin_dir),
            ],
            capture_output=True,
            text=True,
            check=True,
            env=environment,
        )
        assert "deploy complete" in deployed.stdout
        assert not retired.exists()
        assert unrelated.exists()
        rsync_arguments = rsync_trace.read_text(encoding="utf-8").splitlines()
        assert rsync_arguments[:3] == ["-az", "--info=stats1", "--"]
        assert rsync_arguments[3:-1] == [str(bin_dir / name) for name in canonical_names]
        assert rsync_arguments[-1] == "operator@keyboard:/srv/hidloom/bin/"
        assert str(unrelated) not in rsync_arguments
        assert ssh_trace.is_file()

    print("ok: generated binary hygiene removes retired outputs and bounds deploy")


if __name__ == "__main__":
    main()
