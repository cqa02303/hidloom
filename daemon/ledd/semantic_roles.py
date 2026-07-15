#!/usr/bin/env python3
"""Semantic LED role normalization helpers for ledd.

This module is intentionally side-effect free. It defines the config shape
that lets ledd distinguish key meaning (modifier, layer, lock, script, ...)
from animation rendering without pulling in GPIO or direct-frame dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

VALID_ROLES = {
    "normal",
    "modifier",
    "function",
    "layer",
    "lock",
    "script",
    "system",
}
EFFECT_BLEND_MODES = {"replace", "max", "add", "alpha"}

DEFAULT_REACTIVE_EXCLUDE_ROLES = ("modifier", "function", "layer", "lock")
DEFAULT_OVERLAY_PRIORITY = {
    "normal": 0,
    "modifier": 10,
    "function": 20,
    "layer": 30,
    "script": 35,
    "lock": 40,
    "system": 50,
}

_BASE_DIR = Path(__file__).resolve().parents[2]
from hidloom_paths import default_config_file, runtime_file
DEFAULT_KEYMAP_PATHS = (
    runtime_file("keymap.json"),
    default_config_file("keymap.json", _BASE_DIR),
)

KEYCODE_ALIASES = {
    "KC_CAPS": "KC_CAPSLOCK",
    "KC_CAPSLOCK": "KC_CAPSLOCK",
    "KC_NUM": "KC_NUMLOCK",
    "KC_NUMLOCK": "KC_NUMLOCK",
    "KC_NLCK": "KC_NUMLOCK",
    "KC_SCROLL": "KC_SCROLLLOCK",
    "KC_SCROLLLOCK": "KC_SCROLLLOCK",
    "KC_SLCK": "KC_SCROLLLOCK",
    "KC_KANA": "KC_KANA",
    "KC_INT2": "KC_KANA",
    "KC_COMPOSE": "KC_COMPOSE",
}

LOCK_STATE_BY_CANONICAL_KEYCODE = {
    "KC_NUMLOCK": "num_lock",
    "KC_CAPSLOCK": "caps_lock",
    "KC_SCROLLLOCK": "scroll_lock",
    "KC_COMPOSE": "compose",
    "KC_KANA": "kana",
}


def _layer_index_from_state_name(name: str) -> int:
    for prefix in ("layer:", "layer_"):
        if name.startswith(prefix):
            try:
                return int(name[len(prefix) :])
            except ValueError:
                return -1
    return -1


@dataclass(frozen=True)
class LedSemanticRoleConfig:
    """Normalized semantic-role config used by ledd overlay rendering."""

    roles: dict[str, str]
    state_overlays: dict[str, dict[str, Any]]
    reactive_exclude_roles: tuple[str, ...]
    overlay_priority: dict[str, int]
    overlay_blend: str = "priority"
    fallback_internal_lock_toggle: bool = False

    def role_for_keycode(self, keycode: str) -> str:
        canonical = canonical_keycode(keycode)
        return self.roles.get(canonical, self.roles.get(keycode, infer_role_from_keycode(canonical)))

    def reactive_enabled_for_keycode(self, keycode: str) -> bool:
        return self.role_for_keycode(keycode) not in self.reactive_exclude_roles

    def state_overlays_for_keycode(self, keycode: str, active_states: set[str] | frozenset[str]) -> list[dict[str, Any]]:
        canonical = canonical_keycode(keycode)
        overlays = []
        for name in active_states:
            overlay = self.state_overlays.get(name)
            if not overlay or not overlay.get("follow_keys", True) or canonical not in overlay["keys"]:
                continue
            overlays.append(overlay)
        overlays.sort(
            key=lambda overlay: (
                int(overlay.get("priority", 0)),
                int(overlay.get("layer_index", -1)),
            ),
            reverse=True,
        )
        return overlays

    def state_overlays_for_position(self, led_key: str, keycode: str, active_states: set[str] | frozenset[str]) -> list[dict[str, Any]]:
        canonical = canonical_keycode(keycode)
        overlays = []
        for name in active_states:
            overlay = self.state_overlays.get(name)
            if not overlay:
                continue
            follows_key = bool(overlay.get("follow_keys", True)) and canonical in overlay["keys"]
            explicit_led = led_key in overlay.get("leds", [])
            if follows_key or explicit_led:
                overlays.append(overlay)
        overlays.sort(
            key=lambda overlay: (
                int(overlay.get("priority", 0)),
                int(overlay.get("layer_index", -1)),
            ),
            reverse=True,
        )
        return overlays

    def restore_color_for_keycode(self, keycode: str, active_states: set[str] | frozenset[str]) -> list[int] | None:
        overlays = self.state_overlays_for_keycode(keycode, active_states)
        if overlays:
            return list(overlays[0]["color"])
        return None

    def restore_color_for_position(self, led_key: str, keycode: str, active_states: set[str] | frozenset[str]) -> list[int] | None:
        overlays = self.state_overlays_for_position(led_key, keycode, active_states)
        if not overlays:
            return None
        if self.overlay_blend == "max":
            color = [0, 0, 0]
            for overlay in overlays:
                overlay_color = _overlay_color_for_target(overlay, led_key, keycode)
                color = [max(color[idx], overlay_color[idx]) for idx in range(3)]
            return color
        if self.overlay_blend == "add":
            color = [0, 0, 0]
            for overlay in overlays:
                overlay_color = _overlay_color_for_target(overlay, led_key, keycode)
                color = [min(255, color[idx] + overlay_color[idx]) for idx in range(3)]
            return color
        return _overlay_color_for_target(overlays[0], led_key, keycode)

    def blended_color_for_position(
        self,
        led_key: str,
        keycode: str,
        active_states: set[str] | frozenset[str],
        base_color: list[int],
    ) -> list[int] | None:
        overlays = self.state_overlays_for_position(led_key, keycode, active_states)
        if not overlays:
            return None
        overlay_color = self.restore_color_for_position(led_key, keycode, active_states)
        if overlay_color is None:
            return None
        top_overlay = overlays[0]
        return _blend_with_effect(base_color, overlay_color, top_overlay)

    def overlay_priority_for_keycode(self, keycode: str) -> int:
        return int(self.overlay_priority.get(self.role_for_keycode(keycode), 0))


def infer_role_from_keycode(keycode: str) -> str:
    """Return a conservative role for keycodes not explicitly configured."""

    if not isinstance(keycode, str) or not keycode:
        return "normal"
    keycode = canonical_keycode(keycode)
    if keycode in LOCK_STATE_BY_CANONICAL_KEYCODE:
        return "lock"
    if keycode.startswith("KC_SH") or keycode.startswith("SCRIPT("):
        return "script"
    if keycode.startswith(("MO(", "TG(", "TO(", "DF(", "OSL(", "LT(")):
        return "layer"
    if keycode.startswith(("KC_LCTL", "KC_RCTL", "KC_LSFT", "KC_RSFT", "KC_LALT", "KC_RALT", "KC_LGUI", "KC_RGUI")):
        return "modifier"
    if keycode.startswith("KC_F") and keycode[4:].isdigit():
        return "function"
    if keycode.startswith(("KC_USB", "KC_CONN", "BT_", "KC_CONSOLE", "KC_SHUTDOWN")) or keycode in {"KC_BT"}:
        return "system"
    return "normal"


def _normalize_roles(raw: Any) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError("roles must be an object mapping keycode to role")
    roles: dict[str, str] = {}
    for keycode, role in raw.items():
        if not isinstance(keycode, str) or not keycode:
            raise ValueError("role keycode must be a non-empty string")
        if role not in VALID_ROLES:
            raise ValueError(f"invalid LED semantic role for {keycode}: {role!r}")
        roles[canonical_keycode(keycode)] = str(role)
    return roles


def canonical_keycode(keycode: str) -> str:
    if not isinstance(keycode, str):
        return ""
    return KEYCODE_ALIASES.get(keycode, keycode)


def lock_state_for_keycode(keycode: str) -> str | None:
    return LOCK_STATE_BY_CANONICAL_KEYCODE.get(canonical_keycode(keycode))


def _normalize_key_list(raw: Any, *, field: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(k, str) and k for k in raw):
        raise ValueError(f"{field} must be a list of keycodes")
    return list(dict.fromkeys(canonical_keycode(k) for k in raw))


def _normalize_led_list(raw: Any, *, field: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(k, str) and k for k in raw):
        raise ValueError(f"{field} must be a list of LED keys")
    return list(dict.fromkeys(str(k) for k in raw))


def _normalize_color(raw: Any, *, field: str) -> list[int]:
    if not isinstance(raw, list) or len(raw) != 3 or not all(isinstance(c, int) and 0 <= c <= 255 for c in raw):
        raise ValueError(f"{field} must be [r,g,b] bytes")
    return list(raw)


def _normalize_alpha(raw: Any, *, field: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number between 0.0 and 1.0") from None
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{field} must be a number between 0.0 and 1.0")
    return value


def _normalize_effect_blend(raw: Any, *, field: str) -> str:
    blend = str(raw or "replace").strip().lower().replace("-", "_")
    if blend not in EFFECT_BLEND_MODES:
        raise ValueError(f"{field} must be one of {sorted(EFFECT_BLEND_MODES)}")
    return blend


def _normalize_key_colors(raw: Any, *, field: str) -> dict[str, list[int]]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"{field} must be an object")
    out: dict[str, list[int]] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"{field} keys must be non-empty strings")
        color = _normalize_color(value, field=f"{field}.{key}")
        out[key] = color
        out[canonical_keycode(key)] = color
    return out


def _bool_value(raw: Any, *, field: str) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int):
        return bool(raw)
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{field} must be boolean")


def _overlay_color_for_target(overlay: Mapping[str, Any], led_key: str, keycode: str) -> list[int]:
    key_colors = overlay.get("key_colors", {})
    canonical = canonical_keycode(keycode)
    if isinstance(key_colors, Mapping):
        for candidate in (led_key, canonical, keycode):
            value = key_colors.get(candidate)
            if isinstance(value, list) and len(value) == 3:
                return list(value)
    return list(overlay["color"])


def _blend_with_effect(base_color: list[int], overlay_color: list[int], overlay: Mapping[str, Any]) -> list[int]:
    mode = str(overlay.get("effect_blend", "replace"))
    base = [int(max(0, min(255, value))) for value in base_color[:3]]
    color = [int(max(0, min(255, value))) for value in overlay_color[:3]]
    if mode == "max":
        return [max(base[idx], color[idx]) for idx in range(3)]
    if mode == "add":
        return [min(255, base[idx] + color[idx]) for idx in range(3)]
    if mode == "alpha":
        alpha = float(overlay.get("effect_alpha", 0.5))
        return [
            int(round(base[idx] * (1.0 - alpha) + color[idx] * alpha))
            for idx in range(3)
        ]
    return color


def _normalize_state_overlays(raw: Any) -> dict[str, dict[str, Any]]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError("state_overlays must be an object")
    overlays: dict[str, dict[str, Any]] = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not name:
            raise ValueError("state overlay name must be a non-empty string")
        if not isinstance(value, Mapping):
            raise ValueError(f"state overlay {name} must be an object")
        keys = _normalize_key_list(value.get("keys", []), field=f"state overlay {name}.keys")
        leds = _normalize_led_list(value.get("leds", value.get("extra_leds", [])), field=f"state overlay {name}.leds")
        color = _normalize_color(value.get("color", [0, 0, 0]), field=f"state overlay {name}.color")
        priority = int(value.get("priority", DEFAULT_OVERLAY_PRIORITY["lock"]))
        overlays[name] = {
            "name": name,
            "keys": keys,
            "leds": leds,
            "follow_keys": _bool_value(value.get("follow_keys", True), field=f"state overlay {name}.follow_keys"),
            "include_layer_changes": _bool_value(
                value.get("include_layer_changes", False),
                field=f"state overlay {name}.include_layer_changes",
            ),
            "color": color,
            "key_colors": _normalize_key_colors(value.get("key_colors"), field=f"state overlay {name}.key_colors"),
            "effect_blend": _normalize_effect_blend(
                value.get("effect_blend", "replace"),
                field=f"state overlay {name}.effect_blend",
            ),
            "effect_alpha": _normalize_alpha(
                value.get("effect_alpha", 0.5),
                field=f"state overlay {name}.effect_alpha",
            ),
            "priority": priority,
            "layer_index": _layer_index_from_state_name(name),
        }
    return overlays


def _normalize_lock_indicators(raw: Any) -> tuple[str, dict[str, dict[str, Any]]]:
    if raw is None:
        return "priority", {}
    if not isinstance(raw, Mapping):
        raise ValueError("lock_indicators must be an object")
    blend = str(raw.get("blend", "max")).strip().lower()
    if blend not in {"priority", "max", "add"}:
        raise ValueError("lock_indicators.blend must be priority, max, or add")
    states = raw.get("states", {})
    if not isinstance(states, Mapping):
        raise ValueError("lock_indicators.states must be an object")
    overlays: dict[str, dict[str, Any]] = {}
    for name, value in states.items():
        if name not in LOCK_STATE_BY_CANONICAL_KEYCODE.values():
            raise ValueError(f"unknown lock indicator state: {name}")
        if not isinstance(value, Mapping):
            raise ValueError(f"lock_indicators.states.{name} must be an object")
        default_keys = [
            keycode
            for keycode, state in LOCK_STATE_BY_CANONICAL_KEYCODE.items()
            if state == name
        ]
        keys = _normalize_key_list(value.get("keys", default_keys), field=f"lock_indicators.states.{name}.keys")
        overlays[str(name)] = {
            "name": str(name),
            "keys": keys,
            "leds": _normalize_led_list(value.get("extra_leds", value.get("leds", [])), field=f"lock_indicators.states.{name}.extra_leds"),
            "follow_keys": _bool_value(value.get("follow_keys", True), field=f"lock_indicators.states.{name}.follow_keys"),
            "color": _normalize_color(value.get("color", [0, 0, 0]), field=f"lock_indicators.states.{name}.color"),
            "key_colors": _normalize_key_colors(value.get("key_colors"), field=f"lock_indicators.states.{name}.key_colors"),
            "effect_blend": _normalize_effect_blend(
                value.get("effect_blend", "replace"),
                field=f"lock_indicators.states.{name}.effect_blend",
            ),
            "effect_alpha": _normalize_alpha(
                value.get("effect_alpha", 0.5),
                field=f"lock_indicators.states.{name}.effect_alpha",
            ),
            "priority": int(value.get("priority", DEFAULT_OVERLAY_PRIORITY["lock"])),
            "layer_index": -1,
        }
    return blend, overlays


def _normalize_exclude_roles(raw: Any, *, modifier_triggers_effects: bool | None = None) -> tuple[str, ...]:
    if raw is None:
        result = list(DEFAULT_REACTIVE_EXCLUDE_ROLES)
    elif not isinstance(raw, list):
        raise ValueError("reactive.exclude_roles must be a list")
    else:
        result = []
        for role in raw:
            if role not in VALID_ROLES:
                raise ValueError(f"invalid reactive exclude role: {role!r}")
            result.append(str(role))
    if modifier_triggers_effects is True:
        result = [role for role in result if role != "modifier"]
    elif modifier_triggers_effects is False and "modifier" not in result:
        result = ["modifier", *result]
    return tuple(dict.fromkeys(result))


def normalize_led_semantic_role_config(raw: Mapping[str, Any] | None) -> LedSemanticRoleConfig:
    """Normalize and validate a semantic LED role config."""

    raw = raw or {}
    if not isinstance(raw, Mapping):
        raise ValueError("LED semantic role config root must be an object")
    priority = dict(DEFAULT_OVERLAY_PRIORITY)
    custom_priority = raw.get("overlay_priority", {})
    if custom_priority is not None:
        if not isinstance(custom_priority, Mapping):
            raise ValueError("overlay_priority must be an object")
        for role, value in custom_priority.items():
            if role not in VALID_ROLES:
                raise ValueError(f"invalid overlay priority role: {role!r}")
            priority[str(role)] = int(value)
    reactive = raw.get("reactive", {})
    if reactive is None:
        reactive = {}
    if not isinstance(reactive, Mapping):
        raise ValueError("reactive must be an object")
    modifier_triggers_effects = reactive.get("modifier_triggers_effects")
    if modifier_triggers_effects is not None and not isinstance(modifier_triggers_effects, bool):
        raise ValueError("reactive.modifier_triggers_effects must be boolean")
    lock_blend, lock_overlays = _normalize_lock_indicators(raw.get("lock_indicators"))
    state_overlays = _normalize_state_overlays(raw.get("state_overlays"))
    state_overlays.update(lock_overlays)
    return LedSemanticRoleConfig(
        roles=_normalize_roles(raw.get("roles")),
        state_overlays=state_overlays,
        reactive_exclude_roles=_normalize_exclude_roles(
            reactive.get("exclude_roles"),
            modifier_triggers_effects=modifier_triggers_effects,
        ),
        overlay_priority=priority,
        overlay_blend=lock_blend if lock_overlays else "priority",
        fallback_internal_lock_toggle=_bool_value(
            raw.get("fallback_internal_lock_toggle", False),
            field="fallback_internal_lock_toggle",
        ),
    )


def keymap_json_to_base_keycodes(keymap: Mapping[str, Any]) -> dict[str, str]:
    """Return a row,col -> keycode map for layer 0 from keymap.json."""

    layout_def = keymap.get("_layout_def", {})
    layers = keymap.get("layers", [])
    if not isinstance(layout_def, Mapping) or not isinstance(layers, list) or not layers:
        return {}
    layer0 = layers[0]
    if not isinstance(layer0, Mapping):
        return {}

    out: dict[str, str] = {}
    for group, entries in layout_def.items():
        if not isinstance(group, str) or group.startswith("_") or not isinstance(entries, list):
            continue
        values = layer0.get(group, [])
        if not isinstance(values, list):
            continue
        for entry, keycode in zip(entries, values):
            if not isinstance(entry, list) or len(entry) < 2 or not keycode:
                continue
            out[f"{int(entry[0])},{int(entry[1])}"] = str(keycode)
    return out


def load_base_keycodes(paths: tuple[Path, ...] = DEFAULT_KEYMAP_PATHS) -> dict[str, str]:
    """Load the first available keymap.json and return layer-0 keycodes."""

    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(raw, Mapping):
            keycodes = keymap_json_to_base_keycodes(raw)
            if keycodes:
                return keycodes
    return {}
