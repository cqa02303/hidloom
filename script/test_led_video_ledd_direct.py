#!/usr/bin/env python3
"""Regression tests for LED video ledd-direct packet generation."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from tools.demo import play_led_video  # noqa: E402
from ledd.direct_frame import DirectFrameFormat, decode_direct_frame  # noqa: E402


class FakeNumpy:
    uint8 = object()


class FakeBgrArray:
    """Tiny ndarray-like test double for the packet-generation hot path."""

    def __init__(self, rows: Iterable[Iterable[int]]) -> None:
        self.rows = [tuple(int(v) for v in row) for row in rows]

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, key):
        row_key, col_key = key
        if row_key != slice(None):
            raise AssertionError(f"unexpected row selector: {row_key!r}")
        return FakeBgrArray(tuple(row[i] for i in col_key) for row in self.rows)

    def astype(self, _dtype, copy: bool = False):
        if copy:
            return FakeBgrArray(self.rows)
        return self

    def tobytes(self) -> bytes:
        return bytes(channel for row in self.rows for channel in row)


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[bytes] = []

    def sendall(self, data: bytes) -> None:
        self.sent.append(bytes(data))


def main() -> None:
    play_led_video.np = FakeNumpy()
    colors_bgr = FakeBgrArray([
        [3, 2, 1],
        [6, 5, 4],
    ])
    assert play_led_video.bgr_to_rgb_payload(colors_bgr) == bytes([1, 2, 3, 4, 5, 6])

    sock = FakeSocket()
    play_led_video.send_ledd_direct_frame(sock, 42, colors_bgr)
    assert len(sock.sent) == 1
    frame = decode_direct_frame(sock.sent[0], expected_led_count=2)
    assert frame.frame_id == 42
    assert frame.led_count == 2
    assert frame.format == DirectFrameFormat.RGB
    assert frame.payload == bytes([1, 2, 3, 4, 5, 6])

    play_led_video.np = np
    capped = play_led_video.apply_max_brightness(
        np.array([
            [200, 100, 50],
            [10, 20, 30],
            [0, 0, 0],
        ], dtype=np.uint8),
        100,
    )
    assert capped.tolist() == [
        [100, 50, 25],
        [10, 20, 30],
        [0, 0, 0],
    ]
    assert play_led_video.apply_max_brightness(capped, 0).tolist() == [
        [0, 0, 0],
        [0, 0, 0],
        [0, 0, 0],
    ]

    print("ok: LED video ledd-direct")


if __name__ == "__main__":
    main()
