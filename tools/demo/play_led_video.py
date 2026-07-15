#!/usr/bin/env python3
"""Play a video on the keyboard LEDs.

Backends:
- ``direct`` sends VialRGB direct chunks through viald for compatibility.
- ``ledd-direct`` sends one full-frame LDF1 packet directly to ledd.
- ``hardware`` writes to rpi_ws281x directly for standalone experiments.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import struct
import sys
import time
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
DAEMON_ROOT = ROOT / "daemon"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(DAEMON_ROOT))

from ledd.direct_frame import DirectFrameFormat, encode_direct_frame  # noqa: E402
from ledd.direct_frame_socket import DEFAULT_DIRECT_FRAME_SOCKET  # noqa: E402

REPORT_SIZE = 32
DIRECT_PIXELS_PER_PACKET = 9
DOT_MM = 19.05 / 8
DEFAULT_CONFIG = ROOT / "config" / "default" / "ledd.json"
DEFAULT_VIDEO = ROOT / "demo" / "assets" / "led_video_demo.mp4"
DEFAULT_PIDFILE = Path("/tmp/hidloom_led_video.pid")

_stop_requested = False
_owned_pidfile: Path | None = None


def _request_stop(signum: int, _frame: object) -> None:
    global _stop_requested
    print(f"received signal {signum}; stopping after current frame", flush=True)
    _stop_requested = True


def _process_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _process_looks_like_led_player(pid: int) -> bool:
    try:
        cmdline = (Path("/proc") / str(pid) / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="replace")
    except OSError:
        return False
    return "play_led_video.py" in cmdline


def _stop_previous_instance(pidfile: Path, timeout: float = 8.0) -> None:
    try:
        old_pid = int(pidfile.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return
    if old_pid == os.getpid() or not _process_is_running(old_pid):
        return
    if not _process_looks_like_led_player(old_pid):
        print(f"pidfile ignored: pid {old_pid} is not a LED video player", flush=True)
        return

    print(f"stopping previous LED video player pid={old_pid}", flush=True)
    try:
        os.kill(old_pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _process_is_running(old_pid):
            return
        time.sleep(0.1)

    if _process_is_running(old_pid):
        print(f"previous LED video player pid={old_pid} did not exit; sending SIGKILL", flush=True)
        try:
            os.kill(old_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def acquire_singleton(pidfile: Path) -> None:
    global _owned_pidfile
    _stop_previous_instance(pidfile)
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


def direct_fastset(sock: socket.socket, first: int, pixels: np.ndarray) -> None:
    count = int(len(pixels))
    payload = b"\x07\x42" + struct.pack("<HB", first, count)
    payload += pixels.astype(np.uint8, copy=False).tobytes()
    exchange(sock, payload)


def frame_chunks(frame_hsv: np.ndarray) -> Iterable[tuple[int, np.ndarray]]:
    for first in range(0, len(frame_hsv), DIRECT_PIXELS_PER_PACKET):
        yield first, frame_hsv[first:first + DIRECT_PIXELS_PER_PACKET]


def bgr_to_rgb_payload(colors_bgr: np.ndarray) -> bytes:
    """Convert sampled OpenCV BGR triples to direct-frame RGB payload bytes."""
    return colors_bgr[:, [2, 1, 0]].astype(np.uint8, copy=False).tobytes()


def apply_max_brightness(colors_bgr: np.ndarray, max_brightness: int) -> np.ndarray:
    """Scale each LED color so its brightest channel stays under the limit."""
    limit = max(0, min(255, int(max_brightness)))
    colors_u8 = colors_bgr.astype(np.uint8, copy=False)
    if limit >= 255:
        return colors_u8
    if limit <= 0:
        return np.zeros_like(colors_u8, dtype=np.uint8)

    peaks = colors_u8.max(axis=1).astype(np.float32)
    scale = np.minimum(1.0, limit / np.maximum(peaks, 1.0))
    return np.rint(colors_u8.astype(np.float32) * scale[:, None]).astype(np.uint8)


def send_ledd_direct_frame(sock: socket.socket, frame_id: int, colors_bgr: np.ndarray) -> None:
    """Send one full LED frame to ledd direct-frame socket."""
    led_count = int(len(colors_bgr))
    packet = encode_direct_frame(
        frame_id=frame_id & 0xFFFFFFFF,
        led_count=led_count,
        payload=bgr_to_rgb_payload(colors_bgr),
        format=DirectFrameFormat.RGB,
    )
    sock.sendall(packet)


def load_led_mapping(config_path: Path) -> tuple[dict, np.ndarray, np.ndarray, float, float]:
    with config_path.open(encoding="utf-8") as f:
        data = json.load(f)
    leds = data["leds"]
    wired_keys = list(leds.keys())
    physical_items = sorted(leds.items(), key=lambda kv: (kv[1]["y"], kv[1]["x"]))

    xs = np.array([pos["x"] for _, pos in physical_items])
    ys = np.array([pos["y"] for _, pos in physical_items])
    min_x, max_x = xs.min(), xs.max()
    min_y, max_y = ys.min(), ys.max()
    width_mm = max_x - min_x
    height_mm = max_y - min_y

    norm_x = (xs - min_x) / width_mm
    norm_y = (ys - min_y) / height_mm
    key_index = {key: idx for idx, (key, _pos) in enumerate(physical_items)}
    map_idx = np.array([key_index[key] for key in wired_keys])
    norm_xy = np.column_stack((norm_x, norm_y))
    return data, norm_xy, map_idx, width_mm, height_mm


def build_sampler(
    norm_xy: np.ndarray,
    target_w: int,
    target_h: int,
) -> tuple[np.ndarray, np.ndarray]:
    offsets = np.array([
        [-1, -1], [-1, 0], [-1, 1],
        [0, -1], [0, 0], [0, 1],
        [1, -1], [1, 0], [1, 1],
    ])
    px = (norm_xy[:, 0] * target_w).astype(np.int32).clip(0, target_w - 1)
    py = (norm_xy[:, 1] * target_h).astype(np.int32).clip(0, target_h - 1)
    px9 = (px[:, None] + offsets[:, 0]).clip(0, target_w - 1)
    py9 = (py[:, None] + offsets[:, 1]).clip(0, target_h - 1)
    return px9, py9


def crop_for_aspect(orig_w: int, orig_h: int, led_aspect: float) -> tuple[slice, slice]:
    video_aspect = orig_w / orig_h
    if video_aspect > led_aspect:
        new_width = int(orig_h * led_aspect)
        x0 = (orig_w - new_width) // 2
        return slice(None), slice(x0, x0 + new_width)
    new_height = int(orig_w / led_aspect)
    y0 = (orig_h - new_height) // 2
    return slice(y0, y0 + new_height), slice(None)


def sample_frame_bgr(
    frame: np.ndarray,
    crop: tuple[slice, slice],
    target_w: int,
    target_h: int,
    px9: np.ndarray,
    py9: np.ndarray,
    map_idx: np.ndarray,
) -> np.ndarray:
    resized = cv2.resize(frame[crop], (target_w, target_h), interpolation=cv2.INTER_NEAREST)
    colors9 = resized[py9, px9]
    colors_physical = colors9.mean(axis=1)
    return colors_physical[map_idx].astype(np.uint8)


def bgr_to_vial_hsv(colors_bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(colors_bgr.reshape((-1, 1, 3)), cv2.COLOR_BGR2HSV).reshape((-1, 3))
    # OpenCV hue is 0..179; VialRGB direct uses 0..255.
    hsv[:, 0] = np.minimum(255, (hsv[:, 0].astype(np.uint16) * 255 // 179)).astype(np.uint8)
    return hsv


def init_hardware_strip(data: dict):
    import rpi_ws281x as ws
    from rpi_ws281x import PixelStrip

    strip_type_map = {
        "GRB": getattr(ws, "SK6812_STRIP_GRB", 0x00081000),
        "RGB": getattr(ws, "WS2812_STRIP", 0x00081000),
        "BGR": getattr(ws, "SK6812_STRIP", 0x00081000),
    }
    color_order = data["led"].get("color_order", "GRB").upper()
    strip_type = strip_type_map.get(color_order, strip_type_map["GRB"])
    strip = PixelStrip(
        num=len(data["leds"]),
        pin=data["led"]["gpio_bcm"],
        brightness=data["led"]["brightness"],
        dma=10,
        strip_type=strip_type,
    )
    strip.begin()
    return strip


def render_hardware(strip: object, colors_bgr: np.ndarray) -> None:
    packed = (
        (colors_bgr[:, 2].astype(np.uint32) << 16)
        | (colors_bgr[:, 1].astype(np.uint32) << 8)
        | colors_bgr[:, 0].astype(np.uint32)
    )
    for idx, color in enumerate(packed):
        strip.setPixelColor(idx, int(color))
    strip.show()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Play video frames on keyboard LEDs")
    parser.add_argument("video", nargs="?", default=str(DEFAULT_VIDEO))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--backend", choices=("direct", "ledd-direct", "hardware"), default="direct")
    parser.add_argument("--socket", default="/tmp/viald_events.sock", help="viald socket for --backend direct")
    parser.add_argument("--ledd-socket", default=DEFAULT_DIRECT_FRAME_SOCKET, help="ledd direct-frame socket for --backend ledd-direct")
    parser.add_argument("--pidfile", default=str(DEFAULT_PIDFILE))
    parser.add_argument("--allow-multiple", action="store_true", help="do not stop an existing LED video player instance")
    parser.add_argument("--once", action="store_true", help="stop at end of video instead of looping")
    parser.add_argument("--seconds", type=float, default=0.0, help="stop after this many seconds when > 0")
    parser.add_argument("--no-restore", action="store_true", help="do not restore the previous VialRGB mode")
    parser.add_argument("--fps", type=float, default=0.0, help="override video FPS when > 0")
    parser.add_argument(
        "--max-brightness",
        type=int,
        default=96,
        help="per-LED channel ceiling after sampling, 0..255; lower values reduce peak LED current",
    )
    return parser.parse_args()


def main() -> None:
    global cv2, np

    args = parse_args()
    if not args.allow_multiple:
        acquire_singleton(Path(args.pidfile))

    import cv2 as cv2_module
    import numpy as np_module

    cv2 = cv2_module
    np = np_module

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    video_path = Path(args.video)
    config_path = Path(args.config)
    print(f"Using video: {video_path}", flush=True)

    data, norm_xy, map_idx, width_mm, height_mm = load_led_mapping(config_path)
    target_w = max(1, int(width_mm / DOT_MM))
    target_h = max(1, int(height_mm / DOT_MM))
    px9, py9 = build_sampler(norm_xy, target_w, target_h)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise SystemExit(f"ERROR: 動画を開けません: {video_path}")
    video_fps = args.fps if args.fps > 0 else cap.get(cv2.CAP_PROP_FPS)
    if not video_fps or video_fps <= 0:
        video_fps = 16.0
    frame_delay = 1.0 / video_fps
    max_brightness = max(0, min(255, int(args.max_brightness)))

    orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    crop = crop_for_aspect(orig_w, orig_h, width_mm / height_mm)
    print(
        f"LED effective resolution: {target_w} x {target_h}, "
        f"video FPS: {video_fps:.1f}, max brightness: {max_brightness}",
        flush=True,
    )

    strip = None
    sock: socket.socket | None = None
    original_mode: tuple[int, int, int, int, int] | None = None
    frames = 0
    packets = 0
    started = time.monotonic()

    try:
        if args.backend == "hardware":
            strip = init_hardware_strip(data)
            print("backend: hardware", flush=True)
        elif args.backend == "ledd-direct":
            sock_path = Path(args.ledd_socket)
            if not sock_path.exists():
                raise SystemExit(f"socket not found: {sock_path}")
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(str(sock_path))
            print(f"backend: ledd-direct socket={sock_path}", flush=True)
        else:
            sock_path = Path(args.socket)
            if not sock_path.exists():
                raise SystemExit(f"socket not found: {sock_path}")
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(str(sock_path))
            led_count = read_led_count(sock)
            if led_count != len(data["leds"]):
                print(f"warning: config LEDs={len(data['leds'])}, viald LEDs={led_count}", flush=True)
            original_mode = read_mode(sock)
            set_mode(sock, 1, 128, 0, 0, 0)
            print(f"backend: direct original_mode={original_mode}", flush=True)

        next_frame = time.monotonic()
        deadline = time.monotonic() + args.seconds if args.seconds > 0 else None
        while not _stop_requested:
            if deadline is not None and time.monotonic() >= deadline:
                break
            frame_start = time.monotonic()
            ret, frame = cap.read()
            if not ret:
                if args.once:
                    break
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue

            colors_bgr = sample_frame_bgr(frame, crop, target_w, target_h, px9, py9, map_idx)
            colors_bgr = apply_max_brightness(colors_bgr, max_brightness)
            if args.backend == "hardware":
                render_hardware(strip, colors_bgr)
            elif args.backend == "ledd-direct":
                assert sock is not None
                send_ledd_direct_frame(sock, frames, colors_bgr)
                packets += 1
            else:
                assert sock is not None
                frame_hsv = bgr_to_vial_hsv(colors_bgr)
                for first, pixels in frame_chunks(frame_hsv):
                    direct_fastset(sock, first, pixels)
                    packets += 1
            frames += 1

            next_frame += frame_delay
            sleep_time = next_frame - time.monotonic()
            if sleep_time > 0:
                time.sleep(sleep_time)
            elif frame_start - next_frame > 1.0:
                next_frame = time.monotonic()
    finally:
        cap.release()
        if sock is not None:
            try:
                if args.backend == "direct" and original_mode is not None and not args.no_restore:
                    set_mode(sock, *original_mode)
                    print(f"restored mode={original_mode[0]} speed={original_mode[1]} hsv={original_mode[2:]}", flush=True)
            finally:
                sock.close()
        elapsed = max(0.001, time.monotonic() - started)
        print(
            f"played frames={frames} fps={frames / elapsed:.1f} packets={packets} packets/s={packets / elapsed:.1f}",
            flush=True,
        )
        release_singleton()


if __name__ == "__main__":
    try:
        try:
            main()
        except BrokenPipeError:
            sys.exit(1)
    finally:
        release_singleton()
