"""Default-off ASCII autocorrect runtime helper.

This helper is intentionally independent from the live HID dispatch path.  It
validates a small dictionary and converts final tap actions into an internal
tap sequence for callers that provide the normal cancellation gates.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

_WORD_RE = re.compile(r"^[a-z]+$")
_KC_TO_CHAR = {f"KC_{chr(code)}": chr(code + 32) for code in range(ord("A"), ord("Z") + 1)}
_CHAR_TO_KC = {char: keycode for keycode, char in _KC_TO_CHAR.items()}
_BOUNDARY_ACTIONS = {
    "KC_SPACE",
    "KC_ENTER",
    "KC_TAB",
    "KC_DOT",
    "KC_COMM",
    "KC_SCLN",
    "KC_QUOT",
    "KC_SLSH",
    "KC_MINS",
    "KC_EQL",
}
_BACKSPACE_ACTIONS = {"KC_BSPC", "KC_BACKSPACE"}


@dataclass(frozen=True)
class AutocorrectValidation:
    enabled: bool
    mode: str
    entries: dict[str, str]
    max_word_length: int
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class AutocorrectResult:
    correction: tuple[str, ...] = ()
    buffer: str = ""
    cleared: bool = False
    reason: str | None = None

    @property
    def corrected(self) -> bool:
        return bool(self.correction)


def validate_autocorrect_settings(settings: dict[str, Any] | None) -> AutocorrectValidation:
    raw = settings if isinstance(settings, dict) else {}
    enabled = bool(raw.get("enabled", False))
    mode = raw.get("mode", "ascii_words")
    max_word_length = raw.get("max_word_length", 32)
    entries_raw = raw.get("entries", {})
    errors: list[str] = []
    warnings: list[str] = []
    entries: dict[str, str] = {}

    if mode != "ascii_words":
        errors.append("autocorrect mode must be ascii_words")
    if not isinstance(max_word_length, int) or not (1 <= max_word_length <= 64):
        errors.append("autocorrect max_word_length must be 1..64")
        max_word_length = 32
    if not isinstance(entries_raw, dict):
        errors.append("autocorrect entries must be an object")
        entries_raw = {}

    for trigger, replacement in entries_raw.items():
        if not isinstance(trigger, str) or not isinstance(replacement, str):
            errors.append("autocorrect trigger and replacement must be strings")
            continue
        if trigger != trigger.lower() or not _WORD_RE.match(trigger):
            errors.append(f"autocorrect trigger must be lower-case ASCII word: {trigger!r}")
            continue
        if not _WORD_RE.match(replacement):
            errors.append(f"autocorrect replacement must be lower-case ASCII word: {trigger!r}")
            continue
        if len(trigger) > max_word_length or len(replacement) > max_word_length:
            errors.append(f"autocorrect entry exceeds max_word_length: {trigger!r}")
            continue
        if trigger == replacement:
            warnings.append(f"autocorrect entry is a no-op: {trigger!r}")
            continue
        entries[trigger] = replacement

    return AutocorrectValidation(
        enabled=enabled,
        mode="ascii_words",
        entries=entries,
        max_word_length=max_word_length,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


class AutocorrectRuntime:
    """Small word-buffer runtime for final tap actions."""

    def __init__(self, settings: dict[str, Any] | None) -> None:
        validation = validate_autocorrect_settings(settings)
        self.validation = validation
        self.enabled = validation.enabled and validation.ok
        self._entries = validation.entries
        self._max_word_length = validation.max_word_length
        self._buffer = ""

    @property
    def buffer(self) -> str:
        return self._buffer

    def reset(self) -> None:
        self._buffer = ""

    def handle_action(self, action: str, is_press: bool) -> AutocorrectResult:
        if not is_press:
            return AutocorrectResult(buffer=self._buffer)
        if not self.enabled:
            return AutocorrectResult(buffer="")

        char = _KC_TO_CHAR.get(action)
        if char is not None:
            self._buffer = (self._buffer + char)[-self._max_word_length :]
            return AutocorrectResult(buffer=self._buffer)

        if action in _BACKSPACE_ACTIONS:
            self._buffer = self._buffer[:-1]
            return AutocorrectResult(buffer=self._buffer, reason="backspace")

        if action in _BOUNDARY_ACTIONS:
            result = self._apply_boundary(action)
            self._buffer = ""
            return result

        self._buffer = ""
        return AutocorrectResult(buffer="", cleared=True, reason="non_printable")

    def _apply_boundary(self, boundary_action: str) -> AutocorrectResult:
        replacement = self._entries.get(self._buffer)
        if replacement is None:
            return AutocorrectResult(buffer="", reason="boundary")
        correction = tuple(["KC_BSPC"] * len(self._buffer) + [_CHAR_TO_KC[c] for c in replacement] + [boundary_action])
        return AutocorrectResult(correction=correction, buffer="", reason="correction")
