# LED Life Game effect

更新日: 2026-05-30

キー入力を seed にして LED 盤面へ Conway-style のセルを発生させる
push-trigger effect です。初期実装では VialRGB mode `1001`
(`LED Life Game`) として扱います。

## 方針

- renderer の中心ロジックは `daemon/ledd/life_game.py` に副作用なしで分離する。
- PCB 座標 (`config/default/ledd.json` の `leds`) は、行ごとの x 順へ変換し、
  row-stagger に沿う neighbor graph として扱う。同一行は左右、上下行は x が揃っている時だけ
  真上/真下と左右をつなぎ、半キーずれている時は近い斜めだけをつなぐ。
- key press では該当 LED 1 セルだけを pending seed として queue し、renderer thread を起こす。
  描画は renderer thread に一本化し、key event handler 側から途中 frame を直接 `show()` しない。
  pending seed は次 tick で正式に born へ移す。周辺セルは同時に生やさず、
  その次の tick 以降の Life Game rule でだけ増減させる。
- step ごとに Conway の birth/survival を計算し、消えた cell は intensity decay で短く残光する。
- 死亡判定された cell は赤のまま fade-out 表示し、次 tick へ赤残光を持ち越さず、
  1 tick 内を8段階に分けて明るさを落とす。pending / 生誕 cell は暗めから通常 alive 輝度へ短く fade-in し、
  生誕 cell に隣接して生誕へ関与した cell は 1 turn ピンクで表示する。死亡 marker はピンクより優先する。
- 全セル死亡後の idle 色は、空セルと同じ `(h + 44) % 256` の低輝度色に揃える。
  `h=100` の実機確認では黄緑ではなく青寄りへ戻る。
- debug 中は OLED alert に `Life #N` と alive cell 数を tick ごとに表示する。
  `LEDD_LIFE_GAME_OLED_DEBUG=0` で無効化できる。
- `speed` は tick 間隔の調整に使う。Life Game は見え方優先のため、
  ほかの reactive / splash effect よりかなり遅くし、約 0.8-5.4 tick/sec に抑える。
  `h/s/v` は発光色と明るさに使う。
- semantic overlay は既存の `_show_with_state_overlays()` を通すため、layer / lock overlay と重ねられる。

## 境界

- host へキー入力を追加で送らない。既存の `ledd` key event を視覚効果の seed として読むだけ。
- direct-frame producer が active の時は direct-frame を優先する。
- `reactive.exclude_roles` の対象キーは seed しない。modifier / layer / lock を除外する既定方針と揃える。
- Life Game の pattern editor はまだ作らない。まずは fixed rule の実機見え方を確認する。

## 実装

- `vialrgb_effects.py`
  - mode `1001`: `LED Life Game`
  - category: `experimental`
  - render group: `life_game`
- `daemon/ledd/life_game.py`
  - `cells_from_led_positions()`
  - row-stagger-aware neighbor graph
  - `LedLifeGameState.seed_index()`
  - `LedLifeGameState.step()`
  - `LedLifeGameState.frame()`
  - `LedLifeGameState.transition_frame()`
  - `LedLifeGameState.transition_intensity_frame()`
  - `LedLifeGameState.tick_count`
- `daemon/ledd/vialrgb_runtime.py`
  - mode `1001` で `_run_vialrgb_life_game` thread を開始する。
- `daemon/ledd/vialrgb_reactive_renderers.py`
  - active cell frame を HSV color として描画する。
- `daemon/ledd/ledd.py`
  - key press から active LED index だけを pending seed にし、renderer thread を wake する。

## 受け入れ条件

- [x] Life Game state は LED hardware なしで単体テストできる。
- [x] mode `1001` が HTTP Lighting metadata に出る。
- [x] key press で LED frame が idle から変化する。
- [x] key press の seed は LED 1 セル単位で pending 表示し、次 tick で born に移して即時死亡を避ける。
- [x] 死亡 cell は赤のまま fade-out、生誕へ関与した cell はピンクで 1 turn 表示する。
- [x] debug 用に OLED へ tick counter / alive count を表示する。
- [x] row-stagger に沿う斜め neighbor で上下行を接続する。
- [x] key press の seed は renderer thread 側に一本化し、死亡 fade 途中の割り込み描画を避ける。
- [x] semantic overlay とは既存の `_show_with_state_overlays()` 経路で混ざる。
- [x] `<keyboard-host>` 実機で seed / decay / FPS / 全滅 idle 色を目視確認する。
- [x] 実機確認はいったん完了扱いにし、長時間観測または pattern editor は Wishlist / follow-up 候補へ戻す。
