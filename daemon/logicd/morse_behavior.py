"""Timed tap / Morse-style behavior core.

This module intentionally stays separate from tap dance.  It converts press
lengths into dot / dash strokes and resolves a variable-depth sequence map into
a tap action. InteractionEngine invokes it through the dedicated ``MORSE(name)``
action without coupling Morse state to tap-count based tap dance state.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

MORSE_ACTION_RE = re.compile(r"^MORSE\(([^\)]+)\)$")
INVALID_MORSE_ACTIONS = {"", "KC_NO", "KC_NONE", "NO", "NONE"}


@dataclass(frozen=True)
class MorseBehaviorDef:
    """One timed tap / Morse behavior definition."""

    name: str
    actions: dict[str, str]
    dot_threshold: float = 0.180
    sequence_timeout: float = 0.700
    max_depth: int = 4
    force_commit_sequences: frozenset[str] = frozenset()
    fallback_action: str | None = None

    def __post_init__(self) -> None:
        if self.dot_threshold <= 0:
            raise ValueError("dot_threshold must be positive")
        if self.sequence_timeout <= 0:
            raise ValueError("sequence_timeout must be positive")
        if self.max_depth < 1:
            raise ValueError("max_depth must be >= 1")
        for sequence in self.actions:
            self._validate_sequence(sequence)
        for sequence in self.force_commit_sequences:
            self._validate_sequence(sequence)
            if sequence not in self.actions:
                raise ValueError(f"force-commit morse sequence has no action: {sequence!r}")

    def _validate_sequence(self, sequence: str) -> None:
        if not is_valid_sequence(sequence):
            raise ValueError(f"invalid morse sequence: {sequence!r}")
        if len(sequence) > self.max_depth:
            raise ValueError(f"morse sequence exceeds max_depth: {sequence!r}")

    def action_for(self, sequence: str) -> str | None:
        """Return action for sequence, treating empty / KC_NONE as cancel."""
        return normalize_action(self.actions.get(sequence))

    def fallback_for_cancel(self) -> str | None:
        """Return fallback action for unmapped/canceled Morse input."""
        return normalize_action(self.fallback_action)

    def has_prefix(self, sequence: str) -> bool:
        """Return whether any longer configured sequence starts with sequence."""
        return any(candidate != sequence and candidate.startswith(sequence) for candidate in self.actions)

    def is_force_commit(self, sequence: str) -> bool:
        """Return whether a matched sequence must commit even when it has children."""
        return sequence in self.force_commit_sequences

    @property
    def terminal_sequences(self) -> frozenset[str]:
        """Backward-compatible alias for the old terminal name."""
        return self.force_commit_sequences


def normalize_action(action: Any) -> str | None:
    """Normalize optional action strings, treating KC_NO/KC_NONE as no action."""
    if action is None:
        return None
    text = str(action).strip()
    if text.upper() in INVALID_MORSE_ACTIONS:
        return None
    return text


def is_valid_sequence(sequence: str) -> bool:
    """Return true when sequence is made only of dot / dash strokes."""
    return bool(sequence) and all(ch in ".-" for ch in sequence)


def parse_morse_action(action: str) -> str | None:
    """Parse ``MORSE(name)`` action strings."""
    match = MORSE_ACTION_RE.match(action.strip())
    if not match:
        return None
    name = match.group(1).strip()
    return name or None


def normalize_morse_behaviors(raw: Any) -> dict[str, MorseBehaviorDef]:
    """Normalize permissive config into behavior definitions.

    Accepted shape:

    ``{"main": {"dot_threshold": 0.18, "sequence_timeout": 0.7,
    "max_depth": 4, "force_commit": [".-"], "fallback_action": "KC_ESC",
    "map": {".": "KC_E"}}}``

    ``terminal`` and ``terminal_sequences`` are accepted as compatibility
    aliases, but new configs should use ``force_commit``.
    """
    if not isinstance(raw, dict):
        return {}
    result: dict[str, MorseBehaviorDef] = {}
    for name_raw, entry in raw.items():
        name = str(name_raw).strip()
        if not name:
            continue
        if isinstance(entry, dict) and isinstance(entry.get("map"), dict):
            actions_raw = entry.get("map", {})
            dot_threshold = _float(entry.get("dot_threshold"), 0.180)
            sequence_timeout = _float(entry.get("sequence_timeout"), 0.700)
            max_depth = _int(entry.get("max_depth"), 4)
            force_commit_sequences = _sequence_set(_force_commit_raw(entry))
            fallback_action = normalize_action(entry.get("fallback_action"))
        elif isinstance(entry, dict):
            actions_raw = entry
            dot_threshold = 0.180
            sequence_timeout = 0.700
            max_depth = max([len(str(seq)) for seq in entry] + [1])
            force_commit_sequences = frozenset()
            fallback_action = None
        else:
            continue
        actions = {
            str(sequence).strip(): str(action).strip()
            for sequence, action in actions_raw.items()
            if is_valid_sequence(str(sequence).strip())
        }
        if not actions:
            continue
        try:
            result[name] = MorseBehaviorDef(
                name=name,
                actions=actions,
                dot_threshold=dot_threshold,
                sequence_timeout=sequence_timeout,
                max_depth=max_depth,
                force_commit_sequences=force_commit_sequences,
                fallback_action=fallback_action,
            )
        except ValueError:
            continue
    return result


def _force_commit_raw(entry: dict[str, Any]) -> Any:
    if "force_commit" in entry:
        return entry.get("force_commit")
    if "terminal" in entry:
        return entry.get("terminal")
    return entry.get("terminal_sequences", [])


def _sequence_set(raw: Any) -> frozenset[str]:
    if raw in (None, ""):
        return frozenset()
    if isinstance(raw, str):
        items = [raw]
    elif isinstance(raw, list):
        items = raw
    else:
        return frozenset()
    return frozenset(str(item).strip() for item in items if is_valid_sequence(str(item).strip()))


def _float(raw: Any, default: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value


def _int(raw: Any, default: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value


@dataclass
class MorseState:
    """Mutable input state for one behavior instance."""

    sequence: str = ""
    generation: int = 0
    last_started_at: float | None = None
    last_released_at: float | None = None
    pending_action: str | None = None
    canceled: bool = False
    history: list[str] = field(default_factory=list)

    def clear(self) -> None:
        self.sequence = ""
        self.pending_action = None
        self.canceled = False
        self.last_started_at = None
        self.last_released_at = None
        self.history.clear()


@dataclass(frozen=True)
class MorseStepResult:
    """Result of adding one dot / dash stroke."""

    sequence: str
    stroke: str
    pending_action: str | None
    committed_action: str | None = None
    canceled: bool = False
    needs_timeout: bool = False
    reason: str = "pending"


class MorseBehaviorRuntime:
    """Resolve press durations to dot / dash sequences."""

    def __init__(self, definition: MorseBehaviorDef) -> None:
        self.definition = definition
        self.state = MorseState()

    def reset(self) -> None:
        self.state.clear()
        self.state.generation += 1

    def press(self, now: float) -> None:
        self.state.last_started_at = now

    def release(self, now: float) -> MorseStepResult:
        if self.state.last_started_at is None:
            fallback = self.definition.fallback_for_cancel()
            return MorseStepResult(
                sequence=self.state.sequence,
                stroke="",
                pending_action=self.state.pending_action,
                committed_action=fallback,
                canceled=True,
                reason="fallback_release_without_press" if fallback else "release_without_press",
            )
        duration = max(0.0, now - self.state.last_started_at)
        stroke = "." if duration <= self.definition.dot_threshold else "-"
        return self.add_stroke(stroke, now=now)

    def _cancel_result(self, sequence: str, stroke: str, reason: str) -> MorseStepResult:
        fallback = self.definition.fallback_for_cancel()
        self.reset()
        return MorseStepResult(
            sequence,
            stroke,
            None,
            committed_action=fallback,
            canceled=True,
            reason=f"fallback_{reason}" if fallback else reason,
        )

    def add_stroke(self, stroke: str, *, now: float | None = None) -> MorseStepResult:
        """Add a dot/dash stroke and resolve current state.

        Invalid or over-depth sequences cancel immediately. A valid leaf with no
        longer prefix commits immediately. A force-commit sequence commits
        immediately even when longer prefix matches exist.  If ``fallback_action``
        is configured, canceled/unmapped input emits that action as a tap.
        """
        if stroke not in {".", "-"}:
            return self._cancel_result("", stroke, "invalid_stroke")

        sequence = f"{self.state.sequence}{stroke}"
        self.state.sequence = sequence
        self.state.history.append(stroke)
        self.state.last_released_at = now
        self.state.generation += 1

        if len(sequence) > self.definition.max_depth:
            return self._cancel_result(sequence, stroke, "max_depth")

        action = self.definition.action_for(sequence)
        has_prefix = self.definition.has_prefix(sequence)
        self.state.pending_action = action

        if action is None and not has_prefix:
            return self._cancel_result(sequence, stroke, "unmapped")

        if action is not None and self.definition.is_force_commit(sequence):
            self.reset()
            return MorseStepResult(sequence, stroke, None, committed_action=action, reason="force_commit")

        if action is not None and not has_prefix:
            self.reset()
            return MorseStepResult(sequence, stroke, None, committed_action=action, reason="leaf")

        return MorseStepResult(
            sequence=sequence,
            stroke=stroke,
            pending_action=action,
            needs_timeout=True,
            reason="prefix",
        )

    def timeout(self) -> MorseStepResult:
        """Commit pending action or cancel the current sequence."""
        sequence = self.state.sequence
        action = self.state.pending_action
        if not sequence:
            return MorseStepResult("", "", None, canceled=False, reason="idle")
        fallback = self.definition.fallback_for_cancel()
        self.reset()
        if action is None:
            return MorseStepResult(
                sequence,
                "",
                None,
                committed_action=fallback,
                canceled=True,
                reason="fallback_timeout_unmapped" if fallback else "timeout_unmapped",
            )
        return MorseStepResult(sequence, "", None, committed_action=action, reason="timeout")
