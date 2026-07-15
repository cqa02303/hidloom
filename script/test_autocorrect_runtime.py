#!/usr/bin/env python3
"""Tests for the default-off ASCII autocorrect runtime helper."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.autocorrect import AutocorrectRuntime, validate_autocorrect_settings  # noqa: E402


def test_default_is_disabled_and_does_not_buffer() -> None:
    runtime = AutocorrectRuntime({})
    assert runtime.validation.ok
    assert not runtime.enabled
    assert not runtime.handle_action("KC_T", True).corrected
    assert runtime.buffer == ""


def test_dictionary_validation_is_ascii_lowercase_only() -> None:
    validation = validate_autocorrect_settings({
        "enabled": True,
        "entries": {
            "teh": "the",
            "Teh": "the",
            "kana": "かな",
            "same": "same",
        },
    })
    assert not validation.ok
    assert validation.entries == {"teh": "the"}
    assert any("lower-case ASCII" in error for error in validation.errors)
    assert any("replacement" in error for error in validation.errors)
    assert any("no-op" in warning for warning in validation.warnings)


def test_boundary_generates_backspace_replacement_and_boundary_taps() -> None:
    runtime = AutocorrectRuntime({"enabled": True, "entries": {"teh": "the"}})
    for action in ["KC_T", "KC_E", "KC_H"]:
        result = runtime.handle_action(action, True)
        assert not result.corrected
    result = runtime.handle_action("KC_SPACE", True)
    assert result.correction == ("KC_BSPC", "KC_BSPC", "KC_BSPC", "KC_T", "KC_H", "KC_E", "KC_SPACE")
    assert runtime.buffer == ""


def test_backspace_adjusts_buffer_and_releases_are_ignored() -> None:
    runtime = AutocorrectRuntime({"enabled": True, "entries": {"adn": "and"}})
    runtime.handle_action("KC_A", True)
    runtime.handle_action("KC_X", True)
    runtime.handle_action("KC_X", False)
    runtime.handle_action("KC_BSPC", True)
    runtime.handle_action("KC_D", True)
    runtime.handle_action("KC_N", True)
    result = runtime.handle_action("KC_ENTER", True)
    assert result.correction == ("KC_BSPC", "KC_BSPC", "KC_BSPC", "KC_A", "KC_N", "KC_D", "KC_ENTER")


def test_non_printable_clears_buffer() -> None:
    runtime = AutocorrectRuntime({"enabled": True, "entries": {"teh": "the"}})
    runtime.handle_action("KC_T", True)
    runtime.handle_action("KC_E", True)
    result = runtime.handle_action("WIFI_POWER_OFF", True)
    assert result.cleared
    assert result.reason == "non_printable"
    assert runtime.buffer == ""


def main() -> None:
    test_default_is_disabled_and_does_not_buffer()
    test_dictionary_validation_is_ascii_lowercase_only()
    test_boundary_generates_backspace_replacement_and_boundary_taps()
    test_backspace_adjusts_buffer_and_releases_are_ignored()
    test_non_printable_clears_buffer()
    print("ok: autocorrect runtime helper")


if __name__ == "__main__":
    main()
