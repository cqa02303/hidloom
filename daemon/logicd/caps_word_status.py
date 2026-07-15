"""Read-only status helper for Caps Word.

Caps Word is intentionally separate from host Caps Lock.  This helper exposes a
small runtime-only status payload that UI/OLED/LED code can consume without
implying that OS Caps Lock or host lock LEDs changed.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CapsWordStatus:
    """Runtime-only Caps Word status."""

    enabled: bool
    active: bool
    label: str = "Caps Word"
    lock_type: str = "caps_word"
    host_caps_lock: bool | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "active": self.active,
            "label": self.label,
            "lock_type": self.lock_type,
            "host_caps_lock": self.host_caps_lock,
        }


def caps_word_status(*, enabled: bool, active: bool, host_caps_lock: bool | None = None) -> CapsWordStatus:
    """Build a Caps Word status object distinct from host Caps Lock."""
    return CapsWordStatus(
        enabled=bool(enabled),
        active=bool(enabled and active),
        host_caps_lock=host_caps_lock,
    )


def caps_word_status_from_engine(engine: object, *, host_caps_lock: bool | None = None) -> dict[str, object]:
    """Return Caps Word status from an InteractionEngine-like object."""
    caps_word = getattr(engine, "caps_word", {})
    enabled = bool(caps_word.get("enabled", True)) if isinstance(caps_word, dict) else True
    active = bool(getattr(engine, "caps_word_active", False))
    return caps_word_status(
        enabled=enabled,
        active=active,
        host_caps_lock=host_caps_lock,
    ).to_dict()


def caps_word_oled_label(status: dict[str, object]) -> str:
    """Return a short OLED label that cannot be mistaken for Caps Lock."""
    if not status.get("enabled", True):
        return "CW off"
    if status.get("active"):
        return "CW on"
    return "CW"


def caps_word_led_overlay_name() -> str:
    """Return the LED overlay name reserved for Caps Word.

    This must stay separate from host-synced Caps Lock overlay names.
    """
    return "caps_word"
