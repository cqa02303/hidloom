#!/usr/bin/env python3
"""Generate the original HIDloom loom/matrix web icon set."""
from __future__ import annotations

import argparse
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "daemon" / "http" / "static"

BACKGROUND = (15, 23, 42, 255)
CYAN = (34, 211, 238, 255)
VIOLET = (167, 139, 250, 255)
BORDER = (51, 65, 85, 255)
TRANSPARENT = (0, 0, 0, 0)


def png_chunk(kind: bytes, data: bytes) -> bytes:
    payload = kind + data
    return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload))


def rounded_square(x: float, y: float) -> bool:
    margin = 0.04
    radius = 0.18
    if margin + radius <= x <= 1 - margin - radius:
        return margin <= y <= 1 - margin
    if margin + radius <= y <= 1 - margin - radius:
        return margin <= x <= 1 - margin
    center_x = margin + radius if x < 0.5 else 1 - margin - radius
    center_y = margin + radius if y < 0.5 else 1 - margin - radius
    return (x - center_x) ** 2 + (y - center_y) ** 2 <= radius**2


def inside_thread(value: float, center: float, width: float) -> bool:
    return abs(value - center) <= width / 2


def pixel(x: float, y: float) -> tuple[int, int, int, int]:
    if not rounded_square(x, y):
        return TRANSPARENT
    if x < 0.06 or x > 0.94 or y < 0.06 or y > 0.94:
        return BORDER

    centers = (0.29, 0.50, 0.71)
    width = 0.095
    in_horizontal = 0.18 <= x <= 0.82 and any(inside_thread(y, center, width) for center in centers)
    in_vertical = 0.18 <= y <= 0.82 and any(inside_thread(x, center, width) for center in centers)
    color = BACKGROUND
    if in_horizontal:
        color = VIOLET
    if in_vertical:
        color = CYAN

    for column, center_x in enumerate(centers):
        for row, center_y in enumerate(centers):
            if inside_thread(x, center_x, width + 0.012) and inside_thread(
                y, center_y, width + 0.012
            ):
                color = VIOLET if (row + column) % 2 == 0 else CYAN
    return color


def png(size: int) -> bytes:
    rows = bytearray()
    for row in range(size):
        rows.append(0)
        y = (row + 0.5) / size
        for column in range(size):
            x = (column + 0.5) / size
            rows.extend(pixel(x, y))
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", header) + png_chunk(
        b"IDAT", zlib.compress(bytes(rows), 9)
    ) + png_chunk(b"IEND", b"")


def ico(images: list[tuple[int, bytes]]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = bytearray()
    payload = bytearray()
    for size, data in images:
        dimension = 0 if size == 256 else size
        entries.extend(
            struct.pack("<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(data), offset)
        )
        payload.extend(data)
        offset += len(data)
    return header + bytes(entries) + bytes(payload)


def svg() -> str:
    crossings = []
    centers = (18.56, 32.0, 45.44)
    for column, center_x in enumerate(centers):
        for row, center_y in enumerate(centers):
            color = "#a78bfa" if (row + column) % 2 == 0 else "#22d3ee"
            crossings.append(
                f'  <rect x="{center_x - 3.4:.2f}" y="{center_y - 3.4:.2f}" '
                f'width="6.80" height="6.80" rx="1" fill="{color}"/>'
            )
    return "\n".join(
        [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-labelledby="title desc">',
            '  <title id="title">HIDloom mark</title>',
            '  <desc id="desc">Interwoven cyan and violet threads forming a keyboard matrix.</desc>',
            '  <rect x="2.5" y="2.5" width="59" height="59" rx="11.5" fill="#0f172a" stroke="#334155"/>',
            '  <path d="M11.5 18.56H52.5M11.5 32H52.5M11.5 45.44H52.5" stroke="#a78bfa" stroke-width="6.1" stroke-linecap="round"/>',
            '  <path d="M18.56 11.5V52.5M32 11.5V52.5M45.44 11.5V52.5" stroke="#22d3ee" stroke-width="6.1" stroke-linecap="round"/>',
            *crossings,
            "</svg>",
            "",
        ]
    )


def write_icons(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    outputs = {
        "favicon-32x32.png": png(32),
        "apple-touch-icon.png": png(180),
        "android-chrome-192x192.png": png(192),
        "android-chrome-512x512.png": png(512),
    }
    for name, content in outputs.items():
        (output / name).write_bytes(content)
    (output / "favicon.ico").write_bytes(ico([(size, png(size)) for size in (16, 32, 48)]))
    (output / "hidloom-mark.svg").write_text(svg(), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    write_icons(args.output_dir)
    print(f"generated HIDloom icons: {args.output_dir}")


if __name__ == "__main__":
    main()
