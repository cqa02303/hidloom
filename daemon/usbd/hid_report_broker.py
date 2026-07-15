"""USB HID report broker protocol and profile adapters.

The broker receives canonical HID payloads from local daemons and turns them
into the concrete USB gadget report shape for the active descriptor profile.
"""
from __future__ import annotations

from dataclasses import dataclass

FRAME_MAGIC = b"CQAU"
FRAME_VERSION = 0x01
FRAME_SIZE = 64
PAYLOAD_OFFSET = 8
PAYLOAD_CAPACITY = 24
CHECKSUM_OFFSET = FRAME_SIZE - 1

KIND_KEYBOARD = 0x01
KIND_MOUSE = 0x02
KIND_CONSUMER = 0x03
KIND_US_SUB_KEYBOARD = 0x04

REPORT_ID_KEYBOARD = 0x01
REPORT_ID_MOUSE = 0x02
REPORT_ID_CONSUMER = 0x03

PAYLOAD_LENGTHS = {
    KIND_KEYBOARD: 8,
    KIND_MOUSE: 4,
    KIND_CONSUMER: 2,
    KIND_US_SUB_KEYBOARD: 8,
}

KIND_NAMES = {
    KIND_KEYBOARD: "keyboard",
    KIND_MOUSE: "mouse",
    KIND_CONSUMER: "consumer",
    KIND_US_SUB_KEYBOARD: "us_sub_keyboard",
}


@dataclass(frozen=True)
class HidReportRequest:
    kind: int
    payload: bytes
    flags: int = 0

    @property
    def kind_name(self) -> str:
        return KIND_NAMES.get(self.kind, f"unknown_{self.kind:02x}")


@dataclass(frozen=True)
class UsbReport:
    endpoint: str
    report: bytes
    kind: int

    @property
    def kind_name(self) -> str:
        return KIND_NAMES.get(self.kind, f"unknown_{self.kind:02x}")


def _xor_checksum(data: bytes) -> int:
    value = 0
    for byte in data:
        value ^= byte
    return value & 0xFF


def encode_hid_report_request(kind: int, payload: bytes, *, flags: int = 0) -> bytes:
    payload = bytes(payload)
    expected_length = PAYLOAD_LENGTHS.get(kind)
    if expected_length is None:
        raise ValueError(f"unsupported HID report kind: 0x{kind:02x}")
    if len(payload) != expected_length:
        raise ValueError(
            f"invalid {KIND_NAMES[kind]} payload length: got={len(payload)} expected={expected_length}"
        )
    if flags < 0 or flags > 0xFF:
        raise ValueError(f"invalid HID report flags: {flags}")
    if len(payload) > PAYLOAD_CAPACITY:
        raise ValueError(f"payload too large: {len(payload)} > {PAYLOAD_CAPACITY}")

    frame = bytearray(FRAME_SIZE)
    frame[0:4] = FRAME_MAGIC
    frame[4] = FRAME_VERSION
    frame[5] = kind & 0xFF
    frame[6] = len(payload)
    frame[7] = flags & 0xFF
    frame[PAYLOAD_OFFSET:PAYLOAD_OFFSET + len(payload)] = payload
    frame[CHECKSUM_OFFSET] = _xor_checksum(frame[:CHECKSUM_OFFSET])
    return bytes(frame)


def decode_hid_report_request(frame: bytes) -> HidReportRequest:
    frame = bytes(frame)
    if len(frame) != FRAME_SIZE:
        raise ValueError(f"invalid HID report request size: got={len(frame)} expected={FRAME_SIZE}")
    if frame[0:4] != FRAME_MAGIC:
        raise ValueError(f"invalid HID report request magic: {frame[0:4]!r}")
    if frame[4] != FRAME_VERSION:
        raise ValueError(f"unsupported HID report request version: {frame[4]}")
    if _xor_checksum(frame[:CHECKSUM_OFFSET]) != frame[CHECKSUM_OFFSET]:
        raise ValueError("invalid HID report request checksum")

    kind = frame[5]
    payload_length = frame[6]
    flags = frame[7]
    expected_length = PAYLOAD_LENGTHS.get(kind)
    if expected_length is None:
        raise ValueError(f"unsupported HID report kind: 0x{kind:02x}")
    if payload_length != expected_length:
        raise ValueError(
            f"invalid {KIND_NAMES[kind]} payload length: got={payload_length} expected={expected_length}"
        )
    if payload_length > PAYLOAD_CAPACITY:
        raise ValueError(f"payload too large: {payload_length} > {PAYLOAD_CAPACITY}")
    payload = frame[PAYLOAD_OFFSET:PAYLOAD_OFFSET + payload_length]
    reserved = frame[PAYLOAD_OFFSET + payload_length:CHECKSUM_OFFSET]
    if any(reserved):
        raise ValueError("reserved bytes must be zero")
    return HidReportRequest(kind=kind, payload=payload, flags=flags)


def adapt_current_multi_report_profile(
    request: HidReportRequest,
    *,
    hidg_path: str = "/dev/hidg0",
    us_sub_hidg_path: str = "/dev/hidg2",
) -> UsbReport:
    """Convert a canonical request to the current /dev/hidg0 multi-report bytes."""
    if request.kind == KIND_KEYBOARD:
        return UsbReport(hidg_path, bytes([REPORT_ID_KEYBOARD]) + request.payload, request.kind)
    if request.kind == KIND_MOUSE:
        return UsbReport(hidg_path, bytes([REPORT_ID_MOUSE]) + request.payload, request.kind)
    if request.kind == KIND_CONSUMER:
        return UsbReport(hidg_path, bytes([REPORT_ID_CONSUMER]) + request.payload, request.kind)
    if request.kind == KIND_US_SUB_KEYBOARD:
        return UsbReport(us_sub_hidg_path, request.payload, request.kind)
    raise ValueError(f"unsupported HID report kind: 0x{request.kind:02x}")
