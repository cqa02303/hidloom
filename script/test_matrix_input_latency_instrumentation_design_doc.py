#!/usr/bin/env python3
"""Static checks for matrix input latency instrumentation design documentation."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = (
    ROOT
    / "docs"
    / "daemon"
    / "specs"
    / "matrixd"
    / "input-latency-instrumentation-design.md"
)


def main() -> None:
    text = DOC.read_text(encoding="utf-8")
    required_phrases = [
        "matrixd -> logicd -> output backend",
        "v=2",
        "mixed-version",
        "event_id",
        "matrix_input_monotonic_ns",
        "logicd_receive_monotonic_ns",
        "hid_send_monotonic_ns",
        "output_backend",
        "scan_to_logicd_ms",
        "logicd_to_hid_ms",
        "matrix_to_hid_ms",
        "ring buffer",
        "threshold",
        "KC_SH8",
        "tools/matrixd_diagnostics_snapshot.py",
        "available: false",
        "legacy matrix event protocol",
        "Do not change key dispatch behavior",
    ]
    for phrase in required_phrases:
        assert phrase in text, phrase
    print("ok: matrix input latency instrumentation design keeps protocol/logging boundaries explicit")


if __name__ == "__main__":
    main()
