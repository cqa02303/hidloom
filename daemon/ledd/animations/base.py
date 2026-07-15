"""アニメーション基底クラス"""

import threading
from abc import ABC, abstractmethod
from typing import Any


class AnimationBase(ABC):
    """LED アニメーションの基底クラス。

    全アニメーションはこのクラスを継承し、ANIMATION_ID と ANIMATION_NAME を設定する。
    """

    ANIMATION_ID: int = -1
    ANIMATION_NAME: str = "unknown"

    def setup(self, config: dict[str, Any], led_positions: dict[str, dict]) -> None:
        """アニメーション開始前の初期化処理（オプション）。

        Args:
            config: ledd.json 全体の設定辞書。
            led_positions: LED 位置マップ {"行,列": {"x": float, "y": float}}。
                           JSON 記述順 = 配線順。
        """

    def on_key_event(
        self,
        row: int,
        col: int,
        is_press: bool,
        led_pos: tuple[float, float] | None,
    ) -> None:
        """キーイベントを受け取る（オプション）。

        Args:
            row: キーの行番号。
            col: キーの列番号。
            is_press: True=押下, False=離放。
            led_pos: キーに対応する LED の物理座標 (x, y) [mm]。
                     対応 LED がない場合は None。
        """

    @abstractmethod
    def run(self, strip: Any, led_count: int, stop_event: threading.Event) -> None:
        """アニメーションのメインループ。

        stop_event がセットされたら速やかに終了すること。

        Args:
            strip: PixelStrip インスタンス。
            led_count: LED の総数。
            stop_event: 停止シグナル。
        """
        ...
