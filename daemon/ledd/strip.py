"""LED strip hardware adapter for ledd."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("ledd")

try:
    import rpi_ws281x as ws  # type: ignore
    from rpi_ws281x import Color, PixelStrip  # type: ignore

    HAS_HW = True
    logger.debug("rpi_ws281x ライブラリを使用")
except ImportError:
    logger.warning("rpi_ws281x が見つかりません。スタブモードで動作します（実際の LED は光りません）")
    HAS_HW = False

    class Color:  # type: ignore
        """rpi_ws281x.Color のスタブ"""

        def __new__(cls, r: int, g: int, b: int, w: int = 0) -> int:  # type: ignore[misc]
            return (w << 24) | (r << 16) | (g << 8) | b

    class _FakeWs:  # type: ignore
        SK6812_STRIP_GRB = 0x00081000
        WS2812_STRIP = 0x00081000

    ws = _FakeWs()  # type: ignore

    class PixelStrip:  # type: ignore
        """rpi_ws281x.PixelStrip のスタブ"""

        def __init__(self, num: int, pin: int, *args: Any, **kwargs: Any) -> None:
            self._num = num
            self._leds: list[int] = [0] * num

        def begin(self) -> None:
            pass

        def setPixelColor(self, n: int, color: int) -> None:
            if 0 <= n < self._num:
                self._leds[n] = color

        def show(self) -> None:
            pass

        def numPixels(self) -> int:
            return self._num


_STRIP_TYPE_MAP: dict[str, int] = {
    "GRB": getattr(ws, "SK6812_STRIP_GRB", 0x00081000),
    "RGB": getattr(ws, "WS2812_STRIP", 0x00081000),
    "BGR": getattr(ws, "SK6812_STRIP", 0x00081000),
}


def init_strip(config: dict[str, Any]) -> PixelStrip:
    """設定に基づいて LEDストリップを初期化して返す"""
    led_cfg = config["led"]
    color_order: str = led_cfg.get("color_order", "GRB").upper()
    strip_type = _STRIP_TYPE_MAP.get(color_order, _STRIP_TYPE_MAP["GRB"])

    strip = PixelStrip(
        len(config["leds"]),
        led_cfg["gpio_bcm"],
        800000,
        10,
        False,
        led_cfg.get("brightness", 128),
        0,
        strip_type,
    )
    strip.begin()
    return strip


def all_off(strip: PixelStrip, led_count: int) -> None:
    """全 LED を消灯する"""
    for i in range(led_count):
        strip.setPixelColor(i, Color(0, 0, 0))
    strip.show()
