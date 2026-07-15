"""Matrix-backed rotary encoder decoding for logicd."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class EncoderBinding:
    name: str
    a: tuple[int, int]
    b: tuple[int, int]
    resolution: int = 4
    reverse: bool = False


@dataclass(frozen=True)
class EncoderEvent:
    index: int
    name: str
    direction: str
    row: int
    col: int


class EncoderState:
    """Decode quadrature transitions from two debounced matrix positions."""

    _TRANSITIONS = {
        (0b00, 0b01): 1,
        (0b01, 0b11): 1,
        (0b11, 0b10): 1,
        (0b10, 0b00): 1,
        (0b00, 0b10): -1,
        (0b10, 0b11): -1,
        (0b11, 0b01): -1,
        (0b01, 0b00): -1,
    }

    def __init__(self, binding: EncoderBinding) -> None:
        self.binding = binding
        self.a_pressed = False
        self.b_pressed = False
        self.state = 0
        self.accumulator = 0

    def process(self, row: int, col: int, is_press: bool) -> str | None:
        if (row, col) == self.binding.a:
            self.a_pressed = is_press
        elif (row, col) == self.binding.b:
            self.b_pressed = is_press
        else:
            return None

        new_state = (int(self.a_pressed) << 1) | int(self.b_pressed)
        if new_state == self.state:
            return None

        delta = self._TRANSITIONS.get((self.state, new_state))
        self.state = new_state
        if delta is None:
            self.accumulator = 0
            return "invalid"

        self.accumulator += -delta if self.binding.reverse else delta
        threshold = max(1, int(self.binding.resolution))
        if self.accumulator >= threshold:
            self.accumulator = 0
            return "cw"
        if self.accumulator <= -threshold:
            self.accumulator = 0
            return "ccw"
        return None


class EncoderManager:
    def __init__(self, bindings: Iterable[EncoderBinding] = ()) -> None:
        self.states = [EncoderState(binding) for binding in bindings]
        self.positions: dict[tuple[int, int], int] = {}
        for idx, state in enumerate(self.states):
            self.positions[state.binding.a] = idx
            self.positions[state.binding.b] = idx

    def handles(self, row: int, col: int) -> bool:
        return (row, col) in self.positions

    def process(self, row: int, col: int, is_press: bool) -> EncoderEvent | str | None:
        idx = self.positions.get((row, col))
        if idx is None:
            return None
        state = self.states[idx]
        direction = state.process(row, col, is_press)
        if direction in (None, "invalid"):
            return direction
        target = state.binding.a if direction == "cw" else state.binding.b
        return EncoderEvent(
            index=idx,
            name=state.binding.name,
            direction=direction,
            row=target[0],
            col=target[1],
        )
