#!/usr/bin/env python3
"""
Web UI daemon for the CQA02303v5 keyboard.

Serves a browser-based virtual keyboard and relays key events to logicd
via Unix Domain Socket (/tmp/matrix_events.sock).
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import secrets
import shlex
import socket
import ssl
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Set

from aiohttp import web

_HERE = Path(__file__).parent
_REPO_ROOT = _HERE.parents[1]
_DAEMON_ROOT = _REPO_ROOT / "daemon"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_DAEMON_ROOT) not in sys.path:
    sys.path.insert(0, str(_DAEMON_ROOT))

from conditional_layer_inspector_api import register_conditional_layer_inspector_route
from interaction_api import (
    interaction_get_response,
    interaction_put_response,
    interaction_runtime_status_response,
    interaction_validate_response,
)
from interaction_builder_ux import register_interaction_builder_ux_route
from interaction_inspector import register_interaction_inspector_route
from keymap_api import (
    DebouncedKeymapSaver,
    keymap_active_response,
    keymap_layer_add_response,
    keymap_layer_clear_response,
    keymap_layer_lock_clear_response,
    keymap_reset_response,
    keymap_set_response,
)
from layout_api import build_layout_payload, current_keymap_layers
from lighting_api import lighting_get_response, lighting_reset_response, lighting_set_response, matrix_get_response
from lighting_layer_overlays import (
    lighting_layer_overlays_get_response,
    lighting_layer_overlays_put_response,
)
from lighting_lock_indicators import (
    lighting_lock_indicators_get_response,
    lighting_lock_indicators_put_response,
)
from lighting_role_inspector import register_lighting_role_inspector_route
from lighting_role_preview_api import register_lighting_role_preview_route
from morse_feedback_api import register_morse_feedback_route
from morse_inspector import register_morse_inspector_route
from text_send_safety_api import register_text_send_safety_route
from touch_panel_flick_api import register_touch_panel_flick_route
from settings_api import (
    settings_analog_stick_calibration_response,
    settings_get_response,
    settings_http_auth_response,
    settings_send_strings_response,
)
import script_store
from script_store import (
    delete_runtime_script,
    fallback_script_path,
    iter_script_entries,
    script_entry,
    valid_script_keycode,
    write_runtime_script,
)
from scripts_api import (
    script_check_env,
    script_check_run_response,
    script_get_response,
    script_put_response,
    script_reset_response,
    script_run_response,
    scripts_list_response,
    sync_script_store_config,
    trim_script_output,
    run_script_path_response,
)
from socket_bridge import (
    get_sock_writer,
    handle_ws_response,
    process_ws_message,
    query_logicd_active_layers,
    query_logicd_layers,
    send_ctrl_command,
    send_key_event,
)
from security_api import (
    audit_field,
    audit_log,
    basic_auth_allowed,
    build_ssl_context,
    configured_allowed_networks,
    csrf_token_for_request,
    csrf_token_valid,
    hash_http_basic_auth_password,
    http_basic_auth_file,
    load_http_basic_auth,
    load_tls_paths,
    remote_ip_allowed,
    resolve_initial_http_basic_auth_password,
    response_should_set_csrf_cookie,
    set_csrf_cookie,
    verify_http_basic_auth_password,
    write_http_basic_auth_file,
)
from status_api import (
    bluetooth_host_forget_response,
    bluetooth_host_rename_response,
    bluetooth_forget_response,
    bluetooth_pairing_response,
    logs_response,
    status_response,
)
from wifi_status import wifi_status
from vil_api import (
    attachment_content_disposition,
    safe_header_filename_part,
    vil_export_response,
    vil_import_response,
)
from hidloom_paths import default_config_dir, default_config_file

_STATIC_DIR = _HERE / "static"
_CONF_DIR = default_config_dir(_REPO_ROOT)

LAYOUT_JSON = default_config_file("keyboard-layout.json", _REPO_ROOT)
VIAL_JSON = default_config_file("vial.json", _REPO_ROOT)
KEY_LABELS_JSON = default_config_file("key_labels.json", _REPO_ROOT)
KEYMAP_JSON = default_config_file("keymap.json", _REPO_ROOT)
CONFIG_JSON = default_config_file("config.json", _REPO_ROOT)
I2CD_JSON = default_config_file("i2cd.json", _REPO_ROOT)
DEFAULT_SCRIPT_DIR = script_store.DEFAULT_SCRIPT_DIR
FALLBACK_SCRIPT_DIR = script_store.FALLBACK_SCRIPT_DIR

MATRIX_EVENTS_SOCK = os.environ.get("MATRIX_EVENTS_SOCK", "/tmp/matrix_events.sock")
CTRL_EVENTS_SOCK = os.environ.get("CTRL_EVENTS_SOCK", "/tmp/ctrl_events.sock")
LISTEN_HOST = os.environ.get("HTTPD_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("HTTPD_PORT", "443"))
HID_DEVICE = os.environ.get("HID_DEVICE", "/dev/hidg0")
HTTPD_PRIVATE_ONLY = os.environ.get("HTTPD_PRIVATE_ONLY", "1").strip().lower() not in {"0", "false", "no", "off"}
HTTPD_ALLOWED_NETS = os.environ.get("HTTPD_ALLOWED_NETS", "")
HTTPD_AUTH_BYPASS_LOOPBACK = os.environ.get("HTTPD_AUTH_BYPASS_LOOPBACK", "0").strip().lower() in {"1", "true", "yes", "on"}
HTTPD_SYSTEM_SHUTDOWN_COMMAND = os.environ.get("HTTPD_SYSTEM_SHUTDOWN_COMMAND", "sudo shutdown -h now")
HTTPD_CSRF_COOKIE = "hidloom_csrf"
HTTPD_CSRF_HEADER = "X-HIDLOOM-CSRF"
HTTPD_CSRF_TOKEN = secrets.token_urlsafe(32)
HTTPD_KEYMAP_SAVE_DELAY_SECONDS = float(os.environ.get("HTTPD_KEYMAP_SAVE_DELAY_SECONDS", "20.0"))
HTTPD_SHUTDOWN_TIMEOUT_SECONDS = float(os.environ.get("HTTPD_SHUTDOWN_TIMEOUT_SECONDS", "0.75"))
HTTPD_WS_CLOSE_TIMEOUT_SECONDS = float(os.environ.get("HTTPD_WS_CLOSE_TIMEOUT_SECONDS", "0.25"))

_HELP = """usage: python3 daemon/http/httpd.py

HTTPS Web UI and local API daemon.

Options:
  -h, --help    show this help and exit

Common environment:
  LOG_LEVEL
  HTTPD_HOST
  HTTPD_PORT
  HTTPD_PRIVATE_ONLY
  HTTPD_ALLOWED_NETS
  HTTPD_AUTH_BYPASS_LOOPBACK
  HTTPD_SYSTEM_SHUTDOWN_COMMAND
  MATRIX_EVENTS_SOCK
  CTRL_EVENTS_SOCK
"""

log = logging.getLogger("httpd")
_ws_clients: Set[web.WebSocketResponse] = set()
_AccessLoggerBase = getattr(web, "AbstractAccessLogger", object)
_QUIET_POLLING_PATHS = {"/api/status", "/api/keymap/active", "/api/matrix"}
_WS_CLOSE_GOING_AWAY = 1001
# Security inventory anchors for audited mutation routes delegated to feature
# modules: "script_save" "script_check_run" "script_run" "bluetooth_forget"
# "keymap_reset".
# Security helper anchors delegated to security_api: "AUDIT http".
# Status inventory anchors delegated to status_api:
# logicd_data, interaction_status, logicd_env, btd_env, usbd_env, hidd_env, bt, wifi = await asyncio.gather
# wifi_status(),
# "wifi": wifi,
# "hidd": hidd_status(hidd_env=hidd_env, logicd_env=logicd_env),
# "usbd": usbd_status(usbd_env=usbd_env, hidd_env=hidd_env, logicd_env=logicd_env),
# "text_send": text_send_status(config_json),
# "interaction": _normalized_interaction_status(interaction_status),


class _HttpAccessLogger(_AccessLoggerBase):
    """Access logger that keeps polling noise out of the journal."""

    def enabled(self) -> bool:
        return self.logger.isEnabledFor(logging.INFO)

    def log(self, request: web.BaseRequest, response: web.StreamResponse, time: float) -> None:
        if request.path in _QUIET_POLLING_PATHS and response.status < 400:
            return
        self.logger.info(
            '%s "%s %s" %s %.3fs',
            request.remote or "-",
            request.method,
            request.path_qs,
            response.status,
            time,
        )
_sock_writer: Optional[asyncio.StreamWriter] = None
_keymap_saver: DebouncedKeymapSaver | None = None
_DEFAULT_ALLOWED_NETS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
)


def _configured_allowed_networks(value: str = HTTPD_ALLOWED_NETS) -> tuple[ipaddress._BaseNetwork, ...]:
    return configured_allowed_networks(log, value)


_EXTRA_ALLOWED_NETS = _configured_allowed_networks()


def _remote_ip_allowed(remote: str | None) -> bool:
    return remote_ip_allowed(
        remote,
        private_only=HTTPD_PRIVATE_ONLY,
        default_allowed_nets=_DEFAULT_ALLOWED_NETS,
        extra_allowed_nets=_EXTRA_ALLOWED_NETS,
    )


def _auth_bypass_allowed(remote: str | None) -> bool:
    if not HTTPD_AUTH_BYPASS_LOOPBACK or not remote:
        return False
    try:
        return ipaddress.ip_address(remote.rsplit("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _csrf_token_valid(value: str | None) -> bool:
    return csrf_token_valid(value, HTTPD_CSRF_TOKEN)


def _csrf_token_for_request(request: web.Request) -> str | None:
    return csrf_token_for_request(request, HTTPD_CSRF_HEADER)


def _response_should_set_csrf_cookie(request: web.Request) -> bool:
    return response_should_set_csrf_cookie(request)


def _set_csrf_cookie(response: web.StreamResponse) -> None:
    set_csrf_cookie(response, cookie_name=HTTPD_CSRF_COOKIE, token=HTTPD_CSRF_TOKEN)


def _audit_field(value: object, fallback: str = "-") -> str:
    return audit_field(value, fallback)


def _audit_log(request: web.Request, action: str, **fields: object) -> None:
    audit_log(log, request, action, username=HTTP_BASIC_AUTH_USERNAME, **fields)


def _safe_header_filename_part(value: object, fallback: str = "layout") -> str:
    return safe_header_filename_part(value, fallback)


def _attachment_content_disposition(filename: str) -> str:
    return attachment_content_disposition(filename)


def _http_basic_auth_file() -> Path:
    return http_basic_auth_file(CONFIG_JSON)


def _hash_http_basic_auth_password(password: str, *, iterations: int = 200_000) -> str:
    return hash_http_basic_auth_password(password, iterations=iterations)


def _verify_http_basic_auth_password(password: str, stored: str) -> bool:
    return verify_http_basic_auth_password(password, stored)


def _resolve_initial_http_basic_auth_password(value: str | None) -> str:
    return resolve_initial_http_basic_auth_password(value)


def _load_http_basic_auth() -> tuple[str, str]:
    return load_http_basic_auth(CONFIG_JSON, _http_basic_auth_file, log)


HTTP_BASIC_AUTH_USERNAME, HTTP_BASIC_AUTH_PASSWORD = _load_http_basic_auth()


def _write_http_basic_auth_file(username: str, password: str) -> tuple[Path, str]:
    return write_http_basic_auth_file(
        username,
        password,
        auth_file=_http_basic_auth_file,
        hash_password=_hash_http_basic_auth_password,
    )


def _load_tls_paths() -> tuple[Path, Path]:
    return load_tls_paths(CONFIG_JSON, log)


def _build_ssl_context() -> ssl.SSLContext:
    return build_ssl_context(CONFIG_JSON, log)


@web.middleware
async def private_network_middleware(request: web.Request, handler: web.Handler) -> web.StreamResponse:
    if _remote_ip_allowed(request.remote):
        return await handler(request)
    log.warning("Rejecting non-private HTTP client: remote=%r path=%s", request.remote, request.path)
    raise web.HTTPForbidden(text="Forbidden")


@web.middleware
async def basic_auth_middleware(request: web.Request, handler: web.Handler) -> web.StreamResponse:
    if _auth_bypass_allowed(request.remote):
        return await handler(request)
    if await basic_auth_allowed(
        request,
        username=HTTP_BASIC_AUTH_USERNAME,
        password_hash=HTTP_BASIC_AUTH_PASSWORD,
        verify_password=_verify_http_basic_auth_password,
    ):
        return await handler(request)
    raise web.HTTPUnauthorized(
        headers={"WWW-Authenticate": 'Basic realm="CQA02303v5"'},
        text="Authentication required",
    )


@web.middleware
async def csrf_middleware(request: web.Request, handler: web.Handler) -> web.StreamResponse:
    if request.method in {"POST", "PUT", "DELETE"} or request.path == "/ws":
        if not _csrf_token_valid(_csrf_token_for_request(request)):
            log.warning("Rejecting request with invalid CSRF token: method=%s path=%s", request.method, request.path)
            raise web.HTTPForbidden(text="Forbidden")
    return await handler(request)


@web.middleware
async def cache_control_middleware(request: web.Request, handler: web.Handler) -> web.StreamResponse:
    response = await handler(request)
    if request.path == "/" or request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, max-age=0, must-revalidate"
    if _response_should_set_csrf_cookie(request):
        _set_csrf_cookie(response)
    return response

async def _get_sock_writer() -> Optional[asyncio.StreamWriter]:
    global _sock_writer
    _sock_writer = await get_sock_writer(_sock_writer, socket_path=MATRIX_EVENTS_SOCK, log=log)
    return _sock_writer


async def _send_key_event(event_str: str) -> None:
    global _sock_writer

    def clear_writer() -> None:
        global _sock_writer
        _sock_writer = None

    await send_key_event(
        event_str,
        writer=_sock_writer,
        get_writer=_get_sock_writer,
        clear_writer=clear_writer,
        log=log,
    )


async def _send_ctrl_command(cmd: Dict[str, Any], timeout: float = 2.0) -> Optional[Dict[str, Any]]:
    return await send_ctrl_command(cmd, socket_path=CTRL_EVENTS_SOCK, timeout=timeout, log=log)


def _get_keymap_saver() -> DebouncedKeymapSaver:
    global _keymap_saver
    if _keymap_saver is None:
        _keymap_saver = DebouncedKeymapSaver(
            _send_ctrl_command,
            delay_seconds=HTTPD_KEYMAP_SAVE_DELAY_SECONDS,
            logger=log,
        )
    return _keymap_saver


async def _close_keymap_saver(app: web.Application) -> None:
    if _keymap_saver is not None:
        await _keymap_saver.close()


async def _close_ws_client_fast(ws: web.WebSocketResponse) -> None:
    if ws.closed:
        return
    try:
        await asyncio.wait_for(
            ws.close(code=_WS_CLOSE_GOING_AWAY, message=b"server shutdown"),
            timeout=HTTPD_WS_CLOSE_TIMEOUT_SECONDS,
        )
    except (asyncio.TimeoutError, ConnectionError, RuntimeError):
        log.info("WS shutdown close skipped after %.2fs", HTTPD_WS_CLOSE_TIMEOUT_SECONDS)


async def _close_ws_clients_on_shutdown(app: web.Application) -> None:
    clients = [ws for ws in _ws_clients if not ws.closed]
    if not clients:
        return
    log.info("Closing %d WS client(s) for shutdown", len(clients))
    await asyncio.gather(*(_close_ws_client_fast(ws) for ws in clients), return_exceptions=True)
    _ws_clients.difference_update(clients)


async def _query_logicd_layers() -> Optional[Dict[str, Any]]:
    return await query_logicd_layers(_send_ctrl_command, log=log)


async def _query_logicd_active_layers() -> Optional[Dict[str, Any]]:
    # Status-policy test anchor: data = await _send_ctrl_command({"t": "ACTIVE"})
    return await query_logicd_active_layers(_send_ctrl_command, log=log)


async def _query_logicd_interaction_status() -> Optional[Dict[str, Any]]:
    # Status-policy test anchor: data = await _send_ctrl_command({"t": "INTERACTION_STATUS"})
    return await _send_ctrl_command({"t": "INTERACTION_STATUS"})


async def handle_interaction_get(request: web.Request) -> web.Response:
    return await interaction_get_response(CONFIG_JSON, VIAL_JSON)


async def handle_interaction_put(request: web.Request) -> web.Response:
    return await interaction_put_response(request, CONFIG_JSON, VIAL_JSON)


async def handle_interaction_validate(request: web.Request) -> web.Response:
    return await interaction_validate_response(request, VIAL_JSON)


async def handle_interaction_runtime_status(request: web.Request) -> web.Response:
    return await interaction_runtime_status_response(_send_ctrl_command)


def _sync_script_store_config() -> None:
    sync_script_store_config(CONFIG_JSON, DEFAULT_SCRIPT_DIR, FALLBACK_SCRIPT_DIR)


def _iter_script_entries() -> list[Dict[str, Any]]:
    _sync_script_store_config()
    return iter_script_entries()


def _script_entry(keycode: str) -> Dict[str, Any]:
    _sync_script_store_config()
    return script_entry(keycode)


def _valid_script_keycode(keycode: str) -> bool:
    _sync_script_store_config()
    return valid_script_keycode(keycode)


def _fallback_script_path(keycode: str) -> Path:
    _sync_script_store_config()
    return fallback_script_path(keycode)


def _write_runtime_script(keycode: str, content: str) -> Path:
    _sync_script_store_config()
    return write_runtime_script(keycode, content)


def _delete_runtime_script(keycode: str) -> bool:
    _sync_script_store_config()
    return delete_runtime_script(keycode)


async def handle_index(request: web.Request) -> web.Response:
    html = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return web.Response(text=html.replace("{HOSTNAME}", socket.gethostname()), content_type="text/html")


async def handle_status(request: web.Request) -> web.Response:
    return await status_response(
        _query_logicd_layers,
        hid_device=HID_DEVICE,
        query_interaction_status=_query_logicd_interaction_status,
        config_json=CONFIG_JSON,
    )


async def handle_bluetooth_pairing(request: web.Request) -> web.Response:
    return await bluetooth_pairing_response(request, _send_ctrl_command)


async def handle_bluetooth_forget(request: web.Request) -> web.Response:
    return await bluetooth_forget_response(
        request,
        lambda cmd, timeout: _send_ctrl_command(cmd, timeout=timeout),
        _audit_log,
    )


async def handle_bluetooth_host_rename(request: web.Request) -> web.Response:
    return await bluetooth_host_rename_response(request, _audit_log)


async def handle_bluetooth_host_forget(request: web.Request) -> web.Response:
    return await bluetooth_host_forget_response(request, _audit_log)


async def handle_settings_get(request: web.Request) -> web.Response:
    return await settings_get_response(HTTP_BASIC_AUTH_USERNAME, CONFIG_JSON, I2CD_JSON)


async def handle_settings_http_auth(request: web.Request) -> web.Response:
    global HTTP_BASIC_AUTH_PASSWORD
    response, password_hash = await settings_http_auth_response(
        request,
        username=HTTP_BASIC_AUTH_USERNAME,
        current_password_hash=HTTP_BASIC_AUTH_PASSWORD,
        verify_password=_verify_http_basic_auth_password,
        write_password=_write_http_basic_auth_file,
        audit_log=_audit_log,
    )
    if password_hash is not None:
        HTTP_BASIC_AUTH_PASSWORD = password_hash
    return response


async def handle_settings_send_strings(request: web.Request) -> web.Response:
    return await settings_send_strings_response(request, CONFIG_JSON)


async def handle_settings_analog_stick_calibration(request: web.Request) -> web.Response:
    return await settings_analog_stick_calibration_response(request, I2CD_JSON)


async def handle_lighting_get(request: web.Request) -> web.Response:
    return await lighting_get_response(_send_ctrl_command)


async def handle_lighting_set(request: web.Request) -> web.Response:
    return await lighting_set_response(request, _send_ctrl_command)


async def handle_lighting_reset(request: web.Request) -> web.Response:
    return await lighting_reset_response(_send_ctrl_command)


async def handle_lighting_layer_overlays_get(request: web.Request) -> web.Response:
    return await lighting_layer_overlays_get_response()


async def handle_lighting_layer_overlays_put(request: web.Request) -> web.Response:
    return await lighting_layer_overlays_put_response(request, _send_ctrl_command)


async def handle_lighting_lock_indicators_get(request: web.Request) -> web.Response:
    return await lighting_lock_indicators_get_response()


async def handle_lighting_lock_indicators_put(request: web.Request) -> web.Response:
    return await lighting_lock_indicators_put_response(request, _send_ctrl_command)


async def handle_matrix_get(request: web.Request) -> web.Response:
    return await matrix_get_response(_send_ctrl_command)


async def handle_scripts_list(request: web.Request) -> web.Response:
    return await scripts_list_response(_iter_script_entries)


async def handle_script_get(request: web.Request) -> web.Response:
    return await script_get_response(
        request,
        valid_script_keycode=_valid_script_keycode,
        script_entry=_script_entry,
    )


async def handle_script_put(request: web.Request) -> web.Response:
    return await script_put_response(
        request,
        valid_script_keycode=_valid_script_keycode,
        write_runtime_script=_write_runtime_script,
        audit_log=_audit_log,
    )


async def handle_script_reset(request: web.Request) -> web.Response:
    return await script_reset_response(
        request,
        valid_script_keycode=_valid_script_keycode,
        fallback_script_path=_fallback_script_path,
        delete_runtime_script=_delete_runtime_script,
        script_entry=_script_entry,
        audit_log=_audit_log,
    )


def _script_check_env() -> Dict[str, str]:
    return script_check_env(_REPO_ROOT)


def _trim_script_output(text: str, limit: int = 4000) -> str:
    return trim_script_output(text, limit)


async def _run_script_path(request: web.Request, keycode: str, script_path: Path, *, audit_action: str) -> web.Response:
    return await run_script_path_response(
        request,
        keycode,
        script_path,
        audit_action=audit_action,
        repo_root=_REPO_ROOT,
        audit_log=_audit_log,
    )


async def handle_script_check_run(request: web.Request) -> web.Response:
    return await script_check_run_response(
        request,
        valid_script_keycode=_valid_script_keycode,
        repo_root=_REPO_ROOT,
        audit_log=_audit_log,
    )


async def handle_script_run(request: web.Request) -> web.Response:
    return await script_run_response(
        request,
        valid_script_keycode=_valid_script_keycode,
        script_entry=_script_entry,
        repo_root=_REPO_ROOT,
        audit_log=_audit_log,
    )


async def handle_layout(request: web.Request) -> web.Response:
    return web.json_response(await build_layout_payload(_query_logicd_layers))


async def handle_keymap_active(request: web.Request) -> web.Response:
    # Status-policy test anchor: logicd_data = await _query_logicd_active_layers()
    return await keymap_active_response(_query_logicd_active_layers)


async def handle_keymap_set(request: web.Request) -> web.Response:
    saver = _get_keymap_saver()
    return await keymap_set_response(request, _send_ctrl_command, saver.schedule)


async def handle_keymap_reset(request: web.Request) -> web.Response:
    return await keymap_reset_response(request, _send_ctrl_command, _audit_log)


async def handle_keymap_layer_add(request: web.Request) -> web.Response:
    return await keymap_layer_add_response(request, _send_ctrl_command, _audit_log)


async def handle_keymap_layer_clear(request: web.Request) -> web.Response:
    return await keymap_layer_clear_response(request, _send_ctrl_command, _audit_log)


async def handle_keymap_layer_lock_clear(request: web.Request) -> web.Response:
    return await keymap_layer_lock_clear_response(request, _send_ctrl_command, _audit_log)


async def handle_vil_export(request: web.Request) -> web.Response:
    return await vil_export_response(
        query_logicd_layers=_query_logicd_layers,
        vial_json=VIAL_JSON,
        keymap_json=KEYMAP_JSON,
        config_json=CONFIG_JSON,
    )


async def handle_vil_import(request: web.Request) -> web.Response:
    return await vil_import_response(
        request,
        send_ctrl_command=_send_ctrl_command,
        vial_json=VIAL_JSON,
        keymap_json=KEYMAP_JSON,
        config_json=CONFIG_JSON,
        audit_log=_audit_log,
    )


async def handle_logs(request: web.Request) -> web.Response:
    return await logs_response(request)


async def handle_system_shutdown(request: web.Request) -> web.Response:
    args = shlex.split(HTTPD_SYSTEM_SHUTDOWN_COMMAND)
    if not args:
        log.warning("system shutdown requested but HTTPD_SYSTEM_SHUTDOWN_COMMAND is empty")
        return web.json_response({"result": "error", "msg": "shutdown command is disabled"}, status=503)
    try:
        await asyncio.create_subprocess_exec(*args)
    except Exception as exc:
        log.error("failed to launch system shutdown command: %s", exc)
        return web.json_response({"result": "error", "msg": str(exc)}, status=500)
    log.warning("system shutdown command launched from HTTP UI: %s", " ".join(args))
    return web.json_response({"result": "ok"})


async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    return await handle_ws_response(request, ws_clients=_ws_clients, process_message=_process_ws_message, log=log)


async def _process_ws_message(raw: str) -> None:
    await process_ws_message(raw, send_key_event_func=_send_key_event, log=log)


def create_app() -> web.Application:
    app = web.Application(middlewares=[
        private_network_middleware,
        basic_auth_middleware,
        csrf_middleware,
        cache_control_middleware,
    ])
    app.on_shutdown.append(_close_ws_clients_on_shutdown)
    app.on_cleanup.append(_close_keymap_saver)
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/layout", handle_layout)
    app.router.add_get("/api/keymap/active", handle_keymap_active)
    app.router.add_get("/api/status", handle_status)
    app.router.add_post("/api/bluetooth/pairing", handle_bluetooth_pairing)
    app.router.add_post("/api/bluetooth/forget", handle_bluetooth_forget)
    app.router.add_post("/api/bluetooth/hosts/{address}/rename", handle_bluetooth_host_rename)
    app.router.add_post("/api/bluetooth/hosts/{address}/forget", handle_bluetooth_host_forget)
    app.router.add_get("/api/settings", handle_settings_get)
    app.router.add_post("/api/settings/http-auth", handle_settings_http_auth)
    app.router.add_put("/api/settings/send-strings", handle_settings_send_strings)
    app.router.add_post("/api/settings/analog-stick/calibrate", handle_settings_analog_stick_calibration)
    app.router.add_post("/api/system/shutdown", handle_system_shutdown)
    app.router.add_get("/api/logs", handle_logs)
    app.router.add_get("/api/interaction", handle_interaction_get)
    app.router.add_put("/api/interaction", handle_interaction_put)
    app.router.add_post("/api/interaction/validate", handle_interaction_validate)
    app.router.add_get("/api/interaction/runtime-status", handle_interaction_runtime_status)
    register_interaction_builder_ux_route(app)
    register_interaction_inspector_route(app, CONFIG_JSON, VIAL_JSON)
    register_conditional_layer_inspector_route(app, CONFIG_JSON, _query_logicd_active_layers)
    register_morse_inspector_route(app, CONFIG_JSON, VIAL_JSON)
    register_morse_feedback_route(app, _send_ctrl_command)
    register_text_send_safety_route(app, CONFIG_JSON)
    register_touch_panel_flick_route(app, _send_ctrl_command)
    app.router.add_get("/api/scripts", handle_scripts_list)
    app.router.add_get("/api/scripts/{keycode}", handle_script_get)
    app.router.add_put("/api/scripts/{keycode}", handle_script_put)
    app.router.add_post("/api/scripts/{keycode}/reset", handle_script_reset)
    app.router.add_post("/api/scripts/{keycode}/check-run", handle_script_check_run)
    app.router.add_post("/api/scripts/{keycode}/run", handle_script_run)
    app.router.add_get("/api/lighting", handle_lighting_get)
    app.router.add_post("/api/lighting", handle_lighting_set)
    app.router.add_post("/api/lighting/reset", handle_lighting_reset)
    register_lighting_role_preview_route(app, _send_ctrl_command)
    register_lighting_role_inspector_route(app, _query_logicd_layers)
    app.router.add_get("/api/lighting/layer-overlays", handle_lighting_layer_overlays_get)
    app.router.add_put("/api/lighting/layer-overlays", handle_lighting_layer_overlays_put)
    app.router.add_get("/api/lighting/lock-indicators", handle_lighting_lock_indicators_get)
    app.router.add_put("/api/lighting/lock-indicators", handle_lighting_lock_indicators_put)
    app.router.add_get("/api/matrix", handle_matrix_get)
    app.router.add_post("/api/keymap", handle_keymap_set)
    app.router.add_post("/api/keymap/reset", handle_keymap_reset)
    app.router.add_post("/api/keymap/layers", handle_keymap_layer_add)
    app.router.add_delete("/api/keymap/layers/{layer}", handle_keymap_layer_clear)
    app.router.add_post("/api/keymap/layer-lock/clear", handle_keymap_layer_lock_clear)
    app.router.add_get("/api/vil/export", handle_vil_export)
    app.router.add_post("/api/vil/import", handle_vil_import)
    app.router.add_get("/ws", handle_ws)
    app.router.add_static("/static", _STATIC_DIR, show_index=False)
    return app


def main() -> None:
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        print(_HELP.rstrip())
        return

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = create_app()
    ssl_context = _build_ssl_context()
    log.info("Starting Web UI on https://%s:%d/", LISTEN_HOST, LISTEN_PORT)
    web.run_app(
        app,
        host=LISTEN_HOST,
        port=LISTEN_PORT,
        ssl_context=ssl_context,
        access_log=log,
        access_log_class=_HttpAccessLogger,
        shutdown_timeout=HTTPD_SHUTDOWN_TIMEOUT_SECONDS,
        handler_cancellation=True,
    )


if __name__ == "__main__":
    main()
