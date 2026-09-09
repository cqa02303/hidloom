#!/usr/bin/env python3
"""Compose Python mutations and real native owner, capturing only fixture HID."""
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "daemon"), str(ROOT), str(ROOT / "script")]
from logicd.keymap import LayerManager
from logicd.keymap_coordinator import KeymapCoordinator
from test_logicd_core_rs_tool import BIN, build_tool, core_env, flat_keymap, wait_for_socket
from usbd.hid_report_broker import KIND_KEYBOARD, encode_hid_report_request


async def main():
    if "HIDLOOM_TEST_CORE_BINARY" not in os.environ:
        build_tool()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        keymap = {"_layout_def": {"matrix": [[0, 0]]}, "layers": [{"matrix": ["KC_A"]}]}
        env = core_env(root, keymap)
        runtime = root / "keymap.json"
        default = root / "default-keymap.json"
        default.write_bytes(runtime.read_bytes())
        ctrl, matrix, sink = (root / name for name in ("ctrl.sock", "matrix.sock", "sink.sock"))
        env.update(LOGICD_CORE_MATRIX_SOCKET=str(matrix), LOGICD_CORE_CTRL_SOCKET=str(ctrl), LOGICD_CORE_HID_REPORT_SOCKET=str(sink), LOGICD_CORE_OUTPUT_ENABLED="1", LOGICD_CORE_STATUS_PATH=str(root / "status.json"), LOGICD_CORE_DELEGATE_SOCKET="none")
        broker = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        broker.bind(str(sink))
        broker.setblocking(False)
        binary = os.environ.get("HIDLOOM_TEST_CORE_BINARY", str(BIN))
        process = subprocess.Popen([binary, "--serve"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            await asyncio.to_thread(wait_for_socket, ctrl)
            async def request(payload):
                reader, writer = await asyncio.open_unix_connection(str(ctrl))
                try:
                    writer.write(json.dumps(payload).encode() + b"\n")
                    await writer.drain()
                    return json.loads(await reader.readline())
                finally:
                    writer.close()
                    await writer.wait_closed()
            async def event(packet):
                _, writer = await asyncio.open_unix_connection(str(matrix))
                writer.write(packet)
                await writer.drain()
                writer.close()
                await writer.wait_closed()
                return await asyncio.wait_for(asyncio.get_running_loop().sock_recv(broker, 128), 2.0)
            layers = LayerManager()
            layers.load([{"0,0": "KC_A"}])
            coordinator = KeymapCoordinator(layers, runtime, default, lambda r,c: r == 0 and c == 0, native_request=request)
            before_disk = runtime.read_bytes()
            changed = await coordinator.execute({"t": "M", "l": 0, "r": 0, "c": 0, "a": "KC_B"})
            assert changed["result"] == "ok", changed
            assert runtime.read_bytes() == before_disk, "ordinary M must preserve disk debounce"
            assert await event(b"P00\n") == encode_hid_report_request(KIND_KEYBOARD, bytes([0,0,5,0,0,0,0,0]))
            remapped_held = await coordinator.execute({"t": "M", "l": 0, "r": 0, "c": 0, "a": "KC_C"})
            assert remapped_held["result"] == "ok", remapped_held
            assert await event(b"R00\n") == encode_hid_report_request(KIND_KEYBOARD, bytes(8))
            assert await event(b"P00\n") == encode_hid_report_request(KIND_KEYBOARD, bytes([0,0,6,0,0,0,0,0]))
            assert (await coordinator.execute({"t": "S"}))["result"] == "ok"
            assert await event(b"R00\n") == encode_hid_report_request(KIND_KEYBOARD, bytes(8))
            for message, count in (({"t": "LAYER_ADD"}, 2), ({"t": "LAYER_CLEAR", "l": 1}, 1), ({"t": "RESET_KEYMAP"}, 1)):
                response = await coordinator.execute(message)
                assert response["result"] == "ok" and response["persisted"], response
                owner = await request({"t": "owner_state", "include_keymap": True})
                assert len(owner["layers"]) == count
            assert await event(b"P00\n") == encode_hid_report_request(KIND_KEYBOARD, bytes([0,0,4,0,0,0,0,0]))
            assert await event(b"R00\n") == encode_hid_report_request(KIND_KEYBOARD, bytes(8))
        finally:
            process.terminate()
            process.communicate(timeout=3)
            broker.close()
    print("keymap coordinator native compose: ok")


if __name__ == "__main__":
    asyncio.run(main())
