#!/usr/bin/env python3
"""Regression tests for MORSE feedback LED flashes."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from ledd.ledd import AnimationManager  # noqa: E402
from ledd.logicd_client import handle_logicd_message  # noqa: E402
from ledd.strip import Color  # noqa: E402
from logicd.runtime_notifications import LogicdNotifier  # noqa: E402


class FakeStrip:
    def __init__(self, n: int) -> None:
        self.pixels = [0] * n
        self.show_count = 0

    def setPixelColor(self, idx: int, color: int) -> None:
        self.pixels[idx] = color

    def show(self) -> None:
        self.show_count += 1


class FakeWriter:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def write(self, data: bytes) -> None:
        self.messages.append(data.decode("utf-8").strip())


class FakeRuntime:
    def __init__(self) -> None:
        self.ledd_writers = [FakeWriter()]


def _make_manager() -> tuple[AnimationManager, FakeStrip]:
    positions = {
        "0,0": {"x": 0, "y": 0},
        "0,1": {"x": 1, "y": 0},
    }
    strip = FakeStrip(2)
    return AnimationManager(
        strip,
        2,
        {
            "leds": positions,
            "keycodes_by_position": {"0,0": "KC_A", "0,1": "KC_B"},
            "animation": {"default_id": 0},
        },
        positions,
    ), strip


def test_morse_feedback_direct_flash_restores_base_pixel() -> None:
    manager, strip = _make_manager()
    manager._strip.setPixelColor(1, Color(1, 2, 3))
    manager._strip.show()

    manager.on_morse_feedback({"phase": "commit", "row": 0, "col": 1, "duration": 0.03})
    assert strip.pixels[1] == Color(0, 220, 60)
    time.sleep(0.06)
    assert strip.pixels[1] == Color(1, 2, 3)


def test_logicd_morse_feedback_message_reaches_manager() -> None:
    manager, strip = _make_manager()
    handle_logicd_message('{"t":"morse_feedback","phase":"pending","row":0,"col":0,"duration":0.03}', manager)
    assert strip.pixels[0] == Color(255, 150, 0)
    time.sleep(0.06)


def test_logicd_notifier_broadcasts_morse_feedback_payload() -> None:
    runtime = FakeRuntime()
    notifier = LogicdNotifier(runtime)  # type: ignore[arg-type]
    notifier.push_ledd_morse_feedback({"phase": "cancel", "row": 0, "col": 1})
    assert json.loads(runtime.ledd_writers[0].messages[0]) == {
        "t": "morse_feedback",
        "phase": "cancel",
        "row": 0,
        "col": 1,
    }


def main() -> None:
    test_morse_feedback_direct_flash_restores_base_pixel()
    test_logicd_morse_feedback_message_reaches_manager()
    test_logicd_notifier_broadcasts_morse_feedback_payload()
    print("ok: MORSE LED feedback")


if __name__ == "__main__":
    main()
