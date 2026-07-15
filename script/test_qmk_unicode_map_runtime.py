#!/usr/bin/env python3
"""Smoke tests for QMK Unicode map groundwork helpers."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.qmk_unicode import (  # noqa: E402
    QMK_UNICODE_ACTION_SCHEMA,
    QMK_UNICODE_MAP_SCHEMA,
    build_qmk_unicode_action_plan,
    normalize_qmk_unicode_codepoint,
    qmk_unicode_mode_gate,
    validate_qmk_unicode_map,
)


def _ready_settings() -> dict:
    return {
        "unicode": {
            "mode": "windows_ime_hex_f5",
            "host_profile": "win11-ime",
            "map": {
                "kana_a": "U+3042",
                "face": "1F600",
            },
        },
    }


def main() -> None:
    assert normalize_qmk_unicode_codepoint("3042") == "3042"
    assert normalize_qmk_unicode_codepoint("U+1f600") == "01F600"
    assert normalize_qmk_unicode_codepoint(0x41) == "0041"
    assert normalize_qmk_unicode_codepoint("D800") is None
    assert normalize_qmk_unicode_codepoint("110000") is None

    invalid_map = validate_qmk_unicode_map({
        "unicode_map": {
            "kana_a": "3042",
            "bad/name": "0041",
            "surrogate": "D800",
        }
    })
    assert invalid_map["schema"] == QMK_UNICODE_MAP_SCHEMA
    assert invalid_map["read_only"] is True
    assert invalid_map["entry_count"] == 3
    assert invalid_map["valid"] is False
    assert "invalid_name" in invalid_map["errors"]
    assert "invalid_codepoint" in invalid_map["errors"]

    gate = qmk_unicode_mode_gate({})
    assert gate["ready_for_preview"] is False
    assert gate["auto_mode_switching"] is False
    assert gate["persistent_mode_mutation"] is False
    assert "unicode_mode_none" in gate["blocking_reasons"]
    assert "explicit_host_profile_required" in gate["blocking_reasons"]

    direct = build_qmk_unicode_action_plan("UC(3042)", _ready_settings())
    assert direct["schema"] == QMK_UNICODE_ACTION_SCHEMA
    assert direct["read_only"] is True
    assert direct["sends_hid_reports"] is False
    assert direct["family"] == "uc"
    assert direct["normalized"] == "UC(3042)"
    assert direct["preview_available"] is True
    assert direct["blocking_reasons"] == []
    assert [tap["key"] for tap in direct["tap_previews"][0]["sequences"][0]["taps"]] == [
        "KC_3",
        "KC_0",
        "KC_4",
        "KC_2",
        "KC_F5",
        "KC_ENTER",
    ]

    mapped = build_qmk_unicode_action_plan("UM(kana_a)", _ready_settings())
    assert mapped["family"] == "um"
    assert mapped["codepoints"] == ["3042"]
    assert mapped["preview_available"] is True

    pair = build_qmk_unicode_action_plan("UP(kana_a,face)", _ready_settings())
    assert pair["family"] == "up"
    assert pair["codepoints"] == ["3042", "01F600"]
    assert len(pair["tap_previews"]) == 2

    missing = build_qmk_unicode_action_plan("UM(missing)", _ready_settings())
    assert missing["preview_available"] is False
    assert "unicode_map_entry_missing_or_invalid" in missing["blocking_reasons"]

    blocked = build_qmk_unicode_action_plan("UC(3042)", {"unicode": {"mode": "none"}})
    assert blocked["preview_available"] is False
    assert "unicode_mode_none" in blocked["blocking_reasons"]
    assert "explicit_host_profile_required" in blocked["blocking_reasons"]

    mode = build_qmk_unicode_action_plan("UC_LINX", _ready_settings())
    assert mode["family"] == "unicode_mode"
    assert mode["preview_available"] is False
    assert "unicode_mode_action_is_preview_only" in mode["blocking_reasons"]

    unsupported = build_qmk_unicode_action_plan("KC_A", _ready_settings())
    assert unsupported["family"] == "unsupported"
    assert "unsupported_qmk_unicode_action" in unsupported["blocking_reasons"]

    print("ok: QMK Unicode map groundwork helpers")


if __name__ == "__main__":
    main()
