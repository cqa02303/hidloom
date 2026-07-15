"""Runtime helper for Key Toggle / Key Lock / Drag Lock.

This module intentionally does not talk to HID devices directly.  It owns only
transient synthetic lock state and emits press/release action events for the
caller to dispatch through the normal output path.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

_KEY_LOCK_RE = re.compile(r"^(KEY_TOGGLE|KEY_LOCK|KEY_UNLOCK)\(([^)]+)\)$")
_MOUSE_BUTTON_RE = re.compile(r"^KC_BTN([1-5])$")

_MODIFIER_KEYS = frozenset({
    "KC_LCTL",
    "KC_LCTRL",
    "KC_RCTL",
    "KC_RCTRL",
    "KC_LSFT",
    "KC_LSHIFT",
    "KC_RSFT",
    "KC_RSHIFT",
    "KC_LALT",
    "KC_RALT",
    "KC_LGUI",
    "KC_LWIN",
    "KC_LCMD",
    "KC_RGUI",
    "KC_RWIN",
    "KC_RCMD",
})
_MOUSE_BUTTON_KEYS = frozenset(f"KC_BTN{idx}" for idx in range(1, 6))


@dataclass(frozen=True)
class KeyLockTarget:
    """Normalized target accepted by Key Lock."""

    action: str
    kind: str


@dataclass(frozen=True)
class KeyLockCommand:
    """Parsed Key Lock command."""

    op: str
    target: KeyLockTarget
    source: str


@dataclass(frozen=True)
class KeyLockEvent:
    """Synthetic event emitted by KeyLockState."""

    action: str
    is_press: bool
    source: str = "key_lock"


@dataclass(frozen=True)
class KeyLockEntry:
    """Active synthetic lock state."""

    action: str
    kind: str
    source: str

    def to_status(self) -> dict[str, object]:
        return {
            "action": self.action,
            "mode": "locked",
            "source": self.source,
            "kind": self.kind,
            "locked": True,
            "cancel_reason": None,
        }


@dataclass(frozen=True)
class KeyLockResult:
    """Result of handling a key-lock action."""

    handled: bool
    changed: bool
    events: tuple[KeyLockEvent, ...] = ()
    warning: str | None = None


def normalize_key_lock_target(action: str) -> KeyLockTarget | None:
    """Return an accepted Key Lock target, or None for unsupported actions."""
    target = action.strip()
    if target in _MODIFIER_KEYS:
        return KeyLockTarget(action=target, kind="modifier")
    if target in _MOUSE_BUTTON_KEYS or _MOUSE_BUTTON_RE.fullmatch(target):
        return KeyLockTarget(action=target, kind="mouse_button")
    return None


def parse_key_lock_action(action: str) -> KeyLockCommand | None:
    """Parse KEY_TOGGLE/KEY_LOCK/KEY_UNLOCK/DRAG_LOCK action names."""
    if action == "DRAG_LOCK":
        target = normalize_key_lock_target("KC_BTN1")
        assert target is not None
        return KeyLockCommand(op="KEY_TOGGLE", target=target, source="DRAG_LOCK")

    match = _KEY_LOCK_RE.fullmatch(action.strip())
    if not match:
        return None
    target = normalize_key_lock_target(match.group(2).strip())
    if target is None:
        return KeyLockCommand(
            op=match.group(1),
            target=KeyLockTarget(action=match.group(2).strip(), kind="unsupported"),
            source=match.group(1),
        )
    return KeyLockCommand(op=match.group(1), target=target, source=match.group(1))


class KeyLockState:
    """Track synthetic key locks separately from physical key state."""

    def __init__(self) -> None:
        self._locked: dict[str, KeyLockEntry] = {}

    def active_actions(self) -> tuple[str, ...]:
        return tuple(sorted(self._locked))

    def status(self) -> dict[str, list[dict[str, object]]]:
        """Return Sticky status compatible read-only key lock state."""
        return {
            "keys": [
                self._locked[action].to_status()
                for action in sorted(self._locked)
            ]
        }

    def is_locked(self, action: str) -> bool:
        return action in self._locked

    def handle_action(self, action: str, *, is_press: bool = True) -> KeyLockResult | None:
        """Handle a Key Lock command and return synthetic events.

        Release events of the command key are consumed but do not mutate state.
        Unsupported targets are consumed with a warning so they cannot fall
        through to the normal macro executor.
        """
        command = parse_key_lock_action(action)
        if command is None:
            return None
        if not is_press:
            return KeyLockResult(handled=True, changed=False)
        if command.target.kind == "unsupported":
            return KeyLockResult(
                handled=True,
                changed=False,
                warning=f"unsupported key lock target: {command.target.action}",
            )
        target = command.target.action
        if command.op == "KEY_UNLOCK":
            return self._unlock(target)
        if command.op == "KEY_LOCK":
            return self._lock(command.target, command.source)
        if target in self._locked:
            return self._unlock(target)
        return self._lock(command.target, command.source)

    def _lock(self, target: KeyLockTarget, source: str) -> KeyLockResult:
        if target.action in self._locked:
            return KeyLockResult(handled=True, changed=False)
        self._locked[target.action] = KeyLockEntry(
            action=target.action,
            kind=target.kind,
            source=source,
        )
        return KeyLockResult(
            handled=True,
            changed=True,
            events=(KeyLockEvent(target.action, True),),
        )

    def _unlock(self, action: str) -> KeyLockResult:
        if action not in self._locked:
            return KeyLockResult(handled=True, changed=False)
        self._locked.pop(action, None)
        return KeyLockResult(
            handled=True,
            changed=True,
            events=(KeyLockEvent(action, False),),
        )

    def clear(self, *, reason: str | None = None) -> tuple[KeyLockEvent, ...]:
        """Release all synthetic locks and clear state."""
        events = tuple(
            KeyLockEvent(action=action, is_press=False)
            for action in sorted(self._locked)
        )
        self._locked.clear()
        return events


def key_lock_supported_targets() -> dict[str, tuple[str, ...]]:
    """Return accepted target actions grouped by kind."""
    return {
        "modifier": tuple(sorted(_MODIFIER_KEYS)),
        "mouse_button": tuple(sorted(_MOUSE_BUTTON_KEYS)),
    }


def reject_unsafe_key_lock_targets(actions: Iterable[str]) -> tuple[str, ...]:
    """Return unsupported target actions from a candidate list."""
    rejected: list[str] = []
    for action in actions:
        if normalize_key_lock_target(str(action)) is None:
            rejected.append(str(action))
    return tuple(rejected)
