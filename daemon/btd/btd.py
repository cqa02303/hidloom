#!/usr/bin/env python3
"""Bluetooth HID daemon for HIDloom.

This daemon accepts keyboard HID report bytes over a Unix domain socket, parses
them as fixed 8-byte keyboard reports, and routes them through a backend
interface. The BlueZ backend can expose a BLE HID-over-GATT keyboard service.
The default backend only logs reports.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .backend import BtdBackend, LoggingBackend
from .bluez_backend import (
    DEFAULT_BLUEZ_ADVERTISING_MODE,
    BlueZBackend,
)
from .gatt_app import GATT_SECURITY_MODES, GATT_SECURITY_NONE
from .protocol import (
    FRAME_HEADER_SIZE,
    FRAME_MAGIC,
    FRAME_TYPE_CONSUMER,
    FRAME_TYPE_CONTROL,
    FRAME_TYPE_KEYBOARD,
    FRAME_TYPE_MOUSE,
    KEYBOARD_REPORT_SIZE,
    CONSUMER_REPORT_SIZE,
    parse_raw_keyboard_report,
    parse_raw_consumer_report,
    parse_raw_mouse_report,
)

DEFAULT_SOCKET = "/tmp/btd_events.sock"
DEFAULT_REPORT_SIZE = KEYBOARD_REPORT_SIZE
DEFAULT_GATT_ADAPTER = "dry-run"
DEFAULT_ADVERTISING_ADAPTER = "auto"
DEFAULT_PAIRING_ADAPTER = "dry-run"
DEFAULT_PAIRING_AGENT_CAPABILITY = "KeyboardOnly"

log = logging.getLogger("btd")


def build_backend(
    name: str,
    *,
    gatt_adapter: str | None = None,
    advertising_adapter: str | None = None,
    pairing_adapter: str | None = None,
    pairing_agent_capability: str | None = None,
    gatt_security: str | None = None,
    pairing_mode: bool = False,
    advertising_mode: str | None = None,
    advertising_monitor_interval_sec: float = 1.0,
    advertising_idle_monitor_interval_sec: float = 60.0,
    bluez_enable: bool = False,
    disconnect_monitor_interval_sec: float = 0.0,
    disconnect_idle_monitor_interval_sec: float = 60.0,
    stuck_reconnect_polls: int = 0,
    stuck_reconnect_cooldown_sec: float = 30.0,
    reconnect_notify_grace_sec: float = 2.0,
    output_on_connect: str | None = None,
    output_on_disconnect: str | None = None,
    logicd_ctrl_socket_path: str | None = None,
    mouse_coalesce_interval_sec: float = 0.0,
    mouse_small_coalesce_interval_sec: float = 0.0,
    mouse_small_coalesce_threshold: int = 0,
    mouse_fast_hold_sec: float = 0.0,
    keyboard_repeat_enabled: bool = False,
    keyboard_repeat_delay_sec: float = 0.45,
    keyboard_repeat_interval_sec: float = 0.035,
    keyboard_repeat_tap_gap_sec: float = 0.006,
    consumer_control: bool | None = None,
) -> BtdBackend:
    """Create a backend by name.

    Design intent:
    - backend selection controls which object receives parsed KeyboardReport.
    - GATT adapter selection controls how the BlueZ backend registers/notifies.
    - BLE HID over GATT is the implemented transport.
    - adapter selection must not leak into or change the raw 8-byte socket
      protocol.

    `bluez` defaults to a dry-run adapter unless the service drop-in selects
    bluez-dbus. The dry-run path is safe for development because it validates
    lifecycle/report shape without talking to BlueZ.
    """
    if name == "logging":
        return LoggingBackend()
    if name == "bluez":
        return BlueZBackend.with_adapter_kind(
            enabled=bluez_enable,
            adapter_kind=gatt_adapter or DEFAULT_GATT_ADAPTER,
            advertising_adapter_kind=None if advertising_adapter in {None, "auto"} else advertising_adapter,
            pairing_adapter_kind=pairing_adapter or DEFAULT_PAIRING_ADAPTER,
            pairing_agent_capability=pairing_agent_capability,
            gatt_security=gatt_security,
            pairing_mode=pairing_mode,
            advertising_mode=advertising_mode,
            advertising_monitor_interval_sec=advertising_monitor_interval_sec,
            advertising_idle_monitor_interval_sec=advertising_idle_monitor_interval_sec,
            disconnect_monitor_interval_sec=disconnect_monitor_interval_sec,
            disconnect_idle_monitor_interval_sec=disconnect_idle_monitor_interval_sec,
            stuck_reconnect_polls=stuck_reconnect_polls,
            stuck_reconnect_cooldown_sec=stuck_reconnect_cooldown_sec,
            reconnect_notify_grace_sec=reconnect_notify_grace_sec,
            output_on_connect=output_on_connect,
            output_on_disconnect=output_on_disconnect,
            logicd_ctrl_socket_path=logicd_ctrl_socket_path,
            mouse_coalesce_interval_sec=mouse_coalesce_interval_sec,
            mouse_small_coalesce_interval_sec=mouse_small_coalesce_interval_sec,
            mouse_small_coalesce_threshold=mouse_small_coalesce_threshold,
            mouse_fast_hold_sec=mouse_fast_hold_sec,
            keyboard_repeat_enabled=keyboard_repeat_enabled,
            keyboard_repeat_delay_sec=keyboard_repeat_delay_sec,
            keyboard_repeat_interval_sec=keyboard_repeat_interval_sec,
            keyboard_repeat_tap_gap_sec=keyboard_repeat_tap_gap_sec,
            consumer_control=consumer_control,
        )
    raise ValueError(f"unknown backend: {name}")


class BtdServer:
    def __init__(
        self,
        socket_path: str = DEFAULT_SOCKET,
        report_size: int = DEFAULT_REPORT_SIZE,
        socket_mode: int = 0o660,
        backend: BtdBackend | None = None,
        status_interval_sec: float = 0.0,
    ) -> None:
        self.socket_path = socket_path
        self.report_size = report_size
        self.socket_mode = socket_mode
        self.backend = backend or LoggingBackend()
        self.status_interval_sec = max(0.0, status_interval_sec)
        self._server: asyncio.AbstractServer | None = None
        self._status_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        path = Path(self.socket_path)
        if path.exists():
            path.unlink()
        await self.backend.start()
        self._server = await asyncio.start_unix_server(self._handle_client, path=self.socket_path)
        os.chmod(self.socket_path, self.socket_mode)
        log.info("btd listening on %s report_size=%d", self.socket_path, self.report_size)
        _log_backend_status(self.backend)
        if self.status_interval_sec > 0:
            self._status_task = asyncio.create_task(_backend_status_loop(self.backend, self.status_interval_sec))

    async def serve_forever(self) -> None:
        if self._server is None:
            await self.start()
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        if self._status_task is not None:
            self._status_task.cancel()
            try:
                await self._status_task
            except asyncio.CancelledError:
                pass
            self._status_task = None
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        try:
            await self.backend.stop()
        finally:
            try:
                os.unlink(self.socket_path)
            except FileNotFoundError:
                pass

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        log.debug("client connected: %s", peer or "unix")
        buffer = bytearray()
        try:
            while True:
                data = await reader.read(
                    max(self.report_size, FRAME_HEADER_SIZE + KEYBOARD_REPORT_SIZE, FRAME_HEADER_SIZE + CONSUMER_REPORT_SIZE)
                )
                if not data:
                    break
                buffer.extend(data)
                while True:
                    if buffer.startswith(FRAME_MAGIC):
                        if len(buffer) < FRAME_HEADER_SIZE:
                            break
                        report_type = buffer[4]
                        payload_len = buffer[5]
                        frame_len = FRAME_HEADER_SIZE + payload_len
                        if len(buffer) < frame_len:
                            break
                        payload = bytes(buffer[FRAME_HEADER_SIZE:frame_len])
                        del buffer[:frame_len]
                        await self._dispatch_framed_report(report_type, payload, writer)
                        continue
                    if len(buffer) < self.report_size:
                        break
                    payload = bytes(buffer[: self.report_size])
                    del buffer[: self.report_size]
                    try:
                        report = parse_raw_keyboard_report(payload)
                    except ValueError as exc:
                        log.warning("invalid keyboard report len=%d bytes=%s error=%s", len(payload), payload.hex(), exc)
                        continue
                    await self.backend.send_keyboard_report(report)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("client error: %s", exc)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            log.debug("client disconnected")

    async def _dispatch_framed_report(
        self,
        report_type: int,
        payload: bytes,
        writer: asyncio.StreamWriter | None = None,
    ) -> None:
        try:
            if report_type == FRAME_TYPE_KEYBOARD:
                await self.backend.send_keyboard_report(parse_raw_keyboard_report(payload))
            elif report_type == FRAME_TYPE_MOUSE:
                await self.backend.send_mouse_report(parse_raw_mouse_report(payload))
            elif report_type == FRAME_TYPE_CONTROL:
                await self._dispatch_control_frame(payload, writer)
            elif report_type == FRAME_TYPE_CONSUMER:
                await self.backend.send_consumer_report(parse_raw_consumer_report(payload))
            else:
                log.warning("invalid framed HID report type=%d len=%d bytes=%s", report_type, len(payload), payload.hex())
        except ValueError as exc:
            log.warning(
                "invalid framed HID report type=%d len=%d bytes=%s error=%s",
                report_type,
                len(payload),
                payload.hex(),
                exc,
            )

    async def _dispatch_control_frame(self, payload: bytes, writer: asyncio.StreamWriter | None = None) -> None:
        try:
            msg = json.loads(payload.decode("utf-8"))
            if not isinstance(msg, dict):
                raise ValueError("control frame root must be object")
            command = str(msg.get("command") or "")
            if command == "status":
                if writer is not None:
                    writer.write(json.dumps({"result": "ok", "status": _backend_status_dict(self.backend)}).encode() + b"\n")
                    await writer.drain()
                return
            if command == "reconnect_advertising":
                await self.backend.set_reconnect_advertising(bool(msg.get("enabled")))
                return
            if command == "sync_pairing_advertising":
                sync = getattr(self.backend, "sync_pairing_advertising", None)
                if callable(sync):
                    await sync()
                return
            raise ValueError(f"unknown control command: {command!r}")
        except Exception as exc:
            log.warning("invalid control frame len=%d bytes=%s error=%s", len(payload), payload.hex(), exc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bluetooth HID daemon")
    parser.add_argument("--socket", default=os.environ.get("BTD_EVENTS_SOCK", DEFAULT_SOCKET))
    parser.add_argument("--report-size", type=int, default=int(os.environ.get("BTD_REPORT_SIZE", str(DEFAULT_REPORT_SIZE))))
    parser.add_argument("--socket-mode", default=os.environ.get("BTD_SOCKET_MODE", "660"))
    parser.add_argument("--backend", choices=("logging", "bluez"), default=os.environ.get("BTD_BACKEND", "logging"))
    parser.add_argument(
        "--gatt-adapter",
        choices=("dry-run", "bluez-dbus"),
        default=os.environ.get("BTD_GATT_ADAPTER", DEFAULT_GATT_ADAPTER),
        help="GATT registration adapter. Default is dry-run; bluez-dbus enables real BlueZ registration.",
    )
    parser.add_argument(
        "--gatt-security",
        choices=GATT_SECURITY_MODES,
        default=os.environ.get("BTD_GATT_SECURITY", GATT_SECURITY_NONE),
        help="GATT characteristic security mode. Default none. Use encrypt to require encrypted read/notify.",
    )
    parser.add_argument(
        "--advertising-adapter",
        choices=("auto", "dry-run", "bluez-dbus"),
        default=os.environ.get("BTD_ADVERTISING_ADAPTER", DEFAULT_ADVERTISING_ADAPTER),
        help="Advertising adapter. Default auto follows the GATT adapter: dry-run for dry-run, bluez-dbus for bluez-dbus.",
    )
    parser.add_argument(
        "--advertising-mode",
        choices=("always", "pairing", "off"),
        default=os.environ.get("BTD_ADVERTISING_MODE", DEFAULT_BLUEZ_ADVERTISING_MODE.value),
        help="When to register BLE advertisement. Default pairing advertises only while pairable/discoverable is enabled.",
    )
    parser.add_argument(
        "--advertising-monitor-interval",
        type=float,
        default=float(os.environ.get("BTD_ADVERTISING_MONITOR_INTERVAL", "1") or "1"),
        help="Polling interval for --advertising-mode pairing. Default 1 second.",
    )
    parser.add_argument(
        "--advertising-idle-monitor-interval",
        type=float,
        default=float(os.environ.get("BTD_ADVERTISING_IDLE_MONITOR_INTERVAL", "60") or "60"),
        help="Polling interval for idle pairing visibility checks. Default 60 seconds.",
    )
    parser.add_argument(
        "--pairing-adapter",
        choices=("dry-run", "bluetoothctl"),
        default=os.environ.get("BTD_PAIRING_ADAPTER", DEFAULT_PAIRING_ADAPTER),
        help="Pairing mode adapter. Default dry-run. Use bluetoothctl on Raspberry Pi/BlueZ.",
    )
    parser.add_argument(
        "--pairing-agent",
        choices=("DisplayOnly", "DisplayYesNo", "KeyboardOnly", "KeyboardDisplay", "NoInputNoOutput"),
        default=os.environ.get("BTD_PAIRING_AGENT", DEFAULT_PAIRING_AGENT_CAPABILITY),
        help="bluetoothctl agent capability used by --pairing-adapter bluetoothctl. Default is KeyboardOnly.",
    )
    parser.add_argument(
        "--pairing-mode",
        action="store_true",
        default=os.environ.get("BTD_PAIRING_MODE", "").strip().lower() in {"1", "true", "yes", "on"},
        help="Enable pairable mode while this btd instance is running, restoring previous state on stop.",
    )
    parser.add_argument(
        "--consumer-control",
        action="store_true",
        default=os.environ.get("BTD_CONSUMER_CONTROL", "").strip().lower() in {"1", "true", "yes", "on"},
        help="Expose BLE Consumer Control Input Report. Default off to preserve existing bonded host HID maps.",
    )
    parser.add_argument(
        "--bluez-enable",
        action="store_true",
        default=os.environ.get("BTD_BLUEZ_ENABLE", "").strip().lower() in {"1", "true", "yes", "on"},
        help="Enable BlueZ backend registration/notification. Without this, --backend bluez remains a safe dry-run path.",
    )
    parser.add_argument("--log-level", default=os.environ.get("BTD_LOG_LEVEL", "INFO"))
    parser.add_argument(
        "--status-interval",
        type=float,
        default=float(os.environ.get("BTD_STATUS_INTERVAL", "0") or "0"),
        help="Log backend status every N seconds. Default 0 disables periodic status logging.",
    )
    parser.add_argument(
        "--disconnect-monitor-interval",
        type=float,
        default=float(os.environ.get("BTD_DISCONNECT_MONITOR_INTERVAL", "0") or "0"),
        help="Poll BlueZ connected devices every N seconds and reset keyboard input on disconnect. Default 0 disables it.",
    )
    parser.add_argument(
        "--disconnect-idle-monitor-interval",
        type=float,
        default=float(os.environ.get("BTD_DISCONNECT_IDLE_MONITOR_INTERVAL", "60") or "60"),
        help="Poll BlueZ connected devices every N seconds while no host is connected. Default 60 seconds.",
    )
    parser.add_argument(
        "--stuck-reconnect-polls",
        type=int,
        default=int(os.environ.get("BTD_STUCK_RECONNECT_POLLS", "0") or "0"),
        help="Recover when BlueZ has connected devices but HID notify is inactive for N monitor polls. Default 0 disables it.",
    )
    parser.add_argument(
        "--stuck-reconnect-cooldown",
        type=float,
        default=float(os.environ.get("BTD_STUCK_RECONNECT_COOLDOWN", "30") or "30"),
        help="Minimum seconds between stuck reconnect recoveries. Default 30.",
    )
    parser.add_argument(
        "--reconnect-notify-grace",
        type=float,
        default=float(os.environ.get("BTD_RECONNECT_NOTIFY_GRACE", "2.0") or "2.0"),
        help="Seconds to wait after reconnect before stuck recovery may re-register GATT. Default 2.0.",
    )
    parser.add_argument(
        "--output-on-connect",
        choices=("off", "auto", "gadget", "uinput", "bt"),
        default=os.environ.get("BTD_OUTPUT_ON_CONNECT", "off"),
        help="Force logicd output target when a Bluetooth host connects. Default off.",
    )
    parser.add_argument(
        "--output-on-disconnect",
        choices=("off", "auto", "gadget", "uinput", "bt"),
        default=os.environ.get("BTD_OUTPUT_ON_DISCONNECT", "off"),
        help="Force logicd output target when all Bluetooth hosts disconnect. Default off.",
    )
    parser.add_argument(
        "--logicd-ctrl-socket",
        default=os.environ.get("CTRL_EVENTS_SOCK", "/tmp/ctrl_events.sock"),
        help="logicd ctrl socket used by --output-on-connect. Default /tmp/ctrl_events.sock.",
    )
    parser.add_argument(
        "--mouse-coalesce-interval",
        type=float,
        default=float(os.environ.get("BTD_MOUSE_COALESCE_INTERVAL", "0.020") or "0.020"),
        help="Seconds to accumulate relative mouse motion before notifying BLE. Use 0 to disable. Default 0.020.",
    )
    parser.add_argument(
        "--mouse-small-coalesce-interval",
        type=float,
        default=float(os.environ.get("BTD_MOUSE_SMALL_COALESCE_INTERVAL", "0.040") or "0.040"),
        help="Seconds to accumulate tiny relative mouse motion before notifying BLE. Default 0.040.",
    )
    parser.add_argument(
        "--mouse-small-coalesce-threshold",
        type=int,
        default=int(os.environ.get("BTD_MOUSE_SMALL_COALESCE_THRESHOLD", "4") or "4"),
        help="Max absolute dx/dy/wheel treated as tiny mouse motion for coalescing. Default 4.",
    )
    parser.add_argument(
        "--mouse-fast-hold",
        type=float,
        default=float(os.environ.get("BTD_MOUSE_FAST_HOLD", "0.12") or "0.12"),
        help="Seconds to keep fast mouse coalescing after larger motion. Default 0.12.",
    )
    parser.add_argument(
        "--keyboard-repeat",
        action="store_true",
        default=os.environ.get("BTD_KEYBOARD_REPEAT", "1").strip().lower() in {"1", "true", "yes", "on"},
        help="Re-notify held keyboard reports for BLE hosts that do not perform host-side key repeat. Default on.",
    )
    parser.add_argument(
        "--keyboard-repeat-delay",
        type=float,
        default=float(os.environ.get("BTD_KEYBOARD_REPEAT_DELAY", "0.45") or "0.45"),
        help="Seconds before BLE keyboard repeat starts. Default 0.45.",
    )
    parser.add_argument(
        "--keyboard-repeat-interval",
        type=float,
        default=float(os.environ.get("BTD_KEYBOARD_REPEAT_INTERVAL", "0.090") or "0.090"),
        help="Seconds between repeated BLE keyboard notifications. Default 0.090.",
    )
    parser.add_argument(
        "--keyboard-repeat-tap-gap",
        type=float,
        default=float(os.environ.get("BTD_KEYBOARD_REPEAT_TAP_GAP", "0.006") or "0.006"),
        help="Seconds between synthetic repeat release and press notifications. Default 0.006.",
    )
    return parser.parse_args()


async def main_async() -> None:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        socket_mode = int(str(args.socket_mode), 8)
    except ValueError:
        raise SystemExit(f"invalid socket mode: {args.socket_mode!r}")
    server = BtdServer(
        socket_path=args.socket,
        report_size=max(1, args.report_size),
        socket_mode=socket_mode,
        status_interval_sec=args.status_interval,
        backend=build_backend(
            args.backend,
            gatt_adapter=args.gatt_adapter,
            gatt_security=args.gatt_security,
            advertising_adapter=args.advertising_adapter,
            advertising_mode=args.advertising_mode,
            advertising_monitor_interval_sec=max(0.1, args.advertising_monitor_interval),
            advertising_idle_monitor_interval_sec=max(0.1, args.advertising_idle_monitor_interval),
            pairing_adapter=args.pairing_adapter,
            pairing_agent_capability=args.pairing_agent,
            pairing_mode=args.pairing_mode,
            bluez_enable=args.bluez_enable,
            disconnect_monitor_interval_sec=max(0.0, args.disconnect_monitor_interval),
            disconnect_idle_monitor_interval_sec=max(0.1, args.disconnect_idle_monitor_interval),
            stuck_reconnect_polls=max(0, args.stuck_reconnect_polls),
            stuck_reconnect_cooldown_sec=max(0.0, args.stuck_reconnect_cooldown),
            reconnect_notify_grace_sec=max(0.0, args.reconnect_notify_grace),
            output_on_connect=args.output_on_connect,
            output_on_disconnect=args.output_on_disconnect,
            logicd_ctrl_socket_path=args.logicd_ctrl_socket,
            mouse_coalesce_interval_sec=max(0.0, args.mouse_coalesce_interval),
            mouse_small_coalesce_interval_sec=max(0.0, args.mouse_small_coalesce_interval),
            mouse_small_coalesce_threshold=max(0, args.mouse_small_coalesce_threshold),
            mouse_fast_hold_sec=max(0.0, args.mouse_fast_hold),
            keyboard_repeat_enabled=args.keyboard_repeat,
            keyboard_repeat_delay_sec=max(0.05, args.keyboard_repeat_delay),
            keyboard_repeat_interval_sec=max(0.01, args.keyboard_repeat_interval),
            keyboard_repeat_tap_gap_sec=max(0.001, args.keyboard_repeat_tap_gap),
            consumer_control=args.consumer_control,
        ),
    )

    loop = asyncio.get_running_loop()

    def stop() -> None:
        for task in asyncio.all_tasks(loop):
            task.cancel()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop)
        except NotImplementedError:
            pass

    try:
        await server.serve_forever()
    except asyncio.CancelledError:
        pass
    finally:
        await server.stop()
        log.info("btd stopped")


async def _backend_status_loop(backend: BtdBackend, interval_sec: float) -> None:
    while True:
        await asyncio.sleep(interval_sec)
        _log_backend_status(backend)


def _log_backend_status(backend: BtdBackend) -> None:
    fields = _backend_status_fields(backend)
    if fields:
        log.info("backend status %s", fields)


def _backend_status_fields(backend: BtdBackend) -> str:
    values = _backend_status_dict(backend)
    if "error" in values:
        return f"error={values['error']!r}"
    parts: list[str] = []
    for key in sorted(values):
        parts.append(f"{key}={_status_value_to_text(values[key])}")
    return " ".join(parts)


def _backend_status_dict(backend: BtdBackend) -> dict[str, Any]:
    status_fn = getattr(backend, "status", None)
    if not callable(status_fn):
        return {}
    try:
        status = status_fn()
    except Exception as exc:
        return {"error": repr(exc)}
    if is_dataclass(status):
        values = asdict(status)
    elif isinstance(status, dict):
        values = dict(status)
    else:
        values = vars(status)
    return {str(key): _status_value_to_json(value) for key, value in values.items()}


def _status_value_to_json(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {str(key): _status_value_to_json(val) for key, val in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _status_value_to_json(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_status_value_to_json(item) for item in value]
    return value


def _status_value_to_text(value: Any) -> str:
    if isinstance(value, str):
        return value or '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
