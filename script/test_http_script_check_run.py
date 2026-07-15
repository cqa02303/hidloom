#!/usr/bin/env python3
"""Smoke tests for HTTP script check-run API."""
from __future__ import annotations

import asyncio
import json
import os
import sys

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon" / "http"))
sys.path.insert(0, str(ROOT))

import httpd  # noqa: E402


class FakeRequest:
    def __init__(self, keycode: str, body: dict | None = None) -> None:
        self.match_info = {"keycode": keycode}
        self._body = body or {}

    async def json(self) -> dict:
        return self._body


async def _main_async() -> None:
    if os.name == "nt":
        print("skip: HTTP script check-run requires POSIX shell script execution")
        return

    audit_events: list[tuple[str, dict]] = []
    original_audit_log = httpd._audit_log
    original_script_entry = httpd._script_entry

    def fake_audit(_request: object, action: str, **fields: object) -> None:
        audit_events.append((action, fields))

    try:
        httpd._audit_log = fake_audit  # type: ignore[assignment]
        ok = await httpd.handle_script_check_run(FakeRequest("KC_SH1", {
            "content": "#!/bin/sh\necho check-ok\n",
        }))
        assert ok.status == 200
        ok_body = json.loads(ok.text)
        assert ok_body["result"] == "ok"
        assert ok_body["exit_code"] == 0
        assert ok_body["stdout"] == "check-ok\n"

        bad = await httpd.handle_script_check_run(FakeRequest("KC_SH1", {
            "content": "#!/bin/sh\necho check-ng >&2\nexit 7\n",
        }))
        assert bad.status == 422
        bad_body = json.loads(bad.text)
        assert bad_body["result"] == "error"
        assert bad_body["exit_code"] == 7
        assert bad_body["stderr"] == "check-ng\n"

        script_path = ROOT / "config" / "default" / "script" / "KC_SH0.sh"
        httpd._script_entry = lambda _keycode: {  # type: ignore[assignment]
            "exists": True,
            "path": str(script_path),
            "source": "fallback",
        }
        run = await httpd.handle_script_run(FakeRequest("KC_SH0"))
        assert run.status == 200
        run_body = json.loads(run.text)
        assert run_body["result"] == "ok"
        assert run_body["exit_code"] == 0
        assert "KC_SH0: safe no-op" in run_body["stdout"]
    finally:
        httpd._audit_log = original_audit_log  # type: ignore[assignment]
        httpd._script_entry = original_script_entry  # type: ignore[assignment]

    assert audit_events == [
        ("script_check_run", {"keycode": "KC_SH1", "result": "ok", "exit_code": 0}),
        ("script_check_run", {"keycode": "KC_SH1", "result": "error", "exit_code": 7}),
        ("script_run", {"keycode": "KC_SH0", "result": "ok", "exit_code": 0}),
    ]


def main() -> None:
    asyncio.run(_main_async())
    print("ok: HTTP script check-run API")


if __name__ == "__main__":
    main()
