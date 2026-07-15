#!/usr/bin/env python3
"""USB bridge daemon.

Stage 1 responsibility:
  /dev/hidg1 Raw HID <-> /tmp/viald_events.sock

This daemon intentionally does not decode Vial packets. It only forwards
fixed-size Raw HID reports between the USB gadget endpoint and viald.
"""
from __future__ import annotations

import logging
import os
import socket
import sys
import threading
import time
import grp
import errno

from .hid_report_broker import (
    KIND_KEYBOARD,
    KIND_MOUSE,
    KIND_US_SUB_KEYBOARD,
    UsbReport,
    adapt_current_multi_report_profile,
    decode_hid_report_request,
)

log = logging.getLogger("usbd")

RAW_HID_PATH = os.environ.get("USBD_RAW_HID_PATH", "/dev/hidg1")
HID_REPORT_PATH = os.environ.get("USBD_HID_REPORT_PATH", "/dev/hidg0")
US_SUB_HID_REPORT_PATH = os.environ.get("USBD_US_SUB_HID_REPORT_PATH", "/dev/hidg2")
VIALD_SOCKET = os.environ.get("VIALD_EVENTS_SOCK", "/tmp/viald_events.sock")
WINDOWS_IME_SOCKET = os.environ.get("USBD_WINDOWS_IME_SOCKET", "/tmp/usbd_windows_ime.sock")
HID_REPORT_SOCKET = os.environ.get("USBD_HID_REPORT_SOCKET", "/tmp/usbd_hid_reports.sock")


def _env_int(name: str, default: int, *, min_value: int | None = None, max_value: int | None = None) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw, 0)
    except ValueError:
        log.warning("invalid %s=%r; using default %d", name, raw, default)
        return default
    if min_value is not None and value < min_value:
        log.warning("invalid %s=%d below minimum %d; using default %d", name, value, min_value, default)
        return default
    if max_value is not None and value > max_value:
        log.warning("invalid %s=%d above maximum %d; using default %d", name, value, max_value, default)
        return default
    return value


def _env_float(name: str, default: float, *, min_value: float | None = None) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        log.warning("invalid %s=%r; using default %.3f", name, raw, default)
        return default
    if min_value is not None and value < min_value:
        log.warning("invalid %s=%.3f below minimum %.3f; using default %.3f", name, value, min_value, default)
        return default
    return value


REPORT_SIZE = _env_int("USBD_REPORT_SIZE", 32, min_value=1, max_value=1024)
RETRY_SEC = _env_float("USBD_RETRY_SEC", 1.0, min_value=0.05)
SOCKET_TIMEOUT_SEC = _env_float("USBD_SOCKET_TIMEOUT_SEC", 2.0, min_value=0.1)
WINDOWS_IME_SOCKET_ENABLED = _env_int("USBD_WINDOWS_IME_SOCKET_ENABLED", 0, min_value=0, max_value=1)
HID_REPORT_SOCKET_ENABLED = _env_int("USBD_HID_REPORT_SOCKET_ENABLED", 0, min_value=0, max_value=1)
RAW_HID_BRIDGE_ENABLED = _env_int("USBD_RAW_HID_BRIDGE_ENABLED", 1, min_value=0, max_value=1)
HID_REPORT_LOG_ENABLED = _env_int("USBD_HID_REPORT_LOG", 0, min_value=0, max_value=1)
HID_WRITE_RETRY_TIMEOUT_SEC = _env_float("USBD_HID_WRITE_RETRY_TIMEOUT_SEC", 0.25, min_value=0.0)
HID_WRITE_RETRY_INTERVAL_SEC = _env_float("USBD_HID_WRITE_RETRY_INTERVAL_SEC", 0.002, min_value=0.0)
MOUSE_REPORT_HZ = _env_float("USBD_MOUSE_REPORT_HZ", 125.0, min_value=1.0)
KEYBOARD_REPORT_HZ = _env_float("USBD_KEYBOARD_REPORT_HZ", 500.0, min_value=1.0)
KEYBOARD_REPORT_DEDUP_ENABLED = _env_int("USBD_KEYBOARD_REPORT_DEDUP", 1, min_value=0, max_value=1)
KEYBOARD_RELEASE_MERGE_WINDOW_SEC = _env_float("USBD_KEYBOARD_RELEASE_MERGE_WINDOW_SEC", 0.016, min_value=0.0)

_HELP = """usage: python3 -m usbd.usbd

USB HID bridge daemon.

Options:
  -h, --help    show this help and exit

Common environment:
  LOG_LEVEL
  USBD_RAW_HID_PATH
  USBD_HID_REPORT_PATH
  USBD_US_SUB_HID_REPORT_PATH
  USBD_HID_REPORT_SOCKET
  USBD_HID_REPORT_SOCKET_ENABLED
  USBD_RAW_HID_BRIDGE_ENABLED
  USBD_REPORT_SIZE
  VIALD_EVENTS_SOCK
"""


def _clamp_i8(value: int) -> int:
    return max(-127, min(127, int(value)))


def _signed_i8(byte: int) -> int:
    byte = int(byte) & 0xFF
    return byte - 256 if byte >= 128 else byte


def _i8_byte(value: int) -> int:
    return _clamp_i8(value) & 0xFF


class MouseReportScheduler:
    """Coalesce USB mouse motion close to the gadget endpoint.

    Keyboard and consumer reports are latency-sensitive state transitions and
    bypass this scheduler. Mouse movement can be accumulated safely as long as
    button transitions are flushed immediately.
    """

    def __init__(
        self,
        *,
        output_hz: float = MOUSE_REPORT_HZ,
        clock=time.monotonic,
    ) -> None:
        self.output_interval = 1.0 / max(1.0, float(output_hz))
        self._clock = clock
        self._next_flush = self._clock()
        self.endpoint = HID_REPORT_PATH
        self.report_id = 0x02
        self.buttons = 0
        self.dx = 0
        self.dy = 0
        self.wheel = 0
        self._initialized = False
        self.coalesced_reports = 0

    def enqueue(self, report: UsbReport) -> list[UsbReport]:
        if report.kind != KIND_MOUSE:
            return [report]
        if len(report.report) != 5:
            return [report]

        report_id = report.report[0]
        buttons = report.report[1]
        dx = _signed_i8(report.report[2])
        dy = _signed_i8(report.report[3])
        wheel = _signed_i8(report.report[4])
        immediate: list[UsbReport] = []

        if not self._initialized:
            self.endpoint = report.endpoint
            self.report_id = report_id
            self.buttons = buttons
            self._initialized = True
        elif buttons != self.buttons:
            pending = self.flush(force=True)
            if pending is not None:
                immediate.append(pending)
            self.buttons = buttons
            self.endpoint = report.endpoint
            self.report_id = report_id
            immediate.append(self._make_report(0, 0, 0))
            self._next_flush = self._clock() + self.output_interval

        self.dx += dx
        self.dy += dy
        self.wheel += wheel
        if dx or dy or wheel:
            self.coalesced_reports += 1

        due = self.flush_due()
        if due is not None:
            immediate.append(due)
        return immediate

    def flush_due(self) -> UsbReport | None:
        now = self._clock()
        if now < self._next_flush:
            return None
        self._next_flush = now + self.output_interval
        return self.flush()

    def flush(self, *, force: bool = False) -> UsbReport | None:
        if not self._initialized:
            return None
        if self.dx == 0 and self.dy == 0 and self.wheel == 0:
            return None
        emit_dx = _clamp_i8(self.dx)
        emit_dy = _clamp_i8(self.dy)
        emit_wheel = _clamp_i8(self.wheel)
        self.dx -= emit_dx
        self.dy -= emit_dy
        self.wheel -= emit_wheel
        return self._make_report(emit_dx, emit_dy, emit_wheel)

    def time_until_flush(self) -> float:
        if not self._initialized or (self.dx == 0 and self.dy == 0 and self.wheel == 0):
            return 0.5
        return max(0.0, self._next_flush - self._clock())

    def _make_report(self, dx: int, dy: int, wheel: int) -> UsbReport:
        return UsbReport(
            self.endpoint,
            bytes([self.report_id, self.buttons & 0xFF, _i8_byte(dx), _i8_byte(dy), _i8_byte(wheel)]),
            KIND_MOUSE,
        )


class KeyboardReportPacer:
    """Pace keyboard state transitions without merging press/release pairs."""

    keyboard_kinds = frozenset({KIND_KEYBOARD, KIND_US_SUB_KEYBOARD})

    def __init__(
        self,
        *,
        output_hz: float = KEYBOARD_REPORT_HZ,
        dedup_enabled: bool = bool(KEYBOARD_REPORT_DEDUP_ENABLED),
        clock=time.monotonic,
        sleeper=time.sleep,
    ) -> None:
        self.output_interval = 1.0 / max(1.0, float(output_hz))
        self.dedup_enabled = bool(dedup_enabled)
        self._clock = clock
        self._sleeper = sleeper
        self._next_write_by_endpoint: dict[str, float] = {}
        self._last_report_by_endpoint: dict[str, bytes] = {}
        self.deduplicated_reports = 0

    def prepare(self, report: UsbReport) -> bool:
        if report.kind not in self.keyboard_kinds:
            return True

        if self.dedup_enabled and self._last_report_by_endpoint.get(report.endpoint) == report.report:
            self.deduplicated_reports += 1
            return False

        now = self._clock()
        next_write = self._next_write_by_endpoint.get(report.endpoint, now)
        wait_sec = max(0.0, next_write - now)
        if wait_sec > 0:
            self._sleeper(wait_sec)
            now = self._clock()

        self._last_report_by_endpoint[report.endpoint] = report.report
        self._next_write_by_endpoint[report.endpoint] = max(now, next_write) + self.output_interval
        return True


def _keyboard_payload(report: UsbReport) -> bytes:
    if report.kind == KIND_KEYBOARD and len(report.report) >= 9:
        return report.report[1:]
    return report.report


def _keyboard_non_modifier_keys(report: UsbReport) -> frozenset[int]:
    payload = _keyboard_payload(report)
    if len(payload) < 8:
        return frozenset()
    return frozenset(byte for byte in payload[2:8] if byte)


def _keyboard_modifier_bits(report: UsbReport) -> int:
    payload = _keyboard_payload(report)
    if len(payload) < 8:
        return 0
    return payload[0]


def _keyboard_is_release(report: UsbReport) -> bool:
    payload = _keyboard_payload(report)
    if len(payload) < 8:
        return False
    return payload[0] == 0 and all(byte == 0 for byte in payload[2:8])


class KeyboardReleaseCoalescer:
    """Merge adjacent different-key release/press transitions when safe."""

    keyboard_kinds = frozenset({KIND_KEYBOARD, KIND_US_SUB_KEYBOARD})

    def __init__(
        self,
        *,
        merge_window_sec: float = KEYBOARD_RELEASE_MERGE_WINDOW_SEC,
        clock=time.monotonic,
    ) -> None:
        self.merge_window_sec = max(0.0, float(merge_window_sec))
        self._clock = clock
        self._pending_release_by_endpoint: dict[str, tuple[UsbReport, float, frozenset[int], int]] = {}
        self._last_non_modifier_keys_by_endpoint: dict[str, frozenset[int]] = {}
        self._last_modifier_bits_by_endpoint: dict[str, int] = {}
        self.coalesced_releases = 0

    def enqueue(self, report: UsbReport) -> list[UsbReport]:
        if report.kind not in self.keyboard_kinds:
            return [report]

        endpoint = report.endpoint
        due_reports = self.flush_due(endpoint=endpoint)
        if _keyboard_is_release(report):
            previous_keys = self._last_non_modifier_keys_by_endpoint.get(endpoint, frozenset())
            previous_modifiers = self._last_modifier_bits_by_endpoint.get(endpoint, 0)
            self._pending_release_by_endpoint[endpoint] = (
                report,
                self._clock() + self.merge_window_sec,
                previous_keys,
                previous_modifiers,
            )
            return due_reports

        reports = due_reports
        new_keys = _keyboard_non_modifier_keys(report)
        new_modifiers = _keyboard_modifier_bits(report)
        pending = self._pending_release_by_endpoint.pop(endpoint, None)
        if pending is not None:
            release_report, _deadline, previous_keys, previous_modifiers = pending
            modifier_only_overlap = (
                not previous_keys
                and not new_keys
                and bool(previous_modifiers & new_modifiers)
            )
            if (previous_keys & new_keys) or modifier_only_overlap:
                reports.append(release_report)
            else:
                self.coalesced_releases += 1
        reports.append(report)
        self._last_non_modifier_keys_by_endpoint[endpoint] = new_keys
        self._last_modifier_bits_by_endpoint[endpoint] = new_modifiers
        return reports

    def flush_due(self, *, endpoint: str | None = None) -> list[UsbReport]:
        now = self._clock()
        due: list[UsbReport] = []
        endpoints = [endpoint] if endpoint is not None else list(self._pending_release_by_endpoint)
        for current_endpoint in endpoints:
            pending = self._pending_release_by_endpoint.get(current_endpoint)
            if pending is None:
                continue
            release_report, deadline, _previous_keys, _previous_modifiers = pending
            if now < deadline:
                continue
            self._pending_release_by_endpoint.pop(current_endpoint, None)
            self._last_non_modifier_keys_by_endpoint[current_endpoint] = frozenset()
            self._last_modifier_bits_by_endpoint[current_endpoint] = 0
            due.append(release_report)
        return due

    def flush_all(self) -> list[UsbReport]:
        reports = [pending[0] for pending in self._pending_release_by_endpoint.values()]
        for endpoint in list(self._pending_release_by_endpoint):
            self._last_non_modifier_keys_by_endpoint[endpoint] = frozenset()
            self._last_modifier_bits_by_endpoint[endpoint] = 0
        self._pending_release_by_endpoint.clear()
        return reports

    def time_until_flush(self) -> float:
        if not self._pending_release_by_endpoint:
            return 0.5
        now = self._clock()
        return max(
            0.0,
            min(deadline for _report, deadline, _keys, _modifiers in self._pending_release_by_endpoint.values()) - now,
        )


def _read_exact(fd: int, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = os.read(fd, remaining)
        if not chunk:
            raise EOFError("raw hid EOF")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise EOFError("viald socket EOF")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _write_exact(fd: int, data: bytes, write_lock: threading.Lock | None = None) -> None:
    lock = write_lock or threading.Lock()
    with lock:
        deadline = time.monotonic() + HID_WRITE_RETRY_TIMEOUT_SEC
        written_total = 0
        while written_total < len(data):
            try:
                written = os.write(fd, data[written_total:])
            except BlockingIOError as exc:
                if exc.errno not in (errno.EAGAIN, errno.EWOULDBLOCK):
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError("USB HID write timed out waiting for gadget endpoint") from exc
                if HID_WRITE_RETRY_INTERVAL_SEC > 0:
                    time.sleep(HID_WRITE_RETRY_INTERVAL_SEC)
                continue
            except InterruptedError:
                continue
            if written <= 0:
                raise EOFError("raw hid write EOF")
            written_total += written


def _connect_viald() -> socket.socket:
    while True:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(SOCKET_TIMEOUT_SEC)
        try:
            sock.connect(VIALD_SOCKET)
            log.info("connected to viald: %s", VIALD_SOCKET)
            return sock
        except OSError as exc:
            sock.close()
            log.warning("cannot connect to viald (%s): %s", VIALD_SOCKET, exc)
            time.sleep(RETRY_SEC)


def _open_raw_hid() -> int:
    while True:
        try:
            fd = os.open(RAW_HID_PATH, os.O_RDWR)
            log.info("opened raw hid: %s", RAW_HID_PATH)
            return fd
        except OSError as exc:
            log.warning("cannot open raw hid (%s): %s", RAW_HID_PATH, exc)
            time.sleep(RETRY_SEC)


def _open_hid_report_device() -> int:
    while True:
        try:
            fd = os.open(HID_REPORT_PATH, os.O_WRONLY | os.O_NONBLOCK)
            log.info("opened USB HID report device: %s", HID_REPORT_PATH)
            return fd
        except OSError as exc:
            log.warning("cannot open USB HID report device (%s): %s", HID_REPORT_PATH, exc)
            time.sleep(RETRY_SEC)


def _open_hid_report_endpoint(path: str) -> int:
    while True:
        try:
            fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
            log.info("opened USB HID report endpoint: %s", path)
            return fd
        except OSError as exc:
            log.warning("cannot open USB HID report endpoint (%s): %s", path, exc)
            time.sleep(RETRY_SEC)


def _bridge_once(
    fd: int,
    sock: socket.socket,
    report_size: int = REPORT_SIZE,
    write_lock: threading.Lock | None = None,
) -> None:
    request = _read_exact(fd, report_size)
    sock.sendall(request)
    response = _recv_exact(sock, report_size)
    _write_exact(fd, response, write_lock)


def _unlink_socket(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        return
    except OSError as exc:
        log.warning("cannot remove socket %s: %s", path, exc)


def _windows_ime_socket_loop(fd: int, stop_event: threading.Event, write_lock: threading.Lock) -> None:
    if not WINDOWS_IME_SOCKET_ENABLED:
        _unlink_socket(WINDOWS_IME_SOCKET)
        return
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.settimeout(0.5)
    _unlink_socket(WINDOWS_IME_SOCKET)
    try:
        sock.bind(WINDOWS_IME_SOCKET)
        try:
            input_gid = grp.getgrnam("input").gr_gid
            os.chown(WINDOWS_IME_SOCKET, 0, input_gid)
        except (KeyError, PermissionError, OSError) as exc:
            log.warning("cannot assign Windows IME socket to input group: %s", exc)
        os.chmod(WINDOWS_IME_SOCKET, 0o666)
        log.info("Windows IME Raw HID socket listening: %s", WINDOWS_IME_SOCKET)
        while not stop_event.is_set():
            try:
                frame = sock.recv(REPORT_SIZE)
            except socket.timeout:
                continue
            except OSError as exc:
                if not stop_event.is_set():
                    log.warning("Windows IME Raw HID socket read failed: %s", exc)
                break
            if len(frame) != REPORT_SIZE:
                log.warning("Windows IME Raw HID frame ignored: size=%d expected=%d", len(frame), REPORT_SIZE)
                continue
            try:
                _write_exact(fd, frame, write_lock)
                log.info("Windows IME Raw HID frame forwarded: size=%d", len(frame))
            except (OSError, EOFError) as exc:
                log.warning("Windows IME Raw HID write failed: %s", exc)
                break
    finally:
        try:
            sock.close()
        except OSError:
            pass
        _unlink_socket(WINDOWS_IME_SOCKET)


def _hid_report_socket_loop(stop_event: threading.Event) -> None:
    if not HID_REPORT_SOCKET_ENABLED:
        _unlink_socket(HID_REPORT_SOCKET)
        return
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.settimeout(0.5)
    _unlink_socket(HID_REPORT_SOCKET)
    hid_fds: dict[str, int] = {}
    mouse_scheduler = MouseReportScheduler()
    keyboard_coalescer = KeyboardReleaseCoalescer()
    keyboard_pacer = KeyboardReportPacer()

    def write_usb_report(usb_report: UsbReport) -> None:
        if not keyboard_pacer.prepare(usb_report):
            if HID_REPORT_LOG_ENABLED:
                log.info(
                    "USB HID report deduplicated kind=%s endpoint=%s final_len=%d final_hex=%s",
                    usb_report.kind_name,
                    usb_report.endpoint,
                    len(usb_report.report),
                    usb_report.report.hex(),
                )
            return
        hid_fd = hid_fds.get(usb_report.endpoint)
        if hid_fd is None:
            hid_fd = _open_hid_report_endpoint(usb_report.endpoint)
            hid_fds[usb_report.endpoint] = hid_fd
        if HID_REPORT_LOG_ENABLED:
            log.info(
                "USB HID report forwarded kind=%s endpoint=%s final_len=%d final_hex=%s",
                usb_report.kind_name,
                usb_report.endpoint,
                len(usb_report.report),
                usb_report.report.hex(),
            )
        _write_exact(hid_fd, usb_report.report)

    try:
        sock.bind(HID_REPORT_SOCKET)
        try:
            input_gid = grp.getgrnam("input").gr_gid
            os.chown(HID_REPORT_SOCKET, 0, input_gid)
        except (KeyError, PermissionError, OSError) as exc:
            log.warning("cannot assign HID report socket to input group: %s", exc)
        os.chmod(HID_REPORT_SOCKET, 0o666)
        log.info("USB HID report broker socket listening: %s", HID_REPORT_SOCKET)
        while not stop_event.is_set():
            sock.settimeout(
                min(
                    0.5,
                    max(0.0, mouse_scheduler.time_until_flush()),
                    max(0.0, keyboard_coalescer.time_until_flush()),
                )
            )
            try:
                frame = sock.recv(64)
            except (socket.timeout, BlockingIOError):
                due_reports = []
                due_reports.extend(keyboard_coalescer.flush_due())
                mouse_due = mouse_scheduler.flush_due()
                if mouse_due is not None:
                    due_reports.append(mouse_due)
                try:
                    for due in due_reports:
                        write_usb_report(due)
                except (OSError, EOFError) as exc:
                    log.warning("USB HID report write failed: %s", exc)
                    for due in due_reports:
                        hid_fd = hid_fds.pop(due.endpoint, None)
                        if hid_fd is not None:
                            try:
                                os.close(hid_fd)
                            except OSError:
                                pass
                continue
            except OSError as exc:
                if not stop_event.is_set():
                    log.warning("USB HID report socket read failed: %s", exc)
                break
            try:
                request = decode_hid_report_request(frame)
                usb_report = adapt_current_multi_report_profile(
                    request,
                    hidg_path=HID_REPORT_PATH,
                    us_sub_hidg_path=US_SUB_HID_REPORT_PATH,
                )
            except ValueError as exc:
                log.warning("USB HID report request ignored: %s", exc)
                continue
            if usb_report.kind == KIND_MOUSE:
                reports = keyboard_coalescer.flush_all() + mouse_scheduler.enqueue(usb_report)
            else:
                pending_mouse = mouse_scheduler.flush(force=True)
                if usb_report.kind in KeyboardReleaseCoalescer.keyboard_kinds:
                    reports = ([pending_mouse] if pending_mouse is not None else []) + keyboard_coalescer.enqueue(usb_report)
                else:
                    reports = (
                        ([pending_mouse] if pending_mouse is not None else [])
                        + keyboard_coalescer.flush_all()
                        + [usb_report]
                    )
            try:
                for report in reports:
                    write_usb_report(report)
            except (OSError, EOFError) as exc:
                log.warning("USB HID report write failed: %s", exc)
                for report in reports:
                    hid_fd = hid_fds.pop(report.endpoint, None)
                    if hid_fd is not None:
                        try:
                            os.close(hid_fd)
                        except OSError:
                            pass
    finally:
        for hid_fd in hid_fds.values():
            try:
                os.close(hid_fd)
            except OSError:
                pass
        try:
            sock.close()
        except OSError:
            pass
        _unlink_socket(HID_REPORT_SOCKET)


def run() -> None:
    hid_report_stop_event = threading.Event()
    hid_report_thread = threading.Thread(
        target=_hid_report_socket_loop,
        args=(hid_report_stop_event,),
        name="usb-hid-report-socket",
        daemon=True,
    )
    hid_report_thread.start()
    if not RAW_HID_BRIDGE_ENABLED:
        if not HID_REPORT_SOCKET_ENABLED:
            log.warning("raw HID bridge and HID report broker are both disabled; usbd will idle")
        log.info("raw HID bridge disabled; running HID report broker only")
        try:
            while True:
                time.sleep(3600)
        finally:
            hid_report_stop_event.set()
            hid_report_thread.join(timeout=1.0)

    while True:
        fd = _open_raw_hid()
        sock = _connect_viald()
        write_lock = threading.Lock()
        stop_event = threading.Event()
        aux_thread = threading.Thread(
            target=_windows_ime_socket_loop,
            args=(fd, stop_event, write_lock),
            name="windows-ime-raw-hid-socket",
            daemon=True,
        )
        aux_thread.start()
        try:
            while True:
                _bridge_once(fd, sock, REPORT_SIZE, write_lock)
        except (OSError, EOFError, socket.timeout) as exc:
            log.warning("bridge reset: %s", exc)
        finally:
            stop_event.set()
            aux_thread.join(timeout=1.0)
            try:
                sock.close()
            except OSError:
                pass
            try:
                os.close(fd)
            except OSError:
                pass
            time.sleep(RETRY_SEC)


def main() -> None:
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        print(_HELP.rstrip())
        return

    logging.basicConfig(
        level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO"), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log.info(
        "starting usbd: raw_bridge=%d hid=%s socket=%s report_size=%d",
        RAW_HID_BRIDGE_ENABLED,
        RAW_HID_PATH,
        VIALD_SOCKET,
        REPORT_SIZE,
    )
    if WINDOWS_IME_SOCKET_ENABLED:
        log.info("Windows IME Raw HID socket enabled: %s", WINDOWS_IME_SOCKET)
    if HID_REPORT_SOCKET_ENABLED:
        log.info(
            "USB HID report broker socket enabled: %s -> %s us_sub=%s",
            HID_REPORT_SOCKET,
            HID_REPORT_PATH,
            US_SUB_HID_REPORT_PATH,
        )
    run()


if __name__ == "__main__":
    main()
