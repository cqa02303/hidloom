#!/usr/bin/env python3
"""Regression tests for ledd direct-frame producer disconnect fallback."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from ledd.direct_frame import decode_direct_frame, encode_direct_frame  # noqa: E402
from ledd.ledd import AnimationManager, direct_frame_fallback_policy  # noqa: E402
from ledd.strip import Color  # noqa: E402


class FakeStrip:
    def __init__(self, n: int) -> None:
        self.pixels = [0] * n
        self.show_count = 0

    def setPixelColor(self, idx: int, color: int) -> None:
        self.pixels[idx] = color

    def show(self) -> None:
        self.show_count += 1


def make_manager(policy: str) -> AnimationManager:
    positions = {f"0,{idx}": {"x": idx, "y": 0} for idx in range(2)}
    return AnimationManager(
        FakeStrip(2),
        2,
        {"leds": positions, "ipc": {"direct_frame_fallback": policy}, "animation": {"default_id": 0}},
        positions,
    )


def apply_sample(manager: AnimationManager, frame_id: int = 1) -> None:
    packet = encode_direct_frame(frame_id=frame_id, led_count=2, payload=bytes([10, 20, 30, 40, 50, 60]))
    manager.apply_direct_frame(decode_direct_frame(packet, expected_led_count=2))


def main() -> None:
    keep = make_manager("keep_last_frame")
    apply_sample(keep)
    keep.on_direct_frame_producer_disconnected()
    assert keep._direct_frame_active is True
    assert keep._direct_frame_last_id == 1
    assert keep._raw_strip.pixels == [Color(10, 20, 30), Color(40, 50, 60)]
    keep.on_direct_frame_producer_connected()
    assert keep._direct_frame_active is True
    assert keep._direct_frame_last_id is None
    apply_sample(keep, frame_id=0)
    assert keep._direct_frame_last_id == 0
    assert keep.direct_frame_runtime_status()["ignored_frames"] == 0

    off = make_manager("off")
    apply_sample(off)
    off.on_direct_frame_producer_disconnected()
    assert off._direct_frame_active is False
    assert off._direct_frame_last_id is None
    assert off._raw_strip.pixels == [0, 0]

    restore = make_manager("restore_default")
    apply_sample(restore)
    called: list[int] = []

    def fake_switch(anim_id: int) -> bool:
        called.append(anim_id)
        restore._current_id = anim_id
        return True

    restore.switch = fake_switch  # type: ignore[method-assign]
    restore.on_direct_frame_producer_disconnected()
    assert restore._direct_frame_active is False
    assert restore._direct_frame_last_id is None
    assert called == [0]

    assert direct_frame_fallback_policy({"ipc": {"direct_frame_fallback": "bad"}}) == "keep_last_frame"
    os.environ["LEDD_DIRECT_FRAME_FALLBACK"] = "off"
    try:
        assert direct_frame_fallback_policy({"ipc": {"direct_frame_fallback": "restore_default"}}) == "off"
    finally:
        os.environ.pop("LEDD_DIRECT_FRAME_FALLBACK", None)

    print("ok: ledd direct-frame fallback")


if __name__ == "__main__":
    main()
