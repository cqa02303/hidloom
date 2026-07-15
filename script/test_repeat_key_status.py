#!/usr/bin/env python3
"""Regression tests for logicd.repeat_key_status."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.repeat_key_status import (  # noqa: E402
    alternate_pair_count,
    normalize_alternate_pairs,
    repeat_key_default_alternate_pairs,
    repeat_key_status,
    repeat_key_status_from_engine,
)


class DummyEngine:
    def __init__(self, history=None, enabled=True, alternate=None):
        self.repeat_history = history
        self.repeat_key = {
            "enabled": enabled,
            "alternate": alternate or {},
        }


def test_normalize_alternate_pairs_is_bidirectional() -> None:
    alternate = normalize_alternate_pairs([
        ["KC_LEFT", "KC_RGHT"],
        ["KC_UP", "KC_DOWN"],
        ["KC_A", "KC_A"],
        ["KC_BAD"],
        ["", "KC_X"],
    ])

    assert alternate["KC_LEFT"] == "KC_RGHT"
    assert alternate["KC_RGHT"] == "KC_LEFT"
    assert alternate["KC_UP"] == "KC_DOWN"
    assert alternate["KC_DOWN"] == "KC_UP"
    assert "KC_A" not in alternate
    assert alternate_pair_count(alternate) == 2


def test_default_pairs_are_stable_subset() -> None:
    pairs = repeat_key_default_alternate_pairs()
    assert ("KC_LEFT", "KC_RGHT") in pairs
    assert ("KC_UP", "KC_DOWN") in pairs
    assert ("KC_BSPC", "KC_DEL") in pairs
    assert ("MS_LEFT", "MS_RGHT") in pairs


def test_status_hides_history_action_name() -> None:
    alternate = normalize_alternate_pairs([["KC_LEFT", "KC_RGHT"]])

    status = repeat_key_status(
        enabled=True,
        repeat_history="KC_LEFT",
        alternate=alternate,
    ).to_dict()

    assert status == {
        "enabled": True,
        "history_available": True,
        "alternate_available": True,
        "alternate_pair_count": 1,
    }
    assert "KC_LEFT" not in repr(status)


def test_status_without_history_or_without_alternate() -> None:
    alternate = normalize_alternate_pairs([["KC_LEFT", "KC_RGHT"]])

    no_history = repeat_key_status(enabled=True, repeat_history=None, alternate=alternate).to_dict()
    assert no_history["history_available"] is False
    assert no_history["alternate_available"] is False

    no_alt = repeat_key_status(enabled=True, repeat_history="KC_A", alternate=alternate).to_dict()
    assert no_alt["history_available"] is True
    assert no_alt["alternate_available"] is False

    disabled = repeat_key_status(enabled=False, repeat_history="KC_LEFT", alternate=alternate).to_dict()
    assert disabled["history_available"] is False
    assert disabled["alternate_available"] is False


def test_status_from_engine_like_object() -> None:
    alternate = normalize_alternate_pairs([["KC_LEFT", "KC_RGHT"], ["KC_UP", "KC_DOWN"]])
    engine = DummyEngine(history="KC_RGHT", enabled=True, alternate=alternate)

    status = repeat_key_status_from_engine(engine)

    assert status["enabled"] is True
    assert status["history_available"] is True
    assert status["alternate_available"] is True
    assert status["alternate_pair_count"] == 2
    assert "KC_RGHT" not in repr(status)


def main() -> None:
    test_normalize_alternate_pairs_is_bidirectional()
    test_default_pairs_are_stable_subset()
    test_status_hides_history_action_name()
    test_status_without_history_or_without_alternate()
    test_status_from_engine_like_object()
    print("ok: repeat key status is privacy-safe and alternate-aware")


if __name__ == "__main__":
    main()
