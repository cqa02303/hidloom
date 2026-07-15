#!/usr/bin/env python3
"""Deploy this checkout to a fresh Raspberry Pi OS host and optionally run setup."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from fnmatch import fnmatch
import os
from pathlib import Path, PurePosixPath
import shlex
import stat
import subprocess
import tarfile
import tempfile
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT_ROOT = ROOT / "build" / "artifacts"
REMOTE_ARCHIVE = "/tmp/hidloom-remote-fresh-install.tar.gz"

EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "ENV",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
}

EXCLUDE_PREFIXES = (
    "build/artifacts/",
    "demo/assets/",
    "windows-driver/package/",
)

EXCLUDE_GLOBS = (
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.so",
    "*.mp4",
    "*.bak",
    "*.backup",
    ".DS_Store",
    "Thumbs.db",
)

EXCLUDE_PATHS = {
    ".env",
    "daemon/matrixd/matrixd",
}

LF_EXTENSIONS = {
    ".sh",
    ".service",
    ".socket",
    ".target",
    ".timer",
    ".path",
}


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


def safe_name(value: str) -> str:
    chars = [ch if ch.isalnum() or ch in (".", "-", "_") else "_" for ch in value]
    return "".join(chars).strip("._-") or "remote"


def posix_rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def should_exclude(rel: str, *, is_dir: bool = False) -> bool:
    parts = PurePosixPath(rel).parts
    if any(part in EXCLUDE_DIRS for part in parts):
        return True
    if rel in EXCLUDE_PATHS:
        return True
    if any(rel.startswith(prefix) for prefix in EXCLUDE_PREFIXES):
        return True
    name = PurePosixPath(rel).name
    if any(fnmatch(name, pattern) or fnmatch(rel, pattern) for pattern in EXCLUDE_GLOBS):
        return True
    if is_dir and (rel == "tmp" or rel.startswith(".tmp")):
        return True
    return False


def should_normalize_lf(rel: str, data: bytes) -> bool:
    suffix = PurePosixPath(rel).suffix
    if suffix in LF_EXTENSIONS:
        return True
    if data.startswith(b"#!"):
        return True
    if rel.startswith("build/buildroot/"):
        return True
    return False


def iter_archive_files() -> Iterable[Path]:
    for path in sorted(ROOT.rglob("*")):
        rel = posix_rel(path)
        if should_exclude(rel, is_dir=path.is_dir()):
            if path.is_dir():
                continue
            continue
        if path.is_file():
            yield path


def add_file(tar: tarfile.TarFile, path: Path) -> None:
    rel = posix_rel(path)
    info = tar.gettarinfo(str(path), arcname=rel)
    data = path.read_bytes()
    if should_normalize_lf(rel, data):
        data = data.replace(b"\r\n", b"\n")
        info.size = len(data)
    if data.startswith(b"#!"):
        info.mode |= stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    with tempfile.SpooledTemporaryFile() as fp:
        fp.write(data)
        fp.seek(0)
        tar.addfile(info, fp)


def create_archive(output_dir: Path, label: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"{label}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for path in iter_archive_files():
            add_file(tar, path)
    return archive


def run(command: list[str], *, timeout: float) -> CommandResult:
    proc = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    return CommandResult(command, proc.returncode, proc.stdout, proc.stderr)


def require_ok(result: CommandResult) -> None:
    if result.returncode == 0:
        return
    command_text = " ".join(shlex.quote(part) for part in result.command)
    raise SystemExit(
        f"command failed ({result.returncode}): {command_text}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def ssh_base(connect_timeout: int) -> list[str]:
    return ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={connect_timeout}"]


def scp_base(connect_timeout: int) -> list[str]:
    return ["scp", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={connect_timeout}"]


def remote_quote(path: str) -> str:
    return shlex.quote(path)


def deploy_archive(target: str, archive: Path, remote_dir: str, *, connect_timeout: int) -> None:
    require_ok(
        run(
            [*scp_base(connect_timeout), str(archive), f"{target}:{REMOTE_ARCHIVE}"],
            timeout=120.0,
        )
    )
    remote_script = (
        "set -eu; "
        f"mkdir -p {remote_quote(remote_dir)}; "
        f"tar -xzf {remote_quote(REMOTE_ARCHIVE)} -C {remote_quote(remote_dir)}; "
        f"chmod +x {remote_quote(remote_dir)}/setup_fresh_rpi.sh "
        f"{remote_quote(remote_dir)}/system/install/setup_fresh_rpi.sh || true; "
        f"rm -f {remote_quote(REMOTE_ARCHIVE)}"
    )
    require_ok(run([*ssh_base(connect_timeout), target, remote_script], timeout=180.0))


def run_setup(target: str, remote_dir: str, setup_args: list[str], *, connect_timeout: int, timeout: float) -> None:
    quoted_args = " ".join(shlex.quote(arg) for arg in setup_args)
    remote_script = f"cd {remote_quote(remote_dir)} && sudo ./setup_fresh_rpi.sh {quoted_args}"
    require_ok(run([*ssh_base(connect_timeout), target, remote_script], timeout=timeout))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="SSH target, for example pi@<keyboard-ip>")
    parser.add_argument("--remote-dir", default="hidloom", help="remote checkout directory")
    parser.add_argument("--label", help="artifact label")
    parser.add_argument("--output-dir", type=Path, help="local artifact directory")
    parser.add_argument("--connect-timeout", type=int, default=8)
    parser.add_argument("--deploy", action="store_true", help="copy this checkout to the remote host")
    parser.add_argument("--run-setup", action="store_true", help="run sudo ./setup_fresh_rpi.sh after deploy")
    parser.add_argument("--setup-arg", action="append", default=[], help="argument passed to setup_fresh_rpi.sh")
    parser.add_argument("--setup-timeout-sec", type=float, default=1800.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    label = safe_name(args.label or args.target)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or DEFAULT_ARTIFACT_ROOT / f"{label}-remote-fresh-install-{stamp}"
    archive = create_archive(output_dir, label)
    print(f"archive={archive}")
    print(f"remote_dir={args.remote_dir}")
    if not args.deploy and not args.run_setup:
        print("dry_run=1")
        print("next: add --deploy to copy the checkout, and --run-setup to run setup_fresh_rpi.sh")
        return
    if args.run_setup and not args.deploy:
        raise SystemExit("--run-setup requires --deploy so the remote checkout matches this archive")
    deploy_archive(args.target, archive, args.remote_dir, connect_timeout=args.connect_timeout)
    print("deploy=ok")
    if args.run_setup:
        run_setup(
            args.target,
            args.remote_dir,
            args.setup_arg,
            connect_timeout=args.connect_timeout,
            timeout=args.setup_timeout_sec,
        )
        print("setup=ok")


if __name__ == "__main__":
    main()
