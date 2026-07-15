"""BLE advertising adapter boundary for the btd BlueZ backend."""
from __future__ import annotations

import importlib.util
import logging
import socket
from dataclasses import dataclass
from typing import Any, Protocol

from .gatt_adapter import BlueZGattAdapterUnavailable, _import_dbus_next, _import_dbus_service
from .gatt_hid import HID_SERVICE_UUID

log = logging.getLogger("btd.advertising")

DEFAULT_ADVERTISEMENT_PATH = "/org/hidloom/btd/advertisement0000"
DEFAULT_APPEARANCE_KEYBOARD = 0x03C1


class AdvertisingAdapter(Protocol):
    async def register_advertisement(self, advertisement: "AdvertisementModel") -> None:
        """Register a BLE advertisement."""

    async def unregister_advertisement(self) -> None:
        """Unregister a BLE advertisement."""


@dataclass(frozen=True)
class AdvertisementModel:
    path: str = DEFAULT_ADVERTISEMENT_PATH
    local_name: str = ""
    service_uuids: tuple[str, ...] = (HID_SERVICE_UUID,)
    appearance: int = DEFAULT_APPEARANCE_KEYBOARD
    includes: tuple[str, ...] = ("tx-power",)
    advertisement_type: str = "peripheral"
    discoverable: bool = True


@dataclass(frozen=True)
class AdvertisingStatus:
    registered: bool
    adapter_kind: str = "dry-run"
    available: bool = True
    error: str = ""


def build_keyboard_advertisement(local_name: str | None = None) -> AdvertisementModel:
    name = (local_name or socket.gethostname() or "cqa02303v5").strip()
    return AdvertisementModel(local_name=name[:20])


@dataclass
class DryRunAdvertisingAdapter:
    advertisement: AdvertisementModel = AdvertisementModel()
    registered: bool = False

    async def register_advertisement(self, advertisement: AdvertisementModel | None = None) -> None:
        if advertisement is not None:
            self.advertisement = advertisement
        self.registered = True
        log.info("dry-run advertisement registered path=%s name=%s", self.advertisement.path, self.advertisement.local_name)

    async def unregister_advertisement(self) -> None:
        self.registered = False
        log.info("dry-run advertisement unregistered")

    def status(self) -> AdvertisingStatus:
        return AdvertisingStatus(registered=self.registered, adapter_kind="dry-run")


class BlueZAdvertisingAdapterUnavailable(RuntimeError):
    """Raised when the BlueZ advertising adapter cannot be used."""


@dataclass
class BlueZDbusAdvertisingAdapter:
    advertisement: AdvertisementModel = AdvertisementModel()
    registered: bool = False
    dependency_name: str = "dbus_next"
    bluez_service: str = "org.bluez"
    adapter_path: str = "/org/bluez/hci0"
    bus: Any | None = None
    _advertising_manager: Any | None = None
    _advertisement_interface: Any | None = None

    @property
    def available(self) -> bool:
        return importlib.util.find_spec(self.dependency_name) is not None

    def _require_available(self) -> None:
        if not self.available:
            raise BlueZAdvertisingAdapterUnavailable(
                f"{self.dependency_name!r} is not installed; install python3-dbus-next or use dry-run advertising"
            )

    async def register_advertisement(self, advertisement: AdvertisementModel | None = None) -> None:
        if advertisement is not None:
            self.advertisement = advertisement
        self._require_available()
        if self.registered:
            return
        try:
            bus_mod, _variant_cls = _import_dbus_next()
            bus = self.bus or await bus_mod.MessageBus(bus_type=bus_mod.BusType.SYSTEM).connect()
            bluez = await bus.introspect(self.bluez_service, self.adapter_path)
            adapter_obj = bus.get_proxy_object(self.bluez_service, self.adapter_path, bluez)
            advertising_manager = adapter_obj.get_interface("org.bluez.LEAdvertisingManager1")
            advertisement_interface = _make_advertisement_interface(self.advertisement)
            bus.export(self.advertisement.path, advertisement_interface)
            await advertising_manager.call_register_advertisement(self.advertisement.path, {})
        except Exception as exc:
            self._unexport()
            if isinstance(exc, (BlueZGattAdapterUnavailable, BlueZAdvertisingAdapterUnavailable)):
                raise
            raise BlueZAdvertisingAdapterUnavailable(f"BlueZ advertisement registration failed: {exc}") from exc
        self.bus = bus
        self._advertising_manager = advertising_manager
        self._advertisement_interface = advertisement_interface
        self.registered = True
        log.info("BlueZ advertisement registered path=%s name=%s", self.advertisement.path, self.advertisement.local_name)

    async def unregister_advertisement(self) -> None:
        if not self.registered:
            return
        if self._advertising_manager is not None:
            try:
                await self._advertising_manager.call_unregister_advertisement(self.advertisement.path)
            except Exception as exc:
                log.debug("BlueZ advertisement unregister failed: %s", exc)
        self._unexport()
        self.registered = False
        self._advertising_manager = None
        self._advertisement_interface = None
        log.info("BlueZ advertisement unregistered path=%s", self.advertisement.path)

    def status(self) -> AdvertisingStatus:
        return AdvertisingStatus(
            registered=self.registered,
            adapter_kind="bluez-dbus",
            available=self.available,
            error="" if self.available else f"{self.dependency_name} is not installed",
        )

    def _unexport(self) -> None:
        if self.bus is not None and self._advertisement_interface is not None:
            try:
                self.bus.unexport(self.advertisement.path, self._advertisement_interface)
            except Exception:
                pass


def build_advertising_adapter(kind: str | None = None) -> AdvertisingAdapter:
    normalized = (kind or "dry-run").strip().lower().replace("_", "-")
    if normalized in {"", "dry-run", "dryrun", "mock"}:
        return DryRunAdvertisingAdapter()
    if normalized in {"bluez", "bluez-dbus", "dbus"}:
        return BlueZDbusAdvertisingAdapter()
    raise ValueError("unknown advertising adapter kind: %s" % kind)


def _make_advertisement_interface(advertisement: AdvertisementModel) -> Any:
    ServiceInterface, dbus_property, method, PropertyAccess = _import_dbus_service()

    class AdvertisementInterface(ServiceInterface):  # type: ignore[misc, valid-type]
        def __init__(self) -> None:
            super().__init__("org.bluez.LEAdvertisement1")

        @dbus_property(access=PropertyAccess.READ)
        def Type(self) -> "s":
            return advertisement.advertisement_type

        @dbus_property(access=PropertyAccess.READ)
        def ServiceUUIDs(self) -> "as":
            return list(advertisement.service_uuids)

        @dbus_property(access=PropertyAccess.READ)
        def LocalName(self) -> "s":
            return advertisement.local_name

        @dbus_property(access=PropertyAccess.READ)
        def Appearance(self) -> "q":
            return advertisement.appearance

        @dbus_property(access=PropertyAccess.READ)
        def Includes(self) -> "as":
            return list(advertisement.includes)

        @dbus_property(access=PropertyAccess.READ)
        def Discoverable(self) -> "b":
            return bool(advertisement.discoverable)

        @method()
        def Release(self):
            log.info("BlueZ advertisement released path=%s", advertisement.path)

    return AdvertisementInterface()
