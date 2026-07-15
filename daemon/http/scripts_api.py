"""HTTP script editor API route handlers."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict

from aiohttp import web

from script_runner import run_script_content, run_script_path, script_check_env, trim_script_output
import script_store
from script_store import default_script_content

AuditLog = Callable[..., None]


def sync_script_store_config(config_json: Path, default_script_dir: Path, fallback_script_dir: Path) -> None:
    script_store.configure_paths(config_json, default_script_dir, fallback_script_dir)


async def scripts_list_response(iter_script_entries: Callable[[], list[Dict[str, Any]]]) -> web.Response:
    return web.json_response({"result": "ok", "scripts": iter_script_entries()})


async def script_get_response(
    request: web.Request,
    *,
    valid_script_keycode: Callable[[str], bool],
    script_entry: Callable[[str], Dict[str, Any]],
) -> web.Response:
    keycode = request.match_info.get("keycode", "")
    if not valid_script_keycode(keycode):
        return web.json_response({"result": "error", "msg": "invalid keycode"}, status=400)
    entry = script_entry(keycode)
    if not entry.get("exists"):
        return web.json_response({"result": "ok", **entry, "content": default_script_content(keycode)})
    script_path = Path(str(entry["path"]))
    try:
        content = script_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = script_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return web.json_response({"result": "error", "msg": str(exc)}, status=500)
    return web.json_response({"result": "ok", **entry, "content": content})


async def script_put_response(
    request: web.Request,
    *,
    valid_script_keycode: Callable[[str], bool],
    write_runtime_script: Callable[[str, str], Path],
    audit_log: AuditLog,
) -> web.Response:
    keycode = request.match_info.get("keycode", "")
    if not valid_script_keycode(keycode):
        return web.json_response({"result": "error", "msg": "invalid keycode"}, status=400)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"result": "error", "msg": "Invalid JSON"}, status=400)
    content = body.get("content")
    if not isinstance(content, str):
        return web.json_response({"result": "error", "msg": "Missing content"}, status=400)
    try:
        path = write_runtime_script(keycode, content)
    except OSError as exc:
        audit_log(request, "script_save", keycode=keycode, result="error")
        return web.json_response({"result": "error", "msg": str(exc)}, status=500)
    audit_log(request, "script_save", keycode=keycode, result="ok")
    return web.json_response({"result": "ok", "keycode": keycode, "path": str(path), "source": "runtime"})


async def script_reset_response(
    request: web.Request,
    *,
    valid_script_keycode: Callable[[str], bool],
    fallback_script_path: Callable[[str], Path],
    delete_runtime_script: Callable[[str], bool],
    script_entry: Callable[[str], Dict[str, Any]],
    audit_log: AuditLog,
) -> web.Response:
    keycode = request.match_info.get("keycode", "")
    if not valid_script_keycode(keycode):
        return web.json_response({"result": "error", "msg": "invalid keycode"}, status=400)
    fallback = fallback_script_path(keycode)
    try:
        deleted = delete_runtime_script(keycode)
        entry = script_entry(keycode)
        content = ""
        if fallback.exists():
            content = fallback.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        audit_log(request, "script_reset", keycode=keycode, result="error")
        return web.json_response({"result": "error", "msg": str(exc)}, status=500)
    audit_log(request, "script_reset", keycode=keycode, result="ok", runtime_deleted=deleted)
    return web.json_response({"result": "ok", **entry, "runtime_deleted": deleted, "content": content})


async def script_result_response(
    request: web.Request,
    keycode: str,
    result: dict[str, object],
    *,
    audit_action: str,
    audit_log: AuditLog,
) -> web.Response:
    exit_code = int(result["exit_code"])
    timed_out = bool(result["timed_out"])
    if timed_out:
        audit_log(request, audit_action, keycode=keycode, result="timeout", exit_code=exit_code)
        return web.json_response({
            "result": "error",
            "keycode": keycode,
            "exit_code": exit_code,
            "timed_out": True,
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "msg": "timeout after 20s",
        }, status=408)

    audit_log(
        request,
        audit_action,
        keycode=keycode,
        result="ok" if exit_code == 0 else "error",
        exit_code=exit_code,
    )
    return web.json_response({
        "result": "ok" if exit_code == 0 else "error",
        "keycode": keycode,
        "exit_code": exit_code,
        "timed_out": False,
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "msg": f"exit {exit_code}",
    }, status=200 if exit_code == 0 else 422)


async def run_script_path_response(
    request: web.Request,
    keycode: str,
    script_path: Path,
    *,
    audit_action: str,
    repo_root: Path,
    audit_log: AuditLog,
) -> web.Response:
    try:
        result = await run_script_path(script_path, repo_root=repo_root)
    except OSError as exc:
        audit_log(request, audit_action, keycode=keycode, result="error")
        return web.json_response({"result": "error", "msg": str(exc)}, status=500)
    return await script_result_response(request, keycode, result, audit_action=audit_action, audit_log=audit_log)


async def script_check_run_response(
    request: web.Request,
    *,
    valid_script_keycode: Callable[[str], bool],
    repo_root: Path,
    audit_log: AuditLog,
) -> web.Response:
    keycode = request.match_info.get("keycode", "")
    if not valid_script_keycode(keycode):
        return web.json_response({"result": "error", "msg": "invalid keycode"}, status=400)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"result": "error", "msg": "Invalid JSON"}, status=400)
    content = body.get("content")
    if not isinstance(content, str):
        return web.json_response({"result": "error", "msg": "Missing content"}, status=400)

    try:
        result = await run_script_content(keycode, content, repo_root=repo_root)
    except OSError as exc:
        audit_log(request, "script_check_run", keycode=keycode, result="error")
        return web.json_response({"result": "error", "msg": str(exc)}, status=500)
    return await script_result_response(request, keycode, result, audit_action="script_check_run", audit_log=audit_log)


async def script_run_response(
    request: web.Request,
    *,
    valid_script_keycode: Callable[[str], bool],
    script_entry: Callable[[str], Dict[str, Any]],
    repo_root: Path,
    audit_log: AuditLog,
) -> web.Response:
    keycode = request.match_info.get("keycode", "")
    if not valid_script_keycode(keycode):
        return web.json_response({"result": "error", "msg": "invalid keycode"}, status=400)
    entry = script_entry(keycode)
    if not entry.get("exists"):
        audit_log(request, "script_run", keycode=keycode, result="error")
        return web.json_response({"result": "error", "msg": "script not found"}, status=404)
    script_path = Path(str(entry["path"]))
    return await run_script_path_response(
        request,
        keycode,
        script_path,
        audit_action="script_run",
        repo_root=repo_root,
        audit_log=audit_log,
    )
