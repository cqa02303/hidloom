#!/usr/bin/env python3
"""Regression checks for logicd-facing touch flick dispatch guards."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "daemon" / "http"))

from logicd.input_events import InputEventContext  # noqa: E402
from logicd.interaction_engine import InteractionEngine  # noqa: E402
from logicd.keymap import LayerManager  # noqa: E402
from logicd.text_send_safety import TEXT_SEND_RUNNER_CANCEL_PATH, TEXT_SEND_RUNNER_METHOD, TEXT_SEND_RUNNER_TARGET, TextSendRuntimeState  # noqa: E402
from logicd.ctrl import process_ctrl_json  # noqa: E402
from logicd.touch_flick_dispatch import dispatch_touch_flick_event, validate_touch_flick_dispatch_event  # noqa: E402
from touch_panel_flick_api import resolve_touch_panel_flick_request  # noqa: E402


class EmptyEncoders:
    def handles(self, row: int, col: int) -> bool:
        return False


class RecordingMacros:
    def __init__(self) -> None:
        self.events: list[tuple[str, bool]] = []

    async def handle(self, action: str, is_press: bool) -> None:
        self.events.append((action, is_press))


class FakeWriter:
    def __init__(self) -> None:
        self.data = bytearray()

    def write(self, data: bytes) -> None:
        self.data.extend(data)

    async def drain(self) -> None:
        return None

    def messages(self) -> list[dict]:
        return [json.loads(line) for line in self.data.decode("utf-8").splitlines() if line]


def _ready_text_send_settings() -> dict:
    return {
        "unicode": {"mode": "windows_ime_hex_f5", "host_profile": "win11-ime"},
        "text_send_runner": {
            "connected": True,
            "method": TEXT_SEND_RUNNER_METHOD,
            "target": TEXT_SEND_RUNNER_TARGET,
            "cancel_path": TEXT_SEND_RUNNER_CANCEL_PATH,
            "zero_report_on_cancel": True,
        },
        "send_strings": {"kana_a": {"text": "あ", "enabled": True}},
    }


def _ctx(macros: RecordingMacros, text_send_settings: dict | None = None, text_send: TextSendRuntimeState | None = None) -> InputEventContext:
    layers = LayerManager()
    layers.load([{}])
    return InputEventContext(
        layers=layers,
        interactions=InteractionEngine(layers),
        macros=macros,
        encoders=EmptyEncoders(),
        joysticks=SimpleNamespace(process=lambda *_args: None),
        pressed_matrix=set(),
        push_ledd_key_event=lambda *_args: None,
        push_ledd_status=lambda: None,
        push_i2cd_status=lambda: None,
        push_i2cd_alert=lambda *_args: None,
        push_ledd_anim=lambda *_args: None,
        apply_lighting_key_action=lambda *_args: False,
        mouse_write_fn=lambda _report: None,
        bt_manager=None,
        text_send=text_send,
        text_send_settings=text_send_settings or {},
    )


def test_current_resolver_event_is_blocked_preview_only() -> None:
    resolved = resolve_touch_panel_flick_request({"kind": "ime_control", "key": "convert"})
    assert resolved["result"] == "ok"
    plan = validate_touch_flick_dispatch_event(resolved["dispatch_event"])
    assert plan.result == "ok"
    assert plan.dispatchable is True
    assert plan.action == "KC_SPC"
    assert plan.dispatch == "tap_action"
    assert plan.as_dict()["dispatchable"] is True


def test_dispatch_guard_rejects_preview_state_and_malformed_payloads() -> None:
    base = {
        "source": "touch_panel_flick",
        "kind": "flick_pad",
        "key": "a",
        "action": "U+3044",
        "output": "preview",
        "dispatch": "preview_noop",
        "enabled": False,
    }
    for field in ("preview_state", "requested_direction", "resolved_direction", "requestedDirection", "resolvedDirection"):
        event = dict(base)
        event[field] = "left"
        plan = validate_touch_flick_dispatch_event(event)
        assert plan.result == "error"
        assert plan.reason and plan.reason.startswith("preview_state_not_allowed:")

    assert validate_touch_flick_dispatch_event([]).reason == "event_must_be_object"
    assert validate_touch_flick_dispatch_event({**base, "source": "keyboard"}).reason == "source_must_be_touch_panel_flick"
    assert validate_touch_flick_dispatch_event({**base, "action": ""}).reason == "missing_action"
    assert validate_touch_flick_dispatch_event({**base, "output": "bad"}).reason == "invalid_output"
    assert validate_touch_flick_dispatch_event({**base, "dispatch": "bad"}).reason == "invalid_dispatch"


def test_explicit_future_tap_action_plan_is_final_action_only() -> None:
    plan = validate_touch_flick_dispatch_event(
        {
            "source": "touch_panel_flick",
            "kind": "ime_control",
            "key": "commit",
            "action": "KC_ENTER",
            "output": "keycode",
            "dispatch": "tap_action",
            "enabled": True,
        }
    )
    assert plan.result == "ok"
    assert plan.dispatchable is True
    assert plan.as_dict() == {
        "result": "ok",
        "dispatchable": True,
        "enabled": True,
        "action": "KC_ENTER",
        "output": "keycode",
        "dispatch": "tap_action",
    }

    text_plan = validate_touch_flick_dispatch_event(
        {
            "source": "touch_panel_flick",
            "kind": "flick_pad",
            "key": "a",
            "action": "U+3042",
            "output": "text",
            "dispatch": "tap_action",
            "enabled": True,
        }
    )
    assert text_plan.result == "ok"
    assert text_plan.dispatchable is True

    named_text_plan = validate_touch_flick_dispatch_event(
        {
            "source": "touch_panel_flick",
            "kind": "flick_pad",
            "key": "named_text",
            "action": "TEXT(kana_a)",
            "output": "text",
            "dispatch": "tap_action",
            "enabled": True,
        }
    )
    assert named_text_plan.result == "ok"
    assert named_text_plan.dispatchable is True

    unknown_text_plan = validate_touch_flick_dispatch_event(
        {
            "source": "touch_panel_flick",
            "kind": "flick_pad",
            "key": "bad",
            "action": "not_text",
            "output": "text",
            "dispatch": "tap_action",
            "enabled": True,
        }
    )
    assert unknown_text_plan.result == "blocked"
    assert unknown_text_plan.reason == "unknown_text_action"


async def test_dispatch_helper_taps_explicit_keycode_and_gates_text_actions() -> None:
    macros = RecordingMacros()
    ctx = _ctx(macros)
    blocked = await dispatch_touch_flick_event(
        {
            "source": "touch_panel_flick",
            "kind": "ime_control",
            "key": "convert",
            "action": "KC_SPC",
            "output": "keycode",
            "dispatch": "preview_noop",
            "enabled": False,
        },
        ctx,
        hold_sec=0,
    )
    assert blocked["result"] == "blocked"
    assert blocked["events"] == 0
    assert macros.events == []

    dispatched = await dispatch_touch_flick_event(
        {
            "source": "touch_panel_flick",
            "kind": "ime_control",
            "key": "commit",
            "action": "KC_ENTER",
            "output": "keycode",
            "dispatch": "tap_action",
            "enabled": True,
        },
        ctx,
        hold_sec=0,
    )
    assert dispatched["result"] == "ok"
    assert dispatched["events"] == 2
    assert macros.events == [("KC_ENTER", True), ("KC_ENTER", False)]

    macros = RecordingMacros()
    text_dispatched_without_unicode_settings = await dispatch_touch_flick_event(
        {
            "source": "touch_panel_flick",
            "kind": "flick_pad",
            "key": "a",
            "action": "U+3042",
            "output": "text",
            "dispatch": "tap_action",
            "enabled": True,
        },
        _ctx(macros),
        hold_sec=0,
    )
    assert text_dispatched_without_unicode_settings["result"] == "ok"
    assert text_dispatched_without_unicode_settings["events"] == 2
    assert text_dispatched_without_unicode_settings["composition_mode"] == "romaji_us_ime"
    assert text_dispatched_without_unicode_settings["composition_taps"] == 1
    assert macros.events == [("KC_A", True), ("KC_A", False)]

    macros = RecordingMacros()
    text_state = TextSendRuntimeState()
    text_dispatched = await dispatch_touch_flick_event(
        {
            "source": "touch_panel_flick",
            "kind": "flick_pad",
            "key": "a",
            "action": "U+3042",
            "output": "text",
            "dispatch": "tap_action",
            "enabled": True,
        },
        _ctx(macros, _ready_text_send_settings(), text_state),
        hold_sec=0,
    )
    assert text_dispatched["result"] == "ok"
    assert text_dispatched["events"] == 12
    assert text_dispatched["text_send_taps"] == 6
    assert text_dispatched["schema"] == "text_send.runtime_runner.v1"
    assert text_state.active is False
    assert [event[0] for event in macros.events[::2]] == ["KC_3", "KC_0", "KC_4", "KC_2", "KC_F5", "KC_ENTER"]

    macros = RecordingMacros()
    full_width_digit_dispatched = await dispatch_touch_flick_event(
        {
            "source": "touch_panel_flick",
            "kind": "flick_pad",
            "key": "num1",
            "action": "U+FF11",
            "output": "text",
            "dispatch": "tap_action",
            "enabled": True,
        },
        _ctx(macros, _ready_text_send_settings(), TextSendRuntimeState()),
        hold_sec=0,
    )
    assert full_width_digit_dispatched["result"] == "ok"
    assert full_width_digit_dispatched["events"] == 12
    assert full_width_digit_dispatched["text_send_taps"] == 6
    assert [event[0] for event in macros.events[::2]] == ["KC_F", "KC_F", "KC_1", "KC_1", "KC_F5", "KC_ENTER"]

    macros = RecordingMacros()
    named_text_blocked = await dispatch_touch_flick_event(
        {
            "source": "touch_panel_flick",
            "kind": "flick_pad",
            "key": "named_text",
            "action": "TEXT(kana_a)",
            "output": "text",
            "dispatch": "tap_action",
            "enabled": True,
        },
        _ctx(macros, _ready_text_send_settings(), TextSendRuntimeState()),
        hold_sec=0,
    )
    assert named_text_blocked["result"] == "ok"
    assert named_text_blocked["events"] == 12
    assert named_text_blocked["text_send_taps"] == 6
    assert [event[0] for event in macros.events[::2]] == ["KC_3", "KC_0", "KC_4", "KC_2", "KC_F5", "KC_ENTER"]

    macros = RecordingMacros()
    busy_state = TextSendRuntimeState()
    busy_state.begin("touch_flick")
    text_busy = await dispatch_touch_flick_event(
        {
            "source": "touch_panel_flick",
            "kind": "flick_pad",
            "key": "a",
            "action": "U+3042",
            "output": "text",
            "dispatch": "tap_action",
            "enabled": True,
        },
        _ctx(macros, _ready_text_send_settings(), busy_state),
        hold_sec=0,
    )
    assert text_busy["result"] == "blocked"
    assert text_busy["reason"] == "touch_flick_composition_busy"
    assert text_busy["events"] == 0
    assert macros.events == []


async def test_ctrl_touch_flick_dispatch_uses_final_event_only() -> None:
    macros = RecordingMacros()

    async def handle(event: dict) -> dict:
        return await dispatch_touch_flick_event(event, _ctx(macros), hold_sec=0)

    ctrl_ctx = SimpleNamespace(handle_touch_flick_event=handle)

    writer = FakeWriter()
    await process_ctrl_json(
        json.dumps(
            {
                "t": "TOUCH_FLICK",
                "event": {
                    "source": "touch_panel_flick",
                    "kind": "ime_control",
                    "key": "convert",
                    "action": "KC_SPC",
                    "output": "keycode",
                    "dispatch": "preview_noop",
                    "enabled": False,
                },
            }
        ),
        ctrl_ctx,
        writer,
    )
    assert writer.messages()[-1]["t"] == "TOUCH_FLICK"
    assert writer.messages()[-1]["result"] == "blocked"
    assert writer.messages()[-1]["events"] == 0
    assert macros.events == []

    writer = FakeWriter()
    await process_ctrl_json(
        json.dumps(
            {
                "t": "TOUCH_FLICK",
                "event": {
                    "source": "touch_panel_flick",
                    "kind": "ime_control",
                    "key": "commit",
                    "action": "KC_ENTER",
                    "output": "keycode",
                    "dispatch": "tap_action",
                    "enabled": True,
                },
            }
        ),
        ctrl_ctx,
        writer,
    )
    assert writer.messages()[-1]["result"] == "ok"
    assert writer.messages()[-1]["dispatchable"] is True
    assert writer.messages()[-1]["events"] == 2
    assert macros.events == [("KC_ENTER", True), ("KC_ENTER", False)]

    writer = FakeWriter()
    await process_ctrl_json('{"t":"TOUCH_FLICK","event":[]}', ctrl_ctx, writer)
    assert writer.messages()[-1]["result"] == "error"
    assert writer.messages()[-1]["msg"] == "event must be object"

    no_handler_ctx = SimpleNamespace(handle_touch_flick_event=None)
    writer = FakeWriter()
    await process_ctrl_json('{"t":"TOUCH_FLICK","event":{}}', no_handler_ctx, writer)
    assert writer.messages()[-1]["result"] == "error"
    assert writer.messages()[-1]["msg"] == "touch flick dispatch is not available"


def main() -> None:
    test_current_resolver_event_is_blocked_preview_only()
    test_dispatch_guard_rejects_preview_state_and_malformed_payloads()
    test_explicit_future_tap_action_plan_is_final_action_only()
    asyncio.run(test_dispatch_helper_taps_explicit_keycode_and_gates_text_actions())
    asyncio.run(test_ctrl_touch_flick_dispatch_uses_final_event_only())
    print("ok: touch flick dispatch guard accepts final actions only")


if __name__ == "__main__":
    main()
