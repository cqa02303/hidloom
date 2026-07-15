# LED semantic roles / state overlay

更新日: 2026-05-26

`ledd` で key の意味を区別し、reactive animation、splash、direct-frame、lock 状態表示を
共存させるための仕様メモです。

## 目的

今までの LED は「押された key を光らせる」「animation を流す」方向が中心でした。
今後は次を分離します。

- key の意味: modifier / function / layer / lock / script / system / normal
- 状態表示: CTRL lock、Caps lock、layer lock など
- 一時表示: reactive animation、splash、direct-frame

## Config shape

`daemon/ledd/semantic_roles.py` では次の shape を正規化します。

```json
{
  "roles": {
    "KC_LCTL": "modifier",
    "MO(1)": "layer",
    "KC_CAPS": "lock",
    "KC_SH10": "script"
  },
  "state_overlays": {
    "layer:1": {
      "keys": ["LT(1,KC_LANG2)"],
      "include_layer_changes": true,
      "color": [0, 80, 0],
      "effect_blend": "max",
      "priority": 30
    },
    "ctrl_lock": {
      "keys": ["KC_LCTL"],
      "color": [0, 0, 80],
      "priority": 45
    },
    "caps_lock": {
      "keys": ["KC_CAPS", "KC_CAPSLOCK"],
      "color": [120, 80, 0],
      "priority": 45
    }
  },
  "reactive": {
    "exclude_roles": ["modifier", "function", "layer", "lock"]
  },
  "overlay_priority": {
    "normal": 0,
    "modifier": 10,
    "function": 20,
    "layer": 30,
    "script": 35,
    "lock": 40,
    "system": 50
  }
}
```

## Default inference

明示 role がない場合、keycode から保守的に推定します。

| keycode | role |
| --- | --- |
| `KC_LCTL` / `KC_RSFT` など | `modifier` |
| `KC_F1` ... | `function` |
| `MO(1)` / `TG(1)` / `LT(1,KC_SPACE)` など | `layer` |
| `KC_CAPS` / `KC_NUM` / `KC_SCROLL` | `lock` |
| `KC_SHn` / `SCRIPT(...)` | `script` |
| `KC_BT` / `BT_*` / `KC_USB` など | `system` |
| その他 | `normal` |

## Restore 方針

優先順位は次のように扱います。

1. direct-frame / splash は一時的に全体を上書きできる。
2. 一時表示が終わったら、消灯ではなく state overlay の base 表示へ戻す。
3. reactive animation は `reactive.exclude_roles` の key を trigger にしない。
4. 複数 overlay が同じ key にかかる時は `priority` が高い方を採用する。
   `layer:N` overlay 同士の `priority` が同じ場合は、keymap の実効 layer 解決と同じく
   数字が大きい active layer の overlay を採用する。

## Host lock LED 表示の推奨方針

Host から返る keyboard LED Output Report は、標準 bit として
`num_lock` / `caps_lock` / `scroll_lock` / `compose` / `kana` を扱う。
Web UI では通常利用の多い `caps_lock` / `num_lock` / `scroll_lock` を主表示にし、
`compose` / `kana` は advanced 扱いにする。

Lock state の LED 表示は次の hybrid 方式を推奨する。

- `follow_keys`: 現在有効な layer 上で、その lock state に対応する keycode が割り当てられている
  0 個以上のキー LED をすべて光らせる。
- `extra_leds`: keycode が存在しない配列でも状態表示できるよう、明示指定した LED を追加で光らせる。
- `color`: lock state ごとの既定色を持つ。
- `key_colors`: 必要なら keycode alias、または LED 座標ごとに色を上書きできる。
- `blend`: 1 つの LED に複数 lock state が重なった時の合成方式を選ぶ。

推奨の合成方式は `max` です。例えば同じ LED を
`caps_lock = red`、`num_lock = blue`、`scroll_lock = green` に割り当てると、
Caps + Num は magenta、Caps + Scroll は yellow、Num + Scroll は cyan、
3 つ同時は white に近い表示になる。`add` は明るくなりすぎやすいため、まずは `max` を既定にする。

例:

```json
{
  "lock_indicators": {
    "blend": "max",
    "states": {
      "caps_lock": {
        "follow_keys": true,
        "extra_leds": ["4,4"],
        "color": [255, 0, 0],
        "key_colors": {
          "KC_CAPS": [255, 80, 0],
          "4,4": [255, 0, 0]
        }
      },
      "num_lock": {
        "follow_keys": true,
        "extra_leds": ["4,4"],
        "color": [0, 0, 255]
      },
      "scroll_lock": {
        "follow_keys": true,
        "extra_leds": ["4,4"],
        "color": [0, 255, 0]
      }
    }
  }
}
```

Alias は canonical state へ正規化して扱う。たとえば
`KC_CAPS` / `KC_CAPSLOCK` は `caps_lock`、
`KC_NUM` / `KC_NUMLOCK` / `KC_NLCK` は `num_lock`、
`KC_SCROLL` / `KC_SCROLLLOCK` / `KC_SLCK` は `scroll_lock` とみなす。

Layer が変わった時は、base layer だけではなく現在 active な layer stack から
座標ごとの effective keycode を解決し直す。これにより、同じ物理 LED でも
layer 0 では normal、layer 1 では Num Lock、layer 2 では function key のように
役割と表示色を切り替えられる。

Web UI では state ごとに次を編集できる形にする。

- `Enabled`
- `Color`
- `Extra indicator LEDs`
- `Blend shared LEDs`: `priority` / `max` / `add`
- `Preview` / `Restore`

`follow_keys` は UI 上の独立 checkbox にはせず、常に有効として扱う。
状態ごとの `keys` を追加・削除することで、どの key の LED を host lock state に追従させるかを管理する。
初期表示では `caps_lock` / `num_lock` / `scroll_lock` / `compose` / `kana` の各状態を有効にし、
保存済み config がある場合はその内容を優先する。

LED Effect では `modifier` role を reactive / splash trigger に含めるかを checkbox で切り替えられる。
設定ファイルでは `semantic_roles.reactive.modifier_triggers_effects` を正式なフラグとして扱い、
`true` の時は `reactive.exclude_roles` に `modifier` が残っていても modifier を反応対象にする。

## 実装状況

- `daemon/ledd/semantic_roles.py` を追加し、role 推定、config 正規化、reactive 除外判定を実装済み。
- `ledd` runtime は layer 0 keymap または `keycode_by_led_key` から matrix key の keycode を引き、
  `reactive.exclude_roles` に該当する key を VialRGB reactive / splash trigger から除外する。
- `led_overlay_state` / `state_overlay` 通知と layer active 通知を state overlay 入力として扱い、
  reactive / splash の idle base 色へ priority の高い overlay 色を戻す。
- `include_layer_changes=true` の `layer:N` overlay は、`N` レイヤで `KC_TRNS` 以外に
  上書きされる物理キーも overlay 対象にする。Fn レイヤの `KC_F1`-`KC_F8` /
  `KC_F10`-`KC_F12` / `KC_DEL` のように、押している間だけ意味が変わるキーを
  緑で確認するために使う。
- `color` は overlay ごとに指定できる。`layer:1` を緑、`layer:2` を青のように
  レイヤ別の色を持たせられる。
- 複数 layer が同時に active の場合、同 priority の layer overlay では数字が大きい layer の色が勝つ。
  たとえば `layer:1` と `layer:2` が同時 active でどちらも同じ物理キーを対象にする場合、
  そのキーは `layer:2` の色になる。
- `MO(N)` / `LT(N,kc)` / `TT(N)` などで参照される layer は、`layer:N` overlay が
  未定義でも既定色で自動補完される。layer2 以降は keymap に layer が存在するだけでも
  補完対象にする。`state_overlays.layer:N` を明示すると、その `color` /
  `effect_blend` / `include_layer_changes` が優先される。
- 自動補完の layer 色は固定 palette を循環して使う。既定順は
  layer1 `[0,80,0]`、layer2 `[0,48,120]`、layer3 `[96,0,96]`、
  layer4 `[120,60,0]`、layer5 `[0,96,96]`、layer6 `[120,0,48]` で、
  layer7 以降は layer1 から繰り返す。
- `effect_blend` は overlay 色と現在の effect base 色の混ぜ方を指定する。
  `replace` は従来どおり overlay 色で置き換え、`max` は RGB 成分ごとに明るい方を残し、
  `add` は加算、`alpha` は `effect_alpha` の割合で半透明合成する。
  既定は互換性を優先して `replace`。
- Lighting tab の `Layer overlay colors` accordion から Layer 1-7 の
  `color` / `effect_blend` / `effect_alpha` / `include_layer_changes` を編集できる。
  保存は `GET/PUT /api/lighting/layer-overlays` で `config/default/ledd.json` の
  `state_overlays.layer:N` だけを atomic write し、Host lock LEDs とは別の
  `LEDD_RELOAD semantic_roles` 経路で反映する。
- `daemon/logicd/host_led_output.py` は host keyboard LED Output Report の標準 bit を
  `num_lock` / `caps_lock` / `scroll_lock` / `compose` / `kana` として扱う。
- `settings.host_led_output.states` で有効にする種類だけを設定できる。
  現在の default config は通常利用する `caps_lock` / `num_lock` / `scroll_lock` を有効化し、
  `compose` / `kana` は対応済みだが既定では無効にしている。
- 2026-06-15 の実機観測では、Microsoft IME かな入力 ON 後、次の 1 key 入力で
  Kana bit が反応し、Host lock LEDs の表示 LED も反応した。Kana は host profile 依存で
  遅延しうる advisory state として扱う。
- `logicd` は `HOST_LED` ctrl message (`{"t":"HOST_LED","report":2}`) を受けると、
  設定済み state だけを `led_overlay_state` として `ledd` へ送る。
- USB HID keyboard descriptor は LED Output Report を含み、`daemon/logicd/host_led_reader.py` が
  `/dev/hidg0` から host LED report を読んで `HOST_LED` と同じ処理へ渡す。
- `fallback_internal_toggle` は実 host report 経路がない環境でだけ使うデバッグ用 fallback。
  通常は `false` にし、key 押下だけでは host lock state を local toggle しない。
- `lock_indicators` は `follow_keys` / `extra_leds` / `key_colors` / `blend` を正規化し、
  keycode alias と active layer の effective keycode を使って表示対象を決める。
- Lighting tab に Host lock LED 設定の保存 UI を追加し、旧 `state_overlays` の lock state は
  保存時に `lock_indicators` へ寄せる。
- Host lock LEDs と modifier effect trigger はフォーム編集に近いため、明示保存ボタンのまま扱う。
  一方、Lighting effect 本体は Keymap と同じく「即時反映 + debounce 保存 + リセットで保存済みに戻す」
  操作感に揃える。
- Web UI からの保存は atomic write 後に `logicd` 経由で `ledd` へ `semantic_roles_reload` を送り、
  `ledd` は validation 成功後だけ config / keymap layer map を差し替える。reload 通知は短時間 debounce する。
- HTTP UI の単キー keymap 変更は `logicd` runtime へ即時反映し、永続保存 (`S`) は
  最後の変更から約20秒後に debounce してまとめる。`ledd` の layer 差分 overlay は
  保存済み runtime keymap から再構築するため、後から追加した layer key の点灯は
  debounce 保存と semantic reload の後に反映される。
- Web UI の lock state selector は key picker と LED map picker で編集する。
  色は state 見出し横に現在色を出し、color picker popup に既定色 sample を並べる。
- Lighting tab の LED Effect 内に modifier key を effect trigger に含める checkbox を追加済み。
  Host lock LEDs の保存 / 再読込 button は section 上部に置く。
- `script/test_led_semantic_roles.py` で role 推定と config validation を検証済み。
- `script/test_logicd_host_led_output.py` で host LED Output Report の bit mapping と ctrl message を検証済み。
- `script/test_logicd_host_led_reader.py` で USB Output Report payload parsing を検証済み。
- `script/test_http_lighting_lock_indicators.py` で Web UI 用の永続設定 helper を検証済み。

## 残課題

- BLE Keyboard Output Report `WriteValue` を `HOST_LED` ctrl message へ接続する。
  USB `/dev/hidg0` OUT report 経路は実装済みで、BLE 側の IPC 設計は
  [bluetooth/host-led-output-report-design.md](../bluetooth/host-led-output-report-design.md) に固定済み。
- 実機で modifier trigger 除外、overlay priority、layer changed-key overlay を必要に応じて目視確認する。
