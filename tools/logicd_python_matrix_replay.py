#!/usr/bin/env python3
"""Replay matrix packets through an isolated Python logicd runtime."""
from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.config_runtime import apply_runtime_config  # noqa: E402
from logicd.input_events import InputEventContext, process_matrix_event  # noqa: E402
from logicd.state import LogicdRuntime  # noqa: E402
from usbd.hid_report_broker import decode_hid_report_request  # noqa: E402


def parse_matrix_stream(data: bytes) -> list[tuple[str, int, int]]:
    if len(data) % 4 != 0:
        raise ValueError(f"matrix stream length must be multiple of 4: {len(data)}")
    events: list[tuple[str, int, int]] = []
    for offset in range(0, len(data), 4):
        packet = data[offset : offset + 4]
        if packet[0] not in (ord("P"), ord("R")):
            raise ValueError(f"invalid event type at packet {offset // 4}: 0x{packet[0]:02x}")
        try:
            row = int(chr(packet[1]), 16)
            col = int(chr(packet[2]), 16)
        except ValueError as exc:
            raise ValueError(f"invalid row/col at packet {offset // 4}: {packet!r}") from exc
        events.append((chr(packet[0]), row, col))
    return events


def flatten_keymap(path: Path) -> list[dict[str, str]]:
    keymap = json.loads(path.read_text(encoding="utf-8"))
    layers = keymap.get("layers", [])
    layout_def = keymap.get("_layout_def")
    if not isinstance(layers, list):
        return [{}]
    if not isinstance(layout_def, dict):
        return [dict(layer) for layer in layers if isinstance(layer, dict)] or [{}]
    result: list[dict[str, str]] = []
    for layer in layers:
        flat: dict[str, str] = {}
        if not isinstance(layer, dict):
            result.append(flat)
            continue
        for group, coords in layout_def.items():
            actions = layer.get(group, [])
            if not isinstance(coords, list) or not isinstance(actions, list):
                continue
            for coord, action in zip(coords, actions):
                if (
                    isinstance(coord, list)
                    and len(coord) >= 2
                    and isinstance(coord[0], int)
                    and isinstance(coord[1], int)
                    and isinstance(action, str)
                    and action
                ):
                    flat[f"{coord[0]},{coord[1]}"] = action
        result.append(flat)
    return result or [{}]


def load_config(
    path: Path,
    broker_socket: Path,
    *,
    keymap_path: Path,
    disable_split_keyboard: bool,
) -> dict[str, Any]:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["layers"] = flatten_keymap(keymap_path)
    settings = cfg.setdefault("settings", {})
    settings["outputs"] = ["gadget"]
    settings["usbd_hid_report_broker"] = True
    settings["usbd_hid_report_socket"] = str(broker_socket)
    if disable_split_keyboard:
        settings["usb_split_keyboard"] = {"enabled": False}
    return cfg


def drain_frames(sock: socket.socket) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    while True:
        try:
            raw = sock.recv(64)
        except TimeoutError:
            break
        except socket.timeout:
            break
        request = decode_hid_report_request(raw)
        frames.append(
            {
                "t": "broker_frame",
                "kind": request.kind,
                "kind_name": request.kind_name,
                "payload": request.payload.hex(),
                "frame": raw.hex(),
            }
        )
    return frames


async def run_replay(args: argparse.Namespace) -> list[dict[str, Any]]:
    events = parse_matrix_stream(args.replay_file.read_bytes())
    with tempfile.TemporaryDirectory() as tmpdir:
        broker_socket = Path(tmpdir) / "python-logicd-broker.sock"
        receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        receiver.settimeout(args.drain_timeout)
        receiver.bind(str(broker_socket))
        try:
            cfg = load_config(
                args.config,
                broker_socket,
                keymap_path=args.keymap,
                disable_split_keyboard=not args.keep_split_keyboard,
            )
            runtime = LogicdRuntime()
            apply_runtime_config(
                cfg,
                runtime,
                default_script_dir=str(ROOT / "config/default/script"),
                fallback_script_dir=str(ROOT / "config/default/script"),
                matrix_in_range=lambda _row, _col: True,
                push_ledd_mode=lambda _mode: None,
                push_i2cd_mode=lambda _mode: None,
                broadcast_key_event=lambda _row, _col, _pressed: None,
                push_i2cd_script_exit=lambda _name, _code: None,
            )
            runtime.current_hid_mode = "gadget"
            drain_frames(receiver)
            ctx = InputEventContext(
                layers=runtime.layers,
                interactions=runtime.interactions,
                macros=runtime.macros,
                encoders=runtime.encoders,
                joysticks=runtime.joysticks,
                pressed_matrix=runtime.pressed_matrix,
                push_ledd_key_event=lambda _row, _col, _pressed: None,
                push_ledd_status=lambda: None,
                push_i2cd_status=lambda: None,
                push_i2cd_alert=lambda *args, **kwargs: None,
                push_ledd_anim=lambda _mode: None,
                apply_lighting_key_action=lambda _action, _pressed: False,
                mouse_write_fn=runtime.mouse_write_fn,
                bt_manager=None,
                wifi_manager=None,
            )
            frames: list[dict[str, Any]] = []
            for event in events:
                await process_matrix_event(event, ctx)
                for frame in drain_frames(receiver):
                    frame["event"] = {"kind": event[0], "row": event[1], "col": event[2]}
                    frames.append(frame)
            return frames
        finally:
            receiver.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replay_file", type=Path)
    parser.add_argument("--config", type=Path, default=ROOT / "config/default/config.json")
    parser.add_argument("--keymap", type=Path, default=ROOT / "config/default/keymap.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--drain-timeout", type=float, default=0.05)
    parser.add_argument(
        "--keep-split-keyboard",
        action="store_true",
        help="keep config usb_split_keyboard route instead of forcing M0-comparable keyboard kind",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    frames = asyncio.run(run_replay(args))
    if args.output.parent:
        args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(frame, sort_keys=True) + "\n" for frame in frames),
        encoding="utf-8",
    )
    print(json.dumps({"result": "ok", "frames": len(frames), "output": str(args.output)}, sort_keys=True))


if __name__ == "__main__":
    main()
