"""Linux uinput output helpers for logicd."""
from __future__ import annotations

import logging
import os
import struct
import time
from collections.abc import Callable

from .hid_report import HID_CONSUMER_TO_LINUX, HID_TO_LINUX, MODIFIER_BIT_TO_LINUX, add_hid_report_id

log = logging.getLogger(__name__)


def make_consumer_report_fn(
    write_report: Callable[[bytes], None],
    uinput_shared_ref: list,
) -> Callable[[int, bool], None]:
    """Return Consumer Control writer for gadget mode with uinput fallback."""
    def consumer_fn(usage_id: int, is_press: bool) -> None:
        report = struct.pack("<H", usage_id if is_press else 0)
        try:
            write_report(report)
            return
        except OSError:
            pass

        _write_consumer_uinput(usage_id, is_press, uinput_shared_ref)

    return consumer_fn


def _write_consumer_uinput(usage_id: int, is_press: bool, uinput_shared_ref: list) -> None:
    ufd = uinput_shared_ref[0]
    if ufd is None:
        return
    linux_key = HID_CONSUMER_TO_LINUX.get(usage_id)
    if linux_key is None:
        log.debug("Consumer usage 0x%04X has no Linux key mapping", usage_id)
        return
    value = 1 if is_press else 0
    try:
        event = struct.pack("llHHi", 0, 0, 1, linux_key, value)
        sync = struct.pack("llHHi", 0, 0, 0, 0, 0)
        os.write(ufd, event)
        os.write(ufd, sync)
    except OSError:
        pass


def make_consumer_fn(
    consumer_hidg_path: str,
    uinput_shared_ref: list,
    *,
    report_id: int | None = None,
) -> Callable[[int, bool], None]:
    """Return Consumer Control writer for a gadget path with uinput fallback."""
    fd_box: list = [None]
    last_reopen: list = [0.0]
    reopen_interval = 1.0

    def consumer_fn(usage_id: int, is_press: bool) -> None:
        if fd_box[0] is None:
            now = time.monotonic()
            if now - last_reopen[0] >= reopen_interval:
                last_reopen[0] = now
                try:
                    fd_box[0] = os.open(consumer_hidg_path, os.O_WRONLY | os.O_NONBLOCK)
                    log.debug("Consumer gadget opened: %s", consumer_hidg_path)
                except OSError:
                    pass

        if fd_box[0] is not None:
            report = struct.pack("<H", usage_id if is_press else 0)
            if report_id is not None:
                report = add_hid_report_id(report_id, report)
            try:
                os.write(fd_box[0], report)
                return
            except OSError:
                fd_box[0] = None

        _write_consumer_uinput(usage_id, is_press, uinput_shared_ref)

    return consumer_fn


def create_uinput_write_fn(cfg: dict, uinput_shared_ref: list | None = None) -> Callable[[bytes], None]:
    """Return a writer that converts keyboard HID reports into uinput events."""
    uinput_fd = None
    pressed_keys = set()
    hid_to_linux = HID_TO_LINUX
    modifier_to_linux = MODIFIER_BIT_TO_LINUX

    def setup_uinput(cfg: dict) -> bool:
        nonlocal uinput_fd
        try:
            import fcntl

            device_config = cfg.get("device", {})
            uinput_config = cfg.get("uinput", {})
            repeat_delay = uinput_config.get("repeat_delay_ms", 500)
            repeat_period = uinput_config.get("repeat_period_ms", 100)
            device_name = uinput_config.get("device_name", "Virtual Keyboard")
            vendor_id = int(device_config.get("vendor_id", "0x1234"), 16)
            product_id = int(device_config.get("product_id", "0x5678"), 16)

            uinput_fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)

            fcntl.ioctl(uinput_fd, 0x40045564, 1)     # UI_SET_EVBIT, EV_KEY
            fcntl.ioctl(uinput_fd, 0x40045564, 0)     # UI_SET_EVBIT, EV_SYN
            fcntl.ioctl(uinput_fd, 0x40045564, 0x14)  # UI_SET_EVBIT, EV_REP

            for linux_key in hid_to_linux.values():
                fcntl.ioctl(uinput_fd, 0x40045565, linux_key)
            for linux_key in modifier_to_linux.values():
                fcntl.ioctl(uinput_fd, 0x40045565, linux_key)
            for linux_key in HID_CONSUMER_TO_LINUX.values():
                fcntl.ioctl(uinput_fd, 0x40045565, linux_key)

            dev_info = struct.pack(
                "80sHHHHI64I64I64I64I",
                device_name.encode("ascii")[:80], 3, vendor_id, product_id, 1, 0,
                *([0] * 256),
            )
            os.write(uinput_fd, dev_info)
            fcntl.ioctl(uinput_fd, 0x5501)  # UI_DEV_CREATE

            try:
                time.sleep(0.05)
                repeat_delay_event = struct.pack("llHHi", 0, 0, 0x14, 0, repeat_delay)
                os.write(uinput_fd, repeat_delay_event)
                repeat_period_event = struct.pack("llHHi", 0, 0, 0x14, 1, repeat_period)
                os.write(uinput_fd, repeat_period_event)
                sync = struct.pack("llHHi", 0, 0, 0, 0, 0)
                os.write(uinput_fd, sync)
                log.info("Key repeat settings configured (delay=%sms, period=%sms)", repeat_delay, repeat_period)
            except Exception as exc:
                log.warning("Key repeat setup failed (non-critical): %s", exc)

            log.info("Simple virtual keyboard created")
            if uinput_shared_ref is not None:
                uinput_shared_ref[0] = uinput_fd
            return True
        except Exception as exc:
            log.error("Failed to setup uinput: %s", exc)
            if uinput_fd:
                try:
                    os.close(uinput_fd)
                except OSError:
                    pass
                uinput_fd = None
            return False

    def send_key_event(key_code: int, value: int) -> None:
        if not uinput_fd:
            return
        try:
            event = struct.pack("llHHi", 0, 0, 1, key_code, value)
            sync = struct.pack("llHHi", 0, 0, 0, 0, 0)
            os.write(uinput_fd, event)
            os.write(uinput_fd, sync)
        except Exception as exc:
            log.warning("Key event failed: %s", exc)

    if not setup_uinput(cfg):
        def _write_fallback(data: bytes) -> None:
            log.debug("uinput unavailable, using fallback")
        return _write_fallback

    def _write_uinput(data: bytes) -> None:
        if len(data) < 8 or not uinput_fd:
            return

        modifier = data[0]
        keys = [k for k in data[2:8] if k != 0]
        current_keys = set()

        for bit, linux_key in modifier_to_linux.items():
            if modifier & bit:
                current_keys.add(linux_key)
                if linux_key not in pressed_keys:
                    send_key_event(linux_key, 1)
                    pressed_keys.add(linux_key)
                    log.debug("Virtual modifier press: %d (bit=0x%02x)", linux_key, bit)
            elif linux_key in pressed_keys:
                send_key_event(linux_key, 0)
                pressed_keys.discard(linux_key)
                log.debug("Virtual modifier release: %d", linux_key)

        for hid_key in keys:
            linux_key = hid_to_linux.get(hid_key)
            if linux_key:
                current_keys.add(linux_key)
                if linux_key not in pressed_keys:
                    send_key_event(linux_key, 1)
                    pressed_keys.add(linux_key)
                    log.debug("Virtual key press: %d (HID=0x%02x)", linux_key, hid_key)

        for linux_key in list(pressed_keys):
            if linux_key not in current_keys and linux_key not in modifier_to_linux.values():
                send_key_event(linux_key, 0)
                pressed_keys.discard(linux_key)
                log.debug("Virtual key release: %d", linux_key)

    return _write_uinput
