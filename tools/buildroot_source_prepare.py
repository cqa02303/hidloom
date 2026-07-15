#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "buildroot-source.json"
DEFAULT_DESTINATION = ROOT / "build" / "artifacts" / "buildroot-upstream"


def run(*args: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()


def load_config(path: Path) -> tuple[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "hidloom.buildroot-source.v1":
        raise SystemExit(f"unsupported Buildroot source config: {path}")
    repository = str(payload.get("repository", ""))
    commit = str(payload.get("commit", ""))
    if not repository or len(commit) != 40:
        raise SystemExit(f"invalid Buildroot source config: {path}")
    return repository, commit


def verify(destination: Path, repository: str, commit: str) -> None:
    if not (destination / ".git").is_dir():
        raise SystemExit(f"Buildroot checkout is missing: {destination}")
    actual = run("git", "rev-parse", "HEAD", cwd=destination)
    if actual != commit:
        raise SystemExit(f"Buildroot revision mismatch: expected {commit}, got {actual}")
    status = run("git", "status", "--porcelain", "--untracked-files=no", cwd=destination)
    if status:
        raise SystemExit(f"Buildroot checkout has tracked changes: {destination}")
    origin = run("git", "remote", "get-url", "origin", cwd=destination)
    if origin != repository:
        raise SystemExit(f"Buildroot origin mismatch: expected {repository}, got {origin}")


def clone(destination: Path, repository: str, commit: str) -> None:
    if destination.exists() and any(destination.iterdir()):
        raise SystemExit(f"refusing to replace non-empty Buildroot destination: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-q", str(destination)], check=True)
    subprocess.run(["git", "-C", str(destination), "remote", "add", "origin", repository], check=True)
    subprocess.run(
        ["git", "-C", str(destination), "fetch", "--depth", "1", "origin", commit],
        check=True,
    )
    subprocess.run(["git", "-C", str(destination), "checkout", "-q", "--detach", "FETCH_HEAD"], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare the pinned Buildroot source checkout")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    repository, commit = load_config(args.config.resolve())
    destination = args.destination.resolve()
    if not (destination / ".git").is_dir():
        if args.check_only:
            raise SystemExit(f"Buildroot checkout is missing: {destination}")
        clone(destination, repository, commit)
    verify(destination, repository, commit)
    print(f"ok: Buildroot {commit} at {destination}")


if __name__ == "__main__":
    main()
