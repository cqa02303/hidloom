"""Host keyboard LED output report mapping."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class HostLedKind:
    name: str
    bit: int
    key_actions: frozenset[str]


HOST_LED_KINDS: dict[str, HostLedKind] = {
    "num_lock": HostLedKind("num_lock", 0, frozenset({"KC_NUMLOCK", "KC_NUM", "KC_NLCK"})),
    "caps_lock": HostLedKind("caps_lock", 1, frozenset({"KC_CAPS", "KC_CAPSLOCK"})),
    "scroll_lock": HostLedKind("scroll_lock", 2, frozenset({"KC_SCROLLLOCK", "KC_SCROLL", "KC_SLCK"})),
    "compose": HostLedKind("compose", 3, frozenset({"KC_COMPOSE"})),
    "kana": HostLedKind("kana", 4, frozenset({"KC_KANA", "KC_INT2"})),
}


@dataclass(frozen=True)
class HostLedOutputConfig:
    enabled_states: frozenset[str]
    fallback_internal_toggle: bool = False

    def kind_for_action(self, action: str) -> HostLedKind | None:
        if not self.fallback_internal_toggle:
            return None
        for name in self.enabled_states:
            kind = HOST_LED_KINDS.get(name)
            if kind is not None and action in kind.key_actions:
                return kind
        return None


DEFAULT_HOST_LED_OUTPUT_CONFIG = HostLedOutputConfig(frozenset({"caps_lock"}), False)


def normalize_host_led_output_config(raw: Any) -> HostLedOutputConfig:
    if raw is None:
        return DEFAULT_HOST_LED_OUTPUT_CONFIG
    if not isinstance(raw, dict):
        raise ValueError("host_led_output must be an object")

    enabled = _bool_value(raw.get("enabled", True), field="enabled")
    fallback = _bool_value(raw.get("fallback_internal_toggle", False), field="fallback_internal_toggle")
    states = _normalize_states(raw.get("states", {"caps_lock": True}))
    if not enabled:
        states = frozenset()
    return HostLedOutputConfig(states, fallback)


def host_led_states_from_report(report: int, config: HostLedOutputConfig) -> dict[str, bool]:
    value = int(report) & 0xFF
    return {
        state: bool(value & (1 << HOST_LED_KINDS[state].bit))
        for state in sorted(config.enabled_states)
    }


def apply_host_led_report(
    report: int,
    states: dict[str, bool],
    config: HostLedOutputConfig,
    push_state: Callable[[str, bool], None],
    *,
    force_sync: bool = False,
) -> dict[str, bool]:
    changed: dict[str, bool] = {}
    for state, enabled in host_led_states_from_report(report, config).items():
        if not force_sync and bool(states.get(state, False)) == enabled:
            continue
        states[state] = enabled
        changed[state] = enabled
        push_state(state, enabled)
    return changed


def toggle_host_led_state_for_action(
    action: str,
    states: dict[str, bool],
    config: HostLedOutputConfig,
    push_state: Callable[[str, bool], None],
) -> str | None:
    kind = config.kind_for_action(action)
    if kind is None:
        return None
    enabled = not bool(states.get(kind.name, False))
    states[kind.name] = enabled
    push_state(kind.name, enabled)
    return kind.name


def _normalize_states(raw: Any) -> frozenset[str]:
    if isinstance(raw, list):
        names = {str(item) for item in raw}
    elif isinstance(raw, dict):
        names = {str(name) for name, enabled in raw.items() if _bool_value(enabled, field=f"states.{name}")}
    else:
        raise ValueError("host_led_output.states must be an object or list")

    unknown = sorted(name for name in names if name not in HOST_LED_KINDS)
    if unknown:
        raise ValueError(f"unknown host LED output state(s): {', '.join(unknown)}")
    return frozenset(names)


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
    raise ValueError(f"host_led_output.{field} must be boolean")
