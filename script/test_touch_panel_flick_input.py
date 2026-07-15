#!/usr/bin/env python3
"""Regression checks for the touch-panel flick metadata contract."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon" / "http"))
REPO_FLICK_CONFIG = ROOT / "config" / "default" / "touch-panel" / "osoyoo-4.3" / "flick.json"

from text_send_safety_api import TEXT_SEND_PLAN_ROUTE, TEXT_SEND_SAFETY_ROUTE  # noqa: E402
from touch_panel_flick_api import (  # noqa: E402
    TARGET_TOUCH_PANEL_PROFILE,
    TOUCH_PANEL_FLICK_COMPOSITION_PLAN_ROUTE,
    TOUCH_PANEL_FLICK_DISPATCH_ROUTE,
    TOUCH_PANEL_FLICK_RESOLVE_ROUTE,
    TOUCH_PANEL_FLICK_ROUTE,
    build_touch_flick_composition_plan,
    build_touch_flick_dispatch_event,
    flick_pad_metadata,
    ime_control_metadata,
    resolve_touch_panel_flick_composition_plan_request,
    resolve_touch_panel_flick_dispatch_request,
    resolve_flick_pad_action,
    resolve_ime_control_action,
    resolve_touch_panel_flick_request,
    touch_panel_flick_dispatch_response,
    touch_flick_host_ime_profile_metadata,
    touch_flick_layout_metadata,
    touch_flick_named_text_summary,
    touch_panel_flick_payload,
)


class JsonRequest:
    def __init__(self, body: object):
        self._body = body

    async def json(self) -> object:
        return self._body


def test_flick_pad_is_phone_style_preview_layout() -> None:
    pads = flick_pad_metadata(config_path=REPO_FLICK_CONFIG)

    assert len(pads) == 12
    assert pads[0]["label"] == "あ"
    assert pads[0]["layer"] == 0
    assert pads[0]["index"] == 0
    assert pads[0]["actions"]["center"]["action"] == "U+3042"
    assert pads[0]["actions"]["center"]["output"] == "text"
    assert pads[9]["label"] == "”゜小"
    assert pads[10]["label"] == "わ"
    assert pads[11]["label"] == "、。？！定"
    assert pads[11]["actions"]["left"]["action"] == "TEXT(kana_a)"
    assert pads[11]["actions"]["left"]["label"] == "定"
    assert pads[11]["actions"]["left"]["text_family"] == "named_send_string"
    assert pads[11]["actions"]["left"]["preflight_route"] == TEXT_SEND_PLAN_ROUTE
    layout = touch_flick_layout_metadata(REPO_FLICK_CONFIG)
    assert len(layout["layers"]) == 3
    assert layout["layers"][1]["name"] == "alpha-1"
    assert layout["layers"][1]["pads"][0]["label"] == "＠＃／＆＿"
    assert layout["layers"][1]["pads"][0]["actions"]["center"]["action"] == "KC_AT"
    assert layout["layers"][1]["pads"][0]["actions"]["left"]["action"] == "KC_HASH"
    assert layout["layers"][1]["pads"][0]["actions"]["up"]["action"] == "KC_SLSH"
    assert layout["layers"][1]["pads"][0]["actions"]["right"]["action"] == "KC_AMPR"
    assert layout["layers"][1]["pads"][0]["actions"]["down"]["action"] == "KC_UNDS"
    assert layout["layers"][1]["pads"][9]["label"] == "a/A"
    assert layout["layers"][1]["pads"][9]["actions"]["center"]["action"] == "KC_CAPS"
    assert layout["layers"][1]["pads"][10]["actions"]["left"]["action"] == "KC_DQUO"
    assert layout["layers"][1]["pads"][11]["actions"]["right"]["action"] == "KC_EXLM"
    assert layout["layers"][2]["name"] == "symbol-2"
    assert layout["layers"][2]["pads"][0]["label"] == "１☆♪→"
    assert layout["layers"][2]["pads"][0]["actions"]["center"]["action"] == "U+FF11"
    assert layout["layers"][2]["pads"][0]["actions"]["left"]["action"] == "U+2606"
    assert layout["layers"][2]["pads"][0]["actions"]["up"]["action"] == "U+266A"
    assert layout["layers"][2]["pads"][0]["actions"]["right"]["action"] == "U+2192"
    assert layout["layers"][2]["pads"][10]["label"] == "０～..."
    assert layout["layers"][2]["pads"][10]["actions"]["down"]["action"] == "U+002E"
    assert layout["layers"][2]["pads"][11]["actions"]["right"]["action"] == "U+FF0F"


def test_flick_layout_can_be_changed_by_definition_file() -> None:
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "flick.json"
        path.write_text(
            json.dumps(
                {
                    "columns": 3,
                    "rows": 4,
                    "layers": [
                        {
                            "name": "custom",
                            "pads": [
                                {
                                    "key": "mark",
                                    "label": "や゜",
                                    "actions": {
                                        "center": "ゃ",
                                        "up": "ゅ",
                                        "right": "ょ",
                                        "down": "っ",
                                        "left": "゜",
                                    },
                                },
                                {
                                    "key": "named",
                                    "label": "定型",
                                    "actions": {
                                        "center": "TEXT(kana_a)",
                                        "up": {
                                            "label": "kana a",
                                            "action": "SEND_STRING(kana_a)",
                                            "output": "text",
                                        },
                                    },
                                }
                            ],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        pads = flick_pad_metadata(config_path=path)
        assert pads[0]["label"] == "や゜"
        assert pads[0]["actions"]["right"]["action"] == "U+3087"
        resolved = resolve_flick_pad_action("mark", "down", config_path=path)
        assert resolved["action"]["label"] == "っ"
        assert resolved["action"]["action"] == "U+3063"
        named = resolve_flick_pad_action("named", "center", config_path=path)
        assert named["action"]["action"] == "TEXT(kana_a)"
        assert named["action"]["output"] == "text"
        assert named["action"]["text_family"] == "named_send_string"
        assert named["action"]["preflight_route"] == TEXT_SEND_PLAN_ROUTE
        named_dict = resolve_flick_pad_action("named", "up", config_path=path)
        assert named_dict["action"]["action"] == "SEND_STRING(kana_a)"
        assert named_dict["action"]["label"] == "kana a"
        assert named_dict["action"]["text_family"] == "named_send_string"
        summary = touch_flick_named_text_summary(touch_flick_layout_metadata(path))
        assert summary["schema"] == "touch_panel.flick.named_text_summary.v1"
        assert summary["entry_count"] == 2
        assert summary["preflight_route"] == TEXT_SEND_PLAN_ROUTE
        assert summary["entries"][0]["pad"] == "named"
        assert summary["entries"][0]["direction"] == "center"
        assert summary["entries"][0]["action"] == "TEXT(kana_a)"
        assert summary["entries"][1]["action"] == "SEND_STRING(kana_a)"


def test_ime_controls_are_host_key_actions() -> None:
    controls = ime_control_metadata()
    by_key = {control["key"]: control for control in controls}

    assert by_key["convert"]["label"] == "変換"
    assert by_key["convert"]["action"] == "KC_SPC"
    assert by_key["convert"]["alternatives"] == []
    assert by_key["nonconvert"]["label"] == "無変換"
    assert by_key["nonconvert"]["action"] == "KC_ENTER"
    assert by_key["commit"]["action"] == "KC_ENTER"
    assert by_key["candidate_prev"]["action"] == "KC_UP"
    assert by_key["candidate_next"]["action"] == "KC_DOWN"
    assert by_key["cancel"]["action"] == "KC_ESC"
    assert {control["output"] for control in controls} == {"keycode"}


def test_host_ime_profile_metadata_is_explicit_and_read_only() -> None:
    profile = touch_flick_host_ime_profile_metadata()
    windows = profile["profiles"][0]

    assert profile["auto_detection"] is False
    assert profile["explicit_profile_required"] is True
    assert profile["active_profile"] is None
    assert profile["default_dispatch_allowed"] is False
    assert "host IME profile must be selected" in profile["warning"]
    assert windows["key"] == "windows11_microsoft_ime"
    assert windows["label"] == "Windows 11 / Microsoft IME"
    assert windows["layout"] == "US keyboard compatible keycodes"
    assert windows["unicode_smoke"]["verified"] is True
    assert windows["unicode_smoke"]["sample"] == "あいうえお、。ーがぱぁゃア日本語"
    assert windows["controls"]["convert"] == "KC_SPC"
    assert windows["controls"]["commit"] == "KC_ENTER"
    assert windows["controls"]["cancel"] == "KC_ESC"
    assert windows["dispatch_gate"]["browser_default_enabled"] is False
    assert windows["dispatch_gate"]["requires_warning_ack"] is True
    assert windows["dispatch_gate"]["requires_runner_cancel_path"] is True


def test_resolvers_return_final_actions_only() -> None:
    kana = resolve_flick_pad_action("a", "left", config_path=REPO_FLICK_CONFIG)
    assert kana["result"] == "ok"
    assert kana["kind"] == "flick_pad"
    assert kana["requested_direction"] == "left"
    assert kana["resolved_direction"] == "left"
    assert kana["layer"] == 0
    assert kana["index"] == 0
    assert kana["action"]["action"] == "U+3044"
    assert kana["dispatch"] == "preview_noop"
    assert "preview_state" not in kana

    fallback = resolve_flick_pad_action("punct", "down", config_path=REPO_FLICK_CONFIG)
    assert fallback["result"] == "ok"
    assert fallback["requested_direction"] == "down"
    assert fallback["resolved_direction"] == "down"
    assert fallback["action"]["action"] == "U+3002"

    by_index = resolve_flick_pad_action(direction="right", layer=2, index=11, config_path=REPO_FLICK_CONFIG)
    assert by_index["result"] == "ok"
    assert by_index["key"] == "punct_symbol"
    assert by_index["layer"] == 2
    assert by_index["index"] == 11
    assert by_index["action"]["action"] == "U+FF0F"

    alpha = resolve_flick_pad_action(direction="right", layer=1, index=8, config_path=REPO_FLICK_CONFIG)
    assert alpha["result"] == "ok"
    assert alpha["key"] == "wxyz"
    assert alpha["label"] == "WXYZ"
    assert alpha["action"]["action"] == "KC_Z"
    assert alpha["action"]["output"] == "keycode"

    named = resolve_flick_pad_action("punct", "left", config_path=REPO_FLICK_CONFIG)
    assert named["result"] == "ok"
    assert named["key"] == "punct"
    assert named["label"] == "、。？！定"
    assert named["action"]["action"] == "TEXT(kana_a)"
    assert named["action"]["output"] == "text"
    assert named["action"]["text_family"] == "named_send_string"
    assert named["action"]["preflight_route"] == TEXT_SEND_PLAN_ROUTE

    caps = resolve_flick_pad_action(direction="left", layer=1, index=9, config_path=REPO_FLICK_CONFIG)
    assert caps["result"] == "ok"
    assert caps["resolved_direction"] == "center"
    assert caps["action"]["action"] == "KC_CAPS"

    unknown_pad = resolve_flick_pad_action("missing", "center", config_path=REPO_FLICK_CONFIG)
    assert unknown_pad["result"] == "error"
    assert unknown_pad["reason"] == "unknown_pad"

    ime = resolve_ime_control_action("convert")
    assert ime["result"] == "ok"
    assert ime["kind"] == "ime_control"
    assert ime["action"]["action"] == "KC_SPC"
    assert ime["dispatch"] == "preview_noop"

    unknown_control = resolve_ime_control_action("bad")
    assert unknown_control["result"] == "error"
    assert unknown_control["reason"] == "unknown_control"


def test_resolve_request_builds_preview_safe_dispatch_event() -> None:
    kana = resolve_touch_panel_flick_request(
        {"kind": "flick_pad", "key": "a", "direction": "left"},
        config_path=REPO_FLICK_CONFIG,
    )
    assert kana["result"] == "ok"
    assert kana["schema"] == "touch_panel.flick.resolve.v1"
    assert kana["final_action_only"] is True
    assert kana["preview_state_included"] is False
    assert kana["dispatch"] == "tap_action"
    assert kana["resolved_action"]["action"]["action"] == "U+3044"
    assert kana["dispatch_event"] == {
        "source": "touch_panel_flick",
        "kind": "flick_pad",
        "key": "a",
        "layer": 0,
        "index": 0,
        "action": kana["resolved_action"]["action"]["action"],
        "output": "text",
        "dispatch": "tap_action",
        "enabled": True,
    }
    assert "preview_state" not in kana
    assert "requested_direction" not in kana["dispatch_event"]
    assert "resolved_direction" not in kana["dispatch_event"]

    named = resolve_touch_panel_flick_request(
        {"kind": "flick_pad", "key": "punct", "direction": "left"},
        config_path=REPO_FLICK_CONFIG,
    )
    assert named["result"] == "ok"
    assert named["resolved_action"]["action"]["action"] == "TEXT(kana_a)"
    assert named["dispatch_event"] == {
        "source": "touch_panel_flick",
        "kind": "flick_pad",
        "key": "punct",
        "layer": 0,
        "index": 11,
        "action": "TEXT(kana_a)",
        "output": "text",
        "dispatch": "tap_action",
        "enabled": True,
    }

    ime = resolve_touch_panel_flick_request({"kind": "ime_control", "key": "convert"})
    assert ime["result"] == "ok"
    assert ime["dispatch_event"]["action"] == "KC_SPC"
    assert ime["dispatch_event"]["output"] == "keycode"
    assert ime["dispatch_event"]["enabled"] is True

    resolved = resolve_flick_pad_action("punct", "center", config_path=REPO_FLICK_CONFIG)
    event = build_touch_flick_dispatch_event(resolved)
    assert event["action"] == "U+3001"
    assert event["layer"] == 0
    assert event["index"] == 11
    assert event["enabled"] is True
    assert event["dispatch"] == "tap_action"

    assert resolve_touch_panel_flick_request([])["reason"] == "body_must_be_object"
    assert resolve_touch_panel_flick_request({"kind": "bad", "key": "a"})["reason"] == "unknown_kind"
    assert resolve_touch_panel_flick_request({"kind": "flick_pad"})["reason"] == "missing_key"
    assert resolve_touch_panel_flick_request(
        {"kind": "flick_pad", "key": "missing"},
        config_path=REPO_FLICK_CONFIG,
    )["reason"] == "unknown_pad"


def test_composition_plan_maps_kana_to_us_romaji_taps() -> None:
    kana = resolve_flick_pad_action("a", "left", config_path=REPO_FLICK_CONFIG)
    plan = build_touch_flick_composition_plan(kana)

    assert plan["result"] == "ok"
    assert plan["schema"] == "touch_panel.flick.composition_plan.v1"
    assert plan["read_only"] is True
    assert plan["sends_hid_reports"] is False
    assert plan["mode"] == "romaji_us_ime"
    assert plan["host_profile"] == "windows11_microsoft_ime"
    assert plan["available"] is True
    assert plan["blocking_reasons"] == []
    assert plan["tap_sequence"] == [{"type": "tap", "key": "KC_I"}]
    assert plan["convert_action"] == "KC_SPC"
    assert plan["commit_action"] == "KC_ENTER"
    assert plan["cancel_action"] == "KC_ESC"
    assert plan["blocked_outputs"] == [
        "katakana",
        "emoji",
        "ime_specific_marks",
        "non_ascii_symbols",
        "jis_kana_layout_dependent_keys",
        "named_text_or_send_string_actions",
    ]
    assert "composition_mode_requires_unicode_action" in plan["blocking_reason_policy"]
    assert "katakana_without_romaji_policy" in plan["blocking_reason_policy"]["composition_policy_non_ascii_symbol"]

    ka = resolve_touch_panel_flick_composition_plan_request({"kind": "flick_pad", "key": "ka", "direction": "center"})
    assert ka["available"] is True
    assert ka["tap_sequence"] == [{"type": "tap", "key": "KC_K"}, {"type": "tap", "key": "KC_A"}]

    punct = resolve_touch_panel_flick_composition_plan_request({"kind": "flick_pad", "key": "punct", "direction": "center"})
    assert punct["available"] is True
    assert punct["tap_sequence"] == [{"type": "tap", "key": "KC_COMM"}]

    for action, keys in {
        "U+304C": ["KC_G", "KC_A"],
        "U+3071": ["KC_P", "KC_A"],
        "U+3041": ["KC_L", "KC_A"],
        "U+3083": ["KC_L", "KC_Y", "KC_A"],
        "U+30FC": ["KC_MINS"],
        "U+FF11": ["KC_1"],
        "U+FF10": ["KC_0"],
        "U+FF01": ["KC_EXLM"],
        "U+FF1F": ["KC_QUES"],
        "U+FF08": ["KC_LPRN"],
        "U+FF09": ["KC_RPRN"],
        "U+FF0B": ["KC_PLUS"],
        "U+FF0F": ["KC_SLSH"],
        "U+FF5E": ["KC_TILD"],
        "U+002E": ["KC_DOT"],
    }.items():
        mapped = build_touch_flick_composition_plan({
            "result": "ok",
            "kind": "flick_pad",
            "key": "fixture",
            "action": {"action": action, "output": "text", "label": action},
        })
        assert mapped["available"] is True
        assert mapped["tap_sequence"] == [{"type": "tap", "key": key} for key in keys]

    control = resolve_touch_panel_flick_composition_plan_request({"kind": "ime_control", "key": "convert"})
    assert control["available"] is False
    assert control["not_applicable"] is True
    assert control["not_applicable_reason"] == "keycode_action_not_text_composition"
    assert control["blocking_reasons"] == []

    for action, reason in {
        "U+300C": "composition_policy_jis_kana_dependent",
        "U+309B": "composition_policy_ime_specific_mark",
        "U+266A": "composition_policy_non_ascii_symbol",
    }.items():
        blocked = build_touch_flick_composition_plan({
            "result": "ok",
            "kind": "flick_pad",
            "key": "fixture",
            "action": {"action": action, "output": "text", "label": action},
        })
        assert blocked["available"] is False
        assert blocked["blocking_reasons"] == [reason]
        assert reason in blocked["blocking_reason_policy"]


def test_dispatch_request_forwards_only_final_event_to_ctrl() -> None:
    resolved = resolve_touch_panel_flick_request({"kind": "ime_control", "key": "convert"})
    result = resolve_touch_panel_flick_dispatch_request({"event": resolved["dispatch_event"]})

    assert result["result"] == "ok"
    assert result["schema"] == "touch_panel.flick.dispatch.v1"
    assert result["final_action_only"] is True
    assert result["preview_state_included"] is False
    assert result["command"] == {"t": "TOUCH_FLICK", "event": resolved["dispatch_event"]}
    assert "resolved_action" not in result["command"]
    assert "requested_direction" not in result["command"]["event"]
    assert "resolved_direction" not in result["command"]["event"]

    assert resolve_touch_panel_flick_dispatch_request([])["reason"] == "body_must_be_object"
    assert resolve_touch_panel_flick_dispatch_request({})["reason"] == "event_must_be_object"
    rejected = resolve_touch_panel_flick_dispatch_request({
        "event": {
            **resolved["dispatch_event"],
            "preview_state": {"label": "変換"},
            "requested_direction": "center",
        }
    })
    assert rejected["result"] == "error"
    assert rejected["reason"] == "preview_state_not_dispatch_payload"
    assert rejected["fields"] == ["preview_state", "requested_direction"]


async def test_dispatch_response_relays_ctrl_result() -> None:
    resolved = resolve_touch_panel_flick_request({"kind": "ime_control", "key": "commit"})
    calls: list[dict[str, object]] = []

    async def send_ctrl(command: dict[str, object]) -> dict[str, object]:
        calls.append(command)
        return {"t": "TOUCH_FLICK", "result": "blocked", "reason": "disabled"}

    response = await touch_panel_flick_dispatch_response(JsonRequest({"event": resolved["dispatch_event"]}), send_ctrl)
    payload = json.loads(response.text)

    assert response.status == 200
    assert calls == [{"t": "TOUCH_FLICK", "event": resolved["dispatch_event"]}]
    assert payload["result"] == "blocked"
    assert payload["schema"] == "touch_panel.flick.dispatch.v1"
    assert payload["final_action_only"] is True
    assert payload["preview_state_included"] is False
    assert payload["ctrl"]["reason"] == "disabled"

    bad = await touch_panel_flick_dispatch_response(JsonRequest({"event": {"preview_state": {}}}), send_ctrl)
    assert bad.status == 400


def test_profile_guard_only_allows_osoyoo_43() -> None:
    with TemporaryDirectory() as tmp:
        marker = Path(tmp) / "touch_panel_profile.json"
        marker.write_text(
            json.dumps({"profile": TARGET_TOUCH_PANEL_PROFILE, "reason": "test", "sizes": [{"width": 800, "height": 480}]}),
            encoding="utf-8",
        )
        payload = touch_panel_flick_payload(marker, config_path=REPO_FLICK_CONFIG)
        assert payload["result"] == "ok"
        assert payload["route"] == TOUCH_PANEL_FLICK_ROUTE
        assert payload["read_only"] is True
        assert payload["available"] is True
        assert payload["enabled"] is False
        assert payload["profile_guard"]["matches_target"] is True
        assert payload["event_boundary"]["final_action_only"] is True
        assert "pointercancel" in payload["event_boundary"]["cancel_hooks"]
        assert payload["action_resolution"]["final_action_only"] is True
        assert payload["action_resolution"]["preview_state_is_not_dispatch_payload"] is True
        assert payload["action_resolution"]["dispatch"] == "tap_action"
        assert payload["action_resolution"]["resolve_route"] == TOUCH_PANEL_FLICK_RESOLVE_ROUTE
        assert payload["action_resolution"]["dispatch_route"] == TOUCH_PANEL_FLICK_DISPATCH_ROUTE
        assert payload["action_resolution"]["composition_plan_route"] == TOUCH_PANEL_FLICK_COMPOSITION_PLAN_ROUTE
        assert "resolve_touch_panel_flick_request" in payload["action_resolution"]["helpers"]
        assert "resolve_touch_panel_flick_dispatch_request" in payload["action_resolution"]["helpers"]
        assert "resolve_touch_panel_flick_composition_plan_request" in payload["action_resolution"]["helpers"]
        assert "build_touch_flick_dispatch_event" in payload["action_resolution"]["helpers"]
        assert "build_touch_flick_composition_plan" in payload["action_resolution"]["helpers"]
        assert payload["composition_mode"]["plan_route"] == TOUCH_PANEL_FLICK_COMPOSITION_PLAN_ROUTE
        assert payload["composition_mode"]["mode"] == "romaji_us_ime"
        assert payload["composition_mode"]["uses_us_keyboard_keycodes_only"] is True
        assert payload["composition_mode"]["default_dispatch_allowed"] is False
        assert "dakuten_rows" in payload["composition_mode"]["initial_scope"]
        assert "handakuten_rows" in payload["composition_mode"]["initial_scope"]
        assert "small_ya_yu_yo" in payload["composition_mode"]["initial_scope"]
        assert "basic_japanese_punctuation" in payload["composition_mode"]["initial_scope"]
        assert "full_width_digits" in payload["composition_mode"]["initial_scope"]
        assert "us_shifted_symbol_aliases" in payload["composition_mode"]["initial_scope"]
        assert "katakana" in payload["composition_mode"]["blocked_outputs"]
        assert "symbols" not in payload["composition_mode"]["blocked_outputs"]
        assert "ime_specific_marks" in payload["composition_mode"]["blocked_outputs"]
        assert "non_ascii_symbols" in payload["composition_mode"]["blocked_outputs"]
        assert "jis_kana_layout_dependent_keys" in payload["composition_mode"]["blocked_outputs"]
        assert "named_text_or_send_string_actions" in payload["composition_mode"]["blocked_outputs"]
        assert payload["composition_mode"]["blocking_reason_policy"] == {
            "composition_mode_requires_unicode_action": [
                "named_text_and_send_string_actions_use_text_send_preflight",
            ],
            "composition_policy_ime_specific_mark": [
                "dakuten_handakuten_mark_codepoints",
                "iteration_marks",
                "middle_dot",
            ],
            "composition_policy_jis_kana_dependent": ["corner_brackets"],
            "composition_policy_non_ascii_symbol": [
                "currency",
                "math_symbols",
                "arrows",
                "music_symbols",
                "placeholder_marks",
                "emoji",
                "katakana_without_romaji_policy",
            ],
        }
        assert payload["dispatch_policy"]["dispatch_route"] == TOUCH_PANEL_FLICK_DISPATCH_ROUTE
        assert payload["dispatch_policy"]["browser_default_enabled"] is False
        assert payload["dispatch_policy"]["browser_may_call_dispatch"] is True
        assert payload["dispatch_policy"]["browser_requires_local_enable"] is True
        assert payload["dispatch_policy"]["preview_noop_is_blocked"] is True
        assert payload["dispatch_policy"]["allowed_event"] == {
            "enabled": True,
            "dispatch": "tap_action",
            "output": "keycode_or_ready_text",
        }
        assert payload["dispatch_policy"]["blocked_outputs"]["preview"] == "preview_only"
        assert "preview_state" in payload["dispatch_policy"]["forbidden_event_fields"]
        assert payload["dispatch_policy"]["required_before_text_dispatch"] == ["text_send_runner_must_not_target_kiosk_window"]
        assert payload["dispatch_policy"]["text_output_preflight_route"] == TEXT_SEND_PLAN_ROUTE
        assert payload["unicode_prerequisite"]["route"] == TEXT_SEND_SAFETY_ROUTE
        assert payload["unicode_prerequisite"]["plan_route"] == TEXT_SEND_PLAN_ROUTE
        assert payload["unicode_prerequisite"]["kana_output"] == "flick_definition_to_unicode_action"
        assert payload["unicode_prerequisite"]["named_text_output"] == "TEXT(name)_or_SEND_STRING(name)"
        assert payload["unicode_prerequisite"]["text_output_preflight"] == "action_level_plan_required"
        assert payload["layout"]["layers"][0]["pads"][9]["label"] == "”゜小"
        assert payload["layout"]["layers"][1]["pads"][1]["label"] == "ABC"
        assert payload["layout"]["layers"][1]["pads"][1]["actions"]["left"]["action"] == "KC_B"
        assert payload["layout"]["layers"][2]["pads"][7]["label"] == "８〓々〆"
        assert payload["layout"]["layers"][2]["pads"][7]["actions"]["right"]["action"] == "U+3006"
        assert payload["named_text"]["schema"] == "touch_panel.flick.named_text_summary.v1"
        assert payload["named_text"]["entry_count"] == 1
        assert payload["named_text"]["entries"] == [{
            "layer": 0,
            "layer_name": "kana-0",
            "pad": "punct",
            "label": "、。？！定",
            "direction": "left",
            "action": "TEXT(kana_a)",
            "preflight_route": TEXT_SEND_PLAN_ROUTE,
        }]
        assert payload["named_text"]["preflight_route"] == TEXT_SEND_PLAN_ROUTE
        assert payload["named_text_assignment"]["schema"] == "touch_panel.flick.named_text_assignment.v1"
        assert payload["named_text_assignment"]["status"] == "metadata_flow_fixed"
        assert payload["named_text_assignment"]["source"] == "settings.send_strings"
        assert payload["named_text_assignment"]["settings_route"] == "/api/settings/send-strings"
        assert payload["named_text_assignment"]["action_format"] == ["TEXT(name)", "SEND_STRING(name)"]
        assert payload["named_text_assignment"]["runtime_editor"] is False
        assert "assign_action_in_flick_json" in payload["named_text_assignment"]["edit_flow"]
        assert payload["named_text_assignment"]["verification"]["summary"] == "named_text"
        assert payload["named_text_assignment"]["verification"]["preflight_route"] == TEXT_SEND_PLAN_ROUTE
        assert payload["ime_controls"]["owner"] == "host_ime"
        assert payload["ime_controls"]["key_actions_only"] is True
        assert payload["ime_controls"]["us_keyboard_ime_profile"]["nonconvert"] == "KC_ENTER"
        assert payload["ime_controls"]["us_keyboard_ime_profile"]["convert"] == "KC_SPC"
        assert payload["ime_controls"]["us_keyboard_ime_profile"]["uses_us_keyboard_keycodes_only"] is True
        assert payload["host_ime_profile"]["explicit_profile_required"] is True
        assert payload["host_ime_profile"]["active_profile"] is None
        assert payload["host_ime_profile"]["profiles"][0]["key"] == "windows11_microsoft_ime"


def test_non_target_profile_is_guarded() -> None:
    with TemporaryDirectory() as tmp:
        marker = Path(tmp) / "touch_panel_profile.json"
        marker.write_text(json.dumps({"profile": "waveshare-8.8"}), encoding="utf-8")
        payload = touch_panel_flick_payload(marker)
        assert payload["available"] is False
        assert payload["profile_guard"]["profile"] == "waveshare-8.8"


def test_httpd_registers_touch_panel_flick_route() -> None:
    httpd = (ROOT / "daemon/http/httpd.py").read_text(encoding="utf-8")
    assert "register_touch_panel_flick_route(app, _send_ctrl_command)" in httpd
    assert "from touch_panel_flick_api import register_touch_panel_flick_route" in httpd
    api = (ROOT / "daemon/http/touch_panel_flick_api.py").read_text(encoding="utf-8")
    assert "app.router.add_post(TOUCH_PANEL_FLICK_RESOLVE_ROUTE" in api
    assert "app.router.add_post(TOUCH_PANEL_FLICK_COMPOSITION_PLAN_ROUTE" in api
    assert "app.router.add_post(TOUCH_PANEL_FLICK_DISPATCH_ROUTE" in api


def main() -> None:
    test_flick_pad_is_phone_style_preview_layout()
    test_flick_layout_can_be_changed_by_definition_file()
    test_ime_controls_are_host_key_actions()
    test_host_ime_profile_metadata_is_explicit_and_read_only()
    test_resolvers_return_final_actions_only()
    test_resolve_request_builds_preview_safe_dispatch_event()
    test_composition_plan_maps_kana_to_us_romaji_taps()
    test_dispatch_request_forwards_only_final_event_to_ctrl()
    asyncio.run(test_dispatch_response_relays_ctrl_result())
    test_profile_guard_only_allows_osoyoo_43()
    test_non_target_profile_is_guarded()
    test_httpd_registers_touch_panel_flick_route()
    print("ok: touch-panel flick exposes profile-guarded preview metadata")


if __name__ == "__main__":
    main()
