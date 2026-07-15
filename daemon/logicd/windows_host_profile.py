"""Read-only host profile helpers for Windows US custom HID IME routing."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

WINDOWS_US_CUSTOM_HID_IME_PROFILE: Final[str] = "windows_us_custom_hid_ime"


@dataclass(frozen=True)
class WindowsImeHostProfile:
    name: str
    custom_hid_ime_enabled: bool = False
    receiver_required: bool = True
    receiver_available: bool = False

    @property
    def is_windows_us_custom_hid_ime(self) -> bool:
        return self.name == WINDOWS_US_CUSTOM_HID_IME_PROFILE


def normalize_windows_ime_host_profile(data: Any) -> WindowsImeHostProfile:
    """Normalize a host profile entry without mutating config.

    The default is deliberately safe: even when the profile name matches,
    custom HID IME routing remains disabled unless explicitly enabled and a
    receiver is marked available by explicit companion status data.
    """

    if not isinstance(data, dict):
        return WindowsImeHostProfile(name="")

    name = str(data.get("name") or data.get("profile") or "").strip().lower()
    custom = data.get("custom_hid_ime") if isinstance(data.get("custom_hid_ime"), dict) else {}
    enabled = bool(custom.get("enabled", False))
    receiver_required = bool(custom.get("receiver_required", True))
    receiver_available = bool(custom.get("receiver_available", False))

    if name != WINDOWS_US_CUSTOM_HID_IME_PROFILE:
        enabled = False
        receiver_available = False

    return WindowsImeHostProfile(
        name=name,
        custom_hid_ime_enabled=enabled,
        receiver_required=receiver_required,
        receiver_available=receiver_available,
    )


def profile_to_custom_hid_route_kwargs(profile: WindowsImeHostProfile) -> dict[str, object]:
    """Return kwargs for build_windows_ime_custom_hid_plan()."""

    return {
        "host_profile": profile.name,
        "enabled": profile.custom_hid_ime_enabled,
        "receiver_available": (not profile.receiver_required) or profile.receiver_available,
    }
