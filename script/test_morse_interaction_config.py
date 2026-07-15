#!/usr/bin/env python3
"""Regression tests for MORSE interaction config validation."""
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


def test_morse_action_is_valid_in_combo_and_override() -> None:
    result = validate_interaction_settings(
        {
            "combos": [
                {"keys": [[0, 0], [0, 1]], "action": "MORSE(main)"},
            ],
            "key_overrides": [
                {"trigger": "KC_LSFT", "key": "KC_A", "replacement": "MORSE(nav.layer)"},
            ],
        },
        matrix_in_range=in_range,
    )
    assert result.warnings == []
    assert result.settings["combos"] == [{"keys": [[0, 0], [0, 1]], "action": "MORSE(main)"}]
    assert result.settings["key_overrides"][0]["replacement"] == "MORSE(nav.layer)"


def test_morse_behaviors_are_normalized() -> None:
    result = validate_interaction_settings(
        {
            "morse_behaviors": {
                "main": {
                    "dot_threshold": 0.2,
                    "sequence_timeout": 0.8,
                    "max_depth": 3,
                    "fallback_action": "KC_ESC",
                    "force_commit": [".-"],
                    "map": {
                        ".": "KC_E",
                        "-": "KC_T",
                        ".-": "KC_A",
                        "...": "KC_S",
                    },
                }
            }
        },
        matrix_in_range=in_range,
    )
    assert result.warnings == []
    assert result.settings["morse_behaviors"] == {
        "main": {
            "dot_threshold": 0.2,
            "sequence_timeout": 0.8,
            "max_depth": 3,
            "map": {
                ".": "KC_E",
                "-": "KC_T",
                ".-": "KC_A",
                "...": "KC_S",
            },
            "force_commit": [".-"],
            "fallback_action": "KC_ESC",
        }
    }


def test_legacy_terminal_alias_is_accepted_but_normalized_to_force_commit() -> None:
    result = validate_interaction_settings(
        {
            "morse_behaviors": {
                "legacy": {
                    "max_depth": 2,
                    "terminal": ".-",
                    "map": {".-": "KC_A"},
                }
            }
        },
        matrix_in_range=in_range,
    )
    assert result.warnings == []
    assert result.settings["morse_behaviors"]["legacy"]["force_commit"] == [".-"]


def test_morse_fallback_no_action_values_are_omitted() -> None:
    result = validate_interaction_settings(
        {
            "morse_behaviors": {
                "main": {
                    "fallback_action": "KC_NONE",
                    "map": {".": "KC_E"},
                }
            }
        },
        matrix_in_range=in_range,
    )
    assert result.warnings == []
    assert "fallback_action" not in result.settings["morse_behaviors"]["main"]


def test_runtime_config_passes_morse_behaviors_to_engine() -> None:
    config_runtime = (ROOT / "daemon" / "logicd" / "config_runtime.py").read_text(encoding="utf-8")
    assert 'morse_behaviors=interaction.get("morse_behaviors", {})' in config_runtime


def test_morse_behaviors_warn_and_skip_invalid_entries() -> None:
    result = validate_interaction_settings(
        {
            "morse_behaviors": {
                "main": {
                    "dot_threshold": "bad",
                    "sequence_timeout": -1,
                    "max_depth": 2,
                    "fallback_action": "BAD(A",
                    "force_commit": [".", "---", "--", "abc"],
                    "map": {
                        ".": "KC_E",
                        "abc": "KC_X",
                        "---": "KC_O",
                        "-": "BAD(A",
                    },
                }
            }
        },
        matrix_in_range=in_range,
    )
    assert result.settings["morse_behaviors"] == {
        "main": {
            "dot_threshold": 0.180,
            "sequence_timeout": 0.700,
            "max_depth": 2,
            "map": {".": "KC_E"},
            "force_commit": ["."],
        }
    }
    assert any("dot_threshold ignored" in warning for warning in result.warnings)
    assert any("sequence_timeout ignored" in warning for warning in result.warnings)
    assert any("abc ignored: invalid sequence" in warning for warning in result.warnings)
    assert any("--- ignored: exceeds max_depth" in warning for warning in result.warnings)
    assert any("- ignored: invalid action syntax" in warning for warning in result.warnings)
    assert any("fallback_action ignored: invalid action syntax" in warning for warning in result.warnings)
    assert any("force_commit --- ignored: exceeds max_depth" in warning for warning in result.warnings)
    assert any("force_commit -- ignored: no mapped action" in warning for warning in result.warnings)
    assert any("force_commit 'abc' ignored: invalid sequence" in warning for warning in result.warnings)


def main() -> None:
    test_morse_action_is_valid_in_combo_and_override()
    test_morse_behaviors_are_normalized()
    test_legacy_terminal_alias_is_accepted_but_normalized_to_force_commit()
    test_morse_fallback_no_action_values_are_omitted()
    test_runtime_config_passes_morse_behaviors_to_engine()
    test_morse_behaviors_warn_and_skip_invalid_entries()
    print("ok: MORSE interaction config validation")


if __name__ == "__main__":
    main()
