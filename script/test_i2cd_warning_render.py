#!/usr/bin/env python3
"""Smoke-test i2cd alert and warning render polarity."""
from __future__ import annotations

import sys
import types
from contextlib import contextmanager
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
        self.rectangles: list[dict] = []
        self.texts: list[dict] = []

    def rectangle(self, xy, outline=None, fill=None) -> None:
        self.rectangles.append({"xy": xy, "outline": outline, "fill": fill})

    def text(self, xy, text, font=None, fill=None) -> None:
        self.texts.append({"xy": xy, "text": text, "fill": fill})


class FakeFont:
    def getlength(self, text: str) -> int:
        return len(text) * 6

    def getmetrics(self) -> tuple[int, int]:
        return (10, 2)


def main() -> None:
    draws: list[FakeDraw] = []

    @contextmanager
    def fake_canvas(_device):
        draw = FakeDraw()
        draws.append(draw)
        yield draw

    old_canvas = i2cd.canvas
    try:
        i2cd.canvas = fake_canvas  # type: ignore[assignment]
        i2cd._draw_alert(FakeDevice(), FakeFont(), "normal")
        i2cd._draw_alert(FakeDevice(), FakeFont(), "warn", inverted=True)
        i2cd._draw_shutdown(FakeDevice(), FakeFont())
    finally:
        i2cd.canvas = old_canvas  # type: ignore[assignment]

    assert draws[0].rectangles[0]["fill"] == "black"
    assert draws[0].texts[0]["fill"] == "white"
    assert draws[1].rectangles[0]["fill"] == "white"
    assert draws[1].texts[0]["fill"] == "black"
    assert draws[2].rectangles[0]["fill"] == "white"
    assert draws[2].texts[0]["fill"] == "black"
    assert draws[2].texts[0]["text"] == "shutdown"

    print("ok: i2cd warning render uses inverted polarity")


if __name__ == "__main__":
    main()
