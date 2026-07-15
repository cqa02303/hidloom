#!/usr/bin/env python3
"""Regression checks for real-device smoke script matrix cleanup."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _script(name: str) -> str:
    return (ROOT / "script" / name).read_text(encoding="utf-8")


def main() -> None:
    lighting = _script("test_lighting_key_runtime.py")
    assert 'send_matrix_event(args.matrix, "P", args.row, args.col)' in lighting
    assert 'send_matrix_event(args.matrix, "R", args.row, args.col)' in lighting
    assert "finally:" in lighting

    matrix_state = _script("test_vial_matrix_state_runtime.py")
    assert '_matrix_event(args.matrix, "P", args.row, args.col)' in matrix_state
    assert '_matrix_event(args.matrix, "R", args.row, args.col)' in matrix_state
    assert "finally:" in matrix_state

    runtime_path = _script("test_vial_runtime_path.py")
    assert 'matrix_event(matrix, "P", args.row, args.col)' in runtime_path
    assert 'matrix_event(matrix, "R", args.row, args.col)' in runtime_path
    assert "finally:" in runtime_path

    print("ok: real-device smoke scripts release matrix keys")


if __name__ == "__main__":
    main()
