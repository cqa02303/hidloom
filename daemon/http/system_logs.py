from __future__ import annotations

import asyncio

from aiohttp import web

LOG_ALLOWED_SERVICES = frozenset({
    "logicd",
    "logicd-core",
    "logicd-companion",
    "matrixd",
    "ledd",
    "viald",
    "usbd",
    "hidd",
    "outputd",
    "uidd",
    "i2cd",
    "httpd",
    "btd",
    "spid",
})
LOG_SERVICE_UNITS = {
    "hidd": "hidloom-hidd.service",
    "logicd-core": "hidloom-logicd-core.service",
    "logicd-companion": "logicd-companion.service",
    "outputd": "hidloom-outputd.service",
    "uidd": "hidloom-uidd.service",
}


async def journal_lines(service: str, lines: int) -> web.Response:
    if service not in LOG_ALLOWED_SERVICES:
        return web.json_response({"error": f"Unknown service: {service}"}, status=400)
    lines_int = max(1, min(lines, 500))
    try:
        proc = await asyncio.create_subprocess_exec(
            "journalctl", "-u", LOG_SERVICE_UNITS.get(service, service), "-n", str(lines_int), "--no-pager", "-l", "--output=short-iso",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
    except asyncio.TimeoutError:
        return web.json_response({"error": "journalctl timeout"}, status=504)
    except FileNotFoundError:
        return web.json_response({"error": "journalctl not available on this system"}, status=501)
    return web.json_response({"service": service, "lines": stdout.decode(errors="replace").splitlines()})
