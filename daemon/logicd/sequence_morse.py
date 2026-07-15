"""Morse adapter for the neutral sequence interaction primitives."""
from __future__ import annotations

from dataclasses import dataclass

from .morse_behavior import MorseBehaviorDef, MorseBehaviorRuntime
from .morse_feedback import feedback_for_press, feedback_for_reset, feedback_from_step
from .sequence_engine import SequenceEmission, SequenceProfile, SequenceResult, SequenceStep, SequenceTimerRef


@dataclass
class MorseSequenceProfile(SequenceProfile):
    """Wrap MorseBehaviorRuntime behind the SequenceProfile interface."""

    definition: MorseBehaviorDef

    def __post_init__(self) -> None:
        self.name = f"morse:{self.definition.name}"
        self.runtime = MorseBehaviorRuntime(self.definition)

    def handle_step(self, step: SequenceStep) -> SequenceResult:
        """Process one Morse step without changing existing live dispatch."""
        if step.kind == "press":
            self.runtime.press(step.now)
            return SequenceResult(emissions=(
                _feedback_emission(feedback_for_press(self.definition.name, row=step.row, col=step.col)),
            ))

        if step.kind == "release":
            result = self.runtime.release(step.now)
            emissions: list[SequenceEmission] = []
            if result.committed_action is not None:
                emissions.append(SequenceEmission(
                    "tap",
                    action=result.committed_action,
                    source="morse",
                    row=step.row,
                    col=step.col,
                ))
            emissions.append(_feedback_emission(feedback_from_step(
                self.definition.name,
                result,
                row=step.row,
                col=step.col,
            )))
            timer = None
            if result.needs_timeout:
                timer = SequenceTimerRef(
                    profile=self.name,
                    source_key=_source_key(step),
                    generation=self.runtime.state.generation,
                    due=step.now + self.definition.sequence_timeout,
                )
            sequence_result = SequenceResult(emissions=tuple(emissions), timer=timer)
            sequence_result.validate()
            return sequence_result

        if step.kind == "timeout":
            result = self.runtime.timeout()
            emissions = []
            if result.committed_action is not None:
                emissions.append(SequenceEmission(
                    "tap",
                    action=result.committed_action,
                    source="morse",
                    row=step.row,
                    col=step.col,
                ))
            emissions.append(_feedback_emission(feedback_from_step(
                self.definition.name,
                result,
                row=step.row,
                col=step.col,
            )))
            sequence_result = SequenceResult(emissions=tuple(emissions))
            sequence_result.validate()
            return sequence_result

        if step.kind == "reset":
            self.runtime.reset()
            return SequenceResult(emissions=(
                _feedback_emission(feedback_for_reset(self.definition.name)),
            ))

        return SequenceResult(emissions=(
            SequenceEmission("cancel", source="morse", reason=f"unsupported_{step.kind}"),
        ))


def _source_key(step: SequenceStep) -> tuple[int, int] | None:
    if step.row is None or step.col is None:
        return None
    return (step.row, step.col)


def _feedback_emission(event: object) -> SequenceEmission:
    return SequenceEmission("feedback", source="morse", feedback=event.to_dict())  # type: ignore[attr-defined]

