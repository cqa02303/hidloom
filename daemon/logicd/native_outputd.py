"""Control helper for the native hidloom-outputd router."""
from __future__ import annotations

import json
import logging
import os
import socket
from collections.abc import Callable
from typing import Any

from usbd.hid_report_broker import encode_hid_report_request

log = logging.getLogger(__name__)

DEFAULT_OUTPUTD_REPORT_SOCKET = "/tmp/hidloom_output_reports.sock"
DEFAULT_OUTPUTD_CTRL_SOCKET = "/tmp/hidloom_output_ctrl.sock"


class OutputdControlError(RuntimeError):
    """Raised when hidloom-outputd rejects or misses a control request."""


def outputd_ctrl_socket_from_env() -> str:
    return os.environ.get("LOGICD_OUTPUTD_CTRL_SOCKET", DEFAULT_OUTPUTD_CTRL_SOCKET)


def outputd_report_socket_from_env() -> str:
    return os.environ.get("LOGICD_OUTPUTD_REPORT_SOCKET", DEFAULT_OUTPUTD_REPORT_SOCKET)


def native_outputd_control_enabled() -> bool:
    raw = os.environ.get("LOGICD_NATIVE_OUTPUTD_CTRL", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def create_outputd_report_writer(
    kind: int,
    socket_path: str | None = None,
) -> Callable[[bytes], None]:
    """Return a writer for canonical HID payloads routed through hidloom-outputd."""
    path = socket_path or outputd_report_socket_from_env()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)

    def write(payload: bytes) -> None:
        try:
            frame = encode_hid_report_request(kind, bytes(payload))
            sock.sendto(frame, path)
        except ValueError:
            raise
        except OSError as exc:
            log.warning("outputd report write failed (%s): %s", path, exc)

    setattr(write, "close", sock.close)
    return write


def send_outputd_request(
    message: dict[str, Any],
    *,
    socket_path: str | None = None,
    timeout_sec: float = 0.25,
) -> dict[str, Any]:
    path = socket_path or outputd_ctrl_socket_from_env()
    payload = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout_sec)
            sock.connect(path)
            sock.sendall(payload)
            response = sock.recv(4096)
    except OSError as exc:
        raise OutputdControlError(f"outputd ctrl unavailable: {path}: {exc}") from exc
    if not response:
        raise OutputdControlError("outputd ctrl returned empty response")
    try:
        decoded = json.loads(response.decode("utf-8").splitlines()[0])
    except (UnicodeDecodeError, json.JSONDecodeError, IndexError) as exc:
        raise OutputdControlError(f"invalid outputd ctrl response: {response!r}") from exc
    if decoded.get("result") != "ok":
        raise OutputdControlError(str(decoded.get("error") or decoded))
    return decoded


class NativeOutputdSwitchWriter:
    """Wrap a report writer while routing output switch keys to hidloom-outputd."""

    def __init__(
        self,
        inner: Callable[[bytes], None],
        *,
        socket_path: str | None = None,
        on_target_changed: Callable[[str], None] | None = None,
        request_fn: Callable[..., dict[str, Any]] = send_outputd_request,
    ) -> None:
        self._inner = inner
        self._socket_path = socket_path or outputd_ctrl_socket_from_env()
        self._on_target_changed = on_target_changed
        self._request_fn = request_fn

    def __call__(self, report: bytes) -> None:
        self._inner(report)

    def _set_native_target(self, outputd_target: str, display_target: str) -> None:
        response = self._request_fn(
            {"t": "set_output_target", "target": outputd_target},
            socket_path=self._socket_path,
        )
        if self._on_target_changed is not None:
            self._on_target_changed(display_target)
        log.info(
            "native outputd target switch: requested=%s response=%s",
            outputd_target,
            response.get("target"),
        )

    def force_auto(self) -> None:
        self._set_native_target("auto", "auto")

    def force_gadget(self) -> None:
        self._set_native_target("usb", "gadget")

    def force_uinput(self) -> None:
        self._set_native_target("uinput", "uinput")

    def force_bt(self) -> None:
        self._set_native_target("bt", "bt")

    def check_and_switch(self) -> None:
        fn = getattr(self._inner, "check_and_switch", None)
        if fn is not None:
            fn()

    @property
    def current_mode(self) -> str:
        mode = getattr(self._inner, "current_mode", "")
        return mode if isinstance(mode, str) else ""
