"""Connectivity status helpers for the OLED icon row.

The helpers in this module are read-only.  Runtime power control stays in
logicd/wifi_manager.py; i2cd only needs a small status snapshot for display.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import time
from pathlib import Path
from typing import Any

_WIFI_STATUS_CACHE_TTL = 5.0
_wifi_status_cache: tuple[float, dict[str, Any]] | None = None

OUTPUT_MODE_ICONS: tuple[tuple[str, str], ...] = (
    ("auto", "Automatic"),
    ("usb", "USB HID"),
    ("bt", "Bluetooth HID"),
    ("pi", "Pi / uinput"),
    ("wifi0", "Wi-Fi idle"),
    ("wifi3", "Wi-Fi connected"),
)

OUTPUTD_STATUS_SCHEMA = "hidloom.outputd.status.v1"


def outputd_display_mode(status: dict[str, Any] | None) -> str:
    """Map the native output router status to the OLED mode label."""
    if not isinstance(status, dict):
        return ""
    if status.get("schema") != OUTPUTD_STATUS_SCHEMA or status.get("process") is not True:
        return ""
    target = str(status.get("target") or "").strip()
    return {
        "auto": "auto:gadget",
        "usb": "gadget",
        "gadget": "gadget",
        "uinput": "uinput",
        "console": "uinput",
        "bt": "bt",
        "bluetooth": "bt",
    }.get(target, "")


def effective_output_display_mode(
    notified_mode: str,
    outputd_status: dict[str, Any] | None,
) -> str:
    """Prefer canonical outputd state and retain logicd notifications as fallback."""
    return outputd_display_mode(outputd_status) or str(notified_mode or "").strip()


def load_outputd_status(path: str | Path, *, max_age_sec: float = 2.0) -> dict[str, Any]:
    """Load a recent native output router status snapshot."""
    status_path = Path(path)
    try:
        stat = status_path.stat()
        if max_age_sec > 0 and time.time() - stat.st_mtime > max_age_sec:
            return {}
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if outputd_display_mode(payload):
        return payload
    return {}


def output_mode_icon_row(
    current_mode: str,
    wifi: dict[str, Any] | None = None,
    daemon_status: dict[str, bool] | None = None,
) -> list[tuple[str, bool]]:
    """Return visible connectivity icons for the OLED status row.

    Each tuple is ``(icon_name, active)``.  The row intentionally omits
    off/unavailable icons.  Active/current items are rendered inverted by i2cd.
    """
    row: list[tuple[str, bool]] = []
    mode = str(current_mode or "").strip()
    mode_to_icon = {"gadget": "usb", "bt": "bt", "uinput": "pi"}
    usb_connected = _usb_connected(daemon_status or {})
    if mode.startswith("auto:"):
        _, actual = mode.split(":", 1)
        row.append(("auto", True))
        actual_icon = mode_to_icon.get(actual.strip())
        if actual_icon is None and usb_connected:
            actual_icon = "usb"
        if actual_icon:
            row.append((actual_icon, True))
    else:
        icon = mode_to_icon.get(mode)
        if icon is None and usb_connected:
            icon = "usb"
        if icon:
            row.append((icon, True))

    wifi_entry = wifi_icon_entry(wifi or {})
    if wifi_entry is not None:
        row.append(wifi_entry)
    return row


def _usb_connected(daemon_status: dict[str, bool]) -> bool:
    """Return True when USB HID transport appears available."""
    return bool(daemon_status.get("hidd", daemon_status.get("usbd", False)))


def wifi_icon_entry(wifi: dict[str, Any]) -> tuple[str, bool] | None:
    """Map a Wi-Fi status snapshot to an icon entry.

    Off / unavailable is hidden.  Powered but not connected is shown normally as
    ``wifi0``.  Connected is shown inverted as ``wifi3`` until RSSI/quality is
    available for finer level mapping.
    """
    if not wifi.get("available", False):
        return None
    if wifi.get("powered") is False or wifi.get("blocked") is True:
        return None
    if wifi.get("connected") is True:
        return ("wifi3", True)
    return ("wifi0", False)


async def wifi_status(*, max_age_sec: float = _WIFI_STATUS_CACHE_TTL) -> dict[str, Any]:
    """Return a small Wi-Fi status snapshot for i2cd."""
    global _wifi_status_cache
    now = time.monotonic()
    if max_age_sec > 0 and _wifi_status_cache is not None:
        cached_at, cached_status = _wifi_status_cache
        if now - cached_at < max_age_sec:
            return copy.deepcopy(cached_status)

    interface = os.environ.get("WIFI_INTERFACE", "wlan0")
    rfkill_code, rfkill_out, rfkill_err = await _run_text("rfkill", "list", "wifi")
    nmcli_code, nmcli_out, nmcli_err = await _run_text(
        "nmcli",
        "-t",
        "-f",
        "DEVICE,TYPE,STATE,CONNECTION",
        "device",
        "status",
    )
    blocked = _parse_rfkill_blocked(rfkill_out) if rfkill_code == 0 else None
    connected, ssid = _parse_nmcli_wifi_status(nmcli_out, interface) if nmcli_code == 0 else (None, "")
    status: dict[str, Any] = {
        "available": rfkill_code == 0 or nmcli_code == 0,
        "interface": interface,
        "blocked": blocked,
        "powered": None if blocked is None else not blocked,
        "connected": connected,
        "ssid": ssid,
    }
    errors = []
    if rfkill_code != 0:
        errors.append(rfkill_err.strip() or rfkill_out.strip() or "rfkill failed")
    if nmcli_code != 0:
        errors.append(nmcli_err.strip() or nmcli_out.strip() or "nmcli failed")
    if errors:
        status["errors"] = errors
    if max_age_sec > 0:
        _wifi_status_cache = (now, copy.deepcopy(status))
    return status


def _parse_rfkill_blocked(text: str) -> bool | None:
    soft = re.search(r"Soft blocked:\s*(yes|no)", text, re.IGNORECASE)
    hard = re.search(r"Hard blocked:\s*(yes|no)", text, re.IGNORECASE)
    if soft is None and hard is None:
        return None
    return bool((soft and soft.group(1).lower() == "yes") or (hard and hard.group(1).lower() == "yes"))


def _parse_nmcli_wifi_status(text: str, interface: str) -> tuple[bool | None, str]:
    for raw in text.splitlines():
        parts = raw.split(":", 3)
        if len(parts) != 4:
            continue
        device, typ, state, connection = parts
        if device != interface or typ != "wifi":
            continue
        return state == "connected", connection if state == "connected" else ""
    return None, ""


async def _run_text(*cmd: str, timeout: float = 3.0) -> tuple[int, str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")
    except asyncio.TimeoutError:
        return 124, "", "command timeout"
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    except OSError as exc:
        return 1, "", str(exc)
