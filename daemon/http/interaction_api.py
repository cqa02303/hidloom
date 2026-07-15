"""HTTP helpers for InteractionEngine settings."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from aiohttp import web

_HERE = Path(__file__).parent
_REPO_ROOT = _HERE.parents[1]

import sys
if str(_REPO_ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "daemon"))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from logicd.action_expansion import canonical_aliases_snapshot, modifier_wrappers_snapshot, shifted_aliases_snapshot
from logicd.interaction_config import validate_interaction_settings


def _matrix_in_range_from_vial(vial_json: Path) -> Callable[[int, int], bool]:
    try:
        vial = json.loads(vial_json.read_text(encoding="utf-8"))
        matrix = vial.get("matrix", {})
        rows = int(matrix.get("rows", 32))
        cols = int(matrix.get("cols", 32))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        rows = 32
        cols = 32

    def _in_range(row: int, col: int) -> bool:
        return 0 <= row < rows and 0 <= col < cols

    return _in_range


def _load_config(config_json: Path) -> dict[str, Any]:
    try:
        data = json.loads(config_json.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"settings": {}}
    if not isinstance(data, dict):
        raise ValueError("config root must be an object")
    data.setdefault("settings", {})
    if not isinstance(data["settings"], dict):
        data["settings"] = {}
    return data


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            fp.write(text)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


async def _run_systemctl(*args: str) -> dict[str, Any]:
    command = ["systemctl", *args]
    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=8.0)
    except FileNotFoundError:
        return {"result": "error", "returncode": None, "msg": "systemctl not available"}
    except asyncio.TimeoutError:
        if proc is not None and proc.returncode is None:
            proc.kill()
            await proc.communicate()
        return {
            "result": "error",
            "returncode": None,
            "msg": f"{' '.join(command)} timeout",
        }
    return {
        "result": "ok" if proc.returncode == 0 else "error",
        "returncode": proc.returncode,
        "stdout": stdout.decode(errors="replace"),
        "stderr": stderr.decode(errors="replace"),
    }


async def reload_logicd_service() -> dict[str, Any]:
    checked_units: list[str] = []
    for unit in ("logicd-companion", "logicd"):
        active = await _run_systemctl("is-active", "--quiet", unit)
        checked_units.append(unit)
        if active.get("returncode") is None:
            return {**active, "operation": "is-active", "unit": unit}
        if active.get("returncode") != 0:
            continue
        result = await _run_systemctl("reload", unit)
        return {**result, "operation": "reload", "unit": unit}
    return {
        "result": "error",
        "returncode": None,
        "msg": "no active logicd runtime service",
        "checked_units": checked_units,
    }


def build_interaction_payload(config_json: Path, vial_json: Path) -> dict[str, Any]:
    cfg = _load_config(config_json)
    raw = cfg.get("settings", {}).get("interaction", {})
    validation = validate_interaction_settings(raw, matrix_in_range=_matrix_in_range_from_vial(vial_json))
    return {
        "result": "ok",
        "settings": validation.settings,
        "raw": raw if isinstance(raw, dict) else {},
        "warnings": validation.warnings,
        "metadata": {
            "modifier_wrappers": modifier_wrappers_snapshot(),
            "shifted_aliases": shifted_aliases_snapshot(),
            "canonical_aliases": canonical_aliases_snapshot(),
            "status_connections": {
                "schema": "interaction.status_connections.v1",
                "storage_owner": "settings.interaction",
                "runtime_snapshot_owner": "/api/keymap/active",
                "summary_owner": "http.static.interaction_panel",
                "save_payload_includes_runtime_state": False,
                "features": {
                    "caps_word": {
                        "summary": "settings_only",
                        "runtime_active": "snapshot_only",
                        "runtime_active_source": "/api/interaction/runtime-status",
                        "oled_feedback": "deferred",
                        "led_feedback": "deferred",
                    },
                    "repeat_key": {
                        "summary": "settings_and_pair_count",
                        "runtime_history": "privacy_safe_helper_only",
                        "runtime_active_source": "/api/interaction/runtime-status",
                        "oled_feedback": "deferred",
                        "led_feedback": "deferred",
                    },
                    "conditional_layers": {
                        "summary": "rules_and_runtime_active",
                        "runtime_active_source": "/api/interaction/conditional-layers/inspector",
                        "editor": "read_only_inspector_first",
                    },
                    "one_shot_layer": {
                        "summary": "active_snapshot_oneshot",
                        "runtime_active_source": "/api/keymap/active",
                    },
                    "layer_lock": {
                        "summary": "active_snapshot_locked",
                        "runtime_active_source": "/api/keymap/active",
                        "unlock_button": "/api/keymap/layer-lock/clear",
                        "unlock_mutates_saved_settings": False,
                        "oled_feedback": "deferred",
                        "led_feedback": "deferred",
                    },
                    "mod_morph": {
                        "summary": "read_only_inspector",
                        "runtime_dispatch": "interaction_engine_after_key_override",
                        "inspector_source": "/api/interaction/inspector",
                        "graphical_editor": "deferred_until_needed",
                    },
                    "key_lock": {
                        "summary": "runtime_status_only",
                        "runtime_active_source": "/api/interaction/runtime-status",
                        "targets": ["modifier", "mouse_button"],
                        "save_payload_includes_runtime_state": False,
                    },
                },
                "next_local_todo": "runtime_feedback_or_real_device_touch_flick",
            },
            "example": {
                "tapping_term": 0.2,
                "hold_on_other_key_press": True,
                "combo_term": 0.05,
                "tap_dance_term": 0.2,
                "combos": [{"keys": [[0, 1], [0, 2]], "action": "KC_ESC"}],
                "tap_dances": {"TD0": {"1": "KC_A", "2": "KC_ESC"}},
                "key_overrides": [{"trigger": "KC_LSFT", "key": "KC_1", "replacement": "KC_ESC"}],
                "mod_morphs": {"grave_escape": {"trigger_mods": ["KC_LSFT", "KC_RSFT"], "default_action": "KC_ESC", "morphed_action": "KC_GRV"}},
            },
        },
    }


def save_interaction_settings(config_json: Path, vial_json: Path, raw: Any) -> dict[str, Any]:
    validation = validate_interaction_settings(raw, matrix_in_range=_matrix_in_range_from_vial(vial_json))
    cfg = _load_config(config_json)
    cfg.setdefault("settings", {})
    cfg["settings"]["interaction"] = validation.settings
    _atomic_write_json(config_json, cfg)
    return {
        "result": "ok",
        "settings": validation.settings,
        "warnings": validation.warnings,
        "path": str(config_json),
    }


def validate_interaction_settings_payload(vial_json: Path, raw: Any) -> dict[str, Any]:
    validation = validate_interaction_settings(raw, matrix_in_range=_matrix_in_range_from_vial(vial_json))
    return {
        "result": "ok",
        "settings": validation.settings,
        "warnings": validation.warnings,
    }


async def interaction_get_response(config_json: Path, vial_json: Path) -> web.Response:
    try:
        return web.json_response(build_interaction_payload(config_json, vial_json))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return web.json_response({"result": "error", "msg": str(exc)}, status=500)


async def interaction_put_response(request: web.Request, config_json: Path, vial_json: Path) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"result": "error", "msg": "Invalid JSON"}, status=400)
    raw = body.get("settings", body)
    try:
        result = save_interaction_settings(config_json, vial_json, raw)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return web.json_response({"result": "error", "msg": str(exc)}, status=500)

    if body.get("reload", True):
        reload_result = await reload_logicd_service()
        result["reload"] = reload_result
        if reload_result.get("result") != "ok":
            return web.json_response(result, status=502)
    return web.json_response(result)


async def interaction_validate_response(request: web.Request, vial_json: Path) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"result": "error", "msg": "Invalid JSON"}, status=400)
    raw = body.get("settings", body)
    try:
        return web.json_response(validate_interaction_settings_payload(vial_json, raw))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return web.json_response({"result": "error", "msg": str(exc)}, status=500)


async def interaction_runtime_status_response(send_ctrl_command: Callable[[dict[str, Any]], Any]) -> web.Response:
    resp = await send_ctrl_command({"t": "INTERACTION_STATUS"})
    if resp is None:
        return web.json_response({"result": "error", "msg": "logicd unavailable"}, status=503)
    status = 200 if resp.get("result") == "ok" else 502
    return web.json_response(resp, status=status)
