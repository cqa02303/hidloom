#!/usr/bin/env python3
"""全LEDを赤く点灯させるシャットダウン用スクリプト

systemdのシャットダウンシーケンスから呼び出され、
全LEDを赤色で点灯させる。
"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

# ロギング設定
_LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ledd-shutdown")

# WS2812B / SK6812 ライブラリのインポート（未インストール時はスタブで代替）
try:
    import rpi_ws281x as ws  # type: ignore
    from rpi_ws281x import Color, PixelStrip  # type: ignore

    _HAS_HW = True
    logger.debug("rpi_ws281x ライブラリを使用")
except ImportError:
    logger.warning("rpi_ws281x が見つかりません。スタブモードで動作します（実際の LED は光りません）")
    _HAS_HW = False

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


# 設定ファイルのパス
_BASE_DIR = Path(__file__).resolve().parents[2]
from hidloom_paths import default_config_file
_CONFIG_PATH = default_config_file("ledd.json", _BASE_DIR)

_HELP = f"""usage: python3 -m ledd.shutdown

Set all LEDs to the shutdown indicator color.

Options:
  -h, --help    show this help and exit

Configuration:
  default config path: {_CONFIG_PATH}

Environment:
  LOG_LEVEL
"""


def load_config(path: Path) -> dict[str, Any]:
    """設定ファイルを読み込んで返す"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def init_strip(config: dict[str, Any]) -> PixelStrip:
    """設定に基づいて LEDストリップを初期化して返す"""
    led_count = len(config["leds"])
    led_cfg = config["led"]
    strip = PixelStrip(
        led_count,
        led_cfg.get("gpio_bcm", 12),
        800000,          # 周波数 (Hz)
        10,              # DMAチャンネル
        False,           # 信号反転なし
        led_cfg.get("brightness", 128),
        0,               # チャンネル
    )
    strip.begin()
    return strip


def all_red(strip: PixelStrip, led_count: int) -> None:
    """全 LED を赤色で点灯する"""
    for i in range(led_count):
        strip.setPixelColor(i, Color(255, 0, 0))
    strip.show()


def main() -> None:
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        print(_HELP.rstrip())
        return

    logger.info("shutdown")

    try:
        config = load_config(_CONFIG_PATH)
    except FileNotFoundError:
        logger.error("設定ファイルが見つかりません: %s", _CONFIG_PATH)
        sys.exit(1)

    try:
        strip = init_strip(config)
        led_count = len(config["leds"])
        logger.info("全 LED を赤色で点灯 (LED数: %d)", led_count)
        all_red(strip, led_count)
    except Exception as e:
        logger.error("LEDの制御に失敗: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
