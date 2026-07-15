#!/usr/bin/env python3
"""Regression checks for the Unicode / Send String safety contract."""
from __future__ import annotations

import sys
import asyncio
from tempfile import TemporaryDirectory
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "daemon" / "http"))

from logicd.text_send_safety import (  # noqa: E402
    DEFAULT_UNICODE_MODE,
    DEFAULT_TEXT_SEND_RUNNER_TIMEOUT_SEC,
    TEXT_SEND_CANCEL_TRIGGERS,
    TEXT_SEND_FORBIDDEN_REAL_SEND_STEPS,
    TEXT_SEND_NO_OP_RELEASE_CONDITIONS,
    TEXT_SEND_REAL_SEND_STEP_SCOPE,
    TEXT_SEND_RUNNER_CANCEL_PATH,
    TEXT_SEND_RUNNER_METHOD,
    TEXT_SEND_RUNNER_TARGET,
    TEXT_SEND_TAP_DRY_RUN_SCHEMA,
    TEXT_SEND_TAP_DRY_RUN_SUPPORTED_MODES,
    TextSendRuntimeState,
    build_text_send_real_send_plan,
    build_text_send_tap_dry_run,
    explicit_text_send_host_profile,
    classify_text_send_action,
    normalize_text_send_runner_timeout,
    normalize_unicode_mode,
    send_string_name_valid,
    text_send_runner_connection,
    text_send_execution_gate,
    text_send_safety_policy,
    validate_send_string_entry,
    validate_send_string_settings,
)
from text_send_safety_api import (  # noqa: E402
    TEXT_SEND_PLAN_ROUTE,
    TEXT_SEND_SAFETY_ROUTE,
    text_send_plan_payload,
    text_send_safety_payload,
)
from logicd.text_send_runner import dispatch_text_send_action  # noqa: E402


class RecordingMacros:
    def __init__(self) -> None:
        self.events: list[tuple[str, bool]] = []

    async def handle(self, action: str, is_press: bool) -> None:
        self.events.append((action, is_press))


def _runner_ctx(settings: dict, state: TextSendRuntimeState | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        macros=RecordingMacros(),
        text_send=state or TextSendRuntimeState(),
        text_send_settings=settings,
        layers=SimpleNamespace(),
        interactions=SimpleNamespace(),
        push_ledd_status=lambda: None,
        push_i2cd_status=lambda: None,
        push_ledd_anim=lambda *_args: None,
        apply_lighting_key_action=lambda *_args: False,
        led_overlay_states={},
        host_led_output=SimpleNamespace(caps_lock=False, num_lock=False, scroll_lock=False),
        push_ledd_overlay_state=None,
        bt_passkey=None,
        bt_manager=None,
        wifi_manager=None,
    )


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


def test_unicode_mode_defaults_to_none() -> None:
    assert DEFAULT_UNICODE_MODE == "none"
    assert normalize_unicode_mode("") == "none"
    assert normalize_unicode_mode("UC_LINX") == "none"
    assert normalize_unicode_mode("linux_ctrl_shift_u") == "linux_ctrl_shift_u"


def test_text_action_classification_is_preview_safe() -> None:
    unicode_action = classify_text_send_action("U+3042", unicode_mode="none")
    assert unicode_action.family == "unicode"
    assert unicode_action.supported is True
    assert unicode_action.executable is False
    assert unicode_action.normalized == "U+3042"
    assert "preview/no-op" in unicode_action.warning

    send_string = classify_text_send_action("TEXT(kana_a)")
    assert send_string.family == "send_string"
    assert send_string.normalized == "SEND_STRING(kana_a)"
    assert send_string.executable is False

    mode = classify_text_send_action("UC_MODE(linux_ctrl_shift_u)")
    assert mode.family == "unicode_mode"
    assert mode.supported is True
    assert mode.executable is False


def test_named_entries_and_cancel_triggers() -> None:
    assert send_string_name_valid("kana_a.left")
    assert not send_string_name_valid("../secret")
    assert "output_switch" in TEXT_SEND_CANCEL_TRIGGERS
    assert "emergency_release" in TEXT_SEND_CANCEL_TRIGGERS

    policy = text_send_safety_policy({"unicode": {"mode": "linux_ctrl_shift_u"}})
    assert policy["schema"] == "text_send.safety.v2"
    assert policy["read_only"] is True
    assert policy["unicode"]["auto_os_detection"] is False
    assert policy["host_profile"]["explicit"] is False
    assert policy["execution_gate"]["real_send_allowed"] is False
    assert policy["execution_gate"]["unicode_actions_executable"] is False
    assert "explicit_host_profile_required" in policy["execution_gate"]["blocking_reasons"]
    assert policy["send_string"]["named_entries_only"] is True
    assert policy["send_string"]["direct_text_in_keymap"] is False
    assert policy["send_string"]["newline_requires_allow_newline"] is True
    assert policy["send_string_validation"]["valid"] is True
    assert policy["real_send_step"]["schema"] == "text_send.real_send_plan.v1"
    assert "emit_keyboard_taps_only" in policy["real_send_step"]["minimal_scope"]
    assert "shell_script" in policy["real_send_step"]["forbidden_steps"]
    assert policy["runner_connection"]["schema"] == "text_send.runner_connection.v1"
    assert policy["runner_connection"]["ready"] is False
    assert policy["tap_dry_run"]["schema"] == TEXT_SEND_TAP_DRY_RUN_SCHEMA
    assert policy["tap_dry_run"]["sends_hid_reports"] is False
    assert policy["tap_dry_run"]["supported_modes"] == list(TEXT_SEND_TAP_DRY_RUN_SUPPORTED_MODES)
    assert "windows_ime_hex_f5" in policy["tap_dry_run"]["supported_modes"]
    assert policy["tap_dry_run"]["example"]["schema"] == TEXT_SEND_TAP_DRY_RUN_SCHEMA
    assert "runner_cancel_path_text_send_runtime_state" in policy["execution_gate"]["no_op_release_conditions"]
    assert policy["http_warning"]["required"] is True
    assert "interaction_summary" in policy["http_warning"]["scope"]


def test_explicit_host_profile_gate() -> None:
    empty = explicit_text_send_host_profile({})
    assert empty["explicit"] is False
    assert empty["reason"] == "explicit_host_profile_required"

    configured = explicit_text_send_host_profile({"unicode": {"mode": "linux_ctrl_shift_u", "host_profile": "win11-ime"}})
    assert configured["explicit"] is True
    assert configured["profile"] == "win11-ime"
    gate = text_send_execution_gate({"unicode": {"mode": "linux_ctrl_shift_u", "host_profile": "win11-ime"}})
    assert gate["unicode_actions_executable"] is True
    assert gate["send_string_actions_executable"] is False
    assert gate["real_send_allowed"] is False
    assert "send_string_runner_not_connected" in gate["blocking_reasons"]

    unicode_action = classify_text_send_action(
        "U+3042",
        unicode_mode="linux_ctrl_shift_u",
        require_explicit_host_profile=True,
        host_profile_explicit=False,
    )
    assert unicode_action.executable is False
    assert "explicit host profile" in unicode_action.warning


def test_runner_connection_contract_and_no_op_release_conditions() -> None:
    disconnected = text_send_runner_connection({})
    assert disconnected["schema"] == "text_send.runner_connection.v1"
    assert disconnected["ready"] is False
    assert disconnected["required_method"] == TEXT_SEND_RUNNER_METHOD
    assert disconnected["required_target"] == TEXT_SEND_RUNNER_TARGET
    assert disconnected["required_cancel_path"] == TEXT_SEND_RUNNER_CANCEL_PATH
    assert "send_string_runner_not_connected" in disconnected["blocking_reasons"]
    assert "text_send_runner_method_not_supported" in disconnected["blocking_reasons"]
    assert "runner_connected" in TEXT_SEND_NO_OP_RELEASE_CONDITIONS
    assert "runner_zero_report_on_cancel" in TEXT_SEND_NO_OP_RELEASE_CONDITIONS

    connected_only = text_send_runner_connection({"text_send_runner": {"connected": True}})
    assert connected_only["ready"] is False
    assert "send_string_runner_not_connected" not in connected_only["blocking_reasons"]
    assert "text_send_runner_cancel_path_not_wired" in connected_only["blocking_reasons"]
    assert "text_send_runner_zero_report_not_wired" in connected_only["blocking_reasons"]

    ready = text_send_runner_connection(
        {
            "text_send_runner": {
                "connected": True,
                "method": TEXT_SEND_RUNNER_METHOD,
                "target": TEXT_SEND_RUNNER_TARGET,
                "cancel_path": TEXT_SEND_RUNNER_CANCEL_PATH,
                "zero_report_on_cancel": True,
                "timeout_sec": 1.5,
            }
        }
    )
    assert ready["ready"] is True
    assert ready["blocking_reasons"] == []
    assert ready["timeout_sec"] == 1.5


def test_runtime_cancel_state() -> None:
    state = TextSendRuntimeState()
    idle = state.cancel("output_switch")
    assert idle["canceled"] is False
    assert idle["last_cancel_reason"] == "output_switch"
    assert idle["cancel_count"] == 0
    assert idle["zero_report_required"] is False

    running = state.begin("kana_a")
    assert running["active"] is True
    assert running["active_name"] == "kana_a"

    finished = state.finish()
    assert finished["finished"] is True
    assert finished["active"] is False
    assert state.cancel_count == 0

    state.begin("kana_a")

    canceled = state.cancel("emergency_release")
    assert canceled["canceled"] is True
    assert canceled["active"] is False
    assert canceled["last_cancel_reason"] == "emergency_release"
    assert canceled["cancel_count"] == 1
    assert canceled["zero_report_required"] is True
    sent = state.mark_zero_report_sent("emergency_release")
    assert sent["zero_report_sent"] is True
    assert sent["last_zero_report_reason"] == "emergency_release"
    assert sent["zero_report_count"] == 1

    idle_emergency = state.cancel("emergency_release")
    assert idle_emergency["canceled"] is False
    assert idle_emergency["zero_report_required"] is True

    fallback = state.cancel("unknown")
    assert fallback["last_cancel_reason"] == "explicit_cancel"


def test_runner_timeout_state() -> None:
    assert DEFAULT_TEXT_SEND_RUNNER_TIMEOUT_SEC == 2.0
    assert normalize_text_send_runner_timeout("bad") == 2.0
    assert normalize_text_send_runner_timeout(-1) == 2.0
    assert normalize_text_send_runner_timeout(99) == 30.0
    assert normalize_text_send_runner_timeout(None) is None

    state = TextSendRuntimeState()
    running = state.begin("kana_a", now=10.0, timeout_sec=0.5)
    assert running["runner_timeout_sec"] == 0.5
    assert running["deadline_at"] == 10.5
    assert state.timeout_due(10.49) is False
    assert state.cancel_if_timed_out(10.49) is None

    timed_out = state.cancel_if_timed_out(10.5)
    assert timed_out is not None
    assert timed_out["canceled"] is True
    assert timed_out["last_cancel_reason"] == "runner_timeout"
    assert timed_out["timeout_count"] == 1
    assert timed_out["zero_report_required"] is True
    assert timed_out["active"] is False


def test_send_string_content_validation() -> None:
    ok = validate_send_string_entry("kana_a", {"text": "あ", "enabled": True})
    assert ok["valid"] is True
    assert ok["length"] == 1

    newline = validate_send_string_entry("multi", {"text": "line1\nline2"})
    assert newline["valid"] is False
    assert "newline requires allow_newline" in newline["errors"]

    newline_allowed = validate_send_string_entry("multi", {"text": "line1\nline2", "allow_newline": True})
    assert newline_allowed["valid"] is True

    zero_width = validate_send_string_entry("hidden", {"text": "a\u200bb"})
    assert zero_width["valid"] is True
    assert "zero-width character" in zero_width["warnings"]

    control = validate_send_string_entry("bad", {"text": "a\x00b"})
    assert control["valid"] is False
    assert "control character" in control["errors"]

    settings = validate_send_string_settings(
        {
            "send_strings": {
                "kana_a": {"text": "あ"},
                "bad/name": {"text": "x"},
                "long": {"text": "x" * 81},
            }
        }
    )
    assert settings["valid"] is False
    assert settings["entry_count"] == 3
    assert settings["error_count"] == 2


def test_real_send_step_plan_stays_minimal_and_blocked_by_default() -> None:
    assert "emit_keyboard_taps_only" in TEXT_SEND_REAL_SEND_STEP_SCOPE
    assert "send_zero_report_on_cancel" in TEXT_SEND_REAL_SEND_STEP_SCOPE
    assert "shell_script" in TEXT_SEND_FORBIDDEN_REAL_SEND_STEPS
    assert "newline_codepoint" in TEXT_SEND_FORBIDDEN_REAL_SEND_STEPS

    blocked = build_text_send_real_send_plan("TEXT(kana_a)", {"send_strings": {"kana_a": {"text": "a"}}})
    assert blocked["schema"] == "text_send.real_send_plan.v1"
    assert blocked["read_only"] is True
    assert blocked["real_send_allowed"] is False
    assert "explicit_host_profile_required" in blocked["blocking_reasons"]
    assert "unicode_mode_none" in blocked["blocking_reasons"]
    assert "send_string_runner_not_connected" in blocked["blocking_reasons"]
    assert blocked["entry"]["valid"] is True
    assert blocked["steps"][0] == {"type": "resolve_named_text", "name": "kana_a"}

    ready = build_text_send_real_send_plan(
        "SEND_STRING(kana_a)",
        {
            "unicode": {"mode": "linux_ctrl_shift_u", "host_profile": "win11-ime"},
            "text_send_runner": {
                "connected": True,
                "method": TEXT_SEND_RUNNER_METHOD,
                "target": TEXT_SEND_RUNNER_TARGET,
                "cancel_path": TEXT_SEND_RUNNER_CANCEL_PATH,
                "zero_report_on_cancel": True,
            },
            "send_strings": {"kana_a": {"text": "a", "enabled": True}},
        },
    )
    assert ready["real_send_allowed"] is True
    assert ready["blocking_reasons"] == []
    assert any(step["type"] == "emit_keyboard_taps_only" for step in ready["steps"])
    assert "power_action" in ready["forbidden_steps"]

    missing = build_text_send_real_send_plan(
        "TEXT(missing)",
        {
            "unicode": {"mode": "linux_ctrl_shift_u", "host_profile": "win11-ime"},
            "text_send_runner": {
                "connected": True,
                "method": TEXT_SEND_RUNNER_METHOD,
                "target": TEXT_SEND_RUNNER_TARGET,
                "cancel_path": TEXT_SEND_RUNNER_CANCEL_PATH,
                "zero_report_on_cancel": True,
            },
            "send_strings": {},
        },
    )
    assert missing["real_send_allowed"] is False
    assert "send_string_entry_missing" in missing["blocking_reasons"]
    assert "send_string_entry_invalid" in missing["blocking_reasons"]


def test_named_send_string_blocking_reasons_are_specific() -> None:
    ready_settings = {
        "unicode": {"mode": "windows_ime_hex_f5", "host_profile": "win11-ime"},
        "text_send_runner": {
            "connected": True,
            "method": TEXT_SEND_RUNNER_METHOD,
            "target": TEXT_SEND_RUNNER_TARGET,
            "cancel_path": TEXT_SEND_RUNNER_CANCEL_PATH,
            "zero_report_on_cancel": True,
        },
        "send_strings": {
            "kana_a": {"text": "あ", "enabled": True},
            "disabled": {"text": "あ", "enabled": False},
            "invalid": {"text": "bad\nline", "enabled": True},
            "confirm": {"text": "あ", "enabled": True, "confirm": True},
        },
    }

    cases = {
        "TEXT(missing)": {
            "send_string_entry_missing",
            "send_string_entry_invalid",
            "send_string_entry_disabled",
        },
        "TEXT(disabled)": {"send_string_entry_disabled"},
        "TEXT(invalid)": {"send_string_entry_invalid"},
        "TEXT(confirm)": {"send_string_entry_requires_confirmation"},
    }
    for action, expected in cases.items():
        plan = build_text_send_real_send_plan(action, ready_settings)
        assert plan["real_send_allowed"] is False, action
        assert expected <= set(plan["blocking_reasons"]), action
        assert plan["tap_dry_run"]["available"] is False, action

    ready = build_text_send_real_send_plan("TEXT(kana_a)", ready_settings)
    assert ready["real_send_allowed"] is True
    assert ready["blocking_reasons"] == []
    assert ready["tap_dry_run"]["available"] is True
    assert ready["tap_dry_run"]["sequence_count"] == 1
    assert [tap["key"] for tap in ready["tap_dry_run"]["sequences"][0]["taps"]] == [
        "KC_3",
        "KC_0",
        "KC_4",
        "KC_2",
        "KC_F5",
        "KC_ENTER",
    ]


def test_tap_dry_run_preview_does_not_send_reports() -> None:
    unicode_preview = build_text_send_tap_dry_run(
        "U+3042",
        {"unicode": {"mode": "linux_ctrl_shift_u", "host_profile": "linux-desktop"}},
    )
    assert unicode_preview["schema"] == TEXT_SEND_TAP_DRY_RUN_SCHEMA
    assert unicode_preview["read_only"] is True
    assert unicode_preview["sends_hid_reports"] is False
    assert unicode_preview["available"] is True
    assert unicode_preview["sequence_count"] == 1
    taps = unicode_preview["sequences"][0]["taps"]
    assert taps[0] == {"type": "tap", "key": "KC_U", "modifiers": ["KC_LCTRL", "KC_LSHIFT"]}
    assert [tap["key"] for tap in taps[1:5]] == ["KC_3", "KC_0", "KC_4", "KC_2"]
    assert taps[-1] == {"type": "tap", "key": "KC_ENTER"}

    named_preview = build_text_send_tap_dry_run(
        "TEXT(kana_a)",
        {
            "unicode": {"mode": "linux_ctrl_shift_u", "host_profile": "linux-desktop"},
            "send_strings": {"kana_a": {"text": "a"}},
        },
    )
    assert named_preview["available"] is True
    assert named_preview["sequence_count"] == 1
    assert named_preview["sequences"][0]["codepoint"] == "0061"

    newline_preview = build_text_send_tap_dry_run(
        "TEXT(line)",
        {
            "unicode": {"mode": "linux_ctrl_shift_u", "host_profile": "linux-desktop"},
            "send_strings": {"line": {"text": "\n", "allow_newline": True}},
        },
    )
    assert newline_preview["available"] is False
    assert "newline_requires_key_action" in newline_preview["blocking_reasons"]

    unsupported_mode = build_text_send_tap_dry_run(
        "U+3042",
        {"unicode": {"mode": "mac_unicode_hex", "host_profile": "mac"}},
    )
    assert unsupported_mode["available"] is False
    assert "unicode_mode_mac_unicode_hex_dry_run_not_defined" in unsupported_mode["blocking_reasons"]

    windows_ime = build_text_send_tap_dry_run(
        "U+3042",
        {"unicode": {"mode": "windows_ime_hex_f5", "host_profile": "win11-ime"}},
    )
    assert windows_ime["available"] is True
    assert [tap["key"] for tap in windows_ime["sequences"][0]["taps"]] == [
        "KC_3",
        "KC_0",
        "KC_4",
        "KC_2",
        "KC_F5",
        "KC_ENTER",
    ]


def test_http_payload_and_registration() -> None:
    tmp = TemporaryDirectory()
    config_path = Path(tmp.name) / "config.json"
    config_path.write_text('{"settings": {}}', encoding="utf-8")
    payload = text_send_safety_payload(config_path)
    assert payload["result"] == "ok"
    assert payload["route"] == TEXT_SEND_SAFETY_ROUTE
    assert payload["plan_route"] == TEXT_SEND_PLAN_ROUTE
    assert payload["schema"] == "text_send.safety.v2"
    assert payload["unicode"]["mode"] == "none"
    assert payload["host_profile"]["required_for_real_send"] is True
    assert payload["execution_gate"]["real_send_allowed"] is False
    assert payload["runner_connection"]["ready"] is False
    assert "text_send_runner_cancel_path_not_wired" in payload["runner_connection"]["blocking_reasons"]
    assert payload["send_string"]["max_length"] == 80
    assert payload["real_send_step"]["schema"] == "text_send.real_send_plan.v1"
    assert "direct_text_in_keymap" in payload["real_send_step"]["forbidden_steps"]
    assert payload["tap_dry_run"]["schema"] == TEXT_SEND_TAP_DRY_RUN_SCHEMA
    assert "linux_ctrl_shift_u" in payload["tap_dry_run"]["supported_modes"]
    assert "windows_ime_hex_f5" in payload["tap_dry_run"]["supported_modes"]
    assert "mac_unicode_hex" in payload["tap_dry_run"]["unsupported_modes"]
    assert payload["send_string_validation"]["entry_count"] == 0
    assert any(example["action"] == "U+3042" for example in payload["examples"])

    missing = text_send_plan_payload(config_path, {})
    assert missing == {"result": "error", "reason": "action_required"}
    invalid = text_send_plan_payload(config_path, {"action": ["TEXT(kana_a)"]})
    assert invalid == {"result": "error", "reason": "action_must_be_string"}
    plan_payload = text_send_plan_payload(config_path, {"action": "TEXT(kana_a)"})
    assert plan_payload["result"] == "ok"
    assert plan_payload["route"] == TEXT_SEND_PLAN_ROUTE
    assert plan_payload["read_only"] is True
    assert plan_payload["plan"]["schema"] == "text_send.real_send_plan.v1"
    assert plan_payload["plan"]["tap_dry_run"]["schema"] == TEXT_SEND_TAP_DRY_RUN_SCHEMA
    assert plan_payload["plan"]["real_send_allowed"] is False
    assert "send_string_entry_missing" in plan_payload["plan"]["blocking_reasons"]

    httpd = (ROOT / "daemon/http/httpd.py").read_text(encoding="utf-8")
    assert "register_text_send_safety_route(app, CONFIG_JSON)" in httpd
    assert "from text_send_safety_api import register_text_send_safety_route" in httpd
    text_send_api = (ROOT / "daemon/http/text_send_safety_api.py").read_text(encoding="utf-8")
    assert 'TEXT_SEND_PLAN_ROUTE = "/api/interaction/text-send-safety/plan"' in text_send_api
    assert "app.router.add_post(TEXT_SEND_PLAN_ROUTE, handle_text_send_plan)" in text_send_api


async def test_runtime_runner_uses_real_send_plan_and_keyboard_taps() -> None:
    blocked_ctx = _runner_ctx({"send_strings": {"kana_a": {"text": "あ", "enabled": True}}})
    blocked = await dispatch_text_send_action("TEXT(kana_a)", blocked_ctx)
    assert blocked["result"] == "blocked"
    assert blocked["events"] == 0
    assert "unicode_mode_none" in blocked["blocking_reasons"]
    assert blocked_ctx.macros.events == []

    ready_ctx = _runner_ctx(_ready_text_send_settings())
    sent = await dispatch_text_send_action("TEXT(kana_a)", ready_ctx, hold_sec=0, gap_sec=0)
    assert sent["schema"] == "text_send.runtime_runner.v1"
    assert sent["result"] == "ok"
    assert sent["events"] == 12
    assert sent["text_send_taps"] == 6
    assert ready_ctx.text_send.active is False
    assert [event[0] for event in ready_ctx.macros.events[::2]] == [
        "KC_3",
        "KC_0",
        "KC_4",
        "KC_2",
        "KC_F5",
        "KC_ENTER",
    ]

    busy_state = TextSendRuntimeState()
    busy_state.begin("other")
    busy_ctx = _runner_ctx(_ready_text_send_settings(), busy_state)
    busy = await dispatch_text_send_action("TEXT(kana_a)", busy_ctx, hold_sec=0, gap_sec=0)
    assert busy["result"] == "blocked"
    assert busy["blocking_reasons"] == ["text_send_runner_busy"]
    assert busy_ctx.macros.events == []


def main() -> None:
    test_unicode_mode_defaults_to_none()
    test_text_action_classification_is_preview_safe()
    test_named_entries_and_cancel_triggers()
    test_explicit_host_profile_gate()
    test_runner_connection_contract_and_no_op_release_conditions()
    test_runtime_cancel_state()
    test_runner_timeout_state()
    test_send_string_content_validation()
    test_real_send_step_plan_stays_minimal_and_blocked_by_default()
    test_named_send_string_blocking_reasons_are_specific()
    test_tap_dry_run_preview_does_not_send_reports()
    test_http_payload_and_registration()
    asyncio.run(test_runtime_runner_uses_real_send_plan_and_keyboard_taps())
    print("ok: text-send safety keeps Unicode and named-string actions preview-safe")


if __name__ == "__main__":
    main()
