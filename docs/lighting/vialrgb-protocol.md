# VialRGB 制御プロトコル設計

## 目的

VialRGB を既存の `ledd` アニメーション基盤へ統合するため、
`viald -> logicd -> ledd` 間の責務とメッセージ形式を定義する。

この文書は Vial Raw HID の外部仕様そのものではなく、
VialRGB コマンドを本プロジェクト内部でどう表現するかを定める内部仕様である。
upstream 未確認の項目は [research/vialrgb-upstream.md](../research/vialrgb-upstream.md) に分離する。

## 基本方針

- `viald` は VialRGB コマンドを内部 LED コマンドへ翻訳する。
- `logicd` は LED 状態の正本と中継を担う。
- `ledd` は描画とアニメーション実行だけを担う。
- `viald` から `ledd` へは直結しない。
- 既存の `ANIM(N)` 方式は残し、VialRGB 制御を上位互換として追加する。

```text
Vial GUI
  -> viald
  -> /tmp/ctrl_events.sock
  -> logicd
  -> /tmp/ledd_events.sock
  -> ledd
```

## 役割分担

| 要素 | 担当 |
|---|---|
| `viald` | VialRGB 外部コマンドを内部 LED コマンドへ変換 |
| `logicd` | LED 状態の正本、状態ブロードキャスト |
| `ledd` | effect 実行、parameter 反映、direct frame 描画 |

## VialRGB 機能の内部分類

VialRGB で扱う機能は、内部では次の 3 種へ分ける。

| 分類 | 説明 |
|---|---|
| effect selection | どのアニメーションを実行するか |
| effect parameters | brightness / speed / color など |
| direct control | ホストから渡された RGB frame をそのまま表示 |

## `ctrl_events.sock` 追加 API

`viald` から `logicd` へ送る内部 API。

### 1. effect selection

```json
{"t":"LED","op":"select","vial_effect":3}
```

または、Vial が名前管理であることが確認された場合:

```json
{"t":"LED","op":"select","vial_effect":"solid"}
```

#### フィールド

| フィールド | 型 | 説明 |
|---|---|---|
| `t` | `"LED"` | LED 制御 |
| `op` | `"select"` | effect 選択 |
| `vial_effect` | `int` or `string` | Vial/VialRGB が外部仕様で使う effect 識別子 |

effect 識別子は、Vial/VialRGB の upstream 実装で使われている表現をそのまま正とする。
Vial が番号管理なら番号を、名前管理なら名前を採用する。
独自 effect は Vial が使っていない識別子空間へ追加する。

### 2. global setting

```json
{"t":"LED","op":"global","name":"brightness","value":128}
```

#### 初期対応 global setting

| name | value | 範囲 / 形式 |
|---|---|---|
| `brightness` | `int` | `0..255` |

### 3. effect parameter

```json
{"t":"LED","op":"param","name":"speed","value":96}
{"t":"LED","op":"param","name":"color","value":{"r":255,"g":0,"b":64}}
```

#### 初期対応パラメータ

| name | value | 範囲 / 形式 |
|---|---|---|
| `speed` | `int` | `0..255` |
| `color` | object | `{"r":0..255,"g":0..255,"b":0..255}` |

### 4. direct frame

```json
{
  "t":"LED",
  "op":"vialrgb_direct",
  "first":0,
  "pixels":[[255,0,0],[0,0,0],[0,0,0]]
}
```

#### フィールド

| フィールド | 型 | 説明 |
|---|---|---|
| `first` | `int` | この chunk の先頭 LED index |
| `pixels` | `int[n][3]` | LED チェーン順の HSV 配列 |

`pixels` の順序は `config/default/ledd.json` の `leds` 記述順と一致させる。
VialRGB upstream の `direct_fastset` と同じく、1 packet で最大 9 LED 分の
HSV を送る。

## `logicd` 内部状態

`logicd` は LED の最新状態を保持する。

```python
led_state = {
    "vial_effect": 1,
    "brightness": 64,
    "params": {
        "speed": 128,
        "color": {"r": 255, "g": 255, "b": 255},
    },
    "source": "boot",
    "direct": False,
}
```

### 保持する理由

1. 新規 `ledd` 接続時に現在状態を再送できる。
2. Vial / キー操作 / Web UI の変更を 1 箇所で整合できる。
3. 将来 OLED や Web UI に状態表示しやすい。

## `ledd_events.sock` 拡張 API

`logicd` から `ledd` へ送る内部 API。

### 1. effect selection

```json
{"t":"anim","vial_effect":3,"source":"vialrgb"}
```

### 2. parameter update

```json
{"t":"anim_param","name":"speed","value":96}
{"t":"anim_param","name":"color","value":{"r":255,"g":0,"b":64}}
```

### 3. global setting

```json
{"t":"led_global","name":"brightness","value":128}
```

### 4. direct frame

```json
{
  "t":"frame",
  "source":"vialrgb",
  "pixels":[[255,0,0],[0,0,0],[0,0,0]]
}
```

## `ledd` 側の拡張

## `AnimationBase`

追加候補:

```python
def on_param(self, name: str, value: object) -> None:
    """動的パラメータ更新を受ける。"""
```

## `AnimationManager`

追加候補:

```python
def set_param(self, name: str, value: object) -> None:
    """現在のアニメーションへ動的パラメータを渡す。"""

def set_global(self, name: str, value: object) -> None:
    """LED 全体へ適用する設定を更新する。"""

def render_frame(self, pixels: list[list[int]]) -> None:
    """LED チェーン順の RGB frame を直接描画する。"""
```

## direct mode の扱い

- `frame` を受けたら direct mode とみなす。
- direct mode 中は通常アニメーション thread を停止または休止する。
- `anim` を受けたら direct mode を抜け、指定アニメーションを再開する。
- direct frame にも global brightness を適用する。

現行実装では次の VialRGB コマンドに対応する。

| command | 内容 |
|---|---|
| `GET_NUMBER_LEDS (0x43)` | `config/default/ledd.json` の `leds` 件数を返す |
| `GET_LED_INFO (0x44)` | LED の正規化座標、`LED_FLAG_KEYLIGHT`、matrix row/col を返す |
| `DIRECT_FASTSET (0x07 0x42)` | `first_index`, `num_leds`, `HSV * num_leds` を ledd へ転送する |

## effect 名と animation の対応

Vial/VialRGB が使う識別子を正とし、`ledd` 側の実装クラス名・ファイル名も
その意味に合わせる。

Vial が番号管理の場合:

| 識別子空間 | 用途 |
|---|---|
| Vial 定義済み番号 | Vial 互換 effect |
| 未使用番号 | 独自 effect |

Vial が名前管理の場合:

| 識別子空間 | 用途 |
|---|---|
| Vial 定義済み名 | Vial 互換 effect |
| 独自 prefix 付き名 | 独自 effect |

初期実装では、Vial 互換 effect と direct mode を優先し、
独自 effect は Vial 側の識別子仕様を確認してから追加する。

## Lighting effect 実装状態

Vial/QMK upstream の `quantum/vialrgb_effects.inc` にある標準 VialRGB effect と、
本プロジェクトの実装状態を対応付ける。

状態の意味:

- `実装済み`: `VIALRGB_GET_SUPPORTED` で公開し、`ledd` 側にも処理がある。
- `未実装`: Vial 標準 ID は存在するが、まだ公開も描画処理もしていない。
- `互換簡易`: Vial 標準の名前で公開しているが、QMK と完全同一の見た目ではなく近似実装。

| ID | Effect | 状態 | 備考 |
|---:|---|---|---|
| 0 | Disable | 実装済み | 消灯 |
| 1 | Direct Control | 実装済み | `DIRECT_FASTSET` の HSV chunk を反映 |
| 2 | Solid Color | 実装済み | HSV 単色 |
| 3 | Alphas Mods | 互換簡易 | LED 座標から alpha / modifier 領域を近似 |
| 4 | Gradient Up Down | 互換簡易 | LED 座標から縦グラデーション |
| 5 | Gradient Left Right | 互換簡易 | LED 座標から横グラデーション |
| 6 | Breathing | 実装済み | |
| 7 | Band Sat | 互換簡易 | 座標ベース |
| 8 | Band Val | 互換簡易 | 座標ベース |
| 9 | Band Pinwheel Sat | 互換簡易 | 座標ベース |
| 10 | Band Pinwheel Val | 互換簡易 | 座標ベース |
| 11 | Band Spiral Sat | 互換簡易 | 座標ベース |
| 12 | Band Spiral Val | 互換簡易 | 座標ベース |
| 13 | Cycle All | 実装済み | |
| 14 | Cycle Left Right | 互換簡易 | LED 座標から横方向 cycle |
| 15 | Cycle Up Down | 互換簡易 | LED 座標から縦方向 cycle |
| 16 | Rainbow Moving Chevron | 互換簡易 | LED 座標から chevron pattern を生成 |
| 17 | Cycle Out In | 互換簡易 | LED 座標の中心距離から radial cycle |
| 18 | Cycle Out In Dual | 互換簡易 | 中心距離の dual radial cycle |
| 19 | Cycle Pinwheel | 互換簡易 | LED 座標の角度から pinwheel cycle |
| 20 | Cycle Spiral | 互換簡易 | 角度 + 中心距離から spiral cycle |
| 21 | Dual Beacon | 互換簡易 | LED 座標の角度から dual beacon を生成 |
| 22 | Rainbow Beacon | 互換簡易 | 座標ベース |
| 23 | Rainbow Pinwheels | 互換簡易 | 座標ベース |
| 24 | Raindrops | 互換簡易 | random drop |
| 25 | Jellybean Raindrops | 互換簡易 | random hue drop |
| 26 | Hue Breathing | 実装済み | |
| 27 | Hue Pendulum | 互換簡易 | hue を往復 |
| 28 | Hue Wave | 互換簡易 | LED 座標から波を生成 |
| 29 | Typing Heatmap | 互換簡易 | key event 起点の heat decay |
| 30 | Digital Rain | 互換簡易 | LED 座標の column trail |
| 31 | Solid Reactive Simple | 実装済み | `logicd -> ledd` の key event で反応 |
| 32 | Solid Reactive | 互換簡易 | key event 起点 |
| 33 | Solid Reactive Wide | 互換簡易 | key event 起点の広域反応 |
| 34 | Solid Reactive Multiwide | 互換簡易 | key event 起点の multi-color 広域反応 |
| 35 | Solid Reactive Cross | 互換簡易 | key event 起点の cross 反応 |
| 36 | Solid Reactive Multicross | 互換簡易 | key event 起点の multi-color cross 反応 |
| 37 | Solid Reactive Nexus | 互換簡易 | key event 起点の広域 nexus 反応 |
| 38 | Solid Reactive Multinexus | 互換簡易 | key event 起点の multi-color nexus 反応 |
| 39 | Splash | 実装済み | key event 起点の splash |
| 40 | Multisplash | 実装済み | key event 起点の multi-color splash |
| 41 | Solid Splash | 実装済み | 背景色付き splash |
| 42 | Solid Multisplash | 実装済み | 背景色付き multi-color splash |
| 43 | Pixel Rain | 実装済み | |
| 44 | Pixel Fractal | 互換簡易 | 座標ベースの fractal 風 pattern |
| 1000 | Experimental Custom | 実装済み | 独自 effect |
| 1001 | LED Life Game | 実装済み | キー入力を seed にした独自 effect |
| 1002 | Direct Multisplash | 実装済み | direct-frame 動画ベースに key event 起点の multisplash を合成 |
| 1003 | Key Banner | 実装済み | 押下キーの短いラベルを5x7風の縦LED列として右から左へ流す |

`VIALRGB_GET_SUPPORTED` で現在公開している ID:

```text
0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12,
13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23,
24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34,
35, 36, 37, 38, 39, 40, 41, 42, 43, 44,
1000, 1001, 1002, 1003
```

標準 effect のうち未実装の ID:

```text
なし
```

## 独自 effect の扱い

2026-05-17 に PC の Vial アプリで確認した結果、キーボード側が
`VIALRGB_GET_SUPPORTED` で標準外 ID を返しても、Vial アプリの Lighting UI には表示されなかった。
`1000` 番台だけでなく、標準 ID の直後である `45` でも表示されなかったため、
Vial アプリはキーボード側の supported 応答だけで任意 ID を表示するのではなく、
アプリ内の既知 effect 定義に依存していると考える。

そのため、独自 effect は次の方針で扱う。

- Vial アプリで選ぶ対象は標準 ID `0..44` に限定する。
- 独自 effect は `1000` 番台を本プロジェクト用の予約領域として使う。
- 独自 effect の選択・表示は HTTP UI を正とする。
- 独自 effect を `VIALRGB_GET_SUPPORTED` に含めてもよいが、Vial アプリに表示されることは期待しない。
- 標準 ID の隙間や直後の番号 (`45` など) は将来の upstream 追加と衝突しやすいため使わない。
- `1001` は `LED Life Game` として使う。キー入力を seed にした実験的 effect で、
  Vial アプリではなく HTTP Lighting tab から選ぶ。
- `1002` は `Direct Multisplash` として使う。通常の effect 巡回には入れず、
  HTTP Lighting tab などから明示選択した場合だけ direct-frame 動画へ multisplash を重ねる。
- `1003` は `Key Banner` として使う。実際の入力文字列は保存せず、押下位置の current keymap
  keycode から `A` / `1` / `ENT` などの短い表示ラベルを作り、5x7風の列データとして右から左へ流す。

## VialRGB と既存 `ANIM(N)` の共存

### 既存キー操作

```json
{"t":"anim","id":1,"source":"keymap"}
```

### VialRGB 由来

```json
{"t":"anim","vial_effect":3,"source":"vialrgb"}
```

### 共存ルール

- 最後に届いた selection が勝つ。
- global setting は effect をまたいで維持する。
- parameter は現在選択中の animation にのみ適用する。
- direct frame は direct mode を開始し、通常 animation を一時停止する。
- 例外として独自 effect `1002` (`Direct Multisplash`) 選択中の direct frame は、
  受信 RGB frame を動画ベースとして扱い、通常 animation ではなくキー入力起点の
  multisplash を合成する。
- `ANIM(N)` キーを押すと direct mode を抜けて通常 animation へ戻る。

## Lighting 制御キーコード

Vial/QMK には、キーマップ上のキーコードとして Lighting を変更する操作がある。
本プロジェクトでは QMK の Lighting keycode 値を `daemon/viald/keycode_codec.py` で
internal action へ変換し、打鍵時に `logicd` が `_led_state` を更新する。

対応済み:

- `RGB_TOG`: on/off
- `RGB_MOD` / `RGB_RMOD`: effect 送り / 戻し
- `RGB_VAI` / `RGB_VAD`: brightness up / down
- `RGB_HUI` / `RGB_HUD`: hue up / down
- `RGB_SAI` / `RGB_SAD`: saturation up / down
- `RGB_SPI` / `RGB_SPD`: speed up / down
- `RM_ON` / `RM_OFF` / `RM_TOGG`
- `RM_NEXT` / `RM_PREV`
- `RM_HUEU` / `RM_HUED`
- `RM_SATU` / `RM_SATD`
- `RM_VALU` / `RM_VALD`
- `RM_SPDU` / `RM_SPDD`

実装:

- `daemon/viald/keycode_codec.py` が QMK/Vial keycode と internal action を相互変換する。
- `logicd` が press 時だけ Lighting action を処理する。
- `logicd -> ledd {"t":"vialrgb",...}` と同じ経路で反映する。
- effect 送り / 戻しは `VIALRGB_GET_SUPPORTED` で公開している実装済み effect を巡回する。
- `RGB_*` と `RM_*` のうち意味が同じものは同じ internal action として処理する。
- キーコード打鍵による変更も Lighting 設定永続化の保存対象に含める。

確認:

- `script/test_vial_keycode_codec.py`
- `script/test_logicd_lighting_keys.py`
- `script/test_lighting_key_runtime.py`

## 状態同期

新しい `ledd` クライアントが接続したとき、`logicd` は以下を順に送る。

1. `layer`
2. `mode`
3. `anim`
4. `led_global` 群
5. `anim_param` 群

これにより、`ledd` 再起動後も VialRGB 設定を復元できる。

## Lighting 設定の保存

### 現状

Vial GUI で変更した Lighting 設定は、再起動後も復元する。
HTTP UI では、直接触って試す Lighting effect は Keymap と同じく
「即時反映 + debounce 保存 + リセットで保存済みに戻す」操作として扱う。
Script editor や Interaction editor のようなテキスト / フォーム編集は、誤保存を避けるため
明示的な保存ボタンのままにする。

保存対象:

- `mode`
- `speed`
- `h`
- `s`
- `v`

保存先候補:

- `/mnt/p3/led_state.json`

ファイル例:

```json
{
  "mode": 40,
  "speed": 128,
  "h": 80,
  "s": 255,
  "v": 128
}
```

ただし direct frame は永続化しない。

実装:

- `VIALRGB_SET_MODE` / HTTP Lighting effect 反映後に debounce 付き自動保存する。
  既定では最後の変更から約20秒後に保存する。HTTP Lighting のリセットは pending save を取り消し、
  `/mnt/p3/led_state.json` の保存済み state を読み直して `ledd` へ再反映する。
- `CMD_VIA_LIGHTING_SAVE` でも明示保存する。
- `logicd` 起動時に保存済み Lighting 状態を読み込み、`ledd` 接続時に再送する。
- `viald` は `VIALRGB_GET_MODE` 時に `logicd` へ現在状態を問い合わせる。
- `script/test_vialrgb_persistence.py` で Raw HID 経由の保存・復元確認を行う。

## 実装ステージ

### Stage 1

- `logicd` に LED state を追加
- `ledd_events.sock` に `led_global` を追加
- `ledd_events.sock` に `anim_param` を追加
- `AnimationBase.on_param()`
- `AnimationManager.set_global()`
- `AnimationManager.set_param()`

### Stage 2

- `solid` animation
- `brightness`
- `color`

### Stage 3

- VialRGB effect selection
- `speed`

### Stage 4

- direct frame

### Stage 5

- `breathing`
- `rainbow`
- Lighting 設定の永続化: 実装済み

## 未決事項

1. VialRGB の effect 識別子が番号か名前かの確定
2. Vial 定義済み effect と独自 effect に割り当てる未使用識別子空間
3. Vial direct mode の frame 更新頻度上限
4. brightness を `PixelStrip` の global brightness として扱うか、描画直前の色補正として扱うか
5. `speed` の 0..255 を各 animation の時間軸へどう正規化するか

## 決定事項

- `lighting` は `"vialrgb"` を維持する。
- `viald` から `ledd` へは直結しない。
- `logicd` が LED 状態の正本を持つ。
- 外部 API は Vial/VialRGB の native effect 識別子を正とする。
- Vial が番号管理なら番号を、名前管理なら名前を使う。
- 独自 effect は `1000` 番台へ追加し、HTTP UI で選択する。
- `brightness` は global setting とし、effect をまたいで維持する。
- `speed` / `color` は effect parameter とする。
- direct frame にも brightness を適用する。
- `ledd` は animation 基盤を拡張して VialRGB を受ける。
- direct frame と通常 animation は同じ API に混ぜず、別メッセージとして扱う。
