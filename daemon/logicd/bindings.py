"""Config parsing for matrix-backed input bindings."""
from __future__ import annotations

import logging
from collections.abc import Callable

from .encoder import EncoderBinding
from .joystick import JoystickBinding

log = logging.getLogger(__name__)

MatrixRangeCheck = Callable[[int, int], bool]


def load_encoder_bindings(raw_items: object, matrix_in_range: MatrixRangeCheck) -> list[EncoderBinding]:
    bindings: list[EncoderBinding] = []
    if not isinstance(raw_items, list):
        log.warning("encoders ignored: expected list, got %s", type(raw_items).__name__)
        return bindings

    for idx, item in enumerate(raw_items):
        try:
            if not isinstance(item, dict):
                raise ValueError(f"entry must be object, got {type(item).__name__}")
            a_raw = item["a"]
            b_raw = item["b"]
            if not isinstance(a_raw, list) or len(a_raw) != 2:
                raise ValueError(f"invalid a coordinate: {a_raw!r}")
            if not isinstance(b_raw, list) or len(b_raw) != 2:
                raise ValueError(f"invalid b coordinate: {b_raw!r}")
            a = (int(a_raw[0]), int(a_raw[1]))
            b = (int(b_raw[0]), int(b_raw[1]))
            if not matrix_in_range(*a) or not matrix_in_range(*b):
                raise ValueError(f"matrix out of range: a={a} b={b}")
            bindings.append(
                EncoderBinding(
                    name=str(item.get("name") or f"encoder{idx}"),
                    a=a,
                    b=b,
                    resolution=max(1, int(item.get("resolution", 4))),
                    reverse=bool(item.get("reverse", False)),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            log.warning("encoder ignored: index=%d error=%s item=%r", idx, exc, item)

    if bindings:
        log.info("Loaded %d matrix encoder(s): %s", len(bindings), bindings)
    return bindings


def load_joystick_bindings(raw_items: object, matrix_in_range: MatrixRangeCheck) -> list[JoystickBinding]:
    bindings: list[JoystickBinding] = []
    if not isinstance(raw_items, list):
        log.warning("joysticks ignored: expected list, got %s", type(raw_items).__name__)
        return bindings

    for idx, item in enumerate(raw_items):
        try:
            if not isinstance(item, dict):
                raise ValueError(f"entry must be object, got {type(item).__name__}")

            def coord(name: str) -> tuple[int, int]:
                raw = item[name]
                if not isinstance(raw, list) or len(raw) != 2:
                    raise ValueError(f"invalid {name} coordinate: {raw!r}")
                parsed = (int(raw[0]), int(raw[1]))
                if not matrix_in_range(*parsed):
                    raise ValueError(f"matrix out of range: {name}={parsed}")
                return parsed

            press_threshold = int(item.get("press_threshold", 35))
            release_threshold = int(item.get("release_threshold", 20))
            if not (0 <= release_threshold <= press_threshold <= 100):
                raise ValueError(
                    "thresholds must satisfy 0 <= release_threshold <= press_threshold <= 100"
                )
            bindings.append(
                JoystickBinding(
                    name=str(item.get("name") or f"stick{idx}"),
                    up=coord("up"),
                    down=coord("down"),
                    left=coord("left"),
                    right=coord("right"),
                    axis_max=max(1, int(item.get("axis_max", 32767))),
                    press_threshold=press_threshold,
                    release_threshold=release_threshold,
                    mouse_deadzone=max(0, min(100, int(item.get("mouse_deadzone", 8)))),
                    cursor_max=max(1, min(127, int(item.get("cursor_max", 12)))),
                    wheel_max=max(1, min(127, int(item.get("wheel_max", 6)))),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            log.warning("joystick ignored: index=%d error=%s item=%r", idx, exc, item)

    if bindings:
        log.info("Loaded %d analog joystick(s): %s", len(bindings), bindings)
    return bindings
