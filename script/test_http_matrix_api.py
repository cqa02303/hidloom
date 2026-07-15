#!/usr/bin/env python3
"""Local smoke test for HTTP matrix tester validation helpers."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon" / "http"))

import matrix_state  # noqa: E402


def main() -> None:
    pressed = matrix_state.normalize_pressed_matrix([[1, 2], ["1", "2"], [0, 0]])
    assert pressed == [[0, 0], [1, 2]]

    for raw in (
        "bad",
        [[1]],
        [[-1, 0]],
        [[0, "bad"]],
    ):
        try:
            matrix_state.normalize_pressed_matrix(raw)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid matrix state accepted: {raw!r}")

    lighting_api = (ROOT / "daemon" / "http" / "lighting_api.py").read_text(encoding="utf-8")
    matrix_tester = (ROOT / "daemon" / "http" / "static" / "matrix_tester.js").read_text(encoding="utf-8")
    assert '"joystick": joystick' in lighting_api
    assert "matrixAndJoystickPressedKeys(data)" in matrix_tester
    assert "joystickPressedKeys(data?.joystick)" in matrix_tester

    print("ok: HTTP matrix tester validation is coherent")


if __name__ == "__main__":
    main()
