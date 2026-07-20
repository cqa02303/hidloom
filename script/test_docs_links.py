#!/usr/bin/env python3
"""Check Markdown links between repository documents."""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)#\s][^)\s#]*)(?:#[^)]+)?\)")
EXCLUDED_DIRS = {
    ".git",
    ".tmp-vial-qmk",
    ".venv",
    ".pytest_cache",
    "node_modules",
    "__pycache__",
}


def _ignored_build_directories() -> set[str]:
    directories: set[str] = set()
    for raw in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines():
        value = raw.strip()
        if not value.startswith("build/") or not value.endswith("/"):
            continue
        parts = value.rstrip("/").split("/")
        if len(parts) == 2 and not any(character in parts[1] for character in "*?["):
            directories.add(parts[1])
    return directories


IGNORED_BUILD_DIRS = _ignored_build_directories()


def _repo_markdown_files() -> list[Path]:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        base = Path(dirpath)
        dirnames[:] = [
            name
            for name in dirnames
            if name not in EXCLUDED_DIRS
            and not name.startswith(".")
            and not name.startswith("__codex_tmp_")
            and not (base == ROOT / "build" and name in IGNORED_BUILD_DIRS)
        ]
        files.extend(base / name for name in filenames if name.endswith(".md"))
    return files


def _excluded_target(path: Path, target: str, exclude_globs: list[str]) -> bool:
    target_path = (path.parent / target).resolve()
    try:
        relative = target_path.relative_to(ROOT).as_posix()
    except ValueError:
        return False
    return any(fnmatch.fnmatch(relative, pattern) for pattern in exclude_globs)


def main() -> None:
    assert {"artifacts", "public-rebuild", "touch-panel-release"} <= IGNORED_BUILD_DIRS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--public-export-manifest",
        type=Path,
        help="ignore links to paths intentionally excluded from a public export",
    )
    args = parser.parse_args()
    exclude_globs: list[str] = []
    if args.public_export_manifest:
        manifest = json.loads(args.public_export_manifest.read_text(encoding="utf-8"))
        exclude_globs = manifest.get("exclude_globs", [])

    missing: list[str] = []

    for path in sorted(_repo_markdown_files()):
        if path.name.startswith("PUBLIC_EXPORT_REPORT."):
            continue
        text = path.read_text(encoding="utf-8")
        for match in LINK_RE.finditer(text):
            target = match.group(1)
            if "://" in target or target.startswith("mailto:"):
                continue
            target_path = (path.parent / target).resolve()
            if _excluded_target(path, target, exclude_globs):
                continue
            if not target_path.exists():
                rel = path.relative_to(ROOT).as_posix()
                missing.append(f"{rel}: missing {target}")

    assert not missing, "broken Markdown links:\n" + "\n".join(missing)
    scope = "public export" if args.public_export_manifest else "repository"
    print(f"ok: {scope} Markdown links resolve")


if __name__ == "__main__":
    main()
