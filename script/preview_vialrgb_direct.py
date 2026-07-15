#!/usr/bin/env python3
"""Preview VialRGB direct control with continuous HSV frames."""
from __future__ import annotations

import argparse
import math
import os
import socket
import struct
import time
from pathlib import Path
from typing import Iterable

REPORT_SIZE = 32
DIRECT_PIXELS_PER_PACKET = 9
DEFAULT_PROCESSES = ("viald", "logicd", "ledd")


def recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise RuntimeError("socket closed before full response")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def exchange(sock: socket.socket, payload: bytes) -> bytes:
    if len(payload) > REPORT_SIZE:
        raise ValueError(f"payload too large: {len(payload)} > {REPORT_SIZE}")
    sock.sendall(payload.ljust(REPORT_SIZE, b"\x00"))
    return recv_exact(sock, REPORT_SIZE)


def set_mode(sock: socket.socket, mode: int, speed: int, h: int, s: int, v: int) -> None:
    exchange(sock, b"\x07\x41" + struct.pack("<HBBBB", mode, speed, h, s, v))


def read_mode(sock: socket.socket) -> tuple[int, int, int, int, int]:
    response = exchange(sock, b"\x08\x41")
    return struct.unpack("<HBBBB", response[2:8])


def read_led_count(sock: socket.socket) -> int:
    response = exchange(sock, b"\x08\x43")
    return struct.unpack("<H", response[2:4])[0]


def direct_fastset(sock: socket.socket, first: int, pixels: list[tuple[int, int, int]]) -> None:
    payload = b"\x07\x42" + struct.pack("<HB", first, len(pixels))
    payload += b"".join(bytes(pixel) for pixel in pixels)
    exchange(sock, payload)


def frame_chunks(frame: list[tuple[int, int, int]]) -> Iterable[tuple[int, list[tuple[int, int, int]]]]:
    for first in range(0, len(frame), DIRECT_PIXELS_PER_PACKET):
        yield first, frame[first:first + DIRECT_PIXELS_PER_PACKET]


def make_frame(led_count: int, frame_index: int, pattern: str, brightness: int) -> list[tuple[int, int, int]]:
    if led_count <= 0:
        return []
    brightness = max(0, min(255, brightness))
    frame: list[tuple[int, int, int]] = []
    phase = frame_index * 7
    for idx in range(led_count):
        ratio = idx / max(1, led_count - 1)
        if pattern == "chase":
            distance = min(abs((idx - frame_index) % led_count), abs((frame_index - idx) % led_count))
            v = max(8, brightness - distance * 32)
            h = (phase + idx * 3) % 256
        elif pattern == "pulse":
            wave = (math.sin(frame_index * 0.18 + ratio * math.tau) + 1.0) / 2.0
            v = int(16 + wave * max(0, brightness - 16))
            h = (phase + int(ratio * 64)) % 256
        else:
            v = brightness
            h = (phase + int(ratio * 255)) % 256
        frame.append((h, 255, v))
    return frame


def _read_proc_cpu(pid: str) -> int | None:
    try:
        stat = Path("/proc") / pid / "stat"
        fields = stat.read_text(encoding="utf-8").split()
        return int(fields[13]) + int(fields[14])
    except (OSError, ValueError, IndexError):
        return None


def _proc_cmdline(pid: str) -> str:
    try:
        return (Path("/proc") / pid / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="replace")
    except OSError:
        return ""


def sample_process_cpu(names: Iterable[str]) -> dict[str, tuple[str, int]]:
    wanted = tuple(names)
    samples: dict[str, tuple[str, int]] = {}
    proc = Path("/proc")
    if not proc.exists():
        return samples
    for pid_path in proc.iterdir():
        if not pid_path.name.isdigit():
            continue
        cmdline = _proc_cmdline(pid_path.name)
        for name in wanted:
            if name in samples:
                continue
            if name in cmdline:
                ticks = _read_proc_cpu(pid_path.name)
                if ticks is not None:
                    samples[name] = (pid_path.name, ticks)
    return samples


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview VialRGB direct control continuous frames")
    parser.add_argument("--socket", default="/tmp/viald_events.sock")
    parser.add_argument("--seconds", type=float, default=8.0)
    parser.add_argument("--fps", type=float, default=20.0)
    parser.add_argument("--brightness", type=int, default=96)
    parser.add_argument("--pattern", choices=("rainbow", "chase", "pulse"), default="rainbow")
    parser.add_argument("--restore", action="store_true", help="restore the original VialRGB mode at the end")
    parser.add_argument("--cpu", action="store_true", help="print approximate CPU usage for viald/logicd/ledd")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sock_path = Path(args.socket)
    if not sock_path.exists():
        raise SystemExit(f"socket not found: {sock_path}")
    if args.seconds <= 0:
        raise SystemExit("--seconds must be > 0")
    if args.fps <= 0:
        raise SystemExit("--fps must be > 0")

    cpu_start = sample_process_cpu(DEFAULT_PROCESSES) if args.cpu else {}
    wall_start = time.monotonic()
    frames = 0
    packets = 0

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(str(sock_path))
        led_count = read_led_count(sock)
        original = read_mode(sock)
        frame_interval = 1.0 / args.fps
        deadline = time.monotonic() + args.seconds
        print(
            f"direct preview: leds={led_count} pattern={args.pattern} "
            f"target_fps={args.fps:.1f} seconds={args.seconds:.1f}",
            flush=True,
        )
        try:
            set_mode(sock, 1, 128, 0, 0, 0)
            next_frame = time.monotonic()
            while time.monotonic() < deadline:
                frame = make_frame(led_count, frames, args.pattern, args.brightness)
                for first, pixels in frame_chunks(frame):
                    direct_fastset(sock, first, pixels)
                    packets += 1
                frames += 1
                next_frame += frame_interval
                sleep_for = next_frame - time.monotonic()
                if sleep_for > 0:
                    time.sleep(sleep_for)
                else:
                    next_frame = time.monotonic()
        finally:
            if args.restore:
                set_mode(sock, *original)
                print(f"restored mode={original[0]} speed={original[1]} hsv={original[2:]}", flush=True)

    elapsed = max(0.001, time.monotonic() - wall_start)
    bytes_sent = packets * REPORT_SIZE
    print(
        f"sent frames={frames} packets={packets} "
        f"fps={frames / elapsed:.1f} packets/s={packets / elapsed:.1f} bytes/s={bytes_sent / elapsed:.0f}",
        flush=True,
    )

    if args.cpu:
        cpu_end = sample_process_cpu(DEFAULT_PROCESSES)
        hz = os.sysconf(os.sysconf_names.get("SC_CLK_TCK", "SC_CLK_TCK"))
        for name, (pid, start_ticks) in sorted(cpu_start.items()):
            end = cpu_end.get(name)
            if end is None or end[0] != pid:
                print(f"cpu {name}: unavailable", flush=True)
                continue
            cpu_pct = (end[1] - start_ticks) / hz / elapsed * 100.0
            print(f"cpu {name}[{pid}]: {cpu_pct:.1f}%", flush=True)


if __name__ == "__main__":
    main()
