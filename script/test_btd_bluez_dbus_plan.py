#!/usr/bin/env python3
"""Regression tests for pure-data BlueZ D-Bus GATT registration plans."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from btd.bluez_dbus_plan import (  # noqa: E402
    DEFAULT_ADAPTER_PATH,
    GATT_CHARACTERISTIC_IFACE,
    GATT_DESCRIPTOR_IFACE,
    GATT_MANAGER_IFACE,
    GATT_SERVICE_IFACE,
    build_bluez_gatt_registration_plan,
)
from btd.gatt_adapter import BlueZDbusGattRegistrationAdapter, DryRunGattRegistrationAdapter  # noqa: E402
from btd.gatt_app import build_hid_gatt_application  # noqa: E402
from btd.gatt_hid import (  # noqa: E402
    BATTERY_SERVICE_UUID,
    DEVICE_INFORMATION_SERVICE_UUID,
    HID_REPORT_UUID,
    HID_SERVICE_UUID,
    KEYBOARD_INPUT_REPORT,
    KEYBOARD_OUTPUT_REPORT,
    MOUSE_INPUT_REPORT,
)


async def main_async() -> None:
    app = build_hid_gatt_application()
    plan = build_bluez_gatt_registration_plan(app)

    assert plan.bus_name == "org.bluez"
    assert plan.adapter_path == DEFAULT_ADAPTER_PATH
    assert plan.manager_iface == GATT_MANAGER_IFACE
    assert plan.register_method == "RegisterApplication"
    assert plan.unregister_method == "UnregisterApplication"
    assert plan.app_path == app.path
    assert app.path in plan.object_paths()

    objects = plan.as_object_manager_dict()
    services = [interfaces for interfaces in objects.values() if GATT_SERVICE_IFACE in interfaces]
    service_uuids = {service[GATT_SERVICE_IFACE]["UUID"] for service in services}
    assert service_uuids == {HID_SERVICE_UUID, DEVICE_INFORMATION_SERVICE_UUID, BATTERY_SERVICE_UUID}
    assert all(service[GATT_SERVICE_IFACE]["Primary"] is True for service in services)

    chars = [interfaces[GATT_CHARACTERISTIC_IFACE] for interfaces in objects.values() if GATT_CHARACTERISTIC_IFACE in interfaces]
    assert len(chars) == 13
    report_chars = [char for char in chars if char["UUID"] == HID_REPORT_UUID]
    assert len(report_chars) == 3
    report_lengths = sorted(len(char["Value"]) for char in report_chars)
    assert report_lengths == sorted(
        [KEYBOARD_INPUT_REPORT.payload_size, KEYBOARD_OUTPUT_REPORT.payload_size, MOUSE_INPUT_REPORT.payload_size]
    )
    assert any("notify" in char["Flags"] for char in report_chars)

    descs = [interfaces[GATT_DESCRIPTOR_IFACE] for interfaces in objects.values() if GATT_DESCRIPTOR_IFACE in interfaces]
    assert len(descs) == 7
    assert all("Characteristic" in desc for desc in descs)

    dry = DryRunGattRegistrationAdapter()
    await dry.register_application(app)
    assert dry.registration_plan is not None
    assert dry.status().registered is True
    assert dry.status().object_count == len(plan.objects)
    await dry.notify_keyboard_report(bytes(KEYBOARD_INPUT_REPORT.payload_size))
    assert dry.status().notifications == 1
    await dry.unregister_application()
    assert dry.status().registered is False

    bluez = BlueZDbusGattRegistrationAdapter()
    try:
        await bluez.register_application(app)
    except Exception:
        pass
    assert bluez.registration_plan is not None
    assert bluez.status().adapter_kind == "bluez-dbus"
    assert bluez.status().object_count == len(plan.objects)

    print("ok: BlueZ D-Bus GATT registration plan")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
