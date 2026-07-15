#!/usr/bin/env python3
"""Regression tests for InteractionEngine MORSE behavior wiring."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.interaction_engine import InteractionEngine, ResolvedActionEvent  # noqa: E402
from logicd.keymap import LayerManager  # noqa: E402


def actions(events: list[ResolvedActionEvent]) -> list[tuple[str, bool, str]]:
    return [(event.action, event.is_press, event.source) for event in events]


def make_layers() -> LayerManager:
    layers = LayerManager()
    layers.load([
        {
            "0,0": "MORSE(main)",
            "0,1": "KC_B",
        }
    ])
    return layers


def test_morse_leaf_commits_on_release() -> None:
    engine = InteractionEngine(
        make_layers(),
        morse_behaviors={
            "main": {
                "dot_threshold": 0.180,
                "sequence_timeout": 0.700,
                "max_depth": 1,
                "map": {"-": "KC_T"},
            }
        },
    )

    assert engine.on_key(0, 0, True, 1.000) == []
    assert engine.drain_morse_feedback()[0]["phase"] == "press"
    assert actions(engine.on_key(0, 0, False, 1.250)) == [
        ("KC_T", True, "morse"),
        ("KC_T", False, "morse"),
    ]
    feedback = engine.drain_morse_feedback()
    assert feedback == [{
        "type": "morse",
        "name": "main",
        "phase": "commit",
        "sequence": "-",
        "stroke": "-",
        "action": "KC_T",
        "pending_action": None,
        "reason": "leaf",
        "canceled": False,
        "fallback": False,
        "needs_timeout": False,
        "row": 0,
        "col": 0,
    }]
    assert engine.drain_morse_feedback() == []


def test_morse_prefix_commits_on_timeout() -> None:
    engine = InteractionEngine(
        make_layers(),
        morse_behaviors={
            "main": {
                "dot_threshold": 0.180,
                "sequence_timeout": 0.700,
                "max_depth": 2,
                "map": {".": "KC_E", ".-": "KC_A"},
            }
        },
    )

    assert engine.on_key(0, 0, True, 2.000) == []
    assert engine.on_key(0, 0, False, 2.080) == []
    feedback = engine.drain_morse_feedback()
    assert [event["phase"] for event in feedback] == ["press", "pending"]
    assert feedback[-1]["sequence"] == "."
    assert feedback[-1]["pending_action"] == "KC_E"
    assert engine.next_timer_due() is not None
    assert abs(engine.next_timer_due() - 2.780) < 0.001
    assert actions(engine.on_tick(2.900)) == [
        ("KC_E", True, "morse"),
        ("KC_E", False, "morse"),
    ]
    feedback = engine.drain_morse_feedback()
    assert feedback[-1]["phase"] == "commit"
    assert feedback[-1]["reason"] == "timeout"
    assert feedback[-1]["action"] == "KC_E"


def test_morse_force_commit_without_waiting_for_deeper_prefix() -> None:
    engine = InteractionEngine(
        make_layers(),
        morse_behaviors={
            "main": {
                "dot_threshold": 0.180,
                "sequence_timeout": 0.700,
                "max_depth": 3,
                "force_commit": [".-"],
                "map": {".": "KC_E", ".-": "KC_A", ".-.": "KC_R"},
            }
        },
    )

    assert engine.on_key(0, 0, True, 3.000) == []
    assert engine.on_key(0, 0, False, 3.080) == []
    assert engine.on_key(0, 0, True, 3.200) == []
    assert actions(engine.on_key(0, 0, False, 3.450)) == [
        ("KC_A", True, "morse"),
        ("KC_A", False, "morse"),
    ]
    assert actions(engine.on_tick(4.000)) == []
    feedback = engine.drain_morse_feedback()
    assert feedback[-1]["phase"] == "commit"
    assert feedback[-1]["reason"] == "force_commit"
    assert feedback[-1]["sequence"] == ".-"


def test_morse_unmapped_branch_cancels() -> None:
    engine = InteractionEngine(
        make_layers(),
        morse_behaviors={
            "main": {
                "dot_threshold": 0.180,
                "sequence_timeout": 0.700,
                "max_depth": 1,
                "map": {".": "KC_E"},
            }
        },
    )

    assert engine.on_key(0, 0, True, 4.000) == []
    assert actions(engine.on_key(0, 0, False, 4.300)) == []
    assert engine.next_timer_due() is None
    feedback = engine.drain_morse_feedback()
    assert feedback[-1]["phase"] == "cancel"
    assert feedback[-1]["reason"] == "unmapped"
    assert feedback[-1]["sequence"] == "-"


def test_morse_unmapped_branch_emits_fallback_action() -> None:
    engine = InteractionEngine(
        make_layers(),
        morse_behaviors={
            "main": {
                "dot_threshold": 0.180,
                "sequence_timeout": 0.700,
                "max_depth": 1,
                "fallback_action": "KC_ESC",
                "map": {".": "KC_E"},
            }
        },
    )

    assert engine.on_key(0, 0, True, 4.000) == []
    assert actions(engine.on_key(0, 0, False, 4.300)) == [
        ("KC_ESC", True, "morse"),
        ("KC_ESC", False, "morse"),
    ]
    assert engine.next_timer_due() is None
    feedback = engine.drain_morse_feedback()
    assert feedback[-1]["phase"] == "fallback"
    assert feedback[-1]["action"] == "KC_ESC"
    assert feedback[-1]["reason"] == "fallback_unmapped"


def test_morse_timeout_unmapped_emits_fallback_action() -> None:
    engine = InteractionEngine(
        make_layers(),
        morse_behaviors={
            "main": {
                "dot_threshold": 0.180,
                "sequence_timeout": 0.700,
                "max_depth": 2,
                "fallback_action": "KC_ESC",
                "map": {".": "KC_NONE", ".-": "KC_A"},
            }
        },
    )

    assert engine.on_key(0, 0, True, 4.500) == []
    assert engine.on_key(0, 0, False, 4.580) == []
    assert actions(engine.on_tick(5.400)) == [
        ("KC_ESC", True, "morse"),
        ("KC_ESC", False, "morse"),
    ]
    feedback = engine.drain_morse_feedback()
    assert feedback[-1]["phase"] == "fallback"
    assert feedback[-1]["reason"] == "fallback_timeout_unmapped"
    assert feedback[-1]["sequence"] == "."


def test_morse_reset_clears_pending_sequence() -> None:
    engine = InteractionEngine(
        make_layers(),
        morse_behaviors={
            "main": {
                "dot_threshold": 0.180,
                "sequence_timeout": 0.700,
                "max_depth": 2,
                "map": {".": "KC_E", ".-": "KC_A"},
            }
        },
    )

    assert engine.on_key(0, 0, True, 5.000) == []
    assert engine.on_key(0, 0, False, 5.080) == []
    engine.drain_morse_feedback()
    engine.reset()
    assert actions(engine.on_tick(5.900)) == []
    assert engine.drain_morse_feedback()[0]["phase"] == "reset"


def main() -> None:
    test_morse_leaf_commits_on_release()
    test_morse_prefix_commits_on_timeout()
    test_morse_force_commit_without_waiting_for_deeper_prefix()
    test_morse_unmapped_branch_cancels()
    test_morse_unmapped_branch_emits_fallback_action()
    test_morse_timeout_unmapped_emits_fallback_action()
    test_morse_reset_clears_pending_sequence()
    print("ok: interaction engine MORSE behavior")


if __name__ == "__main__":
    main()
