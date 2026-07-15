#!/usr/bin/env python3
"""Regression tests for the logicd output-router contract."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.output_router import CallableOutputBackend, OutputRouter, parse_output_targets  # noqa: E402


def main() -> None:
    sent: dict[str, list[bytes]] = {"usb": [], "bt": [], "uinput": []}

    router = OutputRouter()
    router.register(CallableOutputBackend("usb", lambda report: sent["usb"].append(report)))
    router.register(CallableOutputBackend("bt", lambda report: sent["bt"].append(report)))
    router.register(CallableOutputBackend("uinput", lambda report: sent["uinput"].append(report)))

    assert router.backend_names() == ("bt", "uinput", "usb")

    router.set_targets(parse_output_targets("usb+bt"))
    assert router.targets() == ("usb", "bt")
    result = router.send(b"report1")
    assert result == {"usb": True, "bt": True}
    assert sent["usb"] == [b"report1"]
    assert sent["bt"] == [b"report1"]
    assert sent["uinput"] == []

    router.set_targets(parse_output_targets(["uinput", "bt", "bt"]))
    assert router.targets() == ("uinput", "bt")
    result = router.send(b"report2")
    assert result == {"uinput": True, "bt": True}
    assert sent["uinput"] == [b"report2"]
    assert sent["bt"] == [b"report1", b"report2"]

    router.set_targets(("missing",))
    assert router.send(b"report3") == {"missing": False}

    router.register(CallableOutputBackend("debug", lambda report: None, enabled=False))
    router.set_targets(parse_output_targets("gadget,uinput,bt,debug"))
    assert router.targets() == ("gadget", "uinput", "bt", "debug")
    assert router.current_mode == "gadget,uinput,bt,debug"

    def auto_writer(_report: bytes) -> None:
        return None

    auto_writer.current_mode = "bt"  # type: ignore[attr-defined]
    router.register(CallableOutputBackend("auto", auto_writer))
    router.set_targets(("auto",))
    assert router.current_mode == "bt"

    print("ok: output router contract")


if __name__ == "__main__":
    main()
