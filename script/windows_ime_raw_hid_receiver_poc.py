#!/usr/bin/env python3
"""Display Windows IME Raw HID multiplex frames from the host side.

Requires:
    python -m pip install hidapi

This PoC only prints frames. It does not call SendInput, TSF, or any IME API.
Close Vial while running this receiver because it opens the same Raw HID
interface.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.windows_ime_raw_hid import RAW_HID_REPORT_SIZE, decode_windows_ime_raw_hid_frame  # noqa: E402

VENDOR_ID = 0x1D6B
PRODUCT_ID = 0x0105
RAW_HID_INTERFACE = 1

COMMAND_LABELS = {
    0x10: "INT4 candidate",
    0x11: "INT5 candidate",
    0x12: "LANG1 candidate",
    0x13: "LANG2 candidate",
    0x20: "HENKAN candidate",
    0x21: "MUHENKAN candidate",
}


def _load_hid_module():
    try:
        import hid  # type: ignore
    except ImportError as exc:
        raise SystemExit("hidapi is required: python -m pip install hidapi") from exc
    return hid


def _find_raw_hid(hid_module, vendor_id: int, product_id: int, interface_number: int) -> dict:
    candidates = []
    for device in hid_module.enumerate(vendor_id, product_id):
        candidates.append(device)
        if device.get("interface_number") == interface_number:
            return device
    summary = "\n".join(
        f"  interface={item.get('interface_number')} path={item.get('path')!r} product={item.get('product_string')!r}"
        for item in candidates
    )
    raise SystemExit(f"raw HID interface MI_{interface_number:02d} not found\n{summary}")


def _format_frame(raw: bytes) -> str:
    decoded = decode_windows_ime_raw_hid_frame(raw)
    payload = decoded["decoded_payload"]
    assert isinstance(payload, dict)
    command_id = int(payload["command_id"])
    direction = "press" if payload["is_press"] else "release"
    label = COMMAND_LABELS.get(command_id, f"0x{command_id:02X}")
    return (
        f"{dt.datetime.now().isoformat(timespec='milliseconds')} "
        f"raw={raw.hex()} command=0x{command_id:02X} {label} "
        f"{direction} sequence={payload['sequence_id']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor-id", type=lambda value: int(value, 0), default=VENDOR_ID)
    parser.add_argument("--product-id", type=lambda value: int(value, 0), default=PRODUCT_ID)
    parser.add_argument("--interface", type=int, default=RAW_HID_INTERFACE)
    parser.add_argument("--timeout-ms", type=int, default=5000)
    parser.add_argument("--count", type=int, default=0, help="number of valid frames to print; 0 means forever")
    args = parser.parse_args()

    hid = _load_hid_module()
    raw_hid = _find_raw_hid(hid, args.vendor_id, args.product_id, args.interface)
    print(f"opening raw HID interface={args.interface} path={raw_hid.get('path')!r}")
    print("waiting for Windows IME Raw HID frames; press Ctrl+C to stop")

    dev = hid.device()
    dev.open_path(raw_hid["path"])
    dev.set_nonblocking(False)
    printed = 0
    try:
        while args.count <= 0 or printed < args.count:
            data = bytes(dev.read(RAW_HID_REPORT_SIZE, args.timeout_ms))
            if not data:
                print(f"{dt.datetime.now().isoformat(timespec='milliseconds')} timeout")
                continue
            try:
                print(_format_frame(data))
                printed += 1
            except ValueError as exc:
                print(f"{dt.datetime.now().isoformat(timespec='milliseconds')} ignored raw={data.hex()} reason={exc}")
    except KeyboardInterrupt:
        print("stopped")
    finally:
        dev.close()


if __name__ == "__main__":
    main()
