from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from system_process import _DAEMON_KEYWORDS, _socket_file_status, check_process

DEFAULT_SPID_CTRL_SOCKET = "/tmp/ctrl_events.sock"
DEFAULT_SPID_EVENTS_SOCKET = "/tmp/spi_events.sock"
DEFAULT_LEDD_DIRECT_FRAME_SOCKET = "/tmp/ledd_direct_frame.sock"
DEFAULT_LEDD_DIRECT_FRAME_STATUS = "/tmp/ledd_direct_frame_status.json"


def spid_status(socket_path: str | None = None) -> Dict[str, Any]:
    """Return spid process/socket/backend settings for HTTP status.

    This is intentionally side-effect free. It does not connect to spid and does
    not require SPI hardware. It only exposes the configured environment and the
    presence/type of expected Unix sockets.
    """
    events_path = socket_path or os.environ.get("SPID_EVENTS_SOCK") or os.environ.get("SPID_SOCKET") or DEFAULT_SPID_EVENTS_SOCKET
    return {
        "process": check_process(_DAEMON_KEYWORDS["spid"]),
        "enabled_env": os.environ.get("SPID_ENABLED", ""),
        "backend_env": os.environ.get("SPID_BACKEND", ""),
        "logicd_mode_env": os.environ.get("LOGICD_SPID_MODE", ""),
        "events_socket": _socket_file_status(events_path),
        "ctrl_socket": _socket_file_status(os.environ.get("CTRL_EVENTS_SOCK", DEFAULT_SPID_CTRL_SOCKET)),
        "spi_bus_env": os.environ.get("SPID_SPI_BUS", ""),
        "spi_device_env": os.environ.get("SPID_SPI_DEVICE", ""),
        "spi_mode_env": os.environ.get("SPID_SPI_MODE", ""),
        "spi_speed_hz_env": os.environ.get("SPID_SPI_SPEED_HZ", ""),
        "paw3805ek_cpi_env": os.environ.get("SPID_PAW3805EK_CPI", ""),
        "paw3805ek_scale_env": os.environ.get("SPID_PAW3805EK_SCALE", ""),
    }


def _read_json_file(path_text: str) -> Dict[str, Any] | None:
    try:
        raw = Path(path_text).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        return {"available": False, "error": str(exc)}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {"available": False, "error": f"invalid JSON: {exc}"}
    return data if isinstance(data, dict) else {"available": False, "error": "JSON root is not object"}


def ledd_direct_frame_status(socket_path: str | None = None, status_path: str | None = None) -> Dict[str, Any]:
    """Return ledd direct-frame socket status for HTTP status.

    Runtime accepted/rejected frame counters are exported by ledd as a small
    JSON snapshot. Reading that file keeps `/api/status` side-effect free.
    """
    path = socket_path or os.environ.get("LEDD_DIRECT_FRAME_SOCK", DEFAULT_LEDD_DIRECT_FRAME_SOCKET)
    metrics_path = status_path or os.environ.get("LEDD_DIRECT_FRAME_STATUS", DEFAULT_LEDD_DIRECT_FRAME_STATUS)
    metrics = _read_json_file(metrics_path) or {}
    result = {
        "process": check_process(_DAEMON_KEYWORDS["ledd"]),
        "socket": _socket_file_status(path),
        "socket_env": os.environ.get("LEDD_DIRECT_FRAME_SOCK", ""),
        "status_path": metrics_path,
        "metrics_source": "json_file" if metrics else "missing",
        "accepted_frames": metrics.get("accepted_frames"),
        "rejected_frames": metrics.get("rejected_frames"),
        "bytes_received": metrics.get("bytes_received"),
        "last_frame_id": metrics.get("last_frame_id"),
        "last_error": metrics.get("last_error", ""),
        "producer_connects": metrics.get("producer_connects"),
        "producer_disconnects": metrics.get("producer_disconnects"),
        "direct_frame_active": metrics.get("direct_frame_active"),
        "applied_frames": metrics.get("applied_frames"),
        "ignored_frames": metrics.get("ignored_frames"),
        "last_applied_frame_id": metrics.get("last_applied_frame_id"),
        "updated_at": metrics.get("updated_at"),
    }
    if metrics.get("available") is False:
        result["metrics_error"] = metrics.get("error", "unavailable")
    return result
