"""Wi-Fi status helpers for the HTTP UI.

This module is side-effect free: it only reads rfkill / nmcli state.  Runtime
power operations live in logicd.wifi_manager.
"""
from __future__ import annotations

import asyncio
import copy
import os
import re
import time
from typing import Any, Dict

_WIFI_STATUS_CACHE_TTL = 5.0
_wifi_status_cache: tuple[float, Dict[str, Any]] | None = None


async def wifi_status(*, max_age_sec: float = _WIFI_STATUS_CACHE_TTL) -> Dict[str, Any]:
    """Return a small Wi-Fi status snapshot for the HTTP UI."""

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
    status: Dict[str, Any] = {
        "available": rfkill_code == 0 or nmcli_code == 0,
        "interface": interface,
        "blocked": blocked,
        "powered": None if blocked is None else not blocked,
        "connected": connected,
        "ssid": ssid,
        "recovery_first": True,
        "persistent_power_off": False,
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
    return (soft and soft.group(1).lower() == "yes") or (hard and hard.group(1).lower() == "yes")


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
    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")
    except asyncio.TimeoutError:
        if proc is not None and proc.returncode is None:
            proc.kill()
            try:
                await asyncio.wait_for(proc.communicate(), timeout=1.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                pass
        return 124, "", "command timeout"
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    except OSError as exc:
        return 1, "", str(exc)
