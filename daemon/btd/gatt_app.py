"""Side-effect-free BLE HID GATT application model.

This module does not perform D-Bus calls. It describes the object paths,
services, characteristics, descriptors, and initial values exported by the
BlueZ D-Bus registration adapter.

Design constraints:
- No D-Bus calls here.
- No packet/framing change for logicd -> btd.
- Keyboard Input Report payload remains raw fixed 8-byte KeyboardReport.report.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .gatt_hid import (
    BATTERY_LEVEL_UUID,
    BATTERY_SERVICE_UUID,
    BOOT_KEYBOARD_INPUT_REPORT_UUID,
    BOOT_KEYBOARD_OUTPUT_REPORT_UUID,
    CLIENT_CHARACTERISTIC_CONFIGURATION_UUID,
    CONSUMER_INPUT_REPORT,
    DEFAULT_BATTERY_LEVEL,
    DEVICE_INFORMATION_SERVICE_UUID,
    HID_CONTROL_POINT_UUID,
    HID_INFORMATION,
    HID_INFORMATION_UUID,
    HID_PROTOCOL_MODE_UUID,
    HID_REPORT_MAP_UUID,
    HID_REPORT_UUID,
    HID_SERVICE_UUID,
    KEYBOARD_INPUT_REPORT,
    KEYBOARD_OUTPUT_REPORT,
    MANUFACTURER_NAME,
    MANUFACTURER_NAME_UUID,
    MODEL_NUMBER,
    MODEL_NUMBER_UUID,
    MOUSE_INPUT_REPORT,
    PNP_ID,
    PNP_ID_UUID,
    REPORT_REFERENCE_DESCRIPTOR_UUID,
    hid_report_map,
)

DEFAULT_APP_PATH = "/org/hidloom/btd"
HID_SERVICE_INDEX = 0
DEVICE_INFORMATION_SERVICE_INDEX = 1
BATTERY_SERVICE_INDEX = 2
GATT_SECURITY_NONE = "none"
GATT_SECURITY_ENCRYPT = "encrypt"
GATT_SECURITY_AUTHENTICATED = "authenticated"
GATT_SECURITY_MODES = (GATT_SECURITY_NONE, GATT_SECURITY_ENCRYPT, GATT_SECURITY_AUTHENTICATED)


@dataclass(frozen=True)
class GattDescriptorModel:
    path: str
    uuid: str
    flags: tuple[str, ...]
    value: bytes = b""


@dataclass(frozen=True)
class GattCharacteristicModel:
    path: str
    uuid: str
    flags: tuple[str, ...]
    value: bytes = b""
    descriptors: tuple[GattDescriptorModel, ...] = ()


@dataclass(frozen=True)
class GattServiceModel:
    path: str
    uuid: str
    primary: bool
    characteristics: tuple[GattCharacteristicModel, ...]


@dataclass(frozen=True)
class GattApplicationModel:
    path: str = DEFAULT_APP_PATH
    services: tuple[GattServiceModel, ...] = field(default_factory=tuple)

    def object_paths(self) -> tuple[str, ...]:
        paths: list[str] = [self.path]
        for service in self.services:
            paths.append(service.path)
            for characteristic in service.characteristics:
                paths.append(characteristic.path)
                for descriptor in characteristic.descriptors:
                    paths.append(descriptor.path)
        return tuple(paths)


def _char_path(service_path: str, index: int) -> str:
    return f"{service_path}/char{index:04d}"


def _desc_path(characteristic_path: str, index: int) -> str:
    return f"{characteristic_path}/desc{index:04d}"


def build_hid_gatt_application(
    app_path: str = DEFAULT_APP_PATH,
    *,
    security: str = GATT_SECURITY_NONE,
    include_consumer: bool = False,
) -> GattApplicationModel:
    """Build the BLE HID model exported by the BlueZ registration adapter."""
    service_path = f"{app_path}/service{HID_SERVICE_INDEX:04d}"
    security = normalize_gatt_security(security)

    hid_information = GattCharacteristicModel(
        path=_char_path(service_path, 0),
        uuid=HID_INFORMATION_UUID,
        flags=_secure_flags(("read",), security),
        value=HID_INFORMATION,
    )
    report_map = GattCharacteristicModel(
        path=_char_path(service_path, 1),
        uuid=HID_REPORT_MAP_UUID,
        flags=_secure_flags(("read",), security),
        value=hid_report_map(include_consumer=include_consumer),
    )
    control_point = GattCharacteristicModel(
        path=_char_path(service_path, 2),
        uuid=HID_CONTROL_POINT_UUID,
        flags=_secure_flags(("write-without-response",), security),
        value=b"",
    )
    protocol_mode = GattCharacteristicModel(
        path=_char_path(service_path, 3),
        uuid=HID_PROTOCOL_MODE_UUID,
        flags=_secure_flags(("read", "write-without-response"), security),
        # 1 = Report Protocol mode. Boot protocol mode is not exposed.
        value=bytes([0x01]),
    )

    input_report_path = _char_path(service_path, 4)
    input_report = GattCharacteristicModel(
        path=input_report_path,
        uuid=HID_REPORT_UUID,
        flags=_secure_flags(("read", "notify"), security),
        value=KEYBOARD_INPUT_REPORT.encode_value(bytes(KEYBOARD_INPUT_REPORT.payload_size)),
        descriptors=(
            GattDescriptorModel(
                path=_desc_path(input_report_path, 0),
                uuid=REPORT_REFERENCE_DESCRIPTOR_UUID,
                flags=("read",),
                value=KEYBOARD_INPUT_REPORT.report_reference,
            ),
            GattDescriptorModel(
                path=_desc_path(input_report_path, 1),
                uuid=CLIENT_CHARACTERISTIC_CONFIGURATION_UUID,
                flags=("read", "write"),
                value=bytes([0x00, 0x00]),
            ),
        ),
    )

    output_report_path = _char_path(service_path, 5)
    output_report = GattCharacteristicModel(
        path=output_report_path,
        uuid=HID_REPORT_UUID,
        flags=_secure_flags(("read", "write", "write-without-response"), security),
        value=KEYBOARD_OUTPUT_REPORT.encode_value(bytes(KEYBOARD_OUTPUT_REPORT.payload_size)),
        descriptors=(
            GattDescriptorModel(
                path=_desc_path(output_report_path, 0),
                uuid=REPORT_REFERENCE_DESCRIPTOR_UUID,
                flags=("read",),
                value=KEYBOARD_OUTPUT_REPORT.report_reference,
            ),
        ),
    )

    mouse_report_path = _char_path(service_path, 6)
    mouse_report = GattCharacteristicModel(
        path=mouse_report_path,
        uuid=HID_REPORT_UUID,
        flags=_secure_flags(("read", "notify"), security),
        value=MOUSE_INPUT_REPORT.encode_value(bytes(MOUSE_INPUT_REPORT.payload_size)),
        descriptors=(
            GattDescriptorModel(
                path=_desc_path(mouse_report_path, 0),
                uuid=REPORT_REFERENCE_DESCRIPTOR_UUID,
                flags=("read",),
                value=MOUSE_INPUT_REPORT.report_reference,
            ),
            GattDescriptorModel(
                path=_desc_path(mouse_report_path, 1),
                uuid=CLIENT_CHARACTERISTIC_CONFIGURATION_UUID,
                flags=("read", "write"),
                value=bytes([0x00, 0x00]),
            ),
        ),
    )

    consumer_report_path = _char_path(service_path, 7)
    consumer_report = GattCharacteristicModel(
        path=consumer_report_path,
        uuid=HID_REPORT_UUID,
        flags=_secure_flags(("read", "notify"), security),
        value=CONSUMER_INPUT_REPORT.encode_value(bytes(CONSUMER_INPUT_REPORT.payload_size)),
        descriptors=(
            GattDescriptorModel(
                path=_desc_path(consumer_report_path, 0),
                uuid=REPORT_REFERENCE_DESCRIPTOR_UUID,
                flags=("read",),
                value=CONSUMER_INPUT_REPORT.report_reference,
            ),
            GattDescriptorModel(
                path=_desc_path(consumer_report_path, 1),
                uuid=CLIENT_CHARACTERISTIC_CONFIGURATION_UUID,
                flags=("read", "write"),
                value=bytes([0x00, 0x00]),
            ),
        ),
    )

    boot_input_report_path = _char_path(service_path, 8 if include_consumer else 7)
    boot_input_report = GattCharacteristicModel(
        path=boot_input_report_path,
        uuid=BOOT_KEYBOARD_INPUT_REPORT_UUID,
        flags=_secure_flags(("read", "notify"), security),
        value=bytes(KEYBOARD_INPUT_REPORT.payload_size),
        descriptors=(
            GattDescriptorModel(
                path=_desc_path(boot_input_report_path, 0),
                uuid=CLIENT_CHARACTERISTIC_CONFIGURATION_UUID,
                flags=("read", "write"),
                value=bytes([0x00, 0x00]),
            ),
        ),
    )

    boot_output_report = GattCharacteristicModel(
        path=_char_path(service_path, 9 if include_consumer else 8),
        uuid=BOOT_KEYBOARD_OUTPUT_REPORT_UUID,
        flags=_secure_flags(("read", "write", "write-without-response"), security),
        value=bytes(KEYBOARD_OUTPUT_REPORT.payload_size),
    )

    report_characteristics = [input_report, output_report, mouse_report]
    if include_consumer:
        report_characteristics.append(consumer_report)

    hid_service = GattServiceModel(
        path=service_path,
        uuid=HID_SERVICE_UUID,
        primary=True,
        characteristics=(
            hid_information,
            report_map,
            control_point,
            protocol_mode,
            *report_characteristics,
            boot_input_report,
            boot_output_report,
        ),
    )

    device_information_path = f"{app_path}/service{DEVICE_INFORMATION_SERVICE_INDEX:04d}"
    device_information_service = GattServiceModel(
        path=device_information_path,
        uuid=DEVICE_INFORMATION_SERVICE_UUID,
        primary=True,
        characteristics=(
            GattCharacteristicModel(
                path=_char_path(device_information_path, 0),
                uuid=MANUFACTURER_NAME_UUID,
                flags=("read",),
                value=MANUFACTURER_NAME,
            ),
            GattCharacteristicModel(
                path=_char_path(device_information_path, 1),
                uuid=MODEL_NUMBER_UUID,
                flags=("read",),
                value=MODEL_NUMBER,
            ),
            GattCharacteristicModel(
                path=_char_path(device_information_path, 2),
                uuid=PNP_ID_UUID,
                flags=("read",),
                value=PNP_ID,
            ),
        ),
    )

    battery_path = f"{app_path}/service{BATTERY_SERVICE_INDEX:04d}"
    battery_level_path = _char_path(battery_path, 0)
    battery_service = GattServiceModel(
        path=battery_path,
        uuid=BATTERY_SERVICE_UUID,
        primary=True,
        characteristics=(
            GattCharacteristicModel(
                path=battery_level_path,
                uuid=BATTERY_LEVEL_UUID,
                flags=("read", "notify"),
                value=DEFAULT_BATTERY_LEVEL,
                descriptors=(
                    GattDescriptorModel(
                        path=_desc_path(battery_level_path, 0),
                        uuid=CLIENT_CHARACTERISTIC_CONFIGURATION_UUID,
                        flags=("read", "write"),
                        value=bytes([0x00, 0x00]),
                    ),
                ),
            ),
        ),
    )
    return GattApplicationModel(path=app_path, services=(hid_service, device_information_service, battery_service))


def normalize_gatt_security(value: str | None) -> str:
    normalized = (value or GATT_SECURITY_NONE).strip().lower()
    if normalized not in GATT_SECURITY_MODES:
        allowed = ", ".join(GATT_SECURITY_MODES)
        raise ValueError(f"invalid GATT security mode {value!r}; expected one of: {allowed}")
    return normalized


def _secure_flags(flags: tuple[str, ...], security: str) -> tuple[str, ...]:
    if security == GATT_SECURITY_NONE:
        return flags
    if security == GATT_SECURITY_ENCRYPT:
        read_flag = "encrypt-read"
        write_flag = "encrypt-write"
        notify_flag = "encrypt-notify"
    elif security == GATT_SECURITY_AUTHENTICATED:
        read_flag = "encrypt-authenticated-read"
        write_flag = "encrypt-authenticated-write"
        notify_flag = "encrypt-authenticated-notify"
    else:
        raise ValueError(f"invalid GATT security mode {security!r}")

    secured: list[str] = []
    for flag in flags:
        if flag == "read":
            secured.append(read_flag)
        elif flag in {"write", "write-without-response"}:
            secured.append(write_flag)
        elif flag == "notify":
            secured.extend(("notify", notify_flag))
        else:
            secured.append(flag)
    return tuple(dict.fromkeys(secured))
