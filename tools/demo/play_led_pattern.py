#!/usr/bin/env python3
"""Stream a dependency-free procedural pattern to the ledd direct-frame socket."""
from __future__ import annotations

import argparse
import colorsys
import json
import math
import os
from pathlib import Path
import signal
import socket
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "daemon"))

from ledd.direct_frame import DirectFrameFormat, encode_direct_frame  # noqa: E402
from ledd.direct_frame_socket import DEFAULT_DIRECT_FRAME_SOCKET  # noqa: E402

PACKAGED_CONFIG = ROOT / "config" / "default" / "ledd.json"
RUNTIME_CONFIG = Path(os.environ.get("HIDLOOM_RUNTIME_DIR", "/mnt/p3")) / "ledd.json"
DEFAULT_CONFIG = RUNTIME_CONFIG if RUNTIME_CONFIG.exists() else PACKAGED_CONFIG
DEFAULT_PIDFILE = Path("/tmp/hidloom_led_video.pid")

_stop_requested = False
_owned_pidfile: Path | None = None


def request_stop(signum: int, _frame: object) -> None:
    global _stop_requested
    print(f"received signal {signum}; stopping", flush=True)
    _stop_requested = True


def process_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def process_is_led_demo(pid: int) -> bool:
    try:
        command = (Path("/proc") / str(pid) / "cmdline").read_bytes().replace(b"\x00", b" ")
    except OSError:
        return False
    return b"play_led_video.py" in command or b"play_led_pattern.py" in command


def acquire_singleton(pidfile: Path) -> None:
    global _owned_pidfile
    try:
        old_pid = int(pidfile.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        old_pid = 0
    if old_pid and old_pid != os.getpid() and process_is_running(old_pid) and process_is_led_demo(old_pid):
        os.kill(old_pid, signal.SIGTERM)
        deadline = time.monotonic() + 8.0
        while process_is_running(old_pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        if process_is_running(old_pid):
            os.kill(old_pid, signal.SIGKILL)
    pidfile.write_text(f"{os.getpid()}\n", encoding="utf-8")
    _owned_pidfile = pidfile


def release_singleton() -> None:
    global _owned_pidfile
    if _owned_pidfile is None:
        return
    try:
        if _owned_pidfile.read_text(encoding="utf-8").strip() == str(os.getpid()):
            _owned_pidfile.unlink()
    except OSError:
        pass
    _owned_pidfile = None


def load_positions(config_path: Path) -> list[tuple[float, float]]:
    data = json.loads(config_path.read_text(encoding="utf-8"))
    leds = data.get("leds")
    if not isinstance(leds, dict) or not leds:
        raise ValueError(f"LED configuration has no leds: {config_path}")
    raw = [(float(position["x"]), float(position["y"])) for position in leds.values()]
    min_x = min(position[0] for position in raw)
    max_x = max(position[0] for position in raw)
    min_y = min(position[1] for position in raw)
    max_y = max(position[1] for position in raw)
    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)
    return [((x - min_x) / span_x, (y - min_y) / span_y) for x, y in raw]


def pattern_payload(positions: list[tuple[float, float]], phase: float, max_brightness: int) -> bytes:
    limit = max(0, min(255, int(max_brightness)))
    payload = bytearray()
    for x, y in positions:
        hue = (phase + x * 0.62 + y * 0.24) % 1.0
        wave = 0.3 + 0.7 * (0.5 + 0.5 * math.sin((x * 2.0 - y + phase * 3.0) * math.tau))
        red, green, blue = colorsys.hsv_to_rgb(hue, 1.0, wave)
        payload.extend(round(channel * limit) for channel in (red, green, blue))
    return bytes(payload)


def stream_pattern(
    sock: socket.socket,
    positions: list[tuple[float, float]],
    *,
    fps: float,
    max_brightness: int,
    seconds: float,
) -> int:
    interval = 1.0 / max(1.0, fps)
    started = time.monotonic()
    deadline = started + seconds if seconds > 0 else None
    frame_id = 0
    while not _stop_requested and (deadline is None or time.monotonic() < deadline):
        frame_started = time.monotonic()
        phase = ((frame_started - started) * 0.08) % 1.0
        payload = pattern_payload(positions, phase, max_brightness)
        packet = encode_direct_frame(
            frame_id=frame_id & 0xFFFFFFFF,
            led_count=len(positions),
            payload=payload,
            format=DirectFrameFormat.RGB,
        )
        sock.sendall(packet)
        frame_id += 1
        remaining = interval - (time.monotonic() - frame_started)
        if remaining > 0:
            time.sleep(remaining)
    return frame_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--socket", default=DEFAULT_DIRECT_FRAME_SOCKET)
    parser.add_argument("--pidfile", type=Path, default=DEFAULT_PIDFILE)
    parser.add_argument("--fps", type=float, default=16.0)
    parser.add_argument("--max-brightness", type=int, default=64)
    parser.add_argument("--seconds", type=float, default=0.0)
    parser.add_argument("--allow-multiple", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    if not args.allow_multiple:
        acquire_singleton(args.pidfile)
    try:
        positions = load_positions(args.config)
        print(
            f"starting procedural LED pattern: leds={len(positions)} fps={args.fps} "
            f"max_brightness={args.max_brightness}",
            flush=True,
        )
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(args.socket)
            frames = stream_pattern(
                client,
                positions,
                fps=args.fps,
                max_brightness=args.max_brightness,
                seconds=args.seconds,
            )
        print(f"procedural LED pattern stopped: frames={frames}", flush=True)
    finally:
        release_singleton()


if __name__ == "__main__":
    main()
