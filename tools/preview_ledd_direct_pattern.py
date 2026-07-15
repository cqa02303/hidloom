#!/usr/bin/env python3
"""Preview a Vial direct-style pattern rendered inside ledd."""
from __future__ import annotations

import argparse
import json
import os
import socket
import time
from pathlib import Path
from typing import Iterable

DEFAULT_PROCESSES = ("viald", "logicd", "ledd")


def json_request(sock_path: str, msg: dict) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(sock_path)
        sock.sendall((json.dumps(msg) + "\n").encode("utf-8"))
        data = sock.recv(65536)
    return json.loads(data.decode("utf-8")) if data else {}


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
    parser = argparse.ArgumentParser(description="Preview ledd internal Vial direct-style pattern")
    parser.add_argument("--ctrl", default="/tmp/ctrl_events.sock")
    parser.add_argument("--seconds", type=float, default=8.0)
    parser.add_argument("--fps", type=float, default=16.0)
    parser.add_argument("--brightness", type=int, default=96)
    parser.add_argument("--pattern", choices=("rainbow", "chase", "pulse"), default="rainbow")
    parser.add_argument("--restore", action="store_true", help="restore the original VialRGB mode at the end")
    parser.add_argument("--cpu", action="store_true", help="print approximate CPU usage for viald/logicd/ledd")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.seconds <= 0:
        raise SystemExit("--seconds must be > 0")
    if args.fps <= 0:
        raise SystemExit("--fps must be > 0")

    original = json_request(args.ctrl, {"t": "LED", "op": "vialrgb_get"})
    if original.get("result") != "ok":
        raise SystemExit(f"failed to read original LED state: {original}")

    cpu_start = sample_process_cpu(DEFAULT_PROCESSES) if args.cpu else {}
    wall_start = time.monotonic()
    try:
        response = json_request(args.ctrl, {
            "t": "LED",
            "op": "vialrgb_direct_pattern",
            "pattern": args.pattern,
            "fps": args.fps,
            "brightness": args.brightness,
        })
        if response.get("result") != "ok":
            raise SystemExit(f"failed to start direct pattern: {response}")
        print(
            f"ledd direct pattern: pattern={response['pattern']} "
            f"target_fps={float(response['fps']):.1f} seconds={args.seconds:.1f} "
            f"brightness={response['brightness']}",
            flush=True,
        )
        time.sleep(args.seconds)
    finally:
        if args.restore:
            restore = json_request(args.ctrl, {
                "t": "LED",
                "op": "vialrgb",
                "mode": original["mode"],
                "speed": original["speed"],
                "h": original["h"],
                "s": original["s"],
                "v": original["v"],
            })
            print(f"restored mode={original['mode']} response={restore.get('result')}", flush=True)

    elapsed = max(0.001, time.monotonic() - wall_start)
    expected_frames = args.seconds * args.fps
    print(f"expected frames={expected_frames:.0f} fps={args.fps:.1f} socket_packets=1", flush=True)

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
