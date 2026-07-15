#!/usr/bin/env python3
"""Detect or remove disposable debris without touching build or operator state."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import fnmatch
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
PRESERVED_ROOT_NAMES = {
    ".agents",
    ".codex",
    ".git",
    ".venv",
    "ENV",
    "bin",
    "build",
    "env",
    "venv",
}
PRESERVED_DIRECTORY_NAMES = {".build", ".venv", "ENV", "env", "node_modules", "target", "venv"}
PRESERVED_PREFIXES = {
    ("codex_tasks", "done"),
    ("codex_tasks", "failed"),
    ("codex_tasks", "inbox"),
    ("codex_tasks", "running"),
    ("demo", "assets"),
    ("windows-driver", "package"),
}
DISPOSABLE_DIRECTORY_NAMES = {
    ".hypothesis",
    ".ipynb_checkpoints",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "__pycache__",
    "htmlcov",
    "site",
}
DISPOSABLE_FILE_GLOBS = (
    ".DS_Store",
    ".DS_Store?",
    ".coverage",
    ".coverage.*",
    "._*",
    "*.pyc",
    "*.pyo",
    "*.swo",
    "*.swp",
    "*.temp",
    "*.tmp",
    "*~",
    "Thumbs.db",
    "desktop.ini",
    "ehthumbs.db",
)
REVIEW_FILE_GLOBS = (
    "*.bak",
    "*.bak[0-9]*",
    "*.backup",
    "*.log",
    "*.orig",
    "*.rej",
)
PROTECTED_RELATIVE_FILES = {
    ".env",
    "conf/http_basic_auth.local.json",
    "config/default/http_basic_auth.local.json",
}


@dataclass(frozen=True, order=True)
class Finding:
    kind: str
    path: str
    removable: bool = False


def matches_any(name: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def git_inventory(root: Path) -> set[str]:
    try:
        top_level = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return set()
    if Path(top_level).resolve() != root:
        return set()
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
    )
    return {
        raw.decode("utf-8")
        for raw in result.stdout.split(b"\0")
        if raw
    }


def manifest_inventory(root: Path) -> set[str]:
    manifest = root / "PUBLIC_EXPORT_MANIFEST.json"
    if not manifest.is_file():
        return set()
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return set()
    files = payload.get("files", [])
    paths = {
        str(item["path"])
        for item in files
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    paths.add("PUBLIC_EXPORT_MANIFEST.json")
    return paths


def tracked_inventory(root: Path) -> set[str]:
    return git_inventory(root) or manifest_inventory(root)


def is_preserved_directory(relative: PurePosixPath) -> bool:
    parts = relative.parts
    if len(parts) == 1 and parts[0] in PRESERVED_ROOT_NAMES:
        return True
    if parts[-1] in PRESERVED_DIRECTORY_NAMES:
        return True
    return any(parts[: len(prefix)] == prefix for prefix in PRESERVED_PREFIXES)


def has_tracked_content(relative: str, tracked: set[str]) -> bool:
    prefix = relative + "/"
    return relative in tracked or any(path.startswith(prefix) for path in tracked)


def file_kind(relative: str, name: str) -> tuple[str, bool] | None:
    if relative in PROTECTED_RELATIVE_FILES or name == ".env.example":
        return None
    if name == ".env" or name.startswith(".env."):
        return "review_environment_file", False
    if matches_any(name, DISPOSABLE_FILE_GLOBS):
        return "disposable_workspace_file", True
    if matches_any(name, REVIEW_FILE_GLOBS):
        return "review_workspace_file", False
    return None


def scan(root: Path) -> list[Finding]:
    tracked = tracked_inventory(root)
    findings: list[Finding] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda item: item.name)
        except OSError:
            relative = directory.relative_to(root).as_posix() if directory != root else "."
            findings.append(Finding("unreadable_workspace_directory", relative))
            continue
        for entry in entries:
            path = Path(entry.path)
            relative_path = PurePosixPath(path.relative_to(root).as_posix())
            relative = relative_path.as_posix()
            try:
                is_symlink = entry.is_symlink()
                is_directory = entry.is_dir(follow_symlinks=False)
                is_file = entry.is_file(follow_symlinks=False)
            except OSError:
                findings.append(Finding("unreadable_workspace_path", relative))
                continue

            if is_symlink:
                matched = (
                    entry.name in DISPOSABLE_DIRECTORY_NAMES
                    or file_kind(relative, entry.name) is not None
                )
                if matched:
                    findings.append(Finding("review_workspace_symlink", relative))
                continue

            if is_directory:
                if is_preserved_directory(relative_path):
                    continue
                if entry.name in DISPOSABLE_DIRECTORY_NAMES:
                    if has_tracked_content(relative, tracked):
                        findings.append(Finding("tracked_workspace_debris", relative))
                    else:
                        findings.append(
                            Finding("disposable_workspace_directory", relative, True)
                        )
                    continue
                pending.append(path)
                continue

            kind = file_kind(relative, entry.name)
            if kind is None:
                continue
            finding_kind, removable = kind
            if not is_file:
                findings.append(Finding("review_workspace_special_file", relative))
            elif relative in tracked:
                findings.append(Finding("tracked_workspace_debris", relative))
            else:
                findings.append(Finding(finding_kind, relative, removable))
    return sorted(findings)


def clean(root: Path, findings: list[Finding]) -> list[str]:
    removed: list[str] = []
    for finding in sorted(findings, key=lambda item: item.path.count("/"), reverse=True):
        if not finding.removable:
            continue
        path = root / PurePosixPath(finding.path)
        try:
            if path.is_symlink():
                continue
            if finding.kind == "disposable_workspace_directory" and path.is_dir():
                shutil.rmtree(path)
            elif finding.kind == "disposable_workspace_file" and path.is_file():
                path.unlink()
            else:
                continue
        except OSError:
            continue
        removed.append(finding.path)
    return sorted(removed)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    findings = scan(root)
    if args.clean and findings:
        for path in clean(root, findings):
            print(f"removed: {path}")
        findings = scan(root)

    if findings:
        for finding in findings:
            print(f"{finding.kind}: {finding.path}", file=sys.stderr)
        removable = sum(finding.removable for finding in findings)
        print(
            f"workspace debris hygiene failed: {len(findings)} finding(s), "
            f"{removable} safely removable",
            file=sys.stderr,
        )
        if removable:
            print("run again with --clean to remove only disposable cache state", file=sys.stderr)
        if removable != len(findings):
            print("review non-removable findings manually; no file content was read", file=sys.stderr)
        raise SystemExit(1)
    print("ok: workspace debris hygiene (build, dependency, and operator state preserved)")


if __name__ == "__main__":
    main()
