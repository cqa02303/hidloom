"""アニメーションパッケージ

新しいアニメーションを追加するには:
  1. このディレクトリに新しいモジュールを作成し AnimationBase を継承する。
  2. 一意の ANIMATION_ID (int) を設定する。
  3. 下記のインポートリストと REGISTRY に追加する。
"""

from .base import AnimationBase
from .bounce import BounceAnimation
from .ripple import RippleAnimation

# アニメーション ID → クラスのレジストリ
REGISTRY: dict[int, type[AnimationBase]] = {
    cls.ANIMATION_ID: cls
    for cls in [BounceAnimation, RippleAnimation]
}

__all__ = [
    "AnimationBase",
    "BounceAnimation",
    "RippleAnimation",
    "REGISTRY",
]
