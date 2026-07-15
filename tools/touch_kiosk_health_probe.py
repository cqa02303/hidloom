#!/usr/bin/env python3
"""Probe and optionally repair the touch-panel Chromium kiosk via CDP."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import urllib.error
import urllib.request

try:
    import websockets
except Exception as exc:  # pragma: no cover - depends on target OS packages
    print(f"websockets unavailable: {exc}", file=sys.stderr)
    raise SystemExit(2)


STATE_EXPR = """
(() => ({
  href: location.href,
  title: document.title,
  readyState: document.readyState,
  bodyLength: document.body ? document.body.innerHTML.length : 0,
  wsStatus: document.getElementById('ws-status')?.textContent || null,
  appTabs: Array.from(document.querySelectorAll('#app-tabs button')).map((b) => b.textContent),
}))()
"""


def load_page(cdp: str) -> dict:
    with urllib.request.urlopen(cdp.rstrip("/") + "/json/list", timeout=4) as response:
        tabs = json.load(response)
    for tab in tabs:
        if tab.get("type") == "page":
            return tab
    if tabs:
        return tabs[0]
    raise RuntimeError("no CDP tabs found")


async def call_cdp(ws_url: str, method: str, params: dict | None = None, timeout: float = 8.0) -> dict:
    async with websockets.connect(ws_url, open_timeout=4, ping_interval=None) as conn:
        await conn.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
        while True:
            message = json.loads(await asyncio.wait_for(conn.recv(), timeout=timeout))
            if message.get("id") == 1:
                return message


async def page_state(ws_url: str) -> dict:
    response = await call_cdp(ws_url, "Runtime.evaluate", {"expression": STATE_EXPR, "returnByValue": True})
    return response.get("result", {}).get("result", {}).get("value", {}) or {}


def is_healthy(state: dict, *, expect_url: str, min_body_length: int, require_ready: bool) -> bool:
    if state.get("href") != expect_url:
        return False
    if int(state.get("bodyLength") or 0) < min_body_length:
        return False
    if not state.get("title"):
        return False
    if require_ready and state.get("wsStatus") != "Ready":
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe touch-panel Chromium kiosk health through loopback CDP")
    parser.add_argument("--cdp", default="http://127.0.0.1:9222")
    parser.add_argument("--expect-url", default="https://127.0.0.1/?keyboard=1")
    parser.add_argument("--min-body-length", type=int, default=1000)
    parser.add_argument("--attempts", type=int, default=5)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--require-ready", action="store_true")
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--inject-about-blank", action="store_true")
    args = parser.parse_args()

    last_state: dict = {}
    last_error: Exception | None = None
    page = load_page(args.cdp)
    ws_url = page.get("webSocketDebuggerUrl")
    if not ws_url:
        raise SystemExit("page has no webSocketDebuggerUrl")

    if args.inject_about_blank:
        asyncio.run(call_cdp(ws_url, "Page.navigate", {"url": "about:blank"}))
        time.sleep(args.interval)

    for _ in range(max(1, args.attempts)):
        try:
            page = load_page(args.cdp)
            ws_url = page["webSocketDebuggerUrl"]
            last_state = asyncio.run(page_state(ws_url))
            if is_healthy(
                last_state,
                expect_url=args.expect_url,
                min_body_length=args.min_body_length,
                require_ready=args.require_ready,
            ):
                print(json.dumps({"ok": True, "state": last_state}, ensure_ascii=False))
                return
            actual_url = last_state.get("href") or page.get("url") or ""
            body_length = int(last_state.get("bodyLength") or 0)
            if args.repair and (
                actual_url in ("", "about:blank")
                or str(actual_url).startswith("chrome-error://")
                or (actual_url == args.expect_url and body_length < args.min_body_length)
            ):
                asyncio.run(call_cdp(ws_url, "Page.navigate", {"url": args.expect_url}))
        except (OSError, urllib.error.URLError, TimeoutError, asyncio.TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(args.interval)

    result = {"ok": False, "state": last_state}
    if last_error is not None:
        result["error"] = repr(last_error)
    print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
