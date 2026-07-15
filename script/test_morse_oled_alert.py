#!/usr/bin/env python3
"""Regression tests for MORSE OLED alert notifications."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.input_events import InputEventContext, process_interaction_tick, process_matrix_event  # noqa: E402
from logicd.interaction_engine import InteractionEngine  # noqa: E402
from logicd.keymap import LayerManager  # noqa: E402


class EmptyEncoders:
    def handles(self, _row: int, _col: int) -> bool:
        return False


class RecordingMacros:
    async def handle(self, _action: str, _is_press: bool) -> None:
        return None


def make_ctx(
    morse_def: dict,
    alerts: list[tuple[str, float, bool]],
    led_events: list[dict] | None = None,
) -> InputEventContext:
    layers = LayerManager()
    layers.load([{"0,0": "MORSE(main)"}])
    return InputEventContext(
        layers=layers,
        interactions=InteractionEngine(layers, morse_behaviors={"main": morse_def}),
        macros=RecordingMacros(),
        encoders=EmptyEncoders(),
        joysticks=SimpleNamespace(process=lambda *_args: None),
        pressed_matrix=set(),
        push_ledd_key_event=lambda *_args: None,
        push_ledd_status=lambda: None,
        push_i2cd_status=lambda: None,
        push_i2cd_alert=lambda msg, sec=2.0, immediate=False: alerts.append((msg, sec, immediate)),
        push_ledd_anim=lambda *_args: None,
        apply_lighting_key_action=lambda *_args: False,
        mouse_write_fn=lambda _report: None,
        push_ledd_morse_feedback=(lambda event: led_events.append(event)) if led_events is not None else None,
        bt_manager=None,
    )


async def test_morse_cancel_emits_oled_alert_without_draining_feedback() -> None:
    alerts: list[tuple[str, float, bool]] = []
    led_events: list[dict] = []
    ctx = make_ctx(
        {
            "dot_threshold": 0.180,
            "sequence_timeout": 0.250,
            "max_depth": 1,
            "map": {".": "KC_NO"},
        },
        alerts,
        led_events,
    )

    await process_matrix_event(("P", 0, 0), ctx)
    assert alerts == []
    await process_matrix_event(("R", 0, 0), ctx)

    assert alerts == [("MORSE main\n. CANCEL", 0.8, True)]
    assert [event["phase"] for event in led_events] == ["cancel"]
    feedback = ctx.interactions.drain_morse_feedback()
    assert [event["phase"] for event in feedback] == ["press", "cancel"]


async def test_morse_pending_and_timeout_commit_emit_oled_alerts() -> None:
    alerts: list[tuple[str, float, bool]] = []
    ctx = make_ctx(
        {
            "dot_threshold": 0.180,
            "sequence_timeout": 0.001,
            "max_depth": 2,
            "map": {".": "KC_E", ".-": "KC_A"},
        },
        alerts,
    )

    await process_matrix_event(("P", 0, 0), ctx)
    await process_matrix_event(("R", 0, 0), ctx)
    assert alerts == [("MORSE main\n. PENDING\nKC_E", 0.7, True)]
    await asyncio.sleep(0.020)
    await process_interaction_tick(ctx)

    assert alerts[-1] == ("MORSE main\n. COMMIT\nKC_E", 1.1, True)


def main() -> None:
    asyncio.run(test_morse_cancel_emits_oled_alert_without_draining_feedback())
    asyncio.run(test_morse_pending_and_timeout_commit_emit_oled_alerts())
    print("ok: MORSE OLED alerts")


if __name__ == "__main__":
    main()
