#!/usr/bin/env python3
"""Generate a Windows .reg file for per-device keyboard layout override."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


LAYOUTS = {
    "jp_106": (7, 2),
    "us_101": (7, 0),
}


def _normalize_instance_path(value: str) -> str:
    value = value.strip().strip('"')
    prefixes = (
        "HKEY_LOCAL_MACHINE\\SYSTEM\\CurrentControlSet\\Enum\\",
        "HKLM\\SYSTEM\\CurrentControlSet\\Enum\\",
    )
    for prefix in prefixes:
        if value.upper().startswith(prefix.upper()):
            value = value[len(prefix):]
            break
    suffix = r"\Device Parameters"
    if value.upper().endswith(suffix.upper()):
        value = value[: -len(suffix)]
    value = value.strip("\\")
    if not value:
        raise ValueError("device instance path is empty")
    if "\\Device Parameters".upper() in value.upper():
        raise ValueError("device instance path contains an unexpected Device Parameters segment")
    return value


def _reg_text(instance_path: str, layout: str) -> str:
    keyboard_type, keyboard_subtype = LAYOUTS[layout]
    path = _normalize_instance_path(instance_path)
    return (
        "Windows Registry Editor Version 5.00\r\n"
        "\r\n"
        f"[HKEY_LOCAL_MACHINE\\SYSTEM\\CurrentControlSet\\Enum\\{path}\\Device Parameters]\r\n"
        f'"OverrideKeyboardType"=dword:{keyboard_type:08x}\r\n'
        f'"OverrideKeyboardSubtype"=dword:{keyboard_subtype:08x}\r\n'
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "instance_path",
        help=r"Device Manager instance path, e.g. HID\VID_1D6B&PID_0105&MI_02\...",
    )
    parser.add_argument("--layout", choices=sorted(LAYOUTS), default="jp_106")
    parser.add_argument("--output", type=Path, help="write UTF-16 LE .reg file instead of printing text")
    args = parser.parse_args()

    try:
        text = _reg_text(args.instance_path, args.layout)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    if args.output:
        args.output.write_bytes(("\ufeff" + text).encode("utf-16le"))
        return
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
