"""Read-only metadata for the 4.3 inch touch-panel flick input profile."""
from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
import sys
from typing import Any

try:
    from aiohttp import web
except ModuleNotFoundError:  # Allow local resolver tests without the HTTP runtime dependency.
    web = None  # type: ignore[assignment]

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "daemon"))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from logicd.touch_flick_composition import (
    COMPOSITION_BLOCKED_OUTPUTS,
    COMPOSITION_BLOCKING_REASON_POLICY,
    TOUCH_FLICK_COMPOSITION_MODE,
    TOUCH_FLICK_WINDOWS_IME_PROFILE,
    romaji_taps_for_text_action,
)
from text_send_safety_api import TEXT_SEND_PLAN_ROUTE, TEXT_SEND_SAFETY_ROUTE
from hidloom_paths import default_config_dir

TOUCH_PANEL_FLICK_ROUTE = "/api/touch-panel/flick"
TOUCH_PANEL_FLICK_RESOLVE_ROUTE = "/api/touch-panel/flick/resolve"
TOUCH_PANEL_FLICK_DISPATCH_ROUTE = "/api/touch-panel/flick/dispatch"
TOUCH_PANEL_FLICK_COMPOSITION_PLAN_ROUTE = "/api/touch-panel/flick/composition-plan"
TARGET_TOUCH_PANEL_PROFILE = "osoyoo-4.3"
DEFAULT_TOUCH_PANEL_PROFILE_FILE = "/mnt/p3/touch_panel_profile.json"
DEFAULT_TOUCH_PANEL_FLICK_CONFIG_FILE = "/mnt/p3/flick.json"
REPO_TOUCH_PANEL_FLICK_CONFIG_FILE = (
    default_config_dir(Path(__file__).resolve().parents[2]) / "touch-panel" / TARGET_TOUCH_PANEL_PROFILE / "flick.json"
)
TOUCH_FLICK_DIRECTIONS = ("center", "up", "right", "down", "left")
_SEND_STRING_ACTION_RE = re.compile(r"^(?:TEXT|SEND_STRING)\([A-Za-z0-9_.-]{1,48}\)$")
FORBIDDEN_DISPATCH_EVENT_FIELDS = (
    "preview_state",
    "requested_direction",
    "resolved_direction",
    "requestedDirection",
    "resolvedDirection",
)
SendCtrl = Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]]


class _LocalJsonResponse:
    def __init__(self, payload: dict[str, Any], status: int = 200) -> None:
        self.status = status
        self.text = json.dumps(payload, ensure_ascii=False)


def _json_response(payload: dict[str, Any], *, status: int = 200) -> Any:
    if web is not None:
        return web.json_response(payload, status=status)
    return _LocalJsonResponse(payload, status)

def _read_touch_panel_profile(marker_path: Path) -> dict[str, Any]:
    if not marker_path.exists():
        return {
            "source": "missing",
            "marker_path": str(marker_path),
            "profile": None,
            "matches_target": False,
        }
    try:
        data = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "source": "error",
            "marker_path": str(marker_path),
            "profile": None,
            "matches_target": False,
            "error": str(exc),
        }
    if not isinstance(data, dict):
        return {
            "source": "error",
            "marker_path": str(marker_path),
            "profile": None,
            "matches_target": False,
            "error": "marker root must be object",
        }
    profile = data.get("profile")
    profile = profile if isinstance(profile, str) and profile else None
    return {
        "source": "marker",
        "marker_path": str(marker_path),
        "profile": profile,
        "reason": data.get("reason") if isinstance(data.get("reason"), str) else None,
        "sizes": data.get("sizes") if isinstance(data.get("sizes"), list) else [],
        "matches_target": profile == TARGET_TOUCH_PANEL_PROFILE,
    }


def _text_action(label: str) -> dict[str, str]:
    if _SEND_STRING_ACTION_RE.fullmatch(label):
        return {
            "label": label,
            "action": label,
            "output": "text",
            "text_family": "named_send_string",
            "preflight_route": TEXT_SEND_PLAN_ROUTE,
        }
    if len(label) != 1:
        return {"label": label, "action": label, "output": "text"}
    return {
        "label": label,
        "action": f"U+{ord(label):04X}",
        "output": "text",
    }


def _key_action(label: str, action: str) -> dict[str, str]:
    return {
        "label": label,
        "action": action,
        "output": "keycode",
    }


def _ime_control(key: str, label: str, role: str, action: str, alternatives: list[str] | None = None) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "role": role,
        "action": action,
        "alternatives": alternatives or [],
        "output": "keycode",
    }


def _read_flick_config(config_path: str | Path = DEFAULT_TOUCH_PANEL_FLICK_CONFIG_FILE) -> dict[str, Any]:
    primary = Path(config_path)
    candidates = [primary]
    if primary == Path(DEFAULT_TOUCH_PANEL_FLICK_CONFIG_FILE):
        candidates.append(REPO_TOUCH_PANEL_FLICK_CONFIG_FILE)
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            return data
    return {"columns": 3, "rows": 4, "layers": []}


def _action_metadata(value: Any, fallback_label: str = "") -> dict[str, str] | None:
    if isinstance(value, dict):
        action = value.get("action")
        output = value.get("output")
        label = value.get("label")
        if isinstance(action, str) and action:
            named_text = _SEND_STRING_ACTION_RE.fullmatch(action)
            return {
                "label": label if isinstance(label, str) else fallback_label or action,
                "action": action,
                "output": output if isinstance(output, str) and output else "keycode" if action.startswith("KC_") else "text",
                **({
                    "text_family": "named_send_string",
                    "preflight_route": TEXT_SEND_PLAN_ROUTE,
                } if named_text else {}),
            }
        value = label
    if not isinstance(value, str) or not value:
        return None
    if value.startswith("KC_"):
        return _key_action(value.replace("KC_", ""), value)
    if value.startswith("U+"):
        return {"label": fallback_label or value, "action": value, "output": "text"}
    return _text_action(value)


def _normalize_flick_pad(raw_pad: Any, layer_index: int, pad_index: int) -> dict[str, Any] | None:
    if not isinstance(raw_pad, dict):
        return None
    key = raw_pad.get("key")
    label = raw_pad.get("label")
    actions = raw_pad.get("actions")
    if not isinstance(key, str) or not key or not isinstance(actions, dict):
        return None
    normalized_actions: dict[str, dict[str, str]] = {}
    for direction in TOUCH_FLICK_DIRECTIONS:
        action = _action_metadata(actions.get(direction), fallback_label=direction)
        if action:
            normalized_actions[direction] = action
    if not normalized_actions:
        return None
    return {
        "key": key,
        "label": label if isinstance(label, str) and label else key,
        "layer": layer_index,
        "index": pad_index,
        "actions": normalized_actions,
    }


def touch_flick_layout_metadata(config_path: str | Path = DEFAULT_TOUCH_PANEL_FLICK_CONFIG_FILE) -> dict[str, Any]:
    config = _read_flick_config(config_path)
    layers: list[dict[str, Any]] = []
    for layer_index, raw_layer in enumerate(config.get("layers", [])):
        if not isinstance(raw_layer, dict):
            continue
        raw_pads = raw_layer.get("pads")
        if not isinstance(raw_pads, list):
            continue
        pads = [
            pad
            for pad_index, raw_pad in enumerate(raw_pads)
            if (pad := _normalize_flick_pad(raw_pad, layer_index, pad_index)) is not None
        ]
        layers.append({
            "index": layer_index,
            "name": raw_layer.get("name") if isinstance(raw_layer.get("name"), str) else f"layer-{layer_index}",
            "pads": pads,
        })
    return {
        "columns": config.get("columns") if isinstance(config.get("columns"), int) else 3,
        "rows": config.get("rows") if isinstance(config.get("rows"), int) else 4,
        "directions": list(TOUCH_FLICK_DIRECTIONS),
        "layers": layers,
        "pads": layers[0]["pads"] if layers else [],
        "config_path": str(config_path),
    }


def touch_flick_named_text_summary(layout: dict[str, Any]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for layer in layout.get("layers", []):
        if not isinstance(layer, dict):
            continue
        for pad in layer.get("pads", []):
            if not isinstance(pad, dict):
                continue
            for direction, action in (pad.get("actions") or {}).items():
                if not isinstance(action, dict) or action.get("text_family") != "named_send_string":
                    continue
                entries.append({
                    "layer": layer.get("index"),
                    "layer_name": layer.get("name"),
                    "pad": pad.get("key"),
                    "label": pad.get("label"),
                    "direction": direction,
                    "action": action.get("action"),
                    "preflight_route": action.get("preflight_route"),
                })
    return {
        "schema": "touch_panel.flick.named_text_summary.v1",
        "entry_count": len(entries),
        "entries": entries,
        "preflight_route": TEXT_SEND_PLAN_ROUTE,
    }


def flick_pad_metadata(layer: int = 0, config_path: str | Path = DEFAULT_TOUCH_PANEL_FLICK_CONFIG_FILE) -> list[dict[str, Any]]:
    layers = touch_flick_layout_metadata(config_path).get("layers", [])
    if not layers:
        return []
    selected = layers[layer] if 0 <= layer < len(layers) else layers[0]
    return selected.get("pads", [])


def ime_control_metadata() -> list[dict[str, Any]]:
    return [
        _ime_control("convert", "変換", "convert_or_next_candidate", "KC_SPC"),
        _ime_control("nonconvert", "無変換", "commit_without_conversion", "KC_ENTER"),
        _ime_control("commit", "確定", "commit_composition_or_candidate", "KC_ENTER"),
        _ime_control("candidate_prev", "候補↑", "previous_candidate", "KC_UP"),
        _ime_control("candidate_next", "候補↓", "next_candidate", "KC_DOWN", ["KC_SPC"]),
        _ime_control("cancel", "取消", "cancel_composition_or_candidate", "KC_ESC"),
    ]


def touch_flick_host_ime_profile_metadata() -> dict[str, Any]:
    return {
        "owner": "http.touch_panel_flick_api",
        "auto_detection": False,
        "explicit_profile_required": True,
        "active_profile": None,
        "default_dispatch_allowed": False,
        "warning": "host IME profile must be selected before browser dispatch is enabled",
        "profiles": [
            {
                "key": TOUCH_FLICK_WINDOWS_IME_PROFILE,
                "label": "Windows 11 / Microsoft IME",
                "layout": "US keyboard compatible keycodes",
                "ime_owner": "host",
                "composition_owner": "host_ime",
                "conversion_owner": "host_ime",
                "unicode_smoke": {
                    "verified": True,
                    "date": "2026-06-01",
                    "host": "<keyboard-host> / Windows 11 / Microsoft IME",
                    "path": "local U+XXXX",
                    "sample": "あいうえお、。ーがぱぁゃア日本語",
                },
                "controls": {
                    "convert": "KC_SPC",
                    "nonconvert": "KC_ENTER",
                    "commit": "KC_ENTER",
                    "candidate_next": "KC_DOWN",
                    "candidate_prev": "KC_UP",
                    "cancel": "KC_ESC",
                },
                "dispatch_gate": {
                    "browser_default_enabled": False,
                    "requires_warning_ack": True,
                    "requires_runner_cancel_path": True,
                },
                "composition_mode": {
                    "mode": TOUCH_FLICK_COMPOSITION_MODE,
                    "plan_route": TOUCH_PANEL_FLICK_COMPOSITION_PLAN_ROUTE,
                    "uses_us_keyboard_keycodes_only": True,
                    "default_dispatch_allowed": False,
                    "composition_owner": "host_ime",
                },
            }
        ],
    }


def _resolve_action(actions: dict[str, dict[str, str]], direction: str) -> tuple[str, dict[str, str] | None]:
    if direction in actions:
        return direction, actions[direction]
    if "center" in actions:
        return "center", actions["center"]
    return direction, None


def resolve_flick_pad_action(
    pad_key: str = "",
    direction: str = "center",
    *,
    layer: int = 0,
    index: int | None = None,
    config_path: str | Path = DEFAULT_TOUCH_PANEL_FLICK_CONFIG_FILE,
) -> dict[str, Any]:
    requested_direction = direction if direction in TOUCH_FLICK_DIRECTIONS else "center"
    pads = flick_pad_metadata(layer, config_path)
    for pad in pads:
        if index is not None and pad.get("index") != index:
            continue
        if index is None and pad.get("key") != pad_key:
            continue
        resolved_direction, action = _resolve_action(pad.get("actions", {}), requested_direction)
        if not action:
            return {
                "result": "error",
                "kind": "flick_pad",
                "key": pad_key or pad.get("key", ""),
                "layer": layer,
                "index": pad.get("index", index),
                "requested_direction": requested_direction,
                "reason": "missing_action",
            }
        return {
            "result": "ok",
            "kind": "flick_pad",
            "key": pad.get("key", pad_key),
            "layer": layer,
            "index": pad.get("index", index),
            "label": pad.get("label", pad_key),
            "requested_direction": requested_direction,
            "resolved_direction": resolved_direction,
            "action": action,
            "dispatch": "preview_noop",
        }
    return {
        "result": "error",
        "kind": "flick_pad",
        "key": pad_key,
        "layer": layer,
        "index": index,
        "requested_direction": requested_direction,
        "reason": "unknown_pad",
    }


def resolve_ime_control_action(control_key: str) -> dict[str, Any]:
    for control in ime_control_metadata():
        if control.get("key") != control_key:
            continue
        return {
            "result": "ok",
            "kind": "ime_control",
            "key": control_key,
            "label": control.get("label", control_key),
            "role": control.get("role"),
            "action": {
                "label": control.get("label", control_key),
                "action": control.get("action"),
                "output": control.get("output", "keycode"),
            },
            "dispatch": "preview_noop",
        }
    return {
        "result": "error",
        "kind": "ime_control",
        "key": control_key,
        "reason": "unknown_control",
    }


def build_touch_flick_dispatch_event(resolved: dict[str, Any]) -> dict[str, Any]:
    action = resolved.get("action") if isinstance(resolved.get("action"), dict) else {}
    output = action.get("output") if isinstance(action.get("output"), str) else "preview"
    return {
        "source": "touch_panel_flick",
        "kind": resolved.get("kind"),
        "key": resolved.get("key"),
        "layer": resolved.get("layer"),
        "index": resolved.get("index"),
        "action": action.get("action"),
        "output": output,
        "dispatch": "tap_action",
        "enabled": True,
    }


def _romaji_taps_for_action(action: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    raw_action = action.get("action") if isinstance(action.get("action"), str) else ""
    output = action.get("output") if isinstance(action.get("output"), str) else ""
    return romaji_taps_for_text_action(raw_action, output)


def build_touch_flick_composition_plan(resolved: dict[str, Any]) -> dict[str, Any]:
    """Build a read-only host IME composition plan without dispatching."""
    if not isinstance(resolved, dict) or resolved.get("result") != "ok":
        return {
            "result": "error",
            "schema": "touch_panel.flick.composition_plan.v1",
            "reason": "resolved_action_required",
        }
    action = resolved.get("action") if isinstance(resolved.get("action"), dict) else {}
    taps, blocking = _romaji_taps_for_action(action)
    output = action.get("output") if isinstance(action.get("output"), str) else ""
    not_applicable = output != "text"
    return {
        "result": "ok",
        "schema": "touch_panel.flick.composition_plan.v1",
        "read_only": True,
        "sends_hid_reports": False,
        "mode": TOUCH_FLICK_COMPOSITION_MODE,
        "host_profile": TOUCH_FLICK_WINDOWS_IME_PROFILE,
        "host_ime_owner": "host",
        "composition_owner": "host_ime",
        "resolved_action": resolved,
        "available": not not_applicable and not blocking,
        "not_applicable": not_applicable,
        "not_applicable_reason": "keycode_action_not_text_composition" if not_applicable else "",
        "blocking_reasons": blocking,
        "blocking_reason_policy": COMPOSITION_BLOCKING_REASON_POLICY,
        "blocked_outputs": list(COMPOSITION_BLOCKED_OUTPUTS),
        "tap_sequence": taps,
        "commit_action": "KC_ENTER",
        "convert_action": "KC_SPC",
        "cancel_action": "KC_ESC",
        "notes": [
            "This plan is metadata only; it does not send HID reports.",
            "Kana is entered as US keyboard romaji so the host IME owns composition and conversion.",
            "Dakuten, handakuten, small kana, comma, period, and long vowel mark use explicit romaji/keycode policy.",
            "Katakana, emoji, IME-specific marks, non-ASCII symbols, JIS-kana layout dependent keys, and named text actions have explicit blocking policy.",
        ],
    }


def resolve_touch_panel_flick_composition_plan_request(
    body: Any,
    *,
    config_path: str | Path = DEFAULT_TOUCH_PANEL_FLICK_CONFIG_FILE,
) -> dict[str, Any]:
    resolved = resolve_touch_panel_flick_request(body, config_path=config_path)
    if resolved.get("result") != "ok":
        return {
            "result": "error",
            "schema": "touch_panel.flick.composition_plan.v1",
            "reason": resolved.get("reason", "resolve_failed"),
            "resolve": resolved,
        }
    return build_touch_flick_composition_plan(resolved["resolved_action"])


def resolve_touch_panel_flick_request(
    body: Any,
    *,
    config_path: str | Path = DEFAULT_TOUCH_PANEL_FLICK_CONFIG_FILE,
) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {"result": "error", "reason": "body_must_be_object"}
    kind = body.get("kind")
    if kind not in {"flick_pad", "ime_control"}:
        return {"result": "error", "reason": "unknown_kind"}
    if kind == "flick_pad":
        key = body.get("key")
        index = body.get("index")
        layer = body.get("layer", 0)
        if not isinstance(key, str):
            key = ""
        if not isinstance(index, int):
            index = None
        if not isinstance(layer, int):
            layer = 0
        if not key and index is None:
            return {"result": "error", "reason": "missing_key"}
        direction = body.get("direction", "center")
        direction = direction if isinstance(direction, str) else "center"
        resolved = resolve_flick_pad_action(key, direction, layer=layer, index=index, config_path=config_path)
    else:
        key = body.get("key")
        if not isinstance(key, str) or not key:
            return {"result": "error", "reason": "missing_key"}
        resolved = resolve_ime_control_action(key)
    if resolved.get("result") != "ok":
        return {
            "result": "error",
            "schema": "touch_panel.flick.resolve.v1",
            "kind": kind,
            "key": key,
            "reason": resolved.get("reason", "resolve_failed"),
        }
    return {
        "result": "ok",
        "schema": "touch_panel.flick.resolve.v1",
        "final_action_only": True,
        "preview_state_included": False,
        "dispatch": "tap_action",
        "resolved_action": resolved,
        "dispatch_event": build_touch_flick_dispatch_event(resolved),
    }


def resolve_touch_panel_flick_dispatch_request(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {"result": "error", "reason": "body_must_be_object"}
    event = body.get("event")
    if not isinstance(event, dict):
        return {"result": "error", "reason": "event_must_be_object"}
    forbidden = sorted(field for field in FORBIDDEN_DISPATCH_EVENT_FIELDS if field in event)
    if forbidden:
        return {
            "result": "error",
            "reason": "preview_state_not_dispatch_payload",
            "fields": forbidden,
        }
    return {
        "result": "ok",
        "schema": "touch_panel.flick.dispatch.v1",
        "final_action_only": True,
        "preview_state_included": False,
        "command": {"t": "TOUCH_FLICK", "event": event},
    }


def touch_panel_flick_payload(
    marker_path: str | Path = DEFAULT_TOUCH_PANEL_PROFILE_FILE,
    config_path: str | Path = DEFAULT_TOUCH_PANEL_FLICK_CONFIG_FILE,
) -> dict[str, Any]:
    marker = _read_touch_panel_profile(Path(marker_path))
    layout = touch_flick_layout_metadata(config_path)
    return {
        "result": "ok",
        "route": TOUCH_PANEL_FLICK_ROUTE,
        "schema": "touch_panel.flick.v1",
        "read_only": True,
        "target_profile": TARGET_TOUCH_PANEL_PROFILE,
        "enabled": False,
        "available": bool(marker.get("matches_target")),
        "profile_guard": marker,
        "unicode_prerequisite": {
            "route": TEXT_SEND_SAFETY_ROUTE,
            "plan_route": TEXT_SEND_PLAN_ROUTE,
            "kana_output": "flick_definition_to_unicode_action",
            "named_text_output": "TEXT(name)_or_SEND_STRING(name)",
            "text_output_preflight": "action_level_plan_required",
        },
        "composition_mode": {
            "schema": "touch_panel.flick.composition_plan.v1",
            "read_only": True,
            "mode": TOUCH_FLICK_COMPOSITION_MODE,
            "plan_route": TOUCH_PANEL_FLICK_COMPOSITION_PLAN_ROUTE,
            "host_profile": TOUCH_FLICK_WINDOWS_IME_PROFILE,
            "host_ime_owner": "host",
            "composition_owner": "host_ime",
            "uses_us_keyboard_keycodes_only": True,
            "default_dispatch_allowed": False,
            "initial_scope": [
                "basic_kana_rows",
                "dakuten_rows",
                "handakuten_rows",
                "small_vowels",
                "small_ya_yu_yo",
                "basic_japanese_punctuation",
                "full_width_digits",
                "us_shifted_symbol_aliases",
            ],
            "blocked_outputs": list(COMPOSITION_BLOCKED_OUTPUTS),
            "blocking_reason_policy": COMPOSITION_BLOCKING_REASON_POLICY,
            "commit_action": "KC_ENTER",
            "convert_action": "KC_SPC",
            "cancel_action": "KC_ESC",
            "helpers": [
                "build_touch_flick_composition_plan",
                "resolve_touch_panel_flick_composition_plan_request",
            ],
        },
        "event_boundary": {
            "owner": "browser",
            "final_action_only": True,
            "preview_is_runtime_ui_only": True,
            "threshold_px": 28,
            "directions": list(TOUCH_FLICK_DIRECTIONS),
            "cancel_hooks": ["pointercancel", "visibilitychange", "tab_switch", "shutdown_menu"],
        },
        "action_resolution": {
            "owner": "http.touch_panel_flick_api",
            "final_action_only": True,
            "preview_state_is_not_dispatch_payload": True,
            "dispatch": "tap_action",
            "resolve_route": TOUCH_PANEL_FLICK_RESOLVE_ROUTE,
            "dispatch_route": TOUCH_PANEL_FLICK_DISPATCH_ROUTE,
            "composition_plan_route": TOUCH_PANEL_FLICK_COMPOSITION_PLAN_ROUTE,
            "helpers": [
                "resolve_flick_pad_action",
                "resolve_ime_control_action",
                "resolve_touch_panel_flick_request",
                "resolve_touch_panel_flick_dispatch_request",
                "resolve_touch_panel_flick_composition_plan_request",
                "build_touch_flick_dispatch_event",
                "build_touch_flick_composition_plan",
            ],
        },
        "dispatch_policy": {
            "owner": "http.touch_panel_flick_api",
            "dispatch_route": TOUCH_PANEL_FLICK_DISPATCH_ROUTE,
            "browser_default_enabled": False,
            "browser_may_call_dispatch": True,
            "browser_requires_local_enable": True,
            "preview_noop_is_blocked": True,
            "allowed_event": {
                "enabled": True,
                "dispatch": "tap_action",
                "output": "keycode_or_ready_text",
            },
            "forbidden_event_fields": list(FORBIDDEN_DISPATCH_EVENT_FIELDS),
            "blocked_outputs": {
                "preview": "preview_only",
            },
            "required_before_text_dispatch": ["text_send_runner_must_not_target_kiosk_window"],
            "text_output_preflight_route": TEXT_SEND_PLAN_ROUTE,
        },
        "layout": {
            **layout,
        },
        "named_text": touch_flick_named_text_summary(layout),
        "named_text_assignment": {
            "schema": "touch_panel.flick.named_text_assignment.v1",
            "status": "metadata_flow_fixed",
            "source": "settings.send_strings",
            "settings_route": "/api/settings/send-strings",
            "action_format": ["TEXT(name)", "SEND_STRING(name)"],
            "edit_flow": [
                "create_or_update_named_entry_in_settings",
                "copy_TEXT_name_from_settings_row",
                "assign_action_in_flick_json",
                "reload_touch_panel_profile_or_httpd",
                "verify_named_text_summary_badge_title_and_text_plan",
            ],
            "runtime_editor": False,
            "runtime_editor_reason": "flick.json remains the touch-panel pad definition owner for this slice",
            "verification": {
                "summary": "named_text",
                "badge": "named-text",
                "title_fields": ["direction", "action", "text_family", "preflight"],
                "plan_preview": "text-plan:ready/taps:N or blocking reason",
                "preflight_route": TEXT_SEND_PLAN_ROUTE,
            },
        },
        "ime_controls": {
            "owner": "host_ime",
            "key_actions_only": True,
            "default_output": "tap_action",
            "controls": ime_control_metadata(),
            "us_keyboard_ime_profile": {
                "convert": "KC_SPC",
                "nonconvert": "KC_ENTER",
                "commit": "KC_ENTER",
                "cancel": "KC_ESC",
                "candidate_navigation": ["KC_SPC", "KC_UP", "KC_DOWN", "KC_ENTER"],
                "uses_us_keyboard_keycodes_only": True,
                "requires_real_device_smoke": True,
            },
        },
        "host_ime_profile": touch_flick_host_ime_profile_metadata(),
        "warnings": [
            "kana text actions are resolved from flick.json into U+XXXX dispatch actions",
            "host IME / layout is not auto-detected",
            "waveshare-8.8 uses a separate profile and is outside this endpoint contract",
        ],
    }


async def touch_panel_flick_response(marker_path: str | Path = DEFAULT_TOUCH_PANEL_PROFILE_FILE) -> web.Response:
    return _json_response(touch_panel_flick_payload(marker_path))


async def touch_panel_flick_resolve_response(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        return _json_response({"result": "error", "msg": "Invalid JSON"}, status=400)
    result = resolve_touch_panel_flick_request(body)
    status = 200 if result.get("result") == "ok" else 400
    return _json_response(result, status=status)


async def touch_panel_flick_composition_plan_response(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        return _json_response({"result": "error", "msg": "Invalid JSON"}, status=400)
    result = resolve_touch_panel_flick_composition_plan_request(body)
    status = 200 if result.get("result") == "ok" else 400
    return _json_response(result, status=status)


async def touch_panel_flick_dispatch_response(request: web.Request, send_ctrl_command: SendCtrl | None) -> web.Response:
    if send_ctrl_command is None:
        return _json_response({"result": "error", "msg": "logicd dispatch unavailable"}, status=503)
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        return _json_response({"result": "error", "msg": "Invalid JSON"}, status=400)
    result = resolve_touch_panel_flick_dispatch_request(body)
    if result.get("result") != "ok":
        return _json_response(result, status=400)
    resp = await send_ctrl_command(result["command"])
    if resp is None:
        return _json_response({"result": "error", "msg": "logicd unavailable"}, status=503)
    ctrl_result = resp.get("result")
    status = 200 if ctrl_result in {"ok", "blocked"} else 502
    return _json_response({
        "result": ctrl_result or "error",
        "schema": "touch_panel.flick.dispatch.v1",
        "final_action_only": True,
        "preview_state_included": False,
        "source": "logicd ctrl TOUCH_FLICK",
        "ctrl": resp,
    }, status=status)


def register_touch_panel_flick_route(
    app: web.Application,
    send_ctrl_command: SendCtrl | None = None,
    marker_path: str | Path = DEFAULT_TOUCH_PANEL_PROFILE_FILE,
) -> None:
    if web is None:
        raise RuntimeError("aiohttp is required to register HTTP routes")

    async def handle_touch_panel_flick(_request: web.Request) -> web.Response:
        return await touch_panel_flick_response(marker_path)

    async def handle_touch_panel_flick_dispatch(request: web.Request) -> web.Response:
        return await touch_panel_flick_dispatch_response(request, send_ctrl_command)

    app.router.add_get(TOUCH_PANEL_FLICK_ROUTE, handle_touch_panel_flick)
    app.router.add_post(TOUCH_PANEL_FLICK_RESOLVE_ROUTE, touch_panel_flick_resolve_response)
    app.router.add_post(TOUCH_PANEL_FLICK_COMPOSITION_PLAN_ROUTE, touch_panel_flick_composition_plan_response)
    app.router.add_post(TOUCH_PANEL_FLICK_DISPATCH_ROUTE, handle_touch_panel_flick_dispatch)
