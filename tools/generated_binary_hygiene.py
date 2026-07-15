#!/usr/bin/env python3
"""Detect or remove retired software binaries from generated output directories."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
RETIRED_BINARY_PREFIX = "c" + "qa-"


@dataclass(frozen=True, order=True)
class Finding:
    kind: str
    path: str


def output_directories(root: Path, extra_bin_dirs: list[Path]) -> list[Path]:
    directories = {root / "bin"}
    for pattern in (
        "build/rpi-rust/*/bin",
        "build/rpi-hidloom-send/*/bin",
        "build/rpi-usb-gadget-fast/*/bin",
    ):
        directories.update(root.glob(pattern))
    directories.update(path.resolve() for path in extra_bin_dirs)
    return sorted(directories)


def display_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def scan(root: Path, extra_bin_dirs: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for directory in output_directories(root, extra_bin_dirs):
        if directory.is_symlink() or not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if not path.name.casefold().startswith(RETIRED_BINARY_PREFIX):
                continue
            if path.is_symlink() or path.is_file():
                kind = "retired_generated_binary"
            elif path.is_dir():
                kind = "retired_generated_directory"
            else:
                kind = "retired_generated_special_file"
            findings.append(Finding(kind, display_path(root, path)))
    return findings


def clean(root: Path, extra_bin_dirs: list[Path], findings: list[Finding]) -> list[str]:
    removable = {
        finding.path
        for finding in findings
        if finding.kind == "retired_generated_binary"
    }
    removed: list[str] = []
    for directory in output_directories(root, extra_bin_dirs):
        if directory.is_symlink() or not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            relative = display_path(root, path)
            if relative not in removable:
                continue
            path.unlink()
            removed.append(relative)
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--extra-bin-dir", type=Path, action="append", default=[])
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    extra_bin_dirs = [path.resolve() for path in args.extra_bin_dir]
    findings = scan(root, extra_bin_dirs)
    if args.clean and findings:
        removed = clean(root, extra_bin_dirs, findings)
        for path in removed:
            print(f"removed: {path}")
        findings = scan(root, extra_bin_dirs)

    if findings:
        for finding in findings:
            print(f"{finding.kind}: {finding.path}", file=sys.stderr)
        print(
            f"generated binary hygiene failed: {len(findings)} finding(s)",
            file=sys.stderr,
        )
        print("run again with --clean to remove regular retired artifacts", file=sys.stderr)
        raise SystemExit(1)
    print("ok: generated binary outputs contain no retired software names")


if __name__ == "__main__":
    main()
