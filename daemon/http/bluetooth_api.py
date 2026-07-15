"""Bluetooth control helpers for the HTTP UI."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
from collections.abc import Awaitable, Callable
from typing import Any

BT_PAIRING_ACTIONS = {
    "on": "BT_PAIRING_ON",
    "off": "BT_PAIRING_OFF",
    "toggle": "BT_PAIRING_TOGGLE",
}

BT_FORGET_SEQUENCE = (
    "BT_PAIRING_OFF",
    "BT_DISCONNECT",
    "BT_FORGET_DEVICE",
)
BLUETOOTH_HOST_METADATA_SCHEMA = 1
BLUETOOTH_HOST_RENAME_REFRESH = "bluetooth_status"
BLUETOOTH_HOST_FORGET_REFRESH = "bluetooth_status"
_BT_MAC_RE = re.compile(r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$", re.IGNORECASE)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


def normalize_pairing_mode(value: object) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    mode = str(value or "").strip().lower()
    if mode in BT_PAIRING_ACTIONS:
        return mode
    raise ValueError("pairing mode must be one of: on, off, toggle")


def normalize_bluetooth_address(value: object) -> str:
    address = str(value or "").strip().upper()
    if not _BT_MAC_RE.fullmatch(address):
        raise ValueError("Bluetooth address must be AA:BB:CC:DD:EE:FF")
    return address


def validate_bluetooth_display_name(value: object, *, clear: bool = False) -> str:
    name = str(value or "").strip()
    if clear:
        return ""
    if not name:
        raise ValueError("display_name must not be empty unless clear=true")
    if len(name) > 64:
        raise ValueError("display_name must be 64 characters or fewer")
    if _CONTROL_CHAR_RE.search(name):
        raise ValueError("display_name must not contain control characters")
    return name


def _validate_optional_metadata_text(value: object, field_name: str, *, max_len: int = 128) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > max_len:
        raise ValueError(f"{field_name} must be {max_len} characters or fewer")
    if _CONTROL_CHAR_RE.search(text):
        raise ValueError(f"{field_name} must not contain control characters")
    return text


def _load_host_metadata_document(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": BLUETOOTH_HOST_METADATA_SCHEMA, "hosts": {}}
    except (OSError, json.JSONDecodeError):
        return {"version": BLUETOOTH_HOST_METADATA_SCHEMA, "hosts": {}}
    if not isinstance(raw, dict):
        return {"version": BLUETOOTH_HOST_METADATA_SCHEMA, "hosts": {}}
    hosts = raw.get("hosts")
    if not isinstance(hosts, dict):
        hosts = {}
    return {
        **raw,
        "version": raw.get("version", BLUETOOTH_HOST_METADATA_SCHEMA),
        "hosts": {str(key).upper(): value for key, value in hosts.items() if isinstance(value, dict)},
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(data)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
    tmp.replace(path)


def rename_bluetooth_host_metadata(
    metadata_path: str | Path,
    address: object,
    display_name: object,
    *,
    clear: bool = False,
) -> dict[str, Any]:
    normalized = normalize_bluetooth_address(address)
    name = validate_bluetooth_display_name(display_name, clear=clear)
    path = Path(metadata_path)
    document = _load_host_metadata_document(path)
    hosts = document.setdefault("hosts", {})
    host = dict(hosts.get(normalized, {}))
    previous = host.get("display_name") if isinstance(host.get("display_name"), str) else None
    if name:
        host["display_name"] = name
    else:
        host.pop("display_name", None)
    hosts[normalized] = host
    document["version"] = BLUETOOTH_HOST_METADATA_SCHEMA
    _atomic_write_json(path, document)
    return {
        "result": "ok",
        "address": normalized,
        "display_name": host.get("display_name"),
        "previous_display_name": previous,
        "cleared": not bool(name),
        "source": "local_metadata",
        "refresh": BLUETOOTH_HOST_RENAME_REFRESH,
    }


def update_bluetooth_host_observation_metadata(
    metadata_path: str | Path,
    address: object,
    *,
    last_seen_name: object | None = None,
    last_connected_at: object | None = None,
    last_connected_source: object | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Write observational Bluetooth host metadata without touching local rename."""
    normalized = normalize_bluetooth_address(address)
    seen_name = _validate_optional_metadata_text(last_seen_name, "last_seen_name")
    connected_at = _validate_optional_metadata_text(last_connected_at, "last_connected_at", max_len=64)
    connected_source = _validate_optional_metadata_text(
        last_connected_source,
        "last_connected_source",
        max_len=64,
    )
    path = Path(metadata_path)
    document = _load_host_metadata_document(path)
    hosts = document.setdefault("hosts", {})
    host = dict(hosts.get(normalized, {}))
    previous = {
        "last_seen_name": host.get("last_seen_name"),
        "last_connected_at": host.get("last_connected_at"),
        "last_connected_source": host.get("last_connected_source"),
        "display_name": host.get("display_name"),
    }
    if seen_name is not None:
        host["last_seen_name"] = seen_name
    if connected_at is not None:
        host["last_connected_at"] = connected_at
    if connected_source is not None:
        host["last_connected_source"] = connected_source
    hosts[normalized] = host
    document["version"] = BLUETOOTH_HOST_METADATA_SCHEMA
    if not dry_run:
        _atomic_write_json(path, document)
    return {
        "result": "ok",
        "address": normalized,
        "dry_run": bool(dry_run),
        "source": "local_metadata_observation",
        "metadata": {
            "last_seen_name": host.get("last_seen_name"),
            "last_connected_at": host.get("last_connected_at"),
            "last_connected_source": host.get("last_connected_source"),
        },
        "previous": previous,
        "preserved_display_name": host.get("display_name"),
    }


def build_bluetooth_host_forget_guard(
    address: object,
    body: dict[str, Any] | None = None,
    *,
    device: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a per-host forget request and return a non-destructive command plan."""
    normalized = normalize_bluetooth_address(address)
    payload = body or {}
    confirmed = normalize_bluetooth_address(payload.get("confirm_address", ""))
    if confirmed != normalized:
        raise ValueError("confirm_address must match route address")
    dry_run = bool(payload.get("dry_run", True))
    if dry_run is not True:
        raise ValueError("per-host forget execution is disabled until real-device single-address removal is verified")
    snapshot = dict(device or {})
    connected = snapshot.get("connected") is True
    paired = snapshot.get("paired") is True or snapshot.get("bonded") is True
    return {
        "result": "dry_run",
        "address": normalized,
        "dry_run": True,
        "schema": "bluetooth.host_forget_guard.v1",
        "single_address_only": True,
        "connected_warning": connected,
        "paired": paired,
        "connected": connected,
        "command_plan": [{"t": "BT", "action": "BT_FORGET_HOST", "address": normalized}],
        "metadata_action": "preserve_on_dry_run",
        "refresh": BLUETOOTH_HOST_FORGET_REFRESH,
    }


async def run_pairing_action(
    send_ctrl_command: Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]],
    mode: object,
) -> dict[str, Any]:
    normalized = normalize_pairing_mode(mode)
    action = BT_PAIRING_ACTIONS[normalized]
    resp = await send_ctrl_command({"t": "BT", "action": action})
    if resp is None:
        return {"result": "error", "msg": "logicd unavailable"}
    if resp.get("result") != "ok":
        return {"result": "error", "msg": resp.get("msg", "Bluetooth action failed"), "logicd": resp}
    return {"result": "ok", "mode": normalized, "action": action}


async def run_forget_action(
    send_ctrl_command: Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]],
) -> dict[str, Any]:
    responses: list[dict[str, Any]] = []
    for action in BT_FORGET_SEQUENCE:
        resp = await send_ctrl_command({"t": "BT", "action": action})
        if resp is None:
            return {
                "result": "error",
                "msg": "logicd unavailable",
                "action": action,
                "responses": responses,
            }
        responses.append(resp)
        if resp.get("result") != "ok":
            return {
                "result": "error",
                "msg": resp.get("msg", "Bluetooth action failed"),
                "action": action,
                "logicd": resp,
                "responses": responses,
            }
    return {"result": "ok", "actions": list(BT_FORGET_SEQUENCE), "responses": responses}
