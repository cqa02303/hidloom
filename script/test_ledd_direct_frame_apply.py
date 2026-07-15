#!/usr/bin/env python3
"""Regression tests for applying direct-frame packets to ledd's LED buffer."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from ledd.direct_frame import DirectFrameFormat, decode_direct_frame, encode_direct_frame  # noqa: E402
from ledd.ledd import AnimationManager  # noqa: E402
from ledd.strip import Color  # noqa: E402
from vialrgb_effects import VIALRGB_EFFECT_SEQUENCE, VIALRGB_EFFECTS  # noqa: E402


class FakeStrip:
    def __init__(self, n: int) -> None:
        self.pixels = [0] * n
        self.show_count = 0

    def setPixelColor(self, idx: int, color: int) -> None:
        self.pixels[idx] = color

    def show(self) -> None:
        self.show_count += 1


def make_manager(led_count: int = 2) -> AnimationManager:
    positions = {f"0,{idx}": {"x": idx, "y": 0} for idx in range(led_count)}
    return AnimationManager(FakeStrip(led_count), led_count, {"leds": positions}, positions)


def main() -> None:
    manager = make_manager(2)
    strip = manager._raw_strip

    packet = encode_direct_frame(
        frame_id=1,
        led_count=2,
        payload=bytes([10, 20, 30, 40, 50, 60]),
        format=DirectFrameFormat.RGB,
    )
    manager.apply_direct_frame(decode_direct_frame(packet, expected_led_count=2))
    assert strip.pixels == [Color(10, 20, 30), Color(40, 50, 60)]
    assert strip.show_count == 1
    assert manager._direct_frame_active is True
    assert manager._direct_frame_last_id == 1
    assert manager.direct_frame_runtime_status()["applied_frames"] == 1
    assert manager.direct_frame_runtime_status()["ignored_frames"] == 0

    # Stale frames must not rewind the displayed frame.
    stale = encode_direct_frame(
        frame_id=1,
        led_count=2,
        payload=bytes([1, 1, 1, 2, 2, 2]),
        format=DirectFrameFormat.RGB,
    )
    manager.apply_direct_frame(decode_direct_frame(stale, expected_led_count=2))
    assert strip.pixels == [Color(10, 20, 30), Color(40, 50, 60)]
    assert strip.show_count == 1
    assert manager.direct_frame_runtime_status()["ignored_frames"] == 1

    # GRB packet payload is normalized before applying.
    grb = encode_direct_frame(
        frame_id=2,
        led_count=2,
        payload=bytes([20, 10, 30, 50, 40, 60]),
        format=DirectFrameFormat.GRB,
    )
    manager.apply_direct_frame(decode_direct_frame(grb, expected_led_count=2))
    assert strip.pixels == [Color(10, 20, 30), Color(40, 50, 60)]
    assert strip.show_count == 2
    assert manager._direct_frame_last_id == 2
    assert manager.direct_frame_runtime_status()["applied_frames"] == 2

    # A mismatched LED count is ignored defensively even though socket decode
    # should normally reject it before this point.
    other = make_manager(3)
    bad = decode_direct_frame(
        encode_direct_frame(frame_id=3, led_count=2, payload=bytes([7, 8, 9, 10, 11, 12])),
    )
    other.apply_direct_frame(bad)
    assert other._raw_strip.show_count == 0
    assert other._direct_frame_last_id is None
    assert other.direct_frame_runtime_status()["ignored_frames"] == 1

    # Direct Multisplash keeps direct-frame video as the base layer and adds
    # key-triggered splash on top instead of forcing plain Direct Control.
    overlay = make_manager(2)
    overlay_strip = overlay._raw_strip
    overlay_strip.pixels = [Color(1, 2, 3), Color(4, 5, 6)]
    overlay.apply_vialrgb(1002, 128, 0, 255, 128)
    assert VIALRGB_EFFECTS[1002] == "Direct Multisplash"
    assert 1002 not in VIALRGB_EFFECT_SEQUENCE
    assert overlay.direct_frame_runtime_status()["overlay"] == "multisplash"
    assert overlay_strip.pixels == [Color(0, 0, 0), Color(0, 0, 0)]

    black = encode_direct_frame(
        frame_id=1,
        led_count=2,
        payload=bytes([0, 0, 0, 0, 0, 0]),
        format=DirectFrameFormat.RGB,
    )
    overlay.apply_direct_frame(decode_direct_frame(black, expected_led_count=2))
    assert overlay._vialrgb_mode == 1002
    assert overlay_strip.pixels == [Color(0, 0, 0), Color(0, 0, 0)]

    overlay.on_key_event(0, 0, True)
    assert overlay_strip.pixels[0] != Color(0, 0, 0)
    assert overlay_strip.pixels[1] != Color(0, 0, 0)

    print("ok: ledd direct frame apply")


if __name__ == "__main__":
    main()
