#!/usr/bin/env python3
"""Regression tests for OLED direct-frame FPS display."""
from __future__ import annotations

import json
import sys
import tempfile
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


class FakeDevice:
    width = 64
    height = 128


class FakeDraw:
    def __init__(self) -> None:
        self.texts: list[str] = []
        self.text_positions: list[tuple[str, tuple[int, int]]] = []
        self.points: list[tuple[tuple[int, int], str]] = []
        self.rectangles: list[dict] = []
        self.lines: list[dict] = []

    def rectangle(self, *args, **kwargs) -> None:
        self.rectangles.append({"args": args, "kwargs": kwargs})

    def line(self, *args, **kwargs) -> None:
        self.lines.append({"args": args, "kwargs": kwargs})

    def point(self, pos, **kwargs) -> None:
        self.points.append((pos, kwargs.get("fill", "")))

    def text(self, pos, text, **_kwargs) -> None:
        self.texts.append(str(text))
        self.text_positions.append((str(text), pos))


class FakeCanvas:
    def __init__(self, draw: FakeDraw) -> None:
        self.draw = draw

    def __enter__(self) -> FakeDraw:
        return self.draw

    def __exit__(self, *_exc) -> None:
        return None


class FakeFont:
    def getbbox(self, text: str):
        return (0, 0, len(text) * 6, 8)


def write_status(path: Path, *, active: bool, applied: int, updated_at: float) -> None:
    path.write_text(
        json.dumps({
            "direct_frame_active": active,
            "applied_frames": applied,
            "updated_at": updated_at,
        }),
        encoding="utf-8",
    )


def test_fps_monitor() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        status = Path(tmp) / "status.json"
        monitor = i2cd._DirectFrameFpsMonitor(str(status))
        assert monitor.label() == ""

        write_status(status, active=True, applied=10, updated_at=100.0)
        assert monitor.label() == "FPS:--"

        write_status(status, active=True, applied=34, updated_at=101.0)
        assert monitor.label() == "FPS:24.0"

        write_status(status, active=False, applied=34, updated_at=102.0)
        assert monitor.label() == ""


def test_ready_display_includes_fps_line() -> None:
    draw = FakeDraw()
    old_canvas = i2cd.canvas
    old_hostname = i2cd._HOSTNAME
    try:
        i2cd.canvas = lambda _device: FakeCanvas(draw)  # type: ignore[assignment]
        i2cd._HOSTNAME = "hidloom"
        i2cd._draw_ready(
            FakeDevice(),
            FakeFont(),
            layer=0,
            active=[0],
            matrixd_ok=True,
            logicd_ok=True,
            current_mode="auto:gadget",
            fps_label="FPS:24.0",
            system_status={"cpu_percent": 12, "cpu_temp": 52.0},
        )
    finally:
        i2cd._HOSTNAME = old_hostname
        i2cd.canvas = old_canvas  # type: ignore[assignment]

    assert "T:52 C" in draw.texts
    assert "FPS:24.0" in draw.texts
    assert not any(text.startswith("mtx:") or text.startswith("lgc:") for text in draw.texts)
    assert draw.points
    assert any(rect["kwargs"].get("fill") == "white" for rect in draw.rectangles)
    assert len(draw.lines) >= 4
    assert [(1, 33), (62, 33)] in [line["args"][0] for line in draw.lines]
    assert [(1, 34), (62, 34)] in [line["args"][0] for line in draw.lines]
    assert "  " in draw.texts[-1]
    white_rects = [rect for rect in draw.rectangles if rect["kwargs"].get("fill") == "white"]
    white_tops = sorted(rect["args"][0][0][1] for rect in white_rects)
    assert white_tops.count(18) >= 2
    assert white_tops.count(36) == 2
    daemon_bottom = max(rect["args"][0][1][1] for rect in white_rects if rect["args"][0][0][1] == 18)
    layer_y = next(pos[1] for text, pos in draw.text_positions if text == "Layer: 0")
    assert layer_y > daemon_bottom


def test_ready_display_hides_inactive_fps_line() -> None:
    draw = FakeDraw()
    old_canvas = i2cd.canvas
    old_hostname = i2cd._HOSTNAME
    try:
        i2cd.canvas = lambda _device: FakeCanvas(draw)  # type: ignore[assignment]
        i2cd._HOSTNAME = "hidloom"
        i2cd._draw_ready(
            FakeDevice(),
            FakeFont(),
            layer=0,
            active=[0],
            matrixd_ok=True,
            logicd_ok=True,
            current_mode="auto:gadget",
            fps_label="",
            system_status={"cpu_percent": 12, "cpu_temp": 52.0},
        )
    finally:
        i2cd._HOSTNAME = old_hostname
        i2cd.canvas = old_canvas  # type: ignore[assignment]

    assert "T:52 C" in draw.texts
    assert not any(text.startswith("FPS:") for text in draw.texts)


def test_boot_display_uses_daemon_icons() -> None:
    draw = FakeDraw()
    old_canvas = i2cd.canvas
    try:
        i2cd.canvas = lambda _device: FakeCanvas(draw)  # type: ignore[assignment]
        i2cd._draw_boot(FakeDevice(), FakeFont(), matrixd_ok=True, logicd_ok=False)
    finally:
        i2cd.canvas = old_canvas  # type: ignore[assignment]

    assert "Booting..." in draw.texts
    assert not any(text.startswith("matrix ") or text.startswith("logicd ") for text in draw.texts)
    assert draw.points
    assert any(rect["kwargs"].get("fill") == "white" for rect in draw.rectangles)
    assert any(fill == "black" for _pos, fill in draw.points)
    daemon_bottom = max(rect["args"][0][1][1] for rect in draw.rectangles if rect["kwargs"].get("fill") == "white")
    booting_y = next(pos[1] for text, pos in draw.text_positions if text == "Booting...")
    assert booting_y > daemon_bottom


def test_long_node_name_wraps_to_two_lines() -> None:
    draw = FakeDraw()
    old_canvas = i2cd.canvas
    old_hostname = i2cd._HOSTNAME
    try:
        i2cd.canvas = lambda _device: FakeCanvas(draw)  # type: ignore[assignment]
        i2cd._HOSTNAME = "keyboard-02"
        i2cd._draw_ready(
            FakeDevice(),
            FakeFont(),
            layer=0,
            active=[0],
            matrixd_ok=True,
            logicd_ok=True,
            current_mode="auto:gadget",
            fps_label="",
            system_status={"cpu_percent": 12, "cpu_temp": 52.0},
        )
    finally:
        i2cd._HOSTNAME = old_hostname
        i2cd.canvas = old_canvas  # type: ignore[assignment]

    node_lines = [text for text, pos in draw.text_positions if pos[0] == 3 and pos[1] in {3, 13}]
    assert node_lines == ["keyboard", "-02"]
    assert all(FakeFont().getbbox(text)[2] <= 58 for text in node_lines)
    top_separator = draw.lines[0]["args"][0]
    assert top_separator == [(1, 25), (62, 25)]


def main() -> None:
    test_fps_monitor()
    test_ready_display_includes_fps_line()
    test_ready_display_hides_inactive_fps_line()
    test_boot_display_uses_daemon_icons()
    test_long_node_name_wraps_to_two_lines()
    print("ok: i2cd direct-frame FPS display")


if __name__ == "__main__":
    main()
