#!/usr/bin/env python3
"""Require tracked lockfiles and locked Rust build commands."""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "PUBLIC_EXPORT_MANIFEST.json"
BUILD_PREFIXES = (".github/", "build/", "script/", "system/", "tools/")
BUILD_SUFFIXES = {".py", ".sh", ".yml", ".yaml"}
CARGO_COMMAND_RE = re.compile(
    r'(?:\bcargo\b|\$\(CARGO\)|"\$CARGO")\s+(?:build|test|fetch|check|clippy)\b',
    re.IGNORECASE,
)


def tracked_paths() -> set[str]:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        capture_output=True,
    )
    if result.returncode == 0:
        return {
            item.decode(errors="surrogateescape")
            for item in result.stdout.split(b"\0")
            if item
        }
    manifest = json.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
    paths = {str(item["path"]) for item in manifest["files"]}
    paths.add(MANIFEST)
    return paths


def main() -> None:
    tracked = tracked_paths()
    manifests = sorted(path for path in tracked if re.fullmatch(r"tools/[^/]+/Cargo\.toml", path))
    assert manifests, "no executable Rust crates found"

    for relative in manifests:
        manifest_path = ROOT / relative
        lock_relative = PurePosixPath(relative).with_name("Cargo.lock").as_posix()
        lock_path = ROOT / lock_relative
        assert lock_relative in tracked, f"untracked Cargo.lock: {lock_relative}"
        assert lock_path.is_file(), f"missing Cargo.lock: {lock_relative}"
        manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
        package = manifest["package"]
        assert any(
            item.get("name") == package["name"] and item.get("version") == package["version"]
            for item in lock.get("package", [])
        ), f"root package missing from {lock_relative}"

    ignored = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-ci", "--exclude-standard", "-z"],
        capture_output=True,
    )
    if ignored.returncode == 0:
        assert ignored.stdout == b"", "tracked files are hidden by .gitignore"

    unlocked: list[str] = []
    for relative in sorted(tracked):
        path = PurePosixPath(relative)
        if not relative.startswith(BUILD_PREFIXES):
            continue
        if path.name != "Makefile" and path.suffix not in BUILD_SUFFIXES:
            continue
        source = ROOT / relative
        if not source.is_file():
            continue
        for line_number, line in enumerate(
            source.read_text(encoding="utf-8", errors="replace").splitlines(),
            start=1,
        ):
            if CARGO_COMMAND_RE.search(line) and "--locked" not in line:
                unlocked.append(f"{relative}:{line_number}: {line.strip()}")
    assert not unlocked, "unlocked Cargo commands:\n" + "\n".join(unlocked)

    print(f"ok: Rust lockfile policy ({len(manifests)} executable crates, locked build surfaces)")


if __name__ == "__main__":
    main()
