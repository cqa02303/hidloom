#!/usr/bin/env python3
"""Small helper for script/test_* suite entrypoints."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]


def test_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    environment = dict(os.environ if source is None else source)
    environment.pop("CARGO_TARGET_DIR", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def rerun_in_clean_snapshot(root: Path, entrypoint: str, marker: str) -> None:
    if os.environ.get(marker) == "1":
        return
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    if untracked:
        paths = [os.fsdecode(item) for item in untracked.split(b"\0") if item]
        raise SystemExit(f"stage or remove untracked validation inputs: {paths}")
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    with tempfile.TemporaryDirectory(prefix="hidloom-validation-snapshot-") as temporary:
        snapshot = Path(temporary) / "repo"
        snapshot.mkdir()
        for encoded in tracked.split(b"\0"):
            if not encoded:
                continue
            relative = Path(os.fsdecode(encoded))
            source = root / relative
            destination = snapshot / relative
            if not source.exists() and not source.is_symlink():
                raise SystemExit(f"tracked validation input is missing: {relative}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_symlink():
                destination.symlink_to(os.readlink(source))
            else:
                shutil.copy2(source, destination)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=snapshot, check=True)
        subprocess.run(
            ["git", "config", "user.name", "HIDloom Validation"],
            cwd=snapshot,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "validation@example.invalid"],
            cwd=snapshot,
            check=True,
        )
        subprocess.run(["git", "add", "-f", "-A"], cwd=snapshot, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "Validation snapshot"], cwd=snapshot, check=True
        )
        environment = test_environment()
        environment[marker] = "1"
        completed = subprocess.run(
            [sys.executable, entrypoint],
            cwd=snapshot,
            env=environment,
        )
        raise SystemExit(completed.returncode)


def run_suite(name: str, tests: Iterable[str], *, stop_on_failure: bool = False) -> None:
    failed: list[str] = []
    environment = test_environment()
    for rel in tests:
        path = ROOT / rel
        print(f"== {rel}", flush=True)
        result = subprocess.run([sys.executable, str(path)], cwd=ROOT, env=environment)
        if result.returncode == 0:
            continue
        if stop_on_failure:
            result.check_returncode()
        failed.append(rel)

    if failed:
        print(f"FAILED {name}:")
        for rel in failed:
            print(f"- {rel}")
        raise SystemExit(1)
    print(f"ok: {name}")
