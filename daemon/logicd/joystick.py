"""Analog joystick mapping for logicd.

The physical ADC reader is intentionally outside logicd.  logicd receives
normalized or signed-int16 x/y samples and turns them into the keycodes assigned
to the virtual stick matrix positions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

from .hid_report import (
    KEYCODE,
    MOUSE_MS_D,
    MOUSE_MS_L,
    MOUSE_MS_R,
    MOUSE_MS_U,
    MOUSE_WH_D,
    MOUSE_WH_L,
    MOUSE_WH_R,
    MOUSE_WH_U,
    MouseState,
)

Direction = Literal["up", "down", "left", "right"]
ActionResolver = Callable[[int, int], str]

_DIRS: tuple[Direction, ...] = ("up", "down", "left", "right")
_MOUSE_CODES = {
    MOUSE_MS_U,
    MOUSE_MS_D,
    MOUSE_MS_L,
    MOUSE_MS_R,
    MOUSE_WH_U,
    MOUSE_WH_D,
    MOUSE_WH_L,
    MOUSE_WH_R,
}
_MOUSE_ACTION_ALIASES = {
    "MS_UP": "KC_MS_U",
    "MS_DOWN": "KC_MS_D",
    "MS_LEFT": "KC_MS_L",
    "MS_RGHT": "KC_MS_R",
    "MS_RIGHT": "KC_MS_R",
    "MS_WHLU": "KC_WH_U",
    "MS_WHLD": "KC_WH_D",
    "MS_WHLL": "KC_WH_L",
    "MS_WHLR": "KC_WH_R",
}


@dataclass(frozen=True)
class JoystickBinding:
    name: str
    up: tuple[int, int]
    down: tuple[int, int]
    left: tuple[int, int]
    right: tuple[int, int]
    axis_max: int = 32767
    press_threshold: int = 35
    release_threshold: int = 20
    mouse_deadzone: int = 8
    cursor_max: int = 12
    wheel_max: int = 6

    def coord(self, direction: Direction) -> tuple[int, int]:
        return getattr(self, direction)


@dataclass(frozen=True)
class JoystickKeyEvent:
    name: str
    direction: Direction
    row: int
    col: int
    action: str
    is_press: bool


@dataclass(frozen=True)
class JoystickMouseEvent:
    name: str
    report: bytes
    dx: int
    dy: int
    wheel: int


@dataclass
class JoystickResult:
    key_events: list[JoystickKeyEvent] = field(default_factory=list)
    mouse_event: JoystickMouseEvent | None = None


class _StickState:
    def __init__(self, binding: JoystickBinding) -> None:
        self.binding = binding
        self.held_actions: dict[Direction, str] = {}
        self.mouse = MouseState()
        self.last_raw_x = 0
        self.last_raw_y = 0
        self.last_x = 0
        self.last_y = 0
        self.last_values: dict[Direction, int] = {direction: 0 for direction in _DIRS}


class JoystickManager:
    def __init__(self, bindings: list[JoystickBinding] | None = None) -> None:
        self._states = [_StickState(binding) for binding in (bindings or [])]

    @property
    def bindings(self) -> list[JoystickBinding]:
        return [state.binding for state in self._states]

    def process(self, index: int, x: int, y: int, resolver: ActionResolver) -> JoystickResult:
        if index < 0 or index >= len(self._states):
            raise IndexError(f"joystick index out of range: {index}")
        state = self._states[index]
        binding = state.binding
        values = _direction_values(x, y, binding.axis_max)
        state.last_raw_x = x
        state.last_raw_y = y
        state.last_x = _to_percent(x, binding.axis_max)
        state.last_y = _to_percent(y, binding.axis_max)
        state.last_values = values
        result = JoystickResult()
        dx = dy = wheel = 0

        for direction in _DIRS:
            row, col = binding.coord(direction)
            action = resolver(row, col)
            code = _mouse_code(action)
            value = values[direction]
            if code in _MOUSE_CODES:
                mdx, mdy, mwheel = _mouse_delta(code, value, binding)
                dx += mdx
                dy += mdy
                wheel += mwheel
                continue

            held = direction in state.held_actions
            if held:
                if value <= binding.release_threshold:
                    held_action = state.held_actions.pop(direction)
                    result.key_events.append(
                        JoystickKeyEvent(binding.name, direction, row, col, held_action, False)
                    )
            elif value >= binding.press_threshold:
                state.held_actions[direction] = action
                result.key_events.append(
                    JoystickKeyEvent(binding.name, direction, row, col, action, True)
                )

        if dx or dy or wheel:
            report = state.mouse.build_move(dx, dy, wheel)
            result.mouse_event = JoystickMouseEvent(binding.name, report, dx, dy, wheel)
        return result

    def status(self, resolver: ActionResolver | None = None) -> dict:
        sticks = []
        for index, state in enumerate(self._states):
            binding = state.binding
            directions = []
            for direction in _DIRS:
                row, col = binding.coord(direction)
                action = resolver(row, col) if resolver is not None else ""
                code = _mouse_code(action)
                value = int(state.last_values.get(direction, 0))
                if code in _MOUSE_CODES:
                    active = value > binding.mouse_deadzone
                else:
                    active = value >= binding.press_threshold
                directions.append({
                    "direction": direction,
                    "row": row,
                    "col": col,
                    "value": value,
                    "active": active,
                    "held": direction in state.held_actions,
                    "action": action,
                })
            sticks.append({
                "index": index,
                "name": binding.name,
                "x": state.last_x,
                "y": state.last_y,
                "raw_x": state.last_raw_x,
                "raw_y": state.last_raw_y,
                "directions": directions,
            })
        return {
            "schema": "joystick.runtime_status.v1",
            "source": "logicd.joysticks",
            "save_payload_includes_runtime_state": False,
            "sticks": sticks,
        }


def _direction_values(x: int, y: int, axis_max: int) -> dict[Direction, int]:
    nx = _to_percent(x, axis_max)
    ny = _to_percent(y, axis_max)
    return {
        "up": max(0, -ny),
        "down": max(0, ny),
        "left": max(0, -nx),
        "right": max(0, nx),
    }


def _to_percent(value: int, axis_max: int) -> int:
    if -100 <= value <= 100:
        return max(-100, min(100, value))
    axis = max(1, int(axis_max))
    return max(-100, min(100, round(value * 100 / axis)))


def _mouse_code(action: str) -> int | None:
    return KEYCODE.get(_MOUSE_ACTION_ALIASES.get(action, action))


def _scaled(value: int, deadzone: int, limit: int) -> int:
    if value <= deadzone:
        return 0
    span = max(1, 100 - deadzone)
    delta = round((value - deadzone) * max(1, limit) / span)
    return max(1, min(127, delta))


def _accelerated_cursor_scaled(value: int, deadzone: int, limit: int) -> int:
    if value <= deadzone:
        return 0
    span = max(1, 100 - deadzone)
    progress = min(1.0, max(0.0, (value - deadzone) / span))
    delta = round(max(1, limit) * 2 * progress * progress)
    return max(1, min(127, delta))


def _mouse_delta(code: int, value: int, binding: JoystickBinding) -> tuple[int, int, int]:
    move = _accelerated_cursor_scaled(value, binding.mouse_deadzone, binding.cursor_max)
    wheel = _scaled(value, binding.mouse_deadzone, binding.wheel_max)
    if code == MOUSE_MS_U:
        return 0, -move, 0
    if code == MOUSE_MS_D:
        return 0, move, 0
    if code == MOUSE_MS_L:
        return -move, 0, 0
    if code == MOUSE_MS_R:
        return move, 0, 0
    if code == MOUSE_WH_U:
        return 0, 0, wheel
    if code == MOUSE_WH_D:
        return 0, 0, -wheel
    if code == MOUSE_WH_L:
        return 0, 0, -wheel
    if code == MOUSE_WH_R:
        return 0, 0, wheel
    return 0, 0, 0
