#!/usr/bin/env python3
"""Generate Vial definition files for touch-panel virtual keyboards."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BASE_VIAL = ROOT / "config" / "default" / "vial.json"
PROFILE_DIRS = (
    ROOT / "config" / "default" / "touch-panel",
    ROOT / "config" / "default" / "touch-panel" / "osoyoo-4.3",
)
TOUCH_PANEL_UID = 4850729948911186022
_MATRIX_HEAD_RE = re.compile(r"^\s*(\d+)\s*,\s*(\d+)\s*$")


# Vial consumes a KLE-like layout list. Keep only geometry attributes that are
# needed for rendering and matrix placement. The KLE/Vial `a` attribute is a
# legend alignment hint, not a matrix mapping field; on the touch-panel Space
# bar it was observed to make the Vial client hide the large key. Use width /
# height / position for large keys and omit `a` unless a specific client-side
# rendering regression proves it is required.
def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _layout_keymap(layout: list[list[Any]]) -> list[list[Any]]:
    keymap: list[list[Any]] = []
    for row in layout:
        out_row: list[Any] = []
        for item in row:
            if isinstance(item, dict):
                out_row.append(item)
                continue
            head = str(item).splitlines()[0].strip()
            if not _MATRIX_HEAD_RE.match(head):
                raise ValueError(f"{head!r} is not a matrix coordinate label")
            out_row.append(str(item))
        keymap.append(out_row)
    return keymap


def _max_matrix(layout_keymap: list[list[Any]]) -> tuple[int, int]:
    max_row = 0
    max_col = 0
    for row in layout_keymap:
        for item in row:
            if not isinstance(item, str):
                continue
            match = _MATRIX_HEAD_RE.match(item)
            if not match:
                continue
            max_row = max(max_row, int(match.group(1)))
            max_col = max(max_col, int(match.group(2)))
    return max_row, max_col


def build_touch_vial(profile_dir: Path, base: dict[str, Any]) -> dict[str, Any]:
    layout = _load_json(profile_dir / "keyboard-layout.json")
    keymap = _layout_keymap(layout)
    max_row, max_col = _max_matrix(keymap)
    profile_name = "waveshare-8.8" if profile_dir.name == "touch-panel" else profile_dir.name
    return {
        "name": f"CQA02303v5-40 Touch Panel ({profile_name})",
        "version": 1,
        "uid": TOUCH_PANEL_UID,
        "lighting": base.get("lighting", "vialrgb"),
        "vial": {
            "unlockKeys": [[0, 0], [max_row, max_col]],
        },
        "matrix": {
            "rows": max(16, max_row + 1),
            "cols": max(16, max_col + 1),
        },
        "customKeycodes": base.get("customKeycodes", []),
        "layouts": {
            "keymap": keymap,
        },
    }


def main() -> None:
    base = _load_json(BASE_VIAL)
    for profile_dir in PROFILE_DIRS:
        vial = build_touch_vial(profile_dir, base)
        out_path = profile_dir / "vial.json"
        out_path.write_text(json.dumps(vial, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"generated {out_path}")


if __name__ == "__main__":
    main()
