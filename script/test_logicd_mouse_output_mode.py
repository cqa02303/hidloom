#!/usr/bin/env python3
"""Regression tests for mouse reports following output mode."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.config_runtime import (  # noqa: E402
    effective_output_mode,
    make_mode_aware_consumer_write_fn,
    make_mode_aware_mouse_write_fn,
)
from logicd.state import LogicdRuntime  # noqa: E402


def main() -> None:
    reports: list[bytes] = []
    bt_reports: list[bytes] = []
    mode = ["gadget"]
    write = make_mode_aware_mouse_write_fn(reports.append, lambda: mode[0], bt_reports.append)

    write(b"\x00\x01\x00\x00")
    assert reports == [b"\x00\x01\x00\x00"]

    mode[0] = "bt"
    write(b"\x00\x02\x00\x00")
    assert reports == [b"\x00\x01\x00\x00"]
    assert bt_reports == [b"\x00\x02\x00\x00"]

    mode[0] = "uinput"
    write(b"\x00\x03\x00\x00")
    assert reports == [b"\x00\x01\x00\x00"]
    assert bt_reports == [b"\x00\x02\x00\x00"]

    mode[0] = "auto"
    write(b"\x00\x04\x00\x00")
    assert reports == [b"\x00\x01\x00\x00", b"\x00\x04\x00\x00"]

    consumer_events: list[tuple[int, bool]] = []
    bt_consumer_events: list[tuple[int, bool]] = []
    consumer_write = make_mode_aware_consumer_write_fn(
        lambda usage, pressed: consumer_events.append((usage, pressed)),
        lambda: mode[0],
        lambda usage, pressed: bt_consumer_events.append((usage, pressed)),
    )
    mode[0] = "gadget"
    consumer_write(0x00E9, True)
    mode[0] = "bt"
    consumer_write(0x00E9, False)
    assert consumer_events == [(0x00E9, True)]
    assert bt_consumer_events == [(0x00E9, False)]

    runtime = LogicdRuntime()
    runtime.current_hid_mode = "auto"

    class AutoWriter:
        current_mode = "bt"

    assert effective_output_mode(runtime, AutoWriter()) == "bt"
    auto_mouse_reports: list[bytes] = []
    auto_bt_reports: list[bytes] = []
    auto_mouse_write = make_mode_aware_mouse_write_fn(
        auto_mouse_reports.append,
        lambda: effective_output_mode(runtime, AutoWriter()),
        auto_bt_reports.append,
    )
    auto_mouse_write(b"\x00\x05\x00\x00")
    assert auto_mouse_reports == []
    assert auto_bt_reports == [b"\x00\x05\x00\x00"]

    class UinputAutoWriter:
        current_mode = "uinput"

    assert effective_output_mode(runtime, UinputAutoWriter()) == "uinput"
    auto_mouse_write = make_mode_aware_mouse_write_fn(
        auto_mouse_reports.append,
        lambda: effective_output_mode(runtime, UinputAutoWriter()),
        auto_bt_reports.append,
    )
    auto_mouse_write(b"\x00\x06\x00\x00")
    assert auto_mouse_reports == []
    assert auto_bt_reports == [b"\x00\x05\x00\x00"]

    print("ok: mouse and consumer reports follow output mode")


if __name__ == "__main__":
    main()
