"""往復アニメーション（デフォルト）

LED1番から最後まで光が行き来するバウンスアニメーション。
"""

import threading
import time
from typing import Any

from .base import AnimationBase

try:
    from rpi_ws281x import Color  # type: ignore
except ImportError:
    class Color:  # type: ignore
        def __new__(cls, r: int, g: int, b: int, w: int = 0) -> int:  # type: ignore[misc]
            return (w << 24) | (r << 16) | (g << 8) | b


class BounceAnimation(AnimationBase):
    """往復アニメーション。

    ヘッドの後ろにフェードアウトするテールを持つ光が LED を往復する。
    """

    ANIMATION_ID = 0
    ANIMATION_NAME = "bounce"

    def setup(self, config: dict[str, Any], led_positions: dict[str, dict]) -> None:
        anim_cfg = config.get("animation", {})
        self._fps: float = float(anim_cfg.get("fps", 30))
        self._color_r = 0
        self._color_g = 100
        self._color_b = 255
        self._tail_len = 5

    def run(self, strip: Any, led_count: int, stop_event: threading.Event) -> None:
        interval = 1.0 / self._fps
        pos = 0
        direction = 1

        while not stop_event.is_set():
            # 全 LED を消灯
            for i in range(led_count):
                strip.setPixelColor(i, Color(0, 0, 0))

            # テール（ヘッドの後方にフェードアウト）
            for t in range(1, self._tail_len + 1):
                tail_pos = pos - direction * t
                if 0 <= tail_pos < led_count:
                    factor = (self._tail_len - t + 1) / (self._tail_len + 1)
                    strip.setPixelColor(
                        tail_pos,
                        Color(
                            int(self._color_r * factor),
                            int(self._color_g * factor),
                            int(self._color_b * factor),
                        ),
                    )

            # ヘッド（最も明るい）
            strip.setPixelColor(pos, Color(self._color_r, self._color_g, self._color_b))
            strip.show()

            time.sleep(interval)

            # 次フレームの位置を計算
            pos += direction
            if pos >= led_count:
                pos = led_count - 2
                direction = -1
            elif pos < 0:
                pos = 1
                direction = 1
