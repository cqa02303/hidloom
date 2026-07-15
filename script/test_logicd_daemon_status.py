#!/usr/bin/env python3
"""Regression tests for logicd-to-i2cd daemon status payloads."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd import daemon_status  # noqa: E402
from logicd.runtime_notifications import LogicdNotifier  # noqa: E402
from logicd.state import LogicdRuntime  # noqa: E402


class FakeWriter:
    def __init__(self) -> None:
        self.data: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.data.append(data)


async def _snapshot_with_fake_services() -> None:
    old = daemon_status.service_active
    try:
        async def fake_service_active(name: str) -> bool:
            return name in {"logicd", "httpd"}

        daemon_status.service_active = fake_service_active  # type: ignore[assignment]
        snapshot = await daemon_status.daemon_status_snapshot(("logicd", "httpd", "hidd", "btd"))
    finally:
        daemon_status.service_active = old  # type: ignore[assignment]

    assert snapshot == {"logicd": True, "httpd": True, "hidd": False, "btd": False}
    assert "hidd" in daemon_status.DAEMON_STATUS_SERVICES
    assert "usbd" not in daemon_status.DAEMON_STATUS_SERVICES


def main() -> None:
    writer = FakeWriter()
    runtime = LogicdRuntime(i2cd_writer=writer)
    notifier = LogicdNotifier(runtime)

    notifier.push_i2cd_daemon_status({"logicd": True, "btd": False})
    assert writer.data == [b'{"t": "daemon_status", "services": {"logicd": true, "btd": false}}\n']

    asyncio.run(_snapshot_with_fake_services())
    print("ok: logicd daemon status payload")


if __name__ == "__main__":
    main()
