"""Read-only metadata helpers for power management presets.

This module never executes power actions. It classifies preset definitions by
recovery risk and exposes confirmation/recovery guidance for HTTP/OLED UI.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


_DEFAULT_PRESETS: dict[str, dict[str, object]] = {
    "low": {
        "oled": "dim",
        "led": "off",
        "bt": "unchanged",
        "wifi": "unchanged",
        "persist": False,
        "requires_confirmation": False,
    },
    "display_off": {
        "oled": "off",
        "led": "off",
        "bt": "unchanged",
        "wifi": "unchanged",
        "persist": False,
        "requires_confirmation": False,
    },
    "radios_off": {
        "oled": "status",
        "led": "off",
        "bt": "off",
        "wifi": "runtime_off",
        "persist": False,
        "requires_confirmation": True,
    },
}

_RECOVERY_ROUTES = (
    "USB keyboard / gadget path",
    "local physical key",
    "power cycle / reboot",
)


@dataclass(frozen=True)
class PowerPresetStatus:
    """Read-only classification for a power preset."""

    name: str
    defined: bool
    risk: str
    requires_confirmation: bool
    persistent: bool
    touches_radios: bool
    wifi: str
    bt: str
    oled: str
    led: str
    recovery_routes: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "defined": self.defined,
            "risk": self.risk,
            "requires_confirmation": self.requires_confirmation,
            "persistent": self.persistent,
            "touches_radios": self.touches_radios,
            "wifi": self.wifi,
            "bt": self.bt,
            "oled": self.oled,
            "led": self.led,
            "recovery_routes": list(self.recovery_routes),
            "warnings": list(self.warnings),
        }


def default_power_presets() -> dict[str, dict[str, object]]:
    """Return default power preset definitions."""
    return {name: dict(value) for name, value in _DEFAULT_PRESETS.items()}


def _preset_map(config: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    if not isinstance(config, Mapping):
        return default_power_presets()
    raw = config.get("power_presets", config)
    if not isinstance(raw, Mapping):
        return default_power_presets()
    merged: dict[str, Mapping[str, Any]] = default_power_presets()
    for name, value in raw.items():
        if isinstance(value, Mapping):
            merged[str(name)] = value
    return merged


def power_preset_status(name: str, config: Mapping[str, Any] | None = None) -> PowerPresetStatus:
    """Return read-only safety metadata for one preset."""
    presets = _preset_map(config)
    preset = presets.get(name)
    if not isinstance(preset, Mapping):
        return PowerPresetStatus(
            name=name,
            defined=False,
            risk="unknown",
            requires_confirmation=True,
            persistent=False,
            touches_radios=False,
            wifi="unknown",
            bt="unknown",
            oled="unknown",
            led="unknown",
            recovery_routes=_RECOVERY_ROUTES,
            warnings=("preset is not defined",),
        )

    wifi = str(preset.get("wifi", "unchanged"))
    bt = str(preset.get("bt", "unchanged"))
    oled = str(preset.get("oled", "unchanged"))
    led = str(preset.get("led", "unchanged"))
    persistent = bool(preset.get("persist", False))
    touches_radios = wifi not in {"unchanged", "on"} or bt not in {"unchanged", "on"}
    requires_confirmation = bool(preset.get("requires_confirmation", False) or touches_radios or persistent)
    warnings: list[str] = []
    if persistent:
        warnings.append("persistent power preset state is not allowed in the initial implementation")
    if wifi not in {"unchanged", "on", "runtime_off"}:
        warnings.append(f"unsupported wifi action: {wifi}")
    if bt not in {"unchanged", "on", "off"}:
        warnings.append(f"unsupported bt action: {bt}")
    if touches_radios:
        warnings.append("radio changes can disconnect HTTP/SSH or Bluetooth input")
    if wifi == "runtime_off":
        warnings.append("Wi-Fi runtime off must use recovery-first behavior and return on reboot")
    if bt == "off":
        warnings.append("Bluetooth off requires paired-host reconnect testing before default use")

    if persistent:
        risk = "blocked"
    elif touches_radios:
        risk = "high"
    elif oled == "off" and led == "off":
        risk = "medium"
    else:
        risk = "low"

    return PowerPresetStatus(
        name=name,
        defined=True,
        risk=risk,
        requires_confirmation=requires_confirmation,
        persistent=persistent,
        touches_radios=touches_radios,
        wifi=wifi,
        bt=bt,
        oled=oled,
        led=led,
        recovery_routes=_RECOVERY_ROUTES,
        warnings=tuple(warnings),
    )


def power_preset_status_payload(config: Mapping[str, Any] | None = None) -> dict[str, object]:
    """Return read-only status for all known presets."""
    presets = _preset_map(config)
    names = sorted(presets)
    statuses = {name: power_preset_status(name, presets).to_dict() for name in names}
    return {
        "schema": "power_preset.status.v1",
        "read_only": True,
        "current_preset": None,
        "restore_available": False,
        "active_state_persistent": False,
        "presets": statuses,
        "recovery_routes": list(_RECOVERY_ROUTES),
        "default_safe_preset": "low",
    }


def power_preset_oled_label(name: str) -> str:
    """Return the short OLED label for preset status/alert."""
    return {
        "low": "Power Low",
        "display_off": "Display Off",
        "radios_off": "Radios Off",
        "restore": "Power Restore",
    }.get(name, "Power Preset")
