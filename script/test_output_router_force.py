#!/usr/bin/env python3
"""Regression tests for OutputRouter force_* output target controls."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.output_router import BluetoothHidOutputBackend, CallableOutputBackend, OutputRouter  # noqa: E402


class DummyWriter:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, report: bytes) -> None:
        self.calls.append(report.hex())

    def force_auto(self) -> None:
        self.calls.append("force_auto")

    def force_gadget(self) -> None:
        self.calls.append("force_gadget")

    def force_uinput(self) -> None:
        self.calls.append("force_uinput")


def main() -> None:
    auto_writer = DummyWriter()
    bt_reports: list[bytes] = []
    bt_disabled_calls: list[str] = []
    target_changes: list[str] = []
    router = OutputRouter(
        on_bt_disabled=lambda: bt_disabled_calls.append("disabled"),
        on_target_changed=target_changes.append,
    )
    router.register(CallableOutputBackend("auto", auto_writer))
    router.register(CallableOutputBackend("gadget", lambda report: None, enabled=False))
    router.register(CallableOutputBackend("uinput", lambda report: None, enabled=False))
    router.register(BluetoothHidOutputBackend(sender=bt_reports.append, enabled=False))
    router.set_targets(("auto",))
    assert router.enabled_names() == ("auto",)

    router.force_bt()
    assert router.enabled_names() == ("bt",)
    assert target_changes[-1] == "bt"
    router.write(b"\x01\x02")
    assert bt_reports == [b"\x01\x02"]

    router.force_auto()
    assert router.enabled_names() == ("auto",)
    assert target_changes[-1] == "auto"
    assert "force_auto" in auto_writer.calls
    assert bt_reports == [b"\x01\x02", bytes(8)]
    assert bt_disabled_calls == ["disabled"]

    router.force_gadget()
    assert router.enabled_names() == ("gadget",)
    assert target_changes[-1] == "gadget"
    assert "force_gadget" not in auto_writer.calls

    router.force_uinput()
    assert router.enabled_names() == ("uinput",)
    assert target_changes[-1] == "uinput"
    assert "force_uinput" not in auto_writer.calls

    explicit = OutputRouter([
        CallableOutputBackend("gadget", lambda report: None),
        CallableOutputBackend("uinput", lambda report: None),
        BluetoothHidOutputBackend(sender=bt_reports.append, enabled=False),
    ])
    explicit.force_gadget()
    assert explicit.enabled_names() == ("gadget",)
    explicit.force_uinput()
    assert explicit.enabled_names() == ("uinput",)
    explicit.force_bt()
    assert explicit.enabled_names() == ("bt",)

    print("ok: output router force controls")


if __name__ == "__main__":
    main()
