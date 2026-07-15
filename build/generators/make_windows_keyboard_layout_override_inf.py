#!/usr/bin/env python3
"""Generate an experimental Windows extension INF for keyboard layout override."""
from __future__ import annotations

import argparse
import re
import sys
import uuid
from datetime import date
from pathlib import Path


LAYOUTS = {
    "jp_106": (7, 2, "JP 106/109"),
    "us_101": (7, 0, "US 101/102"),
}


def _normalize_hardware_id(value: str) -> str:
    value = value.strip().strip('"')
    value = value.replace("/", "\\")
    if "\\" not in value:
        raise ValueError("hardware ID must look like HID\\VID_....")
    if value.upper().startswith(("HKLM\\", "HKEY_LOCAL_MACHINE\\")):
        raise ValueError("use a Hardware Ids value, not a registry path")
    if "\\DEVICE PARAMETERS" in value.upper():
        raise ValueError("use a Hardware Ids value, not a device instance path")
    return value


def _normalize_guid(value: str) -> str:
    value = value.strip()
    if not value:
        return str(uuid.uuid4()).upper()
    value = value.strip("{}")
    return str(uuid.UUID(value)).upper()


def _driver_ver(value: str | None) -> str:
    if value:
        return value
    today = date.today()
    return f"{today.month:02d}/{today.day:02d}/{today.year},1.0.0.0"


def _inf_text(
    *,
    hardware_id: str,
    layout: str,
    extension_id: str,
    driver_ver: str,
    provider: str,
    manufacturer: str,
    device_desc: str,
    catalog_file: str,
) -> str:
    keyboard_type, keyboard_subtype, layout_label = LAYOUTS[layout]
    hardware_id = _normalize_hardware_id(hardware_id)
    extension_id = _normalize_guid(extension_id)
    provider_key = "ProviderName"
    manufacturer_key = "ManufacturerName"
    device_key = "DeviceExtensionDesc"
    lines = [
        "; Experimental extension INF for HIDloom keyboard layout override.",
        "; Validate with infverif/inf2cat and sign the catalog before normal installation.",
        "[Version]",
        'Signature="$WINDOWS NT$"',
        "Class=Extension",
        "ClassGuid={e2f84ce7-8efa-411c-aa69-97454ca4cb57}",
        f"Provider=%{provider_key}%",
        f"ExtensionId={{{extension_id}}}",
        f"DriverVer={driver_ver}",
        f"CatalogFile={catalog_file}",
        "PnpLockdown=1",
        "",
        "[Manufacturer]",
        f"%{manufacturer_key}%=CqaDeviceExtensions,NTamd64",
        "",
        "[CqaDeviceExtensions.NTamd64]",
        f"%{device_key}%=CqaKeyboardLayout_Install, {hardware_id}",
        "",
        "[CqaKeyboardLayout_Install]",
        "; No base driver replacement. The in-box HID keyboard driver remains the base driver.",
        "",
        "[CqaKeyboardLayout_Install.HW]",
        "AddReg=CqaKeyboardLayout_AddReg",
        "",
        "[CqaKeyboardLayout_AddReg]",
        f"HKR,,OverrideKeyboardType,0x00010001,{keyboard_type}",
        f"HKR,,OverrideKeyboardSubtype,0x00010001,{keyboard_subtype}",
        "",
        "[Strings]",
        f'{provider_key}="{provider}"',
        f'{manufacturer_key}="{manufacturer}"',
        f'{device_key}="{device_desc} ({layout_label})"',
        "",
    ]
    return "\r\n".join(lines)


def _default_catalog_name(output: Path | None) -> str:
    if output and output.suffix.lower() == ".inf":
        return output.with_suffix(".cat").name
    return "hidloom-keyboard-layout-override.cat"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "hardware_id",
        help=r"Device Manager Hardware Ids value, e.g. HID\VID_1D6B&PID_0105&MI_02",
    )
    parser.add_argument("--layout", choices=sorted(LAYOUTS), default="jp_106")
    parser.add_argument("--extension-id", default="", help="stable GUID without or with braces; generated if omitted")
    parser.add_argument("--driver-ver", help="DriverVer value such as 06/11/2026,1.0.0.0")
    parser.add_argument("--provider", default="HIDloom Project")
    parser.add_argument("--manufacturer", default="HIDloom Project")
    parser.add_argument("--device-desc", default="HIDloom US Sub Keyboard Layout Override")
    parser.add_argument("--catalog-file", help="CatalogFile entry; defaults to output .cat name")
    parser.add_argument("--output", type=Path, help="write INF file instead of printing text")
    args = parser.parse_args()

    try:
        text = _inf_text(
            hardware_id=args.hardware_id,
            layout=args.layout,
            extension_id=args.extension_id,
            driver_ver=_driver_ver(args.driver_ver),
            provider=args.provider,
            manufacturer=args.manufacturer,
            device_desc=args.device_desc,
            catalog_file=args.catalog_file or _default_catalog_name(args.output),
        )
    except (ValueError, KeyError) as exc:
        raise SystemExit(str(exc)) from exc

    if args.output:
        args.output.write_text(text, encoding="utf-8", newline="")
        return
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
