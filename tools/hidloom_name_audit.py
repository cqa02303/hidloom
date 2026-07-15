#!/usr/bin/env python3
"""Reject retired software identifiers from active HIDloom sources."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PREFIXES = (
    "PUBLIC_",
    "docs/archive/",
    "kicad/",
    "windows-driver/",
    "codex_tasks/done/",
)
EXCLUDED_PATHS = {
    "config/publication-policy.json",
}
RETIRED_PREFIX = "c" + "qa"
RETIRED_OWNER = RETIRED_PREFIX + "02303"
FORBIDDEN = (
    re.compile(r"\b" + RETIRED_PREFIX + r"\b", re.IGNORECASE),
    re.compile(RETIRED_OWNER + "v5rpi", re.IGNORECASE),
    re.compile(RETIRED_PREFIX + r"[-_]", re.IGNORECASE),
    re.compile(RETIRED_PREFIX + "_paths", re.IGNORECASE),
    re.compile(r"/(?:run|usr/lib|usr/share|var/lib|var/backups|opt)/" + "cqa02303v5", re.IGNORECASE),
    re.compile(r"\.config/" + "cqa02303v5", re.IGNORECASE),
    re.compile("cqa02303v5" + r"-(?!\d{2}(?:\b|-))", re.IGNORECASE),
    re.compile("cqa02303v5" + r"\.(?:release-bundle|remap)\.", re.IGNORECASE),
    re.compile(r"RuntimeDirectory=" + "cqa02303v5", re.IGNORECASE),
    re.compile(RETIRED_OWNER + r"(?!v5|/)", re.IGNORECASE),
    re.compile(r"/(?:com|org)/" + RETIRED_OWNER + r"(?:/|$)", re.IGNORECASE),
)
HARDWARE_DEVICE_TEMPLATE = "cqa02303v5" + "-$(DEVICE)"


def tracked_paths(root: Path) -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=root
    )
    return [root / item.decode() for item in output.split(b"\0") if item]


def audit(root: Path) -> list[str]:
    violations: list[str] = []
    for path in tracked_paths(root):
        relative = path.relative_to(root).as_posix()
        if (
            relative in EXCLUDED_PATHS
            or relative.startswith(EXCLUDED_PREFIXES)
            or not path.is_file()
        ):
            continue
        if any(pattern.search(relative) for pattern in FORBIDDEN):
            violations.append(f"path:{relative}")
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            if "kicad" in line.lower() and RETIRED_OWNER + "v5rpi" in line.lower():
                continue
            if HARDWARE_DEVICE_TEMPLATE in line:
                continue
            if any(pattern.search(line) for pattern in FORBIDDEN):
                violations.append(f"content:{relative}:{line_number}:{line.strip()}")
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    violations = audit(args.root.resolve())
    if violations:
        print("HIDloom retired-name audit failed:")
        for violation in violations:
            print(f"- {violation}")
        return 1
    print("ok: active HIDloom sources contain no retired software identifiers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
