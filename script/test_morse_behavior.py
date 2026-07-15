#!/usr/bin/env python3
"""Regression tests for timed tap / Morse behavior core."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.morse_behavior import (  # noqa: E402
    MorseBehaviorDef,
    MorseBehaviorRuntime,
    normalize_morse_behaviors,
    parse_morse_action,
)


def test_parse_morse_action() -> None:
    assert parse_morse_action("MORSE(main)") == "main"
    assert parse_morse_action(" MORSE(nav.layer) ") == "nav.layer"
    assert parse_morse_action("TD(main)") is None


def test_dot_dash_from_press_duration() -> None:
    runtime = MorseBehaviorRuntime(MorseBehaviorDef(
        name="main",
        dot_threshold=0.180,
        sequence_timeout=0.700,
        max_depth=2,
        actions={".": "KC_E", "-": "KC_T"},
    ))

    runtime.press(1.000)
    dot = runtime.release(1.100)
    assert dot.stroke == "."
    assert dot.committed_action == "KC_E"
    assert dot.reason == "leaf"

    runtime.press(2.000)
    dash = runtime.release(2.250)
    assert dash.stroke == "-"
    assert dash.committed_action == "KC_T"
    assert dash.reason == "leaf"


def test_prefix_waits_until_timeout() -> None:
    runtime = MorseBehaviorRuntime(MorseBehaviorDef(
        name="main",
        dot_threshold=0.180,
        sequence_timeout=0.700,
        max_depth=2,
        actions={".": "KC_E", ".-": "KC_A"},
    ))

    pending = runtime.add_stroke(".")
    assert pending.sequence == "."
    assert pending.pending_action == "KC_E"
    assert pending.needs_timeout is True
    assert pending.committed_action is None

    committed = runtime.timeout()
    assert committed.sequence == "."
    assert committed.committed_action == "KC_E"
    assert committed.reason == "timeout"


def test_force_commit_sequence_commits_even_when_prefix_exists() -> None:
    runtime = MorseBehaviorRuntime(MorseBehaviorDef(
        name="main",
        dot_threshold=0.180,
        sequence_timeout=0.700,
        max_depth=3,
        actions={".": "KC_E", ".-": "KC_A", ".-.": "KC_R"},
        force_commit_sequences=frozenset([".-"]),
    ))

    assert runtime.add_stroke(".").needs_timeout is True
    force_commit = runtime.add_stroke("-")
    assert force_commit.sequence == ".-"
    assert force_commit.committed_action == "KC_A"
    assert force_commit.reason == "force_commit"
    assert runtime.state.sequence == ""


def test_longer_sequence_can_commit_leaf() -> None:
    runtime = MorseBehaviorRuntime(MorseBehaviorDef(
        name="main",
        dot_threshold=0.180,
        sequence_timeout=0.700,
        max_depth=2,
        actions={".": "KC_E", ".-": "KC_A"},
    ))

    assert runtime.add_stroke(".").needs_timeout is True
    leaf = runtime.add_stroke("-")
    assert leaf.sequence == ".-"
    assert leaf.committed_action == "KC_A"
    assert leaf.reason == "leaf"


def test_unmapped_branch_cancels() -> None:
    runtime = MorseBehaviorRuntime(MorseBehaviorDef(
        name="main",
        dot_threshold=0.180,
        sequence_timeout=0.700,
        max_depth=2,
        actions={".": "KC_E"},
    ))

    canceled = runtime.add_stroke("-")
    assert canceled.canceled is True
    assert canceled.reason == "unmapped"
    assert runtime.state.sequence == ""


def test_unmapped_branch_emits_fallback_action() -> None:
    runtime = MorseBehaviorRuntime(MorseBehaviorDef(
        name="main",
        dot_threshold=0.180,
        sequence_timeout=0.700,
        max_depth=2,
        actions={".": "KC_E"},
        fallback_action="KC_ESC",
    ))

    fallback = runtime.add_stroke("-")
    assert fallback.canceled is True
    assert fallback.sequence == "-"
    assert fallback.committed_action == "KC_ESC"
    assert fallback.reason == "fallback_unmapped"
    assert runtime.state.sequence == ""


def test_timeout_unmapped_emits_fallback_action() -> None:
    runtime = MorseBehaviorRuntime(MorseBehaviorDef(
        name="main",
        dot_threshold=0.180,
        sequence_timeout=0.700,
        max_depth=2,
        actions={".": "KC_NONE", ".-": "KC_A"},
        fallback_action="KC_ESC",
    ))

    pending = runtime.add_stroke(".")
    assert pending.pending_action is None
    assert pending.needs_timeout is True

    fallback = runtime.timeout()
    assert fallback.canceled is True
    assert fallback.sequence == "."
    assert fallback.committed_action == "KC_ESC"
    assert fallback.reason == "fallback_timeout_unmapped"


def test_none_action_is_cancel_on_timeout() -> None:
    runtime = MorseBehaviorRuntime(MorseBehaviorDef(
        name="main",
        dot_threshold=0.180,
        sequence_timeout=0.700,
        max_depth=2,
        actions={".": "KC_NONE", ".-": "KC_A"},
    ))

    pending = runtime.add_stroke(".")
    assert pending.pending_action is None
    assert pending.needs_timeout is True

    canceled = runtime.timeout()
    assert canceled.canceled is True
    assert canceled.reason == "timeout_unmapped"


def test_max_depth_is_variable_and_rejects_too_deep_definition() -> None:
    try:
        MorseBehaviorDef(
            name="main",
            dot_threshold=0.180,
            sequence_timeout=0.700,
            max_depth=3,
            actions={"...": "KC_S", "....": "KC_H"},
        )
    except ValueError as exc:
        assert "max_depth" in str(exc)
    else:
        raise AssertionError("too-deep Morse definition should be rejected")

    runtime = MorseBehaviorRuntime(MorseBehaviorDef(
        name="main",
        dot_threshold=0.180,
        sequence_timeout=0.700,
        max_depth=3,
        actions={"...": "KC_S"},
    ))
    assert runtime.add_stroke(".").needs_timeout is True
    assert runtime.add_stroke(".").needs_timeout is True
    leaf = runtime.add_stroke(".")
    assert leaf.committed_action == "KC_S"


def test_force_commit_sequence_requires_mapped_action() -> None:
    try:
        MorseBehaviorDef(
            name="main",
            dot_threshold=0.180,
            sequence_timeout=0.700,
            max_depth=3,
            actions={".": "KC_E"},
            force_commit_sequences=frozenset([".-"]),
        )
    except ValueError as exc:
        assert "force-commit" in str(exc)
    else:
        raise AssertionError("force_commit sequence without action should be rejected")


def test_normalize_morse_behaviors() -> None:
    defs = normalize_morse_behaviors({
        "main": {
            "dot_threshold": 0.2,
            "sequence_timeout": 0.8,
            "max_depth": 3,
            "force_commit": [".-"],
            "fallback_action": "KC_ESC",
            "map": {
                ".": "KC_E",
                "-": "KC_T",
                ".-": "KC_A",
                "bad": "KC_NO",
            },
        },
        "legacy": {
            "max_depth": 2,
            "terminal": ".-",
            "map": {".-": "KC_A"},
        },
        "short": {
            ".-": "KC_A",
        },
    })

    assert sorted(defs) == ["legacy", "main", "short"]
    assert defs["main"].dot_threshold == 0.2
    assert defs["main"].sequence_timeout == 0.8
    assert defs["main"].actions == {".": "KC_E", "-": "KC_T", ".-": "KC_A"}
    assert defs["main"].force_commit_sequences == frozenset([".-"])
    assert defs["main"].fallback_action == "KC_ESC"
    assert defs["legacy"].force_commit_sequences == frozenset([".-"])
    assert defs["short"].max_depth == 2


def main() -> None:
    test_parse_morse_action()
    test_dot_dash_from_press_duration()
    test_prefix_waits_until_timeout()
    test_force_commit_sequence_commits_even_when_prefix_exists()
    test_longer_sequence_can_commit_leaf()
    test_unmapped_branch_cancels()
    test_unmapped_branch_emits_fallback_action()
    test_timeout_unmapped_emits_fallback_action()
    test_none_action_is_cancel_on_timeout()
    test_max_depth_is_variable_and_rejects_too_deep_definition()
    test_force_commit_sequence_requires_mapped_action()
    test_normalize_morse_behaviors()
    print("ok: morse behavior core")


if __name__ == "__main__":
    main()
