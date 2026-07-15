"""System status and log helpers for the HTTP UI."""

from __future__ import annotations

import asyncio
import copy
import json
import os
from pathlib import Path
import re
import shlex
import time
from typing import Any, Dict

from system_logs import LOG_ALLOWED_SERVICES, journal_lines
from system_peripherals import ledd_direct_frame_status, spid_status
from system_process import (
    _DAEMON_KEYWORDS,
    _match_process_statuses,
    _parse_systemd_active_states,
    _socket_file_status,
    _systemd_active_statuses,
    check_process,
    hid_gadget_status,
    process_statuses,
)

DEFAULT_BTD_SOCKET = "/tmp/btd_events.sock"
DEFAULT_USBD_HID_REPORT_SOCKET = "/tmp/usbd_hid_reports.sock"
DEFAULT_HIDD_STATUS_PATH = "/run/hidloom/hidd-status.json"
DEFAULT_BLUETOOTH_HOSTS_FILE = "/mnt/p3/bluetooth_hosts.json"
DEFAULT_BOARD_PROFILE_FILE = "/mnt/p3/board_profile.json"
DEFAULT_TOUCH_PANEL_PROFILE_FILE = "/mnt/p3/touch_panel_profile.json"
DEFAULT_DEVICE_PROFILE_FILE = "/mnt/p3/device_profile.json"
DEFAULT_BOARD_VERSION = "ver1.0"
BTD_FRAME_MAGIC = b"btd1"
BTD_FRAME_TYPE_CONTROL = 3
OUTPUT_DISPLAY_LABELS = {
    "gadget": "USB",
    "bt": "BT",
    "uinput": "Pi",
}
_SERVICE_ENV_CACHE_TTL = 30.0
_BLUETOOTH_STATUS_CACHE_TTL = 5.0
_BTD_RUNTIME_STATUS_CACHE_TTL = 5.0
_service_env_cache: dict[str, tuple[float, Dict[str, str]]] = {}
_bluetooth_status_cache: tuple[float, Dict[str, Any]] | None = None
_btd_runtime_status_cache: dict[str, tuple[float, Dict[str, Any]]] = {}
# Process status anchors delegated to system_process:
# def _proc_cmdlines()
# def _systemd_active_statuses()
# return {name: systemd.get(name, fallback[name]) for name in _DAEMON_KEYWORDS}
# Direct-frame status fields delegated to system_peripherals:
# accepted_frames applied_frames ignored_frames direct_frame_active rejected_frames


def _parse_systemd_environment_show(text: str) -> Dict[str, str]:
    m = re.search(r"^Environment=(.*)$", text, re.MULTILINE)
    if not m:
        return {}
    env: Dict[str, str] = {}
    for part in shlex.split(m.group(1)):
        key, sep, value = part.partition("=")
        if sep and key:
            env[key] = value
    return env


def output_mode_display_label(mode: str) -> str:
    """Return the user-facing short label for an output backend name."""
    return OUTPUT_DISPLAY_LABELS.get(mode, mode or "")


def _touch_panel_profile_status(marker_path: str = DEFAULT_TOUCH_PANEL_PROFILE_FILE) -> Dict[str, Any] | None:
    path = Path(marker_path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"source": "error", "marker_path": str(path), "error": str(exc)}
    if not isinstance(data, dict):
        return {"source": "error", "marker_path": str(path), "error": "marker root must be object"}
    profile = data.get("profile")
    return {
        "source": "marker",
        "marker_path": str(path),
        "profile": profile if isinstance(profile, str) and profile else None,
        "reason": data.get("reason") if isinstance(data.get("reason"), str) else None,
        "sizes": data.get("sizes") if isinstance(data.get("sizes"), list) else [],
    }


def _device_profile_touch_panel_status(marker_path: str = DEFAULT_DEVICE_PROFILE_FILE) -> Dict[str, Any] | None:
    path = Path(marker_path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"source": "error", "marker_path": str(path), "error": str(exc)}
    if not isinstance(data, dict):
        return {"source": "error", "marker_path": str(path), "error": "marker root must be object"}
    if data.get("kind") != "touch-panel":
        return None
    profile_id = data.get("id")
    profile = profile_id.removeprefix("touch-") if isinstance(profile_id, str) and profile_id else None
    return {
        "source": "device-profile",
        "marker_path": str(path),
        "profile": profile,
        "id": profile_id if isinstance(profile_id, str) and profile_id else None,
        "selected_at": data.get("selected_at") if isinstance(data.get("selected_at"), str) else None,
        "selected_by": data.get("selected_by") if isinstance(data.get("selected_by"), str) else None,
    }


def board_profile_status(
    marker_path: str = DEFAULT_BOARD_PROFILE_FILE,
    touch_panel_marker_path: str = DEFAULT_TOUCH_PANEL_PROFILE_FILE,
    device_profile_marker_path: str = DEFAULT_DEVICE_PROFILE_FILE,
) -> Dict[str, Any]:
    """Return the active board wiring profile without mutating runtime files."""
    path = Path(marker_path)
    base: Dict[str, Any] = {
        "board_version": DEFAULT_BOARD_VERSION,
        "source": "fallback",
        "marker_path": str(path),
        "marker_exists": False,
        "prototype": False,
        "device_name": None,
        "runtime_profile": None,
        "display_label": DEFAULT_BOARD_VERSION,
    }
    touch_panel = _touch_panel_profile_status(touch_panel_marker_path)
    if touch_panel is None:
        touch_panel = _device_profile_touch_panel_status(device_profile_marker_path)
    if touch_panel is not None:
        profile = touch_panel.get("profile") or "unknown"
        base["runtime_profile"] = {
            "kind": "touch-panel",
            **touch_panel,
        }
        base["device_name"] = "<keyboard-host>"
        base["display_label"] = f"<keyboard-host> touch-panel ({profile})"
    if not path.exists():
        return base
    base["marker_exists"] = True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {**base, "source": "error", "error": str(exc)}
    if not isinstance(data, dict):
        return {**base, "source": "error", "error": "marker root must be object"}
    version = data.get("board_version")
    if isinstance(version, str) and version:
        base["board_version"] = version
        base["source"] = "marker"
    else:
        base["source"] = "error"
        base["error"] = "missing board_version"
    base["prototype"] = bool(data.get("prototype", False))
    device_name = data.get("device_name")
    if touch_panel is None:
        base["device_name"] = device_name if isinstance(device_name, str) and device_name else None
        base["display_label"] = f"{base['board_version']} prototype" if base["prototype"] else base["board_version"]
    elif isinstance(device_name, str) and device_name:
        base["board_device_name"] = device_name
    return base


def output_display_label(runtime_mode: str, output_target: str) -> str:
    """Return the primary display label for the current output state."""
    runtime_label = output_mode_display_label(runtime_mode)
    target_label = output_mode_display_label(output_target)
    if output_target == "auto":
        return f"AUTO {runtime_label}" if runtime_label else "AUTO"
    return target_label or runtime_label


async def service_environment(service: str, *, max_age_sec: float = _SERVICE_ENV_CACHE_TTL) -> Dict[str, str]:
    now = time.monotonic()
    if max_age_sec > 0:
        cached = _service_env_cache.get(service)
        if cached is not None:
            cached_at, cached_env = cached
            if now - cached_at < max_age_sec:
                return dict(cached_env)
    code, out, _ = await _run_text("systemctl", "show", service, "-p", "Environment", "--no-pager")
    if code != 0:
        return {}
    env = _parse_systemd_environment_show(out)
    if max_age_sec > 0:
        _service_env_cache[service] = (now, dict(env))
    return env


async def logicd_runtime_environment() -> Dict[str, str]:
    for service in ("logicd-companion", "logicd"):
        code, _, _ = await _run_text("systemctl", "is-active", "--quiet", service)
        if code == 0:
            return await service_environment(service)
    return {}


def btd_status(
    socket_path: str | None = None,
    service_env: Dict[str, str] | None = None,
    runtime_status: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Return btd process/socket/backend settings for HTTP status.

    Local process/env/file state is always included.  A caller may pass an
    optional read-only btd runtime snapshot obtained over the btd control frame
    protocol; btd remains the source of truth for BlueZ/GATT host state.
    """
    env = service_env if service_env is not None else os.environ
    path = socket_path or env.get("BTD_EVENTS_SOCK", DEFAULT_BTD_SOCKET)
    return {
        "process": check_process(_DAEMON_KEYWORDS["btd"]),
        "socket": _socket_file_status(path),
        "backend_env": env.get("BTD_BACKEND", ""),
        "gatt_adapter_env": env.get("BTD_GATT_ADAPTER", ""),
        "advertising_adapter_env": env.get("BTD_ADVERTISING_ADAPTER", ""),
        "advertising_mode_env": env.get("BTD_ADVERTISING_MODE", ""),
        "advertising_monitor_interval_env": env.get("BTD_ADVERTISING_MONITOR_INTERVAL", ""),
        "gatt_security_env": env.get("BTD_GATT_SECURITY", ""),
        "status_interval_env": env.get("BTD_STATUS_INTERVAL", ""),
        "disconnect_monitor_interval_env": env.get("BTD_DISCONNECT_MONITOR_INTERVAL", ""),
        "stuck_reconnect_polls_env": env.get("BTD_STUCK_RECONNECT_POLLS", ""),
        "stuck_reconnect_cooldown_env": env.get("BTD_STUCK_RECONNECT_COOLDOWN", ""),
        "runtime": runtime_status,
    }


def _env_enabled(env: Dict[str, str], name: str) -> bool:
    return str(env.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def usbd_status(
    *,
    usbd_env: Dict[str, str] | None = None,
    logicd_env: Dict[str, str] | None = None,
    hidd_env: Dict[str, str] | None = None,
    hidd_status_path: str = DEFAULT_HIDD_STATUS_PATH,
) -> Dict[str, Any]:
    """Return USB HID broker readiness without mutating daemon state.

    The historical JSON key is still named ``usbd`` for UI compatibility, but
    the active broker owner may now be native ``hidloom-hidd``.
    """
    uenv = usbd_env if usbd_env is not None else os.environ
    lenv = logicd_env if logicd_env is not None else os.environ
    henv = hidd_env if hidd_env is not None else os.environ
    socket_path = (
        henv.get("USBD_HID_REPORT_SOCKET")
        or uenv.get("USBD_HID_REPORT_SOCKET")
        or lenv.get("LOGICD_USBD_HID_REPORT_SOCKET")
        or DEFAULT_USBD_HID_REPORT_SOCKET
    )
    usbd_enabled = _env_enabled(uenv, "USBD_HID_REPORT_SOCKET_ENABLED")
    hidd_process = check_process(_DAEMON_KEYWORDS["hidd"])
    legacy_usbd_process = check_process(_DAEMON_KEYWORDS["usbd"])
    logicd_enabled = _env_enabled(lenv, "LOGICD_USBD_HID_REPORT_BROKER")
    socket_status = _socket_file_status(socket_path)
    hidd_status = _load_hidd_status(hidd_status_path)
    hidd_active = hidd_process or hidd_status.get("process") is True
    owner = "hidloom-hidd" if hidd_active else ("usbd" if legacy_usbd_process else "unknown")
    broker_ready = bool(logicd_enabled and socket_status.get("is_socket") is True and (hidd_active or usbd_enabled))
    return {
        "owner": owner,
        "process": hidd_process or legacy_usbd_process,
        "hidd_process": hidd_process,
        "usbd_process": legacy_usbd_process,
        "status_path": hidd_status_path,
        "status": hidd_status,
        "hid_report_socket": socket_status,
        "hid_report_socket_enabled_env": uenv.get("USBD_HID_REPORT_SOCKET_ENABLED", ""),
        "hid_report_socket_env": uenv.get("USBD_HID_REPORT_SOCKET", ""),
        "hidd_hid_report_socket_env": henv.get("USBD_HID_REPORT_SOCKET", ""),
        "hid_report_log_env": uenv.get("USBD_HID_REPORT_LOG", ""),
        "logicd_broker_enabled_env": lenv.get("LOGICD_USBD_HID_REPORT_BROKER", ""),
        "logicd_hid_report_socket_env": lenv.get("LOGICD_USBD_HID_REPORT_SOCKET", ""),
        "logicd_hid_report_log_env": lenv.get("LOGICD_HID_REPORT_LOG", ""),
        "broker_ready": broker_ready,
    }


def hidd_status(
    *,
    hidd_env: Dict[str, str] | None = None,
    logicd_env: Dict[str, str] | None = None,
    hidd_status_path: str = DEFAULT_HIDD_STATUS_PATH,
) -> Dict[str, Any]:
    """Return the native hidloom-hidd broker status using the same shape as usbd."""
    return usbd_status(
        usbd_env={},
        hidd_env=hidd_env,
        logicd_env=logicd_env,
        hidd_status_path=hidd_status_path,
    )


def _load_hidd_status(path_text: str) -> Dict[str, Any]:
    path = Path(path_text)
    if not path.exists():
        return {"available": False, "path": path_text}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"available": False, "path": path_text, "error": str(exc)}
    if not isinstance(payload, dict):
        return {"available": False, "path": path_text, "error": "status root must be object"}
    return {"available": True, "path": path_text, **payload}


async def query_btd_runtime_status(
    socket_path: str,
    *,
    timeout: float = 1.0,
    max_age_sec: float = _BTD_RUNTIME_STATUS_CACHE_TTL,
) -> Dict[str, Any]:
    """Read btd's own runtime status through a read-only control frame."""
    now = time.monotonic()
    if max_age_sec > 0:
        cached = _btd_runtime_status_cache.get(socket_path)
        if cached is not None:
            cached_at, cached_status = cached
            if now - cached_at < max_age_sec:
                return copy.deepcopy(cached_status)
    payload = json.dumps({"command": "status"}, separators=(",", ":")).encode("utf-8")
    if len(payload) > 255:
        return {"available": False, "error": "status request too large"}
    open_unix_connection = getattr(asyncio, "open_unix_connection", None)
    if open_unix_connection is None:
        status = {"available": False, "error": "unix sockets are unavailable on this platform"}
        if max_age_sec > 0:
            _btd_runtime_status_cache[socket_path] = (now, copy.deepcopy(status))
        return status
    try:
        reader, writer = await asyncio.wait_for(open_unix_connection(socket_path), timeout=timeout)
        try:
            writer.write(BTD_FRAME_MAGIC + bytes([BTD_FRAME_TYPE_CONTROL, len(payload)]) + payload)
            await asyncio.wait_for(writer.drain(), timeout=timeout)
            line = await asyncio.wait_for(reader.readline(), timeout=timeout)
        finally:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), timeout=timeout)
            except Exception:
                pass
    except (FileNotFoundError, ConnectionRefusedError, PermissionError, OSError, asyncio.TimeoutError) as exc:
        status = {"available": False, "error": str(exc)}
        if max_age_sec > 0:
            _btd_runtime_status_cache[socket_path] = (now, copy.deepcopy(status))
        return status
    try:
        response = json.loads(line.decode(errors="replace"))
    except json.JSONDecodeError as exc:
        status = {"available": False, "error": f"invalid response: {exc}"}
        if max_age_sec > 0:
            _btd_runtime_status_cache[socket_path] = (now, copy.deepcopy(status))
        return status
    if not isinstance(response, dict):
        status = {"available": False, "error": "non-object response"}
        if max_age_sec > 0:
            _btd_runtime_status_cache[socket_path] = (now, copy.deepcopy(status))
        return status
    if response.get("result") != "ok":
        status = {"available": False, "error": str(response.get("msg") or response)}
        if max_age_sec > 0:
            _btd_runtime_status_cache[socket_path] = (now, copy.deepcopy(status))
        return status
    status = response.get("status")
    if not isinstance(status, dict):
        result = {"available": False, "error": "missing status object"}
        if max_age_sec > 0:
            _btd_runtime_status_cache[socket_path] = (now, copy.deepcopy(result))
        return result
    result = {"available": True, **status}
    if max_age_sec > 0:
        _btd_runtime_status_cache[socket_path] = (now, copy.deepcopy(result))
    return result


def output_status(
    service_env: Dict[str, str] | None = None,
    *,
    runtime_mode: str = "",
    output_target: str = "",
) -> Dict[str, Any]:
    """Return configured output-related environment for HTTP status.

    Runtime output ownership is split between the native router and the active
    logicd companion or legacy profile. The caller supplies the selected runtime
    service environment because httpd usually runs with different values.
    """
    env = service_env if service_env is not None else os.environ
    raw_outputs = env.get("LOGICD_OUTPUTS", "")
    outputs = [part for part in re.split(r"[,+\s]+", raw_outputs.strip()) if part]
    lowered = {part.lower() for part in outputs}
    return {
        "logicd_outputs_env": raw_outputs,
        "configured_outputs": outputs,
        "runtime_mode": runtime_mode,
        "output_target": output_target,
        "runtime_mode_label": output_mode_display_label(runtime_mode),
        "output_target_label": output_mode_display_label(output_target),
        "display_label": output_display_label(runtime_mode, output_target),
        "bt_enabled_by_env": "bt" in lowered,
        "debug_enabled_by_env": "debug" in lowered or "log" in lowered or "logging" in lowered,
        "auto_bt_fallback_env": env.get("LOGICD_AUTO_BT_FALLBACK", ""),
        "bt_disconnect_on_output_disable_env": env.get("LOGICD_BT_DISCONNECT_ON_OUTPUT_DISABLE", ""),
        "btd_events_sock_env": env.get("BTD_EVENTS_SOCK", ""),
    }


async def _run_text(*cmd: str, timeout: float = 3.0) -> tuple[int, str, str]:
    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")
    except asyncio.TimeoutError:
        if proc is not None and proc.returncode is None:
            proc.kill()
            try:
                await asyncio.wait_for(proc.communicate(), timeout=1.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                pass
        return 124, "", "command timeout"
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    except OSError as exc:
        return 1, "", str(exc)


def _parse_bt_bool(text: str, field_name: str) -> bool | None:
    m = re.search(rf"^\s*{re.escape(field_name)}:\s*(yes|no)\s*$", text, re.MULTILINE | re.IGNORECASE)
    if not m:
        return None
    return m.group(1).lower() == "yes"


def _parse_device_macs(text: str) -> list[str]:
    return [
        m.group(1).upper()
        for m in re.finditer(r"^Device\s+([0-9A-F:]{17})\b", text, re.MULTILINE | re.IGNORECASE)
    ]


def _parse_device_rows(text: str) -> list[Dict[str, str]]:
    rows: list[Dict[str, str]] = []
    for m in re.finditer(r"^Device\s+([0-9A-F:]{17})\s*(.*)$", text, re.MULTILINE | re.IGNORECASE):
        rows.append({"mac": m.group(1).upper(), "name": m.group(2).strip()})
    return rows


def _parse_bt_field(text: str, field_name: str) -> str | None:
    m = re.search(rf"^\s*{re.escape(field_name)}:\s*(.*?)\s*$", text, re.MULTILINE | re.IGNORECASE)
    return m.group(1) if m else None


def _dedupe_device_macs(*mac_lists: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for macs in mac_lists:
        for mac in macs:
            normalized = mac.upper()
            if normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
    return result


def _load_bluetooth_host_metadata(path: str = DEFAULT_BLUETOOTH_HOSTS_FILE) -> Dict[str, Dict[str, Any]]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    hosts = raw.get("hosts") if isinstance(raw, dict) else None
    if not isinstance(hosts, dict):
        return {}
    result: Dict[str, Dict[str, Any]] = {}
    for mac, metadata in hosts.items():
        if isinstance(mac, str) and isinstance(metadata, dict):
            result[mac.upper()] = metadata
    return result


def _merge_bluetooth_host_metadata(
    devices: list[Dict[str, Any]],
    metadata: Dict[str, Dict[str, Any]],
) -> list[Dict[str, Any]]:
    merged: list[Dict[str, Any]] = []
    for device in devices:
        enriched = dict(device)
        host = metadata.get(str(device.get("mac", "")).upper(), {})
        display_name = host.get("display_name") if isinstance(host, dict) else None
        enriched["display_name"] = display_name if isinstance(display_name, str) and display_name else None
        enriched["display_name_source"] = "local_metadata" if enriched["display_name"] else None
        enriched["last_seen_name"] = host.get("last_seen_name") if isinstance(host, dict) else None
        enriched["last_connected_at"] = host.get("last_connected_at") if isinstance(host, dict) else None
        enriched["last_connected_source"] = host.get("last_connected_source") if isinstance(host, dict) else None
        merged.append(enriched)
    return merged


async def _bluetooth_device_detail(mac: str, fallback_name: str = "") -> Dict[str, Any]:
    code, out, err = await _run_text("bluetoothctl", "info", mac)
    detail: Dict[str, Any] = {
        "mac": mac.upper(),
        "name": fallback_name,
        "paired": None,
        "bonded": None,
        "trusted": None,
        "connected": None,
    }
    if code != 0:
        detail["error"] = err.strip() or out.strip() or "bluetoothctl info failed"
        return detail

    detail["name"] = _parse_bt_field(out, "Name") or fallback_name
    for field in ("Paired", "Bonded", "Trusted", "Connected"):
        detail[field.lower()] = _parse_bt_bool(out, field)
    return detail


async def bluetooth_status(*, max_age_sec: float = _BLUETOOTH_STATUS_CACHE_TTL) -> Dict[str, Any]:
    """Return a small BlueZ/bluetoothctl status snapshot for the HTTP UI."""
    global _bluetooth_status_cache
    now = time.monotonic()
    if max_age_sec > 0 and _bluetooth_status_cache is not None:
        cached_at, cached_status = _bluetooth_status_cache
        if now - cached_at < max_age_sec:
            return copy.deepcopy(cached_status)

    service_code, service_out, service_err = await _run_text("systemctl", "is-active", "bluetooth")
    active_text = service_out.strip()
    service_active = True if active_text == "active" else False if active_text else None
    if service_active is not True:
        status = {
            "available": False,
            "bluetooth_service_active": service_active,
            "powered": None,
            "discoverable": None,
            "pairable": None,
            "paired_devices": [],
            "connected_devices": [],
            "devices": [],
        }
        if service_code != 0:
            status["error"] = service_err.strip() or service_out.strip() or "bluetooth service inactive"
        if max_age_sec > 0:
            _bluetooth_status_cache = (now, copy.deepcopy(status))
        return status

    (
        (show_code, show_out, show_err),
        (paired_code, paired_out, _),
        (connected_code, connected_out, _),
        (devices_code, devices_out, _),
    ) = await asyncio.gather(
        _run_text("bluetoothctl", "show"),
        _run_text("bluetoothctl", "paired-devices"),
        _run_text("bluetoothctl", "devices", "Connected"),
        _run_text("bluetoothctl", "devices"),
    )

    paired_macs = _parse_device_macs(paired_out) if paired_code == 0 else []
    connected_macs = _parse_device_macs(connected_out) if connected_code == 0 else []
    device_rows = _parse_device_rows(devices_out) if devices_code == 0 else []
    device_names = {row["mac"]: row["name"] for row in device_rows}
    device_macs = _dedupe_device_macs([row["mac"] for row in device_rows], connected_macs, paired_macs)

    devices: list[Dict[str, Any]] = []
    if device_macs:
        devices = await asyncio.gather(
            *(_bluetooth_device_detail(mac, device_names.get(mac, "")) for mac in device_macs)
        )

    if devices:
        devices = _merge_bluetooth_host_metadata(devices, _load_bluetooth_host_metadata())
        paired_macs = [
            device["mac"]
            for device in devices
            if device.get("paired") is True or device.get("bonded") is True
        ]
        connected_macs = [
            device["mac"]
            for device in devices
            if device.get("connected") is True
        ] or connected_macs

    status: Dict[str, Any] = {
        "available": show_code == 0,
        "bluetooth_service_active": service_active,
        "powered": _parse_bt_bool(show_out, "Powered"),
        "discoverable": _parse_bt_bool(show_out, "Discoverable"),
        "pairable": _parse_bt_bool(show_out, "Pairable"),
        "paired_devices": paired_macs,
        "connected_devices": connected_macs,
        "devices": devices,
    }
    if show_code != 0:
        status["error"] = show_err.strip() or show_out.strip() or "bluetoothctl show failed"
    if max_age_sec > 0:
        _bluetooth_status_cache = (now, copy.deepcopy(status))
    return status
