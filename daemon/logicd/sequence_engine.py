"""Neutral sequence interaction primitives.

This module intentionally does not dispatch HID events.  It defines the small
emission vocabulary shared by profile adapters such as Morse without coupling
those profiles to the live InteractionEngine output implementation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

SequenceEmissionKind = Literal[
    "tap",
    "press",
    "release",
    "suppress",
    "restore",
    "feedback",
    "cancel",
]

_ORDER_RANK: dict[SequenceEmissionKind, int] = {
    "suppress": 10,
    "release": 20,
    "press": 30,
    "tap": 40,
    "restore": 50,
    "feedback": 60,
    "cancel": 70,
}

HOST_EMISSION_KINDS: frozenset[SequenceEmissionKind] = frozenset({
    "tap",
    "press",
    "release",
    "suppress",
    "restore",
})

NON_HOST_EMISSION_KINDS: frozenset[SequenceEmissionKind] = frozenset({
    "feedback",
    "cancel",
})

FINAL_ACTION_OBSERVER_KINDS: frozenset[SequenceEmissionKind] = frozenset({
    "tap",
    "press",
    "release",
})

SequenceInputKind = Literal["press", "release", "timeout", "interrupt", "reset"]


@dataclass(frozen=True)
class SequenceTimerRef:
    """Timer identity for stale-timeout safe profile scheduling."""

    profile: str
    source_key: tuple[int, int] | None
    generation: int
    due: float

    def matches(self, *, profile: str, source_key: tuple[int, int] | None, generation: int) -> bool:
        """Return whether a timer still belongs to the active state."""
        return self.profile == profile and self.source_key == source_key and self.generation == generation


@dataclass(frozen=True)
class SequenceStep:
    """Input event delivered to a sequence profile."""

    kind: SequenceInputKind
    now: float
    row: int | None = None
    col: int | None = None


@dataclass(frozen=True)
class SequenceResult:
    """Profile output: ordered emissions plus an optional next timer."""

    emissions: tuple[SequenceEmission, ...] = ()
    timer: SequenceTimerRef | None = None

    def validate(self) -> None:
        """Validate emission ordering and timer identity shape."""
        validate_emission_batch(list(self.emissions))
        if self.timer is not None and self.timer.generation < 0:
            raise ValueError("sequence timer generation must be non-negative")


class SequenceProfile(Protocol):
    """Minimal adapter contract for timed interaction profiles."""

    name: str

    def handle_step(self, step: SequenceStep) -> SequenceResult:
        """Process one input step and return host-neutral emissions."""
        ...


@dataclass(frozen=True)
class SequenceEmission:
    """A side-effect request emitted by a sequence profile.

    `action` is required for host-visible emissions and omitted for feedback or
    cancel-only emissions.  `source_action` is optional metadata for
    suppression/restoration accounting; it is not a second host action.
    """

    kind: SequenceEmissionKind
    action: str | None = None
    source: str = "sequence"
    row: int | None = None
    col: int | None = None
    source_action: str | None = None
    feedback: dict[str, Any] | None = None
    reason: str | None = None

    @property
    def is_host_visible(self) -> bool:
        """Return whether this emission should be translated to host output."""
        return self.kind in HOST_EMISSION_KINDS

    def validate(self) -> None:
        """Reject internally inconsistent emissions."""
        if self.kind in HOST_EMISSION_KINDS and not self.action:
            raise ValueError(f"{self.kind} emission requires action")
        if self.kind in NON_HOST_EMISSION_KINDS and self.action is not None:
            raise ValueError(f"{self.kind} emission must not carry host action")
        if self.kind in {"suppress", "restore"} and not (self.source_action or self.action):
            raise ValueError(f"{self.kind} emission requires a source action")


@dataclass
class SequencePressedAction:
    """Pinned host action owned by one timed interaction source."""

    action: str
    source: str
    row: int | None = None
    col: int | None = None
    released: bool = False

    def release(self, *, reason: str = "owner_release") -> SequenceEmission | None:
        """Return one release for the pinned action, guarding double release."""
        if self.released:
            return None
        self.released = True
        return SequenceEmission(
            "release",
            action=self.action,
            source=self.source,
            row=self.row,
            col=self.col,
            reason=reason,
        )


@dataclass
class _SuppressionState:
    source_action: str
    owners: set[str]
    source_pressed: bool = True


class SequenceSuppressionLedger:
    """Reference-counted source suppression shared by Combo / Key Override."""

    def __init__(self) -> None:
        self._states: dict[str, _SuppressionState] = {}

    def suppress(self, source_action: str, *, owner: str) -> SequenceEmission | None:
        state = self._states.get(source_action)
        if state is None:
            self._states[source_action] = _SuppressionState(source_action, {owner})
            return SequenceEmission(
                "suppress",
                action=source_action,
                source=owner,
                source_action=source_action,
            )
        state.owners.add(owner)
        return None

    def mark_source_released(self, source_action: str) -> None:
        state = self._states.get(source_action)
        if state is not None:
            state.source_pressed = False

    def restore(self, source_action: str, *, owner: str) -> SequenceEmission | None:
        state = self._states.get(source_action)
        if state is None:
            return None
        state.owners.discard(owner)
        if state.owners:
            return None
        del self._states[source_action]
        if not state.source_pressed:
            return None
        return SequenceEmission(
            "restore",
            action=source_action,
            source=owner,
            source_action=source_action,
        )

    def active_owners(self, source_action: str) -> frozenset[str]:
        state = self._states.get(source_action)
        return frozenset() if state is None else frozenset(state.owners)


class SequenceTimerRegistry:
    """Generation registry that makes stale timeouts harmless."""

    def __init__(self) -> None:
        self._generations: dict[tuple[str, tuple[int, int] | None], int] = {}

    def schedule(
        self,
        *,
        profile: str,
        source_key: tuple[int, int] | None,
        due: float,
    ) -> SequenceTimerRef:
        key = (profile, source_key)
        generation = self._generations.get(key, 0) + 1
        self._generations[key] = generation
        return SequenceTimerRef(profile=profile, source_key=source_key, generation=generation, due=due)

    def is_active(self, timer: SequenceTimerRef) -> bool:
        generation = self._generations.get((timer.profile, timer.source_key))
        return generation is not None and timer.matches(
            profile=timer.profile,
            source_key=timer.source_key,
            generation=generation,
        )

    def invalidate(
        self,
        *,
        profile: str | None = None,
        source_key: tuple[int, int] | None = None,
    ) -> None:
        for key in list(self._generations):
            key_profile, key_source = key
            if profile is not None and key_profile != profile:
                continue
            if source_key is not None and key_source != source_key:
                continue
            self._generations[key] += 1


def emission_sort_key(emission: SequenceEmission) -> tuple[int, str, str]:
    """Stable ordering key for dispatch-safe emission batches."""
    return (
        _ORDER_RANK[emission.kind],
        emission.action or "",
        emission.source_action or "",
    )


def validate_emission_batch(emissions: list[SequenceEmission]) -> None:
    """Validate a batch and ensure it already follows the safety ordering."""
    for emission in emissions:
        emission.validate()
    expected = sorted(emissions, key=emission_sort_key)
    if emissions != expected:
        raise ValueError("sequence emissions are not in dispatch-safe order")


def split_host_and_feedback(
    emissions: list[SequenceEmission] | tuple[SequenceEmission, ...],
) -> tuple[tuple[SequenceEmission, ...], tuple[SequenceEmission, ...]]:
    """Split host-visible emissions from transport-neutral feedback/cancel data."""
    host: list[SequenceEmission] = []
    feedback: list[SequenceEmission] = []
    for emission in emissions:
        emission.validate()
        if emission.is_host_visible:
            host.append(emission)
        else:
            feedback.append(emission)
    return tuple(host), tuple(feedback)


def final_action_observer_emissions(
    emissions: list[SequenceEmission] | tuple[SequenceEmission, ...],
) -> tuple[SequenceEmission, ...]:
    """Return emissions that Repeat Key / Dynamic Macro style observers may record."""
    return tuple(emission for emission in emissions if emission.kind in FINAL_ACTION_OBSERVER_KINDS)
