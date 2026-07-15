"""Binary direct-frame packet helpers for ledd.

This module is the first step toward a high-speed internal LED path:
producer -> ledd direct-frame socket -> LED strip.

Design intent:
- Keep VialRGB direct compatibility path unchanged.
- Use one packet for one full LED frame.
- Validate all untrusted packet data before ledd applies it to hardware.
- Keep this module side-effect free so it can be tested without LED hardware.

Packet format, little-endian:

    magic      4 bytes  b"LDF1"
    frame_id   4 bytes  unsigned
    led_count  2 bytes  unsigned
    format     1 byte   0=RGB, 1=GRB
    flags      1 byte   reserved for now
    payload    led_count * 3 bytes
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Iterable

MAGIC = b"LDF1"
HEADER_STRUCT = struct.Struct("<4sI H B B")
HEADER_SIZE = HEADER_STRUCT.size
BYTES_PER_LED = 3
MAX_LED_COUNT = 4096


class DirectFrameFormat(IntEnum):
    RGB = 0
    GRB = 1


class DirectFrameError(ValueError):
    """Raised when a direct-frame packet is malformed or unsupported."""


@dataclass(frozen=True)
class DirectFramePacket:
    """Validated full-frame LED packet.

    `payload` is exactly `led_count * 3` bytes.  It is still in the declared
    packet format.  Use `payload_rgb()` when ledd needs RGB-order triples.
    """

    frame_id: int
    led_count: int
    format: DirectFrameFormat
    flags: int
    payload: bytes

    def payload_rgb(self) -> bytes:
        """Return payload as RGB triples.

        The LED hardware path owns its final color conversion. This helper
        normalizes packet format for validation and rendering.
        """
        if self.format == DirectFrameFormat.RGB:
            return self.payload
        if self.format == DirectFrameFormat.GRB:
            out = bytearray(len(self.payload))
            for i in range(0, len(self.payload), 3):
                g, r, b = self.payload[i : i + 3]
                out[i : i + 3] = bytes((r, g, b))
            return bytes(out)
        raise DirectFrameError(f"unsupported direct frame format: {self.format!r}")


def _coerce_format(value: int | DirectFrameFormat) -> DirectFrameFormat:
    try:
        return DirectFrameFormat(int(value))
    except ValueError as exc:
        raise DirectFrameError(f"unsupported direct frame format: {value!r}") from exc


def validate_led_count(led_count: int, *, expected_led_count: int | None = None) -> None:
    if led_count <= 0:
        raise DirectFrameError(f"led_count must be positive: {led_count}")
    if led_count > MAX_LED_COUNT:
        raise DirectFrameError(f"led_count too large: {led_count} > {MAX_LED_COUNT}")
    if expected_led_count is not None and led_count != expected_led_count:
        raise DirectFrameError(f"led_count mismatch: packet={led_count} expected={expected_led_count}")


def encode_direct_frame(
    *,
    frame_id: int,
    led_count: int,
    payload: bytes | bytearray | memoryview,
    format: DirectFrameFormat | int = DirectFrameFormat.RGB,
    flags: int = 0,
) -> bytes:
    """Encode one full LED frame packet.

    This intentionally requires the caller to pass `led_count` explicitly so a
    producer cannot accidentally send a partial frame without noticing.
    """
    frame_format = _coerce_format(format)
    payload_bytes = bytes(payload)
    validate_led_count(int(led_count))
    expected_len = int(led_count) * BYTES_PER_LED
    if len(payload_bytes) != expected_len:
        raise DirectFrameError(f"payload length mismatch: got={len(payload_bytes)} expected={expected_len}")
    if not (0 <= int(frame_id) <= 0xFFFFFFFF):
        raise DirectFrameError(f"frame_id out of range: {frame_id}")
    if not (0 <= int(flags) <= 0xFF):
        raise DirectFrameError(f"flags out of range: {flags}")
    header = HEADER_STRUCT.pack(MAGIC, int(frame_id), int(led_count), int(frame_format), int(flags))
    return header + payload_bytes


def decode_direct_frame(packet: bytes | bytearray | memoryview, *, expected_led_count: int | None = None) -> DirectFramePacket:
    """Decode and validate one direct-frame packet.

    Invalid data raises DirectFrameError.  Callers should catch it, log the
    reason, and ignore the packet rather than stopping ledd.
    """
    data = bytes(packet)
    if len(data) < HEADER_SIZE:
        raise DirectFrameError(f"packet too short: {len(data)} < {HEADER_SIZE}")
    magic, frame_id, led_count, raw_format, flags = HEADER_STRUCT.unpack(data[:HEADER_SIZE])
    if magic != MAGIC:
        raise DirectFrameError(f"invalid magic: {magic!r}")
    frame_format = _coerce_format(raw_format)
    validate_led_count(int(led_count), expected_led_count=expected_led_count)
    expected_len = HEADER_SIZE + int(led_count) * BYTES_PER_LED
    if len(data) != expected_len:
        raise DirectFrameError(f"packet length mismatch: got={len(data)} expected={expected_len}")
    return DirectFramePacket(
        frame_id=int(frame_id),
        led_count=int(led_count),
        format=frame_format,
        flags=int(flags),
        payload=data[HEADER_SIZE:],
    )


def pack_rgb_triples(colors: Iterable[tuple[int, int, int]]) -> bytes:
    """Pack RGB integer triples into payload bytes.

    Values are validated instead of silently clamped so bad producer output is
    caught before it reaches the direct-frame socket.
    """
    out = bytearray()
    for rgb in colors:
        if len(rgb) != 3:
            raise DirectFrameError(f"RGB triple must have length 3: {rgb!r}")
        for channel in rgb:
            if not (0 <= int(channel) <= 0xFF):
                raise DirectFrameError(f"RGB channel out of range: {channel!r}")
            out.append(int(channel))
    return bytes(out)
