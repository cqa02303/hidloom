#!/usr/bin/env python3
"""Tests for neutral SequenceEngine emission primitives."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.sequence_engine import (  # noqa: E402
    FINAL_ACTION_OBSERVER_KINDS,
    NON_HOST_EMISSION_KINDS,
    SequenceEmission,
    SequencePressedAction,
    SequenceResult,
    SequenceStep,
    SequenceSuppressionLedger,
    SequenceTimerRef,
    SequenceTimerRegistry,
    emission_sort_key,
    final_action_observer_emissions,
    split_host_and_feedback,
    validate_emission_batch,
)


def test_host_and_feedback_boundaries() -> None:
    assert SequenceEmission("press", action="KC_A").is_host_visible
    assert SequenceEmission("tap", action="KC_A").is_host_visible
    assert not SequenceEmission("feedback", feedback={"phase": "pending"}).is_host_visible
    assert not SequenceEmission("cancel", reason="reset").is_host_visible
    assert NON_HOST_EMISSION_KINDS == frozenset({"feedback", "cancel"})


def test_required_action_validation() -> None:
    SequenceEmission("suppress", action="KC_LSFT").validate()
    SequenceEmission("restore", action="KC_LSFT").validate()
    SequenceEmission("feedback", feedback={"phase": "commit"}).validate()

    for emission in [
        SequenceEmission("press"),
        SequenceEmission("tap"),
        SequenceEmission("release"),
        SequenceEmission("feedback", action="KC_A"),
        SequenceEmission("cancel", action="KC_A"),
    ]:
        try:
            emission.validate()
        except ValueError:
            continue
        raise AssertionError(f"invalid emission was accepted: {emission!r}")


def test_ordering_keeps_suppress_before_press_and_restore_after_tap() -> None:
    ordered = [
        SequenceEmission("suppress", action="KC_LSFT", source="key_override"),
        SequenceEmission("release", action="KC_ESC", source="emergency_release"),
        SequenceEmission("press", action="KC_ESC", source="matrix"),
        SequenceEmission("tap", action="KC_A", source="morse"),
        SequenceEmission("restore", action="KC_LSFT", source="key_override"),
        SequenceEmission("feedback", feedback={"phase": "commit"}, source="morse"),
        SequenceEmission("cancel", reason="reset", source="sequence"),
    ]
    assert sorted(reversed(ordered), key=emission_sort_key) == ordered
    validate_emission_batch(ordered)

    unordered = [ordered[2], ordered[0]]
    try:
        validate_emission_batch(unordered)
    except ValueError as exc:
        assert "dispatch-safe order" in str(exc)
    else:
        raise AssertionError("unordered emission batch was accepted")


def test_sequence_timer_identity_and_result_validation() -> None:
    step = SequenceStep("press", now=1.250, row=0, col=1)
    assert step.kind == "press"
    assert step.row == 0
    assert step.col == 1

    timer = SequenceTimerRef(profile="morse:main", source_key=(0, 1), generation=7, due=1.950)
    assert timer.matches(profile="morse:main", source_key=(0, 1), generation=7)
    assert not timer.matches(profile="morse:main", source_key=(0, 1), generation=8)
    assert not timer.matches(profile="morse:other", source_key=(0, 1), generation=7)

    result = SequenceResult(
        emissions=(
            SequenceEmission("tap", action="KC_A", source="morse"),
            SequenceEmission("feedback", feedback={"phase": "commit"}, source="morse"),
        ),
        timer=timer,
    )
    result.validate()

    try:
        SequenceResult(timer=SequenceTimerRef(profile="bad", source_key=None, generation=-1, due=2.0)).validate()
    except ValueError as exc:
        assert "generation" in str(exc)
    else:
        raise AssertionError("negative timer generation was accepted")


def test_pressed_action_pins_release_owner_and_guards_double_release() -> None:
    pressed = SequencePressedAction(action="KC_LSFT", source="tap_hold", row=1, col=2)
    release = pressed.release(reason="output_switch")
    assert release == SequenceEmission(
        "release",
        action="KC_LSFT",
        source="tap_hold",
        row=1,
        col=2,
        reason="output_switch",
    )
    assert pressed.release(reason="physical_release") is None


def test_suppression_ledger_reference_count_and_physical_release_rule() -> None:
    ledger = SequenceSuppressionLedger()
    first = ledger.suppress("KC_LSFT", owner="key_override")
    second = ledger.suppress("KC_LSFT", owner="combo")
    assert first == SequenceEmission(
        "suppress",
        action="KC_LSFT",
        source="key_override",
        source_action="KC_LSFT",
    )
    assert second is None
    assert ledger.active_owners("KC_LSFT") == frozenset({"key_override", "combo"})
    assert ledger.restore("KC_LSFT", owner="key_override") is None
    assert ledger.restore("KC_LSFT", owner="combo") == SequenceEmission(
        "restore",
        action="KC_LSFT",
        source="combo",
        source_action="KC_LSFT",
    )

    assert ledger.suppress("KC_A", owner="combo") is not None
    ledger.mark_source_released("KC_A")
    assert ledger.restore("KC_A", owner="combo") is None


def test_timer_registry_invalidates_stale_timeouts() -> None:
    timers = SequenceTimerRegistry()
    first = timers.schedule(profile="tap_hold", source_key=(0, 1), due=1.500)
    assert timers.is_active(first)
    timers.invalidate(profile="tap_hold", source_key=(0, 1))
    assert not timers.is_active(first)
    second = timers.schedule(profile="tap_hold", source_key=(0, 1), due=2.000)
    assert second.generation > first.generation
    assert timers.is_active(second)


def test_feedback_split_and_final_action_observer_boundary() -> None:
    emissions = (
        SequenceEmission("suppress", action="KC_LSFT", source="combo"),
        SequenceEmission("press", action="KC_A", source="matrix"),
        SequenceEmission("tap", action="KC_B", source="morse"),
        SequenceEmission("restore", action="KC_LSFT", source="combo"),
        SequenceEmission("feedback", feedback={"phase": "commit"}, source="morse"),
        SequenceEmission("cancel", reason="reset", source="sequence"),
    )
    host, feedback = split_host_and_feedback(emissions)
    assert [emission.kind for emission in host] == ["suppress", "press", "tap", "restore"]
    assert [emission.kind for emission in feedback] == ["feedback", "cancel"]
    assert FINAL_ACTION_OBSERVER_KINDS == frozenset({"tap", "press", "release"})
    assert [emission.action for emission in final_action_observer_emissions(emissions)] == ["KC_A", "KC_B"]


def main() -> None:
    test_host_and_feedback_boundaries()
    test_required_action_validation()
    test_ordering_keeps_suppress_before_press_and_restore_after_tap()
    test_sequence_timer_identity_and_result_validation()
    test_pressed_action_pins_release_owner_and_guards_double_release()
    test_suppression_ledger_reference_count_and_physical_release_rule()
    test_timer_registry_invalidates_stale_timeouts()
    test_feedback_split_and_final_action_observer_boundary()
    print("ok: sequence engine primitives")


if __name__ == "__main__":
    main()
