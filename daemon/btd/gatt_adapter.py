"""BLE HID GATT registration adapter boundary.

This module defines the BlueZ/D-Bus adapter interface, its real registration
implementation, and a DryRun adapter for tests and development hosts.

Design constraints:
- No packet/framing change for logicd -> btd.
- Keyboard reports are still fixed 8-byte payloads validated by gatt_hid.
- Real BlueZ/D-Bus support must be opt-in so development hosts without BlueZ can
  still run the test suite.
"""
from __future__ import annotations

import importlib.util
import logging
import os
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from typing import Protocol

from .bluez_dbus_plan import BlueZGattRegistrationPlan, build_bluez_gatt_registration_plan
from .gatt_app import (
    GattApplicationModel,
    GattCharacteristicModel,
    GattDescriptorModel,
    GattServiceModel,
    build_hid_gatt_application,
)
from .gatt_hid import (
    BOOT_KEYBOARD_INPUT_REPORT_UUID,
    CONSUMER_INPUT_REPORT,
    HID_REPORT_UUID,
    KEYBOARD_INPUT_REPORT,
    MOUSE_INPUT_REPORT,
    REPORT_REFERENCE_DESCRIPTOR_UUID,
)
from .gatt_hid import validate_consumer_report_payload, validate_keyboard_report_payload, validate_mouse_report_payload

log = logging.getLogger("btd.gatt_adapter")


def _gatt_trace_enabled() -> bool:
    return os.environ.get("BTD_GATT_TRACE", "").strip().lower() in {"1", "true", "yes", "on"}


def _log_gatt_value(message: str, *args: object) -> None:
    if _gatt_trace_enabled():
        log.info(message, *args)
    else:
        log.debug(message, *args)


def _keyboard_input_null_value(uuid: str) -> bytes | None:
    if uuid == HID_REPORT_UUID:
        return KEYBOARD_INPUT_REPORT.encode_value(bytes(KEYBOARD_INPUT_REPORT.payload_size))
    if uuid == BOOT_KEYBOARD_INPUT_REPORT_UUID:
        return bytes(KEYBOARD_INPUT_REPORT.payload_size)
    return None


def _input_null_value(characteristic: GattCharacteristicModel) -> bytes | None:
    if characteristic.uuid == BOOT_KEYBOARD_INPUT_REPORT_UUID:
        return bytes(KEYBOARD_INPUT_REPORT.payload_size)
    if characteristic.uuid != HID_REPORT_UUID:
        return None
    report_reference = _report_reference_value(characteristic)
    if report_reference == KEYBOARD_INPUT_REPORT.report_reference:
        return KEYBOARD_INPUT_REPORT.encode_value(bytes(KEYBOARD_INPUT_REPORT.payload_size))
    if report_reference == MOUSE_INPUT_REPORT.report_reference:
        return MOUSE_INPUT_REPORT.encode_value(bytes(MOUSE_INPUT_REPORT.payload_size))
    if report_reference == CONSUMER_INPUT_REPORT.report_reference:
        return CONSUMER_INPUT_REPORT.encode_value(bytes(CONSUMER_INPUT_REPORT.payload_size))
    return None


def _report_reference_value(characteristic: GattCharacteristicModel) -> bytes:
    for descriptor in characteristic.descriptors:
        if descriptor.uuid == REPORT_REFERENCE_DESCRIPTOR_UUID:
            return descriptor.value
    return b""


class GattRegistrationAdapter(Protocol):
    """Boundary for BlueZ GATT application registration."""

    async def register_application(self, application: GattApplicationModel) -> None:
        """Register the GATT application."""

    async def unregister_application(self) -> None:
        """Unregister the GATT application."""

    async def notify_keyboard_report(self, report: bytes) -> None:
        """Notify one keyboard input report payload."""

    async def notify_mouse_report(self, report: bytes) -> None:
        """Notify one mouse input report payload."""

    async def notify_consumer_report(self, report: bytes) -> None:
        """Notify one Consumer Control input report payload."""


@dataclass
class GattAdapterStatus:
    registered: bool
    notifications: int = 0
    last_report_hex: str = ""
    notifying: bool = False
    adapter_kind: str = "dry-run"
    available: bool = True
    error: str = ""
    app_path: str = ""
    object_count: int = 0
    adapter_path: str = ""


class BlueZGattAdapterUnavailable(RuntimeError):
    """Raised when the real BlueZ adapter is requested but unavailable."""


@dataclass
class DryRunGattRegistrationAdapter:
    """Side-effect-free adapter for tests and non-BlueZ development hosts.

    It records what would be registered/notified and validates report payload
    size. This lets BlueZBackend exercise lifecycle code without touching the
    system D-Bus or Bluetooth stack.
    """

    application: GattApplicationModel = field(default_factory=build_hid_gatt_application)
    registered: bool = False
    notifications: int = 0
    last_report: bytes = b""
    registration_plan: BlueZGattRegistrationPlan | None = None

    async def register_application(self, application: GattApplicationModel | None = None) -> None:
        if application is not None:
            self.application = application
        self.registration_plan = build_bluez_gatt_registration_plan(self.application)
        self.registered = True
        log.info("dry-run GATT application registered paths=%d", len(self.application.object_paths()))

    async def unregister_application(self) -> None:
        self.registered = False
        log.info("dry-run GATT application unregistered")

    async def notify_keyboard_report(self, report: bytes) -> None:
        validate_keyboard_report_payload(report)
        if not self.registered:
            log.debug("dry-run GATT adapter dropped report while unregistered: %s", report.hex())
            return
        self.notifications += 1
        self.last_report = bytes(report)
        log.debug("dry-run GATT keyboard report notify: %s", report.hex())

    async def notify_mouse_report(self, report: bytes) -> None:
        validate_mouse_report_payload(report)
        if not self.registered:
            log.debug("dry-run GATT adapter dropped mouse report while unregistered: %s", report.hex())
            return
        self.notifications += 1
        self.last_report = bytes(report)
        log.debug("dry-run GATT mouse report notify: %s", report.hex())

    async def notify_consumer_report(self, report: bytes) -> None:
        validate_consumer_report_payload(report)
        if not self.registered:
            log.debug("dry-run GATT adapter dropped consumer report while unregistered: %s", report.hex())
            return
        self.notifications += 1
        self.last_report = bytes(report)
        log.debug("dry-run GATT consumer report notify: %s", report.hex())

    async def reset_keyboard_input(self) -> None:
        self.last_report = bytes(KEYBOARD_INPUT_REPORT.payload_size)
        log.info("dry-run GATT keyboard input reset to null report")

    async def reset_mouse_input(self) -> None:
        self.last_report = bytes(MOUSE_INPUT_REPORT.payload_size)
        log.info("dry-run GATT mouse input reset to null report")

    async def reset_consumer_input(self) -> None:
        self.last_report = bytes(CONSUMER_INPUT_REPORT.payload_size)
        log.info("dry-run GATT consumer input reset to null report")

    def status(self) -> GattAdapterStatus:
        plan = self.registration_plan
        return GattAdapterStatus(
            registered=self.registered,
            notifications=self.notifications,
            last_report_hex=self.last_report.hex(),
            notifying=False,
            adapter_kind="dry-run",
            available=True,
            app_path=self.application.path,
            object_count=len(plan.objects) if plan is not None else len(self.application.object_paths()),
            adapter_path=plan.adapter_path if plan is not None else "",
        )


@dataclass
class BlueZDbusGattRegistrationAdapter:
    """Opt-in BlueZ/D-Bus GATT application registration adapter.

    The implementation uses ``dbus-next`` when installed.  It exports a minimal
    ObjectManager-backed HID service model, registers it with BlueZ
    ``GattManager1``, and emits keyboard input report Value changes.

    It remains opt-in because development machines and fresh Pi installs may not
    have ``dbus-next`` or a running BlueZ GATT manager yet.
    """

    application: GattApplicationModel = field(default_factory=build_hid_gatt_application)
    registered: bool = False
    notifications: int = 0
    last_report: bytes = b""
    dependency_name: str = "dbus_next"
    bluez_service: str = "org.bluez"
    adapter_path: str = "/org/bluez/hci0"
    registration_plan: BlueZGattRegistrationPlan | None = None
    last_error: str = ""
    bus: Any | None = None
    _gatt_manager: Any | None = None
    _exported: list[tuple[str, Any]] = field(default_factory=list)
    _keyboard_characteristics: list[tuple[str, Any]] = field(default_factory=list)
    _mouse_characteristics: list[Any] = field(default_factory=list)
    _consumer_characteristics: list[Any] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return importlib.util.find_spec(self.dependency_name) is not None

    def _require_available(self) -> None:
        if not self.available:
            raise BlueZGattAdapterUnavailable(
                f"{self.dependency_name!r} is not installed; install it or use the dry-run GATT adapter"
            )

    async def register_application(self, application: GattApplicationModel | None = None) -> None:
        if application is not None:
            self.application = application
        self.registration_plan = build_bluez_gatt_registration_plan(self.application, adapter_path=self.adapter_path)
        self._require_available()
        if self.registered:
            return

        try:
            bus_mod, variant_cls = _import_dbus_next()
            bus = self.bus or await bus_mod.MessageBus(bus_type=bus_mod.BusType.SYSTEM).connect()
            bluez = await bus.introspect(self.bluez_service, self.adapter_path)
            adapter_obj = bus.get_proxy_object(self.bluez_service, self.adapter_path, bluez)
            gatt_manager = adapter_obj.get_interface("org.bluez.GattManager1")
            exported, keyboard_characteristics, mouse_characteristics, consumer_characteristics = _export_application(
                bus, self.application, variant_cls
            )
            await gatt_manager.call_register_application(self.application.path, {})
        except Exception as exc:
            await self._cleanup_after_failed_registration()
            if isinstance(exc, BlueZGattAdapterUnavailable):
                raise
            raise BlueZGattAdapterUnavailable(f"BlueZ GATT registration failed: {exc}") from exc

        self.bus = bus
        self._gatt_manager = gatt_manager
        self._exported = exported
        self._keyboard_characteristics = keyboard_characteristics
        self._mouse_characteristics = mouse_characteristics
        self._consumer_characteristics = consumer_characteristics
        self.registered = True
        self.last_error = ""
        log.info("BlueZ GATT application registered path=%s objects=%d", self.application.path, len(exported))

    async def unregister_application(self) -> None:
        if not self.registered:
            return
        self._require_available()
        if self._gatt_manager is not None:
            try:
                await self._gatt_manager.call_unregister_application(self.application.path)
            except Exception as exc:
                log.debug("BlueZ GATT unregister failed: %s", exc)
        self._unexport_objects()
        self.registered = False
        self._gatt_manager = None
        self._keyboard_characteristics = []
        self._mouse_characteristics = []
        self._consumer_characteristics = []
        log.info("BlueZ GATT application unregistered path=%s", self.application.path)

    async def notify_keyboard_report(self, report: bytes) -> None:
        validate_keyboard_report_payload(report)
        self._require_available()
        if not self.registered or not self._keyboard_characteristics:
            log.debug("BlueZ GATT adapter dropped report while unregistered: %s", report.hex())
            return
        for uuid, characteristic in self._keyboard_characteristics:
            if uuid == HID_REPORT_UUID:
                value = KEYBOARD_INPUT_REPORT.encode_value(report)
            else:
                value = bytes(report)
            characteristic.update_value(value)
        self.notifications += 1
        self.last_report = bytes(report)
        log.debug("BlueZ GATT keyboard report notify: %s", report.hex())

    async def notify_mouse_report(self, report: bytes) -> None:
        validate_mouse_report_payload(report)
        self._require_available()
        if not self.registered or not self._mouse_characteristics:
            log.debug("BlueZ GATT adapter dropped mouse report while unregistered: %s", report.hex())
            return
        value = MOUSE_INPUT_REPORT.encode_value(report)
        for characteristic in self._mouse_characteristics:
            characteristic.update_value(value)
        self.notifications += 1
        self.last_report = bytes(report)
        log.debug("BlueZ GATT mouse report notify: %s", report.hex())

    async def notify_consumer_report(self, report: bytes) -> None:
        validate_consumer_report_payload(report)
        self._require_available()
        if not self.registered or not self._consumer_characteristics:
            log.debug("BlueZ GATT adapter dropped consumer report while unregistered: %s", report.hex())
            return
        value = CONSUMER_INPUT_REPORT.encode_value(report)
        for characteristic in self._consumer_characteristics:
            characteristic.update_value(value)
        self.notifications += 1
        self.last_report = bytes(report)
        log.debug("BlueZ GATT consumer report notify: %s", report.hex())

    async def reset_keyboard_input(self) -> None:
        self._require_available()
        reset_count = 0
        notify_reset_count = 0
        for uuid, characteristic in self._keyboard_characteristics:
            value = _keyboard_input_null_value(uuid)
            if value is None:
                continue
            characteristic.update_value(value)
            if bool(getattr(characteristic, "notifying", False)):
                characteristic.notifying = False
                characteristic.emit_properties_changed({"Notifying": False})
                notify_reset_count += 1
            reset_count += 1
        if reset_count:
            self.last_report = bytes(KEYBOARD_INPUT_REPORT.payload_size)
            log.info(
                "BlueZ GATT keyboard input reset to null report characteristics=%d notify_reset=%d",
                reset_count,
                notify_reset_count,
            )

    async def reset_mouse_input(self) -> None:
        self._require_available()
        value = MOUSE_INPUT_REPORT.encode_value(bytes(MOUSE_INPUT_REPORT.payload_size))
        reset_count = 0
        for characteristic in self._mouse_characteristics:
            characteristic.update_value(value)
            reset_count += 1
        if reset_count:
            self.last_report = bytes(MOUSE_INPUT_REPORT.payload_size)
            log.info("BlueZ GATT mouse input reset to null report characteristics=%d", reset_count)

    async def reset_consumer_input(self) -> None:
        self._require_available()
        value = CONSUMER_INPUT_REPORT.encode_value(bytes(CONSUMER_INPUT_REPORT.payload_size))
        reset_count = 0
        for characteristic in self._consumer_characteristics:
            characteristic.update_value(value)
            reset_count += 1
        if reset_count:
            self.last_report = bytes(CONSUMER_INPUT_REPORT.payload_size)
            log.info("BlueZ GATT consumer input reset to null report characteristics=%d", reset_count)

    def status(self) -> GattAdapterStatus:
        plan = self.registration_plan
        dependency_error = "" if self.available else f"{self.dependency_name} is not installed"
        return GattAdapterStatus(
            registered=self.registered,
            notifications=self.notifications,
            last_report_hex=self.last_report.hex(),
            notifying=any(bool(getattr(characteristic, "notifying", False)) for _uuid, characteristic in self._keyboard_characteristics),
            adapter_kind="bluez-dbus",
            available=self.available,
            error=self.last_error or dependency_error,
            app_path=self.application.path,
            object_count=len(plan.objects) if plan is not None else len(self.application.object_paths()),
            adapter_path=self.adapter_path,
        )

    async def _cleanup_after_failed_registration(self) -> None:
        self._unexport_objects()
        self.registered = False
        self._gatt_manager = None
        self._keyboard_characteristics = []
        self._mouse_characteristics = []
        self._consumer_characteristics = []

    def _unexport_objects(self) -> None:
        bus = self.bus
        if bus is None:
            self._exported.clear()
            return
        for path, interface in reversed(self._exported):
            try:
                bus.unexport(path, interface)
            except Exception:
                pass
        self._exported.clear()


def build_gatt_adapter(kind: str | None = None) -> GattRegistrationAdapter:
    """Build a GATT adapter by kind.

    `dry-run` remains the safe default. `bluez-dbus` explicitly enables real
    BlueZ registration and reports missing dependencies before registration.
    """
    normalized = (kind or "dry-run").strip().lower().replace("_", "-")
    if normalized in {"", "dry-run", "dryrun", "mock"}:
        return DryRunGattRegistrationAdapter()
    if normalized in {"bluez", "bluez-dbus", "dbus"}:
        return BlueZDbusGattRegistrationAdapter()
    raise ValueError("unknown GATT adapter kind: %s" % kind)


def _import_dbus_next() -> tuple[Any, type]:
    """Import dbus-next lazily so normal tests do not require it."""
    try:
        from dbus_next import BusType, Variant
        from dbus_next.aio import MessageBus
        return SimpleNamespace(BusType=BusType, MessageBus=MessageBus), Variant
    except Exception as exc:
        raise BlueZGattAdapterUnavailable("'dbus_next' is not installed; install it or use the dry-run GATT adapter") from exc


def _import_dbus_service() -> tuple[type, Any, Any, Any]:
    try:
        from dbus_next.service import ServiceInterface, dbus_property, method
        from dbus_next.constants import PropertyAccess
        return ServiceInterface, dbus_property, method, PropertyAccess
    except Exception as exc:
        raise BlueZGattAdapterUnavailable("'dbus_next' service API is unavailable") from exc


def _variant_value(value: Any, variant_cls: type) -> Any:
    if isinstance(value, bool):
        return variant_cls("b", value)
    if isinstance(value, bytes):
        return variant_cls("ay", value)
    if isinstance(value, str):
        return variant_cls("s", value)
    if isinstance(value, tuple):
        return variant_cls("as", list(value))
    if isinstance(value, list):
        return variant_cls("as", value)
    return variant_cls("v", value)


def _model_properties(model: Any, variant_cls: type) -> dict[str, Any]:
    if isinstance(model, GattServiceModel):
        return {
            "UUID": _variant_value(model.uuid, variant_cls),
            "Primary": _variant_value(model.primary, variant_cls),
            "Includes": variant_cls("ao", []),
        }
    if isinstance(model, GattCharacteristicModel):
        return {
            "UUID": _variant_value(model.uuid, variant_cls),
            "Service": variant_cls("o", model.path.rsplit("/", 1)[0]),
            "Flags": _variant_value(model.flags, variant_cls),
            "Value": _variant_value(model.value, variant_cls),
            "Notifying": _variant_value(False, variant_cls),
        }
    if isinstance(model, GattDescriptorModel):
        return {
            "UUID": _variant_value(model.uuid, variant_cls),
            "Characteristic": variant_cls("o", model.path.rsplit("/", 1)[0]),
            "Flags": _variant_value(model.flags, variant_cls),
            "Value": _variant_value(model.value, variant_cls),
        }
    raise TypeError(f"unsupported GATT model: {type(model)!r}")


def _managed_objects(application: GattApplicationModel, variant_cls: type) -> dict[str, dict[str, dict[str, Any]]]:
    objects: dict[str, dict[str, dict[str, Any]]] = {}
    for service in application.services:
        objects[service.path] = {"org.bluez.GattService1": _model_properties(service, variant_cls)}
        for characteristic in service.characteristics:
            objects[characteristic.path] = {
                "org.bluez.GattCharacteristic1": _model_properties(characteristic, variant_cls)
            }
            for descriptor in characteristic.descriptors:
                objects[descriptor.path] = {
                    "org.bluez.GattDescriptor1": _model_properties(descriptor, variant_cls)
                }
    return objects


def _export_application(
    bus: Any,
    application: GattApplicationModel,
    variant_cls: type,
) -> tuple[list[tuple[str, Any]], list[tuple[str, Any]], list[Any], list[Any]]:
    """Export dbus-next service interfaces for the pure GATT application model."""
    ServiceInterface, dbus_property, method, PropertyAccess = _import_dbus_service()
    exported: list[tuple[str, Any]] = []

    class ObjectManagerInterface(ServiceInterface):  # type: ignore[misc, valid-type]
        def __init__(self) -> None:
            super().__init__("org.freedesktop.DBus.ObjectManager")

        @method()
        def GetManagedObjects(self) -> "a{oa{sa{sv}}}":
            return _managed_objects(application, variant_cls)

    class GattServiceInterface(ServiceInterface):  # type: ignore[misc, valid-type]
        def __init__(self, service: GattServiceModel) -> None:
            super().__init__("org.bluez.GattService1")
            self.service = service

        @dbus_property(access=PropertyAccess.READ)
        def UUID(self) -> "s":
            return self.service.uuid

        @dbus_property(access=PropertyAccess.READ)
        def Primary(self) -> "b":
            return self.service.primary

        @dbus_property(access=PropertyAccess.READ)
        def Includes(self) -> "ao":
            return []

    class GattCharacteristicInterface(ServiceInterface):  # type: ignore[misc, valid-type]
        def __init__(self, characteristic: GattCharacteristicModel) -> None:
            super().__init__("org.bluez.GattCharacteristic1")
            self.characteristic = characteristic
            self.value = bytes(characteristic.value)
            self.notifying = False

        @dbus_property(access=PropertyAccess.READ)
        def UUID(self) -> "s":
            return self.characteristic.uuid

        @dbus_property(access=PropertyAccess.READ)
        def Service(self) -> "o":
            return self.characteristic.path.rsplit("/", 1)[0]

        @dbus_property(access=PropertyAccess.READ)
        def Flags(self) -> "as":
            return list(self.characteristic.flags)

        @dbus_property(access=PropertyAccess.READ)
        def Value(self) -> "ay":
            return self.value

        @dbus_property(access=PropertyAccess.READ)
        def Notifying(self) -> "b":
            return self.notifying

        @method()
        def ReadValue(self, _options: "a{sv}") -> "ay":
            _log_gatt_value(
                "BlueZ GATT ReadValue characteristic=%s uuid=%s len=%d value=%s",
                self.characteristic.path,
                self.characteristic.uuid,
                len(self.value),
                self.value.hex(),
            )
            return self.value

        @method()
        def WriteValue(self, value: "ay", _options: "a{sv}"):
            self.value = bytes(value)
            _log_gatt_value(
                "BlueZ GATT WriteValue characteristic=%s uuid=%s len=%d value=%s",
                self.characteristic.path,
                self.characteristic.uuid,
                len(self.value),
                self.value.hex(),
            )
            self.emit_properties_changed({"Value": self.value})

        @method()
        def StartNotify(self):
            reset_value = _input_null_value(self.characteristic)
            if reset_value is not None:
                self.value = reset_value
                self.emit_properties_changed({"Value": self.value})
            self.notifying = True
            self.emit_properties_changed({"Notifying": self.notifying})
            log.info(
                "BlueZ GATT notify started characteristic=%s uuid=%s len=%d reset_keyboard_null=%s",
                self.characteristic.path,
                self.characteristic.uuid,
                len(self.value),
                reset_value is not None,
            )

        @method()
        def StopNotify(self):
            self.notifying = False
            reset_value = _input_null_value(self.characteristic)
            if reset_value is not None:
                self.value = reset_value
                self.emit_properties_changed({"Value": self.value})
            self.emit_properties_changed({"Notifying": self.notifying})
            log.info(
                "BlueZ GATT notify stopped characteristic=%s uuid=%s reset_keyboard_null=%s",
                self.characteristic.path,
                self.characteristic.uuid,
                reset_value is not None,
            )

        def update_value(self, value: bytes) -> None:
            self.value = bytes(value)
            if self.notifying:
                _log_gatt_value(
                    "BlueZ GATT notify value characteristic=%s uuid=%s len=%d value=%s",
                    self.characteristic.path,
                    self.characteristic.uuid,
                    len(self.value),
                    self.value.hex(),
                )
                self.emit_properties_changed({"Value": self.value})

    class GattDescriptorInterface(ServiceInterface):  # type: ignore[misc, valid-type]
        def __init__(self, descriptor: GattDescriptorModel) -> None:
            super().__init__("org.bluez.GattDescriptor1")
            self.descriptor = descriptor
            self.value = bytes(descriptor.value)

        @dbus_property(access=PropertyAccess.READ)
        def UUID(self) -> "s":
            return self.descriptor.uuid

        @dbus_property(access=PropertyAccess.READ)
        def Characteristic(self) -> "o":
            return self.descriptor.path.rsplit("/", 1)[0]

        @dbus_property(access=PropertyAccess.READ)
        def Flags(self) -> "as":
            return list(self.descriptor.flags)

        @dbus_property(access=PropertyAccess.READ)
        def Value(self) -> "ay":
            return self.value

        @method()
        def ReadValue(self, _options: "a{sv}") -> "ay":
            _log_gatt_value(
                "BlueZ GATT ReadValue descriptor=%s uuid=%s len=%d value=%s",
                self.descriptor.path,
                self.descriptor.uuid,
                len(self.value),
                self.value.hex(),
            )
            return self.value

        @method()
        def WriteValue(self, value: "ay", _options: "a{sv}"):
            self.value = bytes(value)
            _log_gatt_value(
                "BlueZ GATT WriteValue descriptor=%s uuid=%s len=%d value=%s",
                self.descriptor.path,
                self.descriptor.uuid,
                len(self.value),
                self.value.hex(),
            )
            self.emit_properties_changed({"Value": self.value})

    app_iface = ObjectManagerInterface()
    bus.export(application.path, app_iface)
    exported.append((application.path, app_iface))

    keyboard_characteristics: list[tuple[str, Any]] = []
    mouse_characteristics: list[Any] = []
    consumer_characteristics: list[Any] = []
    for service in application.services:
        service_iface = GattServiceInterface(service)
        bus.export(service.path, service_iface)
        exported.append((service.path, service_iface))
        for characteristic in service.characteristics:
            char_iface = GattCharacteristicInterface(characteristic)
            bus.export(characteristic.path, char_iface)
            exported.append((characteristic.path, char_iface))
            if characteristic.uuid == HID_REPORT_UUID and "notify" in characteristic.flags:
                report_reference = _report_reference_value(characteristic)
                if report_reference == KEYBOARD_INPUT_REPORT.report_reference:
                    keyboard_characteristics.append((characteristic.uuid, char_iface))
                elif report_reference == MOUSE_INPUT_REPORT.report_reference:
                    mouse_characteristics.append(char_iface)
                elif report_reference == CONSUMER_INPUT_REPORT.report_reference:
                    consumer_characteristics.append(char_iface)
            elif characteristic.uuid == BOOT_KEYBOARD_INPUT_REPORT_UUID and "notify" in characteristic.flags:
                keyboard_characteristics.append((characteristic.uuid, char_iface))
            for descriptor in characteristic.descriptors:
                desc_iface = GattDescriptorInterface(descriptor)
                bus.export(descriptor.path, desc_iface)
                exported.append((descriptor.path, desc_iface))

    if not keyboard_characteristics:
        raise BlueZGattAdapterUnavailable("GATT application has no notify-capable keyboard characteristic")
    if not mouse_characteristics:
        raise BlueZGattAdapterUnavailable("GATT application has no notify-capable mouse characteristic")
    return exported, keyboard_characteristics, mouse_characteristics, consumer_characteristics
