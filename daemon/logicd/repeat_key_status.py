"""Read-only helpers for Repeat Key status and alternate pair metadata.

The runtime history itself remains owned by InteractionEngine.  This module
keeps user-facing status privacy-safe by exposing only availability flags and
alternate support, never the remembered action name.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

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


@dataclass(frozen=True)
class RepeatKeyStatus:
    """Privacy-safe Repeat Key status."""

    enabled: bool
    history_available: bool
    alternate_available: bool
    alternate_pair_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "history_available": self.history_available,
            "alternate_available": self.alternate_available,
            "alternate_pair_count": self.alternate_pair_count,
        }


def normalize_alternate_pairs(pairs: Iterable[object] | None = None) -> dict[str, str]:
    """Normalize alternate pairs into a bidirectional action map."""
    alternate: dict[str, str] = {}
    for pair in pairs if pairs is not None else _DEFAULT_REPEAT_ALTERNATE_PAIRS:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        left, right = str(pair[0]), str(pair[1])
        if not left or not right or left == right:
            continue
        alternate[left] = right
        alternate[right] = left
    return alternate


def alternate_pair_count(alternate: Mapping[str, str]) -> int:
    """Return the number of logical alternate pairs in a bidirectional map."""
    seen: set[frozenset[str]] = set()
    for left, right in alternate.items():
        if not left or not right or left == right:
            continue
        seen.add(frozenset((left, right)))
    return len(seen)


def repeat_key_status(
    *,
    enabled: bool,
    repeat_history: str | None,
    alternate: Mapping[str, str],
) -> RepeatKeyStatus:
    """Build a privacy-safe status payload.

    The remembered action name is intentionally not returned.  UI consumers only
    need to know whether Repeat and Alternate Repeat can do something now.
    """
    history_available = bool(enabled and repeat_history)
    alternate_available = bool(history_available and repeat_history in alternate)
    return RepeatKeyStatus(
        enabled=enabled,
        history_available=history_available,
        alternate_available=alternate_available,
        alternate_pair_count=alternate_pair_count(alternate),
    )


def repeat_key_status_from_engine(engine: object) -> dict[str, object]:
    """Return Repeat Key status from an InteractionEngine-like object."""
    repeat_key = getattr(engine, "repeat_key", {})
    enabled = bool(repeat_key.get("enabled", True)) if isinstance(repeat_key, dict) else True
    alternate = repeat_key.get("alternate", {}) if isinstance(repeat_key, dict) else {}
    if not isinstance(alternate, Mapping):
        alternate = {}
    repeat_history = getattr(engine, "repeat_history", None)
    return repeat_key_status(
        enabled=enabled,
        repeat_history=str(repeat_history) if repeat_history else None,
        alternate=alternate,
    ).to_dict()


def repeat_key_default_alternate_pairs() -> tuple[tuple[str, str], ...]:
    """Return default alternate pairs as logical pairs, not a bidirectional map."""
    return _DEFAULT_REPEAT_ALTERNATE_PAIRS
