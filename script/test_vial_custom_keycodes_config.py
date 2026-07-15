#!/usr/bin/env python3
"""Check config/default/vial.json customKeycodes match the shared Vial custom action order."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.shared_action_defs import shared_vial_custom_actions  # noqa: E402


def main() -> None:
    vial = json.loads((ROOT / "config" / "default" / "vial.json").read_text(encoding="utf-8"))
    names = [entry["name"] for entry in vial.get("customKeycodes", [])]
    expected = list(shared_vial_custom_actions())
    assert names == expected, "config/default/vial.json customKeycodes must match shared_vial_custom_actions() order"
    assert len(names) <= 64, "Vial GUI resolves USER00..USER63; do not emit USER64 or higher"
    print("ok: Vial customKeycodes config matches shared custom action order")


if __name__ == "__main__":
    main()
