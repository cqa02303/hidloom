"""Feedback helpers for MORSE behavior state.

This module does not route feedback to WebSocket/OLED/LED by itself. It keeps
the payload stable so logicd and HTTP status routes can forward MORSE progress
without coupling transports to MorseBehaviorRuntime internals.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .morse_behavior import MorseBehaviorDef, MorseStepResult


@dataclass(frozen=True)
class MorseFeedbackEvent:
    """Transport-neutral feedback event for MORSE input."""

    name: str
    phase: str
    sequence: str
    stroke: str = ""
    action: str | None = None
    pending_action: str | None = None
    reason: str = ""
    canceled: bool = False
    fallback: bool = False
    needs_timeout: bool = False
    row: int | None = None
    col: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "morse",
            "name": self.name,
            "phase": self.phase,
            "sequence": self.sequence,
            "stroke": self.stroke,
            "action": self.action,
            "pending_action": self.pending_action,
            "reason": self.reason,
            "canceled": self.canceled,
            "fallback": self.fallback,
            "needs_timeout": self.needs_timeout,
            "row": self.row,
            "col": self.col,
        }


def feedback_from_step(
    name: str,
    result: MorseStepResult,
    *,
    row: int | None = None,
    col: int | None = None,
) -> MorseFeedbackEvent:
    """Build feedback from a MorseStepResult."""
    fallback = result.reason.startswith("fallback_")
    if result.committed_action is not None:
        phase = "fallback" if fallback else "commit"
    elif result.canceled:
        phase = "cancel"
    elif result.needs_timeout:
        phase = "pending"
    else:
        phase = "idle"
    return MorseFeedbackEvent(
        name=name,
        phase=phase,
        sequence=result.sequence,
        stroke=result.stroke,
        action=result.committed_action,
        pending_action=result.pending_action,
        reason=result.reason,
        canceled=result.canceled,
        fallback=fallback,
        needs_timeout=result.needs_timeout,
        row=row,
        col=col,
    )


def feedback_for_press(name: str, *, row: int | None = None, col: int | None = None) -> MorseFeedbackEvent:
    """Build feedback for MORSE key press start."""
    return MorseFeedbackEvent(name=name, phase="press", sequence="", row=row, col=col)


def feedback_for_reset(name: str) -> MorseFeedbackEvent:
    """Build feedback for config reload / reset clearing pending MORSE state."""
    return MorseFeedbackEvent(name=name, phase="reset", sequence="")


def behavior_feedback_schema(definition: MorseBehaviorDef) -> dict[str, Any]:
    """Return behavior-level feedback metadata."""
    return {
        "name": definition.name,
        "dot_threshold": definition.dot_threshold,
        "sequence_timeout": definition.sequence_timeout,
        "max_depth": definition.max_depth,
        "force_commit": sorted(definition.force_commit_sequences),
        "fallback_action": definition.fallback_action,
        "map_size": len(definition.actions),
    }
