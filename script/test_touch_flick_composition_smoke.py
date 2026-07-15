#!/usr/bin/env python3
"""Regression checks for the touch flick composition coverage helper."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from touch_flick_composition_smoke import analyze_touch_flick_composition  # noqa: E402


def main() -> None:
    report = analyze_touch_flick_composition()
    rows = report["rows"]
    by_action = {row["action"]: row for row in rows if row.get("action")}

    assert report["schema"] == "touch_panel.flick.composition_smoke.v1"
    assert report["read_only"] is True
    assert report["total"] > 40
    assert report["text_total"] > 80
    assert report["available"] == 87
    assert report["not_applicable"] == 40
    assert report["blocked"] == 22
    assert by_action["TEXT(kana_a)"]["blocking_reasons"] == ["composition_mode_requires_unicode_action"]
    assert by_action["U+3042"]["tap_sequence"] == ["KC_A"]
    assert by_action["U+3041"]["tap_sequence"] == ["KC_L", "KC_A"]
    assert by_action["U+3001"]["tap_sequence"] == ["KC_COMM"]
    assert by_action["U+3002"]["tap_sequence"] == ["KC_DOT"]
    assert by_action["U+30FC"]["tap_sequence"] == ["KC_MINS"]
    assert by_action["U+FF11"]["tap_sequence"] == ["KC_1"]
    assert by_action["U+FF10"]["tap_sequence"] == ["KC_0"]
    assert by_action["U+FF01"]["tap_sequence"] == ["KC_EXLM"]
    assert by_action["U+FF1F"]["tap_sequence"] == ["KC_QUES"]
    assert by_action["U+FF0B"]["tap_sequence"] == ["KC_PLUS"]
    assert by_action["U+FF0F"]["tap_sequence"] == ["KC_SLSH"]
    assert by_action["U+002E"]["tap_sequence"] == ["KC_DOT"]
    assert report["blocked_reasons"] == {
        "composition_mode_requires_unicode_action": 1,
        "composition_policy_ime_specific_mark": 7,
        "composition_policy_jis_kana_dependent": 4,
        "composition_policy_non_ascii_symbol": 10,
    }
    assert report["blocked_policy_complete"] is True
    assert report["unclassified_blocked_reasons"] == []
    assert "named_text_and_send_string_actions_use_text_send_preflight" in report["blocking_reason_policy"]["composition_mode_requires_unicode_action"]
    assert "katakana_without_romaji_policy" in report["blocking_reason_policy"]["composition_policy_non_ascii_symbol"]
    assert "composition_mode_accepts_text_actions_only" not in report["blocked_reasons"]
    assert "romaji_sequence_not_defined" not in report["blocked_reasons"]

    print("ok: touch flick composition smoke helper summarizes read-only romaji coverage")


if __name__ == "__main__":
    main()
