# HTTP Remap Keycode UI

更新日: 2026-06-13

HTTP UI の「キーコード変更」popup の分類と、Bluetooth / output 関連 action の扱いを記録する。

## 方針

キーコード候補が増えてきたため、popup の候補はタブで分類する。
タブ数が増えても、目的別に探しやすいことを優先する。
一覧から探すより直接書いた方が早い action は、popup 上部の `QMK code`
入力欄からそのまま反映できる。

現在のタブ:

- `PC104`
- `Layer`
- `Mouse`
- `Media`
- `Lighting`
- `BT`
- `System`
- `Script`
- `Other`

## 内部キーコードの網羅

よく使うキーは各カテゴリの固定ボタンとして表示する。
それとは別に、`/api/layout` は `config/default/keycodes.json` の内部キーコード一覧を `keycodes`
として返す。

HTTP UI はその一覧から、既存カテゴリにまだ出ていないキーコードを `Other` タブの
`内部キーコード（未分類・別名）` グループへ補完表示する。
これにより、`KC_ESC` / `KC_ESCAPE` のような別名や、`KC_INT6`、`KC_KP_EQUAL`、
`KC_KB_MUTE` など固定カテゴリにない内部名も選択できる。

固定カテゴリは探しやすさを優先し、網羅性はこの補完グループで担保する。

PC104 タブは通常の 104 キー配列に加え、配列差分として使う `日本語IME`
(`KC_ZKHK` / `KC_RO` / `KC_KANA` / `KC_JYEN` / `KC_HENKAN` / `KC_MUHENKAN`) と
`言語` (`KC_LANG1`-`KC_LANG5`) を `特殊` より前に表示する。
これらは `Other` ではなく PC104 から探せるようにする。

`KC_ZKHK` は全角 / 半角用の内部 routing action。USB HID usage は `KC_GRV`
と同じ `0x35` だが、Windows JIS / US split の `jis_special_us_default` では
JIS main 側へ送る。これにより `KC_GRV` を US sub 側の `~` / `` ` `` 用に残したまま、
全角 / 半角キーも HTTP remap で割り当てられる。

## 初期表示タブ

キーコード変更 popup を開いたときは、現在そのキーに割り当てられている action が属するタブを初期表示する。

例:

| current action | initial tab |
|---|---|
| `KC_A` | `PC104` |
| `MO(1)` | `Layer` |
| `KC_MS_U` | `Mouse` |
| `KC_MPLY` | `Media` |
| `RGB_TOG` | `Lighting` |
| `BT_POWER_TOGGLE` | `BT` |
| `KC_BT` | `System` |
| `LT(1,KC_X)` | `Layer` |

## QMK code 直接入力

popup 上部の `QMK code` 入力欄は、一覧ボタンと同じ `/api/keymap` 経路で action を保存する。
入力値は前後と途中の空白を取り除いてから送信する。HTTP API 側でも同じ正規化を行うため、
全角スペースが混ざっても保存前に取り除く。

例:

```text
LSFT(LGUI(KC_F23))
MO(1)
LT(1,KC_X)
```

HTTP 側では `daemon/http/keymap_actions.py` の検証を通すため、未対応の wrapper 名や危険な文字を含む入力は保存しない。
`LSFT(LGUI(KC_F23))` のような modifier wrapper は `logicd.action_expansion` で press/release に展開される。
`LSFT(LGUI(KC_F23))` は Copilot 用キーとして `Other` タブの「ショートカット」にも候補表示する。

## Layer Tap (`LT`) の設定

`LT(layer,kc)` は「短押しでは `kc`、押している間は `layer` を momentary にする」
tap-hold action として扱う。

HTTP UI では、レイヤー数が少ない前提で、先に対象レイヤーを選び、次にタップキーを選ぶ
2段階操作にする。

操作例:

1. 変更したいキーをクリックする。
2. `Layer` タブで `LT(1)` を押す。
3. `PC104` などから `X` を押す。
4. `LT(1,KC_X)` として保存する。

候補表示のルール:

- `LT(n)` は現在編集中のレイヤーを除外して表示する。
- Layer 0 編集中に layer 0/1 がある場合は `LT(1)` のみ表示する。
- Layer 1 編集中に layer 0/1 がある場合は `LT(0)` のみ表示する。
- タップキーは当面 `KC_*` の通常キーに限定し、`KC_NONE` / `KC_TRNS` は許可しない。
- `LT(1,KC_X)` のような既存割当は `Layer` タブを初期表示し、キー上では短縮表示する。
| `KC_SH0` | `Script` |

## Bluetooth action の分類

Bluetooth 関連 action は 2 種類に分ける。

### BT tab: Bluetooth control

Bluetooth power / pairing / disconnect など、Bluetooth 状態を操作する action。

```text
BT_STATUS
BT_POWER_ON
BT_POWER_OFF
BT_POWER_TOGGLE
BT_PAIRING_ON
BT_PAIRING_OFF
BT_PAIRING_TOGGLE
BT_DISCONNECT
BT_FORGET_DEVICE
```

これらは `logicd` の Bluetooth control handler に渡す。

### System tab: output selector

`KC_BT` は Bluetooth control ではなく、keyboard output backend の選択 action として扱う。

```text
KC_CONNAUTO  -> OutputRouter.force_auto()
KC_CONSOLE   -> OutputRouter.force_uinput()
KC_USB       -> OutputRouter.force_gadget()
KC_BT        -> OutputRouter.force_bt()
```

`KC_BT` は Bluetooth power / pairing を変更しない。
単に `logicd` の OutputRouter で `bt` backend を選ぶだけにする。
`KC_USB` / `KC_CONSOLE` / `KC_BT` は auto を止めて、それぞれ対応する単一出力に限定する。
複数出力 fan-out の個別 on/off は、別途 output toggle keycode を追加して扱う。

## Vial custom keycode

HTTP UI と Vial GUI の custom keycode は、できるだけ同じ action 名を見せる。

`config/default/vial.json` の `customKeycodes` と `logicd.shared_action_defs.VIAL_CUSTOM_ACTIONS` の順序は一致させる。

注意:

- 順序がずれると Vial GUI の表示名と実際に保存される action がずれる。
- 新しい custom action は、既存 index を壊さないため可能な限り末尾に追加する。
- Vial GUI は `USER00`-`USER63` までを解決するため、`customKeycodes` は64件以内に保つ。
- `KC_CONNAUTO` / `KC_USB` / `KC_BT` と `OSL(N)` は標準値も decode するが、現在の Vial GUI では raw 表示になりやすいため custom USER 表示を優先する。
- `LT(2,KC_A)` / `MT(KC_LSFT,KC_A)` / `TT(2)` / `TD(TD0)` は実機確認用の固定 custom 候補として扱う。
- `RGB_*` / `RM_*` は custom USER 枠ではなく、Vial/QMK の lighting keycode として扱う。

## Tests

関連テスト:

```bash
python3 script/test_http_remap_categories.py
python3 script/test_http_remap_keycode_coverage.py
python3 script/test_http_keymap_action_validation.py
python3 script/test_jis_zenkaku_hankaku_routing.py
python3 script/test_shared_action_defs.py
python3 script/test_vial_keycode_codec.py
python3 script/test_output_router_force.py
python3 script/test_macro_output_switch.py
```

## 関連ファイル

- `daemon/http/static/index.html`
- `daemon/http/static/remap_key_groups.js`
- `daemon/http/static/remap_kle.js`
- `daemon/http/static/remap_panel.js`
- `daemon/http/static/remap_vil.js`
- `daemon/http/static/extra_key_groups.js`
- `daemon/http/keymap_actions.py`
- `daemon/logicd/output_router.py`
- `daemon/logicd/macro.py`
- `daemon/logicd/shared_action_defs.py`
- `config/default/vial.json`
- `config/default/keycodes.json`
