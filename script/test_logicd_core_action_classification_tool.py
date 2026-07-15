#!/usr/bin/env python3
"""Regression checks for logicd-core action owner classification."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import logicd_core_action_classification as classify  # noqa: E402


def main() -> None:
    assert classify.classify_action("KC_A", {"KC_A": 4}) == ("native", "keyboard")
    assert classify.classify_action("KC_LSFT", {"KC_LSFT": 225}) == ("native", "keyboard")
    assert classify.classify_action("MO(1)", {}) == ("native", "deterministic_layer")
    assert classify.classify_action("TG(1)", {}) == ("native", "deterministic_layer")
    assert classify.classify_action("KC_ZKHK", {}) == ("native", "jis_internal")
    assert classify.classify_action("LT(2,KC_A)", {"KC_A": 4}) == ("delegated", "timed_or_composite")
    assert classify.classify_action("MT(KC_LSFT,KC_A)", {"KC_A": 4}) == ("delegated", "timed_or_composite")
    assert classify.classify_action("TT(2)", {}) == ("delegated", "timed_or_composite")
    assert classify.classify_action("TD(TD0)", {}) == ("delegated", "timed_or_composite")
    assert classify.classify_action("KC_BTN1", {}) == ("delegated", "mouse")
    assert classify.classify_action("TEXT(kana_a)", {}) == ("delegated", "macro_text")

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        keymap = root / "keymap.json"
        keycodes = root / "keycodes.json"
        keymap.write_text(
            '{"layers":[{"0,0":"KC_A","0,1":"MO(1)","0,2":"LT(2,KC_A)",'
            '"0,3":"KC_BTN1","0,4":"TEXT(kana_a)","0,5":"KC_TRNS","0,6":"KC_NONE"}]}',
            encoding="utf-8",
        )
        keycodes.write_text('{"KC_A":{"hid":4}}', encoding="utf-8")
        summary = classify.classify_keymap(keymap, keycodes)

    assert summary["unsupported_actions"] == 0
    assert summary["by_owner"] == {"delegated": 3, "native": 2, "noop": 1, "transparent": 1}
    assert summary["delegated_reasons"] == {"macro_text": 1, "mouse": 1, "timed_or_composite": 1}

    default_summary = classify.classify_keymap(
        ROOT / "config/default/keymap.json",
        ROOT / "config/default/keycodes.json",
    )
    assert default_summary["unsupported_actions"] == 0
    assert default_summary["by_owner"].get("native", 0) > 0
    assert default_summary["delegated_reasons"].get("timed_or_composite", 0) > 0

    print("ok: logicd-core action classification helper")


if __name__ == "__main__":
    main()
