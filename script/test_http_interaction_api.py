#!/usr/bin/env python3
"""Local smoke tests for HTTP Interaction settings helpers."""
from __future__ import annotations

import json
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon" / "http"))
sys.path.insert(0, str(ROOT))

if "aiohttp" not in sys.modules:
    aiohttp_stub = types.ModuleType("aiohttp")
    web_stub = types.SimpleNamespace(Response=object, json_response=lambda *args, **kwargs: None)
    aiohttp_stub.web = web_stub
    sys.modules["aiohttp"] = aiohttp_stub
    sys.modules["aiohttp.web"] = web_stub

import interaction_api  # noqa: E402


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    async def native_systemctl(*args: str) -> dict:
        native_calls.append(args)
        return {
            "result": "ok" if args != ("is-active", "--quiet", "logicd") else "error",
            "returncode": 0 if args != ("is-active", "--quiet", "logicd") else 3,
            "stdout": "",
            "stderr": "",
        }

    native_calls: list[tuple[str, ...]] = []
    original_systemctl = interaction_api._run_systemctl
    interaction_api._run_systemctl = native_systemctl
    try:
        native_reload = __import__("asyncio").run(interaction_api.reload_logicd_service())
    finally:
        interaction_api._run_systemctl = original_systemctl
    assert native_reload["result"] == "ok"
    assert native_reload["unit"] == "logicd-companion"
    assert native_calls == [
        ("is-active", "--quiet", "logicd-companion"),
        ("reload", "logicd-companion"),
    ]

    async def legacy_systemctl(*args: str) -> dict:
        legacy_calls.append(args)
        return {
            "result": "ok" if args != ("is-active", "--quiet", "logicd-companion") else "error",
            "returncode": 3 if args == ("is-active", "--quiet", "logicd-companion") else 0,
            "stdout": "",
            "stderr": "",
        }

    legacy_calls: list[tuple[str, ...]] = []
    interaction_api._run_systemctl = legacy_systemctl
    try:
        legacy_reload = __import__("asyncio").run(interaction_api.reload_logicd_service())
    finally:
        interaction_api._run_systemctl = original_systemctl
    assert legacy_reload["result"] == "ok"
    assert legacy_reload["unit"] == "logicd"
    assert legacy_calls == [
        ("is-active", "--quiet", "logicd-companion"),
        ("is-active", "--quiet", "logicd"),
        ("reload", "logicd"),
    ]

    async def inactive_systemctl(*args: str) -> dict:
        return {"result": "error", "returncode": 3, "stdout": "", "stderr": "inactive"}

    interaction_api._run_systemctl = inactive_systemctl
    try:
        inactive_reload = __import__("asyncio").run(interaction_api.reload_logicd_service())
    finally:
        interaction_api._run_systemctl = original_systemctl
    assert inactive_reload == {
        "result": "error",
        "returncode": None,
        "msg": "no active logicd runtime service",
        "checked_units": ["logicd-companion", "logicd"],
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        config_json = tmp / "config.json"
        vial_json = tmp / "vial.json"
        write_json(vial_json, {"matrix": {"rows": 2, "cols": 3}})
        write_json(config_json, {
            "settings": {
                "interaction": {
                    "tapping_term": "0.18",
                    "combo_term": 0.04,
                    "tap_dance_term": 0.19,
                    "hold_on_other_key_press": True,
                    "combos": [
                        {"keys": [[0, 1], [0, 2]], "action": "KC_ESC"},
                        {"keys": [[0, 1], [9, 9]], "action": "KC_TAB"},
                    ],
                    "tap_dances": {"TD0": {"1": "KC_A", "2": "KC_ESC"}},
                    "key_overrides": [{"trigger": "KC_LSFT", "key": "KC_1", "replacement": "KC_EXLM"}],
                }
            },
            "layers": {"0": {}},
        })

        payload = interaction_api.build_interaction_payload(config_json, vial_json)
        assert payload["result"] == "ok"
        assert payload["settings"]["tapping_term"] == 0.18
        assert payload["settings"]["combo_term"] == 0.04
        assert payload["settings"]["combos"] == [{"keys": [[0, 1], [0, 2]], "action": "KC_ESC"}]
        assert payload["settings"]["tap_dances"] == {"TD0": {1: "KC_A", 2: "KC_ESC"}}
        assert payload["settings"]["key_overrides"] == [{
            "trigger": "KC_LSFT",
            "negative_trigger": [],
            "key": "KC_1",
            "replacement": "KC_EXLM",
            "layers": 0xFFFF,
            "options": 0x83,
        }]
        assert payload["warnings"], "invalid combo should produce a warning"
        assert "KC_EXLM" in payload["metadata"]["shifted_aliases"]
        assert payload["metadata"]["canonical_aliases"]["KC_CAPS_LOCK"] == "KC_CAPSLOCK"
        assert payload["metadata"]["canonical_aliases"]["KC_RETURN"] == "KC_ENTER"
        assert "S" in payload["metadata"]["modifier_wrappers"]
        status_connections = payload["metadata"]["status_connections"]
        assert status_connections["schema"] == "interaction.status_connections.v1"
        assert status_connections["save_payload_includes_runtime_state"] is False
        assert status_connections["storage_owner"] == "settings.interaction"
        assert status_connections["runtime_snapshot_owner"] == "/api/keymap/active"
        assert status_connections["features"]["caps_word"]["summary"] == "settings_only"
        assert status_connections["features"]["caps_word"]["runtime_active"] == "snapshot_only"
        assert status_connections["features"]["caps_word"]["runtime_active_source"] == "/api/interaction/runtime-status"
        assert status_connections["features"]["repeat_key"]["runtime_history"] == "privacy_safe_helper_only"
        assert status_connections["features"]["repeat_key"]["runtime_active_source"] == "/api/interaction/runtime-status"
        assert status_connections["features"]["conditional_layers"]["runtime_active_source"] == "/api/interaction/conditional-layers/inspector"
        assert status_connections["features"]["one_shot_layer"]["summary"] == "active_snapshot_oneshot"
        assert status_connections["features"]["layer_lock"]["unlock_button"] == "/api/keymap/layer-lock/clear"
        assert status_connections["features"]["layer_lock"]["unlock_mutates_saved_settings"] is False
        assert status_connections["next_local_todo"] == "runtime_feedback_or_real_device_touch_flick"

        class FakeResponse:
            def __init__(self) -> None:
                self.status = None
                self.payload = None

            def __call__(self, payload, *, status=200):
                self.payload = payload
                self.status = status
                return payload

        original_json_response = interaction_api.web.json_response
        fake_response = FakeResponse()
        interaction_api.web.json_response = fake_response
        async def fake_send_ctrl(command):
            assert command == {"t": "INTERACTION_STATUS"}
            return {
                "t": "INTERACTION_STATUS",
                "result": "ok",
                "schema": "interaction.runtime_status.v1",
                "caps_word": {"enabled": True, "active": True},
                "repeat_key": {"enabled": True, "history_available": True, "alternate_available": False},
                "key_lock": {"keys": [{"action": "KC_LSFT", "kind": "modifier", "source": "KEY_LOCK"}]},
                "one_shot_layer": {"active_count": 1, "source": "LayerManager.active_snapshot.oneshot"},
            }
        try:
            runtime_payload = __import__("asyncio").run(interaction_api.interaction_runtime_status_response(fake_send_ctrl))
        finally:
            interaction_api.web.json_response = original_json_response
        assert runtime_payload["schema"] == "interaction.runtime_status.v1"
        assert runtime_payload["caps_word"]["active"] is True
        assert runtime_payload["key_lock"]["keys"][0]["action"] == "KC_LSFT"
        assert runtime_payload["one_shot_layer"]["active_count"] == 1
        assert fake_response.status == 200

        preview = interaction_api.validate_interaction_settings_payload(
            vial_json,
            {
                "combos": [
                    {"keys": [[0, 1], [0, 2]], "action": "KC_ESC"},
                    {"keys": [[0, 0], [0, 2]], "action": "S(KC_1)"},
                    {"keys": [[1, 0], [1, 2]], "action": "SCRIPT(foo)"},
                    {"keys": [[0, 1], [9, 9]], "action": "KC_TAB"},
                    {"keys": [[1, 1], [1, 2]], "action": "KC_A;rm"},
                ],
                "tap_dances": {
                    "TD1": {"1": "MACRO:hello", "2": "U+3042", "3": "BAD(KC_A)"},
                },
                "key_overrides": [
                    {"trigger": ["LT(1,KC_SPACE)", "KC_LSFT"], "key": "KC_1", "replacement": "KC_EXLM"},
                    {"trigger": "KC_A;rm", "key": "KC_1", "replacement": "KC_ESC"},
                ],
            },
        )
        assert preview["result"] == "ok"
        assert preview["settings"]["combos"] == [
            {"keys": [[0, 1], [0, 2]], "action": "KC_ESC"},
            {"keys": [[0, 0], [0, 2]], "action": "S(KC_1)"},
            {"keys": [[1, 0], [1, 2]], "action": "SCRIPT(foo)"},
        ]
        assert preview["settings"]["tap_dances"] == {"TD1": {1: "MACRO:hello", 2: "U+3042"}}
        assert preview["settings"]["key_overrides"] == [
            {
                "trigger": ["LT(1,KC_SPACE)", "KC_LSFT"],
                "negative_trigger": [],
                "key": "KC_1",
                "replacement": "KC_EXLM",
                "layers": 0xFFFF,
                "options": 0x83,
            },
        ]
        assert any("invalid action syntax" in warning for warning in preview["warnings"])
        assert json.loads(config_json.read_text(encoding="utf-8"))["settings"]["interaction"]["combo_term"] == 0.04

        saved = interaction_api.save_interaction_settings(
            config_json,
            vial_json,
            {
                "tapping_term": 0.2,
                "hold_on_other_key_press": False,
                "combos": [{"keys": [[1, 1], [1, 2]], "action": "KC_TAB"}],
            },
        )
        assert saved["result"] == "ok"
        assert saved["settings"]["hold_on_other_key_press"] is False
        stored = json.loads(config_json.read_text(encoding="utf-8"))
        assert stored["settings"]["interaction"]["combos"] == [{"keys": [[1, 1], [1, 2]], "action": "KC_TAB"}]
        assert stored["layers"] == {"0": {}}

    print("ok: HTTP interaction API helpers")


if __name__ == "__main__":
    main()
