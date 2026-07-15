# daemon/ledd/animations — アニメーションモジュール

`ledd` デーモンに読み込まれる LED アニメーションを管理するパッケージです。
アニメーションは整数の **ANIMATION_ID** で識別され、実行中でも動的に切り替えられます。

---

## 組み込みアニメーション一覧

| ID | 名前 | ファイル | 説明 |
|----|------|----------|------|
| 0 | `bounce` | `bounce.py` | LED を往復する光（デフォルト） |
| 1 | `ripple` | `ripple.py` | キーを押した位置から広がる波紋 |

---

## 新しいアニメーションの作成方法

### 1. ファイルを作成する

`daemon/ledd/animations/` 以下に新しい `.py` ファイルを作成します。
`AnimationBase` を継承し、以下の属性・メソッドを実装してください。

```python
# daemon/ledd/animations/my_anim.py
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


class MyAnimation(AnimationBase):
    # ★ 他のアニメーションと重複しない整数を設定する
    ANIMATION_ID = 2
    ANIMATION_NAME = "my_anim"

    def setup(self, config: dict[str, Any], led_positions: dict[str, dict]) -> None:
        """初期化処理（オプション）。
        config    : ledd.json 全体の辞書
        led_positions : {"行,列": {"x": float, "y": float}} 配線順
        """
        anim_cfg = config.get("animation", {})
        self._fps = float(anim_cfg.get("fps", 30))

    def on_key_event(
        self,
        row: int,
        col: int,
        is_press: bool,
        led_pos: tuple[float, float] | None,
    ) -> None:
        """キーイベントを受け取る（オプション）。
        led_pos : 対応 LED の物理座標 (x, y) [mm]。LED がないキーは None。
        """
        if is_press and led_pos is not None:
            pass  # 押されたキーの座標を使って何か処理する

    def run(self, strip: Any, led_count: int, stop_event: threading.Event) -> None:
        """★ 必須。アニメーションのメインループ。
        stop_event.is_set() が True になったら速やかに return すること。
        """
        interval = 1.0 / self._fps
        while not stop_event.is_set():
            for i in range(led_count):
                strip.setPixelColor(i, Color(255, 0, 0))
            strip.show()
            time.sleep(interval)
```

### 2. `__init__.py` に登録する

`daemon/ledd/animations/__init__.py` の `REGISTRY` リストに追加します。

```python
from .base import AnimationBase
from .bounce import BounceAnimation
from .ripple import RippleAnimation
from .my_anim import MyAnimation          # ← 追加

REGISTRY: dict[int, type[AnimationBase]] = {
    cls.ANIMATION_ID: cls
    for cls in [BounceAnimation, RippleAnimation, MyAnimation]  # ← 追加
}
```

---

## アニメーションの指定方法

### デフォルトアニメーションの設定

`config/default/ledd.json` の `animation.default_id` に ID を指定します。

```json
{
  "animation": {
    "fps": 16,
    "default_id": 1
  }
}
```

`ledd` 起動時に指定した ID のアニメーションが自動的に開始されます。

---

### キー操作でアニメーションを切り替える

`config/default/config.json`（logicd のキーマップ）で任意のキーに `ANIM(N)` アクションを設定します。
そのキーを押すと即座にアニメーション N に切り替わります。

```json
{
  "layers": [
    {
      "keys": {
        "0,1": "ANIM(0)",
        "0,2": "ANIM(1)"
      }
    }
  ]
}
```

---

### ソケット経由で切り替える（外部プログラムから）

`/tmp/ledd_events.sock` に JSON Lines 形式でメッセージを送信します。

```bash
echo '{"t": "anim", "id": 1}' | nc -U /tmp/ledd_events.sock
```

```python
import socket, json

with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
    s.connect("/tmp/ledd_events.sock")
    s.sendall((json.dumps({"t": "anim", "id": 1}) + "\n").encode())
```

---

## AnimationBase のインタフェース仕様

| メソッド | 必須 | 説明 |
|----------|------|------|
| `setup(config, led_positions)` | 任意 | 起動時の初期化。設定読み取りや座標計算はここで行う |
| `on_key_event(row, col, is_press, led_pos)` | 任意 | キー押下・離放イベント。波紋など起点が必要なアニメーションで使用 |
| `run(strip, led_count, stop_event)` | **必須** | メインループ。`stop_event` を必ず監視すること |

### `led_positions` の構造

`ledd.json` の `leds` セクションの内容がそのまま渡されます。
キーは `"行番号,列番号"` 文字列、値は物理座標 (mm) です。

```python
{
    "4,9": {"x": 223.8375, "y": 184.2893},
    "5,9": {"x": 242.8875, "y": 193.8143},
    ...
}
```

JSON の記述順 = LED の配線順です。`run()` の `i` 番目の LED はこの順序に対応します。

### `strip` オブジェクト

`rpi_ws281x.PixelStrip` のインスタンスです。使用するメソッド:

```python
strip.setPixelColor(i, Color(r, g, b))  # i 番目の LED に色をセット
strip.show()                            # 全 LED に反映（まとめて呼ぶ）
```
