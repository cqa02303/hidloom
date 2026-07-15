#!/usr/bin/env python3
"""Keep stale status snapshots out of the active documentation entrypoints."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    if not (ROOT / "docs" / "CURRENT_STATUS.md").is_file():
        print("ok: private documentation archive is not shipped in the public source tree")
        return

    archived = [
        ROOT / "docs" / "archive" / "CURRENT_STATUS_2026_05_19.md",
        ROOT / "docs" / "archive" / "CURRENT_STATUS_2026_06_08.md",
        ROOT / "docs" / "archive" / "TODO_PRIORITY_2026_05_23.md",
        ROOT / "docs" / "archive" / "VIAL_STATUS.md",
    ]
    for path in archived:
        assert path.exists(), path

    active_entrypoints = [
        ROOT / "README.md",
        ROOT / "docs" / "README.md",
        ROOT / "docs" / "architecture" / "system-overview.md",
        ROOT / "docs" / "CURRENT_STATUS.md",
        ROOT / "daemon" / "viald" / "README.md",
    ]
    stale_links = [
        "docs/VIAL_STATUS.md",
        "(VIAL_STATUS.md)",
        "docs/CURRENT_STATUS_2026_05_19.md",
        "(CURRENT_STATUS_2026_05_19.md)",
    ]
    for path in active_entrypoints:
        text = path.read_text(encoding="utf-8")
        for link in stale_links:
            assert link not in text, f"{path.relative_to(ROOT)} still points at active stale doc: {link}"

    archive_readme = (ROOT / "docs" / "archive" / "README.md").read_text(encoding="utf-8")
    assert "CURRENT_STATUS_2026_05_19.md" in archive_readme
    assert "CURRENT_STATUS_2026_06_08.md" in archive_readme
    assert "TODO_PRIORITY_2026_05_23.md" in archive_readme
    assert "VIAL_STATUS.md" in archive_readme
    assert "bugs/" in archive_readme
    assert "progress/" in archive_readme
    assert "review/" in archive_readme
    assert (ROOT / "docs" / "archive" / "bugs" / "README.md").exists()
    assert (ROOT / "docs" / "archive" / "progress" / "README.md").exists()
    assert (ROOT / "docs" / "archive" / "review" / "README.md").exists()
    assert not (ROOT / "docs" / "bugs").exists()
    assert not (ROOT / "docs" / "progress").exists()
    print("ok: archived docs are out of active entrypoints")


if __name__ == "__main__":
    main()
