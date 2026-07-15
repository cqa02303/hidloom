"""Small systemd status snapshot helper for OLED daemon badges."""
from __future__ import annotations

import asyncio
import time

DAEMON_STATUS_SERVICES: tuple[str, ...] = (
    "matrixd",
    "logicd-core",
    "logicd-companion",
    "outputd",
    "uidd",
    "ledd",
    "btd",
    "httpd",
    "hidd",
    "viald",
)

_CACHE: dict[str, tuple[bool, float]] = {}
_TTL_SEC = 5.0


async def service_active(name: str) -> bool:
    """Return whether a systemd service is active, with a tiny async cache."""

    if name == "logicd":
        return True
    unit_name = {
        "hidd": "hidloom-hidd.service",
        "logicd-core": "hidloom-logicd-core.service",
        "logicd-companion": "logicd-companion.service",
        "outputd": "hidloom-outputd.service",
        "uidd": "hidloom-uidd.service",
    }.get(name, name)

    now = time.monotonic()
    cached = _CACHE.get(name)
    if cached is not None:
        value, updated_at = cached
        if now - updated_at < _TTL_SEC:
            return value

    try:
        proc = await asyncio.create_subprocess_exec(
            "systemctl",
            "is-active",
            unit_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=2.0)
        value = stdout.decode().strip() == "active"
    except Exception:
        value = cached[0] if cached is not None else False

    _CACHE[name] = (value, now)
    return value


async def daemon_status_snapshot(services: tuple[str, ...] = DAEMON_STATUS_SERVICES) -> dict[str, bool]:
    results = await asyncio.gather(*(service_active(service) for service in services))
    return dict(zip(services, results))
