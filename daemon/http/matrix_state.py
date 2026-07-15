"""Helpers for HTTP internal matrix key tester state."""
from __future__ import annotations

from typing import Any


def normalize_pressed_matrix(raw: Any) -> list[list[int]]:
    """Validate and normalize ``[[row, col], ...]`` from logicd."""
    if not isinstance(raw, list):
        raise ValueError(f"pressed must be a list: {type(raw).__name__}")

    pressed: set[tuple[int, int]] = set()
    for idx, item in enumerate(raw):
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError(f"pressed[{idx}] must be [row, col]")
        row = int(item[0])
        col = int(item[1])
        if row < 0 or col < 0:
            raise ValueError(f"pressed[{idx}] must be non-negative: row={row} col={col}")
        pressed.add((row, col))
    return [[row, col] for row, col in sorted(pressed)]
