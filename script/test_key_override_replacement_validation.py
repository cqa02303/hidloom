#!/usr/bin/env python3
"""Regression tests for Key Override replacement safety validation."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.interaction_config import validate_interaction_settings  # noqa: E402


def in_range(row: int, col: int) -> bool:
    return 0 <= row < 2 and 0 <= col < 4


def test_key_override_replacement_allows_key_like_actions() -> None:
    result = validate_interaction_settings(
        {
            "key_overrides": [
                {"trigger": "KC_LSFT", "key": "KC_1", "replacement": "KC_EXLM"},
                {"trigger": "KC_LCTL", "key": "KC_A", "replacement": "S(KC_1)"},
                {"trigger": "KC_LALT", "key": "KC_M", "replacement": "MORSE(nav.layer)"},
            ],
        },
        matrix_in_range=in_range,
    )
    assert result.warnings == []
    assert [entry["replacement"] for entry in result.settings["key_overrides"]] == [
        "KC_EXLM",
        "S(KC_1)",
        "MORSE(nav.layer)",
    ]


def test_key_override_replacement_rejects_stateful_and_control_actions() -> None:
    replacements = [
        "MO(1)",
        "TT(2)",
        "LT(1,KC_SPACE)",
        "KC_USB",
        "KC_BT",
        "KC_SHUTDOWN",
        "KC_SH0",
        "KC_SH10",
        "SCRIPT(report)",
        "BT_POWER_TOGGLE",
        "WIFI_POWER_OFF",
        "S(KC_USB)",
        "MT(KC_LSFT,MO(1))",
    ]
    result = validate_interaction_settings(
        {
            "key_overrides": [
                {"trigger": "KC_LSFT", "key": f"KC_{idx}", "replacement": replacement}
                for idx, replacement in enumerate(replacements, start=1)
            ],
        },
        matrix_in_range=in_range,
    )
    assert result.settings["key_overrides"] == []
    assert len(result.warnings) == len(replacements)
    assert all("replacement action is not safe for Key Override" in warning for warning in result.warnings)


def main() -> None:
    test_key_override_replacement_allows_key_like_actions()
    test_key_override_replacement_rejects_stateful_and_control_actions()
    print("ok: Key Override replacement safety validation")


if __name__ == "__main__":
    main()
