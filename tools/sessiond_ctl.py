#!/usr/bin/env python3
"""Small CLI for the sessiond PTY mirror M0 socket."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from sessiond.protocol import (  # noqa: E402
    DEFAULT_COLUMNS,
    DEFAULT_ROWS,
    DEFAULT_SESSIOND_SOCKET,
    TYPE_PTY_KEY_INPUT,
    TYPE_PTY_STATUS,
    TYPE_PTY_TEXT_STREAM,
    TYPE_STOP_PTY_MIRROR,
    decode_message,
    encode_message,
    make_message,
    start_pty_mirror_message,
)

MAX_WRITE_BYTES = 4096
MAX_KEY_TOKEN_BYTES = 64
MAX_KEY_MODIFIERS = 8


async def _send(socket_path: str, message: dict, *, read_timeout: float) -> tuple[int, dict]:
    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)
    except OSError as exc:
        return 2, {"ok": False, "error": str(exc), "socket": socket_path, "responses": []}

    responses: list[dict] = []
    try:
        writer.write(encode_message(message))
        await writer.drain()
        deadline = asyncio.get_running_loop().time() + max(0.05, read_timeout)
        while asyncio.get_running_loop().time() < deadline:
            timeout = deadline - asyncio.get_running_loop().time()
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=timeout)
            except asyncio.TimeoutError:
                break
            if not line:
                break
            responses.append(decode_message(line))
            if message.get("type") != TYPE_PTY_KEY_INPUT and responses[-1].get("type") == TYPE_PTY_STATUS:
                break
            if responses[-1].get("type") == TYPE_PTY_STATUS and responses[-1].get("active") is False:
                break
    finally:
        writer.close()
        await writer.wait_closed()

    ok = any(
        item.get("type") in {TYPE_PTY_STATUS, TYPE_PTY_TEXT_STREAM} and "error" not in item
        for item in responses
    )
    return (0 if ok else 1), {"ok": ok, "socket": socket_path, "request": message, "responses": responses}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", default=DEFAULT_SESSIOND_SOCKET)
    parser.add_argument("--read-timeout", type=float, default=2.0)
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", aliases=["start-pty-mirror"])
    start.add_argument("--shell", default="bash")
    start.add_argument("--columns", type=int, default=DEFAULT_COLUMNS)
    start.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    start.add_argument("--source", default="KC_SH7")

    stop = sub.add_parser("stop")
    stop.add_argument("--reason", default="operator_stop")

    write = sub.add_parser("write")
    write.add_argument("text")
    write.add_argument("--enter", action="store_true")

    key = sub.add_parser("key")
    key.add_argument("action")
    key.add_argument("--modifier", action="append", default=[])
    key.add_argument("--release", action="store_true")

    sub.add_parser("status")
    return parser


async def _amain() -> int:
    args = _build_parser().parse_args()
    if args.command in ("start", "start-pty-mirror"):
        message = start_pty_mirror_message(
            command=args.shell,
            columns=args.columns,
            rows=args.rows,
            source=args.source,
        )
    elif args.command == "stop":
        message = make_message(TYPE_STOP_PTY_MIRROR, reason=args.reason)
    elif args.command == "write":
        text = str(args.text)
        if args.enter:
            text += "\r"
        try:
            data = text.encode("ascii")
        except UnicodeEncodeError:
            print(json.dumps({
                "ok": False,
                "error": "write accepts ASCII text only in PTY mirror M0",
            }, ensure_ascii=False, indent=2))
            return 2
        if len(data) > MAX_WRITE_BYTES:
            print(json.dumps({
                "ok": False,
                "error": f"write accepts at most {MAX_WRITE_BYTES} bytes in PTY mirror M0",
            }, ensure_ascii=False, indent=2))
            return 2
        message = make_message(TYPE_PTY_KEY_INPUT, bytes_hex=data.hex())
    elif args.command == "key":
        key_error = _validate_key_tokens(str(args.action), list(args.modifier or []))
        if key_error:
            print(json.dumps({"ok": False, "error": key_error}, ensure_ascii=False, indent=2))
            return 2
        message = make_message(
            TYPE_PTY_KEY_INPUT,
            action=str(args.action),
            is_press=not bool(args.release),
            modifiers=list(args.modifier or []),
        )
    else:
        message = make_message(TYPE_PTY_STATUS)

    code, payload = await _send(args.socket, message, read_timeout=args.read_timeout)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


def main() -> None:
    raise SystemExit(asyncio.run(_amain()))


def _validate_key_tokens(action: str, modifiers: list[str]) -> str:
    tokens = [action, *modifiers]
    if len(modifiers) > MAX_KEY_MODIFIERS:
        return f"key accepts at most {MAX_KEY_MODIFIERS} modifiers in PTY mirror M0"
    for token in tokens:
        try:
            data = token.encode("ascii")
        except UnicodeEncodeError:
            return "key accepts ASCII action/modifier names only in PTY mirror M0"
        if not data or len(data) > MAX_KEY_TOKEN_BYTES:
            return f"key action/modifier names must be 1-{MAX_KEY_TOKEN_BYTES} bytes in PTY mirror M0"
    return ""


if __name__ == "__main__":
    main()
