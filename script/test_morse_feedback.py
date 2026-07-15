#!/usr/bin/env python3
"""Regression tests for MORSE feedback payload helpers."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.morse_behavior import MorseBehaviorDef, MorseBehaviorRuntime  # noqa: E402
from logicd.morse_feedback import (  # noqa: E402
    behavior_feedback_schema,
    feedback_for_press,
    feedback_for_reset,
    feedback_from_step,
)


def test_feedback_for_press_and_reset() -> None:
    press = feedback_for_press("main", row=1, col=2)
    assert press.to_dict() == {
        "type": "morse",
        "name": "main",
        "phase": "press",
        "sequence": "",
        "stroke": "",
        "action": None,
        "pending_action": None,
        "reason": "",
        "canceled": False,
        "fallback": False,
        "needs_timeout": False,
        "row": 1,
        "col": 2,
    }

    reset = feedback_for_reset("main")
    assert reset.to_dict()["phase"] == "reset"
    assert reset.to_dict()["name"] == "main"


def test_feedback_from_pending_and_commit() -> None:
    runtime = MorseBehaviorRuntime(MorseBehaviorDef(
        name="main",
        actions={".": "KC_E", ".-": "KC_A"},
        max_depth=2,
    ))
    pending = feedback_from_step("main", runtime.add_stroke("."), row=0, col=0)
    assert pending.phase == "pending"
    assert pending.sequence == "."
    assert pending.pending_action == "KC_E"
    assert pending.needs_timeout is True

    commit = feedback_from_step("main", runtime.add_stroke("-"), row=0, col=0)
    assert commit.phase == "commit"
    assert commit.sequence == ".-"
    assert commit.action == "KC_A"
    assert commit.fallback is False


def test_feedback_from_fallback() -> None:
    runtime = MorseBehaviorRuntime(MorseBehaviorDef(
        name="main",
        actions={".": "KC_E"},
        max_depth=1,
        fallback_action="KC_ESC",
    ))
    fallback = feedback_from_step("main", runtime.add_stroke("-"), row=0, col=0)
    payload = fallback.to_dict()
    assert payload["phase"] == "fallback"
    assert payload["sequence"] == "-"
    assert payload["action"] == "KC_ESC"
    assert payload["fallback"] is True
    assert payload["canceled"] is True
    assert payload["reason"] == "fallback_unmapped"


def test_behavior_feedback_schema() -> None:
    definition = MorseBehaviorDef(
        name="nav",
        actions={".": "KC_LEFT", "-": "KC_RIGHT"},
        dot_threshold=0.15,
        sequence_timeout=0.45,
        max_depth=3,
        force_commit_sequences=frozenset(["."]),
        fallback_action="KC_ESC",
    )
    assert behavior_feedback_schema(definition) == {
        "name": "nav",
        "dot_threshold": 0.15,
        "sequence_timeout": 0.45,
        "max_depth": 3,
        "force_commit": ["."],
        "fallback_action": "KC_ESC",
        "map_size": 2,
    }


def main() -> None:
    test_feedback_for_press_and_reset()
    test_feedback_from_pending_and_commit()
    test_feedback_from_fallback()
    test_behavior_feedback_schema()
    print("ok: MORSE feedback schema")


if __name__ == "__main__":
    main()
