"""logicd writers for the optional usbd USB HID report broker."""
from __future__ import annotations

import logging
import os
import socket
from collections.abc import Callable

from usbd.hid_report_broker import (
    KIND_CONSUMER,
    KIND_KEYBOARD,
    KIND_MOUSE,
    KIND_US_SUB_KEYBOARD,
    encode_hid_report_request,
)

log = logging.getLogger(__name__)

DEFAULT_USBD_HID_REPORT_SOCKET = "/tmp/usbd_hid_reports.sock"


def env_flag_enabled(value: object) -> bool:
    """Return true for common opt-in flag spellings."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def create_usbd_hid_report_writer(kind: int, socket_path: str) -> Callable[[bytes], None]:
    """Return a writer that sends canonical HID payloads to usbd."""
    path = str(socket_path)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)

    def write(payload: bytes) -> None:
        try:
            frame = encode_hid_report_request(kind, bytes(payload))
            sock.sendto(frame, path)
        except ValueError:
            raise
        except OSError as exc:
            log.warning("usbd HID report broker write failed (%s): %s", path, exc)

    return write


__all__ = [
    "DEFAULT_USBD_HID_REPORT_SOCKET",
    "KIND_CONSUMER",
    "KIND_KEYBOARD",
    "KIND_MOUSE",
    "KIND_US_SUB_KEYBOARD",
    "create_usbd_hid_report_writer",
    "env_flag_enabled",
]
