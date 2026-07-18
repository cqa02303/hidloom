from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from aiohttp import web

from bluetooth_api import (
    build_bluetooth_host_forget_guard,
    rename_bluetooth_host_metadata,
    run_forget_action,
    run_pairing_action,
)
from system_api import (
    DEFAULT_BLUETOOTH_HOSTS_FILE,
    board_profile_status,
    bluetooth_status,
    btd_status,
    hidd_status,
    hid_gadget_status,
    journal_lines,
    ledd_direct_frame_status,
    logicd_runtime_environment,
    output_status,
    outputd_status,
    process_statuses,
    query_btd_runtime_status,
    resolve_output_state,
    service_environment,
    spid_status,
    usbd_status,
)
from text_send_safety_api import text_send_safety_payload
from wifi_status import wifi_status


SendCtrl = Callable[[Dict[str, Any]], Awaitable[Optional[Dict[str, Any]]]]
QueryLayers = Callable[[], Awaitable[Optional[Dict[str, Any]]]]
QueryInteractionStatus = Callable[[], Awaitable[Optional[Dict[str, Any]]]]
AuditLog = Callable[[web.Request, str], None]


def _normalized_interaction_status(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not data or data.get("result") != "ok":
        return {
            "available": False,
            "schema": "interaction.runtime_status.v1",
            "caps_word": {"enabled": None, "active": None},
            "repeat_key": {
                "enabled": None,
                "history_available": None,
                "alternate_available": None,
                "alternate_pair_count": None,
            },
            "key_lock": {"active_count": 0},
            "one_shot_layer": {"active_count": 0},
        }
    caps_word = data.get("caps_word") if isinstance(data.get("caps_word"), dict) else {}
    repeat_key = data.get("repeat_key") if isinstance(data.get("repeat_key"), dict) else {}
    key_lock = data.get("key_lock") if isinstance(data.get("key_lock"), dict) else {}
    key_lock_keys = key_lock.get("keys") if isinstance(key_lock.get("keys"), list) else []
    one_shot_layer = data.get("one_shot_layer") if isinstance(data.get("one_shot_layer"), dict) else {}
    return {
        "available": True,
        "schema": data.get("schema", "interaction.runtime_status.v1"),
        "source": data.get("source", "logicd.interactions"),
        "save_payload_includes_runtime_state": bool(data.get("save_payload_includes_runtime_state", False)),
        "caps_word": {
            "enabled": bool(caps_word.get("enabled", False)),
            "active": bool(caps_word.get("active", False)),
        },
        "repeat_key": {
            "enabled": bool(repeat_key.get("enabled", False)),
            "history_available": bool(repeat_key.get("history_available", False)),
            "alternate_available": bool(repeat_key.get("alternate_available", False)),
            "alternate_pair_count": int(repeat_key.get("alternate_pair_count") or 0),
        },
        "key_lock": {
            "active_count": len(key_lock_keys),
        },
        "one_shot_layer": {
            "active_count": int(one_shot_layer.get("active_count") or 0),
        },
    }


def text_send_status(config_json: Path | str | None) -> Dict[str, Any]:
    if config_json is None:
        return {
            "available": False,
            "schema": "text_send.status.v1",
            "reason": "config_json_not_available",
        }
    payload = text_send_safety_payload(Path(config_json))
    unicode_settings = payload.get("unicode") if isinstance(payload.get("unicode"), dict) else {}
    host_profile = payload.get("host_profile") if isinstance(payload.get("host_profile"), dict) else {}
    runner = payload.get("runner_connection") if isinstance(payload.get("runner_connection"), dict) else {}
    gate = payload.get("execution_gate") if isinstance(payload.get("execution_gate"), dict) else {}
    validation = payload.get("send_string_validation") if isinstance(payload.get("send_string_validation"), dict) else {}
    return {
        "available": True,
        "schema": "text_send.status.v1",
        "safety_schema": payload.get("schema"),
        "safety_route": payload.get("route"),
        "plan_route": payload.get("plan_route"),
        "unicode_mode": unicode_settings.get("mode"),
        "host_profile_explicit": bool(host_profile.get("explicit", False)),
        "host_profile": host_profile.get("profile"),
        "runner_connected": bool(runner.get("connected", False)),
        "runner_ready": bool(runner.get("ready", False)),
        "runner_method": runner.get("method"),
        "runner_timeout_sec": runner.get("timeout_sec"),
        "real_send_allowed": bool(gate.get("real_send_allowed", False)),
        "send_string_actions_executable": bool(gate.get("send_string_actions_executable", False)),
        "blocking_reasons": list(gate.get("blocking_reasons") or []),
        "send_string_entry_count": int(validation.get("entry_count") or 0),
        "send_string_error_count": int(validation.get("error_count") or 0),
        "send_string_warning_count": int(validation.get("warning_count") or 0),
    }


async def status_response(
    query_logicd_layers: QueryLayers,
    *,
    hid_device: str,
    query_interaction_status: QueryInteractionStatus | None = None,
    config_json: Path | str | None = None,
) -> web.Response:
    interaction_status_task = query_interaction_status() if query_interaction_status else asyncio.sleep(0, result=None)
    logicd_data, interaction_status, logicd_env, btd_env, usbd_env, hidd_env, bt, wifi = await asyncio.gather(
        query_logicd_layers(),
        interaction_status_task,
        logicd_runtime_environment(),
        service_environment("btd"),
        service_environment("usbd"),
        service_environment("hidloom-hidd"),
        bluetooth_status(),
        wifi_status(),
    )
    btd_socket = btd_env.get("BTD_EVENTS_SOCK", "")
    btd_runtime = await query_btd_runtime_status(btd_socket or "/tmp/btd_events.sock")
    mode = str(logicd_data.get("mode", "")) if logicd_data is not None else ""
    output_target = str(logicd_data.get("output_target", "")) if logicd_data is not None else ""
    native_output = outputd_status()
    mode, output_target = resolve_output_state(mode, output_target, native_output)
    return web.json_response({
        "hid": hid_gadget_status(hid_device),
        "mode": mode,
        "output_target": output_target,
        "processes": process_statuses(),
        "bluetooth": bt,
        "wifi": wifi,
        "board_profile": board_profile_status(),
        "interaction": _normalized_interaction_status(interaction_status),
        "text_send": text_send_status(config_json),
        "btd": btd_status(service_env=btd_env, runtime_status=btd_runtime),
        "hidd": hidd_status(hidd_env=hidd_env, logicd_env=logicd_env),
        "hid_broker": hidd_status(hidd_env=hidd_env, logicd_env=logicd_env),
        "usbd": usbd_status(usbd_env=usbd_env, hidd_env=hidd_env, logicd_env=logicd_env),
        "output": output_status(logicd_env, runtime_mode=mode, output_target=output_target),
        "outputd": native_output,
        "spid": spid_status(),
        "ledd_direct_frame": ledd_direct_frame_status(),
    })


async def bluetooth_pairing_response(request: web.Request, send_ctrl_command: SendCtrl) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"result": "error", "msg": "Invalid JSON"}, status=400)
    try:
        result = await run_pairing_action(send_ctrl_command, body.get("mode", body.get("enabled", "toggle")))
    except ValueError as exc:
        return web.json_response({"result": "error", "msg": str(exc)}, status=400)
    status_code = 200 if result.get("result") == "ok" else 503
    if result.get("result") == "ok":
        result["bluetooth"] = await bluetooth_status(max_age_sec=0)
    return web.json_response(result, status=status_code)


async def bluetooth_forget_response(
    request: web.Request,
    send_ctrl_command: Callable[[Dict[str, Any], float], Awaitable[Optional[Dict[str, Any]]]],
    audit_log: Callable[..., None],
) -> web.Response:
    async def send_forget_command(cmd: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return await send_ctrl_command(cmd, 12.0)

    result = await run_forget_action(send_forget_command)
    status_code = 200 if result.get("result") == "ok" else 503
    audit_log(request, "bluetooth_forget", result=result.get("result", "unknown"), status=status_code)
    if result.get("result") == "ok":
        result["bluetooth"] = await bluetooth_status(max_age_sec=0)
    return web.json_response(result, status=status_code)


async def bluetooth_host_rename_response(
    request: web.Request,
    audit_log: Callable[..., None],
    *,
    metadata_path: str = DEFAULT_BLUETOOTH_HOSTS_FILE,
) -> web.Response:
    address = request.match_info.get("address", "")
    try:
        body = await request.json()
    except Exception:
        audit_log(request, "bluetooth_host_rename", address=address, result="error", status=400)
        return web.json_response({"result": "error", "msg": "Invalid JSON"}, status=400)
    try:
        result = rename_bluetooth_host_metadata(
            metadata_path,
            address,
            body.get("display_name", ""),
            clear=bool(body.get("clear", False)),
        )
    except ValueError as exc:
        audit_log(request, "bluetooth_host_rename", address=address, result="error", status=400)
        return web.json_response({"result": "error", "msg": str(exc)}, status=400)
    audit_log(request, "bluetooth_host_rename", address=result["address"], result="ok", status=200)
    result["bluetooth"] = await bluetooth_status(max_age_sec=0)
    return web.json_response(result)


async def bluetooth_host_forget_response(
    request: web.Request,
    audit_log: Callable[..., None],
) -> web.Response:
    address = request.match_info.get("address", "")
    try:
        body = await request.json()
    except Exception:
        audit_log(request, "bluetooth_host_forget", address=address, result="error", status=400)
        return web.json_response({"result": "error", "msg": "Invalid JSON"}, status=400)
    bt = await bluetooth_status(max_age_sec=0)
    devices = bt.get("devices") if isinstance(bt.get("devices"), list) else []
    normalized_address = str(address or "").strip().upper()
    device = next(
        (
            item
            for item in devices
            if isinstance(item, dict) and str(item.get("mac", "")).upper() == normalized_address
        ),
        None,
    )
    try:
        result = build_bluetooth_host_forget_guard(address, body, device=device)
    except ValueError as exc:
        audit_log(request, "bluetooth_host_forget", address=address, result="error", status=400)
        return web.json_response({"result": "error", "msg": str(exc)}, status=400)
    audit_log(
        request,
        "bluetooth_host_forget",
        address=result["address"],
        result=result["result"],
        status=200,
        dry_run=True,
        connected=result.get("connected"),
        paired=result.get("paired"),
    )
    result["bluetooth"] = bt
    return web.json_response(result)


async def logs_response(request: web.Request) -> web.Response:
    service = request.rel_url.query.get("service", "")
    try:
        lines_int = int(request.rel_url.query.get("lines", "100"))
    except ValueError:
        lines_int = 100
    return await journal_lines(service, lines_int)
