#!/usr/bin/env python3
"""Regression tests for auto output fallback order."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd import output_switch  # noqa: E402
from logicd.output_switch import create_dynamic_write_fn  # noqa: E402


def main() -> None:
    bt_reports: list[bytes] = []
    uinput_reports: list[bytes] = []
    i2cd_modes: list[str] = []

    writer = create_dynamic_write_fn(
        "/tmp/missing-hidg-for-auto-test",
        {},
        uinput_factory=lambda _cfg: uinput_reports.append,
        bt_writer=bt_reports.append,
        bt_available=lambda: True,
        push_i2cd_mode=i2cd_modes.append,
    )

    writer(b"report")
    assert bt_reports == []
    assert uinput_reports == [b"report"]
    assert i2cd_modes == ["auto:uinput"]
    assert writer.current_mode == "uinput"  # type: ignore[attr-defined]

    bt_reports.clear()
    uinput_reports.clear()
    i2cd_modes.clear()
    writer = create_dynamic_write_fn(
        "/tmp/missing-hidg-for-auto-test",
        {},
        uinput_factory=lambda _cfg: uinput_reports.append,
        bt_writer=bt_reports.append,
        bt_available=lambda: False,
        allow_bt_fallback=True,
        push_i2cd_mode=i2cd_modes.append,
    )

    writer(b"report")
    assert bt_reports == []
    assert uinput_reports == [b"report"]
    assert i2cd_modes == ["auto:uinput"]
    assert writer.current_mode == "uinput"  # type: ignore[attr-defined]

    bt_reports.clear()
    uinput_reports.clear()
    i2cd_modes.clear()
    writer = create_dynamic_write_fn(
        "/tmp/missing-hidg-for-auto-test",
        {},
        uinput_factory=lambda _cfg: uinput_reports.append,
        bt_writer=bt_reports.append,
        bt_available=lambda: True,
        allow_bt_fallback=True,
        push_i2cd_mode=i2cd_modes.append,
    )

    writer(b"report")
    assert bt_reports == [b"report"]
    assert uinput_reports == []
    assert i2cd_modes == ["auto:bt"]
    assert writer.current_mode == "bt"  # type: ignore[attr-defined]

    bt_reports.clear()
    uinput_reports.clear()
    i2cd_modes.clear()
    writer.force_auto()  # type: ignore[attr-defined]
    assert bt_reports == []
    assert uinput_reports == []
    assert i2cd_modes == ["auto:bt"]

    debug_messages: list[str] = []
    now = [0.0]
    old_glob = output_switch.glob.glob
    old_debug = output_switch.log.debug
    old_monotonic = output_switch.time.monotonic
    try:
        output_switch.glob.glob = lambda _pattern: []  # type: ignore[assignment]
        output_switch.log.debug = lambda msg, *args, **_kwargs: debug_messages.append(msg % args)  # type: ignore[assignment]
        output_switch.time.monotonic = lambda: now[0]  # type: ignore[assignment]
        writer = create_dynamic_write_fn(
            "/tmp/missing-hidg-for-auto-test",
            {},
            uinput_factory=lambda _cfg: uinput_reports.append,
        )
        writer(b"first")
        now[0] = 3.0
        writer(b"second")
        assert [
            msg for msg in debug_messages if msg.startswith("USB接続チェック:")
        ] == ["USB接続チェック: 切断 (現在モード: uinput)"]
    finally:
        output_switch.glob.glob = old_glob  # type: ignore[assignment]
        output_switch.log.debug = old_debug  # type: ignore[assignment]
        output_switch.time.monotonic = old_monotonic  # type: ignore[assignment]

    print("ok: output switch auto fallback order")


if __name__ == "__main__":
    main()
