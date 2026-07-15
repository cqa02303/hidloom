"""Recovery-first Wi-Fi power control helper.

The default policy is intentionally non-persistent: WIFI_POWER_OFF uses runtime
rfkill only, so rebooting the Raspberry Pi restores the boot-time radio policy.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class WifiStatus:
    blocked: bool | None = None
    connected: bool | None = None
    ssid: str = ""

    def summary(self) -> str:
        if self.blocked is True:
            state = "off"
        elif self.connected is True:
            state = "connected"
        elif self.blocked is False:
            state = "on"
        else:
            state = "unknown"
        ssid = f" ssid={self.ssid}" if self.ssid else ""
        return f"Wi-Fi {state}{ssid}"


class WifiManager:
    """Small recovery-first Wi-Fi control facade used from key actions."""

    ACTIONS = {
        "WIFI_STATUS",
        "WIFI_POWER_ON",
        "WIFI_POWER_OFF",
        "WIFI_POWER_TOGGLE",
    }

    def __init__(self, command_timeout: float = 5.0) -> None:
        self.command_timeout = command_timeout
        self.interface = os.environ.get("WIFI_INTERFACE", "wlan0")
        self.use_nmcli_status = _env_bool("WIFI_STATUS_USE_NMCLI", default=True)

    def handles(self, action: str) -> bool:
        return action in self.ACTIONS

    async def handle_action(self, action: str, is_press: bool) -> bool:
        if not self.handles(action):
            return False
        if not is_press:
            return True
        try:
            if action == "WIFI_STATUS":
                await self.log_status()
            elif action == "WIFI_POWER_ON":
                await self.power(True)
            elif action == "WIFI_POWER_OFF":
                await self.power(False)
            elif action == "WIFI_POWER_TOGGLE":
                await self.toggle_power()
        except Exception as exc:
            log.warning("Wi-Fi action failed: %s: %s", action, exc)
        return True

    async def power(self, enabled: bool) -> None:
        # Recovery-first: do not persist this to boot config or systemd enablement.
        if self._command_available("rfkill"):
            await self._run_text("rfkill", "unblock" if enabled else "block", "wifi", check=False)
        else:
            await self._run_text("nmcli", "radio", "wifi", "on" if enabled else "off", check=False)
        log.info("Wi-Fi runtime power %s", "on" if enabled else "off until reboot")

    async def toggle_power(self) -> None:
        status = await self.get_status()
        await self.power(bool(status.blocked))

    async def log_status(self) -> WifiStatus:
        status = await self.get_status()
        log.info(status.summary())
        return status

    async def get_status(self) -> WifiStatus:
        blocked = None
        if self._command_available("rfkill"):
            rfkill = await self._run_text("rfkill", "list", "wifi", check=False)
            blocked = _parse_rfkill_blocked(rfkill)
        connected = None
        ssid = ""
        if self.use_nmcli_status:
            nmcli = await self._run_text("nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status", check=False)
            connected, ssid = _parse_nmcli_wifi_status(nmcli, self.interface)
        return WifiStatus(blocked=blocked, connected=connected, ssid=ssid)

    def _command_available(self, name: str) -> bool:
        return shutil.which(name) is not None

    async def _run_text(self, *cmd: str, check: bool = True) -> str:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.command_timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError("command timed out: " + " ".join(cmd))
        out = stdout.decode(errors="replace")
        err = stderr.decode(errors="replace")
        if check and proc.returncode != 0:
            raise RuntimeError(f"{' '.join(cmd)} failed ({proc.returncode}): {err.strip() or out.strip()}")
        if err.strip():
            log.debug("%s stderr: %s", " ".join(cmd), err.strip())
        return out


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


def _env_bool(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
