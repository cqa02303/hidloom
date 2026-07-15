"""Read-only host profile status helpers.

This module is intentionally read-only. It combines connected-host metadata
with persistent profile config into a safe status payload that UI/OLED code can
display; profile application belongs to the control layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class HostProfileStatus:
    """Derived read-only active host profile metadata."""

    active: bool
    host_address: str | None
    host_label: str | None
    profile: str | None
    profile_label: str | None
    layout: str | None
    enabled: bool
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "active": self.active,
            "host_address": self.host_address,
            "host_label": self.host_label,
            "profile": self.profile,
            "profile_label": self.profile_label,
            "layout": self.layout,
            "enabled": self.enabled,
            "reason": self.reason,
        }


def _host_address(host: Mapping[str, Any] | None) -> str | None:
    if not isinstance(host, Mapping):
        return None
    for key in ("address", "addr", "mac", "host_address"):
        value = host.get(key)
        if value:
            return str(value).upper()
    return None


def _host_label(host: Mapping[str, Any] | None) -> str | None:
    if not isinstance(host, Mapping):
        return None
    for key in ("alias", "name", "label"):
        value = host.get(key)
        if value:
            return str(value)
    return None


def active_host_profile_status(
    host: Mapping[str, Any] | None,
    profile_config: Mapping[str, Any] | None,
) -> HostProfileStatus:
    """Return read-only active profile metadata for a connected host."""
    address = _host_address(host)
    label = _host_label(host)
    if address is None:
        return HostProfileStatus(
            active=False,
            host_address=None,
            host_label=label,
            profile=None,
            profile_label=None,
            layout=None,
            enabled=False,
            reason="no_active_host",
        )

    config = profile_config if isinstance(profile_config, Mapping) else {}
    hosts = config.get("hosts", {}) if isinstance(config.get("hosts", {}), Mapping) else {}
    profiles = config.get("profiles", {}) if isinstance(config.get("profiles", {}), Mapping) else {}
    entry = hosts.get(address) or hosts.get(address.upper()) or hosts.get(address.lower())
    if not isinstance(entry, Mapping):
        return HostProfileStatus(
            active=False,
            host_address=address,
            host_label=label,
            profile=None,
            profile_label=None,
            layout=None,
            enabled=False,
            reason="profile_not_configured",
        )

    enabled = bool(entry.get("enabled", True))
    profile_name = str(entry.get("profile") or "") or None
    profile_info = profiles.get(profile_name, {}) if profile_name and isinstance(profiles.get(profile_name, {}), Mapping) else {}
    profile_label = str(profile_info.get("display_name") or profile_name or "") or None
    layout = str(entry.get("layout") or profile_info.get("layout") or "") or None
    if not enabled:
        return HostProfileStatus(
            active=False,
            host_address=address,
            host_label=str(entry.get("label") or label or "") or None,
            profile=profile_name,
            profile_label=profile_label,
            layout=layout,
            enabled=False,
            reason="profile_disabled",
        )

    return HostProfileStatus(
        active=True,
        host_address=address,
        host_label=str(entry.get("label") or label or "") or None,
        profile=profile_name,
        profile_label=profile_label,
        layout=layout,
        enabled=True,
        reason="matched",
    )


def merge_profile_status_into_host(
    host: Mapping[str, Any],
    profile_config: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return a host metadata copy with read-only profile fields attached."""
    result = dict(host)
    status = active_host_profile_status(host, profile_config).to_dict()
    result["profile_status"] = status
    result["profile_active"] = status["active"]
    result["profile"] = status["profile"]
    result["profile_label"] = status["profile_label"]
    result["profile_layout"] = status["layout"]
    return result


def host_profile_oled_label(status: Mapping[str, Any]) -> str:
    """Return short OLED label for an active host profile."""
    if not status.get("active"):
        return ""
    label = status.get("profile_label") or status.get("profile") or "Host"
    return f"Host {label}"
