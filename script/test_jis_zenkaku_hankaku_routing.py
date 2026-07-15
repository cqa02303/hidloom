#!/usr/bin/env python3
"""Regression tests for the distinct JIS Zenkaku/Hankaku routing action."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from logicd.config_runtime import _with_usb_split_keyboard_switch  # noqa: E402
from logicd.hid_report import HidState  # noqa: E402
from logicd.macro import MacroExecutor  # noqa: E402


async def _capture_macro_reports(action: str) -> list[bytes]:
    reports: list[bytes] = []
    executor = MacroExecutor(HidState(), reports.append, {})
    await executor.handle(action, True)
    await executor.handle(action, False)
    return reports


def _route_reports(reports: list[bytes]) -> tuple[list[bytes], list[bytes]]:
    jis_main: list[bytes] = []
    us_sub: list[bytes] = []
    writer = _with_usb_split_keyboard_switch(
        jis_main.append,
        us_sub.append,
        route="jis_special_us_default",
    )
    for report in reports:
        writer(report)
    return jis_main, us_sub


def test_jis_special_release_preserves_modifier_on_main() -> None:
    jis_main, us_sub = _route_reports([
        bytes([0x02, 0, 0, 0, 0, 0, 0, 0]),  # Shift down on US sub.
        bytes([0x02, 0, 0x87, 0, 0, 0, 0, 0]),  # Shift + KC_RO on JIS main.
        bytes([0x02, 0, 0, 0, 0, 0, 0, 0]),  # KC_RO release while Shift remains down.
        bytes(8),  # Shift release.
    ])

    assert jis_main == [
        bytes([0x02, 0, 0x87, 0, 0, 0, 0, 0]),
        bytes([0x02, 0, 0, 0, 0, 0, 0, 0]),
        bytes(8),
    ]
    assert us_sub == [
        bytes([0x02, 0, 0, 0, 0, 0, 0, 0]),
        bytes([0x02, 0, 0, 0, 0, 0, 0, 0]),
        bytes(8),
    ]


def test_jis_special_double_tap_with_held_modifier_releases_between_taps() -> None:
    jis_main, us_sub = _route_reports([
        bytes([0x02, 0, 0, 0, 0, 0, 0, 0]),  # Shift down on US sub.
        bytes([0x02, 0, 0x87, 0, 0, 0, 0, 0]),  # First Shift + KC_RO press.
        bytes([0x02, 0, 0, 0, 0, 0, 0, 0]),  # First KC_RO release.
        bytes([0x02, 0, 0x87, 0, 0, 0, 0, 0]),  # Second Shift + KC_RO press.
        bytes([0x02, 0, 0, 0, 0, 0, 0, 0]),  # Second KC_RO release.
        bytes(8),  # Shift release.
    ])

    assert jis_main == [
        bytes([0x02, 0, 0x87, 0, 0, 0, 0, 0]),
        bytes([0x02, 0, 0, 0, 0, 0, 0, 0]),
        bytes([0x02, 0, 0x87, 0, 0, 0, 0, 0]),
        bytes([0x02, 0, 0, 0, 0, 0, 0, 0]),
        bytes(8),
    ]
    assert us_sub == [
        bytes([0x02, 0, 0, 0, 0, 0, 0, 0]),
        bytes([0x02, 0, 0, 0, 0, 0, 0, 0]),
        bytes([0x02, 0, 0, 0, 0, 0, 0, 0]),
        bytes(8),
    ]


async def main_async() -> None:
    grave_reports = await _capture_macro_reports("KC_GRV")
    zkhk_reports = await _capture_macro_reports("KC_ZKHK")

    assert grave_reports == [
        bytes([0, 0, 0x35, 0, 0, 0, 0, 0]),
        bytes(8),
    ]
    assert zkhk_reports == [
        bytes([0, 0x5A, 0x35, 0, 0, 0, 0, 0]),
        bytes(8),
    ]

    grave_jis_main, grave_us_sub = _route_reports(grave_reports)
    zkhk_jis_main, zkhk_us_sub = _route_reports(zkhk_reports)

    assert grave_jis_main == []
    assert grave_us_sub == [
        bytes([0, 0, 0x35, 0, 0, 0, 0, 0]),
        bytes(8),
    ]
    assert zkhk_jis_main == [
        bytes([0, 0, 0x35, 0, 0, 0, 0, 0]),
        bytes(8),
    ]
    assert zkhk_us_sub == []


def main() -> None:
    test_jis_special_release_preserves_modifier_on_main()
    test_jis_special_double_tap_with_held_modifier_releases_between_taps()
    asyncio.run(main_async())
    print("ok: KC_ZKHK routes as JIS-main Zenkaku/Hankaku without changing KC_GRV")


if __name__ == "__main__":
    main()
