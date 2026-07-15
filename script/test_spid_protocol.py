#!/usr/bin/env python3
"""Regression tests for spid JSON Lines protocol."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from spid.protocol import MotionEvent, StatusEvent, decode_event, decode_motion, encode_event  # noqa: E402


def main() -> None:
    motion = MotionEvent(dx=3, dy=-2, wheel=1, buttons=4, sensor="mock")
    encoded = encode_event(motion)
    assert encoded.endswith(b"\n")
    payload = decode_event(encoded)
    assert payload == {"t": "motion", "dx": 3, "dy": -2, "wheel": 1, "buttons": 4, "sensor": "mock"}
    decoded = decode_motion(encoded)
    assert decoded == motion
    assert MotionEvent().is_zero()
    assert not motion.is_zero()

    status = StatusEvent(sensor="PAW3805EK", ok=True, msg="ready", cpi=800)
    payload = decode_event(encode_event(status))
    assert payload["t"] == "status"
    assert payload["sensor"] == "PAW3805EK"
    assert payload["ok"] is True
    assert payload["cpi"] == 800

    try:
        decode_motion(encode_event(status))
    except ValueError as exc:
        assert "expected motion" in str(exc)
    else:
        raise AssertionError("status should not decode as motion")

    print("ok: spid protocol")


if __name__ == "__main__":
    main()
