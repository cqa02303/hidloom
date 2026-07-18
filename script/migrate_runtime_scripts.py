#!/usr/bin/env python3
"""Migrate unchanged HIDloom runtime scripts without overwriting user edits."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS_DIR = ROOT / "config" / "default" / "script"
MANIFEST = ROOT / "config" / "default" / "script-migrations.json"
RUNTIME_DIR = Path(os.environ.get("HIDLOOM_RUNTIME_DIR", "/mnt/p3")) / "script"
SCHEMA = "hidloom.runtime-script-migrations.v1"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path) -> dict[str, set[str]]:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA:
        raise SystemExit(f"invalid runtime script migration schema: {path}")
    scripts = payload.get("scripts")
    if not isinstance(scripts, dict):
        raise SystemExit(f"runtime script migrations must be an object: {path}")
    result: dict[str, set[str]] = {}
    for name, spec in scripts.items():
        if not isinstance(name, str) or not name or Path(name).name != name:
            raise SystemExit(f"invalid runtime script name: {name!r}")
        if not isinstance(spec, dict) or not isinstance(spec.get("legacy_sha256"), list):
            raise SystemExit(f"invalid runtime script migration entry: {name}")
        hashes = set()
        for value in spec["legacy_sha256"]:
            digest = str(value).lower()
            if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
                raise SystemExit(f"invalid legacy sha256 for {name}: {value!r}")
            hashes.add(digest)
        result[name] = hashes
    return result


def next_backup_path(path: Path, timestamp: str) -> Path:
    candidate = path.with_name(f"{path.name}.bak.{timestamp}")
    counter = 1
    while candidate.exists() or candidate.is_symlink():
        candidate = path.with_name(f"{path.name}.bak.{timestamp}.{counter}")
        counter += 1
    return candidate


def install_default(source: Path, target: Path) -> None:
    temporary = target.with_name(f".{target.name}.migrate.{os.getpid()}")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def migrate_runtime_scripts(
    *,
    defaults_dir: Path,
    runtime_dir: Path,
    manifest_path: Path,
    dry_run: bool = False,
    backup: bool = True,
    timestamp: str | None = None,
) -> dict[str, str]:
    migrations = load_manifest(manifest_path)
    if not defaults_dir.is_dir():
        raise SystemExit(f"runtime script defaults directory not found: {defaults_dir}")
    for name in migrations:
        if not (defaults_dir / name).is_file():
            raise SystemExit(f"runtime script migration default not found: {defaults_dir / name}")

    selected_timestamp = timestamp or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    if not dry_run:
        runtime_dir.mkdir(parents=True, exist_ok=True)

    actions: dict[str, str] = {}
    for source in sorted(path for path in defaults_dir.iterdir() if path.is_file()):
        target = runtime_dir / source.name
        if target.is_symlink():
            actions[source.name] = "preserve-symlink"
            print(f"preserve-symlink {target}")
            continue
        if not target.exists():
            actions[source.name] = "seed"
            print(f"seed {source} -> {target}")
            if not dry_run:
                install_default(source, target)
            continue

        current_hash = file_sha256(target)
        default_hash = file_sha256(source)
        if current_hash == default_hash:
            actions[source.name] = "current"
            print(f"current {target}")
            continue
        if current_hash not in migrations.get(source.name, set()):
            actions[source.name] = "preserve-custom"
            print(f"preserve-custom {target} sha256={current_hash}")
            continue

        actions[source.name] = "migrate"
        if backup:
            backup_target = next_backup_path(target, selected_timestamp)
            print(f"backup {target} -> {backup_target}")
            if not dry_run:
                shutil.copy2(target, backup_target)
        print(f"migrate {source} -> {target}")
        if not dry_run:
            install_default(source, target)
    return actions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--defaults-dir", type=Path, default=DEFAULTS_DIR)
    parser.add_argument("--runtime-dir", type=Path, default=RUNTIME_DIR)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    parser.add_argument("--timestamp")
    args = parser.parse_args()
    actions = migrate_runtime_scripts(
        defaults_dir=args.defaults_dir,
        runtime_dir=args.runtime_dir,
        manifest_path=args.manifest,
        dry_run=args.dry_run,
        backup=not args.no_backup,
        timestamp=args.timestamp,
    )
    counts: dict[str, int] = {}
    for action in actions.values():
        counts[action] = counts.get(action, 0) + 1
    summary = " ".join(f"{key}={counts[key]}" for key in sorted(counts))
    print(f"runtime script migration complete: {summary}")


if __name__ == "__main__":
    main()
