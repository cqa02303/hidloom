#!/usr/bin/env python3
"""Regression test for opt-in logicd -> usbd HID report broker output."""
from __future__ import annotations

import asyncio
import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.config_runtime import apply_runtime_config  # noqa: E402
from logicd.input_events import InputEventContext, handle_analog_stick  # noqa: E402
from logicd.joystick import JoystickBinding, JoystickManager  # noqa: E402
from logicd.spid_motion import SpidMotionHandler  # noqa: E402
from logicd.state import LogicdRuntime  # noqa: E402
from usbd.hid_report_broker import (  # noqa: E402
    KIND_CONSUMER,
    KIND_KEYBOARD,
    KIND_MOUSE,
    KIND_US_SUB_KEYBOARD,
    decode_hid_report_request,
)


def _recv_request(receiver: socket.socket):
    return decode_hid_report_request(receiver.recv(64))


class EmptyEncoders:
    def handles(self, row: int, col: int) -> bool:
        return False


def _apply_broker_runtime(socket_path: str, *, split_route: str | None = None) -> LogicdRuntime:
    runtime = LogicdRuntime()
    runtime.current_hid_mode = "gadget"
    usb_split_keyboard: dict[str, object] = {"enabled": True}
    if split_route is not None:
        usb_split_keyboard["route"] = split_route
    apply_runtime_config(
        {
            "settings": {
                "hidg": "/dev/hidg0",
                "mouse_hidg": "/dev/hidg0",
                "consumer_hidg": "/dev/hidg0",
                "console_fallback": True,
                "outputs": ["gadget"],
                "usbd_hid_report_broker": True,
                "usbd_hid_report_socket": socket_path,
                "usb_split_keyboard": usb_split_keyboard,
            },
            "layers": [{}],
            "macros": {},
        },
        runtime,
        default_script_dir="config/default/script",
        fallback_script_dir="config/default/script",
        matrix_in_range=lambda _row, _col: True,
        push_ledd_mode=lambda _mode: None,
        push_i2cd_mode=lambda _mode: None,
        broadcast_key_event=lambda _row, _col, _pressed: None,
        push_i2cd_script_exit=lambda _name, _code: None,
    )
    runtime.current_hid_mode = "gadget"
    return runtime


async def _run() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        socket_path = str(Path(tmpdir) / "usbd_hid_reports.sock")
        receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        receiver.settimeout(2.0)
        try:
            receiver.bind(socket_path)
            runtime = _apply_broker_runtime(socket_path)

            runtime.macros._write(bytes([0, 0, 0x04, 0, 0, 0, 0, 0]))
            runtime.macros._write(bytes([0, 0, 0x87, 0, 0, 0, 0, 0]))
            runtime.macros._write(bytes(8))
            runtime.macros._write(bytes([0, 0, 0x8A, 0, 0, 0, 0, 0]))
            runtime.macros._write(bytes(8))
            runtime.macros._write(bytes([0, 0, 0x90, 0, 0, 0, 0, 0]))
            runtime.macros._write(bytes(8))
            runtime.mouse_write_fn(bytes([0x01, 0x02, 0x03, 0x04]))
            runtime.macros._consumer(0x00E9, True)

            keyboard = _recv_request(receiver)
            us_sub_ro = _recv_request(receiver)
            us_sub_ro_release = _recv_request(receiver)
            us_sub_henkan = _recv_request(receiver)
            us_sub_release = _recv_request(receiver)
            us_sub_lang1 = _recv_request(receiver)
            us_sub_lang1_release = _recv_request(receiver)
            mouse = _recv_request(receiver)
            consumer = _recv_request(receiver)
        finally:
            receiver.close()

    assert keyboard.kind == KIND_KEYBOARD
    assert keyboard.payload == bytes([0, 0, 0x04, 0, 0, 0, 0, 0])
    assert us_sub_ro.kind == KIND_US_SUB_KEYBOARD
    assert us_sub_ro.payload == bytes([0, 0, 0x87, 0, 0, 0, 0, 0])
    assert us_sub_ro_release.kind == KIND_US_SUB_KEYBOARD
    assert us_sub_ro_release.payload == bytes(8)
    assert us_sub_henkan.kind == KIND_US_SUB_KEYBOARD
    assert us_sub_henkan.payload == bytes([0, 0, 0x8A, 0, 0, 0, 0, 0])
    assert us_sub_release.kind == KIND_US_SUB_KEYBOARD
    assert us_sub_release.payload == bytes(8)
    assert us_sub_lang1.kind == KIND_US_SUB_KEYBOARD
    assert us_sub_lang1.payload == bytes([0, 0, 0x90, 0, 0, 0, 0, 0])
    assert us_sub_lang1_release.kind == KIND_US_SUB_KEYBOARD
    assert us_sub_lang1_release.payload == bytes(8)
    assert mouse.kind == KIND_MOUSE
    assert mouse.payload == bytes([0x01, 0x02, 0x03, 0x04])
    assert consumer.kind == KIND_CONSUMER
    assert consumer.payload == bytes.fromhex("e900")


async def _run_split_route_all() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        socket_path = str(Path(tmpdir) / "usbd_hid_reports.sock")
        receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        receiver.settimeout(2.0)
        try:
            receiver.bind(socket_path)
            runtime = _apply_broker_runtime(socket_path, split_route="all")

            runtime.macros._write(bytes([0, 0, 0x04, 0, 0, 0, 0, 0]))
            runtime.macros._write(bytes(8))
            runtime.mouse_write_fn(bytes([0x01, 0x02, 0x03, 0x04]))

            us_sub_keyboard = _recv_request(receiver)
            us_sub_release = _recv_request(receiver)
            mouse = _recv_request(receiver)
        finally:
            receiver.close()

    assert us_sub_keyboard.kind == KIND_US_SUB_KEYBOARD
    assert us_sub_keyboard.payload == bytes([0, 0, 0x04, 0, 0, 0, 0, 0])
    assert us_sub_release.kind == KIND_US_SUB_KEYBOARD
    assert us_sub_release.payload == bytes(8)
    assert mouse.kind == KIND_MOUSE
    assert mouse.payload == bytes([0x01, 0x02, 0x03, 0x04])


async def _run_jis_special_us_default_route() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        socket_path = str(Path(tmpdir) / "usbd_hid_reports.sock")
        receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        receiver.settimeout(2.0)
        try:
            receiver.bind(socket_path)
            runtime = _apply_broker_runtime(socket_path, split_route="jis_special_us_default")

            runtime.macros._write(bytes([0, 0, 0x04, 0, 0, 0, 0, 0]))  # KC_A: normal key
            normal = _recv_request(receiver)
            runtime.macros._write(bytes(8))
            normal_release = _recv_request(receiver)
            runtime.macros._write(bytes([0, 0, 0x88, 0, 0, 0, 0, 0]))  # KC_KANA: JIS main Kana lock key
            kana = _recv_request(receiver)
            runtime.macros._write(bytes(8))
            kana_release = _recv_request(receiver)
            runtime.macros._write(bytes([0, 0, 0x87, 0, 0, 0, 0, 0]))  # KC_RO: JIS-only key
            ro = _recv_request(receiver)
            runtime.macros._write(bytes(8))
            ro_release = _recv_request(receiver)
            runtime.macros._write(bytes([0, 0, 0x89, 0, 0, 0, 0, 0]))  # KC_JYEN: JIS-only key
            jyen = _recv_request(receiver)
            runtime.macros._write(bytes(8))
            jyen_release = _recv_request(receiver)
            runtime.macros._write(bytes([0, 0, 0x8A, 0, 0, 0, 0, 0]))  # KC_HENKAN
            henkan = _recv_request(receiver)
            runtime.macros._write(bytes(8))
            henkan_release = _recv_request(receiver)
            runtime.macros._write(bytes([0, 0, 0x8B, 0, 0, 0, 0, 0]))  # KC_MUHENKAN
            muhenkan = _recv_request(receiver)
            runtime.macros._write(bytes(8))
            muhenkan_release = _recv_request(receiver)
            await runtime.macros.handle("KC_GRV", True)
            grave = _recv_request(receiver)
            await runtime.macros.handle("KC_GRV", False)
            grave_release = _recv_request(receiver)
            await runtime.macros.handle("KC_ZKHK", True)
            zkhk = _recv_request(receiver)
            await runtime.macros.handle("KC_ZKHK", False)
            zkhk_release = _recv_request(receiver)
        finally:
            receiver.close()

    assert normal.kind == KIND_US_SUB_KEYBOARD
    assert normal.payload == bytes([0, 0, 0x04, 0, 0, 0, 0, 0])
    assert normal_release.kind == KIND_US_SUB_KEYBOARD
    assert normal_release.payload == bytes(8)
    assert kana.kind == KIND_KEYBOARD
    assert kana.payload == bytes([0, 0, 0x88, 0, 0, 0, 0, 0])
    assert kana_release.kind == KIND_KEYBOARD
    assert kana_release.payload == bytes(8)
    assert ro.kind == KIND_KEYBOARD
    assert ro.payload == bytes([0, 0, 0x87, 0, 0, 0, 0, 0])
    assert ro_release.kind == KIND_KEYBOARD
    assert ro_release.payload == bytes(8)
    assert jyen.kind == KIND_KEYBOARD
    assert jyen.payload == bytes([0, 0, 0x89, 0, 0, 0, 0, 0])
    assert jyen_release.kind == KIND_KEYBOARD
    assert jyen_release.payload == bytes(8)
    assert henkan.kind == KIND_KEYBOARD
    assert henkan.payload == bytes([0, 0, 0x8A, 0, 0, 0, 0, 0])
    assert henkan_release.kind == KIND_KEYBOARD
    assert henkan_release.payload == bytes(8)
    assert muhenkan.kind == KIND_KEYBOARD
    assert muhenkan.payload == bytes([0, 0, 0x8B, 0, 0, 0, 0, 0])
    assert muhenkan_release.kind == KIND_KEYBOARD
    assert muhenkan_release.payload == bytes(8)
    assert grave.kind == KIND_US_SUB_KEYBOARD
    assert grave.payload == bytes([0, 0, 0x35, 0, 0, 0, 0, 0])
    assert grave_release.kind == KIND_US_SUB_KEYBOARD
    assert grave_release.payload == bytes(8)
    assert zkhk.kind == KIND_KEYBOARD
    assert zkhk.payload == bytes([0, 0, 0x35, 0, 0, 0, 0, 0])
    assert zkhk_release.kind == KIND_KEYBOARD
    assert zkhk_release.payload == bytes(8)


async def _run_mouse_sources() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        socket_path = str(Path(tmpdir) / "usbd_hid_reports.sock")
        receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        receiver.settimeout(2.0)
        try:
            receiver.bind(socket_path)
            runtime = _apply_broker_runtime(socket_path)
            runtime.layers.load([{"2,2": "KC_MS_R"}])
            runtime.joysticks = JoystickManager(
                [
                    JoystickBinding(
                        name="stick0",
                        up=(0, 0),
                        left=(1, 1),
                        right=(2, 2),
                        down=(3, 3),
                    )
                ]
            )
            ctx = InputEventContext(
                layers=runtime.layers,
                interactions=runtime.interactions,
                macros=runtime.macros,
                encoders=EmptyEncoders(),
                joysticks=runtime.joysticks,
                pressed_matrix=set(),
                push_ledd_key_event=lambda *_args: None,
                push_ledd_status=lambda: None,
                push_i2cd_status=lambda: None,
                push_i2cd_alert=lambda *_args, **_kwargs: None,
                push_ledd_anim=lambda *_args: None,
                apply_lighting_key_action=lambda *_args: False,
                mouse_write_fn=runtime.mouse_write_fn,
                bt_manager=None,
            )

            await handle_analog_stick(0, 80, 0, ctx)
            analog = _recv_request(receiver)

            await runtime.macros.handle("KC_MS_R", True)
            await asyncio.sleep(0.02)
            mouse_key = _recv_request(receiver)
            await runtime.macros.handle("KC_MS_R", False)
            mouse_key_reports = [mouse_key]
            while mouse_key_reports[-1].payload != bytes(4):
                mouse_key_reports.append(_recv_request(receiver))

            spid = SpidMotionHandler(runtime.mouse_write_fn, output_hz=100.0)
            assert spid.handle_line('{"t":"motion","dx":4,"dy":-2,"wheel":1,"buttons":0}') is True
            spid_report = _recv_request(receiver)
        finally:
            receiver.close()

    assert analog.kind == KIND_MOUSE
    assert analog.payload[0] == 0
    assert analog.payload[1] > 0
    assert analog.payload[2:] == bytes([0, 0])
    assert mouse_key.kind == KIND_MOUSE
    assert mouse_key.payload[1] > 0
    assert mouse_key_reports[-1].kind == KIND_MOUSE
    assert mouse_key_reports[-1].payload == bytes(4)
    assert spid_report.kind == KIND_MOUSE
    assert spid_report.payload == bytes([0, 4, 0xFE, 1])


def main() -> None:
    asyncio.run(_run())
    asyncio.run(_run_split_route_all())
    asyncio.run(_run_jis_special_us_default_route())
    asyncio.run(_run_mouse_sources())
    print("ok: logicd can route gadget reports through usbd HID report broker")


if __name__ == "__main__":
    main()
