# Vial .vil Import Policy

更新日: 2026-05-21

HTTP UI / Vial 連携で `.vil` を読み込むときの方針を記録する。

## 方針

`.vil` import は、標準 Vial / VIA が理解できる keymap 情報を優先して取り込む。
プロジェクト独自の action や拡張 field は、無理に標準 keycode として解釈しない。

基本方針:

- 標準 Vial keycode は通常通り import する
- `shared_vial_custom_actions()` にある custom action は import する
- 表現できない action は warning にする
- 不明な拡張 field は保存対象にしない
- project が生成する `settings.hidloom_interaction_settings` は interaction 設定として復元する
- project が生成する `settings.hidloom_vial_macro_buffer` は Vial Macro buffer として復元する
- import 失敗よりも、読み込める範囲を読み込んで warning を返す

## 取り込むもの

### 標準 keymap

`.vil` の layer / row / col に相当する keycode は、`viald.keycode_codec.KeycodeCodec` で decode できる場合に取り込む。

例:

```text
KC_A
KC_ESC
KC_LEFT
MO(1)
TG(2)
DF(0)
```

### project custom action

`logicd.shared_action_defs.shared_vial_custom_actions()` にある action は import 可能にする。

代表例:

```text
KC_SH0..KC_SH10
KC_CONNAUTO
KC_CONSOLE
KC_USB
KC_BT
BT_STATUS
BT_POWER_TOGGLE
BT_PAIRING_TOGGLE
BT_DISCONNECT
OSL(0)..OSL(31)
LT(2,KC_A)
MT(KC_LSFT,KC_A)
TT(2)
TD(TD0)
```

注意:

- `KC_BT` は Bluetooth power / pairing ではなく OutputRouter の `bt` backend selector
- `BT_*` は Bluetooth control action
- `KC_CONNAUTO` / `KC_USB` / `KC_BT` と `OSL(0)..OSL(31)` は標準値も decode するが、現在の Vial GUI では表示が raw になるため custom USER keycode を優先して encode する
- `LT(2,KC_A)` / `MT(KC_LSFT,KC_A)` / `TT(2)` / `TD(TD0)` は実機確認用の固定 custom 候補として扱う
- `RGB_*` / `RM_*` は custom USER keycode ではなく、Vial/QMK の lighting keycode として扱う

## 取り込まないもの

### 標準外の未知 field

以下のような field が `.vil` に含まれていても、現時点では import しない。

```json
{
  "hidloom_extra": {...},
  "internal_actions": {...},
  "interaction": {...}
}
```

理由:

- Vial GUI / upstream Vial との互換性を壊したくない
- 独自 field の永続化 schema は `settings.hidloom_interaction_settings` だけを固定対象にする
- その他の内部状態は keymap import と責務を分ける

### project interaction settings

このプロジェクトが export した `.vil` では、次の field を保存・復元する。

```json
{
  "settings": {
    "hidloom_interaction_settings": {
      "tap_dances": {},
      "combos": [],
      "key_overrides": []
    },
    "hidloom_vial_macro_buffer": "..."
  }
}
```

同時に、Vial GUI で読めるよう top-level `tap_dance` / `combo` / `key_override`
にも可能な範囲で同じ内容を出す。

### logicd 内部専用 action

Vial keycode codec で表現できない内部 action は、import では標準 keymap として扱わない。

例:

```text
SCRIPT(name)
MACRO:name
U+3042
complex internal action object
```

必要なら、将来 `.vil` ではなく project 専用 export/import schema を別に設計する。

## warning 方針

`.vil` import では、次のような場合に warning を返す。

- decode できない keycode がある
- project custom action ではない unknown user keycode がある
- layer 数 / matrix 座標が実機定義から外れる
- UID mismatch を force import した
- 標準外 field を無視した

warning は HTTP UI に表示し、import 自体は可能な限り続行する。

現在 `vil_layout.parse_vil_import()` と `script/test_vil_import_warnings.py` で固定している
warning の扱い:

| 状況 | 扱い |
| --- | --- |
| UID mismatch かつ force import | `uid mismatch forced` warning を返し、読み込める keymap は取り込む |
| UID mismatch かつ force なし | import を block し、remap plan は空にする |
| unknown top-level field | `unknown field '<name>' ignored` warning を返し、保存しない |
| unknown `settings` field | `unknown field '<name>' ignored` warning を返し、保存しない |
| `settings.hidloom_export_warnings` | 前回 export 時の warning として import warning に引き継ぐ |
| matrix cols 外の値 | 対象 column を無視し、`column(s) beyond matrix cols ignored` warning を返す |
| matrix rows 外の値 | 対象 row を無視し、`row(s) beyond matrix rows ignored` warning を返す |
| negative keycode | 対象 key を無視し、`negative keycode` warning を返す |
| decode できない keycode | 対象 key を無視し、`unsupported keycode` warning を返す |
| matrix cell の余分な値 | 余分な値を無視し、`extra value(s) ignored` warning を返す |
| encoder config 外の encoder | 対象 encoder を無視し、`encoder(s) beyond config ignored` warning を返す |

HTTP UI / CLI / Vial import helper は、これらの warning を「成功したが注意が必要な
import」として表示する。UID mismatch が force されていない場合だけ、誤った機種への
適用を避けるため remap plan を空にして止める。

## error 方針

次の場合は error として import を中断する。

- JSON として壊れている
- `.vil` として必要な基本構造がない
- UID mismatch かつ force import されていない
- keymap 全体を安全に解釈できない

## export 方針

`.vil` export は Vial 互換を優先する。

- 標準 keycode は標準表現で出す
- project custom action は custom keycode として出す
- 表現できない内部 action は warning 付きで `KC_NONE` に落とす
- `settings.interaction` は `settings.hidloom_interaction_settings` として保存する
- Vial Macro buffer は `settings.hidloom_vial_macro_buffer` として保存する
- Tap Dance / Combo / Key Override は Vial 互換 top-level field にも出す

## 将来検討

project 専用の完全 backup / restore が必要になった場合は、`.vil` に無理に詰め込まず、別 schema を検討する。

候補:

```text
.hidloom-layout.json
.hidloom-profile.json
```

含める候補:

- keymap
- interaction settings
- scripts mapping
- LED settings
- output settings
- spid settings

## 関連ファイル

- `daemon/viald/keycode_codec.py`
- `daemon/logicd/shared_action_defs.py`
- `vil_layout.py`
- `daemon/http/httpd.py`
- `docs/keycode/http-remap-keycode-ui.md`
- [docs/macro/compatibility-plan.md](../macro/compatibility-plan.md)
