"""Stateful interaction engine for matrix key semantics.

The engine resolves physical matrix events into logical action events.  It also
owns state/time dependent key semantics such as oneshot layer and tap-hold so
those rules stay out of LayerManager and MacroExecutor.
"""
from __future__ import annotations

import heapq
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .action_expansion import space_cadet_tap_hold
from .key_lock import KeyLockEvent, KeyLockState
from .shared_action_defs import (
    is_animation_action,
    is_layer_action,
    is_macro_action,
    is_script_action,
)
from .morse_behavior import MorseBehaviorRuntime, normalize_morse_behaviors, parse_morse_action
from .morse_feedback import feedback_for_press, feedback_for_reset, feedback_from_step
from .mod_morph import ModMorphConfig, normalize_mod_morph_config, resolve_mod_morph_action

_DEFAULT_TAPPING_TERM = 0.200
_DEFAULT_COMBO_TERM = 0.050
_DEFAULT_TAP_DANCE_TERM = 0.200
_TAP_HOLD_RE = re.compile(r"^(LT|MT)\(([^,]+),\s*([^\)]+)\)$")
_TAP_TOGGLE_RE = re.compile(r"^TT\((\d+)\)$")
_TAP_DANCE_RE = re.compile(r"^TD\(([^\)]+)\)$")
_LAYER_HOLD_RE = re.compile(r"^MO\((\d+)\)$")
_LETTER_ACTION_RE = re.compile(r"^KC_([A-Z])$")
_CAPS_WORD_ALIASES = {"CAPS_WORD", "CAPS_WORD_TOGGLE", "CW_TOGG"}
_REPEAT_KEY_ALIASES = {
    "REPEAT_KEY": "REPEAT_KEY",
    "QK_REPEAT_KEY": "REPEAT_KEY",
    "ALT_REPEAT_KEY": "ALT_REPEAT_KEY",
    "QK_ALT_REPEAT_KEY": "ALT_REPEAT_KEY",
}
_OUTPUT_SWITCH_ACTIONS = {"KC_CONNAUTO", "KC_CONSOLE", "KC_USB", "KC_BT"}
_SYSTEM_ACTIONS = {"KC_SHUTDOWN", *_OUTPUT_SWITCH_ACTIONS}
_DEFAULT_CAPS_WORD_CONTINUE = ("KC_MINS", "KC_BSPC", "KC_DEL", "KC_UNDS")
_DEFAULT_CAPS_WORD_CANCEL = ("KC_SPACE", "KC_ENTER", "KC_ESC", "KC_TAB")
_DEFAULT_REPEAT_ALTERNATE_PAIRS = (
    ("KC_LEFT", "KC_RGHT"),
    ("KC_UP", "KC_DOWN"),
    ("KC_HOME", "KC_END"),
    ("KC_PGUP", "KC_PGDN"),
    ("KC_BSPC", "KC_DEL"),
    ("KC_WH_U", "KC_WH_D"),
    ("KC_WH_L", "KC_WH_R"),
    ("MS_LEFT", "MS_RGHT"),
    ("MS_UP", "MS_DOWN"),
)

_MOD_ALIASES = {
    "LCTL": "KC_LCTL",
    "LCtrl": "KC_LCTL",
    "LCTRL": "KC_LCTL",
    "MOD_LCTL": "KC_LCTL",
    "MOD_LCTRL": "KC_LCTL",
    "LSFT": "KC_LSFT",
    "LSHIFT": "KC_LSFT",
    "MOD_LSFT": "KC_LSFT",
    "MOD_LSHIFT": "KC_LSFT",
    "LALT": "KC_LALT",
    "MOD_LALT": "KC_LALT",
    "LGUI": "KC_LGUI",
    "LWIN": "KC_LWIN",
    "LCMD": "KC_LCMD",
    "MOD_LGUI": "KC_LGUI",
    "MOD_LWIN": "KC_LWIN",
    "RCTL": "KC_RCTL",
    "RCTRL": "KC_RCTL",
    "MOD_RCTL": "KC_RCTL",
    "MOD_RCTRL": "KC_RCTRL",
    "RSFT": "KC_RSFT",
    "RSHIFT": "KC_RSFT",
    "MOD_RSFT": "KC_RSFT",
    "MOD_RSHIFT": "KC_RSFT",
    "RALT": "KC_RALT",
    "MOD_RALT": "KC_RALT",
    "RGUI": "KC_RGUI",
    "RWIN": "KC_RWIN",
    "RCMD": "KC_RCMD",
    "MOD_RGUI": "KC_RGUI",
    "MOD_RWIN": "KC_RWIN",
}


@dataclass(frozen=True)
class ResolvedActionEvent:
    """Action event emitted by InteractionEngine."""

    action: str
    is_press: bool
    row: int | None = None
    col: int | None = None
    source: str = "matrix"


@dataclass(frozen=True)
class ComboDef:
    """Physical-key combo definition."""

    keys: frozenset[tuple[int, int]]
    action: str


@dataclass(frozen=True)
class TapDanceDef:
    """Tap dance definition mapping tap counts to actions."""

    name: str
    actions: dict[int, str]
    hold_action: str | None = None
    tap_hold_action: str | None = None
    term: float | None = None


@dataclass(frozen=True)
class KeyOverrideDef:
    """Action override activated by currently-held trigger actions."""

    trigger: frozenset[str]
    key: str
    replacement: str
    negative_trigger: frozenset[str] = frozenset()
    layers: int = 0xFFFF
    options: int = 0x83


@dataclass
class TapDanceState:
    """Pending tap dance state."""

    name: str
    count: int
    due: float
    generation: int
    row: int
    col: int


@dataclass
class KeyState:
    """Physical key state tracked by the interaction layer."""

    row: int
    col: int
    action: str
    physical_pressed: bool
    press_time: float
    interrupted: bool = False
    decided: bool = False
    tap_action: str | None = None
    hold_action: str | None = None
    hold_sent: bool = False
    suppressed: bool = False
    combo_action: str | None = None
    original_action: str | None = None
    tap_dance_count_base: int = 0
    normal_sent: bool = False
    override_suppressed_triggers: tuple[str, ...] = ()
    override_suppression_count: int = 0


@dataclass(order=True)
class InteractionTimer:
    """Timer entry for timeout-based interaction features."""

    due: float
    kind: str
    key: tuple[int, int] | None = None
    data: dict[str, Any] = field(default_factory=dict, compare=False)


def normalize_combos(combos: Iterable[Any] | None) -> list[ComboDef]:
    """Normalize combo definitions."""
    result: list[ComboDef] = []
    for combo in combos or []:
        if isinstance(combo, ComboDef):
            result.append(combo)
            continue
        if isinstance(combo, dict):
            keys = combo.get("keys", [])
            action = str(combo.get("action", "KC_NONE"))
        else:
            keys, action = combo
        norm_keys = frozenset((int(row), int(col)) for row, col in keys)
        if len(norm_keys) < 2:
            continue
        result.append(ComboDef(norm_keys, str(action)))
    return result


def normalize_tap_dances(tap_dances: Iterable[Any] | dict[str, Any] | None) -> dict[str, TapDanceDef]:
    """Normalize tap dance definitions."""
    result: dict[str, TapDanceDef] = {}
    if tap_dances is None:
        return result
    items: Iterable[Any]
    if isinstance(tap_dances, dict):
        items = tap_dances.items()
    else:
        items = tap_dances
    for entry in items:
        if isinstance(entry, TapDanceDef):
            result[entry.name] = entry
            continue
        if isinstance(entry, dict):
            name = str(entry.get("name", ""))
            actions_raw = entry.get("actions", {})
        else:
            name, actions_raw = entry
            name = str(name)
        raw_actions = dict(actions_raw)
        hold_action = raw_actions.pop("hold", None) or raw_actions.pop("on_hold", None)
        tap_hold_action = raw_actions.pop("tap_hold", None) or raw_actions.pop("on_tap_hold", None)
        term_raw = raw_actions.pop("term", None)
        term = None
        if term_raw is not None:
            try:
                term = max(0.001, float(term_raw))
            except (TypeError, ValueError):
                term = None
        actions = {int(count): str(action) for count, action in raw_actions.items()}
        if name and actions:
            result[name] = TapDanceDef(
                name=name,
                actions=actions,
                hold_action=str(hold_action) if hold_action else None,
                tap_hold_action=str(tap_hold_action) if tap_hold_action else None,
                term=term,
            )
    return result


def normalize_key_overrides(overrides: Iterable[Any] | None) -> list[KeyOverrideDef]:
    """Normalize key override definitions."""
    result: list[KeyOverrideDef] = []
    for entry in overrides or []:
        if isinstance(entry, KeyOverrideDef):
            result.append(entry)
            continue
        if isinstance(entry, dict):
            trigger_raw = entry.get("trigger", [])
            negative_raw = entry.get("negative_trigger", entry.get("negative", []))
            key = str(entry.get("key", ""))
            replacement = str(entry.get("replacement", "KC_NONE"))
            layers = int(entry.get("layers", 0xFFFF))
            options = int(entry.get("options", 0x83))
        else:
            trigger_raw, key, replacement = entry
            negative_raw = []
            layers = 0xFFFF
            options = 0x83
            key = str(key)
            replacement = str(replacement)
        if isinstance(trigger_raw, str):
            trigger = frozenset([trigger_raw])
        else:
            trigger = frozenset(str(item) for item in trigger_raw)
        if isinstance(negative_raw, str):
            negative_trigger = frozenset([negative_raw])
        else:
            negative_trigger = frozenset(str(item) for item in negative_raw or [])
        if trigger and key and replacement:
            result.append(KeyOverrideDef(
                trigger=trigger,
                key=key,
                replacement=replacement,
                negative_trigger=negative_trigger,
                layers=layers,
                options=options,
            ))
    return result


def normalize_caps_word_config(config: dict[str, Any] | None) -> dict[str, Any]:
    raw = config if isinstance(config, dict) else {}
    return {
        "enabled": bool(raw.get("enabled", True)),
        "continue_keys": frozenset(str(item) for item in raw.get("continue_keys", _DEFAULT_CAPS_WORD_CONTINUE)),
        "cancel_keys": frozenset(str(item) for item in raw.get("cancel_keys", _DEFAULT_CAPS_WORD_CANCEL)),
    }


def normalize_repeat_key_config(config: dict[str, Any] | None) -> dict[str, Any]:
    raw = config if isinstance(config, dict) else {}
    alternate: dict[str, str] = {}
    pairs = raw.get("alternate_pairs", _DEFAULT_REPEAT_ALTERNATE_PAIRS)
    for pair in pairs if isinstance(pairs, Iterable) else ():
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        left, right = str(pair[0]), str(pair[1])
        if not left or not right or left == right:
            continue
        alternate[left] = right
        alternate[right] = left
    return {
        "enabled": bool(raw.get("enabled", True)),
        "alternate": alternate,
    }


class InteractionEngine:
    """Resolve physical matrix events into logical action events."""

    def __init__(
        self,
        layers: Any,
        *,
        tapping_term: float = _DEFAULT_TAPPING_TERM,
        hold_on_other_key_press: bool = True,
        combo_term: float = _DEFAULT_COMBO_TERM,
        combos: Iterable[Any] | None = None,
        tap_dance_term: float = _DEFAULT_TAP_DANCE_TERM,
        tap_dances: Iterable[Any] | dict[str, Any] | None = None,
        morse_behaviors: dict[str, Any] | None = None,
        key_overrides: Iterable[Any] | None = None,
        caps_word: dict[str, Any] | None = None,
        repeat_key: dict[str, Any] | None = None,
        mod_morphs: dict[str, Any] | ModMorphConfig | None = None,
    ) -> None:
        self.layers = layers
        self.tapping_term = tapping_term
        self.hold_on_other_key_press = hold_on_other_key_press
        self.combo_term = combo_term
        self.combos = normalize_combos(combos)
        self.tap_dance_term = tap_dance_term
        self.tap_dances = normalize_tap_dances(tap_dances)
        self.morse_behaviors = normalize_morse_behaviors(morse_behaviors)
        self.morse_runtimes = {
            name: MorseBehaviorRuntime(definition)
            for name, definition in self.morse_behaviors.items()
        }
        self.key_overrides = normalize_key_overrides(key_overrides)
        self.mod_morphs = mod_morphs if isinstance(mod_morphs, ModMorphConfig) else normalize_mod_morph_config(mod_morphs)
        self.key_locks = KeyLockState()
        self.caps_word = normalize_caps_word_config(caps_word)
        self.caps_word_active = False
        self.repeat_key = normalize_repeat_key_config(repeat_key)
        self.repeat_history: str | None = None
        self.tap_dance_state: dict[str, TapDanceState] = {}
        self._tap_dance_generation = 0
        self.pressed: dict[tuple[int, int], KeyState] = {}
        self._cleared_release_keys: set[tuple[int, int]] = set()
        self.timers: list[InteractionTimer] = []
        self.morse_feedback_events: list[dict[str, Any]] = []

    def reset(self, layers: Any | None = None) -> list[ResolvedActionEvent]:
        """Clear transient interaction state after keymap/config reload."""
        if layers is not None:
            self.layers = layers
        events = self.clear_key_locks(reason="reset")
        events.extend(self.clear_held_keys(reason="reset"))
        self.timers.clear()
        self.tap_dance_state.clear()
        self.clear_runtime_shortcuts()
        for name, runtime in self.morse_runtimes.items():
            runtime.reset()
            self._record_morse_feedback(feedback_for_reset(name))
        return events

    def clear_runtime_shortcuts(self) -> None:
        """Clear non-persistent helper state without disturbing held keys."""
        self.caps_word_active = False
        self.repeat_history = None

    def clear_key_locks(self, *, reason: str | None = None) -> list[ResolvedActionEvent]:
        """Release all synthetic key locks and return dispatchable events."""
        return self._key_lock_events(self.key_locks.clear(reason=reason))

    def clear_held_keys(
        self,
        *,
        reason: str = "clear",
        exclude_actions: Iterable[str] = (),
    ) -> list[ResolvedActionEvent]:
        """Release host-visible held interaction actions and clear physical state."""
        events: list[ResolvedActionEvent] = []
        excluded = set(exclude_actions)
        kept: dict[tuple[int, int], KeyState] = {}
        for state in list(self.pressed.values()):
            action = self._state_host_action(state)
            key = (state.row, state.col)
            if action in excluded:
                kept[(state.row, state.col)] = state
                continue
            self._cleared_release_keys.add(key)
            if action is not None:
                events.append(ResolvedActionEvent(
                    action=action,
                    is_press=False,
                    row=state.row,
                    col=state.col,
                    source=reason,
                ))
        self.pressed = kept
        self.timers.clear()
        self.tap_dance_state.clear()
        return events

    def drain_morse_feedback(self) -> list[dict[str, Any]]:
        """Return and clear buffered MORSE feedback events."""
        events = list(self.morse_feedback_events)
        self.morse_feedback_events.clear()
        return events

    def _record_morse_feedback(self, event: Any) -> None:
        self.morse_feedback_events.append(event.to_dict())

    def _push_timer(self, timer: InteractionTimer) -> None:
        heapq.heappush(self.timers, timer)

    def next_timer_due(self) -> float | None:
        """Return the earliest pending interaction timer deadline."""
        if not self.timers:
            return None
        return self.timers[0].due

    def _schedule_hold_timeout(self, key: tuple[int, int], due: float, press_time: float) -> None:
        self._push_timer(InteractionTimer(
            due=due,
            kind="hold",
            key=key,
            data={"press_time": press_time},
        ))

    def _schedule_combo_source_timeout(self, key: tuple[int, int], due: float) -> None:
        self._push_timer(InteractionTimer(due=due, kind="combo_source", key=key))

    def _schedule_tap_dance_timeout(self, name: str, due: float, generation: int) -> None:
        self._push_timer(InteractionTimer(
            due=due,
            kind="tapdance",
            data={"name": name, "generation": generation},
        ))

    def _schedule_morse_timeout(self, name: str, due: float, generation: int, row: int, col: int) -> None:
        self._push_timer(InteractionTimer(
            due=due,
            kind="morse",
            data={"name": name, "generation": generation, "row": row, "col": col},
        ))

    def _consume_oneshot_if_needed(self, action: str) -> None:
        if not self.layers.has_oneshot():
            return
        if self.layers.is_layer_action(action):
            return
        if action in {"KC_NONE", ""}:
            return
        self.layers.oneshot_clear()

    def _parse_tap_hold(self, action: str) -> tuple[str, str] | None:
        space_cadet = space_cadet_tap_hold(action)
        if space_cadet is not None:
            return space_cadet

        m = _TAP_HOLD_RE.match(action)
        if m:
            op, first, tap_action = m.group(1), m.group(2).strip(), m.group(3).strip()
            if op == "LT":
                return tap_action, f"MO({int(first)})"
            mod_action = _MOD_ALIASES.get(first, first)
            if not mod_action.startswith("KC_"):
                mod_action = f"KC_{mod_action}"
            return tap_action, mod_action

        tt_m = _TAP_TOGGLE_RE.match(action)
        if tt_m:
            layer = int(tt_m.group(1))
            return f"TG({layer})", f"MO({layer})"
        return None

    def _parse_tap_dance(self, action: str) -> str | None:
        m = _TAP_DANCE_RE.match(action)
        if not m:
            return None
        name = m.group(1).strip()
        return name if name in self.tap_dances else None

    def _parse_morse(self, action: str) -> str | None:
        name = parse_morse_action(action)
        return name if name in self.morse_runtimes else None

    def _event(self, action: str, is_press: bool, row: int | None, col: int | None, source: str = "matrix") -> ResolvedActionEvent:
        if is_press:
            self._record_repeat_history(action)
        return ResolvedActionEvent(action=action, is_press=is_press, row=row, col=col, source=source)

    def _tap_events(self, tap_action: str, row: int | None, col: int | None, source: str = "matrix") -> list[ResolvedActionEvent]:
        return [
            self._event(tap_action, True, row, col, source),
            self._event(tap_action, False, row, col, source),
        ]

    def _active_actions(self) -> set[str]:
        active: set[str] = set()
        for state in self.pressed.values():
            if state.suppressed:
                continue
            if state.combo_action is not None:
                active.add(state.combo_action)
            elif state.hold_sent and state.hold_action is not None:
                active.add(state.hold_action)
            else:
                active.add(state.action)
        active.update(self.key_locks.active_actions())
        return active

    def _normalize_control_action(self, action: str) -> str:
        if action in _CAPS_WORD_ALIASES:
            return "CAPS_WORD"
        return _REPEAT_KEY_ALIASES.get(action, action)

    def _is_caps_word_letter(self, action: str) -> bool:
        return bool(_LETTER_ACTION_RE.fullmatch(action))

    def _apply_caps_word(self, action: str) -> str:
        if not self.caps_word.get("enabled", True) or not self.caps_word_active:
            return action
        if self._is_caps_word_letter(action):
            return f"S({action})"
        if action in self.caps_word["continue_keys"]:
            return action
        self.caps_word_active = False
        return action

    def _is_repeatable_action(self, action: str) -> bool:
        normalized = self._normalize_control_action(action)
        if normalized in {"CAPS_WORD", "REPEAT_KEY", "ALT_REPEAT_KEY", "KC_NONE", "KC_TRNS", ""}:
            return False
        if is_layer_action(normalized):
            return False
        if self._parse_tap_dance(normalized) is not None or self._parse_morse(normalized) is not None:
            return False
        if is_macro_action(normalized) or is_script_action(normalized) or is_animation_action(normalized):
            return False
        if normalized.startswith("KC_SH") or normalized.startswith("BT_") or normalized.startswith("WIFI_"):
            return False
        if normalized in _SYSTEM_ACTIONS:
            return False
        if normalized.startswith(("RGB_", "RM_")):
            return False
        return True

    def _record_repeat_history(self, action: str) -> None:
        if self.repeat_key.get("enabled", True) and self._is_repeatable_action(action):
            self.repeat_history = action

    def _control_action_events(self, action: str, row: int, col: int) -> list[ResolvedActionEvent] | None:
        key_lock_result = self.key_locks.handle_action(action, is_press=True)
        if key_lock_result is not None:
            return self._key_lock_events(key_lock_result.events)
        normalized = self._normalize_control_action(action)
        if normalized == "CAPS_WORD":
            if self.caps_word.get("enabled", True):
                self.caps_word_active = not self.caps_word_active
            return []
        if normalized == "REPEAT_KEY":
            if not self.repeat_key.get("enabled", True) or self.repeat_history is None:
                return []
            return self._tap_events(self.repeat_history, row, col, source="repeat")
        if normalized == "ALT_REPEAT_KEY":
            if not self.repeat_key.get("enabled", True) or self.repeat_history is None:
                return []
            alternate = self.repeat_key["alternate"].get(self.repeat_history)
            if alternate is None:
                return []
            return self._tap_events(alternate, row, col, source="repeat")
        return None

    def _key_lock_events(self, events: Iterable[KeyLockEvent]) -> list[ResolvedActionEvent]:
        return [
            ResolvedActionEvent(action=event.action, is_press=event.is_press, row=None, col=None, source=event.source)
            for event in events
        ]

    def _is_combo_source_key(self, key: tuple[int, int]) -> bool:
        return any(key in combo.keys for combo in self.combos)

    def _resolve_key_override(self, action: str) -> tuple[str, tuple[str, ...]]:
        active = self._active_actions()
        active_layers = self._active_layer_ids()
        for override in self.key_overrides:
            if not (override.options & 0x80):
                continue
            if not any(override.layers & (1 << int(layer)) for layer in active_layers if 0 <= int(layer) < 16):
                continue
            if override.key == action and override.trigger <= active and not (override.negative_trigger & active):
                return override.replacement, tuple(sorted(override.trigger))
        return action, ()

    def _apply_key_override(self, action: str) -> str:
        replacement, _suppressed_triggers = self._resolve_key_override(action)
        return replacement

    def _override_suppression_event(self, action: str, is_press: bool, row: int | None, col: int | None) -> ResolvedActionEvent:
        return ResolvedActionEvent(action=action, is_press=is_press, row=row, col=col, source="key_override")

    def _state_active_action(self, state: KeyState) -> str | None:
        if state.suppressed:
            return None
        if state.combo_action is not None:
            return state.combo_action
        if state.hold_sent and state.hold_action is not None:
            return state.hold_action
        if state.normal_sent:
            return state.action
        return None

    def _state_host_action(self, state: KeyState) -> str | None:
        if state.override_suppression_count > 0:
            return None
        return self._state_active_action(state)

    def _suppress_key_override_triggers(self, triggers: Iterable[str]) -> list[ResolvedActionEvent]:
        events: list[ResolvedActionEvent] = []
        for trigger in triggers:
            for state in self.pressed.values():
                if self._state_active_action(state) != trigger:
                    continue
                state.override_suppression_count += 1
                if state.override_suppression_count == 1:
                    events.append(self._override_suppression_event(trigger, False, state.row, state.col))
                break
        return events

    def _restore_key_override_triggers(self, triggers: Iterable[str]) -> list[ResolvedActionEvent]:
        events: list[ResolvedActionEvent] = []
        for trigger in triggers:
            for state in self.pressed.values():
                if self._state_active_action(state) != trigger or state.override_suppression_count <= 0:
                    continue
                state.override_suppression_count -= 1
                if state.override_suppression_count == 0:
                    events.append(self._override_suppression_event(trigger, True, state.row, state.col))
                break
        return events

    def _active_layer_ids(self) -> list[int]:
        if not hasattr(self.layers, "active_snapshot"):
            return [0]
        return list(self.layers.active_snapshot().get("all", [0]))

    def _apply_mod_morph(self, action: str) -> str:
        return resolve_mod_morph_action(
            action,
            self.mod_morphs,
            held_actions=self._active_actions(),
            active_layers=self._active_layer_ids(),
        )

    def _resolve_tap_dance_action(self, name: str, count: int) -> str:
        definition = self.tap_dances[name]
        if count in definition.actions:
            return definition.actions[count]
        max_count = max(definition.actions)
        return definition.actions[max_count]

    def _tap_dance_double_action(self, name: str) -> str:
        definition = self.tap_dances[name]
        if 2 in definition.actions:
            return definition.actions[2]
        return self._resolve_tap_dance_action(name, 2)

    def _tap_dance_hold_action(self, name: str) -> str | None:
        return self.tap_dances[name].hold_action

    def _tap_dance_tap_hold_action(self, name: str) -> str | None:
        return self.tap_dances[name].tap_hold_action

    def _tap_dance_term(self, name: str) -> float:
        return self.tap_dances[name].term or self.tap_dance_term

    def _tap_dance_events(self, name: str, count: int, row: int, col: int) -> list[ResolvedActionEvent]:
        action = self._resolve_tap_dance_action(name, count)
        return self._tap_events(action, row, col, source="tapdance")

    def _record_tap_dance(self, name: str, row: int, col: int, now: float, *, count_override: int | None = None) -> None:
        prev = self.tap_dance_state.get(name)
        count = count_override if count_override is not None else ((prev.count + 1) if prev is not None else 1)
        self._tap_dance_generation += 1
        generation = self._tap_dance_generation
        due = now + self._tap_dance_term(name)
        self.tap_dance_state[name] = TapDanceState(
            name=name,
            count=count,
            due=due,
            generation=generation,
            row=row,
            col=col,
        )
        self._schedule_tap_dance_timeout(name, due, generation)

    def _start_tap_dance_press(self, name: str, row: int, col: int, now: float) -> list[ResolvedActionEvent]:
        key = (row, col)
        prev = self.tap_dance_state.get(name)
        tap_hold_action = self._tap_dance_tap_hold_action(name)
        if prev is not None and prev.count == 1 and tap_hold_action is not None:
            self.tap_dance_state.pop(name, None)
            self.pressed[key] = KeyState(
                row=row,
                col=col,
                action=f"TD({name})",
                original_action=f"TD({name})",
                physical_pressed=True,
                press_time=now,
                tap_action=self._tap_dance_double_action(name),
                hold_action=tap_hold_action,
                tap_dance_count_base=prev.count,
            )
            self._schedule_hold_timeout(key, now + self._tap_dance_term(name), now)
            return []

        hold_action = self._tap_dance_hold_action(name)
        self.pressed[key] = KeyState(
            row=row,
            col=col,
            action=f"TD({name})",
            original_action=f"TD({name})",
            physical_pressed=True,
            press_time=now,
            hold_action=hold_action,
        )
        if hold_action is not None:
            self._schedule_hold_timeout(key, now + self._tap_dance_term(name), now)
        return []

    def _start_morse_press(self, name: str, row: int, col: int, now: float) -> list[ResolvedActionEvent]:
        runtime = self.morse_runtimes[name]
        runtime.press(now)
        self._record_morse_feedback(feedback_for_press(name, row=row, col=col))
        return []

    def _finish_morse_release(self, name: str, row: int, col: int, now: float) -> list[ResolvedActionEvent]:
        runtime = self.morse_runtimes[name]
        result = runtime.release(now)
        self._record_morse_feedback(feedback_from_step(name, result, row=row, col=col))
        if result.committed_action is not None:
            return self._tap_events(result.committed_action, row, col, source="morse")
        if result.needs_timeout:
            self._schedule_morse_timeout(
                name,
                now + runtime.definition.sequence_timeout,
                runtime.state.generation,
                row,
                col,
            )
        return []

    def _activate_hold(self, key: tuple[int, int], state: KeyState) -> list[ResolvedActionEvent]:
        if state.hold_action is None or state.hold_sent or state.suppressed:
            return []
        state.decided = True
        state.hold_sent = True
        state.interrupted = True

        layer_m = _LAYER_HOLD_RE.match(state.hold_action)
        if layer_m:
            self.layers.momentary_on(int(layer_m.group(1)))
        return [self._event(state.hold_action, True, state.row, state.col)]

    def _activate_due_tap_dance(self, timer: InteractionTimer) -> list[ResolvedActionEvent]:
        name = str(timer.data.get("name", ""))
        generation = int(timer.data.get("generation", -1))
        state = self.tap_dance_state.get(name)
        if state is None or state.generation != generation:
            return []
        self.tap_dance_state.pop(name, None)
        return self._tap_dance_events(name, state.count, state.row, state.col)

    def _activate_due_morse(self, timer: InteractionTimer) -> list[ResolvedActionEvent]:
        name = str(timer.data.get("name", ""))
        runtime = self.morse_runtimes.get(name)
        if runtime is None:
            return []
        generation = int(timer.data.get("generation", -1))
        if runtime.state.generation != generation:
            return []
        row = int(timer.data.get("row", -1))
        col = int(timer.data.get("col", -1))
        result = runtime.timeout()
        self._record_morse_feedback(feedback_from_step(name, result, row=row, col=col))
        if result.committed_action is None:
            return []
        return self._tap_events(result.committed_action, row, col, source="morse")

    def _activate_due_timers(self, now: float) -> list[ResolvedActionEvent]:
        events: list[ResolvedActionEvent] = []
        while self.timers and self.timers[0].due <= now:
            timer = heapq.heappop(self.timers)
            if timer.kind == "tapdance":
                events.extend(self._activate_due_tap_dance(timer))
                continue
            if timer.kind == "morse":
                events.extend(self._activate_due_morse(timer))
                continue
            if timer.kind == "combo_source" and timer.key is not None:
                state = self.pressed.get(timer.key)
                if (
                    state is not None
                    and state.hold_action is None
                    and state.combo_action is None
                    and not state.suppressed
                    and not state.normal_sent
                ):
                    state.normal_sent = True
                    events.append(self._event(state.action, True, state.row, state.col))
                continue
            if timer.kind != "hold" or timer.key is None:
                continue
            state = self.pressed.get(timer.key)
            if (
                state is None
                or state.hold_action is None
                or state.hold_sent
                or state.suppressed
                or state.press_time != timer.data.get("press_time")
            ):
                continue
            events.extend(self._activate_hold(timer.key, state))
        return events

    def _activate_interrupted_holds(self, current_key: tuple[int, int]) -> list[ResolvedActionEvent]:
        if not self.hold_on_other_key_press:
            return []
        events: list[ResolvedActionEvent] = []
        for key, state in list(self.pressed.items()):
            if key == current_key:
                continue
            if state.hold_action is not None and not state.hold_sent and not state.suppressed:
                events.extend(self._activate_hold(key, state))
        return events

    def _try_activate_combo(self, current_key: tuple[int, int], now: float) -> list[ResolvedActionEvent]:
        pressed_keys = set(self.pressed)
        candidates = [combo for combo in self.combos if current_key in combo.keys and combo.keys <= pressed_keys]
        if not candidates:
            return []
        combo = max(candidates, key=lambda item: len(item.keys))
        press_times = [self.pressed[key].press_time for key in combo.keys]
        if max(press_times) - min(press_times) > self.combo_term:
            return []
        events: list[ResolvedActionEvent] = []
        for key in combo.keys:
            state = self.pressed[key]
            if state.normal_sent:
                events.append(self._event(state.action, False, state.row, state.col))
                state.normal_sent = False
            state.suppressed = True
            state.combo_action = combo.action
            state.decided = True
        row, col = current_key
        events.append(self._event(combo.action, True, row, col, source="combo"))
        return events

    def on_key(self, row: int, col: int, is_press: bool, now: float) -> list[ResolvedActionEvent]:
        """Return action events for a physical matrix event."""
        key = (row, col)
        events: list[ResolvedActionEvent] = []

        if is_press:
            self._cleared_release_keys.discard(key)
            events.extend(self._activate_due_timers(now))
            action = self.layers.get_action(row, col)
            self._consume_oneshot_if_needed(action)
            action, override_suppressed_triggers = self._resolve_key_override(action)
            action = self._apply_mod_morph(action)
            action = self._normalize_control_action(action)
            control_events = self._control_action_events(action, row, col)
            if control_events is not None:
                self.pressed[key] = KeyState(
                    row=row,
                    col=col,
                    action=action,
                    original_action=action,
                    physical_pressed=True,
                    press_time=now,
                    suppressed=True,
                    override_suppressed_triggers=override_suppressed_triggers,
                )
                return [*self._suppress_key_override_triggers(override_suppressed_triggers), *control_events]
            action = self._apply_caps_word(action)
            tap_hold = self._parse_tap_hold(action)
            original_action = self.layers.get_action(row, col)
            if tap_hold is not None:
                tap_action, hold_action = tap_hold
                self.pressed[key] = KeyState(
                    row=row,
                    col=col,
                    action=action,
                    original_action=original_action,
                    physical_pressed=True,
                    press_time=now,
                    tap_action=tap_action,
                    hold_action=hold_action,
                    override_suppressed_triggers=override_suppressed_triggers,
                )
                self._schedule_hold_timeout(key, now + self.tapping_term, now)
            else:
                self.pressed[key] = KeyState(
                    row=row,
                    col=col,
                    action=action,
                    original_action=original_action,
                    physical_pressed=True,
                    press_time=now,
                    override_suppressed_triggers=override_suppressed_triggers,
                )

            combo_events = self._try_activate_combo(key, now)
            if combo_events:
                events.extend(combo_events)
                return events

            events.extend(self._activate_interrupted_holds(key))
            if tap_hold is not None:
                return events
            if events:
                action = self._apply_key_override(self.layers.get_action(row, col))
                action = self._apply_mod_morph(action)
                action = self._apply_caps_word(self._normalize_control_action(action))
                current_state = self.pressed.get(key)
                if current_state is not None:
                    current_state.action = action
                    current_state.original_action = action
            tap_dance = self._parse_tap_dance(action)
            if tap_dance is not None:
                events.extend(self._start_tap_dance_press(tap_dance, row, col, now))
                return events
            morse = self._parse_morse(action)
            if morse is not None:
                events.extend(self._start_morse_press(morse, row, col, now))
                return events
            # Combo source keys are delayed for combo_term so a successful combo
            # does not leak the first source key or leave release state skewed.
            if self._is_combo_source_key(key):
                self._schedule_combo_source_timeout(key, now + self.combo_term)
                return events
            state = self.pressed.get(key)
            if state is not None:
                state.normal_sent = True
            events.extend(self._suppress_key_override_triggers(override_suppressed_triggers))
            events.append(self._event(action, True, row, col))
            return events

        state = self.pressed.pop(key, None)
        if state is None:
            if key in self._cleared_release_keys:
                self._cleared_release_keys.discard(key)
                return events
            action = self.layers.get_action(row, col)
            events.append(self._event(action, False, row, col))
            return events

        if state.combo_action is not None:
            if not any(other.combo_action == state.combo_action for other in self.pressed.values()):
                events.append(self._event(state.combo_action, False, row, col, source="combo"))
            return events

        if state.suppressed:
            events.extend(self._restore_key_override_triggers(state.override_suppressed_triggers))
            return events

        if state.override_suppression_count > 0:
            return events

        tap_dance = self._parse_tap_dance(state.action)
        if tap_dance is not None:
            if state.hold_sent:
                events.append(self._event(state.hold_action or "KC_NONE", False, row, col))
                return events
            if state.hold_action is not None and state.tap_action is not None:
                self._record_tap_dance(tap_dance, row, col, now, count_override=state.tap_dance_count_base + 1)
                return events
            self._record_tap_dance(tap_dance, row, col, now)
            return events

        morse = self._parse_morse(state.action)
        if morse is not None:
            events.extend(self._finish_morse_release(morse, row, col, now))
            return events

        if state.hold_action is not None:
            if state.hold_sent:
                events.append(self._event(state.hold_action, False, row, col))
            else:
                tap = state.tap_action or "KC_NONE"
                events.extend(self._tap_events(tap, row, col))
            return events

        if state.normal_sent:
            events.append(self._event(state.action, False, row, col))
        else:
            events.extend(self._tap_events(state.action, row, col))
        events.extend(self._restore_key_override_triggers(state.override_suppressed_triggers))
        return events

    def on_tick(self, now: float) -> list[ResolvedActionEvent]:
        """Return timeout-generated action events."""
        return self._activate_due_timers(now)
