"""Validation helpers for InteractionEngine configuration."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .shared_action_defs import (
    is_animation_action,
    is_layer_action_in_range,
    is_macro_action,
    is_script_action,
    shared_connectivity_actions,
    is_unicode_action,
    is_wrapper_action,
)
from .mod_morph import normalize_mod_morph_config, parse_mod_morph_action
from .key_lock import parse_key_lock_action

_SAFE_ACTION_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_TAP_HOLD_ACTION_RE = re.compile(r"^(LT|MT)\(([^,]+),\s*(.+)\)$")
_TAP_TOGGLE_ACTION_RE = re.compile(r"^TT\((\d+)\)$")
_TAP_DANCE_ACTION_RE = re.compile(r"^TD\([A-Za-z0-9_.-]{1,64}\)$")
_MORSE_ACTION_RE = re.compile(r"^MORSE\([A-Za-z0-9_.-]{1,64}\)$")
_MORSE_SEQUENCE_RE = re.compile(r"^[.-]+$")
_NO_ACTION_VALUES = {"", "KC_NO", "KC_NONE", "NO", "NONE"}
_DEFAULT_CAPS_WORD_CONTINUE = ["KC_MINS", "KC_BSPC", "KC_DEL", "KC_UNDS"]
_DEFAULT_CAPS_WORD_CANCEL = ["KC_SPACE", "KC_ENTER", "KC_ESC", "KC_TAB"]
_DEFAULT_REPEAT_ALTERNATE_PAIRS = [
    ["KC_LEFT", "KC_RGHT"],
    ["KC_UP", "KC_DOWN"],
    ["KC_HOME", "KC_END"],
    ["KC_PGUP", "KC_PGDN"],
    ["KC_BSPC", "KC_DEL"],
    ["KC_WH_U", "KC_WH_D"],
    ["KC_WH_L", "KC_WH_R"],
    ["MS_LEFT", "MS_RGHT"],
    ["MS_UP", "MS_DOWN"],
]
_OUTPUT_SWITCH_ACTIONS = {"KC_CONNAUTO", "KC_CONSOLE", "KC_USB", "KC_BT"}
_SYSTEM_ACTIONS = {"KC_SHUTDOWN", *_OUTPUT_SWITCH_ACTIONS}
_SCRIPT_KEY_RE = re.compile(r"^KC_SH(?:[0-9]|10)$")
_WRAPPER_ACTION_RE = re.compile(r"^[A-Z0-9_]+\((.+)\)$")


@dataclass
class InteractionConfigValidation:
    """Normalized interaction settings plus non-fatal validation warnings."""

    settings: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


def _float_setting(raw: dict, key: str, default: float, *, min_value: float, warnings: list[str]) -> float:
    value = raw.get(key, default)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        warnings.append(f"settings.interaction.{key} ignored: expected number")
        return default
    if parsed < min_value:
        warnings.append(f"settings.interaction.{key} ignored: must be >= {min_value}")
        return default
    return parsed


def _bool_setting(raw: dict, key: str, default: bool, *, warnings: list[str]) -> bool:
    value = raw.get(key, default)
    if isinstance(value, bool):
        return value
    warnings.append(f"settings.interaction.{key} ignored: expected boolean")
    return default


def _matrix_key(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        return int(value[0]), int(value[1])
    except (TypeError, ValueError):
        return None


def _is_valid_action(action: str, depth: int = 0) -> bool:
    if depth > 4:
        return False
    if _SAFE_ACTION_RE.fullmatch(action):
        return True
    if is_layer_action_in_range(action, max_layers=32):
        return True
    if is_wrapper_action(action):
        return True
    if is_animation_action(action):
        return True
    if is_unicode_action(action):
        return True
    if is_macro_action(action):
        return True
    if is_script_action(action):
        return True
    tap_toggle = _TAP_TOGGLE_ACTION_RE.fullmatch(action)
    if tap_toggle:
        return 0 <= int(tap_toggle.group(1)) < 32
    if _TAP_DANCE_ACTION_RE.fullmatch(action):
        return True
    if _MORSE_ACTION_RE.fullmatch(action):
        return True
    if parse_mod_morph_action(action) is not None:
        return True
    key_lock = parse_key_lock_action(action)
    if key_lock is not None:
        return key_lock.target.kind != "unsupported"
    tap_hold = _TAP_HOLD_ACTION_RE.fullmatch(action)
    if tap_hold:
        op, first, tap_action = tap_hold.group(1), tap_hold.group(2).strip(), tap_hold.group(3).strip()
        if op == "LT":
            try:
                layer = int(first)
            except ValueError:
                return False
            return 0 <= layer < 32 and _is_valid_action(tap_action, depth + 1)
        return bool(_SAFE_ACTION_RE.fullmatch(first)) and _is_valid_action(tap_action, depth + 1)
    return False


def _valid_action_or_warn(path: str, value: Any, warnings: list[str]) -> str | None:
    if not isinstance(value, str) or not value:
        warnings.append(f"{path} ignored: expected action string")
        return None
    if not _is_valid_action(value):
        warnings.append(f"{path} ignored: invalid action syntax: {value!r}")
        return None
    return value


def _is_key_override_safe_replacement(action: str, depth: int = 0) -> bool:
    if depth > 4:
        return False
    if action in _SYSTEM_ACTIONS or action in shared_connectivity_actions():
        return False
    if _SCRIPT_KEY_RE.fullmatch(action) or is_script_action(action):
        return False
    if is_layer_action_in_range(action, max_layers=32) or _TAP_TOGGLE_ACTION_RE.fullmatch(action):
        return False
    tap_hold = _TAP_HOLD_ACTION_RE.fullmatch(action)
    if tap_hold:
        op, _first, tap_action = tap_hold.group(1), tap_hold.group(2).strip(), tap_hold.group(3).strip()
        if op == "LT":
            return False
        return _is_key_override_safe_replacement(tap_action, depth + 1)
    if is_wrapper_action(action):
        wrapper = _WRAPPER_ACTION_RE.fullmatch(action)
        if wrapper is None:
            return False
        return _is_key_override_safe_replacement(wrapper.group(1).strip(), depth + 1)
    return True


def _key_override_replacement_or_warn(path: str, value: Any, warnings: list[str]) -> str | None:
    action = _valid_action_or_warn(path, value, warnings)
    if action is None:
        return None
    if not _is_key_override_safe_replacement(action):
        warnings.append(f"{path} ignored: replacement action is not safe for Key Override: {action!r}")
        return None
    return action


def _optional_action_or_warn(path: str, value: Any, warnings: list[str]) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        warnings.append(f"{path} ignored: expected action string")
        return None
    text = value.strip()
    if text.upper() in _NO_ACTION_VALUES:
        return None
    return _valid_action_or_warn(path, text, warnings)


def _validate_combos(raw: Any, matrix_in_range: Callable[[int, int], bool], warnings: list[str]) -> list[dict[str, Any]]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        warnings.append("settings.interaction.combos ignored: expected list")
        return []
    result: list[dict[str, Any]] = []
    for idx, combo in enumerate(raw):
        if not isinstance(combo, dict):
            warnings.append(f"settings.interaction.combos[{idx}] ignored: expected object")
            continue
        keys_raw = combo.get("keys", [])
        action = _valid_action_or_warn(f"settings.interaction.combos[{idx}].action", combo.get("action"), warnings)
        if not isinstance(keys_raw, list) or len(keys_raw) < 2:
            warnings.append(f"settings.interaction.combos[{idx}] ignored: expected at least two keys")
            continue
        if action is None:
            continue
        seen: set[tuple[int, int]] = set()
        invalid = False
        for key_raw in keys_raw:
            key = _matrix_key(key_raw)
            if key is None or not matrix_in_range(*key):
                warnings.append(f"settings.interaction.combos[{idx}] ignored: invalid key {key_raw!r}")
                invalid = True
                break
            seen.add(key)
        if invalid:
            continue
        if len(seen) < 2:
            warnings.append(f"settings.interaction.combos[{idx}] ignored: duplicate keys")
            continue
        keys = [[row, col] for row, col in sorted(seen)]
        result.append({"keys": keys, "action": action})
    return result


def _validate_tap_dances(raw: Any, warnings: list[str]) -> dict[str, dict[Any, Any]]:
    if raw in (None, ""):
        return {}
    if not isinstance(raw, dict):
        warnings.append("settings.interaction.tap_dances ignored: expected object")
        return {}
    result: dict[str, dict[Any, Any]] = {}
    for name, actions_raw in raw.items():
        if not isinstance(name, str) or not name:
            warnings.append("settings.interaction.tap_dances entry ignored: expected non-empty name")
            continue
        if not isinstance(actions_raw, dict) or not actions_raw:
            warnings.append(f"settings.interaction.tap_dances.{name} ignored: expected action map")
            continue
        actions: dict[Any, Any] = {}
        for count_raw, action in actions_raw.items():
            if count_raw == "term":
                try:
                    actions["term"] = max(0.001, float(action))
                except (TypeError, ValueError):
                    warnings.append(f"settings.interaction.tap_dances.{name}.term ignored: expected number")
                continue
            if count_raw in {"hold", "on_hold", "tap_hold", "on_tap_hold"}:
                normalized_action = _valid_action_or_warn(
                    f"settings.interaction.tap_dances.{name}.{count_raw}",
                    action,
                    warnings,
                )
                if normalized_action is not None:
                    actions[str(count_raw)] = normalized_action
                continue
            try:
                count = int(count_raw)
            except (TypeError, ValueError):
                warnings.append(f"settings.interaction.tap_dances.{name}.{count_raw} ignored: invalid count")
                continue
            if count < 1:
                warnings.append(f"settings.interaction.tap_dances.{name}.{count_raw} ignored: count must be >= 1")
                continue
            normalized_action = _valid_action_or_warn(
                f"settings.interaction.tap_dances.{name}.{count_raw}",
                action,
                warnings,
            )
            if normalized_action is None:
                continue
            actions[count] = normalized_action
        if actions:
            result[name] = actions
    return result


def _force_commit_raw(entry: dict[str, Any]) -> tuple[Any, str]:
    if "force_commit" in entry:
        return entry.get("force_commit"), "force_commit"
    if "terminal" in entry:
        return entry.get("terminal"), "terminal"
    return entry.get("terminal_sequences", []), "terminal_sequences"


def _force_commit_sequence_list(
    raw: Any,
    *,
    source_name: str,
    name: str,
    max_depth: int,
    actions: dict[str, str],
    warnings: list[str],
) -> list[str]:
    if raw in (None, "", []):
        return []
    if isinstance(raw, str):
        items = [raw]
    elif isinstance(raw, list):
        items = raw
    else:
        warnings.append(f"settings.interaction.morse_behaviors.{name}.{source_name} ignored: expected sequence or list")
        return []
    result: list[str] = []
    for item in items:
        sequence = str(item).strip()
        if not _MORSE_SEQUENCE_RE.fullmatch(sequence):
            warnings.append(f"settings.interaction.morse_behaviors.{name}.{source_name} {item!r} ignored: invalid sequence")
            continue
        if len(sequence) > max_depth:
            warnings.append(f"settings.interaction.morse_behaviors.{name}.{source_name} {sequence} ignored: exceeds max_depth")
            continue
        if sequence not in actions:
            warnings.append(f"settings.interaction.morse_behaviors.{name}.{source_name} {sequence} ignored: no mapped action")
            continue
        if sequence not in result:
            result.append(sequence)
    return result


def _validate_morse_behaviors(raw: Any, warnings: list[str]) -> dict[str, dict[str, Any]]:
    if raw in (None, ""):
        return {}
    if not isinstance(raw, dict):
        warnings.append("settings.interaction.morse_behaviors ignored: expected object")
        return {}
    result: dict[str, dict[str, Any]] = {}
    for name, entry in raw.items():
        if not isinstance(name, str) or not name:
            warnings.append("settings.interaction.morse_behaviors entry ignored: expected non-empty name")
            continue
        if not isinstance(entry, dict) or not entry:
            warnings.append(f"settings.interaction.morse_behaviors.{name} ignored: expected object")
            continue
        action_map_raw = entry.get("map", entry)
        if not isinstance(action_map_raw, dict) or not action_map_raw:
            warnings.append(f"settings.interaction.morse_behaviors.{name}.map ignored: expected action map")
            continue
        dot_threshold = _float_morse_setting(entry, "dot_threshold", 0.180, warnings, name)
        sequence_timeout = _float_morse_setting(entry, "sequence_timeout", 0.700, warnings, name)
        max_depth = _int_morse_setting(entry, "max_depth", 4, warnings, name)
        if max_depth < 1:
            warnings.append(f"settings.interaction.morse_behaviors.{name}.max_depth ignored: must be >= 1")
            max_depth = 4
        actions: dict[str, str] = {}
        for sequence_raw, action_raw in action_map_raw.items():
            if sequence_raw in {"dot_threshold", "sequence_timeout", "max_depth", "force_commit", "terminal", "terminal_sequences", "fallback_action"}:
                continue
            sequence = str(sequence_raw).strip()
            if not _MORSE_SEQUENCE_RE.fullmatch(sequence):
                warnings.append(f"settings.interaction.morse_behaviors.{name}.{sequence_raw} ignored: invalid sequence")
                continue
            if len(sequence) > max_depth:
                warnings.append(f"settings.interaction.morse_behaviors.{name}.{sequence} ignored: exceeds max_depth")
                continue
            normalized_action = _valid_action_or_warn(
                f"settings.interaction.morse_behaviors.{name}.{sequence}",
                action_raw,
                warnings,
            )
            if normalized_action is None:
                continue
            actions[sequence] = normalized_action
        if actions:
            force_commit_raw, source_name = _force_commit_raw(entry)
            force_commit = _force_commit_sequence_list(
                force_commit_raw,
                source_name=source_name,
                name=name,
                max_depth=max_depth,
                actions=actions,
                warnings=warnings,
            )
            fallback_action = _optional_action_or_warn(
                f"settings.interaction.morse_behaviors.{name}.fallback_action",
                entry.get("fallback_action"),
                warnings,
            )
            normalized: dict[str, Any] = {
                "dot_threshold": dot_threshold,
                "sequence_timeout": sequence_timeout,
                "max_depth": max_depth,
                "map": actions,
            }
            if force_commit:
                normalized["force_commit"] = force_commit
            if fallback_action:
                normalized["fallback_action"] = fallback_action
            result[name] = normalized
    return result


def _float_morse_setting(entry: dict[str, Any], key: str, default: float, warnings: list[str], name: str) -> float:
    value = entry.get(key, default)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        warnings.append(f"settings.interaction.morse_behaviors.{name}.{key} ignored: expected number")
        return default
    if parsed <= 0:
        warnings.append(f"settings.interaction.morse_behaviors.{name}.{key} ignored: must be > 0")
        return default
    return parsed


def _int_morse_setting(entry: dict[str, Any], key: str, default: int, warnings: list[str], name: str) -> int:
    value = entry.get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        warnings.append(f"settings.interaction.morse_behaviors.{name}.{key} ignored: expected integer")
        return default


def _validate_key_overrides(raw: Any, warnings: list[str]) -> list[dict[str, Any]]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        warnings.append("settings.interaction.key_overrides ignored: expected list")
        return []
    result: list[dict[str, Any]] = []
    for idx, override in enumerate(raw):
        if not isinstance(override, dict):
            warnings.append(f"settings.interaction.key_overrides[{idx}] ignored: expected object")
            continue
        trigger = override.get("trigger")
        key = override.get("key")
        replacement = override.get("replacement")
        if isinstance(trigger, str):
            normalized_trigger: str | list[str] | None = _valid_action_or_warn(
                f"settings.interaction.key_overrides[{idx}].trigger",
                trigger,
                warnings,
            )
        elif isinstance(trigger, list) and trigger:
            normalized_trigger_items = [
                _valid_action_or_warn(
                    f"settings.interaction.key_overrides[{idx}].trigger[{item_idx}]",
                    item,
                    warnings,
                )
                for item_idx, item in enumerate(trigger)
            ]
            normalized_trigger = list(normalized_trigger_items) if all(normalized_trigger_items) else None
        else:
            warnings.append(f"settings.interaction.key_overrides[{idx}] ignored: invalid trigger")
            continue
        normalized_key = _valid_action_or_warn(f"settings.interaction.key_overrides[{idx}].key", key, warnings)
        normalized_replacement = _key_override_replacement_or_warn(
            f"settings.interaction.key_overrides[{idx}].replacement",
            replacement,
            warnings,
        )
        negative = override.get("negative_trigger", override.get("negative", []))
        normalized_negative: str | list[str] | None
        if negative in (None, "", []):
            normalized_negative = []
        elif isinstance(negative, str):
            normalized_negative = _valid_action_or_warn(
                f"settings.interaction.key_overrides[{idx}].negative_trigger",
                negative,
                warnings,
            )
        elif isinstance(negative, list):
            normalized_negative_items = [
                _valid_action_or_warn(
                    f"settings.interaction.key_overrides[{idx}].negative_trigger[{item_idx}]",
                    item,
                    warnings,
                )
                for item_idx, item in enumerate(negative)
            ]
            normalized_negative = list(normalized_negative_items) if all(normalized_negative_items) else None
        else:
            warnings.append(f"settings.interaction.key_overrides[{idx}].negative_trigger ignored: expected action or list")
            normalized_negative = []
        try:
            layers = int(override.get("layers", 0xFFFF))
        except (TypeError, ValueError):
            warnings.append(f"settings.interaction.key_overrides[{idx}].layers ignored: expected integer")
            layers = 0xFFFF
        try:
            options = int(override.get("options", 0x83))
        except (TypeError, ValueError):
            warnings.append(f"settings.interaction.key_overrides[{idx}].options ignored: expected integer")
            options = 0x83
        if normalized_trigger is None or normalized_key is None or normalized_replacement is None or normalized_negative is None:
            continue
        result.append({
            "trigger": normalized_trigger,
            "negative_trigger": normalized_negative,
            "key": normalized_key,
            "replacement": normalized_replacement,
            "layers": max(0, min(0xFFFF, layers)),
            "options": max(0, min(0xFF, options)),
        })
    return result


def _action_list_setting(raw: dict[str, Any], key: str, default: list[str], warnings: list[str], path: str) -> list[str]:
    value = raw.get(key, default)
    if not isinstance(value, list):
        warnings.append(f"{path}.{key} ignored: expected list")
        return list(default)
    result: list[str] = []
    for idx, item in enumerate(value):
        action = _valid_action_or_warn(f"{path}.{key}[{idx}]", item, warnings)
        if action is not None and action not in result:
            result.append(action)
    return result


def _validate_caps_word(raw: Any, warnings: list[str]) -> dict[str, Any]:
    path = "settings.interaction.caps_word"
    if raw in (None, ""):
        raw = {}
    if not isinstance(raw, dict):
        warnings.append(f"{path} ignored: expected object")
        raw = {}
    return {
        "enabled": _bool_setting(raw, "enabled", True, warnings=warnings),
        "continue_keys": _action_list_setting(raw, "continue_keys", _DEFAULT_CAPS_WORD_CONTINUE, warnings, path),
        "cancel_keys": _action_list_setting(raw, "cancel_keys", _DEFAULT_CAPS_WORD_CANCEL, warnings, path),
    }


def _validate_repeat_key(raw: Any, warnings: list[str]) -> dict[str, Any]:
    path = "settings.interaction.repeat_key"
    if raw in (None, ""):
        raw = {}
    if not isinstance(raw, dict):
        warnings.append(f"{path} ignored: expected object")
        raw = {}
    pairs_raw = raw.get("alternate_pairs", _DEFAULT_REPEAT_ALTERNATE_PAIRS)
    pairs: list[list[str]] = []
    if not isinstance(pairs_raw, list):
        warnings.append(f"{path}.alternate_pairs ignored: expected list")
        pairs_raw = _DEFAULT_REPEAT_ALTERNATE_PAIRS
    for idx, pair in enumerate(pairs_raw):
        if not isinstance(pair, list) or len(pair) != 2:
            warnings.append(f"{path}.alternate_pairs[{idx}] ignored: expected [action, action]")
            continue
        left = _valid_action_or_warn(f"{path}.alternate_pairs[{idx}][0]", pair[0], warnings)
        right = _valid_action_or_warn(f"{path}.alternate_pairs[{idx}][1]", pair[1], warnings)
        if left is not None and right is not None and left != right:
            pairs.append([left, right])
    return {
        "enabled": _bool_setting(raw, "enabled", True, warnings=warnings),
        "alternate_pairs": pairs,
    }


def _validate_mod_morphs(raw: Any, warnings: list[str]) -> dict[str, Any]:
    path = "settings.interaction.mod_morphs"
    if raw in (None, ""):
        return {}
    if not isinstance(raw, dict):
        warnings.append(f"{path} ignored: expected object")
        return {}
    normalized = normalize_mod_morph_config(raw)
    for warning in normalized.warnings:
        warnings.append(f"{path}.{warning.name} ignored: {warning.message}")
    result: dict[str, Any] = {}
    for name, original in raw.items():
        rule = normalized.rules.get(str(name))
        if rule is None:
            continue
        result[str(name)] = {
            "trigger_mods": sorted(rule.trigger_mods),
            "default_action": rule.default_action,
            "morphed_action": rule.morphed_action,
            "layers": "all" if rule.layers is None else sorted(rule.layers),
        }
        if not isinstance(original, dict):
            continue
    return result


def _validate_conditional_layers(raw: Any, warnings: list[str]) -> list[dict[str, Any]]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        warnings.append("settings.interaction.conditional_layers ignored: expected list")
        return []
    result: list[dict[str, Any]] = []
    target_to_sources: dict[int, set[int]] = {}
    for idx, rule in enumerate(raw):
        path = f"settings.interaction.conditional_layers[{idx}]"
        if not isinstance(rule, dict):
            warnings.append(f"{path} ignored: expected object")
            continue
        name = str(rule.get("name", f"rule_{idx}")).strip() or f"rule_{idx}"
        sources_raw = rule.get("if_all")
        if not isinstance(sources_raw, list) or len(sources_raw) < 2:
            warnings.append(f"{path}.if_all ignored: expected at least two layers")
            continue
        sources: list[int] = []
        invalid = False
        for source_idx, layer_raw in enumerate(sources_raw):
            try:
                layer = int(layer_raw)
            except (TypeError, ValueError):
                warnings.append(f"{path}.if_all[{source_idx}] ignored: expected integer")
                invalid = True
                break
            if not 0 <= layer < 32:
                warnings.append(f"{path}.if_all[{source_idx}] ignored: layer must be 0-31")
                invalid = True
                break
            if layer not in sources:
                sources.append(layer)
        if invalid or len(sources) < 2:
            continue
        try:
            target = int(rule.get("then"))
        except (TypeError, ValueError):
            warnings.append(f"{path}.then ignored: expected integer")
            continue
        if not 0 <= target < 32:
            warnings.append(f"{path}.then ignored: layer must be 0-31")
            continue
        if target in sources:
            warnings.append(f"{path} ignored: then layer must not be in if_all")
            continue
        if target in target_to_sources and target_to_sources[target] == set(sources):
            warnings.append(f"{path} ignored: duplicate conditional layer rule")
            continue
        target_to_sources[target] = set(sources)
        result.append({"name": name, "if_all": sources, "then": target})
    return result


def validate_interaction_settings(
    raw: Any,
    *,
    matrix_in_range: Callable[[int, int], bool],
) -> InteractionConfigValidation:
    """Return normalized InteractionEngine settings and warnings.

    This validator is intentionally tolerant for runtime loading: invalid
    advanced sections are skipped with warnings instead of preventing logicd
    from starting.
    """
    warnings: list[str] = []
    if raw in (None, ""):
        raw = {}
    if not isinstance(raw, dict):
        warnings.append("settings.interaction ignored: expected object")
        raw = {}
    settings = {
        "tapping_term": _float_setting(raw, "tapping_term", 0.200, min_value=0.001, warnings=warnings),
        "hold_on_other_key_press": _bool_setting(raw, "hold_on_other_key_press", True, warnings=warnings),
        "combo_term": _float_setting(raw, "combo_term", 0.050, min_value=0.001, warnings=warnings),
        "tap_dance_term": _float_setting(raw, "tap_dance_term", 0.200, min_value=0.001, warnings=warnings),
        "combos": _validate_combos(raw.get("combos", []), matrix_in_range, warnings),
        "tap_dances": _validate_tap_dances(raw.get("tap_dances", {}), warnings),
        "morse_behaviors": _validate_morse_behaviors(raw.get("morse_behaviors", {}), warnings),
        "key_overrides": _validate_key_overrides(raw.get("key_overrides", []), warnings),
        "caps_word": _validate_caps_word(raw.get("caps_word", {}), warnings),
        "repeat_key": _validate_repeat_key(raw.get("repeat_key", {}), warnings),
        "mod_morphs": _validate_mod_morphs(raw.get("mod_morphs", {}), warnings),
        "conditional_layers": _validate_conditional_layers(raw.get("conditional_layers", []), warnings),
    }
    return InteractionConfigValidation(settings=settings, warnings=warnings)
