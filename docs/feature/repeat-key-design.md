# Repeat Key / Alternate Repeat Key design

作成日: 2026-05-30
更新日: 2026-06-01

QMK / ZMK / KMK 先行機能候補のうち、`Repeat Key` / `Alternate Repeat Key` を
`logicd` に入れる場合の設計です。
2026-05-30 に runtime 初期実装を追加済みです。
2026-06-01 には実機なしで進められる follow-up として、privacy-safe な status helper と alternate pair metadata test を追加しました。

## Goal

Repeat Key は、直前に送った通常 action をもう一度送る入力補助です。
Alternate Repeat Key は、直前 action の反対方向や対になる action を送ります。

優先する体験:

- `REPEAT_KEY` で直前の repeatable action を再送する。
- `ALT_REPEAT_KEY` で Left/Right、Up/Down、Backspace/Delete、wheel up/down などを反転する。
- daemon restart / output switch / config reload では履歴を破棄し、古い host へ意図しない再送をしない。
- macro / script / Bluetooth control / Wi-Fi control / shutdown のような副作用 action は repeat しない。
- status / UI では、履歴 action 名をそのまま出さず `history_available` / `alternate_available` から始める。

## Keycodes

| keycode | 動作 |
| --- | --- |
| `REPEAT_KEY` | 直前の repeatable action を再送する。履歴がない場合は何もしない。 |
| `ALT_REPEAT_KEY` | 直前 action の alternate mapping があれば反対 action を送る。mapping がなければ何もしない。 |
| `QK_REPEAT_KEY` | QMK 互換 alias。保存時または validation 時に `REPEAT_KEY` へ正規化する候補。 |
| `QK_ALT_REPEAT_KEY` | QMK 互換 alias。保存時または validation 時に `ALT_REPEAT_KEY` へ正規化する候補。 |

初期実装では repeat count、長押し連打、per-key alternate override は作らない。

## Owner / state

| 項目 | 方針 |
| --- | --- |
| runtime owner | `logicd` の `InteractionEngine` |
| config owner | `settings.interaction.repeat_key` |
| persistence | repeat history は永続化しない。daemon restart / config reload / output switch で破棄する。 |
| output | repeat 対象 action を通常の key event と同じ path へ流す。 |
| status | `logicd.repeat_key_status` が action 名を出さない read-only status を生成する。 |

`settings.interaction.repeat_key` の最小 schema:

```json
{
  "enabled": true,
  "alternate_pairs": [
    ["KC_LEFT", "KC_RGHT"],
    ["KC_UP", "KC_DOWN"],
    ["KC_BSPC", "KC_DEL"],
    ["KC_WH_U", "KC_WH_D"],
    ["KC_WH_L", "KC_WH_R"]
  ]
}
```

`enabled=false` の場合、`REPEAT_KEY` / `ALT_REPEAT_KEY` は何もせず warning なしで無視する。

## Privacy-safe status

`repeat_history` には、直前に出力した action 名が入るため、そのまま HTTP / OLED / LED に出しません。
UI 向けには次の最小情報だけを出します。

```json
{
  "enabled": true,
  "history_available": true,
  "alternate_available": true,
  "alternate_pair_count": 9
}
```

実装済み helper:

- `logicd.repeat_key_status.normalize_alternate_pairs()`
- `logicd.repeat_key_status.repeat_key_status()`
- `logicd.repeat_key_status.repeat_key_status_from_engine()`
- `logicd.repeat_key_status.repeat_key_default_alternate_pairs()`

この helper は read-only で、`InteractionEngine` の履歴 owner を移さない。

## Repeatable actions

repeat してよい候補:

- 基本 keyboard keycode: `KC_A`-`KC_Z`、数字、記号、navigation、editing。
- modifier wrapper: `S(KC_1)` など、単発 tap として扱えるもの。
- mouse button / wheel / relative move keycode のうち、既存 macro path で単発 tap として安全なもの。

repeat しない候補:

- `REPEAT_KEY` / `ALT_REPEAT_KEY` 自身。
- layer control: `MO` / `TG` / `TO` / `DF` / `OSL` / `TT` / `LT` / `MT` の hold 側。
- Interaction control: `TD(...)`、`MORSE(...)` の開始 action。
- macro / script: `MACRO:*`、`KC_SHn`、KML。
- system / power / connectivity: `KC_SHUTDOWN`、`BT_*`、`WIFI_*`、`KC_USB`、`KC_BT`、`KC_CONNAUTO`。
- VialRGB / LED direct control など、状態変更だけの action。

repeat history に保存するのは、最終的に出力した repeatable tap action だけにする。
combo / tap dance / key override 由来でも、最終 action が repeatable なら保存してよい。

## Alternate mapping

初期 alternate pair:

| normal | alternate |
| --- | --- |
| `KC_LEFT` | `KC_RGHT` |
| `KC_UP` | `KC_DOWN` |
| `KC_HOME` | `KC_END` |
| `KC_PGUP` | `KC_PGDN` |
| `KC_BSPC` | `KC_DEL` |
| `KC_WH_U` | `KC_WH_D` |
| `KC_WH_L` | `KC_WH_R` |
| `MS_LEFT` | `MS_RGHT` |
| `MS_UP` | `MS_DOWN` |

mapping は双方向に扱う。
alternate mapping がない action では `ALT_REPEAT_KEY` は何もしない。
`alternate_pair_count` は bidirectional map の entry 数ではなく logical pair 数として数える。

追加候補と初期判断:

| family | 候補 | 初期扱い |
| --- | --- | --- |
| navigation | `KC_LEFT` / `KC_RGHT`, `KC_UP` / `KC_DOWN`, `KC_HOME` / `KC_END`, `KC_PGUP` / `KC_PGDN` | 初期対象 |
| editing | `KC_BSPC` / `KC_DEL` | 初期対象 |
| mouse wheel | `KC_WH_U` / `KC_WH_D`, `KC_WH_L` / `KC_WH_R` | 初期対象 |
| mouse move aliases | `MS_LEFT` / `MS_RGHT`, `MS_UP` / `MS_DOWN` | 初期対象 |
| punctuation / brackets | `KC_LBRC` / `KC_RBRC`, `KC_LPRN` / `KC_RPRN` 相当 | 初期対象外。host layout / alias policy と混ぜない |
| layer / system / script | `MO` / `TG` / `KC_SHn` / `BT_*` / `WIFI_*` | 対象外 |

## Behavior

1. repeatable action が通常出力されたら、repeat history をその action へ更新する。
2. `REPEAT_KEY` が押されたら、repeat history の action を通常 tap として出力する。
3. repeat によって出力された action も、repeat history を同じ action へ更新する。
4. `ALT_REPEAT_KEY` が押されたら、repeat history の alternate action を通常 tap として出力する。
5. alternate によって出力された action は、repeat history を alternate action へ更新する。
6. repeat history がない、または対象外 action の場合は何もしない。

history を破棄する event:

- daemon restart / shutdown
- config reload
- output target switch
- USB/BLE/uinput output unavailable からの復帰
- emergency release / stuck-key recovery
- keymap clear / layer reset のような大きい runtime state reset

## Safety / non-goals

- 副作用 action、system action、script action は repeat しない。
- 長押し auto-repeat は初期実装しない。
- repeat history は保存しない。
- host ごとの履歴分離は初期実装しない。output switch 時に履歴破棄することで安全側に倒す。
- QMK の全 alternate mapping 互換は目指さず、local config で育てる。
- status には履歴 action 名を出さない。

## UI / status boundary

- first slice の Interaction summary は `Repeat Key` metric に設定 enabled / disabled と logical pair count だけを出す。
- `history_available` / `alternate_available` は `logicd.repeat_key_status` の privacy-safe payload として固定するが、runtime snapshot 接続までは HTTP summary / accordion header へ出さない。
- `/api/status` へ出す場合は `InteractionEngine` の repeat history snapshot と `logicd.repeat_key_status` を同じ request 内で使い、履歴 action 名を含めない。
- OLED / LED へ出す場合も `Repeat ready` / `Alt ready` 程度に留め、action 名、script 名、macro 名は出さない。
- output switch / config reload / non-repeatable action 後に `history_available=false` / `alternate_available=false` が返ることを接続テストで固定する。

## Static tests added with implementation

Runtime 初期実装:

- `REPEAT_KEY` / `ALT_REPEAT_KEY` alias が validation を通る。
- repeatable action 後の `REPEAT_KEY` が同じ tap action を出す。
- alternate pair 後の `ALT_REPEAT_KEY` が反対 action を出す。
- repeat 対象外 action は history に残らない。
- daemon restart / config reload / output switch 相当で history が消える。
- `REPEAT_KEY` 自身を repeat history に保存しない。
- HTTP remap candidate に `REPEAT_KEY` / `ALT_REPEAT_KEY` が出る。

Status follow-up:

- alternate pair は bidirectional map に正規化される。
- logical pair 数を `alternate_pair_count` として返す。
- `history_available` / `alternate_available` を返す。
- status payload に履歴 action 名を含めない。
- `InteractionEngine` 風 object から status を作れる。

## Implementation gate

実装済み:

- `InteractionEngine` の最終 tap action を history に記録する位置を小さな単体テストで固定できる。
- system / script / connectivity action を repeat 対象外にする allowlist を先に作れる。
- output switch 時に history を破棄する hook を `logicd` 側に置ける。
- privacy-safe status helper を用意できる。

後続候補:

- HTTP `/api/status` または Interaction summary に privacy-safe runtime availability を接続する。
- 追加 alternate pair を config / UI で安全に編集する場合は、host layout / alias policy と衝突しない family から増やす。

実装しない条件:

- macro / script / system action の再実行を同時に求められる。
- host ごとの履歴分離が必須になる。
- long-press repeat や repeat count UI まで初期要件に入る。
