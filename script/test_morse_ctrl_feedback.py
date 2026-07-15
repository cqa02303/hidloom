#!/usr/bin/env python3
"""Regression tests for MORSE_FEEDBACK ctrl command."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.ctrl import CtrlContext, process_ctrl_json  # noqa: E402


class FakeWriter:
    def __init__(self) -> None:
        self.data = b""

    def write(self, data: bytes) -> None:
        self.data += data

    async def drain(self) -> None:
        return None

    def payloads(self) -> list[dict]:
        return [json.loads(line) for line in self.data.decode().splitlines() if line]


async def noop_async(*_args, **_kwargs) -> None:
    return None


def context_with_feedback(events: list[dict] | None) -> CtrlContext:
    def drain() -> list[dict]:
        if events is None:
            return []
        drained = list(events)
        events.clear()
        return drained

    return CtrlContext(
        matrix_in_range=lambda row, col: True,
        handle_analog_stick=noop_async,
        layers=None,
        current_hid_mode="auto",
        current_output_target="auto",
        pressed_matrix=set(),
        save_runtime_keymap=lambda: "ok",
        reset_runtime_keymap=lambda: {},
        led_state={},
        normalize_led_state=lambda raw: {},
        load_led_state=lambda: None,
        save_led_state=lambda: "ok",
        cancel_led_state_save=lambda: None,
        push_ledd_vialrgb_direct=lambda first, pixels: None,
        push_ledd_vialrgb_direct_pattern=lambda pattern, fps, brightness: None,
        normalize_vialrgb_mode=lambda mode: mode,
        remember_nonzero_led_mode=lambda: None,
        push_ledd_vialrgb=lambda: None,
        schedule_led_state_save=lambda: None,
        notify_i2cd_led_effect_if_changed=lambda prev, cur: None,
        drain_morse_feedback=drain if events is not None else None,
    )


async def test_morse_feedback_ctrl_drains_events() -> None:
    events = [{"type": "morse", "phase": "pending", "sequence": "."}]
    writer = FakeWriter()
    await process_ctrl_json('{"t":"MORSE_FEEDBACK"}', context_with_feedback(events), writer)
    payload = writer.payloads()[0]
    assert payload == {
        "t": "MORSE_FEEDBACK",
        "result": "ok",
        "events": [{"type": "morse", "phase": "pending", "sequence": "."}],
        "count": 1,
    }
    assert events == []


async def test_morse_feedback_ctrl_reports_unavailable() -> None:
    writer = FakeWriter()
    await process_ctrl_json('{"t":"MORSE_FEEDBACK"}', context_with_feedback(None), writer)
    payload = writer.payloads()[0]
    assert payload["t"] == "MORSE_FEEDBACK"
    assert payload["result"] == "error"
    assert "not available" in payload["msg"]


def main() -> None:
    asyncio.run(test_morse_feedback_ctrl_drains_events())
    asyncio.run(test_morse_feedback_ctrl_reports_unavailable())
    print("ok: MORSE ctrl feedback")


if __name__ == "__main__":
    main()
