"""BlueZ backend for btd.

This module owns the BLE HID-over-GATT backend boundary. It can use dry-run
adapters in tests, or BlueZ D-Bus adapters on Raspberry Pi.

Design notes:
- btd owns Bluetooth/BlueZ state; logicd only sends canonical keyboard reports.
- The public backend I/F is start/stop/send_keyboard_report.
- BLE HID over GATT is the implemented transport.
- The transport does not change the raw 8-byte keyboard report socket protocol.
- enabled=False is the safe default and reports are dropped instead of raising.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Awaitable, Callable

from .advertising import (
    AdvertisingAdapter,
    AdvertisementModel,
    DryRunAdvertisingAdapter,
    build_advertising_adapter,
    build_keyboard_advertisement,
)
from .gatt_adapter import DryRunGattRegistrationAdapter, GattRegistrationAdapter, build_gatt_adapter
from .gatt_app import GattApplicationModel, build_hid_gatt_application
from .pairing import DryRunPairingModeAdapter, PairingModeAdapter, build_pairing_mode_adapter
from .protocol import ConsumerReport, KeyboardReport, MouseReport, null_consumer_report, null_keyboard_report, null_mouse_report

log = logging.getLogger("btd.bluez")
ConnectedDevicesProbe = Callable[[], Awaitable[list[str]]]
DeviceNameProbe = Callable[[str], Awaitable[str | None]]
ObservationMetadataWriter = Callable[[str, str | None, str], Awaitable[None]]


class BlueZHidTransport(str, Enum):
    """Implemented BlueZ HID transport."""

    BLE = "ble"


DEFAULT_BLUEZ_HID_TRANSPORT = BlueZHidTransport.BLE


class BlueZAdvertisingMode(str, Enum):
    """When the BLE HID advertisement should be visible to hosts."""

    ALWAYS = "always"
    PAIRING = "pairing"
    OFF = "off"


DEFAULT_BLUEZ_ADVERTISING_MODE = BlueZAdvertisingMode.PAIRING


@dataclass(frozen=True)
class BlueZBackendStatus:
    """Observable BlueZ backend state used by logs and status APIs."""

    enabled: bool
    transport: BlueZHidTransport
    service_registered: bool = False
    host_connected: bool = False
    notifications: int = 0
    last_report_hex: str = ""
    gatt_adapter_kind: str = ""
    gatt_adapter_available: bool = True
    gatt_adapter_error: str = ""
    advertising_registered: bool = False
    advertising_adapter_kind: str = ""
    advertising_error: str = ""
    advertising_mode: BlueZAdvertisingMode = DEFAULT_BLUEZ_ADVERTISING_MODE
    pairing_mode_enabled: bool = False
    pairing_adapter_kind: str = ""
    pairing_agent_capability: str = ""
    pairing_error: str = ""
    stuck_reconnect_recoveries: int = 0


@dataclass
class BlueZBackend:
    """BlueZ HID backend with dry-run and BlueZ D-Bus adapters.

    Responsibilities:

    - register Bluetooth HID service
    - track connected host state
    - send keyboard HID reports
    - send null report on disconnect/restart when possible

    - enabled=False: safely drop reports
    - enabled=True with the default DryRun adapter: exercise lifecycle and report
      validation without touching BlueZ/D-Bus
    - enabled=True with the BlueZ D-Bus adapter: register and notify through BlueZ
    """

    send_null_on_stop: bool = True
    enabled: bool = False
    transport: BlueZHidTransport = DEFAULT_BLUEZ_HID_TRANSPORT
    service_registered: bool = False
    host_connected: bool = False
    application: GattApplicationModel = field(default_factory=build_hid_gatt_application)
    adapter: GattRegistrationAdapter = field(default_factory=DryRunGattRegistrationAdapter)
    advertisement: AdvertisementModel = field(default_factory=build_keyboard_advertisement)
    advertising_adapter: AdvertisingAdapter = field(default_factory=DryRunAdvertisingAdapter)
    pairing_mode_adapter: PairingModeAdapter = field(default_factory=DryRunPairingModeAdapter)
    pairing_mode: bool = False
    advertising_mode: BlueZAdvertisingMode = DEFAULT_BLUEZ_ADVERTISING_MODE
    advertising_monitor_interval_sec: float = 1.0
    advertising_idle_monitor_interval_sec: float = 60.0
    disconnect_monitor_interval_sec: float = 0.0
    disconnect_idle_monitor_interval_sec: float = 60.0
    stuck_reconnect_polls: int = 0
    stuck_reconnect_cooldown_sec: float = 30.0
    reconnect_notify_grace_sec: float = 2.0
    host_metadata_path: str = "/mnt/p3/bluetooth_hosts.json"
    output_on_connect: str = ""
    output_on_disconnect: str = ""
    logicd_ctrl_socket_path: str = "/tmp/ctrl_events.sock"
    mouse_coalesce_interval_sec: float = 0.0
    mouse_small_coalesce_interval_sec: float = 0.0
    mouse_small_coalesce_threshold: int = 0
    mouse_fast_hold_sec: float = 0.0
    keyboard_repeat_enabled: bool = False
    keyboard_repeat_delay_sec: float = 0.45
    keyboard_repeat_interval_sec: float = 0.035
    keyboard_repeat_tap_gap_sec: float = 0.006
    connected_devices_probe: ConnectedDevicesProbe | None = None
    device_name_probe: DeviceNameProbe | None = None
    observation_metadata_writer: ObservationMetadataWriter | None = None
    last_error: str = ""
    advertising_error: str = ""
    pairing_error: str = ""
    _disconnect_monitor_task: asyncio.Task[None] | None = None
    _advertising_monitor_task: asyncio.Task[None] | None = None
    _monitor_saw_connected_devices: bool = False
    _stuck_reconnect_polls_seen: int = 0
    _last_stuck_reconnect_recovery_monotonic: float = 0.0
    _stuck_reconnect_recoveries: int = 0
    _reconnect_advertising: bool = False
    _reconnect_connect_task: asyncio.Task[None] | None = None
    _mouse_flush_task: asyncio.Task[None] | None = None
    _mouse_pending_buttons: int = 0
    _mouse_pending_dx: int = 0
    _mouse_pending_dy: int = 0
    _mouse_pending_wheel: int = 0
    _mouse_flush_deadline_monotonic: float = 0.0
    _mouse_fast_until_monotonic: float = 0.0
    _keyboard_repeat_task: asyncio.Task[None] | None = None
    _keyboard_repeat_report: bytes = b""
    _last_observed_notify_ready_host: str = ""

    @classmethod
    def with_adapter_kind(
        cls,
        *,
        adapter_kind: str | None = None,
        advertising_adapter_kind: str | None = None,
        pairing_adapter_kind: str | None = None,
        pairing_agent_capability: str | None = None,
        gatt_security: str | None = None,
        pairing_mode: bool = False,
        advertising_mode: BlueZAdvertisingMode | str | None = DEFAULT_BLUEZ_ADVERTISING_MODE,
        advertising_monitor_interval_sec: float = 1.0,
        advertising_idle_monitor_interval_sec: float = 60.0,
        enabled: bool = False,
        send_null_on_stop: bool = True,
        disconnect_monitor_interval_sec: float = 0.0,
        disconnect_idle_monitor_interval_sec: float = 60.0,
        stuck_reconnect_polls: int = 0,
        stuck_reconnect_cooldown_sec: float = 30.0,
        reconnect_notify_grace_sec: float = 2.0,
        host_metadata_path: str | None = None,
        output_on_connect: str | None = None,
        output_on_disconnect: str | None = None,
        logicd_ctrl_socket_path: str | None = None,
        mouse_coalesce_interval_sec: float = 0.0,
        mouse_small_coalesce_interval_sec: float = 0.0,
        mouse_small_coalesce_threshold: int = 0,
        mouse_fast_hold_sec: float = 0.0,
        keyboard_repeat_enabled: bool = False,
        keyboard_repeat_delay_sec: float = 0.45,
        keyboard_repeat_interval_sec: float = 0.035,
        keyboard_repeat_tap_gap_sec: float = 0.006,
        consumer_control: bool | None = None,
    ) -> "BlueZBackend":
        mouse_interval = max(0.0, float(mouse_coalesce_interval_sec))
        enable_consumer_control = _env_bool("BTD_CONSUMER_CONTROL", False) if consumer_control is None else consumer_control
        return cls(
            enabled=enabled,
            send_null_on_stop=send_null_on_stop,
            disconnect_monitor_interval_sec=disconnect_monitor_interval_sec,
            stuck_reconnect_polls=max(0, int(stuck_reconnect_polls)),
            stuck_reconnect_cooldown_sec=max(0.0, float(stuck_reconnect_cooldown_sec)),
            reconnect_notify_grace_sec=max(0.0, float(reconnect_notify_grace_sec)),
            host_metadata_path=host_metadata_path or os.environ.get(
                "BTD_HOST_METADATA_PATH",
                "/mnt/p3/bluetooth_hosts.json",
            ),
            output_on_connect=_normalize_output_target(output_on_connect, env_name="BTD_OUTPUT_ON_CONNECT"),
            output_on_disconnect=_normalize_output_target(output_on_disconnect, env_name="BTD_OUTPUT_ON_DISCONNECT"),
            logicd_ctrl_socket_path=logicd_ctrl_socket_path or "/tmp/ctrl_events.sock",
            mouse_coalesce_interval_sec=mouse_interval,
            mouse_small_coalesce_interval_sec=max(mouse_interval, float(mouse_small_coalesce_interval_sec)),
            mouse_small_coalesce_threshold=max(0, int(mouse_small_coalesce_threshold)),
            mouse_fast_hold_sec=max(0.0, float(mouse_fast_hold_sec)),
            keyboard_repeat_enabled=bool(keyboard_repeat_enabled),
            keyboard_repeat_delay_sec=max(0.05, float(keyboard_repeat_delay_sec)),
            keyboard_repeat_interval_sec=max(0.01, float(keyboard_repeat_interval_sec)),
            keyboard_repeat_tap_gap_sec=max(0.001, float(keyboard_repeat_tap_gap_sec)),
            application=build_hid_gatt_application(
                security=gatt_security or "none",
                include_consumer=enable_consumer_control,
            ),
            adapter=build_gatt_adapter(adapter_kind),
            advertising_adapter=build_advertising_adapter(
                advertising_adapter_kind or _default_advertising_adapter_kind(adapter_kind)
            ),
            pairing_mode_adapter=build_pairing_mode_adapter(
                pairing_adapter_kind,
                agent_capability=pairing_agent_capability,
            ),
            pairing_mode=pairing_mode,
            advertising_mode=parse_bluez_advertising_mode(advertising_mode),
            advertising_monitor_interval_sec=max(0.1, float(advertising_monitor_interval_sec)),
            advertising_idle_monitor_interval_sec=max(0.1, float(advertising_idle_monitor_interval_sec)),
            disconnect_idle_monitor_interval_sec=max(0.1, float(disconnect_idle_monitor_interval_sec)),
        )

    async def start(self) -> None:
        log.info(
            "BlueZ backend started enabled=%s transport=%s",
            self.enabled,
            self.transport.value,
        )
        if not self.enabled:
            return
        try:
            await self.adapter.register_application(self.application)
        except Exception as exc:
            self.last_error = str(exc)
            self.service_registered = False
            self.enabled = False
            log.warning("BlueZ backend disabled after registration failure: %s", exc)
            return
        self.last_error = ""
        self.service_registered = True
        if self.pairing_mode:
            try:
                await self.pairing_mode_adapter.enable_pairing_mode()
            except Exception as exc:
                self.pairing_error = str(exc)
                log.warning("BlueZ pairing mode enable failed: %s", exc)
            else:
                self.pairing_error = ""
        if self.advertising_mode == BlueZAdvertisingMode.ALWAYS:
            await self._set_advertising_registered(True)
        elif self.advertising_mode == BlueZAdvertisingMode.PAIRING:
            await self._sync_pairing_advertising()
            self._advertising_monitor_task = asyncio.create_task(self._advertising_monitor_loop())
        if self.disconnect_monitor_interval_sec > 0:
            self._disconnect_monitor_task = asyncio.create_task(self._disconnect_monitor_loop())

    async def stop(self) -> None:
        if self._advertising_monitor_task is not None:
            self._advertising_monitor_task.cancel()
            try:
                await self._advertising_monitor_task
            except asyncio.CancelledError:
                pass
            self._advertising_monitor_task = None
        if self._disconnect_monitor_task is not None:
            self._disconnect_monitor_task.cancel()
            try:
                await self._disconnect_monitor_task
            except asyncio.CancelledError:
                pass
            self._disconnect_monitor_task = None
        self._cancel_reconnect_connect_task()
        self._cancel_keyboard_repeat()
        await self._flush_pending_mouse_report()
        if self.send_null_on_stop and self.enabled:
            try:
                await self.send_keyboard_report(null_keyboard_report())
                await self.send_mouse_report(null_mouse_report())
                await self.send_consumer_report(null_consumer_report())
            except Exception as exc:
                log.debug("BlueZ backend stop null report failed: %s", exc)
        await self._set_advertising_registered(False)
        if self.pairing_mode:
            try:
                await self.pairing_mode_adapter.restore_pairing_mode()
            except Exception as exc:
                log.debug("BlueZ pairing mode restore failed: %s", exc)
        if self.enabled:
            try:
                await self.adapter.unregister_application()
            except Exception as exc:
                log.debug("BlueZ backend unregister failed: %s", exc)
            self.service_registered = False
        log.info("BlueZ backend stopped")

    async def send_keyboard_report(self, report: KeyboardReport) -> None:
        if not self.enabled:
            log.debug("BlueZ backend disabled; drop keyboard report bytes=%s", report.hex)
            return
        await self._notify_keyboard_report(report)
        self._update_keyboard_repeat(report.report)

    async def _notify_keyboard_report(self, report: KeyboardReport) -> None:
        try:
            await self.adapter.notify_keyboard_report(report.report)
        except Exception as exc:
            self.last_error = str(exc)
            log.warning("BlueZ backend notify failed: %s", exc)

    def _update_keyboard_repeat(self, report: bytes) -> None:
        if not self.keyboard_repeat_enabled:
            return
        payload = bytes(report)
        if not self.status().host_connected or not _keyboard_report_has_repeatable_key(payload):
            self._cancel_keyboard_repeat()
            return
        if payload == self._keyboard_repeat_report and self._keyboard_repeat_task is not None:
            return
        self._cancel_keyboard_repeat()
        self._keyboard_repeat_report = payload
        self._keyboard_repeat_task = asyncio.create_task(self._repeat_keyboard_report(payload))

    def _cancel_keyboard_repeat(self) -> None:
        if self._keyboard_repeat_task is not None:
            self._keyboard_repeat_task.cancel()
            self._keyboard_repeat_task = None
        self._keyboard_repeat_report = b""

    async def _repeat_keyboard_report(self, payload: bytes) -> None:
        try:
            await asyncio.sleep(self.keyboard_repeat_delay_sec)
            press_report = KeyboardReport(payload)
            release_report = KeyboardReport(_keyboard_repeat_release_report(payload))
            while self._keyboard_repeat_report == payload:
                if not self.status().host_connected:
                    self._cancel_keyboard_repeat()
                    return
                await self._notify_keyboard_report(release_report)
                await asyncio.sleep(self.keyboard_repeat_tap_gap_sec)
                if self._keyboard_repeat_report != payload or not self.status().host_connected:
                    return
                await self._notify_keyboard_report(press_report)
                await asyncio.sleep(self.keyboard_repeat_interval_sec)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_error = str(exc)
            log.debug("BlueZ keyboard repeat stopped: %s", exc)

    async def send_mouse_report(self, report: MouseReport) -> None:
        if not self.enabled:
            log.debug("BlueZ backend disabled; drop mouse report bytes=%s", report.hex)
            return
        if self.mouse_coalesce_interval_sec > 0:
            await self._queue_mouse_report(report)
            return
        await self._notify_mouse_report(report)

    async def _notify_mouse_report(self, report: MouseReport) -> None:
        try:
            await self.adapter.notify_mouse_report(report.report)
        except Exception as exc:
            self.last_error = str(exc)
            log.warning("BlueZ backend mouse notify failed: %s", exc)

    async def send_consumer_report(self, report: ConsumerReport) -> None:
        if not self.enabled:
            log.debug("BlueZ backend disabled; drop consumer report bytes=%s", report.hex)
            return
        try:
            await self.adapter.notify_consumer_report(report.report)
        except Exception as exc:
            self.last_error = str(exc)
            log.warning("BlueZ backend consumer notify failed: %s", exc)

    async def _queue_mouse_report(self, report: MouseReport) -> None:
        buttons = report.report[0]
        dx = _int8(report.report[1])
        dy = _int8(report.report[2])
        wheel = _int8(report.report[3])
        if dx == 0 and dy == 0 and wheel == 0:
            await self._flush_pending_mouse_report()
            await self._notify_mouse_report(report)
            return
        if self._mouse_flush_task is not None and buttons != self._mouse_pending_buttons:
            await self._flush_pending_mouse_report()
        self._mouse_pending_buttons = buttons
        self._mouse_pending_dx = _clamp_int8(self._mouse_pending_dx + dx)
        self._mouse_pending_dy = _clamp_int8(self._mouse_pending_dy + dy)
        self._mouse_pending_wheel = _clamp_int8(self._mouse_pending_wheel + wheel)
        magnitude = max(
            abs(self._mouse_pending_dx),
            abs(self._mouse_pending_dy),
            abs(self._mouse_pending_wheel),
        )
        now = time.monotonic()
        if self.mouse_small_coalesce_threshold <= 0 or magnitude > self.mouse_small_coalesce_threshold:
            self._mouse_fast_until_monotonic = now + self.mouse_fast_hold_sec
        delay = self.mouse_coalesce_interval_sec
        if (
            self.mouse_small_coalesce_threshold > 0
            and magnitude <= self.mouse_small_coalesce_threshold
            and self.mouse_small_coalesce_interval_sec > self.mouse_coalesce_interval_sec
            and now >= self._mouse_fast_until_monotonic
        ):
            delay = self.mouse_small_coalesce_interval_sec
        self._schedule_mouse_flush(delay)

    def _schedule_mouse_flush(self, delay: float) -> None:
        deadline = time.monotonic() + max(0.0, delay)
        if self._mouse_flush_task is not None:
            if self._mouse_flush_deadline_monotonic <= deadline:
                return
            self._mouse_flush_task.cancel()
        self._mouse_flush_deadline_monotonic = deadline
        self._mouse_flush_task = asyncio.create_task(self._flush_mouse_report_later(deadline))

    async def _flush_mouse_report_later(self, deadline: float) -> None:
        try:
            await asyncio.sleep(max(0.0, deadline - time.monotonic()))
            await self._flush_pending_mouse_report()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.debug("BlueZ mouse coalesce flush failed: %s", exc)

    async def _flush_pending_mouse_report(self) -> None:
        task = self._mouse_flush_task
        current = asyncio.current_task()
        if task is not None and task is not current:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._mouse_flush_task = None
        self._mouse_flush_deadline_monotonic = 0.0
        if self._mouse_pending_dx == 0 and self._mouse_pending_dy == 0 and self._mouse_pending_wheel == 0:
            return
        payload = bytes(
            [
                self._mouse_pending_buttons & 0xFF,
                _uint8(self._mouse_pending_dx),
                _uint8(self._mouse_pending_dy),
                _uint8(self._mouse_pending_wheel),
            ]
        )
        self._mouse_pending_dx = 0
        self._mouse_pending_dy = 0
        self._mouse_pending_wheel = 0
        await self._notify_mouse_report(MouseReport(payload))

    async def set_reconnect_advertising(self, enabled: bool) -> None:
        self._reconnect_advertising = bool(enabled)
        if not enabled:
            self._cancel_reconnect_connect_task()
            self._cancel_keyboard_repeat()
        if enabled and not self._pairing_mode_adapter_enabled():
            await _bluetoothctl_set_pairing_visibility(pairable=False, discoverable=False)
        if self.advertising_mode == BlueZAdvertisingMode.PAIRING:
            await self._sync_pairing_advertising()
        if enabled:
            self._start_reconnect_connect_task()
        log.info("BlueZ reconnect advertising %s", "enabled" if enabled else "disabled")

    async def sync_pairing_advertising(self) -> None:
        await self._sync_pairing_advertising()

    def _start_reconnect_connect_task(self) -> None:
        if self._reconnect_connect_task is not None and not self._reconnect_connect_task.done():
            return
        self._reconnect_connect_task = asyncio.create_task(self._connect_paired_devices_for_reconnect())

    def _cancel_reconnect_connect_task(self) -> None:
        if self._reconnect_connect_task is not None:
            self._reconnect_connect_task.cancel()
            self._reconnect_connect_task = None

    async def _connect_paired_devices_for_reconnect(self) -> None:
        try:
            paired_macs = await _bluetoothctl_paired_devices()
            if not paired_macs:
                return
            log.info("BlueZ reconnect trying paired devices: %s", ",".join(paired_macs))
            has_connected_device = False
            for mac in paired_macs:
                await _bluetoothctl_trust_device(mac)
                if await _bluetoothctl_device_connected(mac):
                    has_connected_device = True
                    continue
                connected = await _bluetoothctl_connect_device(mac, timeout=5.0)
                if connected:
                    has_connected_device = True
                    log.info("BlueZ reconnect connected paired device: %s", mac)
                    break
            if has_connected_device:
                await asyncio.sleep(self.reconnect_notify_grace_sec)
                await self._recover_stuck_reconnect_now_if_needed()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.debug("BlueZ reconnect paired-device connect failed: %s", exc)
        finally:
            if asyncio.current_task() is self._reconnect_connect_task:
                self._reconnect_connect_task = None

    async def _disconnect_monitor_loop(self) -> None:
        while True:
            try:
                if self.status().host_connected and not self._last_observed_notify_ready_host:
                    connected_macs = await self._connected_devices()
                    await self._handle_connected_devices_snapshot(connected_macs)
                await asyncio.sleep(self._disconnect_monitor_sleep_interval())
                connected_macs = await self._connected_devices()
                await self._handle_connected_devices_snapshot(connected_macs)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.debug("BlueZ connected device monitor failed: %s", exc)

    async def _advertising_monitor_loop(self) -> None:
        while True:
            await asyncio.sleep(self._advertising_monitor_sleep_interval())
            try:
                await self._sync_pairing_advertising()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.debug("BlueZ advertising monitor failed: %s", exc)

    def _disconnect_monitor_sleep_interval(self) -> float:
        if self._monitor_saw_connected_devices or self.status().host_connected:
            return self.disconnect_monitor_interval_sec
        return max(self.disconnect_monitor_interval_sec, self.disconnect_idle_monitor_interval_sec)

    def _advertising_monitor_sleep_interval(self) -> float:
        if self._reconnect_advertising or self._pairing_mode_adapter_enabled() or self.status().advertising_registered:
            return self.advertising_monitor_interval_sec
        return max(self.advertising_monitor_interval_sec, self.advertising_idle_monitor_interval_sec)

    async def _sync_pairing_advertising(self) -> None:
        if self.advertising_mode != BlueZAdvertisingMode.PAIRING:
            return
        if not self.enabled or not self.service_registered:
            await self._set_advertising_registered(False)
            return
        pairing_visible = self._reconnect_advertising or self._pairing_mode_adapter_enabled()
        if not pairing_visible:
            try:
                pairing_visible = await _bluetoothctl_pairing_visible()
            except Exception as exc:
                log.debug("BlueZ pairing visibility probe failed: %s", exc)
                pairing_visible = False
        await self._set_advertising_registered(pairing_visible)

    def _pairing_mode_adapter_enabled(self) -> bool:
        if not self.pairing_mode:
            return False
        status_fn = getattr(self.pairing_mode_adapter, "status", None)
        if not callable(status_fn):
            return True
        try:
            return bool(getattr(status_fn(), "enabled", False))
        except Exception:
            return False

    async def _set_advertising_registered(self, enabled: bool) -> None:
        try:
            status_fn = getattr(self.advertising_adapter, "status", None)
            registered = bool(getattr(status_fn(), "registered", False)) if callable(status_fn) else False
        except Exception:
            registered = False
        if enabled and not registered:
            try:
                await self.advertising_adapter.register_advertisement(self.advertisement)
            except Exception as exc:
                self.advertising_error = str(exc)
                log.warning("BlueZ advertising registration failed: %s", exc)
            else:
                self.advertising_error = ""
        elif not enabled and registered:
            try:
                await self.advertising_adapter.unregister_advertisement()
            except Exception as exc:
                log.debug("BlueZ advertising unregister failed: %s", exc)

    async def _connected_devices(self) -> list[str]:
        if self.connected_devices_probe is not None:
            return await self.connected_devices_probe()
        return await _bluetoothctl_connected_devices()

    async def _handle_connected_devices_snapshot(self, connected_macs: list[str]) -> None:
        has_connected_devices = bool(connected_macs)
        if self._monitor_saw_connected_devices and not has_connected_devices:
            self._cancel_keyboard_repeat()
            self._last_observed_notify_ready_host = ""
            reset = getattr(self.adapter, "reset_keyboard_input", None)
            if callable(reset):
                await reset()
            reset_mouse = getattr(self.adapter, "reset_mouse_input", None)
            if callable(reset_mouse):
                await reset_mouse()
            reset_consumer = getattr(self.adapter, "reset_consumer_input", None)
            if callable(reset_consumer):
                await reset_consumer()
            log.info("BlueZ connected device monitor saw disconnect; HID input reset")
            await self._notify_logicd_output_target(self.output_on_disconnect, [])
            self._stuck_reconnect_polls_seen = 0
        elif has_connected_devices:
            if not self._monitor_saw_connected_devices:
                await self._notify_logicd_output_target(
                    self._output_target_on_connect(),
                    connected_macs,
                )
            await self._maybe_recover_stuck_reconnect(connected_macs)
            await self._maybe_record_notify_ready_host(connected_macs)
        else:
            self._stuck_reconnect_polls_seen = 0
            self._last_observed_notify_ready_host = ""
        self._monitor_saw_connected_devices = has_connected_devices

    async def _maybe_record_notify_ready_host(self, connected_macs: list[str]) -> None:
        if not connected_macs or not self.status().host_connected:
            return
        address = str(connected_macs[0]).upper()
        if address == self._last_observed_notify_ready_host:
            return
        name = await self._device_name(address)
        connected_at = _utc_timestamp()
        try:
            await self._write_observation_metadata(address, name, connected_at)
        except Exception as exc:
            log.debug("BlueZ host observation metadata update failed address=%s: %s", address, exc)
            return
        self._last_observed_notify_ready_host = address
        log.info(
            "BlueZ host observation metadata updated address=%s name=%s source=btd_notify_ready",
            address,
            name or "",
        )

    async def _device_name(self, address: str) -> str | None:
        if self.device_name_probe is not None:
            return await self.device_name_probe(address)
        return await _bluetoothctl_device_name(address)

    async def _write_observation_metadata(self, address: str, name: str | None, connected_at: str) -> None:
        if self.observation_metadata_writer is not None:
            await self.observation_metadata_writer(address, name, connected_at)
            return
        await _write_bluetooth_host_observation_metadata(
            self.host_metadata_path,
            address,
            last_seen_name=name,
            last_connected_at=connected_at,
            last_connected_source="btd_notify_ready",
        )

    def _output_target_on_connect(self) -> str:
        if self.output_on_connect == "bt" and not self._reconnect_advertising:
            return "auto"
        return self.output_on_connect

    async def _notify_logicd_output_target(self, target: str, connected_macs: list[str]) -> None:
        if not target:
            return
        try:
            response = await _send_logicd_output_target(
                self.logicd_ctrl_socket_path,
                target,
            )
        except Exception as exc:
            log.warning("BlueZ output target notification failed target=%s devices=%s: %s", target, ",".join(connected_macs), exc)
            return
        if response.get("result") == "ok":
            log.info("BlueZ output target notification target=%s devices=%s", target, ",".join(connected_macs) or "none")
        else:
            log.warning("BlueZ output target notification rejected target=%s response=%s", target, response)

    async def _maybe_recover_stuck_reconnect(self, connected_macs: list[str]) -> None:
        if self.stuck_reconnect_polls <= 0 or not self.enabled or not self.service_registered:
            return
        if self.status().host_connected:
            self._stuck_reconnect_polls_seen = 0
            return
        self._stuck_reconnect_polls_seen += 1
        log.debug(
            "BlueZ stuck reconnect candidate polls=%d/%d connected_devices=%s",
            self._stuck_reconnect_polls_seen,
            self.stuck_reconnect_polls,
            ",".join(connected_macs),
        )
        if self._stuck_reconnect_polls_seen < self.stuck_reconnect_polls:
            return
        now = time.monotonic()
        if now - self._last_stuck_reconnect_recovery_monotonic < self.stuck_reconnect_cooldown_sec:
            return
        self._stuck_reconnect_polls_seen = 0
        self._last_stuck_reconnect_recovery_monotonic = now
        await self._recover_stuck_reconnect(connected_macs)

    async def _recover_stuck_reconnect_now_if_needed(self, *, force: bool = False) -> None:
        if self.stuck_reconnect_polls <= 0 or not self.enabled or not self.service_registered:
            return
        if self.status().host_connected:
            self._stuck_reconnect_polls_seen = 0
            return
        connected_macs = await self._connected_devices()
        if not connected_macs:
            self._stuck_reconnect_polls_seen = 0
            return
        now = time.monotonic()
        if not force and now - self._last_stuck_reconnect_recovery_monotonic < self.stuck_reconnect_cooldown_sec:
            return
        log.info(
            "BlueZ stuck reconnect recovery requested immediately: connected_devices=%s",
            ",".join(connected_macs),
        )
        self._stuck_reconnect_polls_seen = 0
        self._last_stuck_reconnect_recovery_monotonic = now
        await self._recover_stuck_reconnect(connected_macs)

    async def _recover_stuck_reconnect(self, connected_macs: list[str]) -> None:
        log.warning(
            "BlueZ stuck reconnect detected: connected_devices=%s host_connected=false; re-registering GATT service",
            ",".join(connected_macs),
        )
        self._cancel_keyboard_repeat()
        reset = getattr(self.adapter, "reset_keyboard_input", None)
        if callable(reset):
            try:
                await reset()
            except Exception as exc:
                log.debug("BlueZ stuck reconnect null reset failed: %s", exc)
        reset_mouse = getattr(self.adapter, "reset_mouse_input", None)
        if callable(reset_mouse):
            try:
                await reset_mouse()
            except Exception as exc:
                log.debug("BlueZ stuck reconnect mouse null reset failed: %s", exc)
        reset_consumer = getattr(self.adapter, "reset_consumer_input", None)
        if callable(reset_consumer):
            try:
                await reset_consumer()
            except Exception as exc:
                log.debug("BlueZ stuck reconnect consumer null reset failed: %s", exc)
        await self._set_advertising_registered(False)
        try:
            await self.adapter.unregister_application()
        except Exception as exc:
            log.debug("BlueZ stuck reconnect GATT unregister failed: %s", exc)
        self.service_registered = False
        try:
            await self.adapter.register_application(self.application)
        except Exception as exc:
            self.last_error = str(exc)
            log.warning("BlueZ stuck reconnect GATT re-register failed: %s", exc)
            return
        self.last_error = ""
        self.service_registered = True
        if self.advertising_mode == BlueZAdvertisingMode.ALWAYS:
            await self._set_advertising_registered(True)
        elif self.advertising_mode == BlueZAdvertisingMode.PAIRING:
            await self._sync_pairing_advertising()
        self._stuck_reconnect_recoveries += 1
        log.info("BlueZ stuck reconnect recovery completed recoveries=%d", self._stuck_reconnect_recoveries)

    def status(self) -> BlueZBackendStatus:
        """Return backend status without touching BlueZ.

        This is intentionally side-effect free so HTTP status and tests can
        inspect the active or dry-run adapter without issuing D-Bus calls.
        """
        notifications = 0
        last_report_hex = ""
        gatt_adapter_kind = ""
        gatt_adapter_available = True
        gatt_adapter_error = ""
        host_connected = self.host_connected
        advertising_registered = False
        advertising_adapter_kind = ""
        advertising_error = self.advertising_error
        pairing_mode_enabled = False
        pairing_adapter_kind = ""
        pairing_agent_capability = ""
        pairing_error = self.pairing_error
        adapter_status = getattr(self.adapter, "status", None)
        if callable(adapter_status):
            status = adapter_status()
            notifications = int(getattr(status, "notifications", 0))
            last_report_hex = str(getattr(status, "last_report_hex", ""))
            host_connected = bool(getattr(status, "notifying", False))
            gatt_adapter_kind = str(getattr(status, "adapter_kind", ""))
            gatt_adapter_available = bool(getattr(status, "available", True))
            gatt_adapter_error = str(getattr(status, "error", ""))
        advertising_status = getattr(self.advertising_adapter, "status", None)
        if callable(advertising_status):
            status = advertising_status()
            advertising_registered = bool(getattr(status, "registered", False))
            advertising_adapter_kind = str(getattr(status, "adapter_kind", ""))
            advertising_error = advertising_error or str(getattr(status, "error", ""))
        pairing_status = getattr(self.pairing_mode_adapter, "status", None)
        if callable(pairing_status):
            status = pairing_status()
            pairing_mode_enabled = bool(getattr(status, "enabled", False))
            pairing_adapter_kind = str(getattr(status, "adapter_kind", ""))
            pairing_agent_capability = str(getattr(status, "agent_capability", ""))
            pairing_error = pairing_error or str(getattr(status, "error", ""))
        if self.last_error:
            gatt_adapter_error = self.last_error
        return BlueZBackendStatus(
            enabled=self.enabled,
            transport=self.transport,
            service_registered=self.service_registered,
            host_connected=host_connected,
            notifications=notifications,
            last_report_hex=last_report_hex,
            gatt_adapter_kind=gatt_adapter_kind,
            gatt_adapter_available=gatt_adapter_available,
            gatt_adapter_error=gatt_adapter_error,
            advertising_registered=advertising_registered,
            advertising_adapter_kind=advertising_adapter_kind,
            advertising_error=advertising_error,
            advertising_mode=self.advertising_mode,
            pairing_mode_enabled=pairing_mode_enabled,
            pairing_adapter_kind=pairing_adapter_kind,
            pairing_agent_capability=pairing_agent_capability,
            pairing_error=pairing_error,
            stuck_reconnect_recoveries=self._stuck_reconnect_recoveries,
        )


def parse_bluez_advertising_mode(value: str | BlueZAdvertisingMode | None) -> BlueZAdvertisingMode:
    """Parse when BLE HID should advertise."""
    if isinstance(value, BlueZAdvertisingMode):
        return value
    if value is None or str(value).strip() == "":
        return DEFAULT_BLUEZ_ADVERTISING_MODE
    text = str(value).strip().lower()
    try:
        return BlueZAdvertisingMode(text)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in BlueZAdvertisingMode)
        raise ValueError(f"invalid BlueZ advertising mode {value!r}; expected one of: {allowed}") from exc


def _default_advertising_adapter_kind(gatt_adapter_kind: str | None) -> str:
    normalized = (gatt_adapter_kind or "dry-run").strip().lower().replace("_", "-")
    if normalized in {"bluez", "bluez-dbus", "dbus"}:
        return "bluez-dbus"
    return "dry-run"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


async def _bluetoothctl_pairing_visible() -> bool:
    proc = await asyncio.create_subprocess_exec(
        "bluetoothctl",
        "show",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=3.0)
    if proc.returncode != 0:
        err = stderr.decode(errors="replace").strip() or stdout.decode(errors="replace").strip()
        raise RuntimeError(err or "bluetoothctl show failed")
    text = stdout.decode(errors="replace")
    return _parse_bt_bool(text, "Pairable") or _parse_bt_bool(text, "Discoverable")


async def _bluetoothctl_paired_devices() -> list[str]:
    try:
        output = await _run_bluetoothctl("paired-devices", timeout=3.0)
        devices = _parse_bluetoothctl_devices(output)
        if devices:
            return devices
    except Exception as exc:
        log.debug("bluetoothctl paired-devices failed; fallback to devices Paired: %s", exc)
    output = await _run_bluetoothctl("devices", "Paired", timeout=3.0)
    return _parse_bluetoothctl_devices(output)


async def _bluetoothctl_trust_device(mac: str) -> None:
    try:
        await _run_bluetoothctl("trust", mac, timeout=3.0)
    except Exception as exc:
        log.debug("bluetoothctl trust %s failed: %s", mac, exc)


async def _bluetoothctl_device_connected(mac: str) -> bool:
    try:
        output = await _run_bluetoothctl("info", mac, timeout=3.0)
    except Exception as exc:
        log.debug("bluetoothctl info %s failed: %s", mac, exc)
        return False
    return _parse_bt_bool(output, "Connected")


async def _bluetoothctl_connect_device(mac: str, *, timeout: float = 5.0) -> bool:
    try:
        await _run_bluetoothctl("connect", mac, timeout=timeout)
    except Exception as exc:
        log.debug("bluetoothctl connect %s failed: %s", mac, exc)
    return await _bluetoothctl_device_connected(mac)


async def _bluetoothctl_set_pairing_visibility(*, pairable: bool, discoverable: bool) -> None:
    for key, enabled in (("pairable", pairable), ("discoverable", discoverable)):
        try:
            await _run_bluetoothctl(key, "on" if enabled else "off", timeout=3.0)
        except Exception as exc:
            err = str(exc)
            log.debug("bluetoothctl %s %s failed: %s", key, "on" if enabled else "off", err)


async def _run_bluetoothctl(*args: str, timeout: float = 3.0) -> str:
    proc = await asyncio.create_subprocess_exec(
        "bluetoothctl",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    text = stdout.decode(errors="replace")
    if proc.returncode != 0:
        err = stderr.decode(errors="replace").strip() or text.strip()
        raise RuntimeError(err or f"bluetoothctl {' '.join(args)} failed")
    return text


def _parse_bluetoothctl_devices(text: str) -> list[str]:
    devices: list[str] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "Device":
            devices.append(parts[1].upper())
    return devices


async def _bluetoothctl_device_name(mac: str) -> str | None:
    try:
        output = await _run_bluetoothctl("info", mac, timeout=3.0)
    except Exception as exc:
        log.debug("bluetoothctl info %s for name failed: %s", mac, exc)
        return None
    for field in ("Name", "Alias"):
        value = _parse_bt_text(output, field)
        if value:
            return value
    return None


async def _write_bluetooth_host_observation_metadata(
    metadata_path: str | Path,
    address: str,
    *,
    last_seen_name: str | None,
    last_connected_at: str,
    last_connected_source: str,
) -> None:
    document = await asyncio.to_thread(_read_bluetooth_host_metadata_document, Path(metadata_path))
    hosts = document.setdefault("hosts", {})
    normalized = address.upper()
    host = dict(hosts.get(normalized, {}))
    if last_seen_name:
        host["last_seen_name"] = last_seen_name
    host["last_connected_at"] = last_connected_at
    host["last_connected_source"] = last_connected_source
    hosts[normalized] = host
    document["version"] = int(document.get("version", 1) or 1)
    await asyncio.to_thread(_atomic_write_json, Path(metadata_path), document)


def _read_bluetooth_host_metadata_document(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {"version": 1, "hosts": {}}
    if not isinstance(raw, dict):
        return {"version": 1, "hosts": {}}
    hosts = raw.get("hosts")
    if not isinstance(hosts, dict):
        hosts = {}
    return {
        **raw,
        "version": raw.get("version", 1),
        "hosts": {str(key).upper(): value for key, value in hosts.items() if isinstance(value, dict)},
    }


def _atomic_write_json(path: Path, payload: dict) -> None:
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


async def _send_logicd_output_target(socket_path: str, target: str, *, timeout: float = 3.0) -> dict:
    reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(socket_path), timeout=timeout)
    try:
        writer.write(json.dumps({"t": "OUTPUT", "target": target}).encode() + b"\n")
        await asyncio.wait_for(writer.drain(), timeout=timeout)
        line = await asyncio.wait_for(reader.readline(), timeout=timeout)
        if not line:
            return {"result": "error", "msg": "empty response"}
        response = json.loads(line.decode(errors="replace"))
        return response if isinstance(response, dict) else {"result": "error", "msg": "non-object response"}
    finally:
        writer.close()


def _normalize_output_target(value: str | None, *, env_name: str) -> str:
    raw = (value if value is not None else os.environ.get(env_name, "")).strip().lower()
    aliases = {
        "": "",
        "off": "",
        "none": "",
        "0": "",
        "false": "",
        "no": "",
        "bluetooth": "bt",
        "kc_bt": "bt",
        "usb": "gadget",
        "kc_usb": "gadget",
        "console": "uinput",
        "kc_console": "uinput",
        "kc_connauto": "auto",
    }
    normalized = aliases.get(raw, raw)
    if normalized not in {"", "auto", "gadget", "uinput", "bt"}:
        raise ValueError("invalid output target %s=%r" % (env_name, value))
    return normalized


def _normalize_output_on_connect(value: str | None) -> str:
    return _normalize_output_target(value, env_name="BTD_OUTPUT_ON_CONNECT")


def _parse_bt_bool(text: str, field: str) -> bool:
    prefix = f"{field}:"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            value = stripped[len(prefix) :].strip().lower()
            return value in {"yes", "true", "1", "on"}
    return False


def _parse_bt_text(text: str, field: str) -> str | None:
    prefix = f"{field}:"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            value = stripped[len(prefix) :].strip()
            return value or None
    return None


def _utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _int8(value: int) -> int:
    value &= 0xFF
    return value - 256 if value >= 128 else value


def _keyboard_report_has_repeatable_key(report: bytes) -> bool:
    if len(report) < 8:
        return False
    return any(code for code in report[2:8])


def _keyboard_repeat_release_report(report: bytes) -> bytes:
    if len(report) < 8:
        return bytes(8)
    return bytes([report[0], 0, 0, 0, 0, 0, 0, 0])


def _uint8(value: int) -> int:
    return value & 0xFF


def _clamp_int8(value: int) -> int:
    return max(-127, min(127, value))


async def _bluetoothctl_connected_devices() -> list[str]:
    proc = await asyncio.create_subprocess_exec(
        "bluetoothctl",
        "devices",
        "Connected",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=3.0)
    if proc.returncode != 0:
        err = stderr.decode(errors="replace").strip() or stdout.decode(errors="replace").strip()
        raise RuntimeError(err or "bluetoothctl devices Connected failed")
    devices: list[str] = []
    for line in stdout.decode(errors="replace").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "Device":
            devices.append(parts[1].upper())
    return devices
