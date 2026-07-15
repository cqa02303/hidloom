#!/usr/bin/env python3
"""Tests for the neutral MorseSequenceProfile adapter."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.morse_behavior import MorseBehaviorDef  # noqa: E402
from logicd.sequence_engine import SequenceEmission, SequenceStep  # noqa: E402
from logicd.sequence_morse import MorseSequenceProfile  # noqa: E402


def feedback_phases(emissions: tuple[SequenceEmission, ...]) -> list[str]:
    return [
        str(emission.feedback.get("phase"))
        for emission in emissions
        if emission.kind == "feedback" and emission.feedback is not None
    ]


def tap_actions(emissions: tuple[SequenceEmission, ...]) -> list[str]:
    return [
        str(emission.action)
        for emission in emissions
        if emission.kind == "tap"
    ]


def make_profile() -> MorseSequenceProfile:
    return MorseSequenceProfile(MorseBehaviorDef(
        name="main",
        actions={".": "KC_E", ".-": "KC_A"},
        dot_threshold=0.180,
        sequence_timeout=0.700,
        max_depth=2,
    ))


def test_morse_profile_leaf_commit_matches_existing_source() -> None:
    profile = MorseSequenceProfile(MorseBehaviorDef(
        name="leaf",
        actions={"-": "KC_T"},
        dot_threshold=0.180,
        sequence_timeout=0.700,
        max_depth=1,
    ))

    press = profile.handle_step(SequenceStep("press", now=1.000, row=0, col=0))
    assert feedback_phases(press.emissions) == ["press"]
    assert not press.timer

    release = profile.handle_step(SequenceStep("release", now=1.250, row=0, col=0))
    assert tap_actions(release.emissions) == ["KC_T"]
    assert feedback_phases(release.emissions) == ["commit"]
    assert release.emissions[0].source == "morse"
    assert release.emissions[1].feedback["reason"] == "leaf"
    assert not release.timer


def test_morse_profile_prefix_timeout_uses_timer_identity() -> None:
    profile = make_profile()

    profile.handle_step(SequenceStep("press", now=2.000, row=0, col=0))
    release = profile.handle_step(SequenceStep("release", now=2.080, row=0, col=0))
    assert tap_actions(release.emissions) == []
    assert feedback_phases(release.emissions) == ["pending"]
    assert release.timer is not None
    assert release.timer.profile == "morse:main"
    assert release.timer.source_key == (0, 0)
    assert abs(release.timer.due - 2.780) < 0.001
    assert release.timer.matches(profile="morse:main", source_key=(0, 0), generation=release.timer.generation)

    timeout = profile.handle_step(SequenceStep("timeout", now=2.900, row=0, col=0))
    assert tap_actions(timeout.emissions) == ["KC_E"]
    assert feedback_phases(timeout.emissions) == ["commit"]
    assert timeout.emissions[-1].feedback["reason"] == "timeout"


def test_morse_profile_force_commit_and_reset_feedback() -> None:
    profile = MorseSequenceProfile(MorseBehaviorDef(
        name="force",
        actions={".": "KC_E", ".-": "KC_A", ".-.": "KC_R"},
        dot_threshold=0.180,
        sequence_timeout=0.700,
        max_depth=3,
        force_commit_sequences=frozenset({".-"}),
    ))

    profile.handle_step(SequenceStep("press", now=3.000, row=0, col=0))
    pending = profile.handle_step(SequenceStep("release", now=3.080, row=0, col=0))
    assert feedback_phases(pending.emissions) == ["pending"]
    assert pending.timer is not None

    profile.handle_step(SequenceStep("press", now=3.200, row=0, col=0))
    commit = profile.handle_step(SequenceStep("release", now=3.450, row=0, col=0))
    assert tap_actions(commit.emissions) == ["KC_A"]
    assert commit.emissions[-1].feedback["reason"] == "force_commit"
    assert not commit.timer

    reset = profile.handle_step(SequenceStep("reset", now=4.000))
    assert feedback_phases(reset.emissions) == ["reset"]


def main() -> None:
    test_morse_profile_leaf_commit_matches_existing_source()
    test_morse_profile_prefix_timeout_uses_timer_identity()
    test_morse_profile_force_commit_and_reset_feedback()
    print("ok: sequence Morse profile")


if __name__ == "__main__":
    main()

