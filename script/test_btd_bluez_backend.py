#!/usr/bin/env python3
"""Regression tests for the btd BlueZ backend."""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from btd.bluez_backend import (  # noqa: E402
    DEFAULT_BLUEZ_ADVERTISING_MODE,
    DEFAULT_BLUEZ_HID_TRANSPORT,
    BlueZAdvertisingMode,
    BlueZBackend,
    BlueZHidTransport,
    _normalize_output_on_connect,
    _normalize_output_target,
    parse_bluez_advertising_mode,
)
import btd.bluez_backend as bluez_backend_module  # noqa: E402
from btd.gatt_adapter import BlueZGattAdapterUnavailable  # noqa: E402
from btd.protocol import parse_raw_consumer_report, parse_raw_keyboard_report, parse_raw_mouse_report  # noqa: E402


async def _pairing_not_visible() -> bool:
    return False


bluez_backend_module._bluetoothctl_pairing_visible = _pairing_not_visible


visibility_changes: list[tuple[bool, bool]] = []
paired_connect_calls: list[tuple[str, str]] = []


async def _capture_pairing_visibility(*, pairable: bool, discoverable: bool) -> None:
    visibility_changes.append((pairable, discoverable))


bluez_backend_module._bluetoothctl_set_pairing_visibility = _capture_pairing_visibility


async def _fake_paired_devices() -> list[str]:
    paired_connect_calls.append(("paired", ""))
    return ["AA:BB:CC:DD:EE:FF"]


async def _fake_trust_device(mac: str) -> None:
    paired_connect_calls.append(("trust", mac))


async def _fake_device_connected(mac: str) -> bool:
    paired_connect_calls.append(("connected", mac))
    return False


async def _fake_connect_device(mac: str, *, timeout: float = 5.0) -> bool:
    del timeout
    paired_connect_calls.append(("connect", mac))
    return True


bluez_backend_module._bluetoothctl_paired_devices = _fake_paired_devices
bluez_backend_module._bluetoothctl_trust_device = _fake_trust_device
bluez_backend_module._bluetoothctl_device_connected = _fake_device_connected
bluez_backend_module._bluetoothctl_connect_device = _fake_connect_device


class FailingAdapter:
    async def register_application(self, _application):
        raise BlueZGattAdapterUnavailable("missing dependency")

    async def unregister_application(self):
        raise AssertionError("unregister should not be called after failed registration")

    async def notify_keyboard_report(self, _report: bytes):
        raise AssertionError("notify should not be called after failed registration")

    async def notify_mouse_report(self, _report: bytes):
        raise AssertionError("notify should not be called after failed registration")

    async def notify_consumer_report(self, _report: bytes):
        raise AssertionError("notify should not be called after failed registration")

    def status(self):
        class Status:
            notifications = 0
            last_report_hex = ""
            adapter_kind = "failing"
            available = False
            error = "missing dependency"

        return Status()


class NotifyingAdapter:
    def __init__(self) -> None:
        self.resets = 0
        self.mouse_resets = 0
        self.consumer_resets = 0
        self.keyboard_reports: list[bytes] = []
        self.mouse_reports: list[bytes] = []
        self.consumer_reports: list[bytes] = []
        self.notifying = False

    async def register_application(self, _application):
        pass

    async def unregister_application(self):
        pass

    async def notify_keyboard_report(self, _report: bytes):
        self.keyboard_reports.append(bytes(_report))

    async def notify_mouse_report(self, _report: bytes):
        self.mouse_reports.append(bytes(_report))

    async def notify_consumer_report(self, _report: bytes):
        self.consumer_reports.append(bytes(_report))

    async def reset_keyboard_input(self):
        self.resets += 1

    async def reset_mouse_input(self):
        self.mouse_resets += 1

    async def reset_consumer_input(self):
        self.consumer_resets += 1

    def status(self):
        class Status:
            notifications = 0
            last_report_hex = ""
            adapter_kind = "notifying"
            available = True
            error = ""

        Status.notifying = self.notifying
        return Status()


class RecoverableAdapter:
    def __init__(self) -> None:
        self.registers = 0
        self.unregisters = 0
        self.resets = 0
        self.mouse_resets = 0
        self.consumer_resets = 0

    async def register_application(self, _application):
        self.registers += 1

    async def unregister_application(self):
        self.unregisters += 1

    async def notify_keyboard_report(self, _report: bytes):
        pass

    async def notify_mouse_report(self, _report: bytes):
        pass

    async def notify_consumer_report(self, _report: bytes):
        pass

    async def reset_keyboard_input(self):
        self.resets += 1

    async def reset_mouse_input(self):
        self.mouse_resets += 1

    async def reset_consumer_input(self):
        self.consumer_resets += 1

    def status(self):
        class Status:
            notifications = 0
            last_report_hex = ""
            notifying = False
            adapter_kind = "recoverable"
            available = True
            error = ""

        return Status()


class RecoverableAdvertising:
    def __init__(self) -> None:
        self.registers = 0
        self.unregisters = 0

    async def register_advertisement(self, _advertisement):
        self.registers += 1

    async def unregister_advertisement(self):
        self.unregisters += 1

    def status(self):
        registered = self.registers > self.unregisters

        class Status:
            pass

        Status.registered = registered
        Status.adapter_kind = "recoverable"
        Status.available = True
        Status.error = ""
        return Status()


async def main_async() -> None:
    report = parse_raw_keyboard_report(bytes.fromhex("0000040000000000"))
    mouse_report = parse_raw_mouse_report(bytes.fromhex("0001ff00"))
    consumer_report = parse_raw_consumer_report(bytes.fromhex("e900"))

    disabled = BlueZBackend(enabled=False)
    await disabled.start()
    await disabled.send_keyboard_report(report)
    status = disabled.status()
    assert status.enabled is False
    assert status.transport == BlueZHidTransport.BLE
    assert status.service_registered is False
    assert status.host_connected is False
    assert status.notifications == 0
    await disabled.stop()

    enabled = BlueZBackend(
        enabled=True,
        send_null_on_stop=False,
        advertising_mode=BlueZAdvertisingMode.OFF,
    )
    await enabled.start()
    status = enabled.status()
    assert status.enabled is True
    assert status.service_registered is True
    assert status.transport == BlueZHidTransport.BLE

    await enabled.send_keyboard_report(report)
    await enabled.send_mouse_report(mouse_report)
    await enabled.send_consumer_report(consumer_report)
    status = enabled.status()
    assert status.notifications == 3
    assert status.last_report_hex == consumer_report.hex
    assert status.advertising_registered is False
    await enabled.stop()
    assert enabled.status().service_registered is False
    assert enabled.status().advertising_registered is False

    always_advertising = BlueZBackend(
        enabled=True,
        send_null_on_stop=False,
        advertising_mode=BlueZAdvertisingMode.ALWAYS,
    )
    await always_advertising.start()
    assert always_advertising.status().advertising_registered is True
    await always_advertising.stop()
    assert always_advertising.status().advertising_registered is False

    reconnect_advertising = BlueZBackend(
        enabled=True,
        send_null_on_stop=False,
        advertising_mode=BlueZAdvertisingMode.PAIRING,
    )
    await reconnect_advertising.start()
    assert reconnect_advertising.status().advertising_registered is False
    visibility_changes.clear()
    await reconnect_advertising.set_reconnect_advertising(True)
    assert visibility_changes == [(False, False)]
    assert reconnect_advertising.status().advertising_registered is True
    await asyncio.sleep(0)
    await asyncio.sleep(0.25)
    assert paired_connect_calls == [
        ("paired", ""),
        ("trust", "AA:BB:CC:DD:EE:FF"),
        ("connected", "AA:BB:CC:DD:EE:FF"),
        ("connect", "AA:BB:CC:DD:EE:FF"),
    ]
    paired_connect_calls.clear()
    await reconnect_advertising.set_reconnect_advertising(False)
    assert reconnect_advertising.status().advertising_registered is False
    await reconnect_advertising.stop()

    failed = BlueZBackend(enabled=True, adapter=FailingAdapter())
    await failed.start()
    status = failed.status()
    assert status.enabled is False
    assert status.service_registered is False
    assert "missing dependency" in status.gatt_adapter_error
    await failed.send_keyboard_report(report)
    await failed.stop()

    notifying_adapter = NotifyingAdapter()
    notifying_adapter.notifying = True
    observed_hosts: list[tuple[str, str | None, str]] = []

    async def capture_observation(address: str, name: str | None, connected_at: str) -> None:
        observed_hosts.append((address, name, connected_at))

    async def fake_device_name(address: str) -> str | None:
        assert address == "AA:BB:CC:DD:EE:FF"
        return "Test Host"

    notifying = BlueZBackend(
        enabled=True,
        adapter=notifying_adapter,
        device_name_probe=fake_device_name,
        observation_metadata_writer=capture_observation,
    )
    status = notifying.status()
    assert status.host_connected is True
    assert notifying.host_connected is False
    await notifying._handle_connected_devices_snapshot(["AA:BB:CC:DD:EE:FF"])
    assert len(observed_hosts) == 1
    assert observed_hosts[0][0] == "AA:BB:CC:DD:EE:FF"
    assert observed_hosts[0][1] == "Test Host"
    assert observed_hosts[0][2].endswith("+00:00")
    await notifying._handle_connected_devices_snapshot(["AA:BB:CC:DD:EE:FF"])
    assert len(observed_hosts) == 1
    await notifying._handle_connected_devices_snapshot([])
    assert notifying.adapter.resets == 1
    assert notifying.adapter.mouse_resets == 1
    assert notifying.adapter.consumer_resets == 1
    await notifying._handle_connected_devices_snapshot([])
    assert notifying.adapter.resets == 1
    assert notifying.adapter.mouse_resets == 1
    assert notifying.adapter.consumer_resets == 1

    with tempfile.TemporaryDirectory() as tmpdir:
        metadata_path = Path(tmpdir) / "bluetooth_hosts.json"
        metadata_path.write_text(
            '{"version":1,"hosts":{"AA:BB:CC:DD:EE:FF":{"display_name":"Desk PC"}}}\n',
            encoding="utf-8",
        )
        file_writer = BlueZBackend(enabled=True, adapter=notifying_adapter, host_metadata_path=str(metadata_path))
        await file_writer._write_observation_metadata(
            "AA:BB:CC:DD:EE:FF",
            "Test Host",
            "2026-06-10T21:09:00+00:00",
        )
        stored = metadata_path.read_text(encoding="utf-8")
        assert '"display_name": "Desk PC"' in stored
        assert '"last_seen_name": "Test Host"' in stored
        assert '"last_connected_at": "2026-06-10T21:09:00+00:00"' in stored
        assert '"last_connected_source": "btd_notify_ready"' in stored

    immediate_monitor_adapter = NotifyingAdapter()
    immediate_monitor_adapter.notifying = True
    immediate_monitor_observations: list[tuple[str, str | None, str]] = []

    async def immediate_connected_probe() -> list[str]:
        return ["AA:BB:CC:DD:EE:FF"]

    async def immediate_observation(address: str, name: str | None, connected_at: str) -> None:
        immediate_monitor_observations.append((address, name, connected_at))

    immediate_monitor = BlueZBackend(
        enabled=True,
        adapter=immediate_monitor_adapter,
        connected_devices_probe=immediate_connected_probe,
        device_name_probe=fake_device_name,
        observation_metadata_writer=immediate_observation,
        disconnect_monitor_interval_sec=99,
        disconnect_idle_monitor_interval_sec=99,
    )
    monitor_task = asyncio.create_task(immediate_monitor._disconnect_monitor_loop())
    await asyncio.sleep(0.01)
    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass
    assert len(immediate_monitor_observations) == 1
    assert immediate_monitor_observations[0][0] == "AA:BB:CC:DD:EE:FF"

    coalescing_adapter = NotifyingAdapter()
    coalescing = BlueZBackend(
        enabled=True,
        adapter=coalescing_adapter,
        mouse_coalesce_interval_sec=0.01,
        mouse_small_coalesce_interval_sec=0.02,
        mouse_small_coalesce_threshold=3,
        mouse_fast_hold_sec=0.05,
    )
    await coalescing.send_mouse_report(parse_raw_mouse_report(bytes([0, 1, 1, 0])))
    await asyncio.sleep(0.012)
    assert coalescing_adapter.mouse_reports == []
    await coalescing.send_mouse_report(parse_raw_mouse_report(bytes([0, 20, 2, 0])))
    assert coalescing_adapter.mouse_reports == []
    await asyncio.sleep(0.02)
    assert coalescing_adapter.mouse_reports == [bytes([0, 21, 3, 0])]
    await coalescing.send_mouse_report(parse_raw_mouse_report(bytes([0, 20, 0, 0])))
    await coalescing.send_mouse_report(parse_raw_mouse_report(bytes([0, 1, 0, 0])))
    await asyncio.sleep(0.012)
    assert coalescing_adapter.mouse_reports[-1] == bytes([0, 21, 0, 0])
    await coalescing.send_mouse_report(parse_raw_mouse_report(bytes([1, 0, 0, 0])))
    assert coalescing_adapter.mouse_reports[-1] == bytes([1, 0, 0, 0])

    repeat_adapter = NotifyingAdapter()
    repeat_adapter.notifying = True
    repeating = BlueZBackend(
        enabled=True,
        adapter=repeat_adapter,
        keyboard_repeat_enabled=True,
        keyboard_repeat_delay_sec=0.01,
        keyboard_repeat_interval_sec=0.01,
    )
    await repeating.send_keyboard_report(report)
    await asyncio.sleep(0.035)
    repeated_count = len(repeat_adapter.keyboard_reports)
    assert repeated_count >= 3
    assert bytes(8) in repeat_adapter.keyboard_reports[1:]
    assert report.report in repeat_adapter.keyboard_reports[2:]
    await repeating.send_keyboard_report(parse_raw_keyboard_report(bytes(8)))
    await asyncio.sleep(0.025)
    assert repeat_adapter.keyboard_reports[-1] == bytes(8)
    assert len(repeat_adapter.keyboard_reports) == repeated_count + 1

    disconnected_repeat_adapter = NotifyingAdapter()
    disconnected_repeating = BlueZBackend(
        enabled=True,
        adapter=disconnected_repeat_adapter,
        keyboard_repeat_enabled=True,
        keyboard_repeat_delay_sec=0.01,
        keyboard_repeat_interval_sec=0.01,
    )
    await disconnected_repeating.send_keyboard_report(report)
    await asyncio.sleep(0.03)
    assert disconnected_repeat_adapter.keyboard_reports == [report.report]

    output_switches: list[tuple[str, str]] = []

    async def fake_send_logicd_output(socket_path: str, target: str, *, timeout: float = 3.0) -> dict:
        del timeout
        output_switches.append((socket_path, target))
        return {"result": "ok"}

    old_send_logicd_output = bluez_backend_module._send_logicd_output_target
    bluez_backend_module._send_logicd_output_target = fake_send_logicd_output
    try:
        switch_on_connect = BlueZBackend(
            enabled=True,
            adapter=NotifyingAdapter(),
            output_on_connect="bt",
            output_on_disconnect="auto",
            logicd_ctrl_socket_path="/tmp/test-ctrl.sock",
        )
        await switch_on_connect._handle_connected_devices_snapshot(["AA:BB:CC:DD:EE:FF"])
        await switch_on_connect._handle_connected_devices_snapshot(["AA:BB:CC:DD:EE:FF"])
        await switch_on_connect._handle_connected_devices_snapshot([])
        await switch_on_connect._handle_connected_devices_snapshot([])
        assert output_switches == [
            ("/tmp/test-ctrl.sock", "auto"),
            ("/tmp/test-ctrl.sock", "auto"),
        ]
        output_switches.clear()
        switch_on_bt_reconnect = BlueZBackend(
            enabled=True,
            adapter=NotifyingAdapter(),
            output_on_connect="bt",
            logicd_ctrl_socket_path="/tmp/test-ctrl.sock",
        )
        await switch_on_bt_reconnect.set_reconnect_advertising(True)
        await switch_on_bt_reconnect._handle_connected_devices_snapshot(["AA:BB:CC:DD:EE:FF"])
        assert output_switches == [("/tmp/test-ctrl.sock", "bt")]
    finally:
        bluez_backend_module._send_logicd_output_target = old_send_logicd_output

    recoverable_adapter = RecoverableAdapter()
    recoverable_advertising = RecoverableAdvertising()
    recoverable = BlueZBackend(
        enabled=True,
        adapter=recoverable_adapter,
        advertising_adapter=recoverable_advertising,
        advertising_mode=BlueZAdvertisingMode.ALWAYS,
        stuck_reconnect_polls=2,
        stuck_reconnect_cooldown_sec=0,
    )
    await recoverable.start()
    assert recoverable_adapter.registers == 1
    assert recoverable_advertising.registers == 1
    await recoverable._handle_connected_devices_snapshot(["AA:BB:CC:DD:EE:FF"])
    assert recoverable_adapter.unregisters == 0
    await recoverable._handle_connected_devices_snapshot(["AA:BB:CC:DD:EE:FF"])
    assert recoverable_adapter.resets == 1
    assert recoverable_adapter.mouse_resets == 1
    assert recoverable_adapter.consumer_resets == 1
    assert recoverable_adapter.unregisters == 1
    assert recoverable_adapter.registers == 2
    assert recoverable_advertising.unregisters == 1
    assert recoverable_advertising.registers == 2
    assert recoverable.status().stuck_reconnect_recoveries == 1
    await recoverable.stop()

    immediate_recoverable_adapter = RecoverableAdapter()
    immediate_recoverable_advertising = RecoverableAdvertising()

    async def connected_probe() -> list[str]:
        return ["AA:BB:CC:DD:EE:FF"]

    immediate_recoverable = BlueZBackend(
        enabled=True,
        adapter=immediate_recoverable_adapter,
        advertising_adapter=immediate_recoverable_advertising,
        advertising_mode=BlueZAdvertisingMode.PAIRING,
        connected_devices_probe=connected_probe,
        stuck_reconnect_polls=3,
        stuck_reconnect_cooldown_sec=0,
        reconnect_notify_grace_sec=0.01,
    )
    await immediate_recoverable.start()
    assert immediate_recoverable_adapter.registers == 1
    assert immediate_recoverable_advertising.registers == 0
    await immediate_recoverable.set_reconnect_advertising(True)
    await asyncio.sleep(0.05)
    assert immediate_recoverable_adapter.resets == 1
    assert immediate_recoverable_adapter.mouse_resets == 1
    assert immediate_recoverable_adapter.consumer_resets == 1
    assert immediate_recoverable_adapter.unregisters == 1
    assert immediate_recoverable_adapter.registers == 2
    assert immediate_recoverable_advertising.unregisters == 1
    assert immediate_recoverable_advertising.registers == 2
    assert immediate_recoverable.status().stuck_reconnect_recoveries == 1
    await immediate_recoverable.stop()

    stop_null = BlueZBackend(enabled=True, send_null_on_stop=True)
    await stop_null.start()
    await stop_null.send_keyboard_report(report)
    await stop_null.stop()
    status = stop_null.status()
    assert status.notifications == 4
    assert status.last_report_hex == bytes(2).hex()

    assert DEFAULT_BLUEZ_HID_TRANSPORT == BlueZHidTransport.BLE
    assert DEFAULT_BLUEZ_ADVERTISING_MODE == BlueZAdvertisingMode.PAIRING

    assert parse_bluez_advertising_mode(None) == BlueZAdvertisingMode.PAIRING
    assert parse_bluez_advertising_mode("") == BlueZAdvertisingMode.PAIRING
    assert parse_bluez_advertising_mode("always") == BlueZAdvertisingMode.ALWAYS
    assert parse_bluez_advertising_mode("PAIRING") == BlueZAdvertisingMode.PAIRING
    assert parse_bluez_advertising_mode("off") == BlueZAdvertisingMode.OFF
    try:
        parse_bluez_advertising_mode("invalid")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid advertising mode should raise ValueError")

    assert _normalize_output_on_connect(None) == ""
    assert _normalize_output_on_connect("bluetooth") == "bt"
    assert _normalize_output_on_connect("KC_USB") == "gadget"
    assert _normalize_output_target("KC_CONNAUTO", env_name="BTD_OUTPUT_ON_DISCONNECT") == "auto"
    try:
        _normalize_output_on_connect("bad")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid output-on-connect should raise ValueError")

    print("ok: btd BlueZ backend")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
