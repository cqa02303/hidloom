"""HTTP settings API handlers."""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any, Callable
from pathlib import Path

from aiohttp import web

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "daemon"))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from interaction_api import _atomic_write_json, _load_config, reload_logicd_service
from logicd.text_send_safety import validate_send_string_settings
from tools.calibrate_ads1115_stick import run_phase_calibration, validate_saved_calibration

log = logging.getLogger(__name__)
_analog_stick_calibration_lock = asyncio.Lock()


def _analog_stick_min_range_volts(raw: dict[str, Any] | None, *, default: float = 0.1) -> float:
    if not isinstance(raw, dict) or "min_range_volts" not in raw:
        return default
    try:
        value = float(raw["min_range_volts"])
    except (TypeError, ValueError):
        return default
    if value < 0 or value > 2:
        return default
    return value


def _analog_stick_calibration_snapshot(i2cd_json: Path | None) -> dict[str, Any] | None:
    if i2cd_json is None:
        return None
    try:
        cfg = _load_config(i2cd_json)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    raw = cfg.get("analog_stick")
    if not isinstance(raw, dict):
        return None

    def numeric(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    min_range_volts = _analog_stick_min_range_volts(raw)
    errors: list[str] = []

    def axis_snapshot(name: str) -> dict[str, Any] | None:
        axis = raw.get(name)
        if not isinstance(axis, dict):
            errors.append(f"{name}.config must be an object")
            return None
        result: dict[str, Any] = {}
        for key in ("channel", "center", "low", "high", "invert"):
            if key in axis:
                result[key] = axis[key]
        center = numeric(axis.get("center"))
        low = numeric(axis.get("low"))
        high = numeric(axis.get("high"))
        if low is not None and high is not None:
            span = high - low
            result["span"] = span
            result["span_valid"] = span >= min_range_volts
            if not result["span_valid"]:
                errors.append(f"{name}.span {span:.4f}V is smaller than {min_range_volts:.4f}V")
        if center is not None and low is not None and high is not None:
            result["center_valid"] = low < center < high
            if not result["center_valid"]:
                errors.append(f"{name}.center must be between low and high")
        if "center_valid" in result and "span_valid" in result:
            result["valid"] = result["center_valid"] is True and result["span_valid"] is True
        return result

    x = axis_snapshot("x")
    y = axis_snapshot("y")
    axes = [axis for axis in (x, y) if axis is not None]
    center_valid = bool(axes) and all(axis.get("center_valid") is True for axis in axes)
    span_valid = bool(axes) and all(axis.get("span_valid") is True for axis in axes)
    return {
        "enabled": bool(raw.get("enabled", False)),
        "stick": raw.get("stick", 0),
        "deadzone": raw.get("deadzone"),
        "auto_center_on_start": bool(raw.get("auto_center_on_start", False)),
        "auto_center_duration": raw.get("auto_center_duration"),
        "min_range_volts": min_range_volts,
        "center_valid": center_valid,
        "span_valid": span_valid,
        "valid": center_valid and span_valid,
        "errors": errors,
        "x": x,
        "y": y,
    }


def _configured_analog_stick_min_range_volts(i2cd_json: Path) -> float:
    try:
        cfg = _load_config(i2cd_json)
    except (OSError, ValueError, json.JSONDecodeError):
        return 0.1
    raw = cfg.get("analog_stick")
    return _analog_stick_min_range_volts(raw if isinstance(raw, dict) else None)


async def settings_get_response(
    username: str,
    config_json: Path | None = None,
    i2cd_json: Path | None = None,
) -> web.Response:
    send_strings = {}
    send_string_validation = validate_send_string_settings({})
    if config_json is not None:
        try:
            cfg = _load_config(config_json)
            settings = cfg.get("settings", {}) if isinstance(cfg.get("settings"), dict) else {}
            send_strings = settings.get("send_strings", {}) if isinstance(settings.get("send_strings"), dict) else {}
            send_string_validation = validate_send_string_settings(settings)
        except ValueError as exc:
            return web.json_response({"result": "error", "msg": str(exc)}, status=500)
    return web.json_response({
        "result": "ok",
        "http_basic_auth": {"username": username},
        "send_strings": send_strings,
        "send_string_validation": send_string_validation,
        "analog_stick_calibration": _analog_stick_calibration_snapshot(i2cd_json),
    })


async def settings_http_auth_response(
    request: web.Request,
    *,
    username: str,
    current_password_hash: str,
    verify_password: Callable[[str, str], bool],
    write_password: Callable[[str, str], tuple[Any, str]],
    audit_log: Callable[..., None],
) -> tuple[web.Response, str | None]:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"result": "error", "msg": "Invalid JSON"}, status=400), None

    current_password = body.get("current_password")
    new_password = body.get("new_password")
    confirm_password = body.get("confirm_password")
    if not all(isinstance(value, str) for value in [current_password, new_password, confirm_password]):
        return web.json_response({"result": "error", "msg": "password fields must be strings"}, status=400), None
    if not verify_password(current_password, current_password_hash):
        return web.json_response({"result": "error", "msg": "current password does not match"}, status=403), None
    if new_password != confirm_password:
        return web.json_response({"result": "error", "msg": "new password confirmation does not match"}, status=400), None
    if not new_password:
        return web.json_response({"result": "error", "msg": "new password must not be empty"}, status=400), None
    if len(new_password) > 256:
        return web.json_response({"result": "error", "msg": "new password is too long"}, status=400), None

    try:
        auth_file, password_hash = write_password(username, new_password)
    except OSError as exc:
        log.warning("HTTP Basic auth password update failed: %s", exc)
        return web.json_response({"result": "error", "msg": str(exc)}, status=500), None

    audit_log(request, "http_auth_password_update", result="ok")
    log.info("HTTP Basic auth password updated for user=%s file=%s", username, auth_file)
    return web.json_response({
        "result": "ok",
        "msg": "password updated",
        "http_basic_auth": {"username": username},
    }), password_hash


async def settings_send_strings_response(request: web.Request, config_json: Path) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"result": "error", "msg": "Invalid JSON"}, status=400)

    if not isinstance(body, dict):
        return web.json_response({"result": "error", "msg": "body must be object"}, status=400)
    entries = body.get("send_strings")
    if entries is None:
        entries = {}
    if not isinstance(entries, dict):
        return web.json_response({"result": "error", "msg": "send_strings must be object"}, status=400)

    validation = validate_send_string_settings({"send_strings": entries})
    if validation["error_count"] > 0:
        return web.json_response({
            "result": "error",
            "msg": "send_strings validation failed",
            "send_strings": entries,
            "send_string_validation": validation,
        }, status=400)

    try:
        cfg = _load_config(config_json)
        settings = cfg.setdefault("settings", {})
        if entries:
            settings["send_strings"] = entries
        else:
            settings.pop("send_strings", None)
        _atomic_write_json(config_json, cfg)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        log.warning("send_strings update failed: %s", exc)
        return web.json_response({"result": "error", "msg": str(exc)}, status=500)

    reload_result = None
    if body.get("reload") is True:
        reload_result = await reload_logicd_service()

    return web.json_response({
        "result": "ok",
        "send_strings": entries,
        "send_string_validation": validation,
        "reload": reload_result,
    })


async def settings_analog_stick_calibration_response(request: web.Request, i2cd_json: Path) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"result": "error", "msg": "Invalid JSON"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"result": "error", "msg": "body must be object"}, status=400)

    phase = body.get("phase")
    if phase not in {"center", "range", "validate"}:
        return web.json_response({"result": "error", "msg": "phase must be center, range, or validate"}, status=400)
    try:
        duration = float(body.get("duration", 2.0 if phase == "center" else 10.0))
        interval = float(body.get("interval", 0.02))
        margin = float(body.get("margin_volts", 0.0))
        min_range_volts = float(body.get("min_range_volts", _configured_analog_stick_min_range_volts(i2cd_json)))
    except (TypeError, ValueError):
        return web.json_response({
            "result": "error",
            "msg": "duration, interval, margin_volts, and min_range_volts must be numbers",
        }, status=400)
    write = body.get("write", True) is not False
    backup = body.get("backup", True) is not False
    if phase == "range" and write and body.get("confirm_range") is not True:
        return web.json_response({
            "result": "error",
            "msg": "range calibration write requires confirm_range=true",
        }, status=400)

    if duration <= 0 or duration > 60:
        return web.json_response({"result": "error", "msg": "duration must be in 0..60 seconds"}, status=400)
    if interval <= 0 or interval > 1:
        return web.json_response({"result": "error", "msg": "interval must be in 0..1 seconds"}, status=400)
    if margin < 0 or margin > 1:
        return web.json_response({"result": "error", "msg": "margin_volts must be in 0..1"}, status=400)
    if min_range_volts < 0 or min_range_volts > 2:
        return web.json_response({"result": "error", "msg": "min_range_volts must be in 0..2"}, status=400)

    if phase == "validate":
        try:
            payload = validate_saved_calibration(_load_config(i2cd_json), min_range_volts=min_range_volts)
        except SystemExit as exc:
            return web.json_response({"result": "error", "msg": str(exc)}, status=400)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return web.json_response({"result": "error", "msg": str(exc)}, status=500)
        return web.json_response(payload, status=200 if payload.get("valid") else 400)

    if _analog_stick_calibration_lock.locked():
        return web.json_response({"result": "error", "msg": "analog stick calibration is already running"}, status=409)

    async with _analog_stick_calibration_lock:
        try:
            payload = await asyncio.to_thread(
                run_phase_calibration,
                config_path=i2cd_json,
                phase=phase,
                duration=duration,
                interval=interval,
                margin=margin,
                write=write,
                backup=backup,
                manage_i2cd_service=True,
                min_range_volts=min_range_volts,
            )
        except SystemExit as exc:
            msg = str(exc)
            status = 503 if msg.startswith("ADS1115 ") else 400
            return web.json_response({"result": "error", "msg": msg}, status=status)
        except Exception as exc:
            log.warning("analog stick calibration failed: %s", exc)
            return web.json_response({"result": "error", "msg": str(exc)}, status=500)

    return web.json_response({"result": "ok", **payload})
