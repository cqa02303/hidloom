#!/usr/bin/env python3
"""Regression tests for OLED output mode connectivity icon row."""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

if "luma" not in sys.modules:
    class DeviceNotFoundError(Exception):
        pass

    sys.modules["luma"] = types.ModuleType("luma")
    sys.modules["luma.core"] = types.ModuleType("luma.core")
    sys.modules["luma.core.interface"] = types.ModuleType("luma.core.interface")
    sys.modules["luma.core.interface.serial"] = types.SimpleNamespace(i2c=lambda *a, **kw: object())
    sys.modules["luma.core.render"] = types.SimpleNamespace(canvas=lambda *a, **kw: None)
    sys.modules["luma.core.error"] = types.SimpleNamespace(DeviceNotFoundError=DeviceNotFoundError)
    sys.modules["luma.oled"] = types.ModuleType("luma.oled")
    sys.modules["luma.oled.device"] = types.SimpleNamespace(sh1107=lambda *a, **kw: object())

from i2cd import i2cd  # noqa: E402


class FakeDraw:
    def __init__(self) -> None:
        self.texts: list[str] = []
        self.points: list[tuple[tuple[int, int], str]] = []
        self.rectangles: list[dict] = []

    def text(self, _pos, text, **_kwargs) -> None:
        self.texts.append(str(text))

    def point(self, pos, **kwargs) -> None:
        self.points.append((pos, kwargs.get("fill", "")))

    def rectangle(self, *args, **kwargs) -> None:
        self.rectangles.append({"args": args, "kwargs": kwargs})


class FakeFont:
    def getbbox(self, text: str):
        return (0, 0, len(text) * 6, 8)


def _draw(mode: str, wifi: dict | None = None) -> FakeDraw:
    draw = FakeDraw()
    i2cd._draw_output_mode(draw, FakeFont(), 0, 1, mode, wifi)
    return draw


def main() -> None:
    assert i2cd._output_mode_icon_row("") == []
    assert i2cd._output_mode_icon_row("off") == []
    assert i2cd._output_mode_icon_row("gadget") == [("usb", True)]
    assert i2cd._output_mode_icon_row("bt") == [("bt", True)]
    assert i2cd._output_mode_icon_row("uinput") == [("pi", True)]
    assert i2cd._output_mode_icon_row("auto:gadget") == [("auto", True), ("usb", True)]
    assert i2cd._output_mode_icon_row("auto:bt") == [("auto", True), ("bt", True)]
    assert i2cd._output_mode_icon_row("auto:uinput") == [("auto", True), ("pi", True)]
    assert i2cd._output_mode_icon_row("uinput", daemon_status={"hidd": True}) == [("pi", True)]
    assert i2cd._output_mode_icon_row("auto:uinput", daemon_status={"hidd": True}) == [
        ("auto", True),
        ("pi", True),
    ]
    assert i2cd._output_mode_icon_row("debug", daemon_status={"hidd": True}) == [("usb", True)]
    assert i2cd._output_mode_icon_row("gadget", {"available": True, "powered": True, "connected": True}) == [
        ("usb", True),
        ("wifi3", True),
    ]
    statuses = {
        "matrixd": True,
        "logicd": False,
        "ledd": True,
        "btd": False,
        "httpd": True,
        "hidd": True,
        "viald": False,
    }
    assert i2cd._daemon_status_icon_row(statuses) == [
        ("mtx", True),
        ("core", False),
        ("cmp", False),
        ("out", False),
        ("uid", False),
        ("led", True),
        ("btd", False),
        ("web", True),
        ("hid", True),
        ("vial", False),
    ]
    native_statuses = dict(statuses)
    native_statuses.update({
        "logicd-core": True,
        "logicd-companion": True,
        "outputd": True,
        "uidd": True,
    })
    assert i2cd._daemon_status_icon_row(native_statuses)[:5] == [
        ("mtx", True),
        ("core", True),
        ("cmp", True),
        ("out", True),
        ("uid", True),
    ]
    legacy_statuses = dict(statuses)
    legacy_statuses.pop("hidd")
    legacy_statuses["usbd"] = True
    assert ("hid", True) in i2cd._daemon_status_icon_row(legacy_statuses)
    daemon_rows = i2cd._daemon_status_icon_rows(native_statuses)
    assert [len(row) for row in daemon_rows] == [5, 5]
    assert all(i2cd._icon_row_width(row) <= 58 for row in daemon_rows)

    for mode in ["gadget", "bt", "uinput", "auto:gadget", "auto:bt", "auto:uinput"]:
        draw = _draw(mode)
        assert draw.texts == [], mode
        assert draw.points, mode
        assert any(rect["kwargs"].get("fill") == "white" for rect in draw.rectangles), mode
        assert any(fill == "black" for _pos, fill in draw.points), mode

    draw = _draw("gadget", {"available": True, "powered": True, "connected": False})
    assert draw.texts == []
    assert draw.points
    assert any(fill == "white" for _pos, fill in draw.points)

    draw = _draw("unknown")
    assert draw.texts == ["unknown"]
    assert not draw.points

    draw = FakeDraw()
    height = i2cd._draw_daemon_status_row(draw, 0, 1, statuses)
    expected_height = sum(
        max(
            i2cd._icon_vertical_bounds(i2cd.icon_bitmap(icon_name))[1]
            - i2cd._icon_vertical_bounds(i2cd.icon_bitmap(icon_name))[0]
            for icon_name, _active in row
        ) + 1
        for row in daemon_rows
    )
    assert height == expected_height
    assert draw.texts == []
    assert draw.points
    assert any(rect["kwargs"].get("fill") == "white" for rect in draw.rectangles)
    assert any(fill == "black" for _pos, fill in draw.points)
    assert any(fill == "white" for _pos, fill in draw.points)
    daemon_rects = [rect for rect in draw.rectangles if rect["kwargs"].get("fill") == "white"]
    assert len(daemon_rects) == 4
    assert max(rect["args"][0][1][1] for rect in daemon_rects) < 1 + height

    source = (ROOT / "daemon" / "i2cd" / "i2cd.py").read_text(encoding="utf-8")
    connectivity = (ROOT / "daemon" / "i2cd" / "connectivity.py").read_text(encoding="utf-8")
    assert "icon_bitmap" in source
    assert "draw_icon_pixels" in source
    assert "output_mode_icon_row" in source
    assert "_wifi_status_loop" in source
    assert "wifi_status(max_age_sec=0.0)" in source
    assert "status_snapshots.get(\"wifi\", {})" in source
    assert "_draw_daemon_status_row" in source
    assert "_draw_node_name" in source
    assert 'msg.get("t") == "daemon_status"' in source
    assert "mtx:{" not in source
    assert "off/unavailable icons" in connectivity
    print("ok: i2cd output mode icon row is display-friendly")


if __name__ == "__main__":
    main()
