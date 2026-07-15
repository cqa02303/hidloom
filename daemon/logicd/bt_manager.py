"""Bluetooth state/control helper for Raspberry Pi / BlueZ.

This module intentionally keeps the first Bluetooth control layer small and
observable.  It uses command line tools that are already common on Raspberry Pi
OS (bluetoothctl, systemctl, rfkill) instead of binding the rest of logicd to a
specific BlueZ D-Bus object model.

The key input layer should call only BtManager.handle_action().  The BLE HID
backend can evolve without changing keymap processing.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BtStatus:
    powered: bool | None = None
    discoverable: bool | None = None
    pairable: bool | None = None
    controller: str = ""
    paired_devices: tuple[str, ...] = field(default_factory=tuple)
    connected_devices: tuple[str, ...] = field(default_factory=tuple)
    bluetooth_service_active: bool | None = None

    def summary(self) -> str:
        def yn(value: bool | None) -> str:
            if value is True:
                return "on"
            if value is False:
                return "off"
            return "unknown"

        connected = ",".join(self.connected_devices) if self.connected_devices else "none"
        paired = len(self.paired_devices)
        return (
            f"BT powered={yn(self.powered)} discoverable={yn(self.discoverable)} "
            f"pairable={yn(self.pairable)} service={yn(self.bluetooth_service_active)} "
            f"paired={paired} connected={connected}"
        )


class BtManager:
    """Small Bluetooth control facade used from keyboard actions."""

    ACTIONS = {
        "BT_STATUS",
        "BT_POWER_ON",
        "BT_POWER_OFF",
        "BT_POWER_TOGGLE",
        "BT_PAIRING_ON",
        "BT_PAIRING_OFF",
        "BT_PAIRING_TOGGLE",
        "BT_DISCONNECT",
        "BT_FORGET_DEVICE",
    }

    def __init__(self, command_timeout: float = 5.0) -> None:
        self.command_timeout = command_timeout
        self.agent_capability = os.environ.get("BTD_PAIRING_AGENT", "DisplayYesNo")
        self.passkey_file = os.environ.get("BTD_PAIRING_PASSKEY_FILE", "/tmp/btd_pairing_passkey.txt")
        self.enable_discoverable_during_pairing = _env_bool("BT_PAIRING_DISCOVERABLE", default=False)
        self.managed_power_services = _env_list("BT_POWER_MANAGED_SERVICES", default=("btd",))
        self.stop_managed_services_on_power_off = _env_bool("BT_POWER_STOP_MANAGED_SERVICES", default=True)
        self.start_managed_services_on_power_on = _env_bool("BT_POWER_START_MANAGED_SERVICES", default=True)
        self.btd_sender = None
        self._agent_proc = None
        self._agent_log_task: asyncio.Task[None] | None = None

    def handles(self, action: str) -> bool:
        return action in self.ACTIONS

    async def handle_action(self, action: str, is_press: bool) -> bool:
        """Handle a key action. Returns True when the action was consumed."""
        if not self.handles(action):
            return False
        if not is_press:
            return True

        try:
            if action == "BT_STATUS":
                await self.log_status()
            elif action == "BT_POWER_ON":
                await self.power(True)
            elif action == "BT_POWER_OFF":
                await self.power(False)
            elif action == "BT_POWER_TOGGLE":
                await self.toggle_power()
            elif action == "BT_PAIRING_ON":
                await self.pairing(True)
            elif action == "BT_PAIRING_OFF":
                await self.pairing(False)
            elif action == "BT_PAIRING_TOGGLE":
                await self.toggle_pairing()
            elif action == "BT_DISCONNECT":
                await self.disconnect_connected_devices()
            elif action == "BT_FORGET_DEVICE":
                await self.forget_paired_devices()
        except Exception as exc:
            log.warning("Bluetooth action failed: %s: %s", action, exc)
        return True

    async def get_status(self) -> BtStatus:
        show = await self._run_text("bluetoothctl", "show", check=False)
        paired = await self._run_text("bluetoothctl", "paired-devices", check=False)
        devices = await self._run_text("bluetoothctl", "devices", "Connected", check=False)
        known = await self._run_text("bluetoothctl", "devices", check=False)
        service_active = await self._service_active("bluetooth")
        paired_macs = list(self._parse_device_macs(paired))
        connected_macs = list(self._parse_device_macs(devices))
        known_macs = _dedupe_macs(self._parse_device_macs(known), paired_macs, connected_macs)

        if known_macs:
            details = await asyncio.gather(
                *(self._bluetooth_info(mac) for mac in known_macs),
                return_exceptions=True,
            )
            detailed_paired = [
                mac
                for mac, detail in zip(known_macs, details)
                if isinstance(detail, str)
                and (
                    self._parse_bool(detail, "Paired") is True
                    or self._parse_bool(detail, "Bonded") is True
                )
            ]
            detailed_connected = [
                mac
                for mac, detail in zip(known_macs, details)
                if isinstance(detail, str) and self._parse_bool(detail, "Connected") is True
            ]
            paired_macs = _dedupe_macs(detailed_paired, paired_macs)
            connected_macs = _dedupe_macs(detailed_connected, connected_macs)

        return BtStatus(
            powered=self._parse_bool(show, "Powered"),
            discoverable=self._parse_bool(show, "Discoverable"),
            pairable=self._parse_bool(show, "Pairable"),
            controller=self._parse_controller(show),
            paired_devices=tuple(paired_macs),
            connected_devices=tuple(connected_macs),
            bluetooth_service_active=service_active,
        )

    async def log_status(self) -> BtStatus:
        status = await self.get_status()
        log.info(status.summary())
        return status

    async def power(self, enabled: bool) -> None:
        if enabled:
            await self._run_text("rfkill", "unblock", "bluetooth", check=False)
            await self._run_text("systemctl", "start", "bluetooth", check=False)
            try:
                await self._bluetoothctl("power", "on")
            except RuntimeError:
                await asyncio.sleep(1.0)
                status = await self.get_status()
                if status.powered is not True:
                    raise
            if self.start_managed_services_on_power_on:
                await self._set_managed_power_services(True)
            log.info("Bluetooth power on")
            return

        await self._prepare_for_power_off()
        if self.stop_managed_services_on_power_off:
            await self._set_managed_power_services(False)
        try:
            await self._bluetoothctl("power", "off")
        except RuntimeError:
            await asyncio.sleep(1.0)
            status = await self.get_status()
            if status.powered is not False:
                raise
        log.info("Bluetooth power off")

    async def _prepare_for_power_off(self) -> None:
        """Stop pairing/discoverable state before radio and btd are stopped."""
        await self._stop_agent_process()
        await self._bluetoothctl("pairable", "off", check=False)
        await self._bluetoothctl("discoverable", "off", check=False)
        self._sync_btd_pairing_advertising()

    async def _set_managed_power_services(self, enabled: bool) -> None:
        if not self.managed_power_services:
            return
        action = "start" if enabled else "stop"
        for service in self.managed_power_services:
            if not service:
                continue
            await self._run_text("systemctl", action, service, check=False)
            log.info("Bluetooth managed service %s: %s", action, service)

    async def ensure_powered_for_output(self) -> None:
        """Power Bluetooth on before switching output to the BT backend."""
        status = await self.get_status()
        if status.powered is True:
            if self.start_managed_services_on_power_on:
                await self._set_managed_power_services(True)
            return
        log.info("Bluetooth power is not on; enabling before BT output")
        await self.power(True)

    async def toggle_power(self) -> None:
        status = await self.get_status()
        await self.power(not bool(status.powered))

    async def pairing(self, enabled: bool) -> None:
        value = "on" if enabled else "off"
        if enabled:
            await self._start_agent_process()
        await self._bluetoothctl("pairable", value)
        discoverable = "on" if enabled and await self._should_enable_discoverable_for_pairing() else "off"
        await self._bluetoothctl("discoverable", discoverable)
        if not enabled:
            await self._stop_agent_process()
        self._sync_btd_pairing_advertising()
        log.info("Bluetooth pairing mode %s discoverable=%s", value, discoverable)

    async def toggle_pairing(self) -> None:
        status = await self.get_status()
        next_state = not bool(status.pairable or status.discoverable)
        await self.pairing(next_state)

    async def disconnect_connected_devices(self) -> None:
        status = await self.get_status()
        for mac in status.connected_devices:
            await self._bluetoothctl("disconnect", mac, check=False)
        log.info("Bluetooth disconnected devices: %s", ", ".join(status.connected_devices) or "none")

    async def forget_paired_devices(self) -> None:
        status = await self.get_status()
        for mac in status.paired_devices:
            await self._bluetoothctl("remove", mac, check=False)
        log.info("Bluetooth removed paired devices: %s", ", ".join(status.paired_devices) or "none")

    async def _should_enable_discoverable_for_pairing(self) -> bool:
        if self.enable_discoverable_during_pairing:
            return True
        return False

    def _sync_btd_pairing_advertising(self) -> None:
        sync = getattr(self.btd_sender, "sync_pairing_advertising", None)
        if callable(sync):
            sync()

    async def _bluetoothctl(self, *args: str, check: bool = True) -> str:
        return await self._run_text("bluetoothctl", *args, check=check)

    async def _bluetooth_info(self, mac: str) -> str:
        return await self._bluetoothctl("info", mac, check=False)

    async def _service_active(self, name: str) -> bool | None:
        try:
            out = await self._run_text("systemctl", "is-active", name, check=False)
        except Exception:
            return None
        text = out.strip()
        if text == "active":
            return True
        if text in {"inactive", "failed", "deactivating", "activating"}:
            return False
        return None

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

    async def _start_agent_process(self) -> None:
        if self._agent_proc is not None and self._agent_proc.returncode is None:
            return
        self._agent_proc = await asyncio.create_subprocess_exec(
            "bluetoothctl",
            "--agent",
            self.agent_capability,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        if self._agent_proc.stdout is not None:
            self._agent_log_task = asyncio.create_task(
                self._log_agent_output(self._agent_proc.stdout, self._agent_proc.stdin)
            )
        await asyncio.sleep(0.3)
        if self._agent_proc.returncode is not None:
            raise RuntimeError(f"bluetoothctl --agent {self.agent_capability} exited early")
        if self._agent_proc.stdin is not None:
            self._agent_proc.stdin.write(b"default-agent\n")
            await self._agent_proc.stdin.drain()
        log.info("Bluetooth pairing agent started capability=%s", self.agent_capability)

    async def _stop_agent_process(self) -> None:
        proc = self._agent_proc
        log_task = self._agent_log_task
        self._agent_proc = None
        self._agent_log_task = None
        if proc is None or proc.returncode is not None:
            if log_task is not None:
                log_task.cancel()
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        if log_task is not None:
            log_task.cancel()
            try:
                await log_task
            except asyncio.CancelledError:
                pass
        log.info("Bluetooth pairing agent stopped")

    async def _log_agent_output(self, stream: asyncio.StreamReader, stdin) -> None:
        while True:
            line = await stream.readline()
            if not line:
                return
            text = line.decode(errors="replace").strip()
            if not text:
                continue
            log.info("Bluetooth pairing agent: %s", text)
            if _is_yes_no_agent_prompt(text) and stdin is not None:
                stdin.write(b"yes\n")
                await stdin.drain()
                log.info("Bluetooth pairing agent confirmation accepted")
            elif ("Enter passkey" in text or "Request passkey" in text) and stdin is not None:
                passkey = await _wait_for_passkey_file(self.passkey_file, timeout=25.0)
                if passkey:
                    stdin.write((passkey + "\n").encode())
                    await stdin.drain()
                    log.info("Bluetooth pairing agent passkey submitted from %s", self.passkey_file)

    @staticmethod
    def _parse_bool(text: str, field_name: str) -> bool | None:
        m = re.search(rf"^\s*{re.escape(field_name)}:\s*(yes|no)\s*$", text, re.MULTILINE | re.IGNORECASE)
        if not m:
            return None
        return m.group(1).lower() == "yes"

    @staticmethod
    def _parse_controller(text: str) -> str:
        m = re.search(r"^Controller\s+([0-9A-F:]{17})\b", text, re.MULTILINE | re.IGNORECASE)
        return m.group(1).upper() if m else ""

    @staticmethod
    def _parse_device_macs(text: str) -> Iterable[str]:
        for m in re.finditer(r"^Device\s+([0-9A-F:]{17})\b", text, re.MULTILINE | re.IGNORECASE):
            yield m.group(1).upper()


def _dedupe_macs(*mac_lists: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for macs in mac_lists:
        for mac in macs:
            normalized = mac.upper()
            if normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
    return result


def _is_yes_no_agent_prompt(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "Confirm passkey",
            "Request confirmation",
            "Authorize service",
            "Accept pairing",
        )
    )


async def _wait_for_passkey_file(path: str, *, timeout: float) -> str | None:
    deadline = asyncio.get_running_loop().time() + timeout
    passkey_path = Path(path)
    while asyncio.get_running_loop().time() < deadline:
        try:
            text = passkey_path.read_text().strip()
        except FileNotFoundError:
            text = ""
        if text:
            try:
                passkey_path.unlink()
            except FileNotFoundError:
                pass
            if text.isdigit():
                return text
            log.warning("Ignoring non-numeric Bluetooth pairing passkey file %s", path)
            return None
        await asyncio.sleep(0.2)
    log.warning("Bluetooth pairing agent timed out waiting for passkey file: %s", path)
    return None


def _env_bool(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, *, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if raw is None:
        return default
    parts = [part.strip() for part in re.split(r"[,\s]+", raw) if part.strip()]
    return tuple(parts)
