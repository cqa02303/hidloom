"""HTTP security middleware helpers.

Keep private-network checks, CSRF helpers, and audit logging out of httpd.py.
This module is deliberately side-effect free apart from emitting audit log lines
through the logger passed by the caller.
"""
from __future__ import annotations

import hmac
import ipaddress
import re

from aiohttp import web


def configured_allowed_networks(log, value: str) -> tuple[ipaddress._BaseNetwork, ...]:
    networks: list[ipaddress._BaseNetwork] = []
    for raw in re.split(r"[,\s]+", value.strip()):
        if not raw:
            continue
        try:
            networks.append(ipaddress.ip_network(raw, strict=False))
        except ValueError:
            log.warning("Ignoring invalid HTTPD_ALLOWED_NETS entry: %r", raw)
    return tuple(networks)


def remote_ip_allowed(
    remote: str | None,
    *,
    private_only: bool,
    default_allowed_nets: tuple[ipaddress._BaseNetwork, ...],
    extra_allowed_nets: tuple[ipaddress._BaseNetwork, ...],
) -> bool:
    if not private_only:
        return True
    if not remote:
        return False
    host = remote.rsplit("%", 1)[0]
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(ip in network for network in (*default_allowed_nets, *extra_allowed_nets))


def csrf_token_valid(value: str | None, token: str) -> bool:
    if not value:
        return False
    return hmac.compare_digest(value, token)


def csrf_token_for_request(request: web.Request, csrf_header: str) -> str | None:
    if request.path == "/ws":
        return request.rel_url.query.get("csrf")
    return request.headers.get(csrf_header)


def response_should_set_csrf_cookie(request: web.Request) -> bool:
    return request.method == "GET" and (request.path == "/" or request.path.startswith("/api/"))


def set_csrf_cookie(response: web.StreamResponse, *, cookie_name: str, token: str) -> None:
    response.set_cookie(
        cookie_name,
        token,
        path="/",
        secure=True,
        httponly=False,
        samesite="Strict",
    )


def audit_field(value: object, fallback: str = "-") -> str:
    text = str(value if value is not None else fallback)
    safe = re.sub(r"[^A-Za-z0-9._:@/+=,-]+", "_", text)
    return (safe or fallback)[:160]


def audit_log(log, request: web.Request, action: str, *, username: str, **fields: object) -> None:
    remote = audit_field(getattr(request, "remote", None))
    parts = [
        f"action={audit_field(action)}",
        f"remote={remote}",
        f"user={audit_field(username)}",
    ]
    parts.extend(f"{audit_field(key)}={audit_field(value)}" for key, value in sorted(fields.items()))
    log.info("AUDIT http %s", " ".join(parts))
