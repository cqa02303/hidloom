"""Runtime helper for Mod-Morph / Grave Escape.

The normalization and resolution API stays independent from output dispatch.
InteractionEngine supplies held modifiers and active layers, then consumes the
resolved action through its normal press/release ownership path.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from .shared_action_defs import (
    is_animation_action,
    is_layer_action,
    is_macro_action,
    is_script_action,
    is_unicode_action,
)

_MOD_MORPH_RE = re.compile(r"^MOD_MORPH\(([A-Za-z0-9_.-]{1,64})\)$")
_BASIC_KEY_RE = re.compile(r"^KC_[A-Z0-9_]+$")
_MOD_WRAPPER_RE = re.compile(r"^(S|LSFT|RSFT|LCTL|RCTL|LALT|RALT|LGUI|RGUI)\((KC_[A-Z0-9_]+)\)$")

_DEFAULT_GRAVE_ESCAPE_NAME = "grave_escape"
_DEFAULT_GRAVE_ESCAPE = {
    "trigger_mods": ["KC_LSFT", "KC_RSFT", "KC_LGUI", "KC_RGUI"],
    "default_action": "KC_ESC",
    "morphed_action": "KC_GRV",
    "layers": "all",
}

_MOD_ALIASES = {
    "KC_LCTRL": "KC_LCTL",
    "KC_RCTRL": "KC_RCTL",
    "KC_LSHIFT": "KC_LSFT",
    "KC_RSHIFT": "KC_RSFT",
    "KC_LWIN": "KC_LGUI",
    "KC_RWIN": "KC_RGUI",
    "KC_LCMD": "KC_LGUI",
    "KC_RCMD": "KC_RGUI",
}
_MODIFIER_ACTIONS = frozenset({
    "KC_LCTL",
    "KC_RCTL",
    "KC_LSFT",
    "KC_RSFT",
    "KC_LALT",
    "KC_RALT",
    "KC_LGUI",
    "KC_RGUI",
})


@dataclass(frozen=True)
class ModMorphRule:
    """Normalized Mod-Morph rule."""

    name: str
    trigger_mods: frozenset[str]
    default_action: str
    morphed_action: str
    layers: frozenset[int] | None = None

    def applies_to_layer(self, active_layers: Iterable[int] | None) -> bool:
        if self.layers is None:
            return True
        return bool(self.layers & {int(layer) for layer in active_layers or []})


@dataclass(frozen=True)
class ModMorphValidationWarning:
    """Validation warning for a skipped Mod-Morph rule."""

    name: str
    message: str


@dataclass(frozen=True)
class ModMorphConfig:
    """Normalized Mod-Morph config."""

    rules: dict[str, ModMorphRule]
    warnings: tuple[ModMorphValidationWarning, ...] = ()


@dataclass(frozen=True)
class ModMorphCommand:
    """Parsed MOD_MORPH command."""

    name: str


def canonical_modifier(action: str) -> str:
    """Return canonical modifier action name."""
    return _MOD_ALIASES.get(action, action)


def parse_mod_morph_action(action: str) -> ModMorphCommand | None:
    """Parse GRAVE_ESCAPE or MOD_MORPH(name)."""
    if action == "GRAVE_ESCAPE":
        return ModMorphCommand(_DEFAULT_GRAVE_ESCAPE_NAME)
    match = _MOD_MORPH_RE.fullmatch(action.strip())
    if not match:
        return None
    return ModMorphCommand(match.group(1))


def is_safe_mod_morph_output(action: str) -> bool:
    """Return True for actions allowed as Mod-Morph outputs.

    Initial scope is deliberately narrow: plain KC_* keyboard actions and a
    small set of modifier wrappers around KC_* actions.  Runtime control,
    connectivity, script, macro, layer, animation, unicode, mouse, and consumer
    actions are not accepted.
    """
    if not action or action in {"KC_NO", "KC_NONE", "KC_TRNS"}:
        return False
    if is_layer_action(action) or is_macro_action(action) or is_script_action(action):
        return False
    if is_animation_action(action) or is_unicode_action(action):
        return False
    if action.startswith(("BT_", "WIFI_", "RGB_", "RM_", "MS_", "KC_BTN", "KC_WH")):
        return False
    if action in {"KC_CONNAUTO", "KC_CONSOLE", "KC_USB", "KC_BT", "KC_SHUTDOWN"}:
        return False
    if action.startswith("KC_SH"):
        return False
    if _BASIC_KEY_RE.fullmatch(action):
        return True
    wrapper = _MOD_WRAPPER_RE.fullmatch(action)
    if wrapper:
        return bool(_BASIC_KEY_RE.fullmatch(wrapper.group(2)))
    return False


def normalize_mod_morph_config(raw: dict[str, Any] | None) -> ModMorphConfig:
    """Normalize settings.interaction.mod_morphs style config."""
    rules: dict[str, ModMorphRule] = {}
    warnings: list[ModMorphValidationWarning] = []
    source = dict(raw or {})
    source.setdefault(_DEFAULT_GRAVE_ESCAPE_NAME, _DEFAULT_GRAVE_ESCAPE)

    for name, entry in source.items():
        rule_name = str(name)
        if not isinstance(entry, dict):
            warnings.append(ModMorphValidationWarning(rule_name, "rule is not an object"))
            continue
        trigger_mods = frozenset(
            canonical_modifier(str(mod))
            for mod in entry.get("trigger_mods", [])
        )
        invalid_mods = sorted(mod for mod in trigger_mods if mod not in _MODIFIER_ACTIONS)
        if not trigger_mods or invalid_mods:
            warnings.append(ModMorphValidationWarning(rule_name, f"invalid trigger_mods: {invalid_mods or 'empty'}"))
            continue
        default_action = str(entry.get("default_action", ""))
        morphed_action = str(entry.get("morphed_action", ""))
        if not is_safe_mod_morph_output(default_action):
            warnings.append(ModMorphValidationWarning(rule_name, f"unsafe default_action: {default_action}"))
            continue
        if not is_safe_mod_morph_output(morphed_action):
            warnings.append(ModMorphValidationWarning(rule_name, f"unsafe morphed_action: {morphed_action}"))
            continue
        layers_raw = entry.get("layers", "all")
        layers: frozenset[int] | None
        if layers_raw == "all" or layers_raw is None:
            layers = None
        elif isinstance(layers_raw, Iterable) and not isinstance(layers_raw, (str, bytes, dict)):
            try:
                layers = frozenset(int(layer) for layer in layers_raw)
            except (TypeError, ValueError):
                warnings.append(ModMorphValidationWarning(rule_name, "invalid layers"))
                continue
            if not layers:
                warnings.append(ModMorphValidationWarning(rule_name, "empty layers"))
                continue
        else:
            warnings.append(ModMorphValidationWarning(rule_name, "invalid layers"))
            continue
        rules[rule_name] = ModMorphRule(
            name=rule_name,
            trigger_mods=trigger_mods,
            default_action=default_action,
            morphed_action=morphed_action,
            layers=layers,
        )
    return ModMorphConfig(rules=rules, warnings=tuple(warnings))


def resolve_mod_morph_action(
    action: str,
    config: ModMorphConfig,
    *,
    held_actions: Iterable[str],
    active_layers: Iterable[int] | None = None,
) -> str:
    """Resolve action through a normalized Mod-Morph config."""
    command = parse_mod_morph_action(action)
    if command is None:
        return action
    rule = config.rules.get(command.name)
    if rule is None:
        return action
    if not rule.applies_to_layer(active_layers):
        return rule.default_action
    held_mods = {canonical_modifier(str(item)) for item in held_actions}
    if rule.trigger_mods & held_mods:
        return rule.morphed_action
    return rule.default_action


def mod_morph_conflicts_for_key_overrides(
    config: ModMorphConfig,
    key_override_keys: Iterable[str],
) -> tuple[str, ...]:
    """Return Mod-Morph action names that may overlap explicit Key Overrides."""
    override_keys = set(str(item) for item in key_override_keys)
    conflicts: list[str] = []
    for name, rule in sorted(config.rules.items()):
        if rule.default_action in override_keys or rule.morphed_action in override_keys:
            conflicts.append(f"MOD_MORPH({name})")
    return tuple(conflicts)
