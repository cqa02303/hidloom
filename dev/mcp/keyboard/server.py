#!/usr/bin/env python3
"""Read-only MCP server for HIDloom keyboard diagnostics."""
from __future__ import annotations

import argparse
import base64
import grp
import hashlib
import json
import os
import pwd
import shlex
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, TextIO


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from script_metadata import analyze_script_safety  # noqa: E402
from hidloom_paths import (  # noqa: E402
    default_config_dir,
    default_config_file,
    environment_value,
    runtime_file,
    runtime_script_dir,
)
from logicd.hid_report import (  # noqa: E402
    CONSUMER_KEYCODE,
    HID_REPORT_ID_CONSUMER,
    HID_REPORT_ID_KEYBOARD,
    KEYCODE,
    HidState,
    add_hid_report_id,
)

DEFAULT_CONFIG = default_config_file("config.json", ROOT)
DEFAULT_KEYCODES = default_config_file("keycodes.json", ROOT)
DEFAULT_KEYMAP = default_config_file("keymap.json", ROOT)
DEFAULT_SCRIPT_DIR = default_config_dir(ROOT) / "script"
DEFAULT_RUNTIME_KEYMAP = Path(environment_value("RUNTIME_KEYMAP", str(runtime_file("keymap.json"))))
DEFAULT_RUNTIME_SCRIPT_DIR = runtime_script_dir()
DEFAULT_RUNTIME_LED_STATE = Path(environment_value("RUNTIME_LED_STATE", str(runtime_file("led_state.json"))))
DEFAULT_RUNTIME_BLUETOOTH_HOSTS = Path(
    environment_value("RUNTIME_BLUETOOTH_HOSTS", str(runtime_file("bluetooth_hosts.json")))
)
DEFAULT_RUNTIME_BOARD_PROFILE = Path(
    environment_value("RUNTIME_BOARD_PROFILE", str(runtime_file("board_profile.json")))
)
DEFAULT_REPO_ROOT = ROOT
DEFAULT_CODEX_TASKS_DIR = ROOT / "codex_tasks"
DEFAULT_CODEX_CONFIG = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml"
DEFAULT_HTTP_STATUS_URL = environment_value("HTTP_STATUS_URL", "https://127.0.0.1/api/status")
DEFAULT_REAL_DEVICE_REPO_ROOT = "/srv/hidloom"
DEFAULT_REAL_DEVICE_TARGET = "keyboard.example"
DEFAULT_REAL_DEVICE_TARGETS = (DEFAULT_REAL_DEVICE_TARGET,)

SERVER_NAME = "hidloom-keyboard"
SERVER_VERSION = "0.1.0"
SERVER_INSTRUCTIONS = (
    "Read-only diagnostics for the HIDloom keyboard. Tools may inspect repository files, "
    "runtime permissions, service status, bounded journal excerpts, keymap summaries, route "
    "decisions, and HID report previews. Do not use this server for key sending, keymap writes, "
    "service restarts, git mutations, driver installs, or other device state changes."
)

SPLIT_KEYBOARD_HID_USAGES = {0x87, 0x88, 0x89, 0x8A, 0x8B}
SPLIT_KEYBOARD_KEYCODES = {
    "KC_RO",
    "KC_INT1",
    "KC_KANA",
    "KC_INT2",
    "KC_JYEN",
    "KC_INT3",
    "KC_HENKAN",
    "KC_INT4",
    "KC_MUHENKAN",
    "KC_INT5",
}
JIS_SPECIAL_ON_MAIN_KEYCODES = {
    "KC_RO",
    "KC_INT1",
    "KC_KANA",
    "KC_INT2",
    "KC_JYEN",
    "KC_INT3",
    "KC_HENKAN",
    "KC_INT4",
    "KC_MUHENKAN",
    "KC_INT5",
    "KC_INT6",
    "KC_INT7",
    "KC_INT8",
    "KC_INT9",
    "KC_ZKHK",
    "KC_ZENKAKU_HANKAKU",
}
MOUSE_PREFIXES = ("KC_MS_", "KC_BTN", "KC_WH_", "MS_")
DEFAULT_SERVICES = (
    "hidloom-usb-gadget",
    "viald",
    "hidloom-hidd",
    "hidloom-uidd",
    "hidloom-outputd",
    "hidloom-logicd-core",
    "logicd-companion",
    "matrixd",
    "ledd",
    "i2cd",
    "httpd",
    "btd",
)
DIAGNOSTIC_SERVICES = ("logicd", "usbd", "spid")
ALLOWED_SERVICES = DEFAULT_SERVICES + DIAGNOSTIC_SERVICES
DEFAULT_SERVICE_UNITS = {
    "hidloom-usb-gadget": "system/systemd/hidloom-usb-gadget.service",
    "viald": "system/systemd/viald.service",
    "hidloom-hidd": "system/systemd/hidloom-hidd.service",
    "hidloom-uidd": "system/systemd/hidloom-uidd.service",
    "hidloom-outputd": "system/systemd/hidloom-outputd.service",
    "hidloom-logicd-core": "system/systemd/hidloom-logicd-core.service",
    "logicd-companion": "system/systemd/logicd-companion.service",
    "usbd": "system/systemd/usbd.service",
    "logicd": "system/systemd/logicd.service",
    "matrixd": "system/systemd/matrixd.service",
    "ledd": "system/systemd/ledd.service",
    "i2cd": "system/systemd/i2cd.service",
    "httpd": "system/systemd/httpd.service",
    "btd": "system/systemd/btd.service",
    "spid": "system/systemd/spid.service",
}
SYSTEMD_SHOW_PROPERTIES = (
    "Id",
    "Names",
    "Description",
    "LoadState",
    "ActiveState",
    "SubState",
    "FragmentPath",
    "DropInPaths",
    "UnitFileState",
    "User",
    "Group",
    "WorkingDirectory",
    "ExecStart",
    "Environment",
    "MainPID",
    "Restart",
    "RestartUSec",
)
SAFE_ENVIRONMENT_FLAGS = {
    "HIDLOOM_REPO_ROOT",
    "LOG_LEVEL",
    "LOG_SYSLOG",
    "LOGICD_OUTPUTS",
    "LOGICD_AUTO_BT_FALLBACK",
    "LOGICD_USBD_HID_REPORT_BROKER",
    "LOGICD_USBD_HID_REPORT_SOCKET",
    "LOGICD_HID_REPORT_LOG",
    "USBD_HID_REPORT_SOCKET_ENABLED",
    "USBD_HID_REPORT_SOCKET",
    "USBD_HID_REPORT_LOG",
    "HIDD_STATUS_PATH",
    "UIDD_REPORT_SOCKET",
    "UIDD_STATUS_PATH",
    "UIDD_UINPUT_PATH",
    "UIDD_DRY_RUN",
    "UIDD_REPORT_SOCKET_MODE",
    "OUTPUTD_REPORT_SOCKET",
    "OUTPUTD_CTRL_SOCKET",
    "OUTPUTD_USB_SOCKET",
    "OUTPUTD_UIDD_SOCKET",
    "OUTPUTD_BT_SOCKET",
    "OUTPUTD_STATUS_PATH",
    "OUTPUTD_TARGET",
    "OUTPUTD_REPORT_SOCKET_MODE",
    "OUTPUTD_CTRL_SOCKET_MODE",
    "LOGICD_CORE_MATRIX_SOCKET",
    "LOGICD_CORE_CTRL_SOCKET",
    "LOGICD_CORE_DELEGATE_SOCKET",
    "LOGICD_CORE_MATRIX_TAP_SOCKET",
    "LOGICD_CORE_HID_REPORT_SOCKET",
    "LOGICD_CORE_STATUS_PATH",
    "LOGICD_CORE_OUTPUT_ENABLED",
    "LOGICD_NATIVE_OUTPUTD_CTRL",
    "LOGICD_OUTPUTD_CTRL_SOCKET",
    "HTTPD_HOST",
    "HTTPD_PORT",
    "HTTPD_PRIVATE_ONLY",
    "HTTPD_AUTH_BYPASS_LOOPBACK",
    "BTD_BACKEND",
    "BTD_REPORT_SIZE",
    "BTD_SOCKET_MODE",
}
SERVICE_EXPECTED_ENV_FLAGS = {
    "hidloom-hidd": ("USBD_HID_REPORT_SOCKET", "HIDD_STATUS_PATH"),
    "hidloom-uidd": ("UIDD_REPORT_SOCKET", "UIDD_STATUS_PATH", "UIDD_UINPUT_PATH"),
    "hidloom-outputd": ("OUTPUTD_REPORT_SOCKET", "OUTPUTD_CTRL_SOCKET", "OUTPUTD_USB_SOCKET"),
    "hidloom-logicd-core": ("LOGICD_CORE_MATRIX_SOCKET", "LOGICD_CORE_HID_REPORT_SOCKET", "LOGICD_CORE_STATUS_PATH"),
    "logicd-companion": ("LOGICD_OUTPUTS", "LOGICD_NATIVE_OUTPUTD_CTRL", "LOGICD_OUTPUTD_CTRL_SOCKET"),
    "usbd": ("USBD_HID_REPORT_SOCKET_ENABLED",),
    "logicd": ("LOGICD_OUTPUTS", "LOGICD_AUTO_BT_FALLBACK", "LOGICD_USBD_HID_REPORT_BROKER"),
}
SERVICE_UNIT_DIRTY_CATEGORIES = {
    "httpd.service": "http",
    "logicd.service": "logicd",
    "logicd-companion.service": "logicd",
    "hidloom-logicd-core.service": "logicd",
    "hidloom-outputd.service": "logicd",
    "hidloom-uidd.service": "logicd",
    "hidloom-hidd.service": "hidd",
    "usbd.service": "usbd",
    "viald.service": "usbd",
    "i2cd.service": "logicd",
    "ledd.service": "logicd",
    "ledd-shutdown.service": "logicd",
    "matrixd.service": "logicd",
    "btd.service": "logicd",
    "spid.service": "logicd",
    "hidloom-usb-gadget.service": "usb_gadget",
}
DIRTY_CATEGORY_PREFIXES = (
    ("mcp", ("dev/mcp/keyboard/", "script/test_mcp_keyboard_server.py", "codex_tasks/")),
    ("docs", ("docs/", "README.md")),
    ("config", ("config/default/", "config/boards/", "conf/")),
    ("http", ("daemon/http/",)),
    ("logicd", ("daemon/logicd/",)),
    ("hidd", ("tools/hidloom_hidd/", "system/systemd/hidloom-hidd.service")),
    ("usbd", ("usbd/",)),
    ("systemd", (".service", ".conf")),
    ("usb_gadget", ("setup_usb_gadget.sh",)),
    ("tests", ("script/test_",)),
    ("native_artifact", ("daemon/matrixd/matrixd", "bin/hidloom-")),
)
DEFAULT_HID_DEVICES = ("/dev/hidg0", "/dev/hidg1", "/dev/hidg2")
DEFAULT_SOCKETS = ("/tmp/usbd_hid_reports.sock", "/tmp/matrix_events.sock", "/tmp/ledd_events.sock")
DEFAULT_RUNTIME_PATHS = (
    "/mnt/p3/keymap.json",
    "/mnt/p3/led_state.json",
    "/mnt/p3/bluetooth_hosts.json",
    "/mnt/p3/script",
    "/mnt/p3",
)
NATIVE_ARTIFACTS = (
    "daemon/matrixd/matrixd",
    "bin/hidloom-ctrl",
    "bin/hidloom-key",
    "bin/hidloom-keytext",
    "bin/hidloom-notify",
    "bin/hidloom-oled",
)
BASE_RSYNC_EXCLUDES = (
    ".git/",
    ".venv/",
    "__pycache__/",
    ".pytest_cache/",
    "daemon/matrixd/matrixd",
    "bin/hidloom-ctrl",
    "bin/hidloom-key",
    "bin/hidloom-keytext",
    "bin/hidloom-notify",
    "bin/hidloom-oled",
)
DEFAULT_SELECTIVE_SYNC_CATEGORIES = ("mcp", "docs")
ATTENTION_ACTIONS = {
    "KC_SHUTDOWN",
    "WIFI_POWER_OFF",
    "WIFI_POWER_TOGGLE",
    "BT_FORGET_DEVICE",
    "BT_POWER_OFF",
}
JIS_ZENKAKU_HANKAKU_INTERNAL_MARKER = 0x5A
JIS_ZENKAKU_HANKAKU_HID_USAGE = 0x35


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, f"missing file: {path}"
    except OSError as exc:
        return None, f"cannot read file: {path}: {exc}"
    except json.JSONDecodeError as exc:
        return None, f"invalid json in {path}: {exc}"


def _load_keymap_doc(path: Path) -> tuple[dict[str, Any], str | None]:
    data, error = _read_json(path)
    return data or {}, error


def _keymap_layers_from_doc(keymap: dict[str, Any]) -> list[dict[str, str]]:
    layout_def = keymap.get("_layout_def", {})
    if not isinstance(layout_def, dict):
        return []
    groups: dict[str, list[tuple[int, int]]] = {}
    for group, entries in layout_def.items():
        if not isinstance(group, str) or group.startswith("_") or not isinstance(entries, list):
            continue
        coords: list[tuple[int, int]] = []
        for entry in entries:
            if isinstance(entry, list) and len(entry) >= 2:
                try:
                    coords.append((int(entry[0]), int(entry[1])))
                except (TypeError, ValueError):
                    continue
        groups[group] = coords

    layers: list[dict[str, str]] = []
    for layer_data in keymap.get("layers", []):
        if not isinstance(layer_data, dict):
            continue
        flat: dict[str, str] = {}
        for group, coords in groups.items():
            keycodes = layer_data.get(group, [])
            if not isinstance(keycodes, list):
                continue
            for (row, col), keycode in zip(coords, keycodes):
                if isinstance(keycode, str) and keycode:
                    flat[f"{row},{col}"] = keycode
        layers.append(flat)
    return layers


def _keymap_layer_names(keymap: dict[str, Any]) -> list[str | None]:
    names: list[str | None] = []
    for layer_data in keymap.get("layers", []):
        if isinstance(layer_data, dict):
            name = layer_data.get("_name")
            names.append(str(name) if name is not None else None)
    return names


def _active_keymap_path(preferred: Path | None = None) -> Path:
    if preferred is not None:
        return preferred
    return DEFAULT_RUNTIME_KEYMAP if DEFAULT_RUNTIME_KEYMAP.exists() else DEFAULT_KEYMAP


def _load_state(
    *,
    config_path: Path = DEFAULT_CONFIG,
    keycodes_path: Path = DEFAULT_KEYCODES,
    keymap_path: Path = DEFAULT_KEYMAP,
) -> dict[str, Any]:
    config, config_error = _read_json(config_path)
    keycodes, keycodes_error = _read_json(keycodes_path)
    keymap, keymap_error = _read_json(keymap_path)
    return {
        "config": config or {},
        "keycodes": keycodes or {},
        "keymap": keymap or {},
        "errors": [err for err in [config_error, keycodes_error, keymap_error] if err],
        "paths": {
            "config": str(config_path),
            "keycodes": str(keycodes_path),
            "keymap": str(keymap_path),
        },
    }


def _settings(state: dict[str, Any]) -> dict[str, Any]:
    settings = state.get("config", {}).get("settings", {})
    return settings if isinstance(settings, dict) else {}


def _keycode_info(state: dict[str, Any], keycode: str) -> dict[str, Any] | None:
    info = state.get("keycodes", {}).get(keycode)
    return info if isinstance(info, dict) else None


def _classify_keycode(state: dict[str, Any], keycode: str) -> dict[str, Any]:
    normalized = str(keycode or "").strip().upper()
    info = _keycode_info(state, normalized)
    hid = info.get("hid") if info else None
    page = info.get("page") if info else None

    if page == "consumer":
        route_kind = "consumer"
    elif normalized.startswith(MOUSE_PREFIXES) or (isinstance(hid, int) and 0x200 <= hid < 0x300):
        route_kind = "mouse"
    elif normalized in SPLIT_KEYBOARD_KEYCODES or normalized in JIS_SPECIAL_ON_MAIN_KEYCODES or (
        isinstance(hid, int) and hid in SPLIT_KEYBOARD_HID_USAGES
    ):
        route_kind = "split_keyboard"
    elif info is not None:
        route_kind = "keyboard"
    else:
        route_kind = "unknown"

    return {
        "keycode": normalized,
        "known": info is not None,
        "hid": hid,
        "linux": info.get("linux") if info else None,
        "page": page or "keyboard",
        "route_kind": route_kind,
    }


def get_usb_split_status(**paths: Any) -> dict[str, Any]:
    state = _load_state(**paths)
    settings = _settings(state)
    split_cfg = settings.get("usb_split_keyboard", {})
    if not isinstance(split_cfg, dict):
        split_cfg = {}

    enabled = bool(split_cfg.get("enabled"))
    route = str(split_cfg.get("route") or "")
    hidg = str(settings.get("hidg") or "/dev/hidg0")
    mouse_hidg = str(settings.get("mouse_hidg") or hidg)
    consumer_hidg = str(settings.get("consumer_hidg") or hidg)
    broker = bool(settings.get("usbd_hid_report_broker"))

    endpoints = [
        {
            "name": "main",
            "device": hidg,
            "identity": "JIS 106/109 main keyboard plus multi-report mouse/consumer"
            if enabled
            else "configured keyboard endpoint",
            "reports": ["keyboard", "mouse", "consumer"] if broker and mouse_hidg == hidg and consumer_hidg == hidg else ["keyboard"],
        },
        {
            "name": "us_sub",
            "device": "/dev/hidg2" if enabled else None,
            "identity": "US 101/102 sub keyboard route" if enabled and route == "jis_special_us_default" else "split keyboard route",
            "reports": ["keyboard"] if enabled else [],
        },
    ]

    if mouse_hidg != hidg:
        endpoints.append({"name": "mouse", "device": mouse_hidg, "identity": "separate mouse endpoint", "reports": ["mouse"]})
    if consumer_hidg != hidg:
        endpoints.append(
            {"name": "consumer", "device": consumer_hidg, "identity": "separate consumer endpoint", "reports": ["consumer"]}
        )

    return {
        "ok": not state["errors"],
        "mode": "read_only",
        "usb_split_keyboard": {"enabled": enabled, "route": route or None},
        "usbd_hid_report_broker": broker,
        "endpoints": endpoints,
        "known_success_shape": {
            "main": "/dev/hidg0 JIS 106/109 main keyboard for JIS specials",
            "sub": "/dev/hidg2 US 101/102 keyboard for default reports",
            "note": "This tool reports configured intent; run real-device smoke to confirm host enumeration.",
        },
        "errors": state["errors"],
    }


def get_status(**paths: Any) -> dict[str, Any]:
    state = _load_state(**paths)
    settings = _settings(state)
    outputs = settings.get("outputs", [])
    if not isinstance(outputs, list):
        outputs = [outputs]

    keymap = state.get("keymap", {})
    layers = keymap.get("layers", [])
    if not isinstance(layers, list):
        layers = []

    return {
        "ok": not state["errors"],
        "mode": "read_only",
        "server": {"name": SERVER_NAME, "version": SERVER_VERSION},
        "config": {
            "outputs": outputs,
            "hidg": settings.get("hidg"),
            "mouse_hidg": settings.get("mouse_hidg"),
            "consumer_hidg": settings.get("consumer_hidg"),
            "usbd_hid_report_broker": bool(settings.get("usbd_hid_report_broker")),
            "usb_split_keyboard": settings.get("usb_split_keyboard", {}),
        },
        "keymap": {
            "schema": keymap.get("_schema"),
            "layer_count": len(layers),
        },
        "paths": state["paths"],
        "errors": state["errors"],
    }


def explain_route_for_keycode(keycode: str, **paths: Any) -> dict[str, Any]:
    state = _load_state(**paths)
    settings = _settings(state)
    classification = _classify_keycode(state, keycode)
    split = get_usb_split_status(**paths)

    route_kind = classification["route_kind"]
    split_cfg = split["usb_split_keyboard"]
    split_route = str(split_cfg.get("route") or "")
    endpoint = settings.get("hidg") or "/dev/hidg0"
    reason = "standard keyboard usage"

    if route_kind in {"keyboard", "split_keyboard"} and split_cfg.get("enabled") and split_route == "jis_special_us_default":
        if classification["keycode"] in JIS_SPECIAL_ON_MAIN_KEYCODES:
            endpoint = settings.get("hidg") or "/dev/hidg0"
            reason = "JIS-specific key is routed to the JIS main keyboard endpoint"
        else:
            endpoint = "/dev/hidg2"
            reason = "default keyboard usage is routed to the US sub keyboard endpoint"
    elif route_kind == "split_keyboard" and split_cfg.get("enabled"):
        endpoint = "/dev/hidg2"
        reason = "split keyboard key is routed to the US sub keyboard endpoint when usb_split_keyboard is enabled"
    elif route_kind == "split_keyboard":
        reason = "split keyboard key is known, but usb_split_keyboard is disabled"
    elif route_kind == "mouse":
        endpoint = settings.get("mouse_hidg") or endpoint
        reason = "mouse keycode follows the configured mouse HID route"
    elif route_kind == "consumer":
        endpoint = settings.get("consumer_hidg") or endpoint
        reason = "consumer keycode follows the configured consumer HID route"
    elif route_kind == "unknown":
        endpoint = None
        reason = "keycode is not present in repository default keycodes.json"

    return {
        "ok": classification["known"] and not state["errors"],
        "mode": "read_only",
        "classification": classification,
        "route": {
            "endpoint": endpoint,
            "kind": route_kind,
            "reason": reason,
            "requires_real_device_confirmation": route_kind != "unknown",
        },
        "usb_split": split["usb_split_keyboard"],
        "errors": state["errors"],
    }


def _path_status(path: str) -> dict[str, Any]:
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return {"path": path, "exists": False, "kind": None, "mode": None}
    mode = st.st_mode
    if stat.S_ISSOCK(mode):
        kind = "socket"
    elif stat.S_ISCHR(mode):
        kind = "char_device"
    elif stat.S_ISDIR(mode):
        kind = "directory"
    elif stat.S_ISREG(mode):
        kind = "file"
    else:
        kind = "other"
    return {
        "path": path,
        "exists": True,
        "kind": kind,
        "mode": stat.filemode(mode),
        "uid": st.st_uid,
        "gid": st.st_gid,
    }


def _runtime_path_access(path: str) -> dict[str, Any]:
    info = _path_status(path)
    info["readable"] = os.access(path, os.R_OK)
    info["writable"] = os.access(path, os.W_OK)
    info["executable"] = os.access(path, os.X_OK)
    if info.get("exists"):
        try:
            info["owner"] = pwd.getpwuid(int(info["uid"])).pw_name
        except (KeyError, TypeError, ValueError):
            info["owner"] = None
        try:
            info["group"] = grp.getgrgid(int(info["gid"])).gr_name
        except (KeyError, TypeError, ValueError):
            info["group"] = None
    return info


def _file_digest_prefix(path: Path, limit_bytes: int = 1024 * 1024) -> str | None:
    try:
        with path.open("rb") as handle:
            digest = hashlib.sha256()
            remaining = limit_bytes
            while remaining > 0:
                chunk = handle.read(min(65536, remaining))
                if not chunk:
                    break
                digest.update(chunk)
                remaining -= len(chunk)
        return digest.hexdigest()[:16]
    except OSError:
        return None


def _runtime_json_file_summary(path: Path) -> dict[str, Any]:
    access = _runtime_path_access(str(path))
    summary: dict[str, Any] = {
        "path": str(path),
        "exists": access.get("exists"),
        "readable": access.get("readable"),
        "mode": access.get("mode"),
        "owner": access.get("owner"),
        "group": access.get("group"),
        "size": None,
        "mtime": None,
        "sha256_prefix": None,
        "json_ok": False,
        "json_type": None,
        "keys": [],
        "error": None,
    }
    if not access.get("exists"):
        return summary
    try:
        st = path.stat()
        summary["size"] = st.st_size
        summary["mtime"] = st.st_mtime
    except OSError as exc:
        summary["error"] = str(exc)
        return summary
    summary["sha256_prefix"] = _file_digest_prefix(path)
    data, error = _read_json(path)
    summary["json_ok"] = error is None
    summary["error"] = error
    if isinstance(data, dict):
        summary["json_type"] = "object"
        summary["keys"] = sorted(str(key) for key in data.keys())[:20]
    elif isinstance(data, list):
        summary["json_type"] = "array"
        summary["length"] = len(data)
    return summary


def _current_identity() -> dict[str, Any]:
    uid = os.geteuid()
    gid = os.getegid()
    groups = os.getgroups()
    return {
        "uid": uid,
        "gid": gid,
        "user": pwd.getpwuid(uid).pw_name if uid >= 0 else None,
        "group": grp.getgrgid(gid).gr_name if gid >= 0 else None,
        "groups": [
            {"gid": item, "name": grp.getgrgid(item).gr_name if item >= 0 else None}
            for item in groups
        ],
    }


def _systemctl_is_active(services: tuple[str, ...] = DEFAULT_SERVICES) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["systemctl", "is-active", *services],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )
    except FileNotFoundError:
        return {"available": False, "returncode": None, "services": {}, "stderr": "systemctl not found"}
    except subprocess.TimeoutExpired:
        return {"available": False, "returncode": None, "services": {}, "stderr": "systemctl timed out"}

    lines = proc.stdout.splitlines()
    statuses = {
        service: (lines[idx].strip() if idx < len(lines) and lines[idx].strip() else "unknown")
        for idx, service in enumerate(services)
    }
    return {"available": True, "returncode": proc.returncode, "services": statuses, "stderr": proc.stderr.strip()}


def _parse_key_value_lines(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _parse_systemd_environment(raw: str) -> dict[str, Any]:
    if not raw:
        return {"names": [], "safe_values": {}, "redacted": []}
    try:
        parts = shlex.split(raw)
    except ValueError:
        parts = raw.split()
    env: dict[str, str] = {}
    for part in parts:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        env[key] = value
    names = sorted(env)
    return {
        "names": names,
        "safe_values": {key: env[key] for key in names if key in SAFE_ENVIRONMENT_FLAGS},
        "redacted": [{"name": key, "value": "<redacted>"} for key in names if key not in SAFE_ENVIRONMENT_FLAGS],
    }


def _repo_unit_metadata(service: str, repo_root: Path = DEFAULT_REPO_ROOT) -> dict[str, Any]:
    rel = DEFAULT_SERVICE_UNITS.get(service)
    if not rel:
        return {"path": None, "exists": False, "environment_names": [], "safe_environment_values": {}}
    path = repo_root / rel
    metadata: dict[str, Any] = {"path": str(path), "relative_path": rel, "exists": path.exists()}
    if not path.exists():
        metadata.update({"environment_names": [], "safe_environment_values": {}, "error": None})
        return metadata
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        metadata.update({"environment_names": [], "safe_environment_values": {}, "error": str(exc)})
        return metadata
    env: dict[str, str] = {}
    exec_start: list[str] = []
    exec_start_pre: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("Environment="):
            for part in shlex.split(stripped.removeprefix("Environment=")):
                if "=" in part:
                    key, value = part.split("=", 1)
                    env[key] = value
        elif stripped.startswith("ExecStart="):
            exec_start.append(stripped.removeprefix("ExecStart="))
        elif stripped.startswith("ExecStartPre="):
            exec_start_pre.append(stripped.removeprefix("ExecStartPre="))
    metadata.update(
        {
            "environment_names": sorted(env),
            "safe_environment_values": {key: env[key] for key in sorted(env) if key in SAFE_ENVIRONMENT_FLAGS},
            "exec_start": exec_start,
            "exec_start_pre": exec_start_pre,
            "error": None,
        }
    )
    return metadata


def get_systemd_unit_summary(
    service: str | None = None,
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
    execute: bool = True,
) -> dict[str, Any]:
    """Summarize allowlisted systemd unit state without returning arbitrary secrets."""
    normalized = str(service or "").strip()
    services = DEFAULT_SERVICES if normalized in {"", "all"} else (normalized,)
    invalid = [item for item in services if item not in ALLOWED_SERVICES]
    if invalid:
        return {
            "ok": False,
            "mode": "read_only",
            "service": normalized,
            "error": f"service must be one of: {', '.join(ALLOWED_SERVICES)}",
        }
    properties_arg = ",".join(SYSTEMD_SHOW_PROPERTIES)
    command = ["systemctl", "show", *services, f"--property={properties_arg}", "--no-pager"]
    if not execute:
        return {"ok": True, "mode": "read_only", "services": {}, "command": command, "skipped": True}
    try:
        proc = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, check=False)
    except FileNotFoundError:
        return {"ok": False, "mode": "read_only", "services": {}, "command": command, "error": "systemctl not found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "mode": "read_only", "services": {}, "command": command, "error": "systemctl timed out"}

    blocks = [block for block in proc.stdout.strip().split("\n\n") if block.strip()]
    service_summaries: dict[str, Any] = {}
    for idx, service_name in enumerate(services):
        values = _parse_key_value_lines(blocks[idx] if idx < len(blocks) else "")
        env = _parse_systemd_environment(values.get("Environment", ""))
        expected = SERVICE_EXPECTED_ENV_FLAGS.get(service_name, ())
        safe_values = env["safe_values"]
        service_summaries[service_name] = {
            "id": values.get("Id"),
            "description": values.get("Description"),
            "load_state": values.get("LoadState"),
            "active_state": values.get("ActiveState"),
            "sub_state": values.get("SubState"),
            "unit_file_state": values.get("UnitFileState"),
            "fragment_path": values.get("FragmentPath"),
            "drop_in_paths": [item for item in values.get("DropInPaths", "").split() if item],
            "user": values.get("User"),
            "group": values.get("Group"),
            "working_directory": values.get("WorkingDirectory"),
            "main_pid": values.get("MainPID"),
            "restart": values.get("Restart"),
            "restart_usec": values.get("RestartUSec"),
            "exec_start_present": bool(values.get("ExecStart")),
            "environment_names": env["names"],
            "safe_environment_values": safe_values,
            "redacted_environment": env["redacted"],
            "expected_environment": {
                "names": list(expected),
                "missing": [name for name in expected if name not in safe_values],
                "present": {name: safe_values[name] for name in expected if name in safe_values},
            },
            "repo_unit": _repo_unit_metadata(service_name, repo_root=repo_root),
        }
    recommendations: list[str] = []
    logicd = service_summaries.get("logicd", {})
    if logicd and "LOGICD_USBD_HID_REPORT_BROKER" in logicd.get("expected_environment", {}).get("missing", []):
        recommendations.append("logicd unit does not expose LOGICD_USBD_HID_REPORT_BROKER; HID broker readiness will stay false unless config enables it")
    return {
        "ok": proc.returncode == 0,
        "mode": "read_only",
        "service": normalized or "all",
        "services": service_summaries,
        "command": command,
        "returncode": proc.returncode,
        "stderr": proc.stderr.strip(),
        "redaction": "only allowlisted environment values are returned; other environment values are replaced with <redacted>",
        "recommendations": recommendations,
    }


def _run_git(args: list[str], *, cwd: Path) -> dict[str, Any]:
    try:
        proc = subprocess.run(["git", *args], cwd=str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, check=False)
    except FileNotFoundError:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": "git not found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": "git timed out"}
    return {"ok": proc.returncode == 0, "returncode": proc.returncode, "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip()}


def get_repo_state(repo_root: Path = DEFAULT_REPO_ROOT, max_files: int = 40) -> dict[str, Any]:
    root = repo_root.resolve()
    git_dir = root / ".git"
    if not git_dir.exists():
        return {
            "ok": False,
            "mode": "read_only",
            "repo_root": str(root),
            "error": "not a git checkout",
        }
    branch = _run_git(["branch", "--show-current"], cwd=root)
    commit = _run_git(["rev-parse", "--short=12", "HEAD"], cwd=root)
    upstream = _run_git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], cwd=root)
    status = _run_git(["status", "--short", "--branch"], cwd=root)
    log = _run_git(["log", "-1", "--format=%h %cd %s", "--date=iso"], cwd=root)
    files = [line for line in status["stdout"].splitlines() if line and not line.startswith("##")]
    limit = max(0, min(int(max_files), 200))
    return {
        "ok": branch["ok"] and commit["ok"] and status["ok"],
        "mode": "read_only",
        "repo_root": str(root),
        "branch": branch["stdout"] if branch["ok"] else None,
        "commit": commit["stdout"] if commit["ok"] else None,
        "upstream": upstream["stdout"] if upstream["ok"] else None,
        "last_commit": log["stdout"] if log["ok"] else None,
        "dirty": bool(files),
        "dirty_count": len(files),
        "dirty_files": files[:limit],
        "dirty_files_truncated": len(files) > limit,
        "status_header": next((line for line in status["stdout"].splitlines() if line.startswith("##")), ""),
        "errors": [
            item["stderr"]
            for item in (branch, commit, upstream, status, log)
            if item.get("stderr") and not item.get("ok")
        ],
    }


def _parse_git_status_short_line(line: str) -> dict[str, str]:
    if line.startswith("?? "):
        path = line[3:].strip()
        return {"status": "??", "path": path, "old_path": ""}
    status = line[:2]
    path_text = line[3:].strip() if len(line) > 3 else ""
    old_path = ""
    if " -> " in path_text:
        old_path, path_text = path_text.split(" -> ", 1)
    return {"status": status.strip() or status, "path": path_text, "old_path": old_path}


def _dirty_category(path: str, status: str) -> str:
    if path.startswith("system/systemd/"):
        category = SERVICE_UNIT_DIRTY_CATEGORIES.get(Path(path).name)
        if category:
            return category
    for category, prefixes in DIRTY_CATEGORY_PREFIXES:
        for prefix in prefixes:
            if prefix.endswith(("/", "-")):
                if path.startswith(prefix):
                    return category
            elif path == prefix or path.endswith(prefix) or path.startswith(prefix):
                return category
    return "other"


def _dirty_attention(path: str, status: str, category: str) -> list[str]:
    attention: list[str] = []
    if category in {"config", "logicd", "hidd", "usbd", "usb_gadget", "systemd"}:
        attention.append("runtime_behavior")
    if category == "native_artifact":
        attention.append("native_binary")
    if status == "??":
        attention.append("untracked")
    if path.endswith(".before-keyboard-only-jis-id-20260612-233818"):
        attention.append("backup_artifact")
    return attention


def get_repo_dirty_summary(repo_root: Path = DEFAULT_REPO_ROOT, max_files: int = 80) -> dict[str, Any]:
    """Classify dirty files in a checkout for safer real-device reflection decisions."""
    root = repo_root.resolve()
    if not (root / ".git").exists():
        return {"ok": False, "mode": "read_only", "repo_root": str(root), "error": "not a git checkout"}
    status = _run_git(["status", "--short", "--branch"], cwd=root)
    if not status["ok"]:
        return {"ok": False, "mode": "read_only", "repo_root": str(root), "error": status["stderr"] or "git status failed"}
    lines = [line for line in status["stdout"].splitlines() if line and not line.startswith("##")]
    limit = max(0, min(int(max_files), 300))
    categories: dict[str, dict[str, Any]] = {}
    status_counts: dict[str, int] = {}
    untracked_count = 0
    attention: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    for line in lines:
        parsed = _parse_git_status_short_line(line)
        path = parsed["path"]
        status_code = parsed["status"]
        category = _dirty_category(path, status_code)
        item = {
            "status": status_code,
            "path": path,
            "old_path": parsed["old_path"] or None,
            "category": category,
            "attention": _dirty_attention(path, status_code, category),
        }
        entries.append(item)
        status_counts[status_code] = status_counts.get(status_code, 0) + 1
        if status_code == "??":
            untracked_count += 1
        bucket = categories.setdefault(category, {"count": 0, "sample": []})
        bucket["count"] += 1
        if len(bucket["sample"]) < min(limit, 20):
            bucket["sample"].append({"status": status_code, "path": path})
        if item["attention"]:
            attention.append(item)
    recommendations: list[str] = []
    if categories.get("native_artifact", {}).get("count"):
        recommendations.append("exclude native artifacts from checkout sync; rebuild ARM64 packages on the x86 cross-build host")
    if untracked_count:
        recommendations.append("review untracked files before git pull or broad rsync")
    if any(category in categories for category in ("config", "logicd", "hidd", "usbd", "usb_gadget", "systemd")):
        recommendations.append("runtime-affecting source changes are present; prefer targeted sync and explicit smoke checks")
    if categories.get("mcp", {}).get("count") and not any(category in categories for category in ("config", "logicd", "hidd", "usbd", "usb_gadget")):
        recommendations.append("dirty files are mostly MCP/docs; targeted read-only reflection is likely sufficient")
    return {
        "ok": True,
        "mode": "read_only",
        "repo_root": str(root),
        "status_header": next((line for line in status["stdout"].splitlines() if line.startswith("##")), ""),
        "dirty": bool(entries),
        "dirty_count": len(entries),
        "status_counts": status_counts,
        "untracked_count": untracked_count,
        "categories": categories,
        "attention_count": len(attention),
        "attention": attention[:limit],
        "attention_truncated": len(attention) > limit,
        "files": entries[:limit],
        "files_truncated": len(entries) > limit,
        "recommendations": recommendations,
    }


def _checkout_path_kind(root: Path, rel_path: str) -> str:
    path = root / rel_path.rstrip("/")
    if path.is_dir():
        return "directory"
    if path.is_file():
        return "file"
    if path.is_symlink():
        return "symlink"
    if path.exists():
        return "other"
    return "missing"


def get_checkout_hygiene_summary(repo_root: Path = DEFAULT_REPO_ROOT, max_files: int = 80) -> dict[str, Any]:
    """Summarize checkout hygiene issues before pull or manual reflection."""
    root = repo_root.resolve()
    dirty = get_repo_dirty_summary(repo_root=root, max_files=max_files)
    if not dirty.get("ok"):
        return {"ok": False, "mode": "read_only", "repo_root": str(root), "error": dirty.get("error"), "dirty_summary": dirty}

    files = dirty.get("files", []) if isinstance(dirty.get("files"), list) else []
    issues: list[dict[str, Any]] = []
    buckets: dict[str, int] = {
        "untracked_directory": 0,
        "untracked_file": 0,
        "runtime_affecting": 0,
        "native_artifact": 0,
        "backup_artifact": 0,
        "delete_or_missing": 0,
    }
    action_counts: dict[str, int] = {}
    items: list[dict[str, Any]] = []

    for item in files:
        path = str(item.get("path") or "")
        status = str(item.get("status") or "")
        category = str(item.get("category") or "other")
        attention = item.get("attention", []) if isinstance(item.get("attention"), list) else []
        path_kind = _checkout_path_kind(root, path) if path else "missing"
        if status == "??" and path_kind == "directory":
            bucket = "untracked_directory"
            action = "inspect_directory_before_sync"
            severity = "warning"
            summary = "untracked directory can make rsync wider than intended"
        elif status == "??":
            bucket = "untracked_file"
            action = "review_before_pull_or_sync"
            severity = "info"
            summary = "untracked file should be reviewed before pull or broad sync"
        elif "runtime_behavior" in attention:
            bucket = "runtime_affecting"
            action = "targeted_sync_with_smoke"
            severity = "warning"
            summary = "runtime-affecting source change needs explicit smoke"
        elif "native_binary" in attention or category == "native_artifact":
            bucket = "native_artifact"
            action = "exclude_and_rebuild_on_target"
            severity = "warning"
            summary = "native artifact should not be broad-synced across architectures"
        elif "backup_artifact" in attention:
            bucket = "backup_artifact"
            action = "archive_or_ignore"
            severity = "info"
            summary = "backup artifact should not drive reflection decisions"
        elif status == "D" or path_kind == "missing":
            bucket = "delete_or_missing"
            action = "confirm_delete_intent"
            severity = "warning"
            summary = "deleted or missing path needs explicit intent before sync"
        else:
            bucket = "ordinary_dirty"
            action = "include_if_in_selected_category"
            severity = "info"
            summary = "ordinary dirty path"

        if bucket in buckets:
            buckets[bucket] += 1
        action_counts[action] = action_counts.get(action, 0) + 1
        hygiene_item = {
            "path": path,
            "status": status,
            "category": category,
            "path_kind": path_kind,
            "bucket": bucket,
            "severity": severity,
            "recommended_action": action,
            "summary": summary,
        }
        items.append(hygiene_item)
        if severity == "warning":
            issues.append(hygiene_item)

    recommendations: list[str] = []
    if buckets["untracked_directory"]:
        recommendations.append("expand or remove untracked directories before using reflection apply plans")
    if buckets["runtime_affecting"]:
        recommendations.append("keep runtime-affecting changes out of broad sync unless smoke commands are explicit")
    if buckets["native_artifact"]:
        recommendations.append("exclude native artifacts and rebuild on the Raspberry Pi target")
    if dirty.get("files_truncated"):
        recommendations.append("increase max_files before making a reflection decision")
    if not recommendations:
        recommendations.append("checkout hygiene has no blocking recommendation")

    return {
        "ok": True,
        "mode": "read_only",
        "repo_root": str(root),
        "status": "needs_review" if issues else ("dirty_but_low_risk" if dirty.get("dirty") else "clean"),
        "dirty_count": dirty.get("dirty_count"),
        "untracked_count": dirty.get("untracked_count"),
        "issue_count": len(issues),
        "buckets": buckets,
        "action_counts": action_counts,
        "issues": issues[: max(0, min(int(max_files), 300))],
        "items": items[: max(0, min(int(max_files), 300))],
        "items_truncated": dirty.get("files_truncated"),
        "dirty_summary": {
            "categories": dirty.get("categories", {}),
            "status_counts": dirty.get("status_counts", {}),
            "recommendations": dirty.get("recommendations", []),
        },
        "recommendations": recommendations,
        "notes": [
            "This tool does not run git, delete files, clean directories, rsync, or edit the checkout.",
            "Use it before get_reflection_apply_plan when selected paths include directories or many untracked files.",
        ],
    }


def get_checkout_drift_summary(
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
    max_files: int = 80,
    reflection_categories: list[str] | None = None,
) -> dict[str, Any]:
    """Attribute dirty checkout drift to likely reflection or local-runtime buckets."""
    root = repo_root.resolve()
    categories = set(reflection_categories or DEFAULT_SELECTIVE_SYNC_CATEGORIES)
    hygiene = get_checkout_hygiene_summary(repo_root=root, max_files=max_files)
    repo = get_repo_state(repo_root=root, max_files=max_files)
    if not hygiene.get("ok"):
        return {"ok": False, "mode": "read_only", "repo_root": str(root), "error": hygiene.get("error"), "hygiene": hygiene}

    groups: dict[str, list[dict[str, Any]]] = {
        "reflection_candidates": [],
        "local_runtime_changes": [],
        "local_untracked_runtime": [],
        "ordinary_dirty": [],
        "backup_or_generated": [],
    }
    for item in hygiene.get("items", []):
        status = str(item.get("status") or "")
        category = str(item.get("category") or "other")
        bucket = str(item.get("bucket") or "")
        path = str(item.get("path") or "")
        drift_item = {
            "path": path,
            "status": status,
            "category": category,
            "path_kind": item.get("path_kind"),
            "hygiene_bucket": bucket,
            "recommended_action": item.get("recommended_action"),
        }
        if status == "??" and category in categories:
            drift_item["reason"] = "untracked file or directory in the current reflection categories"
            groups["reflection_candidates"].append(drift_item)
        elif status == "??" and category in {"config", "logicd", "hidd", "usbd", "usb_gadget", "systemd", "http"}:
            drift_item["reason"] = "untracked runtime-affecting source"
            groups["local_untracked_runtime"].append(drift_item)
        elif bucket == "runtime_affecting":
            drift_item["reason"] = "tracked runtime-affecting source differs from checkout"
            groups["local_runtime_changes"].append(drift_item)
        elif bucket in {"backup_artifact", "native_artifact"} or path.endswith(".before-keyboard-only-jis-id-20260612-233818"):
            drift_item["reason"] = "backup or generated artifact"
            groups["backup_or_generated"].append(drift_item)
        else:
            drift_item["reason"] = "ordinary dirty path outside runtime-critical buckets"
            groups["ordinary_dirty"].append(drift_item)

    counts = {name: len(items) for name, items in groups.items()}
    recommendations: list[str] = []
    if counts["reflection_candidates"]:
        recommendations.append("align the checkout with the pushed commit or narrow future rsync to explicit files before broad reflection")
    if any(item.get("path_kind") == "directory" for item in groups["reflection_candidates"]):
        recommendations.append("expand reflected directories to exact files before using reflection apply plans")
    if counts["local_runtime_changes"] or counts["local_untracked_runtime"]:
        recommendations.append("preserve or review runtime-affecting local changes before git pull, reset, or broad sync")
    if not recommendations:
        recommendations.append("checkout drift has no blocking recommendation")

    return {
        "ok": True,
        "mode": "read_only",
        "repo_root": str(root),
        "reflection_categories": sorted(categories),
        "status": "needs_review" if any(counts[name] for name in ("reflection_candidates", "local_runtime_changes", "local_untracked_runtime")) else hygiene.get("status"),
        "repo": {
            "branch": repo.get("branch"),
            "commit": repo.get("commit"),
            "upstream": repo.get("upstream"),
            "dirty_count": repo.get("dirty_count"),
        },
        "counts": counts,
        "groups": groups,
        "hygiene_status": hygiene.get("status"),
        "hygiene_issue_count": hygiene.get("issue_count"),
        "recommendations": recommendations,
        "notes": [
            "This tool does not run git pull, git clean, git reset, delete files, rsync, or edit the checkout.",
            "Attribution is heuristic: untracked files in reflection categories are treated as likely targeted-rsync artifacts.",
        ],
    }


def _parse_ahead_behind(stdout: str) -> dict[str, int | None]:
    parts = stdout.split()
    if len(parts) < 2:
        return {"behind": None, "ahead": None}
    try:
        left = int(parts[0])
        right = int(parts[1])
    except ValueError:
        return {"behind": None, "ahead": None}
    return {"behind": left, "ahead": right}


def get_pull_readiness_summary(
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
    max_files: int = 80,
    reflection_categories: list[str] | None = None,
) -> dict[str, Any]:
    """Summarize whether a checkout is ready for a manual git pull."""
    root = repo_root.resolve()
    repo = get_repo_state(repo_root=root, max_files=max_files)
    drift = get_checkout_drift_summary(repo_root=root, max_files=max_files, reflection_categories=reflection_categories)
    upstream = repo.get("upstream")
    ahead_behind = {"behind": None, "ahead": None}
    upstream_error = None
    if upstream:
        counts = _run_git(["rev-list", "--left-right", "--count", f"{upstream}...HEAD"], cwd=root)
        if counts.get("ok"):
            ahead_behind = _parse_ahead_behind(str(counts.get("stdout") or ""))
        else:
            upstream_error = counts.get("stderr") or "unable to compare upstream"
    else:
        upstream_error = "no upstream configured"

    drift_counts = drift.get("counts", {}) if isinstance(drift.get("counts"), dict) else {}
    blockers: list[dict[str, Any]] = []
    if not repo.get("ok"):
        blockers.append({"area": "repo", "reason": repo.get("errors") or "repo state unavailable"})
    if upstream_error:
        blockers.append({"area": "upstream", "reason": upstream_error})
    if int(drift_counts.get("local_runtime_changes", 0) or 0):
        blockers.append({"area": "local_runtime_changes", "reason": "tracked runtime-affecting files would be overwritten or conflicted by an unreviewed pull"})
    if int(drift_counts.get("local_untracked_runtime", 0) or 0):
        blockers.append({"area": "local_untracked_runtime", "reason": "untracked runtime-affecting files must be preserved or classified before pull"})
    if int(drift_counts.get("reflection_candidates", 0) or 0):
        blockers.append({"area": "reflection_candidates", "reason": "targeted reflection artifacts are present; align or narrow them before pull"})
    if repo.get("dirty"):
        blockers.append({"area": "dirty_checkout", "reason": "checkout is dirty; pull should wait for explicit preserve/clean decision"})

    behind = ahead_behind.get("behind")
    ahead = ahead_behind.get("ahead")
    recommendations: list[str] = []
    if blockers:
        recommendations.append("do not pull yet; review blockers and preserve or clean local changes first")
    elif behind and behind > 0:
        recommendations.append("manual pull is low-risk from checkout hygiene perspective")
    elif ahead and ahead > 0:
        recommendations.append("checkout has local commits ahead of upstream; push or inspect before pull")
    else:
        recommendations.append("checkout appears up to date with upstream")

    return {
        "ok": bool(repo.get("ok")) and bool(drift.get("ok")),
        "mode": "read_only",
        "repo_root": str(root),
        "status": "blocked" if blockers else ("ready_to_pull" if (behind or 0) > 0 else "no_pull_needed"),
        "branch": repo.get("branch"),
        "upstream": upstream,
        "commit": repo.get("commit"),
        "ahead": ahead,
        "behind": behind,
        "dirty": repo.get("dirty"),
        "dirty_count": repo.get("dirty_count"),
        "drift_counts": drift_counts,
        "blockers": blockers,
        "pre_pull_checks": [
            "inspect blockers",
            "preserve runtime-affecting local files",
            "avoid pulling over targeted-rsync artifacts",
            "run get_development_snapshot after any manual pull",
        ],
        "recommendations": recommendations,
        "notes": [
            "This tool does not run git fetch, git pull, git clean, git reset, delete files, rsync, or edit the checkout.",
            "Ahead/behind uses the existing local upstream refs; it does not contact the network.",
        ],
    }


def get_checkout_cleanup_candidates(
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
    max_files: int = 80,
    reflection_categories: list[str] | None = None,
) -> dict[str, Any]:
    """Suggest read-only preserve/cleanup buckets for a dirty checkout."""
    root = repo_root.resolve()
    drift = get_checkout_drift_summary(repo_root=root, max_files=max_files, reflection_categories=reflection_categories)
    pull = get_pull_readiness_summary(repo_root=root, max_files=max_files, reflection_categories=reflection_categories)
    if not drift.get("ok"):
        return {"ok": False, "mode": "read_only", "repo_root": str(root), "error": drift.get("error"), "drift": drift}

    groups = drift.get("groups", {}) if isinstance(drift.get("groups"), dict) else {}
    preserve = []
    cleanup = []
    review = []

    for source_group in ("local_runtime_changes", "local_untracked_runtime"):
        for item in groups.get(source_group, []) if isinstance(groups.get(source_group), list) else []:
            preserve.append(
                {
                    **item,
                    "source_group": source_group,
                    "recommended_next_step": "preserve_or_document_before_pull",
                    "why": "runtime-affecting local checkout state should not be discarded implicitly",
                }
            )

    for source_group in ("reflection_candidates", "backup_or_generated"):
        for item in groups.get(source_group, []) if isinstance(groups.get(source_group), list) else []:
            path_kind = item.get("path_kind")
            cleanup.append(
                {
                    **item,
                    "source_group": source_group,
                    "recommended_next_step": "inspect_directory_then_align_or_remove" if path_kind == "directory" else "confirm_pushed_then_align_or_remove",
                    "why": "likely targeted reflection or generated artifact is blocking clean pull readiness",
                }
            )

    for item in groups.get("ordinary_dirty", []) if isinstance(groups.get("ordinary_dirty"), list) else []:
        review.append(
            {
                **item,
                "source_group": "ordinary_dirty",
                "recommended_next_step": "review_before_pull",
                "why": "ordinary dirty file still blocks a clean pull decision",
            }
        )

    status = "needs_preserve_decision" if preserve else ("needs_cleanup_review" if cleanup else ("needs_review" if review else "clean"))
    recommendations: list[str] = []
    if preserve:
        recommendations.append("preserve or explicitly document runtime-affecting local changes before cleanup or pull")
    if cleanup:
        recommendations.append("confirm cleanup candidates are already represented in main or no longer needed before removing them")
    if review:
        recommendations.append("review ordinary dirty files before pull")
    if not recommendations:
        recommendations.append("no checkout cleanup candidates are currently visible")

    return {
        "ok": True,
        "mode": "read_only",
        "repo_root": str(root),
        "status": status,
        "pull_status": pull.get("status"),
        "counts": {
            "preserve": len(preserve),
            "cleanup_candidates": len(cleanup),
            "review": len(review),
        },
        "preserve": preserve,
        "cleanup_candidates": cleanup,
        "review": review,
        "read_only_checks": [
            "git status --short -- <path>",
            "git diff -- <path>",
            "git ls-files --others --exclude-standard -- <path>",
        ],
        "recommendations": recommendations,
        "notes": [
            "This tool does not run git clean, git reset, git checkout, rm, rsync, pull, fetch, or edit files.",
            "Cleanup classification is heuristic and must be confirmed by an operator before any destructive action.",
        ],
    }


def _git_diff_stat_for_path(root: Path, rel_path: str) -> dict[str, Any]:
    name_status = _run_git(["diff", "--name-status", "--", rel_path], cwd=root)
    numstat = _run_git(["diff", "--numstat", "--", rel_path], cwd=root)
    item: dict[str, Any] = {
        "name_status": None,
        "insertions": None,
        "deletions": None,
        "binary": False,
        "errors": [],
    }
    if name_status.get("ok") and name_status.get("stdout"):
        item["name_status"] = str(name_status["stdout"]).splitlines()[0].split("\t", 1)[0]
    elif not name_status.get("ok"):
        item["errors"].append(name_status.get("stderr") or "git diff --name-status failed")
    if numstat.get("ok") and numstat.get("stdout"):
        parts = str(numstat["stdout"]).splitlines()[0].split("\t")
        if len(parts) >= 2 and parts[0] == "-" and parts[1] == "-":
            item["binary"] = True
        elif len(parts) >= 2:
            try:
                item["insertions"] = int(parts[0])
                item["deletions"] = int(parts[1])
            except ValueError:
                item["errors"].append("unable to parse git diff --numstat")
    elif not numstat.get("ok"):
        item["errors"].append(numstat.get("stderr") or "git diff --numstat failed")
    return item


def get_checkout_preserve_diff_summary(
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
    max_files: int = 80,
    reflection_categories: list[str] | None = None,
) -> dict[str, Any]:
    """Summarize preserve-candidate diffs without returning diff hunks or file bodies."""
    root = repo_root.resolve()
    cleanup = get_checkout_cleanup_candidates(repo_root=root, max_files=max_files, reflection_categories=reflection_categories)
    if not cleanup.get("ok"):
        return {"ok": False, "mode": "read_only", "repo_root": str(root), "error": cleanup.get("error"), "cleanup": cleanup}

    items: list[dict[str, Any]] = []
    totals = {"tracked": 0, "untracked": 0, "insertions": 0, "deletions": 0, "binary": 0}
    limit = max(0, min(int(max_files), 300))
    for preserve_item in cleanup.get("preserve", [])[:limit] if isinstance(cleanup.get("preserve"), list) else []:
        rel_path = str(preserve_item.get("path") or "").rstrip("/")
        path = root / rel_path
        status = str(preserve_item.get("status") or "")
        item: dict[str, Any] = {
            "path": preserve_item.get("path"),
            "status": status,
            "category": preserve_item.get("category"),
            "source_group": preserve_item.get("source_group"),
            "path_kind": preserve_item.get("path_kind"),
            "summary_only": True,
        }
        if status == "??":
            totals["untracked"] += 1
            try:
                stat_result = path.stat()
                item["size"] = stat_result.st_size
            except OSError as exc:
                item["error"] = str(exc)
            item["diff"] = None
        else:
            totals["tracked"] += 1
            diff = _git_diff_stat_for_path(root, rel_path)
            item["diff"] = diff
            if diff.get("binary"):
                totals["binary"] += 1
            totals["insertions"] += int(diff.get("insertions") or 0)
            totals["deletions"] += int(diff.get("deletions") or 0)
        items.append(item)

    recommendations: list[str] = []
    if items:
        recommendations.append("review preserve diff summaries before cleanup, pull, or reset")
    if totals["untracked"]:
        recommendations.append("inspect untracked preserve files with read-only commands before deciding whether to keep them")
    if totals["insertions"] or totals["deletions"]:
        recommendations.append("tracked preserve files have local diff content that may need documentation or backup")
    if not recommendations:
        recommendations.append("no preserve diff candidates are currently visible")

    return {
        "ok": True,
        "mode": "read_only",
        "repo_root": str(root),
        "status": "has_preserve_diffs" if items else "no_preserve_diffs",
        "pull_status": cleanup.get("pull_status"),
        "counts": {
            "preserve": len(items),
            "tracked": totals["tracked"],
            "untracked": totals["untracked"],
            "binary": totals["binary"],
        },
        "totals": {
            "insertions": totals["insertions"],
            "deletions": totals["deletions"],
        },
        "items": items,
        "recommendations": recommendations,
        "redaction": "diff hunks, file bodies, and untracked file contents are not returned",
        "notes": [
            "This tool does not run git add, git checkout, git reset, git clean, rm, pull, fetch, rsync, or edit files.",
            "Tracked files are summarized with git diff --numstat and --name-status only.",
        ],
    }


def get_checkout_backup_plan_summary(
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
    max_files: int = 80,
    reflection_categories: list[str] | None = None,
    backup_root: Path | None = None,
) -> dict[str, Any]:
    """Return a read-only backup plan for preserve candidates."""
    root = repo_root.resolve()
    backup_base = backup_root or (root / ".codex-backups" / "checkout-preserve")
    preserve = get_checkout_preserve_diff_summary(repo_root=root, max_files=max_files, reflection_categories=reflection_categories)
    if not preserve.get("ok"):
        return {"ok": False, "mode": "read_only", "repo_root": str(root), "error": preserve.get("error"), "preserve": preserve}

    files: list[dict[str, Any]] = []
    total_size = 0
    preserve_items = preserve.get("items", []) if isinstance(preserve.get("items"), list) else []
    for item in preserve_items:
        rel_path = str(item.get("path") or "").rstrip("/")
        path = root / rel_path
        size = item.get("size")
        if size is None and path.is_file():
            try:
                size = path.stat().st_size
            except OSError:
                size = None
        if isinstance(size, int):
            total_size += size
        files.append(
            {
                "path": item.get("path"),
                "status": item.get("status"),
                "category": item.get("category"),
                "source_group": item.get("source_group"),
                "path_kind": item.get("path_kind"),
                "size": size,
                "tracked_diff": item.get("diff") is not None,
            }
        )

    path_args = [str(item["path"]).rstrip("/") for item in files if item.get("path")]
    backup_dir = str(backup_base)
    commands: list[str] = []
    if path_args:
        commands = [
            f"mkdir -p {_shell_join([backup_dir])}",
            _shell_join(["tar", "-czf", f"{backup_dir}/preserve-files.tgz", *path_args]),
            _shell_join(["git", "diff", "--binary", "--", *path_args]) + f" > {_shell_join([f'{backup_dir}/tracked.diff'])}",
            _shell_join(["git", "status", "--short", "--", *path_args]) + f" > {_shell_join([f'{backup_dir}/status.txt'])}",
        ]

    return {
        "ok": True,
        "mode": "read_only",
        "repo_root": str(root),
        "status": "backup_recommended" if files else "no_backup_needed",
        "backup_root": backup_dir,
        "counts": {
            "files": len(files),
            "tracked": preserve.get("counts", {}).get("tracked") if isinstance(preserve.get("counts"), dict) else None,
            "untracked": preserve.get("counts", {}).get("untracked") if isinstance(preserve.get("counts"), dict) else None,
        },
        "estimated_file_bytes": total_size,
        "files": files,
        "manual_commands": commands,
        "recommendations": [
            "make a manual backup before cleanup, pull, reset, or broad sync" if files else "no preserve backup candidates are currently visible",
            "store backups outside paths that may be cleaned or overwritten",
        ],
        "notes": [
            "This tool does not create directories, archive files, run git diff, write backup files, pull, clean, reset, rsync, or edit files.",
            "Manual commands are examples for an operator to review and run intentionally.",
        ],
    }


def get_manual_cleanup_verification_plan(
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
    max_files: int = 80,
    reflection_categories: list[str] | None = None,
    backup_root: Path | None = None,
    backup_confirmed: bool = False,
) -> dict[str, Any]:
    """Return a read-only final verification plan before manual cleanup or pull."""
    root = repo_root.resolve()
    cleanup = get_checkout_cleanup_candidates(repo_root=root, max_files=max_files, reflection_categories=reflection_categories)
    backup = get_checkout_backup_plan_summary(
        repo_root=root,
        max_files=max_files,
        reflection_categories=reflection_categories,
        backup_root=backup_root,
    )
    pull = get_pull_readiness_summary(repo_root=root, max_files=max_files, reflection_categories=reflection_categories)

    cleanup_counts = cleanup.get("counts", {}) if isinstance(cleanup.get("counts"), dict) else {}
    backup_counts = backup.get("counts", {}) if isinstance(backup.get("counts"), dict) else {}
    preserve_count = int(cleanup_counts.get("preserve", 0) or 0)
    cleanup_count = int(cleanup_counts.get("cleanup_candidates", 0) or 0)
    review_count = int(cleanup_counts.get("review", 0) or 0)
    backup_file_count = int(backup_counts.get("files", 0) or 0)

    blockers: list[dict[str, Any]] = []
    if not cleanup.get("ok"):
        blockers.append({"area": "cleanup_candidates", "reason": cleanup.get("error") or "cleanup candidate summary unavailable"})
    if not backup.get("ok"):
        blockers.append({"area": "backup_plan", "reason": backup.get("error") or "backup plan unavailable"})
    if not pull.get("ok"):
        blockers.append({"area": "pull_readiness", "reason": pull.get("error") or "pull readiness unavailable"})
    if preserve_count and backup_file_count and not backup_confirmed:
        blockers.append({"area": "backup_confirmation", "reason": "preserve candidates exist; confirm manual backup before cleanup or pull"})
    if cleanup_count:
        blockers.append({"area": "cleanup_candidates", "reason": "cleanup candidates require operator inspection before any removal or alignment"})
    if review_count:
        blockers.append({"area": "ordinary_dirty", "reason": "ordinary dirty files require operator review before pull"})
    if pull.get("status") == "blocked":
        blockers.append({"area": "pull_readiness", "reason": "pull readiness is still blocked by checkout state"})

    status = "blocked" if blockers else ("ready_for_manual_pull" if pull.get("status") == "ready_to_pull" else "no_manual_cleanup_needed")
    return {
        "ok": bool(cleanup.get("ok")) and bool(backup.get("ok")) and bool(pull.get("ok")),
        "mode": "read_only",
        "repo_root": str(root),
        "status": status,
        "backup_confirmed": backup_confirmed,
        "counts": {
            "preserve": preserve_count,
            "backup_files": backup_file_count,
            "cleanup_candidates": cleanup_count,
            "review": review_count,
            "pull_blockers": len(pull.get("blockers", [])) if isinstance(pull.get("blockers"), list) else None,
        },
        "blockers": blockers,
        "verification_steps": [
            "run get_checkout_backup_plan_summary and review the manual backup command examples",
            "confirm preserve candidates are backed up or intentionally documented",
            "inspect cleanup_candidates and ordinary dirty files with read-only commands",
            "perform any manual cleanup outside MCP only after operator confirmation",
            "rerun get_pull_readiness_summary before manual pull",
            "run get_development_snapshot after manual cleanup or pull",
        ],
        "related_tools": [
            "get_checkout_cleanup_candidates",
            "get_checkout_preserve_diff_summary",
            "get_checkout_backup_plan_summary",
            "get_pull_readiness_summary",
            "get_development_snapshot",
        ],
        "summaries": {
            "cleanup_status": cleanup.get("status"),
            "backup_status": backup.get("status"),
            "backup_root": backup.get("backup_root"),
            "pull_status": pull.get("status"),
            "ahead": pull.get("ahead"),
            "behind": pull.get("behind"),
        },
        "recommendations": [
            "do not run cleanup or pull until blockers is empty" if blockers else "manual pull can proceed from the current read-only checks",
            "keep backup artifacts outside paths that may be cleaned or overwritten",
        ],
        "notes": [
            "This tool does not create backups, run git clean, git reset, rm, git pull, git fetch, rsync, restart services, or edit files.",
            "backup_confirmed is an operator assertion; this tool does not verify archive contents.",
        ],
    }


def get_cleanup_review_order_summary(
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
    max_files: int = 80,
    reflection_categories: list[str] | None = None,
    backup_root: Path | None = None,
    backup_confirmed: bool = False,
) -> dict[str, Any]:
    """Return a read-only prioritized review order for manual cleanup decisions."""
    root = repo_root.resolve()
    cleanup = get_checkout_cleanup_candidates(repo_root=root, max_files=max_files, reflection_categories=reflection_categories)
    gate = get_manual_cleanup_verification_plan(
        repo_root=root,
        max_files=max_files,
        reflection_categories=reflection_categories,
        backup_root=backup_root,
        backup_confirmed=backup_confirmed,
    )
    if not cleanup.get("ok"):
        return {"ok": False, "mode": "read_only", "repo_root": str(root), "error": cleanup.get("error"), "cleanup": cleanup}

    ordered: list[dict[str, Any]] = []
    limit = max(0, min(int(max_files), 300))

    def add_items(bucket: str, items: list[dict[str, Any]], priority_base: int, action: str, reason: str) -> None:
        for index, item in enumerate(items):
            rel_path = str(item.get("path") or "").rstrip("/")
            path_kind = str(item.get("path_kind") or "unknown")
            status = str(item.get("status") or "")
            commands = [_shell_join(["git", "status", "--short", "--", rel_path])] if rel_path else []
            if rel_path and status != "??":
                commands.append(_shell_join(["git", "diff", "--stat", "--", rel_path]))
            if rel_path and (status == "??" or path_kind == "directory"):
                commands.append(_shell_join(["git", "ls-files", "--others", "--exclude-standard", "--", rel_path]))
            ordered.append(
                {
                    "priority": priority_base + index,
                    "bucket": bucket,
                    "path": item.get("path"),
                    "status": status,
                    "category": item.get("category"),
                    "source_group": item.get("source_group"),
                    "path_kind": item.get("path_kind"),
                    "recommended_next_step": item.get("recommended_next_step") or action,
                    "why": item.get("why") or reason,
                    "read_only_checks": commands,
                }
            )

    preserve = cleanup.get("preserve", []) if isinstance(cleanup.get("preserve"), list) else []
    cleanup_candidates = cleanup.get("cleanup_candidates", []) if isinstance(cleanup.get("cleanup_candidates"), list) else []
    review = cleanup.get("review", []) if isinstance(cleanup.get("review"), list) else []
    cleanup_dirs = [item for item in cleanup_candidates if item.get("path_kind") == "directory"]
    cleanup_files = [item for item in cleanup_candidates if item.get("path_kind") != "directory"]

    add_items("preserve", preserve, 1000, "preserve_or_document_before_pull", "runtime-affecting local state must be protected first")
    add_items("cleanup_directory", cleanup_dirs, 2000, "inspect_directory_then_align_or_remove", "directories can hide many files and should be expanded before cleanup")
    add_items("cleanup_file", cleanup_files, 3000, "confirm_pushed_then_align_or_remove", "single cleanup candidates should be checked against pushed state")
    add_items("review", review, 4000, "review_before_pull", "ordinary dirty files still block a clean pull decision")
    ordered = sorted(ordered, key=lambda item: (int(item["priority"]), str(item.get("path") or "")))[:limit]

    return {
        "ok": bool(cleanup.get("ok")) and bool(gate.get("ok")),
        "mode": "read_only",
        "repo_root": str(root),
        "status": "needs_ordered_review" if ordered else "clean",
        "gate_status": gate.get("status"),
        "backup_confirmed": backup_confirmed,
        "counts": {
            "ordered": len(ordered),
            "preserve": len(preserve),
            "cleanup_directories": len(cleanup_dirs),
            "cleanup_files": len(cleanup_files),
            "review": len(review),
            "gate_blockers": len(gate.get("blockers", [])) if isinstance(gate.get("blockers"), list) else None,
        },
        "ordered_review": ordered,
        "ordered_review_truncated": len(preserve) + len(cleanup_dirs) + len(cleanup_files) + len(review) > limit,
        "next_operator_loop": [
            "review ordered_review from lowest priority number to highest",
            "use only the read_only_checks while deciding what to preserve or clean",
            "make backups outside MCP if preserve items remain",
            "rerun get_manual_cleanup_verification_plan before manual cleanup or pull",
        ],
        "related_tools": [
            "get_manual_cleanup_verification_plan",
            "get_checkout_cleanup_candidates",
            "get_checkout_backup_plan_summary",
            "get_pull_readiness_summary",
        ],
        "notes": [
            "This tool does not create backups, run git clean, git reset, rm, git fetch, git pull, rsync, restart services, or edit files.",
            "Read-only command examples are for operator inspection only.",
        ],
    }


def _git_ref_path_state(root: Path, ref: str, rel_path: str, path_kind: str) -> dict[str, Any]:
    clean_path = rel_path.rstrip("/")
    if not clean_path:
        return {"state": "invalid_path", "tracked_count": 0, "sample": [], "errors": ["empty path"]}
    if path_kind == "directory":
        tree = _run_git(["ls-tree", "-r", "--name-only", ref, "--", clean_path], cwd=root)
        if not tree.get("ok"):
            return {"state": "ref_unavailable", "tracked_count": 0, "sample": [], "errors": [tree.get("stderr") or "git ls-tree failed"]}
        paths = [line for line in str(tree.get("stdout") or "").splitlines() if line]
        return {
            "state": "present_in_ref" if paths else "absent_in_ref",
            "tracked_count": len(paths),
            "sample": paths[:10],
            "errors": [],
        }
    exists = _run_git(["cat-file", "-e", f"{ref}:{clean_path}"], cwd=root)
    return {
        "state": "present_in_ref" if exists.get("ok") else "absent_in_ref",
        "tracked_count": 1 if exists.get("ok") else 0,
        "sample": [clean_path] if exists.get("ok") else [],
        "errors": [] if exists.get("ok") else ([exists.get("stderr")] if exists.get("stderr") else []),
    }


def get_reflection_cleanup_alignment_summary(
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
    max_files: int = 80,
    reflection_categories: list[str] | None = None,
    reference: str | None = None,
) -> dict[str, Any]:
    """Return read-only alignment hints for reflection cleanup candidates against a local git ref."""
    root = repo_root.resolve()
    cleanup = get_checkout_cleanup_candidates(repo_root=root, max_files=max_files, reflection_categories=reflection_categories)
    repo = get_repo_state(repo_root=root, max_files=max_files)
    if not cleanup.get("ok"):
        return {"ok": False, "mode": "read_only", "repo_root": str(root), "error": cleanup.get("error"), "cleanup": cleanup}
    ref = reference or str(repo.get("upstream") or "origin/main")
    ref_check = _run_git(["rev-parse", "--verify", "--quiet", ref], cwd=root)

    candidates = cleanup.get("cleanup_candidates", []) if isinstance(cleanup.get("cleanup_candidates"), list) else []
    limit = max(0, min(int(max_files), 300))
    items: list[dict[str, Any]] = []
    counts = {
        "cleanup_candidates": len(candidates),
        "present_in_ref": 0,
        "absent_in_ref": 0,
        "directory_candidates": 0,
        "file_candidates": 0,
        "needs_reference_update": 0,
    }
    for item in candidates[:limit]:
        rel_path = str(item.get("path") or "").rstrip("/")
        path_kind = str(item.get("path_kind") or "")
        if path_kind == "directory":
            counts["directory_candidates"] += 1
        else:
            counts["file_candidates"] += 1
        state = _git_ref_path_state(root, ref, rel_path, path_kind) if ref_check.get("ok") else {
            "state": "ref_unavailable",
            "tracked_count": 0,
            "sample": [],
            "errors": [ref_check.get("stderr") or f"reference not available: {ref}"],
        }
        ref_state = str(state.get("state") or "unknown")
        if ref_state == "present_in_ref":
            counts["present_in_ref"] += 1
            next_step = "compare_against_reference_before_manual_alignment"
            reason = "candidate path exists in the selected local reference"
        elif ref_state == "absent_in_ref":
            counts["absent_in_ref"] += 1
            next_step = "keep_or_investigate_before_cleanup"
            reason = "candidate path is not present in the selected local reference"
        else:
            counts["needs_reference_update"] += 1
            next_step = "refresh_or_select_reference_before_deciding"
            reason = "selected local reference could not be inspected"
        commands = []
        if rel_path:
            commands.append(_shell_join(["git", "status", "--short", "--", rel_path]))
            commands.append(_shell_join(["git", "ls-tree", "-r", "--name-only", ref, "--", rel_path]))
        items.append(
            {
                "path": item.get("path"),
                "status": item.get("status"),
                "category": item.get("category"),
                "source_group": item.get("source_group"),
                "path_kind": item.get("path_kind"),
                "reference_state": ref_state,
                "reference_tracked_count": state.get("tracked_count"),
                "reference_sample": state.get("sample", []),
                "reference_errors": state.get("errors", []),
                "recommended_next_step": next_step,
                "why": reason,
                "read_only_checks": commands,
            }
        )

    return {
        "ok": bool(cleanup.get("ok")) and bool(repo.get("ok")),
        "mode": "read_only",
        "repo_root": str(root),
        "reference": ref,
        "reference_available": bool(ref_check.get("ok")),
        "status": "has_reference_matches" if counts["present_in_ref"] else ("needs_reference_review" if candidates else "no_cleanup_candidates"),
        "counts": counts,
        "items": items,
        "items_truncated": len(candidates) > limit,
        "related_tools": [
            "get_cleanup_review_order_summary",
            "get_checkout_cleanup_candidates",
            "get_pull_readiness_summary",
        ],
        "recommendations": [
            "inspect present_in_ref candidates first; they are likely reflection artifacts already represented in the selected reference" if counts["present_in_ref"] else "no cleanup candidates are currently visible in the selected reference",
            "do not remove absent_in_ref candidates without a separate operator decision",
        ],
        "notes": [
            "This tool does not fetch, pull, clean, reset, remove, rsync, restart services, or edit files.",
            "Reference checks use only local git refs; they do not contact the network.",
        ],
    }


def _parse_stash_list(stdout: str, limit: int) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 4)
        if len(parts) < 5:
            entries.append({"ref": line.strip(), "short_hash": None, "date": None, "message": None})
            continue
        full_ref, ref, short_hash, date, message = parts
        entries.append({"ref": ref, "full_ref": full_ref, "short_hash": short_hash, "date": date, "message": message})
        if len(entries) >= limit:
            break
    return entries


def get_temporary_change_restore_plan_summary(
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
    stash_ref: str | None = None,
    max_stashes: int = 8,
) -> dict[str, Any]:
    """Return a read-only plan for inspecting and restoring temporary device changes."""
    root = repo_root.resolve()
    repo = get_repo_state(repo_root=root, max_files=20)
    stash_list = _run_git(["stash", "list", "--format=%gD%x09%gd%x09%h%x09%ci%x09%s"], cwd=root)
    if not stash_list.get("ok"):
        return {"ok": False, "mode": "read_only", "repo_root": str(root), "error": stash_list.get("stderr") or "git stash list failed"}

    limit = max(0, min(int(max_stashes), 50))
    entries = _parse_stash_list(str(stash_list.get("stdout") or ""), limit)
    selected_ref = stash_ref or (entries[0]["ref"] if entries else None)
    selected: dict[str, Any] | None = None
    if selected_ref:
        show_stat = _run_git(["stash", "show", "--stat", "--name-status", selected_ref], cwd=root)
        selected = {
            "ref": selected_ref,
            "available": bool(show_stat.get("ok")),
            "summary": str(show_stat.get("stdout") or "").splitlines()[:80],
            "error": show_stat.get("stderr") if not show_stat.get("ok") else None,
        }

    manual_commands: list[str] = []
    if selected_ref:
        manual_commands = [
            _shell_join(["git", "stash", "show", "--stat", "--name-status", selected_ref]),
            _shell_join(["git", "stash", "apply", "--index", selected_ref]),
            _shell_join(["git", "stash", "branch", f"restore-{selected_ref.replace('@', '').replace('{', '').replace('}', '')}", selected_ref]),
            _shell_join(["git", "stash", "drop", selected_ref]),
        ]

    status = "has_temporary_changes" if entries else "no_temporary_changes"
    if selected and not selected.get("available"):
        status = "selected_stash_unavailable"
    return {
        "ok": bool(repo.get("ok")),
        "mode": "read_only",
        "repo_root": str(root),
        "status": status,
        "repo": {
            "branch": repo.get("branch"),
            "commit": repo.get("commit"),
            "upstream": repo.get("upstream"),
            "dirty": repo.get("dirty"),
            "dirty_count": repo.get("dirty_count"),
        },
        "counts": {
            "listed_stashes": len(entries),
            "list_truncated": len(entries) >= limit and bool(str(stash_list.get("stdout") or "").splitlines()[limit:]),
        },
        "stashes": entries,
        "selected": selected,
        "manual_commands": manual_commands,
        "recommended_flow": [
            "inspect the selected stash before any restore",
            "prefer git stash branch when you want to review temporary changes away from the clean main checkout",
            "use git stash apply --index only when the clean checkout is the intended restore target",
            "drop the stash only after the restored state has been confirmed or intentionally discarded",
        ],
        "notes": [
            "This tool does not run git stash apply, git stash branch, git stash drop, git clean, git reset, pull, fetch, rsync, restart services, or edit files.",
            "Manual commands are examples for an operator to review and run intentionally.",
        ],
    }


def get_real_device_experiment_workflow_summary(
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
    max_files: int = 80,
    max_stashes: int = 5,
) -> dict[str, Any]:
    """Return a read-only gate for the real-device temporary experiment workflow."""
    root = repo_root.resolve()
    repo = get_repo_state(repo_root=root, max_files=max_files)
    dirty = get_repo_dirty_summary(repo_root=root, max_files=max_files)
    pull = get_pull_readiness_summary(repo_root=root, max_files=max_files)
    stash_plan = get_temporary_change_restore_plan_summary(repo_root=root, max_stashes=max_stashes)

    dirty_count = int(repo.get("dirty_count") or 0)
    stash_count = int(stash_plan.get("counts", {}).get("listed_stashes", 0) or 0) if isinstance(stash_plan.get("counts"), dict) else 0
    blockers: list[dict[str, Any]] = []
    if not repo.get("ok"):
        blockers.append({"area": "repo", "reason": repo.get("errors") or "repo state unavailable"})
    if dirty_count:
        blockers.append({"area": "dirty_checkout", "reason": "temporary experiment changes must be recorded and reverted before clean pull"})
    if pull.get("status") == "blocked":
        blockers.append({"area": "pull_readiness", "reason": "pull readiness is blocked; clean or record experiment changes first"})

    if dirty_count:
        status = "experiment_changes_need_revert"
    elif pull.get("status") == "ready_to_pull":
        status = "clean_ready_for_pull"
    elif pull.get("status") == "no_pull_needed":
        status = "clean_up_to_date"
    else:
        status = "needs_review"

    return {
        "ok": bool(repo.get("ok")) and bool(dirty.get("ok")) and bool(pull.get("ok")) and bool(stash_plan.get("ok")),
        "mode": "read_only",
        "repo_root": str(root),
        "status": status,
        "repo": {
            "branch": repo.get("branch"),
            "commit": repo.get("commit"),
            "upstream": repo.get("upstream"),
            "dirty": repo.get("dirty"),
            "dirty_count": repo.get("dirty_count"),
        },
        "pull_status": pull.get("status"),
        "stash_count": stash_count,
        "blockers": blockers,
        "required_operator_records": [
            "what was changed temporarily",
            "what behavior was observed",
            "which formal repository change is needed",
            "whether any stash must be kept as a safety backup",
        ],
        "read_only_checks": [
            "git status --short --branch",
            "git diff --stat",
            "git stash list",
            "python3 dev/mcp/keyboard/server.py --tool get_development_snapshot --max-files 40",
        ],
        "manual_commands_after_recording": [
            "git stash push -u -m 'experiment safety backup <topic> <date>'",
            "git reset --hard HEAD",
            "git clean -fd",
            "git pull --ff-only",
            "python3 dev/mcp/keyboard/server.py --tool get_development_snapshot --max-files 40",
        ],
        "recommended_flow": [
            "record experiment observations before reverting any temporary checkout change",
            "treat stash as insurance, not as the formal implementation source",
            "return the device checkout to clean state after the experiment",
            "implement the formal change in the repository, then commit and push",
            "update the clean device checkout with git pull --ff-only",
        ],
        "summaries": {
            "dirty_categories": dirty.get("categories", {}),
            "pull_blockers": pull.get("blockers", []),
            "latest_stash": stash_plan.get("stashes", [None])[0] if isinstance(stash_plan.get("stashes"), list) and stash_plan.get("stashes") else None,
        },
        "related_tools": [
            "get_development_snapshot",
            "get_pull_readiness_summary",
            "get_temporary_change_restore_plan_summary",
            "get_manual_cleanup_verification_plan",
        ],
        "notes": [
            "This tool does not run git stash, git reset, git clean, git pull, fetch, rsync, restart services, or edit files.",
            "Manual commands are examples for an operator to review and run intentionally after observations are recorded.",
        ],
    }


def _shell_join(args: list[str]) -> str:
    return " ".join(shlex.quote(str(arg)) for arg in args)


def _target_host(target: str) -> str:
    return target.rsplit("@", 1)[-1].strip()


def _resolve_host(host: str) -> dict[str, Any]:
    if not host:
        return {"ok": False, "host": host, "addresses": [], "error": "empty host"}
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        return {"ok": False, "host": host, "addresses": [], "error": str(exc)}
    addresses = sorted({item[4][0] for item in infos if item and item[4]})
    return {"ok": bool(addresses), "host": host, "addresses": addresses[:5], "error": None}


def _classify_ssh_probe_error(message: str) -> str:
    lower = message.lower()
    if "host key verification failed" in lower:
        return "host_key_verification_failed"
    if "permission denied" in lower or "publickey" in lower:
        return "authentication_failed"
    if "could not resolve hostname" in lower or "name or service not known" in lower:
        return "name_resolution_failed"
    if "connection timed out" in lower or "operation timed out" in lower or "ssh probe timed out" in lower:
        return "timeout"
    if "connection refused" in lower:
        return "connection_refused"
    if "no route to host" in lower:
        return "no_route_to_host"
    if "ssh command not found" in lower:
        return "ssh_missing"
    return "ssh_failed"


def _ssh_checkout_probe(target: str, repo_root: str, timeout_sec: float) -> dict[str, Any]:
    remote_script = (
        f"cd {shlex.quote(repo_root)} && "
        "git status --short --branch && "
        "git rev-parse --short=12 HEAD"
    )
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={max(1, int(timeout_sec))}",
        target,
        remote_script,
    ]
    try:
        proc = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=max(1.0, timeout_sec + 2.0),
            check=False,
        )
    except FileNotFoundError:
        error = "ssh command not found"
        return {
            "ok": False,
            "error": error,
            "error_kind": _classify_ssh_probe_error(error),
            "status_header": "",
            "commit": "",
            "dirty": None,
            "stderr": "",
        }
    except subprocess.TimeoutExpired:
        error = "ssh probe timed out"
        return {
            "ok": False,
            "error": error,
            "error_kind": _classify_ssh_probe_error(error),
            "status_header": "",
            "commit": "",
            "dirty": None,
            "stderr": "",
        }
    stdout_lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    status_header = stdout_lines[0] if stdout_lines and stdout_lines[0].startswith("##") else ""
    commit = stdout_lines[-1] if stdout_lines else ""
    dirty_lines = [line for line in stdout_lines if not line.startswith("##") and line != commit]
    stderr = " ".join(proc.stderr.split())[:300]
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "error": None if proc.returncode == 0 else stderr or "ssh probe failed",
        "error_kind": None if proc.returncode == 0 else _classify_ssh_probe_error(stderr or "ssh probe failed"),
        "status_header": status_header,
        "commit": commit if proc.returncode == 0 else "",
        "dirty": bool(dirty_lines) if proc.returncode == 0 else None,
        "dirty_count": len(dirty_lines) if proc.returncode == 0 else None,
        "stderr": stderr,
    }


def _ssh_error_read_only_checks(devices: list[dict[str, Any]], timeout_sec: float) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for item in devices:
        target = str(item.get("target") or "")
        host = str(item.get("host") or _target_host(target))
        probe = item.get("ssh_probe", {}) if isinstance(item.get("ssh_probe"), dict) else {}
        error_kind = probe.get("error_kind")
        if not error_kind:
            continue
        commands: list[str] = []
        if error_kind == "host_key_verification_failed":
            commands.extend(
                [
                    f"ssh-keygen -F {shlex.quote(host)}",
                    f"ssh-keyscan -T {max(1, int(timeout_sec))} -H {shlex.quote(host)}",
                ]
            )
        elif error_kind == "authentication_failed":
            commands.extend(
                [
                    "ssh-add -l",
                    f"ssh -o BatchMode=yes -o ConnectTimeout={max(1, int(timeout_sec))} {shlex.quote(target)} true",
                ]
            )
        elif error_kind == "name_resolution_failed":
            commands.extend([f"getent hosts {shlex.quote(host)}", f"ping -c 1 {shlex.quote(host)}"])
        elif error_kind in {"timeout", "no_route_to_host", "connection_refused"}:
            commands.extend([f"getent hosts {shlex.quote(host)}", f"ping -c 1 {shlex.quote(host)}"])
        elif error_kind == "ssh_missing":
            commands.append("command -v ssh")
        else:
            commands.append(f"ssh -o BatchMode=yes -o ConnectTimeout={max(1, int(timeout_sec))} {shlex.quote(target)} true")
        checks.append({"target": target, "host": host, "error_kind": error_kind, "commands": commands})
    return checks


def get_real_device_access_summary(
    *,
    targets: list[str] | None = None,
    repo_root: str = DEFAULT_REAL_DEVICE_REPO_ROOT,
    probe_ssh: bool = True,
    timeout_sec: float = 5.0,
) -> dict[str, Any]:
    """Summarize candidate real-device SSH access without writing to the device."""
    selected_targets = [str(item).strip() for item in (targets or list(DEFAULT_REAL_DEVICE_TARGETS)) if str(item).strip()]
    devices: list[dict[str, Any]] = []
    reachable_clean_targets: list[str] = []
    for target in selected_targets:
        host = _target_host(target)
        resolution = _resolve_host(host)
        ssh_probe: dict[str, Any]
        if probe_ssh and resolution["ok"]:
            ssh_probe = _ssh_checkout_probe(target, repo_root, timeout_sec)
            if ssh_probe.get("ok") and ssh_probe.get("dirty") is False:
                reachable_clean_targets.append(target)
        else:
            ssh_probe = {"skipped": not probe_ssh or not resolution["ok"]}
        devices.append(
            {
                "target": target,
                "host": host,
                "resolution": resolution,
                "ssh_probe": ssh_probe,
                "manual_commands": [
                    f"ssh -o BatchMode=yes -o ConnectTimeout={max(1, int(timeout_sec))} {shlex.quote(target)} true",
                    f"ssh -o BatchMode=yes -o ConnectTimeout={max(1, int(timeout_sec))} {shlex.quote(target)} "
                    + shlex.quote(f"cd {repo_root} && git status --short --branch && git rev-parse --short=12 HEAD"),
                ],
            }
        )
    reachable = [item for item in devices if item.get("ssh_probe", {}).get("ok")]
    ssh_error_kind_items = [
        str(item.get("ssh_probe", {}).get("error_kind"))
        for item in devices
        if item.get("ssh_probe", {}).get("error_kind")
    ]
    ssh_error_kinds = sorted(set(ssh_error_kind_items))
    status = "ready" if reachable_clean_targets else "reachable_needs_review" if reachable else "unreachable"
    recommendations: list[str] = []
    if reachable_clean_targets:
        recommendations.append(f"use {reachable_clean_targets[0]} for the next real-device read-only smoke")
    elif reachable:
        recommendations.append("inspect dirty remote checkout before pull or reflection")
    else:
        recommendations.append("retry with the last known numeric IP before relying on host aliases")
    if any(not item["resolution"]["ok"] for item in devices):
        recommendations.append("host aliases that fail DNS should be treated as convenience names, not canonical targets")
    if "host_key_verification_failed" in ssh_error_kinds:
        recommendations.append("host key verification failed; fix the SSH known_hosts/trust entry for that execution environment before using it as a probe source")
    if "authentication_failed" in ssh_error_kinds:
        recommendations.append("SSH authentication failed; check the remote user and key before selecting that target")
    if "timeout" in ssh_error_kinds or "no_route_to_host" in ssh_error_kinds:
        recommendations.append("network reachability failed; prefer the working numeric IP or check device power/network")
    next_read_only_checks = _ssh_error_read_only_checks(devices, timeout_sec)
    return {
        "ok": bool(reachable_clean_targets or reachable),
        "mode": "read_only",
        "status": status,
        "repo_root": repo_root,
        "probe_ssh": probe_ssh,
        "targets": devices,
        "selected_target": reachable_clean_targets[0] if reachable_clean_targets else reachable[0]["target"] if reachable else None,
        "counts": {
            "targets": len(devices),
            "resolved": sum(1 for item in devices if item["resolution"]["ok"]),
            "ssh_reachable": len(reachable),
            "reachable_clean": len(reachable_clean_targets),
            "ssh_error_kinds": {kind: ssh_error_kind_items.count(kind) for kind in ssh_error_kinds},
        },
        "recommendations": recommendations,
        "next_read_only_checks": next_read_only_checks,
        "notes": [
            "This tool only runs DNS resolution and read-only SSH/git status probes.",
            "It does not pull, fetch, stash, reset, clean, rsync, rebuild, restart, or edit files.",
            "Numeric IP targets are useful when mDNS or local hostname resolution is unstable.",
        ],
    }


def get_selective_sync_plan(
    *,
    target: str = DEFAULT_REAL_DEVICE_TARGET,
    repo_root: Path = DEFAULT_REPO_ROOT,
    categories: list[str] | None = None,
    max_files: int = 80,
) -> dict[str, Any]:
    """Return a read-only targeted rsync plan based on dirty-file categories."""
    selected = tuple(categories or DEFAULT_SELECTIVE_SYNC_CATEGORIES)
    dirty = get_repo_dirty_summary(repo_root=repo_root, max_files=max_files)
    if not dirty.get("ok"):
        return {"ok": False, "mode": "read_only", "target": target, "error": dirty.get("error"), "dirty_summary": dirty}
    root = repo_root.resolve()
    entries = dirty.get("files", [])
    selected_files = [
        item
        for item in entries
        if item.get("category") in selected and item.get("status") != "D" and item.get("path")
    ]
    selected_paths = sorted({str(item["path"]).rstrip("/") for item in selected_files})
    blocked = [
        item
        for item in entries
        if item.get("category") in {"native_artifact"} or "native_binary" in item.get("attention", [])
    ]
    runtime_attention = [
        item
        for item in entries
        if "runtime_behavior" in item.get("attention", []) and item.get("category") not in selected
    ]
    target_path = f"{target}:{DEFAULT_REAL_DEVICE_REPO_ROOT}/"
    rsync_args = ["rsync", "-az", "--relative", *selected_paths, target_path] if selected_paths else []
    smoke_commands = [
        "python3 -m py_compile dev/mcp/keyboard/server.py script/test_mcp_keyboard_server.py",
        "python3 script/test_mcp_keyboard_server.py",
        "python3 dev/mcp/keyboard/server.py --tool get_development_snapshot --include-http-status --max-files 4 --max-changes 2",
    ]
    recommendations: list[str] = []
    if not selected_paths:
        recommendations.append("no dirty files match the selected categories")
    if blocked:
        recommendations.append("native artifacts are present; keep them excluded and rebuild ARM64 packages on the x86 cross-build host")
    if runtime_attention:
        recommendations.append("runtime-affecting dirty files exist outside the selected categories; do not broad-sync without review")
    if dirty.get("untracked_count"):
        recommendations.append("review untracked files before any broad rsync or git pull")
    return {
        "ok": True,
        "mode": "read_only",
        "target": target,
        "repo_root": str(root),
        "selected_categories": list(selected),
        "selected_count": len(selected_paths),
        "selected_paths": selected_paths,
        "rsync_command": _shell_join(rsync_args) if rsync_args else None,
        "remote_smoke_commands": smoke_commands,
        "blocked_count": len(blocked),
        "blocked": blocked[: min(max_files, 80)],
        "runtime_attention_count": len(runtime_attention),
        "runtime_attention": runtime_attention[: min(max_files, 80)],
        "dirty_summary": {
            "dirty_count": dirty.get("dirty_count"),
            "untracked_count": dirty.get("untracked_count"),
            "categories": dirty.get("categories", {}),
            "recommendations": dirty.get("recommendations", []),
        },
        "notes": [
            "This tool does not run rsync, tests, service restarts, rebuilds, or git commands.",
            "This development-only MCP/docs reflection plan does not replace split package runtime updates.",
            "Use get_sync_safety_plan before any broad repository reflection.",
        ],
        "recommendations": recommendations,
    }


def get_reflection_apply_plan(
    *,
    target: str = DEFAULT_REAL_DEVICE_TARGET,
    repo_root: Path = DEFAULT_REPO_ROOT,
    categories: list[str] | None = None,
    max_files: int = 80,
    include_http_status: bool = True,
) -> dict[str, Any]:
    """Return a read-only operator plan for reflecting selected changes to a real device."""
    sync_plan = get_selective_sync_plan(target=target, repo_root=repo_root, categories=categories, max_files=max_files)
    readiness = get_update_readiness_summary(repo_root=repo_root, include_http_status=include_http_status)
    selected_paths = sync_plan.get("selected_paths", []) if isinstance(sync_plan.get("selected_paths"), list) else []
    selected_categories = sync_plan.get("selected_categories", []) if isinstance(sync_plan.get("selected_categories"), list) else []
    rsync_command = sync_plan.get("rsync_command")
    smoke_commands = sync_plan.get("remote_smoke_commands", []) if isinstance(sync_plan.get("remote_smoke_commands"), list) else []
    token_source = "\n".join([target, str(repo_root.resolve()), *selected_categories, *selected_paths])
    confirmation_token = hashlib.sha256(token_source.encode("utf-8")).hexdigest()[:12]

    blockers: list[dict[str, Any]] = []
    selected_directories = [
        path
        for path in selected_paths
        if (repo_root.resolve() / str(path).rstrip("/")).is_dir()
    ]
    if not sync_plan.get("ok"):
        blockers.append({"area": "selective_sync", "reason": sync_plan.get("error") or "selective sync plan unavailable"})
    if selected_directories:
        blockers.append({"area": "selected_directory", "reason": "selected paths include directories; review exact file list before manual rsync", "paths": selected_directories})
    if sync_plan.get("blocked_count"):
        blockers.append({"area": "native_artifact", "reason": "native artifacts are present; rebuild on target rather than syncing them"})
    if sync_plan.get("runtime_attention_count"):
        blockers.append({"area": "runtime_dirty", "reason": "runtime-affecting dirty files exist outside the selected categories"})
    if readiness.get("summary", {}).get("apply_tools_recommended_now") is not False:
        blockers.append({"area": "update_boundary", "reason": "update readiness summary did not keep apply tools out of scope"})

    stop_conditions = [
        "selected_paths is empty",
        "selected_paths includes a directory instead of explicit files",
        "blocked_count is non-zero",
        "runtime_attention_count is non-zero and the operator has not reviewed the files",
        "remote smoke command fails",
        "HTTP status or runtime issue summary regresses after reflection",
    ]
    manual_commands = []
    if rsync_command:
        manual_commands.append(rsync_command)
    manual_commands.extend(
        f"ssh {shlex.quote(target)} {shlex.quote('cd ' + DEFAULT_REAL_DEVICE_REPO_ROOT + ' && ' + command)}"
        for command in smoke_commands
    )

    return {
        "ok": sync_plan.get("ok") is True,
        "mode": "read_only",
        "target": target,
        "repo_root": str(repo_root.resolve()),
        "status": "blocked_pending_review" if blockers else ("ready_for_operator_review" if selected_paths else "no_selected_changes"),
        "confirmation": {
            "required_before_manual_apply": True,
            "token": confirmation_token,
            "phrase": f"REFLECT {confirmation_token}",
            "note": "The token is informational only; this read-only tool never accepts or executes confirmation.",
        },
        "selected": {
            "categories": selected_categories,
            "count": len(selected_paths),
            "paths": selected_paths,
        },
        "preflight": {
            "include_http_status": include_http_status,
            "readiness_ok": readiness.get("ok"),
            "apply_tools_recommended_now": readiness.get("summary", {}).get("apply_tools_recommended_now"),
            "repo_dirty_count": readiness.get("source_summaries", {}).get("repo", {}).get("dirty_count"),
            "http_status_ok": readiness.get("source_summaries", {}).get("http_status", {}).get("ok"),
        },
        "manual_commands": manual_commands,
        "phases": [
            {"name": "review", "checks": ["inspect selected paths", "inspect blockers", "confirm native artifacts are excluded"]},
            {"name": "reflect", "commands": [rsync_command] if rsync_command else []},
            {"name": "smoke", "commands": smoke_commands},
            {"name": "document", "checks": ["update docs if behavior changed", "record remaining real-device observations"]},
            {"name": "commit_push", "checks": ["run local tests", "review git diff", "commit", "push"]},
        ],
        "blockers": blockers,
        "stop_conditions": stop_conditions,
        "source_summaries": {
            "selective_sync": {
                "selected_count": sync_plan.get("selected_count"),
                "blocked_count": sync_plan.get("blocked_count"),
                "runtime_attention_count": sync_plan.get("runtime_attention_count"),
                "recommendations": sync_plan.get("recommendations", []),
            },
            "update_readiness": {
                "surface_count": readiness.get("summary", {}).get("surface_count"),
                "recommendations": readiness.get("recommendations", []),
            },
        },
        "notes": [
            "This tool does not run rsync, ssh, tests, rebuilds, service restarts, git commands, or update APIs.",
            "Use it as an operator checklist immediately before a manual real-device reflection pass.",
        ],
    }


def _file_item(path: Path, root: Path) -> dict[str, Any]:
    try:
        rel = str(path.relative_to(root))
    except ValueError:
        rel = str(path)
    try:
        st = path.stat()
    except OSError as exc:
        return {"path": rel, "name": path.name, "exists": False, "error": str(exc)}
    return {
        "path": rel,
        "name": path.name,
        "exists": True,
        "size": st.st_size,
        "mtime": st.st_mtime,
    }


def _read_task_json_summary(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": str(exc)}
    if not isinstance(data, dict):
        return {"ok": False, "error": "task json is not an object"}
    is_result = isinstance(data.get("task"), dict)
    task = data.get("task") if is_result else data
    checks = task.get("checks") if isinstance(task.get("checks"), list) else []
    result_checks = data.get("checks") if is_result and isinstance(data.get("checks"), list) else []
    errors = data.get("errors") if is_result and isinstance(data.get("errors"), list) else []
    return {
        "ok": True,
        "id": task.get("id"),
        "status": data.get("status"),
        "mode": task.get("mode"),
        "requested_by": task.get("requested_by"),
        "summary": task.get("summary"),
        "check_count": len(checks),
        "result_check_count": len(result_checks),
        "error_count": len(errors),
    }


def _summarize_mailbox_dir(root: Path, dirname: str, max_items: int) -> dict[str, Any]:
    directory = root / dirname
    if not directory.exists():
        return {
            "path": str(directory),
            "exists": False,
            "count": 0,
            "active_count": 0,
            "latest": [],
            "json_count": 0,
            "markdown_count": 0,
            "sample_count": 0,
        }
    files = [path for path in directory.iterdir() if path.is_file()]
    files.sort(key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)
    limit = max(0, min(int(max_items), 100))
    latest: list[dict[str, Any]] = []
    for path in files[:limit]:
        item = _file_item(path, root)
        if path.suffix == ".json" or path.name.endswith(".json.sample"):
            item["json_summary"] = _read_task_json_summary(path)
        latest.append(item)
    return {
        "path": str(directory),
        "exists": True,
        "count": len(files),
        "active_count": sum(1 for path in files if not path.name.endswith(".sample")),
        "json_count": sum(1 for path in files if path.suffix == ".json" or path.name.endswith(".json.sample")),
        "markdown_count": sum(1 for path in files if path.suffix == ".md" or path.name.endswith(".md.sample")),
        "sample_count": sum(1 for path in files if path.name.endswith(".sample")),
        "latest": latest,
        "truncated": len(files) > limit,
    }


def get_codex_task_mailbox_summary(
    *,
    tasks_dir: Path = DEFAULT_CODEX_TASKS_DIR,
    max_items: int = 5,
) -> dict[str, Any]:
    """Summarize the Codex task mailbox without returning task bodies or result markdown."""
    root = tasks_dir.resolve()
    sections = {
        name: _summarize_mailbox_dir(root, name, max_items)
        for name in ("inbox", "running", "done", "failed")
    }
    done_files = {item.name for item in (root / "done").iterdir()} if (root / "done").exists() else set()
    failed_files = {item.name for item in (root / "failed").iterdir()} if (root / "failed").exists() else set()
    result_pairs: list[dict[str, Any]] = []
    limit = max(0, min(int(max_items), 100))
    for dirname, names in (("done", done_files), ("failed", failed_files)):
        result_ids = sorted(
            name.removesuffix(".result.json")
            for name in names
            if name.endswith(".result.json")
        )
        for result_id in (result_ids[-limit:] if limit else []):
            result_pairs.append(
                {
                    "status": dirname,
                    "id": result_id,
                    "json": f"{result_id}.result.json" in names,
                    "markdown": f"{result_id}.result.md" in names,
                }
            )
    pending = sections["inbox"].get("active_count", 0) + sections["running"].get("active_count", 0)
    return {
        "ok": root.exists(),
        "mode": "read_only",
        "tasks_dir": str(root),
        "sections": sections,
        "pending_count": pending,
        "result_pairs": result_pairs,
        "recommendations": [
            "process inbox tasks before adding new real-device requests" if pending else "mailbox has no pending tasks",
            "keep worker writes limited to codex_tasks/done or codex_tasks/failed",
        ],
        "redaction": "task/result JSON is summarized; markdown bodies and command stdout/stderr are not returned",
    }


def get_development_snapshot(
    *,
    include_systemctl: bool = True,
    include_http_status: bool = True,
    include_real_device_access: bool = False,
    repo_root: Path = DEFAULT_REPO_ROOT,
    max_files: int = 20,
    max_changes: int = 10,
) -> dict[str, Any]:
    """Return a compact read-only snapshot useful at the start of a dev pass."""
    repo = get_repo_state(repo_root=repo_root, max_files=max_files)
    dirty_summary = get_repo_dirty_summary(repo_root=repo_root, max_files=max_files)
    checkout_hygiene = get_checkout_hygiene_summary(repo_root=repo_root, max_files=max_files)
    access = check_runtime_access()
    preflight = run_preflight(include_systemctl=include_systemctl)
    keymap = get_keymap_summary(max_changes=max_changes)
    scripts = get_script_summary()
    codex_mcp = get_codex_mcp_status(repo_root=repo_root)
    sync_plan = get_sync_safety_plan(repo_root=repo_root)
    selective_sync = get_selective_sync_plan(repo_root=repo_root, max_files=max(max_files, 80))
    systemd_units = get_systemd_unit_summary(repo_root=repo_root) if include_systemctl else {"ok": None, "services": {}, "skipped": True}
    mailbox = get_codex_task_mailbox_summary(tasks_dir=repo_root / "codex_tasks", max_items=3)
    http_status = get_http_status_summary(timeout_sec=2.0) if include_http_status else {"ok": None, "summary": {}, "error": "skipped"}
    real_device_access = (
        get_real_device_access_summary(timeout_sec=3.0)
        if include_real_device_access
        else {"ok": None, "status": "skipped", "selected_target": None, "counts": {}, "recommendations": []}
    )
    output_readiness = _output_readiness_from(preflight, http_status if include_http_status else None)
    runtime_issues = _runtime_issue_items_from(output_readiness, systemd_units if include_systemctl else None)
    runtime_state = get_runtime_state_summary(include_keymap_diff=False)
    return {
        "ok": bool(repo.get("ok")) and bool(preflight.get("ok")) and bool(scripts.get("ok")),
        "mode": "read_only",
        "repo": {
            "ok": repo.get("ok"),
            "repo_root": repo.get("repo_root"),
            "branch": repo.get("branch"),
            "commit": repo.get("commit"),
            "upstream": repo.get("upstream"),
            "dirty": repo.get("dirty"),
            "dirty_count": repo.get("dirty_count"),
            "dirty_files": repo.get("dirty_files", []),
            "dirty_files_truncated": repo.get("dirty_files_truncated"),
            "dirty_categories": dirty_summary.get("categories", {}),
            "dirty_attention_count": dirty_summary.get("attention_count"),
            "dirty_recommendations": dirty_summary.get("recommendations", []),
            "hygiene_status": checkout_hygiene.get("status"),
            "hygiene_issue_count": checkout_hygiene.get("issue_count"),
            "hygiene_recommendations": checkout_hygiene.get("recommendations", []),
        },
        "runtime_access": {
            "user": access.get("identity", {}).get("user"),
            "group": access.get("identity", {}).get("group"),
            "runtime_keymap_readable": access.get("runtime_keymap_readable"),
            "paths": access.get("paths", []),
        },
        "preflight": {
            "ok": preflight.get("ok"),
            "summary": preflight.get("summary", {}),
            "service_status": preflight.get("service_status", {}),
        },
        "keymap": {
            "ok": keymap.get("ok"),
            "layer_count": keymap.get("layer_count"),
            "changed_from_default": keymap.get("changed_from_default"),
            "changed_by_layer": keymap.get("changed_by_layer", []),
            "errors": keymap.get("errors", []),
        },
        "scripts": {
            "ok": scripts.get("ok"),
            "count": scripts.get("count"),
            "dangerous_count": scripts.get("dangerous_count"),
            "missing": scripts.get("missing", []),
            "unreadable": scripts.get("unreadable", []),
        },
        "codex_mcp": {
            "ok": codex_mcp.get("ok"),
            "codex_cli": codex_mcp.get("codex_cli"),
            "project_trusted": codex_mcp.get("project", {}).get("trusted"),
            "keyboard_server": codex_mcp.get("keyboard_server"),
        },
        "sync_safety": {
            "native_artifact_count": len(sync_plan.get("native_artifacts", [])),
            "architecture_warning_count": len(sync_plan.get("architecture_warnings", [])),
            "rsync_excludes": sync_plan.get("rsync_excludes", []),
        },
        "selective_sync": {
            "ok": selective_sync.get("ok"),
            "selected_categories": selective_sync.get("selected_categories", []),
            "selected_count": selective_sync.get("selected_count"),
            "runtime_attention_count": selective_sync.get("runtime_attention_count"),
            "blocked_count": selective_sync.get("blocked_count"),
            "recommendations": selective_sync.get("recommendations", []),
        },
        "systemd_units": {
            "ok": systemd_units.get("ok"),
            "skipped": systemd_units.get("skipped", False),
            "service_count": len(systemd_units.get("services", {})),
            "recommendations": systemd_units.get("recommendations", []),
        },
        "codex_task_mailbox": {
            "ok": mailbox.get("ok"),
            "pending_count": mailbox.get("pending_count"),
            "active_counts": {name: section.get("active_count", 0) for name, section in mailbox.get("sections", {}).items()},
            "total_counts": {name: section.get("count", 0) for name, section in mailbox.get("sections", {}).items()},
            "recommendations": mailbox.get("recommendations", []),
        },
        "http_status": {
            "ok": http_status.get("ok"),
            "summary": http_status.get("summary", {}),
            "error": http_status.get("error"),
        },
        "real_device_access": {
            "ok": real_device_access.get("ok"),
            "status": real_device_access.get("status"),
            "selected_target": real_device_access.get("selected_target"),
            "counts": real_device_access.get("counts", {}),
            "recommendations": real_device_access.get("recommendations", []),
            "next_read_only_checks": real_device_access.get("next_read_only_checks", []),
        },
        "output_readiness": {
            "ok": output_readiness.get("ok"),
            "readiness": output_readiness.get("readiness", {}),
            "issues": output_readiness.get("issues", []),
        },
        "runtime_issues": {
            "issue_count": len([item for item in runtime_issues if item.get("severity") != "ok"]),
            "items": runtime_issues,
        },
        "runtime_state": {
            "ok": runtime_state.get("ok"),
            "led_state": runtime_state.get("led_state"),
            "bluetooth_hosts": runtime_state.get("bluetooth_hosts"),
            "board_profile": runtime_state.get("board_profile"),
            "errors": runtime_state.get("errors", []),
        },
        "errors": {
            "repo": repo.get("errors", []) or ([repo.get("error")] if repo.get("error") else []),
            "preflight": preflight.get("errors", []),
            "keymap": keymap.get("errors", []),
        },
    }


def get_real_device_work_start_summary(
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
    include_http_status: bool = True,
    max_files: int = 20,
    max_changes: int = 5,
) -> dict[str, Any]:
    """Return a compact read-only start order for real-device work."""
    snapshot = get_development_snapshot(
        include_systemctl=False,
        include_http_status=include_http_status,
        include_real_device_access=True,
        repo_root=repo_root,
        max_files=max_files,
        max_changes=max_changes,
    )
    access = snapshot.get("real_device_access", {}) if isinstance(snapshot.get("real_device_access"), dict) else {}
    repo = snapshot.get("repo", {}) if isinstance(snapshot.get("repo"), dict) else {}
    runtime_access = snapshot.get("runtime_access", {}) if isinstance(snapshot.get("runtime_access"), dict) else {}
    output = snapshot.get("output_readiness", {}) if isinstance(snapshot.get("output_readiness"), dict) else {}
    output_issues = output.get("issues", []) if isinstance(output.get("issues"), list) else []
    runtime_paths = runtime_access.get("paths", []) if isinstance(runtime_access.get("paths"), list) else []
    unreadable_runtime_paths = [
        item
        for item in runtime_paths
        if isinstance(item, dict) and item.get("exists") and item.get("readable") is False
    ]
    output_issue_sample = output_issues[:5]
    blockers: list[dict[str, Any]] = []
    if access.get("status") != "ready":
        blockers.append({"area": "real_device_access", "reason": access.get("status"), "next_read_only_checks": access.get("next_read_only_checks", [])})
    if repo.get("dirty_count"):
        blockers.append({"area": "local_checkout", "reason": "local checkout has dirty files", "dirty_count": repo.get("dirty_count")})
    if runtime_access.get("runtime_keymap_readable") is False:
        blockers.append(
            {
                "area": "runtime_access",
                "reason": "runtime keymap is not readable",
                "unreadable_paths": unreadable_runtime_paths[:5],
                "next_read_only_checks": ["python3 dev/mcp/keyboard/server.py --tool check_runtime_access --path /mnt/p3/keymap.json"],
            }
        )
    if output_issues:
        blockers.append(
            {
                "area": "output_readiness",
                "reason": "output readiness has issues",
                "issue_count": len(output_issues),
                "issue_sample": output_issue_sample,
                "next_read_only_checks": [
                    "python3 dev/mcp/keyboard/server.py --tool get_output_readiness_summary --include-http-status",
                    "python3 dev/mcp/keyboard/server.py --tool get_runtime_issue_summary --include-http-status",
                ],
            }
        )

    selected_target = access.get("selected_target")
    status = "ready_for_real_device_work" if selected_target and not blockers else "needs_review"
    ordered_steps = [
        {
            "step": "select_target",
            "status": "ready" if selected_target else "needs_review",
            "summary": selected_target or "no reachable clean target selected",
            "checks": access.get("next_read_only_checks", []),
        },
        {
            "step": "confirm_local_checkout",
            "status": "ready" if not repo.get("dirty_count") else "needs_review",
            "summary": f"{repo.get('branch')} {repo.get('commit')} dirty={repo.get('dirty_count')}",
            "checks": ["git status --short --branch", "git log -1 --oneline"],
        },
        {
            "step": "confirm_runtime_readiness",
            "status": "ready" if runtime_access.get("runtime_keymap_readable") is not False else "needs_review",
            "summary": f"runtime_keymap_readable={runtime_access.get('runtime_keymap_readable')}",
            "checks": ["python3 dev/mcp/keyboard/server.py --tool check_runtime_access --path /mnt/p3/keymap.json"],
        },
        {
            "step": "confirm_output_readiness",
            "status": "ready" if not output_issues else "needs_review",
            "summary": f"issue_count={len(output_issues)}",
            "checks": ["python3 dev/mcp/keyboard/server.py --tool get_output_readiness_summary --include-http-status"],
        },
        {
            "step": "choose_next_action",
            "status": "ready" if status == "ready_for_real_device_work" else "blocked_until_review",
            "summary": "run manual smoke or reflection plan only after earlier steps are ready",
            "checks": ["python3 dev/mcp/keyboard/server.py --tool get_reflection_apply_plan --include-http-status"],
        },
    ]
    return {
        "ok": bool(snapshot.get("ok")),
        "mode": "read_only",
        "status": status,
        "selected_target": selected_target,
        "blockers": blockers,
        "ordered_steps": ordered_steps,
        "source_summary": {
            "repo": {"branch": repo.get("branch"), "commit": repo.get("commit"), "dirty_count": repo.get("dirty_count")},
            "real_device_access": {
                "status": access.get("status"),
                "counts": access.get("counts", {}),
                "recommendations": access.get("recommendations", []),
            },
            "runtime_access": {
                "runtime_keymap_readable": runtime_access.get("runtime_keymap_readable"),
                "unreadable_paths": unreadable_runtime_paths[:5],
            },
            "output_readiness": {
                "issue_count": len(output_issues),
                "issue_sample": output_issue_sample,
            },
        },
        "notes": [
            "This tool only summarizes existing read-only diagnostics.",
            "It does not run pull, fetch, stash, reset, clean, rsync, rebuild, restart, key send, or file edits.",
        ],
    }


def _read_toml(path: Path) -> tuple[dict[str, Any], str | None]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return {}, f"missing file: {path}"
    except OSError as exc:
        return {}, f"cannot read file: {path}: {exc}"
    except tomllib.TOMLDecodeError as exc:
        return {}, f"invalid toml in {path}: {exc}"


def _safe_mcp_server_config(config: dict[str, Any], server_name: str) -> dict[str, Any]:
    servers = config.get("mcp_servers", {})
    server = servers.get(server_name) if isinstance(servers, dict) else None
    if not isinstance(server, dict):
        return {"configured": False, "name": server_name}
    transport = "http" if server.get("url") else "stdio"
    safe: dict[str, Any] = {
        "configured": True,
        "name": server_name,
        "enabled": bool(server.get("enabled", True)),
        "transport": transport,
        "startup_timeout_sec": server.get("startup_timeout_sec"),
        "tool_timeout_sec": server.get("tool_timeout_sec"),
        "default_tools_approval_mode": server.get("default_tools_approval_mode"),
        "enabled_tools": server.get("enabled_tools") if isinstance(server.get("enabled_tools"), list) else None,
        "disabled_tools": server.get("disabled_tools") if isinstance(server.get("disabled_tools"), list) else None,
        "has_env": isinstance(server.get("env"), dict) and bool(server.get("env")),
        "env_vars": server.get("env_vars") if isinstance(server.get("env_vars"), list) else None,
    }
    if transport == "stdio":
        safe.update(
            {
                "command": server.get("command"),
                "args": server.get("args") if isinstance(server.get("args"), list) else None,
                "cwd": server.get("cwd"),
            }
        )
    else:
        safe.update(
            {
                "url": server.get("url"),
                "uses_bearer_token_env_var": bool(server.get("bearer_token_env_var")),
                "has_static_http_headers": isinstance(server.get("http_headers"), dict) and bool(server.get("http_headers")),
                "has_env_http_headers": isinstance(server.get("env_http_headers"), dict) and bool(server.get("env_http_headers")),
            }
        )
    return safe


def get_codex_mcp_status(
    *,
    config_path: Path = DEFAULT_CODEX_CONFIG,
    repo_root: Path = DEFAULT_REPO_ROOT,
    server_name: str = "keyboard",
) -> dict[str, Any]:
    """Return a redacted summary of local Codex MCP registration state."""
    config, error = _read_toml(config_path)
    codex_cli = shutil.which("codex")
    projects = config.get("projects", {}) if isinstance(config, dict) else {}
    repo_resolved = str(repo_root.resolve())
    project_config = projects.get(repo_resolved) if isinstance(projects, dict) else None
    trusted = isinstance(project_config, dict) and project_config.get("trust_level") == "trusted"
    server_config = _safe_mcp_server_config(config, server_name)
    expected_script = str((ROOT / "dev" / "mcp" / "keyboard" / "server.py").resolve())
    args = server_config.get("args") if isinstance(server_config.get("args"), list) else []
    matches_this_checkout = (
        server_config.get("transport") == "stdio"
        and server_config.get("command") in {"python", "python3", sys.executable}
        and expected_script in args
        and "--stdio" in args
    )
    recommendations: list[str] = []
    if error:
        recommendations.append("create or fix Codex config.toml before relying on MCP registration")
    if not codex_cli:
        recommendations.append("install Codex CLI before using `codex mcp` registration")
    if not trusted:
        recommendations.append("mark this repository as trusted for project-scoped Codex settings")
    if not server_config.get("configured"):
        recommendations.append("register this server with `codex mcp add keyboard -- python3 dev/mcp/keyboard/server.py --stdio`")
    elif not matches_this_checkout:
        recommendations.append("review keyboard MCP command/args; it does not point at this checkout's stdio server")
    return {
        "ok": not error and bool(codex_cli) and bool(trusted) and bool(server_config.get("configured")) and matches_this_checkout,
        "mode": "read_only",
        "config_path": str(config_path),
        "config_readable": error is None,
        "error": error,
        "codex_cli": {"path": codex_cli, "available": bool(codex_cli)},
        "project": {"repo_root": repo_resolved, "trusted": trusted, "config": project_config if isinstance(project_config, dict) else None},
        "keyboard_server": {**server_config, "matches_this_checkout": matches_this_checkout},
        "auth_boundary": "stdio uses OS user, SSH, trusted-project, and filesystem permissions; no MCP bearer token or OAuth is used",
        "redaction": "env values, bearer token env names, and HTTP header values are not returned",
        "recommendations": recommendations,
    }


def _file_description(path: Path) -> dict[str, Any]:
    item = {
        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "exists": path.exists(),
        "executable": os.access(path, os.X_OK),
        "file": None,
        "architecture_warning": None,
    }
    if not path.exists():
        return item
    try:
        proc = subprocess.run(["file", str(path)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, check=False)
    except FileNotFoundError:
        item["file"] = "file command not found"
        return item
    except subprocess.TimeoutExpired:
        item["file"] = "file command timed out"
        return item
    description = proc.stdout.strip() or proc.stderr.strip()
    item["file"] = description
    if "x86-64" in description or "x86_64" in description:
        item["architecture_warning"] = "x86-64 artifact; exclude it from device sync and rebuild ARM64 packages on the x86 cross-build host"
    return item


def get_sync_safety_plan(*, target: str = DEFAULT_REAL_DEVICE_TARGET, repo_root: Path = DEFAULT_REPO_ROOT) -> dict[str, Any]:
    """Return a read-only package-first safety plan for real-device reflection."""
    root = repo_root.resolve()
    artifacts = [_file_description(root / artifact) for artifact in NATIVE_ARTIFACTS]
    excludes = list(BASE_RSYNC_EXCLUDES)
    exclude_args = " ".join(f"--exclude {json.dumps(item)}" for item in excludes)
    target_path = f"{target}:{DEFAULT_REAL_DEVICE_REPO_ROOT}/"
    return {
        "ok": True,
        "mode": "read_only",
        "repo_root": str(root),
        "target": target,
        "standard_update": "split_debian_packages",
        "native_artifacts": artifacts,
        "architecture_warnings": [item for item in artifacts if item.get("architecture_warning")],
        "rsync_excludes": excludes,
        "legacy_recovery_rsync_example": f"rsync -az --delete {exclude_args} ./ {target_path}",
        "cross_build_commands": [
            "make cross-build-host-check DEVICE=02",
            "make core-deb-package",
            "make DEVICE_PROFILE=keyboard-ver1 profile-deb-package",
            "tools/package/release_candidate_check.sh --split-profile keyboard-ver1",
        ],
        "install_and_verify_commands": [
            "sudo apt install ./hidloom-core_<version>_arm64.deb ./hidloom-profile-keyboard-ver1_<version>_all.deb",
            "sudo hidloom-profile keyboard-ver1 --apply --backup --restart",
            "systemctl is-active hidloom-usb-gadget viald hidloom-hidd hidloom-uidd hidloom-outputd hidloom-logicd-core logicd-companion matrixd ledd i2cd httpd btd",
        ],
        "notes": [
            "This tool does not run rsync, package builds, installs, or restart commands.",
            "Broad checkout rsync is legacy/recovery-only; standard updates use same-version core/profile packages.",
            "Keep native x86-64 binaries out of Raspberry Pi sync payloads.",
            "Run get_development_snapshot or run_preflight after manual reflection.",
        ],
    }


def _summarize_http_status(data: dict[str, Any]) -> dict[str, Any]:
    processes = data.get("processes") if isinstance(data.get("processes"), dict) else {}
    hid = data.get("hid") if isinstance(data.get("hid"), dict) else {}
    output = data.get("output") if isinstance(data.get("output"), dict) else {}
    hidd = data.get("hidd") if isinstance(data.get("hidd"), dict) else {}
    hid_broker = data.get("hid_broker") if isinstance(data.get("hid_broker"), dict) else {}
    usbd = data.get("usbd") if isinstance(data.get("usbd"), dict) else {}
    broker = hid_broker or hidd or usbd
    text_send = data.get("text_send") if isinstance(data.get("text_send"), dict) else {}
    bluetooth = data.get("bluetooth") if isinstance(data.get("bluetooth"), dict) else {}
    wifi = data.get("wifi") if isinstance(data.get("wifi"), dict) else {}
    spid = data.get("spid") if isinstance(data.get("spid"), dict) else {}
    optional_processes = {"spid"}
    required_processes = {name: active for name, active in processes.items() if name not in optional_processes}
    required_values = [bool(value) for value in required_processes.values()]
    optional_inactive = sorted(name for name in optional_processes if name in processes and not processes.get(name))
    broker_summary = {
        "owner": broker.get("owner"),
        "process": broker.get("process"),
        "hidd_process": broker.get("hidd_process"),
        "usbd_process": broker.get("usbd_process"),
        "broker_ready": broker.get("broker_ready"),
        "hid_report_socket": broker.get("hid_report_socket"),
        "hidd_hid_report_socket_env": broker.get("hidd_hid_report_socket_env"),
        "hid_report_socket_enabled_env": broker.get("hid_report_socket_enabled_env"),
        "logicd_broker_enabled_env": broker.get("logicd_broker_enabled_env"),
    }
    return {
        "processes": {
            "ok": bool(required_values) and all(required_values),
            "items": processes,
            "inactive": sorted(name for name, active in required_processes.items() if not active),
            "required_inactive": sorted(name for name, active in required_processes.items() if not active),
            "optional_inactive": optional_inactive,
            "optional": sorted(optional_processes),
        },
        "hid": {
            "device": hid.get("device"),
            "exists": hid.get("exists"),
            "connected": hid.get("connected"),
            "udc_state": hid.get("udc_state"),
        },
        "output": {
            "mode": data.get("mode"),
            "target": data.get("output_target"),
            "display_label": output.get("display_label"),
            "runtime_mode_label": output.get("runtime_mode_label"),
        },
        "hid_broker": broker_summary,
        "usbd": broker_summary,
        "text_send": {
            "available": text_send.get("available"),
            "runner_ready": text_send.get("runner_ready"),
            "real_send_allowed": text_send.get("real_send_allowed"),
            "blocking_reasons": text_send.get("blocking_reasons", []),
        },
        "bluetooth": {
            "available": bluetooth.get("available"),
            "powered": bluetooth.get("powered"),
            "pairable": bluetooth.get("pairable"),
            "discoverable": bluetooth.get("discoverable"),
            "paired_count": len(bluetooth.get("paired_devices", []) if isinstance(bluetooth.get("paired_devices"), list) else []),
            "connected_count": len(bluetooth.get("connected_devices", []) if isinstance(bluetooth.get("connected_devices"), list) else []),
        },
        "wifi": {
            "available": wifi.get("available"),
            "powered": wifi.get("powered"),
            "connected": wifi.get("connected"),
            "blocked": wifi.get("blocked"),
            "recovery_first": wifi.get("recovery_first"),
            "persistent_power_off": wifi.get("persistent_power_off"),
        },
        "spid": {
            "process": spid.get("process"),
            "events_socket": spid.get("events_socket"),
            "ctrl_socket": spid.get("ctrl_socket"),
        },
    }


def get_http_status_summary(
    *,
    url: str = DEFAULT_HTTP_STATUS_URL,
    username: str = "admin",
    password: str | None = None,
    timeout_sec: float = 5.0,
    verify_tls: bool = False,
) -> dict[str, Any]:
    """Fetch and summarize the local HTTP status API without returning credentials."""
    password_value = password if password is not None else socket.gethostname()
    request = urllib.request.Request(url)
    token = base64.b64encode(f"{username}:{password_value}".encode("utf-8")).decode("ascii")
    request.add_header("Authorization", f"Basic {token}")
    context = None if verify_tls else ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(request, context=context, timeout=timeout_sec) as response:
            raw = response.read()
            status_code = response.status
        data = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"ok": False, "mode": "read_only", "url": url, "http_status": exc.code, "error": str(exc), "credentials_returned": False}
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "mode": "read_only", "url": url, "http_status": None, "error": str(exc), "credentials_returned": False}
    summary = _summarize_http_status(data if isinstance(data, dict) else {})
    return {
        "ok": True,
        "mode": "read_only",
        "url": url,
        "http_status": status_code,
        "summary": summary,
        "credentials_returned": False,
    }


def _output_readiness_from(preflight: dict[str, Any], http_status: dict[str, Any] | None = None) -> dict[str, Any]:
    http_summary = (http_status or {}).get("summary", {}) if isinstance(http_status, dict) else {}
    preflight_summary = preflight.get("summary", {}) if isinstance(preflight, dict) else {}
    routes = preflight.get("routes", {}) if isinstance(preflight, dict) else {}
    issues: list[dict[str, Any]] = []

    services_ok = preflight_summary.get("services_ok")
    hid_devices_present = bool(preflight_summary.get("hid_devices_present"))
    sockets_present = bool(preflight_summary.get("sockets_present"))
    config_ok = bool(preflight_summary.get("config_ok"))
    if services_ok is False:
        inactive = [
            name
            for name, status in preflight.get("service_status", {}).get("services", {}).items()
            if status != "active"
        ]
        issues.append({"severity": "error", "area": "services", "message": "one or more core services are not active", "detail": inactive})
    if not hid_devices_present:
        issues.append({"severity": "error", "area": "hid", "message": "one or more HID gadget devices are missing"})
    if not sockets_present:
        issues.append({"severity": "warning", "area": "sockets", "message": "one or more expected runtime sockets are missing"})
    if not config_ok:
        issues.append({"severity": "error", "area": "config", "message": "repository config could not be read cleanly"})

    http_ok = bool((http_status or {}).get("ok"))
    hid = http_summary.get("hid", {}) if isinstance(http_summary.get("hid"), dict) else {}
    hid_broker = http_summary.get("hid_broker", {}) if isinstance(http_summary.get("hid_broker"), dict) else {}
    if not hid_broker and isinstance(http_summary.get("usbd"), dict):
        hid_broker = http_summary["usbd"]
    text_send = http_summary.get("text_send", {}) if isinstance(http_summary.get("text_send"), dict) else {}
    processes = http_summary.get("processes", {}) if isinstance(http_summary.get("processes"), dict) else {}
    spid = http_summary.get("spid", {}) if isinstance(http_summary.get("spid"), dict) else {}

    if http_status is not None and not http_ok:
        issues.append({"severity": "warning", "area": "http", "message": "HTTP status summary is unavailable", "detail": http_status.get("error")})
    if http_ok and hid.get("connected") is not True:
        issues.append({"severity": "warning", "area": "hid", "message": "HTTP status does not report HID connected", "detail": hid})
    if http_ok and hid_broker.get("broker_ready") is not True:
        issues.append(
            {
                "severity": "info",
                "area": "hid_broker",
                "message": "HID broker is not fully ready according to HTTP status",
                "detail": {
                    "owner": hid_broker.get("owner"),
                    "hidd_hid_report_socket_env": hid_broker.get("hidd_hid_report_socket_env"),
                    "hid_report_socket_enabled_env": hid_broker.get("hid_report_socket_enabled_env"),
                    "logicd_broker_enabled_env": hid_broker.get("logicd_broker_enabled_env"),
                    "socket": hid_broker.get("hid_report_socket"),
                },
            }
        )
    if http_ok and text_send.get("real_send_allowed") is not True:
        issues.append(
            {
                "severity": "info",
                "area": "text_send",
                "message": "real text-send is blocked by safety gates",
                "detail": text_send.get("blocking_reasons", []),
            }
        )
    if http_ok and processes.get("inactive"):
        issues.append({"severity": "info", "area": "http_processes", "message": "HTTP status reports inactive required processes", "detail": processes.get("inactive")})

    keyboard_routes_ok = all(
        routes.get(keycode, {}).get("endpoint")
        for keycode in ("KC_A", "KC_ZKHK", "KC_HENKAN", "KC_KANA")
    )
    readiness = {
        "core_preflight_ok": bool(preflight.get("ok")) and config_ok and hid_devices_present and sockets_present and services_ok is not False,
        "usb_keyboard_routes_ok": keyboard_routes_ok,
        "http_status_ok": http_ok,
        "hid_connected": hid.get("connected") if http_ok else None,
        "hid_broker_ready": hid_broker.get("broker_ready") if http_ok else None,
        "usbd_broker_ready": hid_broker.get("broker_ready") if http_ok else None,
        "text_send_real_allowed": text_send.get("real_send_allowed") if http_ok else None,
        "spid_active": spid.get("process") if http_ok else None,
    }
    return {
        "ok": bool(readiness["core_preflight_ok"] and readiness["usb_keyboard_routes_ok"]),
        "mode": "read_only",
        "readiness": readiness,
        "routes": routes,
        "http": http_summary if http_ok else {"ok": False, "error": (http_status or {}).get("error") if isinstance(http_status, dict) else None},
        "issues": issues,
    }


def get_output_readiness_summary(*, include_systemctl: bool = True, include_http_status: bool = True) -> dict[str, Any]:
    """Combine preflight and HTTP status into a compact output-route readiness summary."""
    preflight = run_preflight(include_systemctl=include_systemctl)
    http_status = get_http_status_summary(timeout_sec=2.0) if include_http_status else None
    result = _output_readiness_from(preflight, http_status)
    result["preflight"] = {
        "ok": preflight.get("ok"),
        "summary": preflight.get("summary", {}),
        "service_status": preflight.get("service_status", {}),
    }
    return result


def _service_active(preflight: dict[str, Any], name: str) -> bool | None:
    services = preflight.get("service_status", {}).get("services", {}) if isinstance(preflight, dict) else {}
    if not isinstance(services, dict) or name not in services:
        return None
    return services.get(name) == "active"


def get_interface_snapshot(*, include_systemctl: bool = True, include_http_status: bool = True) -> dict[str, Any]:
    """Return a read-only HTTP / Vial / BLE-facing interface snapshot."""
    preflight = run_preflight(include_systemctl=include_systemctl)
    http_status = get_http_status_summary(timeout_sec=2.0) if include_http_status else None
    runtime_state = get_runtime_state_summary(include_keymap_diff=False)
    http_summary = http_status.get("summary", {}) if isinstance(http_status, dict) and http_status.get("ok") else {}
    processes = http_summary.get("processes", {}) if isinstance(http_summary.get("processes"), dict) else {}
    hid = http_summary.get("hid", {}) if isinstance(http_summary.get("hid"), dict) else {}
    output = http_summary.get("output", {}) if isinstance(http_summary.get("output"), dict) else {}
    bluetooth = http_summary.get("bluetooth", {}) if isinstance(http_summary.get("bluetooth"), dict) else {}
    wifi = http_summary.get("wifi", {}) if isinstance(http_summary.get("wifi"), dict) else {}
    runtime_bt = runtime_state.get("bluetooth_hosts") if isinstance(runtime_state.get("bluetooth_hosts"), dict) else None

    service_names = ("httpd", "viald", "btd")
    services = {name: {"active": _service_active(preflight, name)} for name in service_names}
    inactive = [name for name, state in services.items() if state["active"] is False]
    recommendations: list[str] = []
    if http_status is not None and not http_status.get("ok"):
        recommendations.append("HTTP /api/status is unavailable; inspect httpd before relying on UI health")
    if services["viald"]["active"] is False:
        recommendations.append("viald is inactive; Vial access should be treated as unavailable")
    if bluetooth.get("available") is False or bluetooth.get("powered") is False:
        recommendations.append("Bluetooth is unavailable or powered off; BLE host checks are not meaningful")
    if not recommendations:
        recommendations.append("snapshot is read-only and has no immediate action recommendation")

    ok = (
        preflight.get("ok") is True
        and (http_status is None or http_status.get("ok") is True)
        and all(state["active"] is not False for state in services.values())
    )
    return {
        "ok": ok,
        "mode": "read_only",
        "http": {
            "queried": include_http_status,
            "ok": http_status.get("ok") if isinstance(http_status, dict) else None,
            "status": http_status.get("http_status") if isinstance(http_status, dict) else None,
            "processes_ok": processes.get("ok"),
            "inactive_processes": processes.get("inactive", []),
            "hid": hid,
            "output": output,
            "wifi": wifi,
        },
        "vial": {
            "service_active": services["viald"]["active"],
            "expected_service": "viald",
            "hid_connected": hid.get("connected") if hid else None,
            "note": "Vial protocol probing is not performed; this snapshot reports service and HID/API readiness only.",
        },
        "ble": {
            "service_active": services["btd"]["active"],
            "available": bluetooth.get("available"),
            "powered": bluetooth.get("powered"),
            "pairable": bluetooth.get("pairable"),
            "discoverable": bluetooth.get("discoverable"),
            "paired_count": bluetooth.get("paired_count"),
            "connected_count": bluetooth.get("connected_count"),
            "runtime_hosts": runtime_bt,
        },
        "services": services,
        "preflight": {
            "ok": preflight.get("ok"),
            "summary": preflight.get("summary", {}),
            "skipped_systemctl": preflight.get("service_status", {}).get("skipped"),
        },
        "recommendations": recommendations,
        "notes": [
            "This tool does not pair, forget, restart services, call Vial commands, or write settings.",
            "Bluetooth addresses, HTTP credentials, and full runtime JSON are not returned.",
        ],
    }


def _runtime_issue_items_from(readiness: dict[str, Any], systemd_units: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    readiness_state = readiness.get("readiness", {}) if isinstance(readiness.get("readiness"), dict) else {}
    unit_services = (systemd_units or {}).get("services", {}) if isinstance(systemd_units, dict) else {}
    hidd_env = (
        unit_services.get("hidloom-hidd", {})
        .get("expected_environment", {})
        .get("missing", [])
        if isinstance(unit_services.get("hidloom-hidd"), dict)
        else []
    )
    outputd_env = (
        unit_services.get("hidloom-outputd", {})
        .get("expected_environment", {})
        .get("missing", [])
        if isinstance(unit_services.get("hidloom-outputd"), dict)
        else []
    )
    core_env = (
        unit_services.get("hidloom-logicd-core", {})
        .get("expected_environment", {})
        .get("missing", [])
        if isinstance(unit_services.get("hidloom-logicd-core"), dict)
        else []
    )

    for issue in readiness.get("issues", []):
        area = issue.get("area")
        if area in {"hid_broker", "usbd"}:
            cause = "unknown"
            if "USBD_HID_REPORT_SOCKET" in hidd_env:
                cause = "hidd_report_socket_missing"
            elif "OUTPUTD_USB_SOCKET" in outputd_env:
                cause = "outputd_usb_socket_missing"
            elif "LOGICD_CORE_HID_REPORT_SOCKET" in core_env:
                cause = "logicd_core_output_socket_missing"
            issues.append(
                {
                    "area": "hid_broker",
                    "severity": "info",
                    "summary": "HID broker is not fully ready",
                    "probable_cause": cause,
                    "detail": issue.get("detail"),
                    "next_checks": [
                        "python3 dev/mcp/keyboard/server.py --tool get_systemd_unit_summary --unit-service hidloom-hidd",
                        "python3 dev/mcp/keyboard/server.py --tool get_systemd_unit_summary --unit-service hidloom-outputd",
                        "python3 dev/mcp/keyboard/server.py --tool get_systemd_unit_summary --unit-service hidloom-logicd-core",
                    ],
                }
            )
        elif area == "text_send":
            issues.append(
                {
                    "area": "text_send",
                    "severity": "info",
                    "summary": "real text-send is blocked by safety gates",
                    "blocking_reasons": issue.get("detail", []),
                    "next_checks": [
                        "python3 dev/mcp/keyboard/server.py --tool get_http_status_summary",
                    ],
                }
            )
        elif area == "spid":
            issues.append(
                {
                    "area": "spid",
                    "severity": "info",
                    "summary": "SPID is inactive",
                    "probable_cause": "optional_sensor_daemon_disabled_or_not_in_scope",
                    "next_checks": ["ignore unless SPI mouse sensor work is in scope"],
                }
            )
        elif area in {"services", "hid", "sockets", "config"}:
            issues.append(
                {
                    "area": area,
                    "severity": issue.get("severity", "warning"),
                    "summary": issue.get("message"),
                    "detail": issue.get("detail"),
                    "next_checks": [
                        "python3 dev/mcp/keyboard/server.py --tool run_preflight",
                        "python3 dev/mcp/keyboard/server.py --tool collect_journal_excerpt --service hidloom-logicd-core --lines 80",
                    ],
                }
            )

    if not issues and readiness_state.get("core_preflight_ok") and readiness_state.get("usb_keyboard_routes_ok"):
        issues.append(
            {
                "area": "runtime",
                "severity": "ok",
                "summary": "core USB keyboard route readiness is clean",
                "next_checks": [],
            }
        )
    return issues


def get_runtime_issue_summary(*, include_systemctl: bool = True, include_http_status: bool = True) -> dict[str, Any]:
    """Summarize runtime issues and likely next read-only checks."""
    readiness = get_output_readiness_summary(include_systemctl=include_systemctl, include_http_status=include_http_status)
    systemd_units = get_systemd_unit_summary() if include_systemctl else {"ok": None, "services": {}, "skipped": True}
    issue_items = _runtime_issue_items_from(readiness, systemd_units)
    return {
        "ok": bool(readiness.get("ok")),
        "mode": "read_only",
        "readiness": readiness.get("readiness", {}),
        "issue_count": len([item for item in issue_items if item.get("severity") != "ok"]),
        "issues": issue_items,
        "systemd_units": {
            "ok": systemd_units.get("ok"),
            "skipped": systemd_units.get("skipped", False),
            "recommendations": systemd_units.get("recommendations", []),
        },
        "notes": [
            "This tool does not restart services, edit unit files, send keys, or change runtime state.",
            "Use get_output_readiness_summary for the underlying readiness payload.",
        ],
    }


def get_runtime_state_summary(
    *,
    keymap_path: Path = DEFAULT_RUNTIME_KEYMAP,
    led_state_path: Path = DEFAULT_RUNTIME_LED_STATE,
    bluetooth_hosts_path: Path = DEFAULT_RUNTIME_BLUETOOTH_HOSTS,
    board_profile_path: Path = DEFAULT_RUNTIME_BOARD_PROFILE,
    include_keymap_diff: bool = True,
    max_changes: int = 5,
) -> dict[str, Any]:
    """Summarize runtime JSON state files without returning full contents."""
    files = {
        "keymap": _runtime_json_file_summary(keymap_path),
        "led_state": _runtime_json_file_summary(led_state_path),
        "bluetooth_hosts": _runtime_json_file_summary(bluetooth_hosts_path),
        "board_profile": _runtime_json_file_summary(board_profile_path),
    }

    led_doc, led_error = _read_json(led_state_path)
    bt_doc, bt_error = _read_json(bluetooth_hosts_path)
    board_doc, board_error = _read_json(board_profile_path)
    keymap = get_keymap_summary(current_keymap_path=keymap_path, max_changes=max_changes) if include_keymap_diff else None

    led_summary = None
    if isinstance(led_doc, dict):
        led_summary = {key: led_doc.get(key) for key in ("mode", "speed", "h", "s", "v") if key in led_doc}

    bluetooth_summary = None
    if isinstance(bt_doc, dict):
        hosts = bt_doc.get("hosts", {})
        if isinstance(hosts, dict):
            bluetooth_summary = {
                "version": bt_doc.get("version"),
                "host_count": len(hosts),
                "hosts": [
                    {
                        "index": index,
                        "has_display_name": bool(value.get("display_name")) if isinstance(value, dict) else False,
                        "last_seen_name": value.get("last_seen_name") if isinstance(value, dict) else None,
                        "last_connected_at": value.get("last_connected_at") if isinstance(value, dict) else None,
                    }
                    for index, value in enumerate(hosts.values())
                ],
            }

    board_summary = None
    if isinstance(board_doc, dict):
        board_summary = {
            "board_version": board_doc.get("board_version"),
            "prototype": board_doc.get("prototype"),
            "device_name": board_doc.get("device_name"),
            "selected_by": board_doc.get("selected_by"),
            "selected_at": board_doc.get("selected_at"),
        }

    errors = [
        error
        for error in (
            files["keymap"].get("error"),
            led_error,
            bt_error,
            board_error,
            *(keymap.get("errors", []) if isinstance(keymap, dict) else []),
        )
        if error
    ]
    return {
        "ok": not errors,
        "mode": "read_only",
        "files": files,
        "keymap": {
            "ok": keymap.get("ok") if isinstance(keymap, dict) else None,
            "layer_count": keymap.get("layer_count") if isinstance(keymap, dict) else None,
            "changed_from_default": keymap.get("changed_from_default") if isinstance(keymap, dict) else None,
            "sample_changes": keymap.get("sample_changes", []) if isinstance(keymap, dict) else [],
        },
        "led_state": led_summary,
        "bluetooth_hosts": bluetooth_summary,
        "board_profile": board_summary,
        "redaction": "full keymap, full LED JSON, Bluetooth addresses, and script bodies are not returned",
        "errors": errors,
    }


def _path_access_by_path(access: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("path")): item
        for item in access.get("paths", [])
        if isinstance(item, dict) and item.get("path") is not None
    }


def get_update_readiness_summary(
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
    include_http_status: bool = True,
) -> dict[str, Any]:
    """Summarize prerequisites before any future update-capable MCP surface."""
    runtime_access = check_runtime_access()
    access_by_path = _path_access_by_path(runtime_access)
    keymap_access = access_by_path.get(str(DEFAULT_RUNTIME_KEYMAP), {})
    repo = get_repo_dirty_summary(repo_root=repo_root, max_files=20)
    sync_plan = get_sync_safety_plan(repo_root=repo_root)
    http_status = get_http_status_summary(timeout_sec=2.0) if include_http_status else {"ok": None, "summary": {}}
    http_summary = http_status.get("summary", {}) if isinstance(http_status, dict) else {}
    output = http_summary.get("output", {}) if isinstance(http_summary.get("output"), dict) else {}
    text_send = http_summary.get("text_send", {}) if isinstance(http_summary.get("text_send"), dict) else {}
    bluetooth = http_summary.get("bluetooth", {}) if isinstance(http_summary.get("bluetooth"), dict) else {}

    runtime_attention_count = int(repo.get("runtime_attention_count", 0) or 0)
    untracked_count = int(repo.get("untracked_count", 0) or 0)
    arch_warning_count = len(sync_plan.get("architecture_warnings", []) if isinstance(sync_plan.get("architecture_warnings"), list) else [])
    identity = runtime_access.get("identity", {}) if isinstance(runtime_access.get("identity"), dict) else {}

    surfaces = {
        "keymap_update": {
            "status": "needs_design",
            "readiness": {
                "runtime_keymap_exists": keymap_access.get("exists"),
                "runtime_keymap_readable": keymap_access.get("readable"),
                "runtime_keymap_writable_by_current_user": keymap_access.get("writable"),
            },
            "required_before_apply": [
                "schema validation",
                "backup and atomic write plan",
                "reload or service interaction plan",
                "rollback path",
            ],
        },
        "service_restart": {
            "status": "needs_explicit_ops_procedure",
            "readiness": {
                "service_allowlist": list(DEFAULT_SERVICES),
                "systemd_read_supported": True,
            },
            "required_before_apply": [
                "unit allowlist",
                "restart order",
                "post-restart smoke",
                "rollback or operator recovery note",
            ],
        },
        "selective_sync": {
            "status": "plan_available",
            "readiness": {
                "dirty_count": repo.get("dirty_count"),
                "runtime_attention_count": runtime_attention_count,
                "untracked_count": untracked_count,
                "architecture_warning_count": arch_warning_count,
            },
            "required_before_apply": [
                "explicit file list",
                "native artifact excludes",
                "x86 cross-build package command if native source changed",
                "same-version core/profile install transaction",
                "post-sync smoke",
            ],
        },
        "output_mode_change": {
            "status": "needs_host_safety_design",
            "readiness": {
                "http_status_ok": http_status.get("ok") if isinstance(http_status, dict) else None,
                "current_output": output,
            },
            "required_before_apply": [
                "target output allowlist",
                "host recovery path",
                "pre-change and post-change snapshots",
            ],
        },
        "bluetooth_host_management": {
            "status": "needs_destructive_boundary",
            "readiness": {
                "available": bluetooth.get("available"),
                "powered": bluetooth.get("powered"),
                "paired_count": bluetooth.get("paired_count"),
                "connected_count": bluetooth.get("connected_count"),
            },
            "required_before_apply": [
                "single-host target identity",
                "dry-run result",
                "operator confirmation",
                "re-pairing recovery note",
            ],
        },
        "key_or_text_send": {
            "status": "blocked_or_last",
            "readiness": {
                "real_text_send_allowed": text_send.get("real_send_allowed"),
                "blocking_reasons": text_send.get("blocking_reasons", []),
            },
            "required_before_apply": [
                "explicit host profile",
                "active output keyboard confirmation",
                "cancel path",
                "zero-report release path",
                "bounded test payload",
            ],
        },
    }

    recommendations = [
        "keep update-capable tools outside the read-only keyboard MCP server",
        "implement plan/dry-run tools before any apply tool",
        "require explicit confirmation and rollback notes for apply tools",
    ]
    if runtime_attention_count or untracked_count:
        recommendations.append("review dirty/untracked checkout state before designing sync apply tools")
    if arch_warning_count:
        recommendations.append("native artifact architecture warnings must stay blocked from broad sync")

    return {
        "ok": True,
        "mode": "read_only",
        "repo_root": str(repo_root),
        "surfaces": surfaces,
        "summary": {
            "surface_count": len(surfaces),
            "apply_tools_recommended_now": False,
            "read_only_coverage_gap": "update preconditions are now summarized; apply behavior remains intentionally out of scope",
        },
        "source_summaries": {
            "runtime_access": {
                "runtime_keymap_readable": runtime_access.get("runtime_keymap_readable"),
                "user": identity.get("user") or runtime_access.get("user"),
                "group": identity.get("group") or runtime_access.get("group"),
            },
            "repo": {
                "dirty_count": repo.get("dirty_count"),
                "runtime_attention_count": runtime_attention_count,
                "untracked_count": untracked_count,
            },
            "sync_safety": {
                "architecture_warning_count": arch_warning_count,
                "rsync_excludes": sync_plan.get("rsync_excludes", []),
            },
            "http_status": {
                "queried": include_http_status,
                "ok": http_status.get("ok") if isinstance(http_status, dict) else None,
                "error": http_status.get("error") if isinstance(http_status, dict) else None,
            },
        },
        "recommendations": recommendations,
        "notes": [
            "This tool does not write keymaps, restart services, run rsync, change output mode, pair/forget Bluetooth hosts, send keys, or run git commands.",
            "It is a readiness map for future plan/dry-run/update API design.",
        ],
    }


def collect_journal_excerpt(service: str, lines: int = 80, *, execute: bool = True) -> dict[str, Any]:
    normalized = str(service or "").strip()
    max_lines = max(1, min(int(lines), 200))
    if normalized not in ALLOWED_SERVICES:
        return {
            "ok": False,
            "mode": "read_only",
            "service": normalized,
            "lines": max_lines,
            "error": f"service must be one of: {', '.join(ALLOWED_SERVICES)}",
        }
    command = ["journalctl", "-u", normalized, "-n", str(max_lines), "--no-pager"]
    if not execute:
        return {"ok": True, "mode": "read_only", "service": normalized, "lines": max_lines, "command": command, "skipped": True}
    try:
        proc = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8, check=False)
    except FileNotFoundError:
        return {
            "ok": False,
            "mode": "read_only",
            "service": normalized,
            "lines": max_lines,
            "command": command,
            "error": "journalctl not found",
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "mode": "read_only",
            "service": normalized,
            "lines": max_lines,
            "command": command,
            "error": "journalctl timed out",
        }
    return {
        "ok": proc.returncode == 0,
        "mode": "read_only",
        "service": normalized,
        "lines": max_lines,
        "command": command,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def check_runtime_access(paths: list[str] | None = None) -> dict[str, Any]:
    selected = paths if paths else list(DEFAULT_RUNTIME_PATHS)
    clean_paths = [str(path).strip() for path in selected if str(path).strip()]
    access = [_runtime_path_access(path) for path in clean_paths]
    keymap = next((item for item in access if item["path"] == "/mnt/p3/keymap.json"), None)
    recommendations: list[dict[str, Any]] = []
    if keymap and keymap.get("exists") and not keymap.get("readable"):
        user = _current_identity().get("user") or "$USER"
        recommendations.append(
            {
                "path": "/mnt/p3/keymap.json",
                "problem": "runtime keymap exists but is not readable by the MCP process user",
                "impact": "get_keymap_summary and inspect_key_position cannot compare the active runtime keymap",
                "preferred_fix": "make the runtime keymap group-readable by a dedicated keyboard diagnostics group",
                "example_commands": [
                    "sudo groupadd --system hidloom-diagnostics || true",
                    f"sudo usermod -aG hidloom-diagnostics {user}",
                    "sudo chgrp hidloom-diagnostics /mnt/p3/keymap.json",
                    "sudo chmod 0640 /mnt/p3/keymap.json",
                ],
                "simple_fix": "sudo chmod 0644 /mnt/p3/keymap.json",
                "requires_relogin": True,
                "executed": False,
            }
        )
    return {
        "ok": True,
        "mode": "read_only",
        "identity": _current_identity(),
        "paths": access,
        "runtime_keymap_readable": bool(keymap and keymap.get("readable")),
        "notes": [
            "This tool uses stat/access checks only; it does not open files for writing.",
            "get_keymap_summary needs /mnt/p3/keymap.json readable when that runtime file exists.",
        ],
        "recommendations": recommendations,
    }


def run_preflight(include_systemctl: bool = True, **paths: Any) -> dict[str, Any]:
    """Collect read-only local diagnostics for a keyboard-side smoke check."""
    state = _load_state(**paths)
    routes = {
        keycode: explain_route_for_keycode(keycode, **paths)["route"]
        for keycode in ("KC_A", "KC_ZKHK", "KC_HENKAN", "KC_KANA", "KC_BTN1", "KC_VOLU")
    }
    hid_devices = [_path_status(path) for path in DEFAULT_HID_DEVICES]
    sockets = [_path_status(path) for path in DEFAULT_SOCKETS]
    service_status = _systemctl_is_active() if include_systemctl else {"available": False, "skipped": True, "services": {}}
    services_ok = True
    if service_status.get("available"):
        services = service_status.get("services", {})
        services_ok = all(status == "active" for status in services.values())

    return {
        "ok": not state["errors"],
        "mode": "read_only",
        "summary": {
            "config_ok": not state["errors"],
            "services_ok": services_ok if service_status.get("available") else None,
            "hid_devices_present": all(item["exists"] for item in hid_devices),
            "sockets_present": all(item["exists"] for item in sockets),
        },
        "service_status": service_status,
        "hid_devices": hid_devices,
        "sockets": sockets,
        "usb_split": get_usb_split_status(**paths),
        "routes": routes,
        "errors": state["errors"],
    }


def _attention_for_action(action: str) -> str | None:
    if action in ATTENTION_ACTIONS:
        return "attention_action"
    if action.startswith("KC_SH") or action.startswith("SCRIPT("):
        return "script_action"
    if action.startswith("U+") or action.startswith("TEXT(") or action.startswith("SEND_STRING("):
        return "text_send_action"
    return None


def _script_keycode_sort_key(keycode: str) -> int:
    suffix = keycode.removeprefix("KC_SH")
    try:
        return int(suffix)
    except ValueError:
        return 9999


def _script_keycodes(keycodes_path: Path = DEFAULT_KEYCODES) -> list[str]:
    keycodes, _error = _read_json(keycodes_path)
    if not isinstance(keycodes, dict):
        return [f"KC_SH{i}" for i in range(11)]
    found = [key for key in keycodes if isinstance(key, str) and key.startswith("KC_SH") and key[5:].isdigit()]
    return sorted(found, key=_script_keycode_sort_key) or [f"KC_SH{i}" for i in range(11)]


def _script_label(content: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# @label "):
            return stripped.removeprefix("# @label ").strip()
    return ""


def _read_text(path: Path) -> tuple[str, str | None]:
    try:
        return path.read_text(encoding="utf-8", errors="replace"), None
    except FileNotFoundError:
        return "", f"missing file: {path}"
    except OSError as exc:
        return "", f"cannot read file: {path}: {exc}"


def _script_entry(keycode: str, *, runtime_dir: Path, fallback_dir: Path) -> dict[str, Any]:
    filename = f"{keycode}.sh"
    runtime_path = runtime_dir / filename
    fallback_path = fallback_dir / filename
    if runtime_path.exists():
        path = runtime_path
        source = "runtime"
    else:
        path = fallback_path
        source = "fallback" if fallback_path.exists() else "missing"
    content, error = _read_text(path)
    safety = analyze_script_safety(content).as_dict()
    status = _runtime_path_access(str(path))
    return {
        "keycode": keycode,
        "filename": filename,
        "source": source,
        "path": str(path),
        "exists": status["exists"],
        "readable": status["readable"],
        "label": _script_label(content),
        "line_count": len(content.splitlines()) if content else 0,
        "safety": safety,
        "error": error,
    }


def get_script_summary(
    *,
    runtime_dir: Path = DEFAULT_RUNTIME_SCRIPT_DIR,
    fallback_dir: Path = DEFAULT_SCRIPT_DIR,
    keycodes_path: Path = DEFAULT_KEYCODES,
) -> dict[str, Any]:
    entries = [_script_entry(keycode, runtime_dir=runtime_dir, fallback_dir=fallback_dir) for keycode in _script_keycodes(keycodes_path)]
    dangerous = [entry for entry in entries if entry.get("safety", {}).get("dangerous")]
    missing = [entry["keycode"] for entry in entries if not entry.get("exists")]
    unreadable = [entry["keycode"] for entry in entries if entry.get("exists") and not entry.get("readable")]
    return {
        "ok": not unreadable,
        "mode": "read_only",
        "runtime_dir": str(runtime_dir),
        "fallback_dir": str(fallback_dir),
        "count": len(entries),
        "dangerous_count": len(dangerous),
        "missing": missing,
        "unreadable": unreadable,
        "entries": entries,
    }


def _keyboard_reports_for_action(action: str, modifiers: list[str] | None = None) -> tuple[bytes, bytes]:
    if action in {"KC_ZKHK", "KC_ZENKAKU_HANKAKU"}:
        mod_state = HidState()
        for modifier in modifiers or []:
            mod_state.press(KEYCODE.get(modifier, 0))
        press = bytes(
            [
                mod_state.mod,
                JIS_ZENKAKU_HANKAKU_INTERNAL_MARKER,
                JIS_ZENKAKU_HANKAKU_HID_USAGE,
                0,
                0,
                0,
                0,
                0,
            ]
        )
        release = bytes([mod_state.mod, 0, 0, 0, 0, 0, 0, 0])
        return press, release
    state = HidState()
    modifier_codes = [KEYCODE.get(modifier, 0) for modifier in (modifiers or [])]
    code = KEYCODE.get(action, 0)
    for modifier_code in modifier_codes:
        state.press(modifier_code)
    state.press(code)
    press = state.build()
    state.release(code)
    for modifier_code in reversed(modifier_codes):
        state.release(modifier_code)
    release = state.build()
    return press, release


def preview_hid_report(keycode: str, modifiers: list[str] | None = None, **paths: Any) -> dict[str, Any]:
    normalized = str(keycode or "").strip().upper()
    clean_modifiers = [str(item or "").strip().upper() for item in (modifiers or []) if str(item or "").strip()]
    route = explain_route_for_keycode(normalized, **paths)
    classification = route["classification"]
    report_kind = classification["route_kind"]

    if report_kind in {"keyboard", "split_keyboard"} and normalized in KEYCODE:
        press, release = _keyboard_reports_for_action(normalized, clean_modifiers)
        report_id = HID_REPORT_ID_KEYBOARD
        return {
            "ok": True,
            "mode": "read_only",
            "keycode": normalized,
            "modifiers": clean_modifiers,
            "route": route["route"],
            "report": {
                "kind": "keyboard",
                "report_id": report_id,
                "canonical_press": press.hex(),
                "canonical_release": release.hex(),
                "with_report_id_press": add_hid_report_id(report_id, press).hex(),
                "with_report_id_release": add_hid_report_id(report_id, release).hex(),
            },
            "errors": route["errors"],
        }

    if report_kind == "consumer" and normalized in CONSUMER_KEYCODE:
        usage = int(CONSUMER_KEYCODE[normalized])
        press = usage.to_bytes(2, "little")
        release = (0).to_bytes(2, "little")
        report_id = HID_REPORT_ID_CONSUMER
        return {
            "ok": True,
            "mode": "read_only",
            "keycode": normalized,
            "modifiers": [],
            "route": route["route"],
            "report": {
                "kind": "consumer",
                "usage": usage,
                "report_id": report_id,
                "canonical_press": press.hex(),
                "canonical_release": release.hex(),
                "with_report_id_press": add_hid_report_id(report_id, press).hex(),
                "with_report_id_release": add_hid_report_id(report_id, release).hex(),
            },
            "errors": route["errors"],
        }

    return {
        "ok": False,
        "mode": "read_only",
        "keycode": normalized,
        "modifiers": clean_modifiers,
        "route": route["route"],
        "report": None,
        "errors": route["errors"] + [f"report preview is not supported for route kind: {report_kind}"],
    }


def get_keymap_summary(
    *,
    current_keymap_path: Path | None = None,
    default_keymap_path: Path = DEFAULT_KEYMAP,
    max_changes: int = 20,
) -> dict[str, Any]:
    current_path = _active_keymap_path(current_keymap_path)
    current_doc, current_error = _load_keymap_doc(current_path)
    default_doc, default_error = _load_keymap_doc(default_keymap_path)
    current_layers = _keymap_layers_from_doc(current_doc)
    default_layers = _keymap_layers_from_doc(default_doc)
    current_names = _keymap_layer_names(current_doc)
    default_names = _keymap_layer_names(default_doc)
    errors = [err for err in (current_error, default_error) if err]
    if errors:
        return {
            "ok": False,
            "mode": "read_only",
            "paths": {"current": str(current_path), "default": str(default_keymap_path)},
            "layer_count": len(current_layers),
            "default_layer_count": len(default_layers),
            "changed_from_default": None,
            "changed_by_layer": [],
            "sample_changes": [],
            "sample_changes_truncated": False,
            "attention_actions": [],
            "attention_actions_truncated": False,
            "errors": errors,
        }

    max_layer_count = max(len(current_layers), len(default_layers))
    changes: list[dict[str, Any]] = []
    changed_by_layer: list[dict[str, Any]] = []
    attention: list[dict[str, Any]] = []

    for layer_index in range(max_layer_count):
        current_layer = current_layers[layer_index] if layer_index < len(current_layers) else {}
        default_layer = default_layers[layer_index] if layer_index < len(default_layers) else {}
        keys = sorted(set(current_layer) | set(default_layer), key=lambda item: tuple(int(part) for part in item.split(",", 1)))
        changed_count = 0
        assigned_count = 0
        transparent_count = 0
        for matrix_key in keys:
            current_action = current_layer.get(matrix_key, "KC_TRNS")
            default_action = default_layer.get(matrix_key, "KC_TRNS")
            if current_action != "KC_TRNS":
                assigned_count += 1
            else:
                transparent_count += 1
            note = _attention_for_action(current_action)
            if note is not None:
                attention.append(
                    {
                        "layer": layer_index,
                        "matrix": matrix_key,
                        "action": current_action,
                        "kind": note,
                    }
                )
            if current_action != default_action:
                changed_count += 1
                if len(changes) < max_changes:
                    changes.append(
                        {
                            "layer": layer_index,
                            "matrix": matrix_key,
                            "current": current_action,
                            "default": default_action,
                        }
                    )
        changed_by_layer.append(
            {
                "layer": layer_index,
                "name": current_names[layer_index] if layer_index < len(current_names) else None,
                "default_name": default_names[layer_index] if layer_index < len(default_names) else None,
                "assigned": assigned_count,
                "transparent": transparent_count,
                "changed_from_default": changed_count,
            }
        )

    total_changes = sum(item["changed_from_default"] for item in changed_by_layer)
    return {
        "ok": not errors,
        "mode": "read_only",
        "paths": {"current": str(current_path), "default": str(default_keymap_path)},
        "layer_count": len(current_layers),
        "default_layer_count": len(default_layers),
        "changed_from_default": total_changes,
        "changed_by_layer": changed_by_layer,
        "sample_changes": changes,
        "sample_changes_truncated": total_changes > len(changes),
        "attention_actions": attention[:max_changes],
        "attention_actions_truncated": len(attention) > max_changes,
        "errors": errors,
    }


def _parse_matrix_position(matrix: str | None = None, row: Any = None, col: Any = None) -> tuple[str | None, str | None]:
    if matrix:
        parts = str(matrix).strip().split(",", 1)
        if len(parts) != 2:
            return None, "matrix must be formatted as 'row,col'"
        try:
            return f"{int(parts[0])},{int(parts[1])}", None
        except ValueError:
            return None, "matrix row and col must be integers"
    try:
        return f"{int(row)},{int(col)}", None
    except (TypeError, ValueError):
        return None, "provide either matrix='row,col' or integer row and col"


def inspect_key_position(
    *,
    matrix: str | None = None,
    row: Any = None,
    col: Any = None,
    include_reports: bool = True,
    current_keymap_path: Path | None = None,
    default_keymap_path: Path = DEFAULT_KEYMAP,
) -> dict[str, Any]:
    matrix_key, matrix_error = _parse_matrix_position(matrix, row, col)
    if matrix_error:
        return {"ok": False, "mode": "read_only", "matrix": matrix, "layers": [], "errors": [matrix_error]}

    current_path = _active_keymap_path(current_keymap_path)
    current_doc, current_error = _load_keymap_doc(current_path)
    default_doc, default_error = _load_keymap_doc(default_keymap_path)
    current_layers = _keymap_layers_from_doc(current_doc)
    default_layers = _keymap_layers_from_doc(default_doc)
    current_names = _keymap_layer_names(current_doc)
    default_names = _keymap_layer_names(default_doc)
    errors = [err for err in (current_error, default_error) if err]
    if errors:
        return {
            "ok": False,
            "mode": "read_only",
            "matrix": matrix_key,
            "paths": {"current": str(current_path), "default": str(default_keymap_path)},
            "layers": [],
            "errors": errors,
        }

    max_layer_count = max(len(current_layers), len(default_layers))
    layers: list[dict[str, Any]] = []
    attention: list[dict[str, Any]] = []
    for layer_index in range(max_layer_count):
        current_layer = current_layers[layer_index] if layer_index < len(current_layers) else {}
        default_layer = default_layers[layer_index] if layer_index < len(default_layers) else {}
        current_action = current_layer.get(matrix_key, "KC_TRNS")
        default_action = default_layer.get(matrix_key, "KC_TRNS")
        note = _attention_for_action(current_action)
        item: dict[str, Any] = {
            "layer": layer_index,
            "name": current_names[layer_index] if layer_index < len(current_names) else None,
            "default_name": default_names[layer_index] if layer_index < len(default_names) else None,
            "current": current_action,
            "default": default_action,
            "changed_from_default": current_action != default_action,
            "attention": note,
        }
        if include_reports and current_action not in {"KC_TRNS", "KC_NONE"}:
            preview = preview_hid_report(current_action)
            item["route"] = preview.get("route")
            item["report"] = preview.get("report")
            item["report_preview_ok"] = bool(preview.get("ok"))
            if not preview.get("ok"):
                item["report_errors"] = preview.get("errors", [])
        if note is not None:
            attention.append({"layer": layer_index, "action": current_action, "kind": note})
        layers.append(item)

    return {
        "ok": True,
        "mode": "read_only",
        "matrix": matrix_key,
        "paths": {"current": str(current_path), "default": str(default_keymap_path)},
        "layer_count": len(current_layers),
        "layers": layers,
        "attention_actions": attention,
        "errors": [],
    }


TOOLS = {
    "get_status": {
        "description": "Summarize read-only keyboard diagnostic inputs.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": lambda args: get_status(),
    },
    "get_usb_split_status": {
        "description": "Explain configured USB keyboard split status.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": lambda args: get_usb_split_status(),
    },
    "explain_route_for_keycode": {
        "description": "Explain the read-only output route for a keycode.",
        "inputSchema": {
            "type": "object",
            "properties": {"keycode": {"type": "string"}},
            "required": ["keycode"],
            "additionalProperties": False,
        },
        "handler": lambda args: explain_route_for_keycode(str(args.get("keycode") or "")),
    },
    "run_preflight": {
        "description": "Run read-only service/path/config/route preflight diagnostics.",
        "inputSchema": {
            "type": "object",
            "properties": {"include_systemctl": {"type": "boolean"}},
            "additionalProperties": False,
        },
        "handler": lambda args: run_preflight(include_systemctl=bool(args.get("include_systemctl", True))),
    },
    "get_keymap_summary": {
        "description": "Summarize current keymap layers, default diffs, and attention actions.",
        "inputSchema": {
            "type": "object",
            "properties": {"max_changes": {"type": "integer", "minimum": 0, "maximum": 200}},
            "additionalProperties": False,
        },
        "handler": lambda args: get_keymap_summary(max_changes=int(args.get("max_changes", 20))),
    },
    "collect_journal_excerpt": {
        "description": "Collect a bounded read-only journal excerpt for an allowed keyboard service.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "lines": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            "required": ["service"],
            "additionalProperties": False,
        },
        "handler": lambda args: collect_journal_excerpt(str(args.get("service") or ""), lines=int(args.get("lines", 80))),
    },
    "check_runtime_access": {
        "description": "Check read-only runtime path permissions for the current MCP process user.",
        "inputSchema": {
            "type": "object",
            "properties": {"paths": {"type": "array", "items": {"type": "string"}}},
            "additionalProperties": False,
        },
        "handler": lambda args: check_runtime_access(paths=args.get("paths") if isinstance(args.get("paths"), list) else None),
    },
    "get_script_summary": {
        "description": "Summarize KC_SH script labels, sources, readability, and safety metadata.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": lambda args: get_script_summary(),
    },
    "preview_hid_report": {
        "description": "Preview keyboard or consumer HID report bytes for a keycode without sending them.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keycode": {"type": "string"},
                "modifiers": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["keycode"],
            "additionalProperties": False,
        },
        "handler": lambda args: preview_hid_report(
            str(args.get("keycode") or ""),
            modifiers=args.get("modifiers") if isinstance(args.get("modifiers"), list) else None,
        ),
    },
    "inspect_key_position": {
        "description": "Inspect current/default actions for one matrix position across layers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "matrix": {"type": "string"},
                "row": {"type": "integer"},
                "col": {"type": "integer"},
                "include_reports": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: inspect_key_position(
            matrix=str(args.get("matrix")) if args.get("matrix") is not None else None,
            row=args.get("row"),
            col=args.get("col"),
            include_reports=bool(args.get("include_reports", True)),
        ),
    },
    "get_repo_state": {
        "description": "Summarize git branch, commit, and dirty files for the checkout.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_root": {"type": "string"},
                "max_files": {"type": "integer", "minimum": 0, "maximum": 200},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: get_repo_state(
            repo_root=Path(str(args.get("repo_root"))) if args.get("repo_root") else DEFAULT_REPO_ROOT,
            max_files=int(args.get("max_files", 40)),
        ),
    },
    "get_repo_dirty_summary": {
        "description": "Classify checkout dirty files by area for safer pull and real-device sync decisions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_root": {"type": "string"},
                "max_files": {"type": "integer", "minimum": 0, "maximum": 300},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: get_repo_dirty_summary(
            repo_root=Path(str(args.get("repo_root"))) if args.get("repo_root") else DEFAULT_REPO_ROOT,
            max_files=int(args.get("max_files", 80)),
        ),
    },
    "get_checkout_hygiene_summary": {
        "description": "Summarize dirty checkout hygiene issues before pull or manual reflection.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_root": {"type": "string"},
                "max_files": {"type": "integer", "minimum": 0, "maximum": 300},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: get_checkout_hygiene_summary(
            repo_root=Path(str(args.get("repo_root"))) if args.get("repo_root") else DEFAULT_REPO_ROOT,
            max_files=int(args.get("max_files", 80)),
        ),
    },
    "get_checkout_drift_summary": {
        "description": "Attribute dirty checkout drift to likely reflection or local-runtime buckets.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_root": {"type": "string"},
                "max_files": {"type": "integer", "minimum": 0, "maximum": 300},
                "reflection_categories": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: get_checkout_drift_summary(
            repo_root=Path(str(args.get("repo_root"))) if args.get("repo_root") else DEFAULT_REPO_ROOT,
            max_files=int(args.get("max_files", 80)),
            reflection_categories=[str(item) for item in args.get("reflection_categories", [])] if isinstance(args.get("reflection_categories"), list) else None,
        ),
    },
    "get_pull_readiness_summary": {
        "description": "Summarize whether a checkout is ready for a manual git pull without running pull or fetch.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_root": {"type": "string"},
                "max_files": {"type": "integer", "minimum": 0, "maximum": 300},
                "reflection_categories": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: get_pull_readiness_summary(
            repo_root=Path(str(args.get("repo_root"))) if args.get("repo_root") else DEFAULT_REPO_ROOT,
            max_files=int(args.get("max_files", 80)),
            reflection_categories=[str(item) for item in args.get("reflection_categories", [])] if isinstance(args.get("reflection_categories"), list) else None,
        ),
    },
    "get_checkout_cleanup_candidates": {
        "description": "Suggest read-only preserve, cleanup-candidate, and review buckets for a dirty checkout.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_root": {"type": "string"},
                "max_files": {"type": "integer", "minimum": 0, "maximum": 300},
                "reflection_categories": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: get_checkout_cleanup_candidates(
            repo_root=Path(str(args.get("repo_root"))) if args.get("repo_root") else DEFAULT_REPO_ROOT,
            max_files=int(args.get("max_files", 80)),
            reflection_categories=[str(item) for item in args.get("reflection_categories", [])] if isinstance(args.get("reflection_categories"), list) else None,
        ),
    },
    "get_checkout_preserve_diff_summary": {
        "description": "Summarize preserve-candidate diffs without returning diff hunks or file bodies.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_root": {"type": "string"},
                "max_files": {"type": "integer", "minimum": 0, "maximum": 300},
                "reflection_categories": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: get_checkout_preserve_diff_summary(
            repo_root=Path(str(args.get("repo_root"))) if args.get("repo_root") else DEFAULT_REPO_ROOT,
            max_files=int(args.get("max_files", 80)),
            reflection_categories=[str(item) for item in args.get("reflection_categories", [])] if isinstance(args.get("reflection_categories"), list) else None,
        ),
    },
    "get_checkout_backup_plan_summary": {
        "description": "Return a read-only backup plan for preserve candidates before checkout cleanup.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_root": {"type": "string"},
                "max_files": {"type": "integer", "minimum": 0, "maximum": 300},
                "reflection_categories": {"type": "array", "items": {"type": "string"}},
                "backup_root": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: get_checkout_backup_plan_summary(
            repo_root=Path(str(args.get("repo_root"))) if args.get("repo_root") else DEFAULT_REPO_ROOT,
            max_files=int(args.get("max_files", 80)),
            reflection_categories=[str(item) for item in args.get("reflection_categories", [])] if isinstance(args.get("reflection_categories"), list) else None,
            backup_root=Path(str(args.get("backup_root"))) if args.get("backup_root") else None,
        ),
    },
    "get_manual_cleanup_verification_plan": {
        "description": "Return a read-only final verification gate before manual checkout cleanup or pull.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_root": {"type": "string"},
                "max_files": {"type": "integer", "minimum": 0, "maximum": 300},
                "reflection_categories": {"type": "array", "items": {"type": "string"}},
                "backup_root": {"type": "string"},
                "backup_confirmed": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: get_manual_cleanup_verification_plan(
            repo_root=Path(str(args.get("repo_root"))) if args.get("repo_root") else DEFAULT_REPO_ROOT,
            max_files=int(args.get("max_files", 80)),
            reflection_categories=[str(item) for item in args.get("reflection_categories", [])] if isinstance(args.get("reflection_categories"), list) else None,
            backup_root=Path(str(args.get("backup_root"))) if args.get("backup_root") else None,
            backup_confirmed=bool(args.get("backup_confirmed", False)),
        ),
    },
    "get_cleanup_review_order_summary": {
        "description": "Return a read-only prioritized review order for manual checkout cleanup decisions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_root": {"type": "string"},
                "max_files": {"type": "integer", "minimum": 0, "maximum": 300},
                "reflection_categories": {"type": "array", "items": {"type": "string"}},
                "backup_root": {"type": "string"},
                "backup_confirmed": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: get_cleanup_review_order_summary(
            repo_root=Path(str(args.get("repo_root"))) if args.get("repo_root") else DEFAULT_REPO_ROOT,
            max_files=int(args.get("max_files", 80)),
            reflection_categories=[str(item) for item in args.get("reflection_categories", [])] if isinstance(args.get("reflection_categories"), list) else None,
            backup_root=Path(str(args.get("backup_root"))) if args.get("backup_root") else None,
            backup_confirmed=bool(args.get("backup_confirmed", False)),
        ),
    },
    "get_reflection_cleanup_alignment_summary": {
        "description": "Return read-only alignment hints for reflection cleanup candidates against a local git ref.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_root": {"type": "string"},
                "max_files": {"type": "integer", "minimum": 0, "maximum": 300},
                "reflection_categories": {"type": "array", "items": {"type": "string"}},
                "reference": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: get_reflection_cleanup_alignment_summary(
            repo_root=Path(str(args.get("repo_root"))) if args.get("repo_root") else DEFAULT_REPO_ROOT,
            max_files=int(args.get("max_files", 80)),
            reflection_categories=[str(item) for item in args.get("reflection_categories", [])] if isinstance(args.get("reflection_categories"), list) else None,
            reference=str(args.get("reference")) if args.get("reference") else None,
        ),
    },
    "get_temporary_change_restore_plan_summary": {
        "description": "Return a read-only plan for inspecting and restoring temporary stashed device changes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_root": {"type": "string"},
                "stash_ref": {"type": "string"},
                "max_stashes": {"type": "integer", "minimum": 0, "maximum": 50},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: get_temporary_change_restore_plan_summary(
            repo_root=Path(str(args.get("repo_root"))) if args.get("repo_root") else DEFAULT_REPO_ROOT,
            stash_ref=str(args.get("stash_ref")) if args.get("stash_ref") else None,
            max_stashes=int(args.get("max_stashes", 8)),
        ),
    },
    "get_real_device_experiment_workflow_summary": {
        "description": "Return a read-only gate for reverting temporary real-device experiments before clean pull.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_root": {"type": "string"},
                "max_files": {"type": "integer", "minimum": 0, "maximum": 300},
                "max_stashes": {"type": "integer", "minimum": 0, "maximum": 50},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: get_real_device_experiment_workflow_summary(
            repo_root=Path(str(args.get("repo_root"))) if args.get("repo_root") else DEFAULT_REPO_ROOT,
            max_files=int(args.get("max_files", 80)),
            max_stashes=int(args.get("max_stashes", 5)),
        ),
    },
    "get_real_device_access_summary": {
        "description": "Summarize candidate real-device SSH access and remote checkout state without writing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "targets": {"type": "array", "items": {"type": "string"}},
                "repo_root": {"type": "string"},
                "probe_ssh": {"type": "boolean"},
                "timeout_sec": {"type": "number"},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: get_real_device_access_summary(
            targets=[str(item) for item in args.get("targets", [])] if isinstance(args.get("targets"), list) else None,
            repo_root=str(args.get("repo_root") or DEFAULT_REAL_DEVICE_REPO_ROOT),
            probe_ssh=bool(args.get("probe_ssh", True)),
            timeout_sec=float(args.get("timeout_sec", 5.0)),
        ),
    },
    "get_development_snapshot": {
        "description": "Return a compact read-only snapshot for starting a development pass.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_systemctl": {"type": "boolean"},
                "include_http_status": {"type": "boolean"},
                "include_real_device_access": {"type": "boolean"},
                "repo_root": {"type": "string"},
                "max_files": {"type": "integer", "minimum": 0, "maximum": 200},
                "max_changes": {"type": "integer", "minimum": 0, "maximum": 200},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: get_development_snapshot(
            include_systemctl=bool(args.get("include_systemctl", True)),
            include_http_status=bool(args.get("include_http_status", True)),
            include_real_device_access=bool(args.get("include_real_device_access", False)),
            repo_root=Path(str(args.get("repo_root"))) if args.get("repo_root") else DEFAULT_REPO_ROOT,
            max_files=int(args.get("max_files", 20)),
            max_changes=int(args.get("max_changes", 10)),
        ),
    },
    "get_real_device_work_start_summary": {
        "description": "Return an ordered read-only start checklist for real-device work.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_root": {"type": "string"},
                "include_http_status": {"type": "boolean"},
                "max_files": {"type": "integer", "minimum": 0, "maximum": 200},
                "max_changes": {"type": "integer", "minimum": 0, "maximum": 200},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: get_real_device_work_start_summary(
            repo_root=Path(str(args.get("repo_root"))) if args.get("repo_root") else DEFAULT_REPO_ROOT,
            include_http_status=bool(args.get("include_http_status", True)),
            max_files=int(args.get("max_files", 20)),
            max_changes=int(args.get("max_changes", 5)),
        ),
    },
    "get_codex_mcp_status": {
        "description": "Summarize local Codex CLI MCP registration without returning secrets.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "config_path": {"type": "string"},
                "repo_root": {"type": "string"},
                "server_name": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: get_codex_mcp_status(
            config_path=Path(str(args.get("config_path"))) if args.get("config_path") else DEFAULT_CODEX_CONFIG,
            repo_root=Path(str(args.get("repo_root"))) if args.get("repo_root") else DEFAULT_REPO_ROOT,
            server_name=str(args.get("server_name") or "keyboard"),
        ),
    },
    "get_sync_safety_plan": {
        "description": "Return package-first update guidance, rsync excludes, and native artifact warnings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "repo_root": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: get_sync_safety_plan(
            target=str(args.get("target") or DEFAULT_REAL_DEVICE_TARGET),
            repo_root=Path(str(args.get("repo_root"))) if args.get("repo_root") else DEFAULT_REPO_ROOT,
        ),
    },
    "get_selective_sync_plan": {
        "description": "Return a read-only targeted rsync plan for selected dirty-file categories.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "repo_root": {"type": "string"},
                "categories": {"type": "array", "items": {"type": "string"}},
                "max_files": {"type": "integer", "minimum": 0, "maximum": 300},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: get_selective_sync_plan(
            target=str(args.get("target") or DEFAULT_REAL_DEVICE_TARGET),
            repo_root=Path(str(args.get("repo_root"))) if args.get("repo_root") else DEFAULT_REPO_ROOT,
            categories=[str(item) for item in args.get("categories", [])] if isinstance(args.get("categories"), list) else None,
            max_files=int(args.get("max_files", 80)),
        ),
    },
    "get_reflection_apply_plan": {
        "description": "Return a read-only operator checklist for reflecting selected changes to a real device.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "repo_root": {"type": "string"},
                "categories": {"type": "array", "items": {"type": "string"}},
                "max_files": {"type": "integer", "minimum": 0, "maximum": 300},
                "include_http_status": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: get_reflection_apply_plan(
            target=str(args.get("target") or DEFAULT_REAL_DEVICE_TARGET),
            repo_root=Path(str(args.get("repo_root"))) if args.get("repo_root") else DEFAULT_REPO_ROOT,
            categories=[str(item) for item in args.get("categories", [])] if isinstance(args.get("categories"), list) else None,
            max_files=int(args.get("max_files", 80)),
            include_http_status=bool(args.get("include_http_status", True)),
        ),
    },
    "get_systemd_unit_summary": {
        "description": "Summarize allowlisted systemd unit state, drop-ins, and safe environment flags.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "repo_root": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: get_systemd_unit_summary(
            service=str(args.get("service") or ""),
            repo_root=Path(str(args.get("repo_root"))) if args.get("repo_root") else DEFAULT_REPO_ROOT,
        ),
    },
    "get_codex_task_mailbox_summary": {
        "description": "Summarize Codex task mailbox counts, latest files, and result pairs without returning bodies.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tasks_dir": {"type": "string"},
                "max_items": {"type": "integer", "minimum": 0, "maximum": 100},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: get_codex_task_mailbox_summary(
            tasks_dir=Path(str(args.get("tasks_dir"))) if args.get("tasks_dir") else DEFAULT_CODEX_TASKS_DIR,
            max_items=int(args.get("max_items", 5)),
        ),
    },
    "get_http_status_summary": {
        "description": "Fetch and summarize the local HTTP /api/status health surface without returning credentials.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "username": {"type": "string"},
                "password": {"type": "string"},
                "timeout_sec": {"type": "number"},
                "verify_tls": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: get_http_status_summary(
            url=str(args.get("url") or DEFAULT_HTTP_STATUS_URL),
            username=str(args.get("username") or "admin"),
            password=str(args.get("password")) if args.get("password") is not None else None,
            timeout_sec=float(args.get("timeout_sec", 5.0)),
            verify_tls=bool(args.get("verify_tls", False)),
        ),
    },
    "get_output_readiness_summary": {
        "description": "Combine preflight and HTTP status into a compact output-route readiness summary.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_systemctl": {"type": "boolean"},
                "include_http_status": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: get_output_readiness_summary(
            include_systemctl=bool(args.get("include_systemctl", True)),
            include_http_status=bool(args.get("include_http_status", True)),
        ),
    },
    "get_interface_snapshot": {
        "description": "Summarize HTTP, Vial, and BLE readiness without pairing, probing Vial commands, or writing settings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_systemctl": {"type": "boolean"},
                "include_http_status": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: get_interface_snapshot(
            include_systemctl=bool(args.get("include_systemctl", True)),
            include_http_status=bool(args.get("include_http_status", True)),
        ),
    },
    "get_update_readiness_summary": {
        "description": "Summarize read-only prerequisites before any future update-capable MCP tools.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_root": {"type": "string"},
                "include_http_status": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: get_update_readiness_summary(
            repo_root=Path(str(args.get("repo_root"))) if args.get("repo_root") else DEFAULT_REPO_ROOT,
            include_http_status=bool(args.get("include_http_status", True)),
        ),
    },
    "get_runtime_issue_summary": {
        "description": "Summarize runtime readiness issues with likely causes and next read-only checks.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_systemctl": {"type": "boolean"},
                "include_http_status": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: get_runtime_issue_summary(
            include_systemctl=bool(args.get("include_systemctl", True)),
            include_http_status=bool(args.get("include_http_status", True)),
        ),
    },
    "get_runtime_state_summary": {
        "description": "Summarize runtime keymap, LED, Bluetooth host, and board-profile JSON without full contents.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_keymap_diff": {"type": "boolean"},
                "max_changes": {"type": "integer", "minimum": 0, "maximum": 200},
            },
            "additionalProperties": False,
        },
        "handler": lambda args: get_runtime_state_summary(
            include_keymap_diff=bool(args.get("include_keymap_diff", True)),
            max_changes=int(args.get("max_changes", 5)),
        ),
    },
}


def _content_result(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            }
        ]
    }


def handle_request(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")

    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": SERVER_INSTRUCTIONS,
            },
        }
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [
                    {
                        "name": name,
                        "description": spec["description"],
                        "inputSchema": spec["inputSchema"],
                    }
                    for name, spec in TOOLS.items()
                ]
            },
        }
    if method == "tools/call":
        params = request.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {})
        if name not in TOOLS:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"unknown tool: {name}"},
            }
        try:
            result = TOOLS[name]["handler"](args if isinstance(args, dict) else {})
        except Exception as exc:  # pragma: no cover - defensive MCP boundary
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32000, "message": str(exc)},
            }
        return {"jsonrpc": "2.0", "id": request_id, "result": _content_result(result)}

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"unsupported method: {method}"},
    }


def _read_framed(stdin: TextIO) -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = stdin.buffer.readline()
        if not line:
            return None
        text = line.decode("ascii", errors="replace").strip()
        if text == "":
            break
        if ":" in text:
            key, value = text.split(":", 1)
            headers[key.lower()] = value.strip()

    length_text = headers.get("content-length")
    if not length_text:
        return None
    body = stdin.buffer.read(int(length_text)).decode("utf-8")
    return json.loads(body)


def _write_framed(stdout: TextIO, response: dict[str, Any]) -> None:
    body = json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    stdout.buffer.write(body)
    stdout.buffer.flush()


def serve_stdio() -> None:
    while True:
        request = _read_framed(sys.stdin)
        if request is None:
            return
        response = handle_request(request)
        if response is not None:
            _write_framed(sys.stdout, response)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdio", action="store_true", help="serve MCP over stdio")
    parser.add_argument("--tool", choices=sorted(TOOLS), help="run one tool and print JSON")
    parser.add_argument("--keycode", help="keycode for explain_route_for_keycode")
    parser.add_argument("--no-systemctl", action="store_true", help="skip systemctl probes for run_preflight")
    parser.add_argument("--include-http-status", action="store_true", help="include HTTP status in get_development_snapshot")
    parser.add_argument("--include-real-device-access", action="store_true", help="include real-device SSH access summary in get_development_snapshot")
    parser.add_argument("--max-changes", type=int, default=20, help="maximum change samples for get_keymap_summary")
    parser.add_argument("--service", help="service for collect_journal_excerpt")
    parser.add_argument("--lines", type=int, default=80, help="line count for collect_journal_excerpt")
    parser.add_argument("--path", action="append", help="path for check_runtime_access; may be repeated")
    parser.add_argument("--modifier", action="append", default=[], help="modifier for preview_hid_report; may be repeated")
    parser.add_argument("--matrix", help="matrix position for inspect_key_position, formatted as row,col")
    parser.add_argument("--row", type=int, help="matrix row for inspect_key_position")
    parser.add_argument("--col", type=int, help="matrix col for inspect_key_position")
    parser.add_argument("--no-reports", action="store_true", help="skip per-action report previews for inspect_key_position")
    parser.add_argument("--max-files", type=int, default=40, help="maximum dirty files for get_repo_state")
    parser.add_argument("--max-items", type=int, default=5, help="maximum mailbox files for get_codex_task_mailbox_summary")
    parser.add_argument("--repo-root", type=Path, help="repository root for get_repo_state")
    parser.add_argument("--backup-root", type=Path, help="backup root for get_checkout_backup_plan_summary")
    parser.add_argument("--backup-confirmed", action="store_true", help="operator assertion for get_manual_cleanup_verification_plan")
    parser.add_argument("--config-path", type=Path, help="Codex config.toml path for get_codex_mcp_status")
    parser.add_argument("--server-name", default="keyboard", help="MCP server name for get_codex_mcp_status")
    parser.add_argument("--reference", help="local git reference for cleanup alignment summaries")
    parser.add_argument("--stash-ref", help="stash reference for temporary change restore plan")
    parser.add_argument("--max-stashes", type=int, default=8, help="maximum stash entries for get_temporary_change_restore_plan_summary")
    parser.add_argument("--target", default=DEFAULT_REAL_DEVICE_TARGET, help="target user@host for get_sync_safety_plan")
    parser.add_argument("--access-target", action="append", default=[], help="target user@host for get_real_device_access_summary; may be repeated")
    parser.add_argument("--no-ssh-probe", action="store_true", help="skip SSH probes for get_real_device_access_summary")
    parser.add_argument("--category", action="append", default=[], help="category for get_selective_sync_plan; may be repeated")
    parser.add_argument("--unit-service", help="service for get_systemd_unit_summary; default is all allowlisted services")
    parser.add_argument("--tasks-dir", type=Path, help="task mailbox directory for get_codex_task_mailbox_summary")
    parser.add_argument("--url", default=DEFAULT_HTTP_STATUS_URL, help="URL for get_http_status_summary")
    parser.add_argument("--username", default="admin", help="HTTP basic auth username for get_http_status_summary")
    parser.add_argument("--password", help="HTTP basic auth password for get_http_status_summary; defaults to hostname")
    parser.add_argument("--timeout-sec", type=float, default=5.0, help="HTTP timeout seconds for get_http_status_summary")
    parser.add_argument("--verify-tls", action="store_true", help="verify TLS for get_http_status_summary")
    parser.add_argument("--include-keymap-diff", action="store_true", help="include keymap diff in get_runtime_state_summary")
    args = parser.parse_args(argv)

    if args.stdio:
        serve_stdio()
        return 0
    if args.tool:
        tool_args = {"keycode": args.keycode} if args.keycode else {}
        if args.tool == "run_preflight" and args.no_systemctl:
            tool_args["include_systemctl"] = False
        if args.tool == "get_keymap_summary":
            tool_args["max_changes"] = args.max_changes
        if args.tool == "collect_journal_excerpt":
            tool_args["service"] = args.service or ""
            tool_args["lines"] = args.lines
        if args.tool == "check_runtime_access":
            tool_args["paths"] = args.path or []
        if args.tool == "preview_hid_report":
            tool_args["keycode"] = args.keycode or ""
            tool_args["modifiers"] = args.modifier or []
        if args.tool == "inspect_key_position":
            tool_args["matrix"] = args.matrix
            tool_args["row"] = args.row
            tool_args["col"] = args.col
            tool_args["include_reports"] = not args.no_reports
        if args.tool == "get_repo_state":
            tool_args["max_files"] = args.max_files
            if args.repo_root is not None:
                tool_args["repo_root"] = str(args.repo_root)
        if args.tool == "get_repo_dirty_summary":
            tool_args["max_files"] = args.max_files
            if args.repo_root is not None:
                tool_args["repo_root"] = str(args.repo_root)
        if args.tool == "get_checkout_hygiene_summary":
            tool_args["max_files"] = args.max_files
            if args.repo_root is not None:
                tool_args["repo_root"] = str(args.repo_root)
        if args.tool == "get_checkout_drift_summary":
            tool_args["max_files"] = args.max_files
            if args.category:
                tool_args["reflection_categories"] = args.category
            if args.repo_root is not None:
                tool_args["repo_root"] = str(args.repo_root)
        if args.tool == "get_pull_readiness_summary":
            tool_args["max_files"] = args.max_files
            if args.category:
                tool_args["reflection_categories"] = args.category
            if args.repo_root is not None:
                tool_args["repo_root"] = str(args.repo_root)
        if args.tool == "get_checkout_cleanup_candidates":
            tool_args["max_files"] = args.max_files
            if args.category:
                tool_args["reflection_categories"] = args.category
            if args.repo_root is not None:
                tool_args["repo_root"] = str(args.repo_root)
        if args.tool == "get_checkout_preserve_diff_summary":
            tool_args["max_files"] = args.max_files
            if args.category:
                tool_args["reflection_categories"] = args.category
            if args.repo_root is not None:
                tool_args["repo_root"] = str(args.repo_root)
        if args.tool == "get_checkout_backup_plan_summary":
            tool_args["max_files"] = args.max_files
            if args.category:
                tool_args["reflection_categories"] = args.category
            if args.repo_root is not None:
                tool_args["repo_root"] = str(args.repo_root)
            if args.backup_root is not None:
                tool_args["backup_root"] = str(args.backup_root)
        if args.tool == "get_manual_cleanup_verification_plan":
            tool_args["max_files"] = args.max_files
            tool_args["backup_confirmed"] = args.backup_confirmed
            if args.category:
                tool_args["reflection_categories"] = args.category
            if args.repo_root is not None:
                tool_args["repo_root"] = str(args.repo_root)
            if args.backup_root is not None:
                tool_args["backup_root"] = str(args.backup_root)
        if args.tool == "get_cleanup_review_order_summary":
            tool_args["max_files"] = args.max_files
            tool_args["backup_confirmed"] = args.backup_confirmed
            if args.category:
                tool_args["reflection_categories"] = args.category
            if args.repo_root is not None:
                tool_args["repo_root"] = str(args.repo_root)
            if args.backup_root is not None:
                tool_args["backup_root"] = str(args.backup_root)
        if args.tool == "get_reflection_cleanup_alignment_summary":
            tool_args["max_files"] = args.max_files
            if args.category:
                tool_args["reflection_categories"] = args.category
            if args.repo_root is not None:
                tool_args["repo_root"] = str(args.repo_root)
            if args.reference:
                tool_args["reference"] = args.reference
        if args.tool == "get_temporary_change_restore_plan_summary":
            tool_args["max_stashes"] = args.max_stashes
            if args.repo_root is not None:
                tool_args["repo_root"] = str(args.repo_root)
            if args.stash_ref:
                tool_args["stash_ref"] = args.stash_ref
        if args.tool == "get_real_device_experiment_workflow_summary":
            tool_args["max_files"] = args.max_files
            tool_args["max_stashes"] = args.max_stashes
            if args.repo_root is not None:
                tool_args["repo_root"] = str(args.repo_root)
        if args.tool == "get_real_device_access_summary":
            if args.access_target:
                tool_args["targets"] = args.access_target
            if args.repo_root is not None:
                tool_args["repo_root"] = str(args.repo_root)
            tool_args["probe_ssh"] = not args.no_ssh_probe
            tool_args["timeout_sec"] = args.timeout_sec
        if args.tool == "get_development_snapshot":
            tool_args["include_systemctl"] = not args.no_systemctl
            tool_args["include_http_status"] = args.include_http_status
            tool_args["include_real_device_access"] = args.include_real_device_access
            tool_args["max_files"] = args.max_files
            tool_args["max_changes"] = args.max_changes
            if args.repo_root is not None:
                tool_args["repo_root"] = str(args.repo_root)
        if args.tool == "get_real_device_work_start_summary":
            tool_args["include_http_status"] = args.include_http_status
            tool_args["max_files"] = args.max_files
            tool_args["max_changes"] = args.max_changes
            if args.repo_root is not None:
                tool_args["repo_root"] = str(args.repo_root)
        if args.tool == "get_codex_mcp_status":
            tool_args["server_name"] = args.server_name
            if args.config_path is not None:
                tool_args["config_path"] = str(args.config_path)
            if args.repo_root is not None:
                tool_args["repo_root"] = str(args.repo_root)
        if args.tool == "get_sync_safety_plan":
            tool_args["target"] = args.target
            if args.repo_root is not None:
                tool_args["repo_root"] = str(args.repo_root)
        if args.tool == "get_selective_sync_plan":
            tool_args["target"] = args.target
            tool_args["max_files"] = args.max_files
            if args.category:
                tool_args["categories"] = args.category
            if args.repo_root is not None:
                tool_args["repo_root"] = str(args.repo_root)
        if args.tool == "get_reflection_apply_plan":
            tool_args["target"] = args.target
            tool_args["max_files"] = args.max_files
            tool_args["include_http_status"] = args.include_http_status
            if args.category:
                tool_args["categories"] = args.category
            if args.repo_root is not None:
                tool_args["repo_root"] = str(args.repo_root)
        if args.tool == "get_systemd_unit_summary":
            tool_args["service"] = args.unit_service or ""
            if args.repo_root is not None:
                tool_args["repo_root"] = str(args.repo_root)
        if args.tool == "get_codex_task_mailbox_summary":
            tool_args["max_items"] = args.max_items
            if args.tasks_dir is not None:
                tool_args["tasks_dir"] = str(args.tasks_dir)
        if args.tool == "get_http_status_summary":
            tool_args["url"] = args.url
            tool_args["username"] = args.username
            if args.password is not None:
                tool_args["password"] = args.password
            tool_args["timeout_sec"] = args.timeout_sec
            tool_args["verify_tls"] = args.verify_tls
        if args.tool == "get_output_readiness_summary":
            tool_args["include_systemctl"] = not args.no_systemctl
            tool_args["include_http_status"] = args.include_http_status
        if args.tool == "get_interface_snapshot":
            tool_args["include_systemctl"] = not args.no_systemctl
            tool_args["include_http_status"] = args.include_http_status
        if args.tool == "get_update_readiness_summary":
            tool_args["include_http_status"] = args.include_http_status
            if args.repo_root:
                tool_args["repo_root"] = str(args.repo_root)
        if args.tool == "get_runtime_issue_summary":
            tool_args["include_systemctl"] = not args.no_systemctl
            tool_args["include_http_status"] = args.include_http_status
        if args.tool == "get_runtime_state_summary":
            tool_args["include_keymap_diff"] = args.include_keymap_diff
            tool_args["max_changes"] = args.max_changes
        print(json.dumps(TOOLS[args.tool]["handler"](tool_args), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
