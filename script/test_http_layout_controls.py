#!/usr/bin/env python3
"""Regression test for HTTP layout control metadata."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon" / "http"))

from layout_controls import control_metadata_from_keymap  # noqa: E402


def main() -> None:
    keymap = json.loads((ROOT / "config" / "default" / "keymap.json").read_text(encoding="utf-8"))
    controls = control_metadata_from_keymap(keymap)

    assert controls["joystick_directions"] == {
        "0,0": "up",
        "1,1": "left",
        "2,2": "right",
        "3,3": "down",
    }
    assert controls["encoder_directions"] == {
        "6,1": "ccw",
        "7,1": "cw",
    }
    assert controls["encoder_actions"] == {
        "0": {
            "ccw": "6,1",
            "cw": "7,1",
        },
    }
    assert controls["encoder_click_keys"] == []

    print("ok: HTTP layout control metadata follows keymap definitions")


if __name__ == "__main__":
    main()
