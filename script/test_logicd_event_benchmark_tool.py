#!/usr/bin/env python3
"""Regression checks for the logicd event benchmark helper."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import logicd_event_benchmark as bench  # noqa: E402


def main() -> None:
    assert bench.matrix_packet("P", 7, 10) == b"P7A\x00"
    assert bench.matrix_packet("R", 0, 15) == b"R0F\x00"
    for bad in [-1, 16]:
        try:
            bench.matrix_packet("P", bad, 0)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid row: {bad}")
    try:
        bench.matrix_packet("X", 0, 0)
    except ValueError:
        pass
    else:
        raise AssertionError("accepted invalid event kind")

    source = (ROOT / "tools" / "logicd_event_benchmark.py").read_text(encoding="utf-8")
    assert "temporary action" in source
    assert "KC_CONNAUTO" in source
    assert "KC_SH3" in source
    assert "--rate-hz" in source
    assert "--no-restore" in source
    assert "restore_result" in source

    print("ok: logicd event benchmark helper")


if __name__ == "__main__":
    main()
