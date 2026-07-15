#!/usr/bin/env python3
"""Regression tests for BLE advertising adapter boundary."""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from btd.advertising import (  # noqa: E402
    BlueZDbusAdvertisingAdapter,
    BlueZAdvertisingAdapterUnavailable,
    DEFAULT_ADVERTISEMENT_PATH,
    DryRunAdvertisingAdapter,
    AdvertisementModel,
    build_advertising_adapter,
    build_keyboard_advertisement,
    _make_advertisement_interface,
)
from btd.gatt_hid import HID_SERVICE_UUID  # noqa: E402


async def main_async() -> None:
    advertisement = build_keyboard_advertisement("<keyboard-host>")
    assert DEFAULT_ADVERTISEMENT_PATH == "/org/hidloom/btd/advertisement0000"
    assert advertisement.path == DEFAULT_ADVERTISEMENT_PATH
    assert advertisement.local_name == "<keyboard-host>"
    assert advertisement.service_uuids == (HID_SERVICE_UUID,)
    assert advertisement.appearance == 0x03C1
    assert advertisement.advertisement_type == "peripheral"
    assert advertisement.discoverable is True

    dry = DryRunAdvertisingAdapter()
    await dry.register_advertisement(advertisement)
    status = dry.status()
    assert status.registered is True
    assert status.adapter_kind == "dry-run"
    await dry.unregister_advertisement()
    assert dry.status().registered is False

    assert isinstance(build_advertising_adapter(), DryRunAdvertisingAdapter)
    assert isinstance(build_advertising_adapter("dry-run"), DryRunAdvertisingAdapter)
    assert isinstance(build_advertising_adapter("bluez-dbus"), BlueZDbusAdvertisingAdapter)

    missing = BlueZDbusAdvertisingAdapter(dependency_name="definitely_missing_dbus_module")
    try:
        await missing.register_advertisement(advertisement)
    except BlueZAdvertisingAdapterUnavailable as exc:
        assert "not installed" in str(exc)
    else:
        raise AssertionError("missing D-Bus dependency should fail explicitly")

    try:
        build_advertising_adapter("bad")
    except ValueError as exc:
        assert "unknown advertising adapter kind" in str(exc)
    else:
        raise AssertionError("invalid advertising adapter should fail")

    # Constructing the dbus-next service interface should not touch the bus.
    if importlib.util.find_spec("dbus_next") is not None:
        iface = _make_advertisement_interface(AdvertisementModel(local_name="kbd"))
        assert iface.Type == "peripheral"
        assert iface.ServiceUUIDs == [HID_SERVICE_UUID]
        assert iface.LocalName == "kbd"
        assert iface.Appearance == 0x03C1
        assert "tx-power" in iface.Includes
        assert iface.Discoverable is True

    print("ok: btd BLE advertising adapter")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
