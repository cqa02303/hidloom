#!/usr/bin/env python3
"""Regression tests for native hidloom-outputd control from logicd companion."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.native_outputd import NativeOutputdSwitchWriter  # noqa: E402


class InnerWriter:
    def __init__(self) -> None:
        self.reports: list[bytes] = []
        self.calls: list[str] = []

    def __call__(self, report: bytes) -> None:
        self.reports.append(report)


def main() -> None:
    requests: list[tuple[dict, str | None]] = []

    def fake_request(message: dict, *, socket_path: str | None = None) -> dict:
        requests.append((message, socket_path))
        return {"result": "ok", "target": message.get("target", "")}

    inner = InnerWriter()
    changed: list[str] = []
    writer = NativeOutputdSwitchWriter(
        inner,
        socket_path="/tmp/test-outputd.sock",
        on_target_changed=changed.append,
        request_fn=fake_request,
    )

    writer(b"12345678")
    writer.force_gadget()
    writer.force_uinput()
    writer.force_auto()
    writer.force_bt()

    assert inner.reports == [b"12345678"]
    assert inner.calls == []
    assert changed == ["gadget", "uinput", "auto", "bt"]
    assert [msg["target"] for msg, _ in requests] == ["usb", "uinput", "auto", "bt"]
    assert [path for _, path in requests] == ["/tmp/test-outputd.sock"] * 4
    assert all(msg["t"] == "set_output_target" for msg, _ in requests)

    print("ok: native outputd ctrl maps companion output switches")


if __name__ == "__main__":
    main()
