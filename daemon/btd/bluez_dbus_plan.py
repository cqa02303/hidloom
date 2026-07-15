"""Pure-data BlueZ D-Bus registration plan for BLE HID GATT.

The BlueZ implementation uses two layers:

1. a side-effect-free plan describing which D-Bus objects/methods/properties are
   required; and
2. an adapter that executes that plan against the system bus.

This module is layer 1. It intentionally performs no D-Bus calls, so tests can
validate object paths, interfaces, and properties without Bluetooth hardware or
BlueZ running.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .gatt_app import (
    GattApplicationModel,
    GattCharacteristicModel,
    GattDescriptorModel,
    GattServiceModel,
)

BLUEZ_SERVICE = "org.bluez"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
DBUS_OBJECT_MANAGER_IFACE = "org.freedesktop.DBus.ObjectManager"
GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHARACTERISTIC_IFACE = "org.bluez.GattCharacteristic1"
GATT_DESCRIPTOR_IFACE = "org.bluez.GattDescriptor1"

DEFAULT_ADAPTER_PATH = "/org/bluez/hci0"


@dataclass(frozen=True)
class BlueZDbusObject:
    """One D-Bus object exported by the btd GATT application."""

    path: str
    interfaces: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class BlueZGattRegistrationPlan:
    """Side-effect-free description of a BlueZ RegisterApplication call."""

    bus_name: str = BLUEZ_SERVICE
    adapter_path: str = DEFAULT_ADAPTER_PATH
    app_path: str = ""
    manager_iface: str = GATT_MANAGER_IFACE
    objects: tuple[BlueZDbusObject, ...] = field(default_factory=tuple)
    options: dict[str, Any] = field(default_factory=dict)

    @property
    def register_method(self) -> str:
        return "RegisterApplication"

    @property
    def unregister_method(self) -> str:
        return "UnregisterApplication"

    def object_paths(self) -> tuple[str, ...]:
        return tuple(obj.path for obj in self.objects)

    def as_object_manager_dict(self) -> dict[str, dict[str, dict[str, Any]]]:
        """Return data shape used by ObjectManager.GetManagedObjects."""
        return {obj.path: obj.interfaces for obj in self.objects}


def _service_interfaces(service: GattServiceModel) -> dict[str, dict[str, Any]]:
    return {
        GATT_SERVICE_IFACE: {
            "UUID": service.uuid,
            "Primary": bool(service.primary),
        }
    }


def _characteristic_interfaces(service: GattServiceModel, char: GattCharacteristicModel) -> dict[str, dict[str, Any]]:
    return {
        GATT_CHARACTERISTIC_IFACE: {
            "UUID": char.uuid,
            "Service": service.path,
            "Flags": list(char.flags),
            "Value": list(char.value),
        }
    }


def _descriptor_interfaces(char: GattCharacteristicModel, desc: GattDescriptorModel) -> dict[str, dict[str, Any]]:
    return {
        GATT_DESCRIPTOR_IFACE: {
            "UUID": desc.uuid,
            "Characteristic": char.path,
            "Flags": list(desc.flags),
            "Value": list(desc.value),
        }
    }


def build_bluez_gatt_registration_plan(
    application: GattApplicationModel,
    *,
    adapter_path: str = DEFAULT_ADAPTER_PATH,
) -> BlueZGattRegistrationPlan:
    """Build the D-Bus registration plan for a GATT application model.

    The app root object exposes ObjectManager. Services, characteristics, and
    descriptors expose BlueZ GATT interfaces. The registration adapter consumes
    this plan to create and export those objects.
    """
    objects: list[BlueZDbusObject] = [
        BlueZDbusObject(
            path=application.path,
            interfaces={DBUS_OBJECT_MANAGER_IFACE: {}},
        )
    ]
    for service in application.services:
        objects.append(BlueZDbusObject(service.path, _service_interfaces(service)))
        for char in service.characteristics:
            objects.append(BlueZDbusObject(char.path, _characteristic_interfaces(service, char)))
            for desc in char.descriptors:
                objects.append(BlueZDbusObject(desc.path, _descriptor_interfaces(char, desc)))
    return BlueZGattRegistrationPlan(
        adapter_path=adapter_path,
        app_path=application.path,
        objects=tuple(objects),
        options={},
    )
