#!/usr/bin/env python3
"""Focused regression checks for HTTP injection hardening."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon" / "http"))
sys.path.insert(0, str(ROOT))

import httpd  # noqa: E402


async def _main_async() -> None:
    private_allowed_ip = ".".join(("192", "168", "0", "49"))
    private_non_loopback_ip = ".".join(("192", "168", "0", "58"))
    assert httpd._remote_ip_allowed("127.0.0.1")
    assert httpd._remote_ip_allowed(private_allowed_ip)
    assert httpd._remote_ip_allowed("10.1.2.3")
    assert httpd._remote_ip_allowed("172.16.0.1")
    assert httpd._remote_ip_allowed("172.31.255.254")
    assert httpd._remote_ip_allowed("169.254.1.2")
    assert not httpd._remote_ip_allowed("8.8.8.8")
    assert not httpd._remote_ip_allowed("2001:4860:4860::8888")
    assert not httpd._remote_ip_allowed("not-an-ip")
    original_loopback_bypass = httpd.HTTPD_AUTH_BYPASS_LOOPBACK
    try:
        httpd.HTTPD_AUTH_BYPASS_LOOPBACK = False
        assert not httpd._auth_bypass_allowed("127.0.0.1")
        httpd.HTTPD_AUTH_BYPASS_LOOPBACK = True
        assert httpd._auth_bypass_allowed("127.0.0.1")
        assert httpd._auth_bypass_allowed("::1")
        assert not httpd._auth_bypass_allowed(private_non_loopback_ip)
        assert not httpd._auth_bypass_allowed("not-an-ip")
    finally:
        httpd.HTTPD_AUTH_BYPASS_LOOPBACK = original_loopback_bypass
    assert httpd._configured_allowed_networks("203.0.113.0/24")[0].version == 4
    assert not httpd._csrf_token_valid("")
    assert not httpd._csrf_token_valid("wrong")
    assert httpd._csrf_token_valid(httpd.HTTPD_CSRF_TOKEN)
    assert httpd._audit_field("bad\r\nvalue with spaces") == "bad_value_with_spaces"

    assert httpd._safe_header_filename_part('host\r\nX-Bad: yes') == "host_X-Bad_yes"
    assert httpd._safe_header_filename_part('../../bad"name;x') == "bad_name_x"
    disposition = httpd._attachment_content_disposition('dev\r\nSet-Cookie: bad=1".vil')
    assert "\r" not in disposition
    assert "\n" not in disposition
    assert "Set-Cookie:" not in disposition
    assert disposition.startswith('attachment; filename="')
    assert disposition.endswith('.vil"')

    sent: list[str] = []
    original_send = httpd._send_key_event
    async def fake_send(event: str) -> None:
        sent.append(event)
    try:
        httpd._send_key_event = fake_send  # type: ignore[assignment]
        await httpd._process_ws_message('{"type":"keydown","row":"bad","col":1}')
        await httpd._process_ws_message('{"type":"keydown","row":16,"col":1}')
        await httpd._process_ws_message('{"type":"keydown","row":1,"col":2}')
        await httpd._process_ws_message("R12")
    finally:
        httpd._send_key_event = original_send  # type: ignore[assignment]
    assert sent == ["P12\n", "R12\n"]

    csrf_js = (ROOT / "daemon/http/static/csrf.js").read_text(encoding="utf-8")
    assert "hidloom_csrf" in csrf_js
    assert "X-HIDLOOM-CSRF" in csrf_js
    assert "csrfFetch" in csrf_js
    assert "csrfWebSocketUrl" in csrf_js

    httpd_py = (ROOT / "daemon/http/httpd.py").read_text(encoding="utf-8")
    assert "csrf_middleware" in httpd_py
    assert "HTTPD_CSRF_TOKEN = secrets.token_urlsafe(32)" in httpd_py
    assert 'request.method in {"POST", "PUT", "DELETE"} or request.path == "/ws"' in httpd_py
    assert "web.HTTPForbidden" in httpd_py
    socket_bridge_py = (ROOT / "daemon/http/socket_bridge.py").read_text(encoding="utf-8")
    assert 'raw[0] in {"P", "R"}' in socket_bridge_py
    assert "AUDIT http" in httpd_py
    assert '"script_save"' in httpd_py
    assert '"script_check_run"' in httpd_py
    assert '"script_run"' in httpd_py
    assert '"bluetooth_forget"' in httpd_py
    assert '"keymap_reset"' in httpd_py


def main() -> None:
    asyncio.run(_main_async())
    print("ok: HTTP injection hardening checks")


if __name__ == "__main__":
    main()
