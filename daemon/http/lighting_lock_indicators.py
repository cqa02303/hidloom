"""HTTP helpers for persistent host lock LED indicator settings."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Awaitable, Callable, Mapping, Optional

from aiohttp import web

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hidloom_paths import default_config_file

LEDD_JSON = default_config_file("ledd.json", _REPO_ROOT)
SendCtrlCommand = Callable[[dict[str, Any]], Awaitable[Optional[dict[str, Any]]]]

LOCK_STATES = ("caps_lock", "num_lock", "scroll_lock", "compose", "kana")
DEFAULT_REACTIVE_EXCLUDE_ROLES = ("modifier", "function", "layer", "lock")
VALID_REACTIVE_ROLES = ("normal", "modifier", "function", "layer", "lock", "script", "system")
DEFAULT_COLORS = {
    "caps_lock": [255, 0, 0],
    "num_lock": [0, 0, 255],
    "scroll_lock": [0, 255, 0],
    "compose": [255, 128, 0],
    "kana": [255, 0, 255],
}
DEFAULT_KEYS = {
    "caps_lock": ["KC_CAPS", "KC_CAPSLOCK"],
    "num_lock": ["KC_NUM", "KC_NUMLOCK", "KC_NLCK"],
    "scroll_lock": ["KC_SCROLL", "KC_SCROLLLOCK", "KC_SLCK"],
    "compose": ["KC_COMPOSE"],
    "kana": ["KC_KANA", "KC_INT2"],
}


def _load_ledd(path: Path = LEDD_JSON) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_ledd(data: Mapping[str, Any], path: Path = LEDD_JSON) -> None:
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


async def _request_ledd_reload(send_ctrl_command: SendCtrlCommand | None) -> dict[str, Any]:
    if send_ctrl_command is None:
        return {"requested": False, "result": "unavailable"}
    resp = await send_ctrl_command({"t": "LEDD_RELOAD", "target": "semantic_roles"})
    if resp is None:
        return {"requested": True, "result": "error", "msg": "logicd unavailable"}
    return {
        "requested": True,
        "result": "ok" if resp.get("result") == "ok" else "error",
        "response": resp,
    }


def _color(value: Any, *, field: str) -> list[int]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{field} must be [r,g,b]")
    out = []
    for item in value:
        if not isinstance(item, int) or item < 0 or item > 255:
            raise ValueError(f"{field} must be [r,g,b] bytes")
        out.append(int(item))
    return out


def _string_list(value: Any, *, field: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [part.strip() for part in value.replace(";", "\n").split()]
        return [item for item in items if item]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of strings")
    return [item.strip() for item in value if item.strip()]


def _state_from_raw(name: str, value: Mapping[str, Any] | None, *, default_enabled: bool = False) -> dict[str, Any]:
    value = value or {}
    return {
        "enabled": bool(value) if value else bool(default_enabled),
        "follow_keys": bool(value.get("follow_keys", True)),
        "keys": list(value.get("keys", DEFAULT_KEYS[name])),
        "extra_leds": list(value.get("extra_leds", value.get("leds", []))),
        "color": list(value.get("color", DEFAULT_COLORS[name])),
        "key_colors": dict(value.get("key_colors", {})),
    }


def _led_positions(leds: Any) -> dict[str, dict[str, float]]:
    if not isinstance(leds, Mapping):
        return {}
    out: dict[str, dict[str, float]] = {}
    for led_id, raw in leds.items():
        if not isinstance(raw, Mapping):
            continue
        try:
            out[str(led_id)] = {"x": float(raw["x"]), "y": float(raw["y"])}
        except (KeyError, TypeError, ValueError):
            continue
    return out


def build_lock_indicator_payload(ledd: Mapping[str, Any]) -> dict[str, Any]:
    semantic = ledd.get("semantic_roles", {})
    if not isinstance(semantic, Mapping):
        semantic = {}
    raw = semantic.get("lock_indicators", {})
    if not isinstance(raw, Mapping):
        raw = {}
    has_lock_indicator_config = "lock_indicators" in semantic and bool(raw)
    raw_states = raw.get("states", {})
    if not isinstance(raw_states, Mapping):
        raw_states = {}

    legacy_overlays = semantic.get("state_overlays", {})
    if not isinstance(legacy_overlays, Mapping):
        legacy_overlays = {}

    states: dict[str, dict[str, Any]] = {}
    for name in LOCK_STATES:
        value = raw_states.get(name)
        if value is None and name in legacy_overlays and isinstance(legacy_overlays[name], Mapping):
            value = legacy_overlays[name]
        states[name] = _state_from_raw(
            name,
            value if isinstance(value, Mapping) else None,
            default_enabled=not has_lock_indicator_config and value is None,
        )
    leds = ledd.get("leds", {})
    return {
        "result": "ok",
        "blend": str(raw.get("blend", "max")),
        "states": states,
        "reactive": _reactive_payload(semantic.get("reactive", {})),
        "default_keys": {name: list(keys) for name, keys in DEFAULT_KEYS.items()},
        "led_keys": list(leds.keys()) if isinstance(leds, Mapping) else [],
        "led_positions": _led_positions(leds),
    }


def _reactive_exclude_roles(raw: Any) -> list[str]:
    if not isinstance(raw, Mapping):
        raw = {}
    exclude = raw.get("exclude_roles", list(DEFAULT_REACTIVE_EXCLUDE_ROLES))
    if exclude is None:
        out = list(DEFAULT_REACTIVE_EXCLUDE_ROLES)
    elif not isinstance(exclude, list):
        out = list(DEFAULT_REACTIVE_EXCLUDE_ROLES)
    else:
        out = []
        for role in exclude:
            value = str(role)
            if value in VALID_REACTIVE_ROLES and value not in out:
                out.append(value)
    flag = raw.get("modifier_triggers_effects")
    if flag is True:
        out = [role for role in out if role != "modifier"]
    elif flag is False and "modifier" not in out:
        out = ["modifier", *out]
    return out


def _reactive_payload(raw: Any) -> dict[str, Any]:
    exclude_roles = _reactive_exclude_roles(raw)
    return {
        "exclude_roles": exclude_roles,
        "modifier_triggers_effects": "modifier" not in exclude_roles,
    }


def normalize_lock_indicator_update(body: Mapping[str, Any]) -> dict[str, Any]:
    blend = str(body.get("blend", "max")).strip().lower()
    if blend not in {"priority", "max", "add"}:
        raise ValueError("blend must be priority, max, or add")
    raw_states = body.get("states", {})
    if not isinstance(raw_states, Mapping):
        raise ValueError("states must be an object")
    states: dict[str, dict[str, Any]] = {}
    for name in LOCK_STATES:
        value = raw_states.get(name, {})
        if not isinstance(value, Mapping):
            raise ValueError(f"states.{name} must be an object")
        if not bool(value.get("enabled", False)):
            continue
        states[name] = {
            "follow_keys": bool(value.get("follow_keys", True)),
            "keys": _string_list(value.get("keys", DEFAULT_KEYS[name]), field=f"states.{name}.keys"),
            "extra_leds": _string_list(value.get("extra_leds", []), field=f"states.{name}.extra_leds"),
            "color": _color(value.get("color", DEFAULT_COLORS[name]), field=f"states.{name}.color"),
        }
        key_colors = value.get("key_colors", {})
        if key_colors:
            if not isinstance(key_colors, Mapping):
                raise ValueError(f"states.{name}.key_colors must be an object")
            states[name]["key_colors"] = {
                str(key): _color(color, field=f"states.{name}.key_colors.{key}")
                for key, color in key_colors.items()
            }
    return {"blend": blend, "states": states}


def apply_lock_indicator_update(ledd: dict[str, Any], update: Mapping[str, Any]) -> dict[str, Any]:
    semantic = ledd.setdefault("semantic_roles", {})
    if not isinstance(semantic, dict):
        raise ValueError("semantic_roles must be an object")
    overlays = semantic.get("state_overlays", {})
    if isinstance(overlays, dict):
        for name in LOCK_STATES:
            overlays.pop(name, None)
    semantic["lock_indicators"] = {"blend": update["blend"], "states": update["states"]}
    return ledd


def apply_reactive_update(ledd: dict[str, Any], body: Mapping[str, Any]) -> dict[str, Any]:
    reactive_update = body.get("reactive")
    if reactive_update is None:
        return ledd
    if not isinstance(reactive_update, Mapping):
        raise ValueError("reactive must be an object")
    if "modifier_triggers_effects" not in reactive_update:
        return ledd
    value = reactive_update.get("modifier_triggers_effects")
    if not isinstance(value, bool):
        raise ValueError("reactive.modifier_triggers_effects must be boolean")
    semantic = ledd.setdefault("semantic_roles", {})
    if not isinstance(semantic, dict):
        raise ValueError("semantic_roles must be an object")
    reactive = semantic.setdefault("reactive", {})
    if not isinstance(reactive, dict):
        raise ValueError("semantic_roles.reactive must be an object")
    exclude_roles = _reactive_exclude_roles(reactive)
    if value:
        exclude_roles = [role for role in exclude_roles if role != "modifier"]
    elif "modifier" not in exclude_roles:
        exclude_roles = ["modifier", *exclude_roles]
    reactive["modifier_triggers_effects"] = value
    reactive["exclude_roles"] = exclude_roles
    return ledd


async def lighting_lock_indicators_get_response() -> web.Response:
    try:
        return web.json_response(build_lock_indicator_payload(_load_ledd()))
    except OSError as exc:
        return web.json_response({"result": "error", "msg": str(exc)}, status=500)


async def lighting_lock_indicators_put_response(
    request: web.Request,
    send_ctrl_command: SendCtrlCommand | None = None,
) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"result": "error", "msg": "Invalid JSON"}, status=400)
    if not isinstance(body, Mapping):
        return web.json_response({"result": "error", "msg": "Invalid JSON"}, status=400)
    try:
        ledd = _load_ledd()
        if "states" in body or "blend" in body:
            update = normalize_lock_indicator_update(body)
            ledd = apply_lock_indicator_update(ledd, update)
        ledd = apply_reactive_update(ledd, body)
        _write_ledd(ledd)
        payload = build_lock_indicator_payload(ledd)
    except (OSError, ValueError, TypeError) as exc:
        return web.json_response({"result": "error", "msg": str(exc)}, status=400)
    reload_result = await _request_ledd_reload(send_ctrl_command)
    return web.json_response({**payload, "saved": True, "reload": reload_result})
