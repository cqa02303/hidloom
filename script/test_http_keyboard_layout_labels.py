#!/usr/bin/env python3
"""Regression checks for explicit matrix labels in the HTTP keyboard layout."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _explicit_label_entries(path: Path) -> list[tuple[str, str]]:
    layout = json.loads(path.read_text(encoding="utf-8"))
    labels: list[tuple[str, str]] = []
    for row in layout:
        for item in row:
            if not isinstance(item, str):
                continue
            parts = item.splitlines()
            if not parts:
                continue
            head = parts[0].strip()
            if "," not in head:
                continue
            tail = parts[-1].strip() if parts else ""
            labels.append((tail, head))
    return labels


def main() -> None:
    expected = {
        "Esc": "7,0",
        "Btn2": "6,0",
        "Shutdown": "9,8",
        "Delete": "4,1",
        "Space": "5,4",
        "Enter": "4,5",
        "BS": "4,6",
        "↑": "4,9",
        "←": "4,8",
        "→": "5,9",
        "Alt": "5,2",
        "Win": "5,7",
        "↓": "5,8",
    }
    for path in (
        ROOT / "config" / "default" / "keyboard-layout.json",
        ROOT / "config" / "boards" / "ver1.0" / "conf" / "keyboard-layout.json",
    ):
        entries = _explicit_label_entries(path)
        labels = dict(entries)
        for label, matrix in expected.items():
            assert labels.get(label) == matrix, f"{path}: {label}: expected {matrix}, got {labels.get(label)}"
        assert ("Shift", "4,2") in entries
        assert ("Fn", "5,3") in entries
        assert ("Fn", "5,6") in entries
    for path in (
        ROOT / "config" / "default" / "vial.json",
        ROOT / "config" / "boards" / "ver1.0" / "conf" / "vial.json",
    ):
        keymap = json.loads(path.read_text(encoding="utf-8"))["layouts"]["keymap"]
        assert keymap[0][1] == "7,0", f"{path}: top-left Esc should be 7,0"
        assert keymap[4][-1] == "9,8", f"{path}: right edge shutdown should be 9,8"
        assert keymap[5] == [
            "4,0",
            {"x": 1.25},
            "4,1",
            {"x": 0.25, "w": 1.25},
            "4,2",
            "4,3",
            {"h": 2.0},
            "5,4",
            {"h": 2.0},
            "4,5",
            "4,6",
            {"w": 1.25},
            "4,7",
            {"x": 1.75},
            "4,9",
        ], f"{path}: Vial bottom row should match the HTTP physical layout"
        assert keymap[6] == [
            {"x": 10.75, "y": -0.5},
            "4,8",
            {"x": 1.0},
            "5,9",
        ], f"{path}: Vial arrow row should match the HTTP physical layout"
        assert keymap[-1][-1] == "6,0", f"{path}: bottom virtual Btn2 should be 6,0"
    print("ok: HTTP keyboard bottom labels have explicit matrix anchors")


if __name__ == "__main__":
    main()
