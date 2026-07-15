"""波紋アニメーション

キーを押した物理座標を起点に円形の波紋が全 LED に広がる。
波紋が重なった場合は加算合成する。
"""

import math
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


class RippleAnimation(AnimationBase):
    """波紋アニメーション。

    キーを押した位置を起点に円形の波紋が広がる。
    複数キー同時押しの波紋は加算合成される。
    """

    ANIMATION_ID = 1
    ANIMATION_NAME = "ripple"

    def setup(self, config: dict[str, Any], led_positions: dict[str, dict]) -> None:
        anim_cfg = config.get("animation", {})
        self._fps: float = float(anim_cfg.get("fps", 30))

        # LED 物理座標（配線順）
        self._led_positions = led_positions

        # 波紋リストとロック
        self._lock = threading.Lock()
        self._ripples: list[dict] = []

        # 波紋パラメータ
        self._speed: float = 250.0       # 波の伝播速度 [mm/秒]
        self._wave_width: float = 20.0  # 波の幅 [mm]
        self._decay_rate: float = 2.0   # 減衰率（値が大きいほど速く減衰）
        self._max_radius: float = self._calc_max_radius()

    def _calc_max_radius(self) -> float:
        """全 LED をカバーする最大伝播半径を計算する"""
        if not self._led_positions:
            return 300.0
        xs = [v["x"] for v in self._led_positions.values()]
        ys = [v["y"] for v in self._led_positions.values()]
        w = max(xs) - min(xs)
        h = max(ys) - min(ys)
        return math.sqrt(w ** 2 + h ** 2)

    def on_key_event(
        self,
        row: int,
        col: int,
        is_press: bool,
        led_pos: tuple[float, float] | None,
    ) -> None:
        # 押下時のみ波紋を生成。対応 LED がないキーは無視
        if not is_press or led_pos is None:
            return
        cx, cy = led_pos
        with self._lock:
            self._ripples.append({
                "cx": cx,
                "cy": cy,
                "radius": 0.0,
                "color": (80, 80, 255),  # 水色
            })

    def run(self, strip: Any, led_count: int, stop_event: threading.Event) -> None:
        interval = 1.0 / self._fps

        # 配線順の座標リストを事前計算
        keys = list(self._led_positions.keys())
        coords = [
            (self._led_positions[k]["x"], self._led_positions[k]["y"])
            for k in keys[:led_count]
        ]
        n = min(led_count, len(coords))

        while not stop_event.is_set():
            t_start = time.monotonic()
            # 各 LED の RGB 寄与を加算合成するための配列
            rgb = [[0.0, 0.0, 0.0] for _ in range(n)]

            with self._lock:
                next_ripples = []
                for rp in self._ripples:
                    r = rp["radius"]
                    cr, cg, cb = rp["color"]
                    # 距離に応じた減衰係数を計算（指数関数的に減衰）
                    decay = math.exp(-self._decay_rate * r / self._max_radius)
                    # 各 LED の RGB 輝度に波紋の寄与を加算
                    for i in range(n):
                        lx, ly = coords[i]
                        dist = math.sqrt((lx - rp["cx"]) ** 2 + (ly - rp["cy"]) ** 2)
                        diff = abs(dist - r)
                        if diff < self._wave_width:
                            # 波の形状係数と減衰を掛け合わせる
                            factor = (1.0 - diff / self._wave_width) ** 2 * decay
                            rgb[i][0] = min(255.0, rgb[i][0] + cr * factor)
                            rgb[i][1] = min(255.0, rgb[i][1] + cg * factor)
                            rgb[i][2] = min(255.0, rgb[i][2] + cb * factor)
                    # 半径を更新し、最大半径を超えたものを除去
                    rp["radius"] += self._speed * interval
                    if rp["radius"] <= self._max_radius:
                        next_ripples.append(rp)
                self._ripples = next_ripples

            # LED に色を書き込む
            for i, (r, g, b) in enumerate(rgb):
                strip.setPixelColor(i, Color(int(r), int(g), int(b)))
            strip.show()

            elapsed = time.monotonic() - t_start
            wait = interval - elapsed
            if wait > 0:
                time.sleep(wait)
