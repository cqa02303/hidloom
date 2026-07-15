#!/usr/bin/env python3
"""Regression tests for ledd direct-frame packet helpers."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from ledd.direct_frame import (  # noqa: E402
    BYTES_PER_LED,
    HEADER_SIZE,
    MAGIC,
    DirectFrameError,
    DirectFrameFormat,
    decode_direct_frame,
    encode_direct_frame,
    pack_rgb_triples,
)


def expect_error(fn, text: str) -> None:
    try:
        fn()
    except DirectFrameError as exc:
        assert text in str(exc), str(exc)
    else:
        raise AssertionError(f"expected DirectFrameError containing {text!r}")


def main() -> None:
    payload = pack_rgb_triples([(1, 2, 3), (4, 5, 6)])
    assert payload == bytes([1, 2, 3, 4, 5, 6])

    packet = encode_direct_frame(frame_id=7, led_count=2, payload=payload)
    assert packet[:4] == MAGIC
    assert len(packet) == HEADER_SIZE + 2 * BYTES_PER_LED

    decoded = decode_direct_frame(packet, expected_led_count=2)
    assert decoded.frame_id == 7
    assert decoded.led_count == 2
    assert decoded.format == DirectFrameFormat.RGB
    assert decoded.flags == 0
    assert decoded.payload == payload
    assert decoded.payload_rgb() == payload

    grb_payload = bytes([20, 10, 30, 50, 40, 60])
    grb_packet = encode_direct_frame(
        frame_id=8,
        led_count=2,
        payload=grb_payload,
        format=DirectFrameFormat.GRB,
        flags=1,
    )
    grb_decoded = decode_direct_frame(grb_packet)
    assert grb_decoded.format == DirectFrameFormat.GRB
    assert grb_decoded.flags == 1
    assert grb_decoded.payload_rgb() == bytes([10, 20, 30, 40, 50, 60])

    expect_error(lambda: decode_direct_frame(b""), "packet too short")
    expect_error(lambda: decode_direct_frame(b"NOPE" + packet[4:]), "invalid magic")
    expect_error(lambda: decode_direct_frame(packet[:-1]), "packet length mismatch")
    expect_error(lambda: decode_direct_frame(packet, expected_led_count=3), "led_count mismatch")
    expect_error(lambda: encode_direct_frame(frame_id=0, led_count=2, payload=payload[:-1]), "payload length mismatch")
    expect_error(lambda: encode_direct_frame(frame_id=-1, led_count=2, payload=payload), "frame_id out of range")
    expect_error(lambda: encode_direct_frame(frame_id=0, led_count=0, payload=b""), "led_count must be positive")
    expect_error(lambda: encode_direct_frame(frame_id=0, led_count=1, payload=bytes(3), format=9), "unsupported direct frame format")
    expect_error(lambda: pack_rgb_triples([(0, 0, 256)]), "RGB channel out of range")

    print("ok: ledd direct frame")


if __name__ == "__main__":
    main()
