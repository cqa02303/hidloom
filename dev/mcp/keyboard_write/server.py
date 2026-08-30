#!/usr/bin/env python3
"""Guarded write-capable MCP companion for one HIDloom keyboard."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import stat
import sys
import time
from pathlib import Path
from typing import Any, Callable, TextIO


ROOT = Path(__file__).resolve().parents[3]
IMPORT_ROOTS = [ROOT]
for raw_path in os.environ.get("PYTHONPATH", "").split(os.pathsep):
    if raw_path:
        import_root = Path(raw_path).resolve()
        if import_root not in IMPORT_ROOTS:
            IMPORT_ROOTS.append(import_root)
for import_root in IMPORT_ROOTS:
    for candidate in (
        import_root,
        import_root / "daemon",
        import_root / "daemon" / "http",
    ):
        if str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))

from dev.mcp.keyboard import server as keyboard_read  # noqa: E402
from keymap_actions import is_valid_keymap_action, normalize_keymap_action  # noqa: E402


SERVER_NAME = "hidloom-keyboard-write"
SERVER_VERSION = "0.1.0"
SERVER_INSTRUCTIONS = (
    "Guarded HIDloom keyboard control companion. All state-changing tools are dry-run unless "
    "their current keymap digest and exact dynamic confirmation phrase are supplied. The companion "
    "does not run shell commands, restart services, overwrite a whole keymap, manage Bluetooth, "
    "or expose credentials. Use the separate hidloom-keyboard server for broad diagnostics."
)

DEFAULT_RUNTIME_KEYMAP = keyboard_read.DEFAULT_RUNTIME_KEYMAP
DEFAULT_CTRL_SOCKET = Path(os.environ.get("HIDLOOM_MCP_CTRL_SOCKET", "/tmp/ctrl_events.sock"))
DEFAULT_MATRIX_SOCKET = Path(os.environ.get("HIDLOOM_MCP_MATRIX_SOCKET", "/tmp/matrix_events.sock"))
MAX_KEYMAP_BYTES = 2 * 1024 * 1024
MAX_CTRL_RESPONSE_BYTES = 512 * 1024
MIN_HOLD_MS = 5
MAX_HOLD_MS = 200
SAFE_TAP_ACTIONS = frozenset(
    {"KC_ESC"}
    | {f"KC_{letter}" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}
    | {f"KC_{digit}" for digit in "0123456789"}
)

CtrlQuery = Callable[[dict[str, Any]], dict[str, Any]]
EventSender = Callable[[str], None]


def _bounded_regular_file_sha256(path: Path) -> str:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ValueError(f"keymap must be a regular non-symlink file: {path}")
    if info.st_size > MAX_KEYMAP_BYTES:
        raise ValueError(f"keymap exceeds {MAX_KEYMAP_BYTES} bytes: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _persisted_layers(path: Path) -> list[dict[str, str]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("keymap document must be an object")
    layers = keyboard_read._keymap_layers_from_doc(raw)
    if not layers:
        raise ValueError("keymap has no usable layers")
    return layers


def _query_ctrl(command: dict[str, Any], socket_path: Path = DEFAULT_CTRL_SOCKET, timeout: float = 2.0) -> dict[str, Any]:
    if not socket_path.exists():
        raise RuntimeError(f"control socket is unavailable: {socket_path}")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(socket_path))
        client.sendall(json.dumps(command, separators=(",", ":")).encode("utf-8") + b"\n")
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = client.recv(min(65536, MAX_CTRL_RESPONSE_BYTES - size + 1))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_CTRL_RESPONSE_BYTES:
                raise RuntimeError("control response exceeded the bounded limit")
            if b"\n" in chunk:
                break
    raw = b"".join(chunks).split(b"\n", 1)[0]
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("control response is not an object")
    return value


def _send_matrix_event(event: str, socket_path: Path = DEFAULT_MATRIX_SOCKET, timeout: float = 2.0) -> None:
    if len(event) != 4 or event[0] not in {"P", "R"} or event[-1] != "\n":
        raise ValueError("matrix event must be one bounded Pxy/Rxy line")
    if not socket_path.exists():
        raise RuntimeError(f"matrix socket is unavailable: {socket_path}")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(socket_path))
        client.sendall(event.encode("ascii"))


def _live_keymap(query_ctrl: CtrlQuery) -> dict[str, Any]:
    value = query_ctrl({"t": "G"})
    if value.get("t") != "keymap" or not isinstance(value.get("layers"), list):
        raise RuntimeError(f"unexpected keymap response: {value.get('t')!r}")
    return value


def _pressed_state(query_ctrl: CtrlQuery) -> dict[str, Any]:
    value = query_ctrl({"t": "K"})
    if value.get("t") != "matrix" or not isinstance(value.get("pressed"), list):
        raise RuntimeError(f"unexpected matrix response: {value.get('t')!r}")
    return value


def _action_at(layers: list[Any], layer: int, row: int, col: int) -> str:
    if not 0 <= layer < len(layers) or not isinstance(layers[layer], dict):
        raise ValueError(f"layer is unavailable: {layer}")
    return str(layers[layer].get(f"{row},{col}", "KC_TRNS"))


def _effective_action(live: dict[str, Any], row: int, col: int) -> tuple[str, list[int]]:
    layers = live.get("layers", [])
    active = live.get("active", {})
    active_all = active.get("all", [0]) if isinstance(active, dict) else [0]
    clean_layers = [int(item) for item in active_all if isinstance(item, int) and 0 <= item < len(layers)]
    if not clean_layers:
        clean_layers = [0]
    for layer in reversed(clean_layers):
        action = _action_at(layers, layer, row, col)
        if action != "KC_TRNS":
            return action, clean_layers
    return "KC_NONE", clean_layers


def _validate_position(row: int, col: int) -> None:
    if not 0 <= row <= 15 or not 0 <= col <= 15:
        raise ValueError("matrix row and col must be in 0..15")


def _keymap_confirmation(layer: int, row: int, col: int, before: str, after: str, digest: str) -> str:
    return f"APPLY_KEYMAP_CHANGE L{layer} R{row} C{col} {before}->{after} SHA256:{digest[:12]}"


def _tap_confirmation(row: int, col: int, action: str, digest: str) -> str:
    return f"SEND_MATRIX_TAP R{row} C{col} {action} SHA256:{digest[:12]}"


def get_control_status(
    *,
    keymap_path: Path = DEFAULT_RUNTIME_KEYMAP,
    query_ctrl: CtrlQuery = _query_ctrl,
) -> dict[str, Any]:
    errors: list[str] = []
    live: dict[str, Any] = {}
    pressed: dict[str, Any] = {}
    digest: str | None = None
    try:
        digest = _bounded_regular_file_sha256(keymap_path)
        _persisted_layers(keymap_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    try:
        live = _live_keymap(query_ctrl)
        pressed = _pressed_state(query_ctrl)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    readiness = keyboard_read.get_output_readiness_summary(include_systemctl=True, include_http_status=False)
    return {
        "ok": not errors and bool(readiness.get("ok")),
        "mode": "guarded_write_companion_status",
        "server": {"name": SERVER_NAME, "version": SERVER_VERSION},
        "keymap": {
            "path": str(keymap_path),
            "sha256": digest,
            "layer_count": len(live.get("layers", [])) if isinstance(live.get("layers"), list) else None,
            "active": live.get("active"),
        },
        "matrix": {"pressed": pressed.get("pressed", [])},
        "output_target": live.get("output_target"),
        "readiness": readiness,
        "write_capabilities": ["bounded_matrix_tap", "single_position_keymap_change"],
        "blocked_capabilities": [
            "arbitrary_shell",
            "whole_keymap_overwrite",
            "service_restart",
            "bluetooth_forget",
            "shutdown_or_reboot",
        ],
        "credentials_returned": False,
        "errors": errors,
    }


def plan_keymap_change(
    layer: int,
    row: int,
    col: int,
    action: str,
    *,
    keymap_path: Path = DEFAULT_RUNTIME_KEYMAP,
    query_ctrl: CtrlQuery = _query_ctrl,
) -> dict[str, Any]:
    _validate_position(row, col)
    normalized = normalize_keymap_action(str(action or ""))
    if not is_valid_keymap_action(normalized):
        return {"ok": False, "mode": "dry_run", "executed": False, "blocker": "invalid_keymap_action"}
    digest = _bounded_regular_file_sha256(keymap_path)
    persisted = _persisted_layers(keymap_path)
    live = _live_keymap(query_ctrl)
    matrix = _pressed_state(query_ctrl)
    before = _action_at(live["layers"], layer, row, col)
    phrase = _keymap_confirmation(layer, row, col, before, normalized, digest)
    blockers: list[str] = []
    if matrix.get("pressed"):
        blockers.append("matrix_not_idle")
    if live["layers"] != persisted:
        blockers.append("live_keymap_has_unpersisted_changes")
    return {
        "ok": not blockers,
        "mode": "dry_run",
        "executed": False,
        "keymap_path": str(keymap_path),
        "keymap_sha256": digest,
        "before": {"layer": layer, "row": row, "col": col, "action": before},
        "after": {"layer": layer, "row": row, "col": col, "action": normalized},
        "no_change": before == normalized,
        "blockers": blockers,
        "confirmation_phrase": phrase,
        "apply_requirements": [
            "expected_sha256 must equal the current runtime keymap digest",
            "confirm must exactly equal confirmation_phrase",
            "logicd must acknowledge remap and synchronous save",
            "live and persisted readback must match",
        ],
        "rollback": {"action": before, "same_position": True},
    }


def apply_keymap_change(
    layer: int,
    row: int,
    col: int,
    action: str,
    *,
    expected_sha256: str,
    confirm: str,
    keymap_path: Path = DEFAULT_RUNTIME_KEYMAP,
    query_ctrl: CtrlQuery = _query_ctrl,
) -> dict[str, Any]:
    plan = plan_keymap_change(layer, row, col, action, keymap_path=keymap_path, query_ctrl=query_ctrl)
    if not plan.get("ok"):
        return plan
    if expected_sha256 != plan["keymap_sha256"]:
        return {**plan, "ok": False, "executed": False, "blocker": "keymap_digest_changed"}
    if confirm != plan["confirmation_phrase"]:
        return {**plan, "ok": False, "executed": False, "blocker": "confirmation_mismatch"}
    if plan["no_change"]:
        return {**plan, "ok": True, "executed": False, "blocker": None, "result": "already_current"}

    before = plan["before"]["action"]
    normalized = plan["after"]["action"]
    remap = query_ctrl({"t": "M", "l": layer, "r": row, "c": col, "a": normalized})
    if remap.get("result") != "ok":
        return {**plan, "ok": False, "executed": True, "blocker": "remap_failed", "remap": remap}
    try:
        save = query_ctrl({"t": "S"})
    except Exception as exc:
        return {
            **plan,
            "ok": False,
            "executed": True,
            "blocker": "save_failed",
            "remap": remap,
            "save_error": f"{type(exc).__name__}: {exc}",
            "rollback": _rollback_keymap_change(layer, row, col, before, query_ctrl, keymap_path),
        }
    if save.get("result") != "ok":
        return {
            **plan,
            "ok": False,
            "executed": True,
            "blocker": "save_failed",
            "remap": remap,
            "save": save,
            "rollback": _rollback_keymap_change(layer, row, col, before, query_ctrl, keymap_path),
        }

    try:
        live_after = _live_keymap(query_ctrl)
        live_action = _action_at(live_after["layers"], layer, row, col)
        persisted_action = _action_at(_persisted_layers(keymap_path), layer, row, col)
        after_digest = _bounded_regular_file_sha256(keymap_path)
    except Exception as exc:
        return {
            **plan,
            "ok": False,
            "mode": "write",
            "executed": True,
            "blocker": "readback_failed",
            "remap": remap,
            "save": {key: value for key, value in save.items() if key != "path"},
            "readback_error": f"{type(exc).__name__}: {exc}",
            "rollback": _rollback_keymap_change(layer, row, col, before, query_ctrl, keymap_path),
        }
    verified = live_action == normalized and persisted_action == normalized and after_digest != plan["keymap_sha256"]
    rollback = (
        {"attempted": False, "action": before, "confirmation_required": True}
        if verified
        else _rollback_keymap_change(layer, row, col, before, query_ctrl, keymap_path)
    )
    return {
        **plan,
        "ok": verified,
        "mode": "write",
        "executed": True,
        "blocker": None if verified else "readback_mismatch",
        "remap": remap,
        "save": {key: value for key, value in save.items() if key != "path"},
        "readback": {
            "live_action": live_action,
            "persisted_action": persisted_action,
            "keymap_sha256": after_digest,
        },
        "rollback": rollback,
    }


def _rollback_keymap_change(
    layer: int,
    row: int,
    col: int,
    action: str,
    query_ctrl: CtrlQuery,
    keymap_path: Path,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "attempted": True,
        "restored_action": action,
        "verified": False,
        "errors": [],
    }
    try:
        evidence["remap"] = query_ctrl({"t": "M", "l": layer, "r": row, "c": col, "a": action})
    except Exception as exc:
        evidence["errors"].append(f"remap: {type(exc).__name__}: {exc}")
        return evidence
    try:
        evidence["save"] = query_ctrl({"t": "S"})
    except Exception as exc:
        evidence["errors"].append(f"save: {type(exc).__name__}: {exc}")
    try:
        live_action = _action_at(_live_keymap(query_ctrl)["layers"], layer, row, col)
        persisted_action = _action_at(_persisted_layers(keymap_path), layer, row, col)
        evidence["readback"] = {
            "live_action": live_action,
            "persisted_action": persisted_action,
            "keymap_sha256": _bounded_regular_file_sha256(keymap_path),
        }
        evidence["verified"] = live_action == action and persisted_action == action
    except Exception as exc:
        evidence["errors"].append(f"readback: {type(exc).__name__}: {exc}")
    return evidence


def plan_key_tap(
    row: int,
    col: int,
    *,
    keymap_path: Path = DEFAULT_RUNTIME_KEYMAP,
    query_ctrl: CtrlQuery = _query_ctrl,
) -> dict[str, Any]:
    _validate_position(row, col)
    digest = _bounded_regular_file_sha256(keymap_path)
    live = _live_keymap(query_ctrl)
    matrix = _pressed_state(query_ctrl)
    action, active_layers = _effective_action(live, row, col)
    blockers: list[str] = []
    if matrix.get("pressed"):
        blockers.append("matrix_not_idle")
    if live.get("output_target") != "auto":
        blockers.append("output_target_not_auto")
    if action not in SAFE_TAP_ACTIONS:
        blockers.append("unsafe_action")
    return {
        "ok": not blockers,
        "mode": "dry_run",
        "executed": False,
        "row": row,
        "col": col,
        "effective_action": action,
        "active_layers": active_layers,
        "output_target": live.get("output_target"),
        "keymap_sha256": digest,
        "safe_action_allowlist": sorted(SAFE_TAP_ACTIONS),
        "blockers": blockers,
        "confirmation_phrase": _tap_confirmation(row, col, action, digest),
        "operator_check": "focus a safe host input field before confirming the tap",
        "release_policy": "one release is always attempted; one bounded retry is used only if post-state remains pressed",
    }


def send_key_tap(
    row: int,
    col: int,
    *,
    expected_sha256: str,
    confirm: str,
    hold_ms: int = 30,
    keymap_path: Path = DEFAULT_RUNTIME_KEYMAP,
    query_ctrl: CtrlQuery = _query_ctrl,
    send_event: EventSender = _send_matrix_event,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    plan = plan_key_tap(row, col, keymap_path=keymap_path, query_ctrl=query_ctrl)
    if not plan.get("ok"):
        return plan
    if expected_sha256 != plan["keymap_sha256"]:
        return {**plan, "ok": False, "executed": False, "blockers": ["keymap_digest_changed"]}
    if confirm != plan["confirmation_phrase"]:
        return {**plan, "ok": False, "executed": False, "blockers": ["confirmation_mismatch"]}
    if not MIN_HOLD_MS <= int(hold_ms) <= MAX_HOLD_MS:
        return {**plan, "ok": False, "executed": False, "blockers": ["hold_ms_out_of_range"]}

    press = f"P{row:X}{col:X}\n"
    release = f"R{row:X}{col:X}\n"
    error: str | None = None
    release_errors: list[str] = []
    release_attempts = 0
    try:
        send_event(press)
        sleep(int(hold_ms) / 1000.0)
    except Exception as exc:  # release still belongs in finally
        error = f"{type(exc).__name__}: {exc}"
    finally:
        release_attempts += 1
        try:
            send_event(release)
        except Exception as exc:
            release_errors.append(f"{type(exc).__name__}: {exc}")

    post = _pressed_state(query_ctrl)
    target_pressed = [row, col] in post.get("pressed", [])
    if target_pressed:
        release_attempts += 1
        try:
            send_event(release)
        except Exception as exc:
            release_errors.append(f"{type(exc).__name__}: {exc}")
        post = _pressed_state(query_ctrl)

    clear = [row, col] not in post.get("pressed", [])
    ok = error is None and not release_errors and clear
    return {
        **plan,
        "ok": ok,
        "mode": "write",
        "executed": True,
        "hold_ms": int(hold_ms),
        "press_error": error,
        "release_attempts": release_attempts,
        "release_errors": release_errors,
        "post_state": {"pressed": post.get("pressed", []), "target_clear": clear},
    }


TOOLS: dict[str, dict[str, Any]] = {
    "get_control_status": {
        "description": "Summarize guarded write readiness, current keymap digest, output, and pressed state.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": lambda args: get_control_status(),
    },
    "plan_key_tap": {
        "description": "Dry-run one Web-GUI-equivalent matrix tap and return its exact confirmation phrase.",
        "inputSchema": {
            "type": "object",
            "properties": {"row": {"type": "integer"}, "col": {"type": "integer"}},
            "required": ["row", "col"],
            "additionalProperties": False,
        },
        "handler": lambda args: plan_key_tap(int(args["row"]), int(args["col"])),
    },
    "send_key_tap": {
        "description": "Send one bounded matrix tap only after digest and dynamic confirmation match.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "row": {"type": "integer"},
                "col": {"type": "integer"},
                "hold_ms": {"type": "integer", "minimum": MIN_HOLD_MS, "maximum": MAX_HOLD_MS},
                "expected_sha256": {"type": "string", "minLength": 64, "maxLength": 64},
                "confirm": {"type": "string"},
            },
            "required": ["row", "col", "expected_sha256", "confirm"],
            "additionalProperties": False,
        },
        "handler": lambda args: send_key_tap(
            int(args["row"]),
            int(args["col"]),
            hold_ms=int(args.get("hold_ms", 30)),
            expected_sha256=str(args.get("expected_sha256") or ""),
            confirm=str(args.get("confirm") or ""),
        ),
    },
    "plan_keymap_change": {
        "description": "Dry-run one validated keymap position change and return digest, rollback, and confirmation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "layer": {"type": "integer", "minimum": 0, "maximum": 31},
                "row": {"type": "integer"},
                "col": {"type": "integer"},
                "action": {"type": "string"},
            },
            "required": ["layer", "row", "col", "action"],
            "additionalProperties": False,
        },
        "handler": lambda args: plan_keymap_change(
            int(args["layer"]), int(args["row"]), int(args["col"]), str(args["action"])
        ),
    },
    "apply_keymap_change": {
        "description": "Apply and synchronously save one keymap position after digest and confirmation checks.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "layer": {"type": "integer", "minimum": 0, "maximum": 31},
                "row": {"type": "integer"},
                "col": {"type": "integer"},
                "action": {"type": "string"},
                "expected_sha256": {"type": "string", "minLength": 64, "maxLength": 64},
                "confirm": {"type": "string"},
            },
            "required": ["layer", "row", "col", "action", "expected_sha256", "confirm"],
            "additionalProperties": False,
        },
        "handler": lambda args: apply_keymap_change(
            int(args["layer"]),
            int(args["row"]),
            int(args["col"]),
            str(args["action"]),
            expected_sha256=str(args.get("expected_sha256") or ""),
            confirm=str(args.get("confirm") or ""),
        ),
    },
}


def _content_result(payload: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)}]}


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
                    {"name": name, "description": spec["description"], "inputSchema": spec["inputSchema"]}
                    for name, spec in TOOLS.items()
                ]
            },
        }
    if method == "tools/call":
        params = request.get("params", {})
        name = params.get("name") if isinstance(params, dict) else None
        args = params.get("arguments", {}) if isinstance(params, dict) else {}
        if name not in TOOLS:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"unknown tool: {name}"}}
        try:
            result = TOOLS[str(name)]["handler"](args if isinstance(args, dict) else {})
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": str(exc)}}
        return {"jsonrpc": "2.0", "id": request_id, "result": _content_result(result)}
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"unsupported method: {method}"}}


def _read_framed(stdin: TextIO) -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = stdin.buffer.readline()
        if not line:
            return None
        text = line.decode("ascii", errors="replace").strip()
        if not text:
            break
        if ":" in text:
            key, value = text.split(":", 1)
            headers[key.lower()] = value.strip()
    length = headers.get("content-length")
    if not length:
        return None
    return json.loads(stdin.buffer.read(int(length)).decode("utf-8"))


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
    parser.add_argument("--args-json", default="{}", help="JSON object passed to --tool")
    args = parser.parse_args(argv)
    if args.stdio:
        serve_stdio()
        return 0
    if args.tool:
        tool_args = json.loads(args.args_json)
        if not isinstance(tool_args, dict):
            raise SystemExit("--args-json must be a JSON object")
        print(json.dumps(TOOLS[args.tool]["handler"](tool_args), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
