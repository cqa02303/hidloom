# KML / QMK macro keycode integration design

作成日: 2026-06-01

この文書は KML runner / QMK macro compatible runner を keymap / HTTP から呼ぶための実装前設計です。
2026-06-03 時点では実装へは進まず、保存場所、keycode 名、runner API、HTTP editor 境界、Vial custom keycode 表示、テスト範囲を固定します。

## Goal

- keymap から named macro runner を呼びやすくする。
- KML と QMK macro syntax を混ぜない。
- 既存 script action (`KC_SHn` / `SCRIPT(name)`) と責務を分ける。
- Vial custom keycode 64 枠を不用意に消費しない。
- macro buffer import/export と runtime runner の source of truth を混同しない。

## Keycode policy

初期実装で採る入口:

| keycode | 意味 | 初期扱い |
| --- | --- | --- |
| `KML(name)` | named KML macro を実行する | 初期採用。HTTP / runtime action 名として扱い、Vial custom 枠を消費しない |
| `QMK_MACRO(name)` | named QMK macro compatible macro を実行する | 初期採用。Vial Macro buffer とは別扱い |

初期実装では `KC_KML0`-`KC_KML10` / `KC_QM0`-`KC_QM10` を追加しません。
固定 slot は slot -> name mapping、Vial custom keycode 64 枠、`.vil` import/export の互換表示を同時に決める必要があるためです。
将来 `KC_KMLn` / `KC_QMn` を追加する場合も、最初は `0`-`7` の 8 slot / family から始め、`KC_KML0`-`KC_KML15` のような広い枠は採りません。

## Storage policy

確定方針:

```text
/mnt/p3/macros/kml/<name>.kml
/mnt/p3/macros/qmk/<name>.qmk
config/default/macros/kml/<name>.kml
config/default/macros/qmk/<name>.qmk
```

優先順位:

1. `/mnt/p3/macros/<kind>/<name>.<ext>`
2. `config/default/macros/<kind>/<name>.<ext>`

詳細:

- `/mnt/p3/macros/` は user-edited runtime macro。
- `config/default/macros/` は fallback / sample / factory default。
- `/mnt/p3/kml/`、`config/default/kml/`、`/mnt/p3/qmk_macro/`、`config/default/qmk_macro/` は初期採用しない。既存 script directory と同じ直下配置に見えるため、macro runner の種類が増えるほど owner が曖昧になる。
- 初期テンプレートは `config/default/macros/kml/example.kml` と `config/default/macros/qmk/example.qmk` を候補にし、実装時に parser subset と合わせて内容を決める。
- import/export で raw Vial macro buffer を保持する `settings.vial_macro_buffer` とは分ける。
- KML と QMK macro compatible syntax は directory も runner も分ける。
- macro file name は `[A-Za-z0-9_.-]{1,64}` に限定する。

## Runner boundary

KML runner:

- KML syntax の parser / validator / executor を持つ。
- host layout / IME 依存が出る text send は安全設計を別途参照する。
- script shell は実行しない。

QMK macro compatible runner:

- QMK macro buffer import/export とは別に、text representation を validate / dry-run / execute する。
- Vial raw macro buffer をそのまま runtime runner の source of truth にしない。
- 非対応 command は warning として落とし、silent 実行しない。
- 初期対応 syntax は `SEND_STRING("...")`、`TAP_CODE(KC_*)`、`TAP_CODE16(TO(n))`、`REGISTER_CODE(KC_*)`、`UNREGISTER_CODE(KC_*)`、`WAIT_MS(n)` に限定する。
- `WAIT_MS(n)` は QMK `SS_DELAY(ms)` / JSON macro `delay` 相当の timing step として扱い、host IME 反映待ちなどのために sequence 内へ明示する。
- Touch panel layer switch 用には既存の QMK / Vial 互換 `TO(n)` を `TAP_CODE16(...)` 経由で扱う。別名の HIDloom 拡張 command は追加せず、arbitrary action 実行へは広げない。
- Touch panel の `あいう` / `ABC` / `☆123` などの表示は macro file ではなく touch panel profile の `action_labels` が owner になる。runner は label を解釈しない。
- QMK C macro の compile / preprocessor / arbitrary C、Dynamic Macro、Vial advanced macro command は対象外にする。

共通:

- runner input は `{name, path, syntax, dry_run, output}` 相当の構造化 request にする。
- runner result は `ok` / `skipped` / `error`、`exit_code`、`events`、`warnings` を返す。
- `dry_run=true` では parser / validation / event expansion だけ行い、出力しない。
- runner は `logicd` の output path を使い、USB / BLE / uinput / `key_events.sock` へ直接書かない。`events` を `logicd` に返し、`logicd` が既存 output processor へ渡す。
- `i2cd` 通知は開始 / 正常終了 / validation error / runtime error の summary に限定し、macro event 本体は流さない。
- output switch / reload / emergency release で実行中 macro を中断できる必要がある。
- system / connectivity / power action は macro runner の中からは初期対象外にする。

## HTTP editor boundary

- 初期は Script viewer を `script / kml / qmk_macro` の編集 UI へ広げない。
- 初期 UI は read-only file picker、syntax label、validation / dry-run 結果の表示に留める。
- shell script は保存しない。
- 実行 button は初期実装では作らない。
- import/export は file 単位を第一候補にし、Vial raw macro buffer と混同しない。

## Vial / keymap boundary

- first slice では keycode を Vial custom space に追加しない。
- `config/default/keycodes.json` / `config/default/vial.json` に `KC_KMLn` / `KC_QMn` 表示名を追加しない。
- HTTP key picker では実装前候補として `KML(name)` / `QMK_MACRO(name)` の validation 表示だけを扱い、通常 keycode 一覧には混ぜない。
- 将来 Vial custom keycode へ出す場合の表示名は `KML 0`-`KML 7` / `QMK Macro 0`-`QMK Macro 7` とし、slot -> name mapping を同じ実装単位で追加する。
- `.vil` import/export では unknown custom action になっても壊れない warning を出す。
- `KC_KMLn` / `KC_QMn` は、slot -> name mapping の保存場所が決まるまで実装しない。

## Safety / non-goals

- Shell script 実行機能ではない。
- `KC_SHn` の置き換えではない。
- Vial raw macro buffer を直接編集 / 実行する機能ではない。
- host IME / Unicode / Send String 高度化は [input/unicode-send-string-safety-design.md](../input/unicode-send-string-safety-design.md) 側で扱う。
- first slice では keycode を Vial custom space に追加しない。

## Test scope

設計 first slice では doc test で固定する。
実装へ進む場合は以下を追加する。

- parser test: KML と QMK macro compatible subset を別 parser として扱い、syntax を混ぜない。
- runner test: `dry_run=true` が出力しないこと、`exit_code` / `warnings` / `events` が返ること。
- keycode dispatch test: `KML(name)` / `QMK_MACRO(name)` action validation と、`KC_KMLn` / `KC_QMn` が first slice で無効なこと。
- lookup order test: `/mnt/p3/macros/<kind>/` が `config/default/macros/<kind>/` より優先され、legacy `/mnt/p3/kml/` / `/mnt/p3/qmk_macro/` を読まないこと。
- i2cd notification test: summary だけを通知し、macro event 本体を送らないこと。
- `/mnt/p3` runtime macro と `config/default/` fallback の lookup order。
- KML と QMK macro compatible runner の directory separation。
- script / system / connectivity action を macro runner から初期除外する validation。
- Vial custom action 64 枠を超えないこと。
- output switch / reload / emergency release で実行中 macro を中断すること。

## 2026-06-10 lookup / validation groundwork

`daemon/logicd/macro_integration.py` を追加し、`KML(name)` / `QMK_MACRO(name)` の
read-only groundwork を固定した。helper は runner を実行せず、HID report も送らない。

完了した範囲:

- action name validation と `KML(name)` / `QMK_MACRO(name)` parse。
- `/mnt/p3/macros/<kind>/<name>.<ext>` を `config/default/macros/<kind>/<name>.<ext>` より優先する lookup order。
- legacy `/mnt/p3/kml/`、`config/default/kml/`、`/mnt/p3/qmk_macro/`、`config/default/qmk_macro/` を読まない boundary。
- KML first subset: `tap KC_*`、`down KC_*`、`up KC_*`、`delay ms`、`text ...`。
- QMK macro first subset: `SEND_STRING("...")`、`TAP_CODE(KC_*)`、`TAP_CODE16(TO(n))`、`REGISTER_CODE(KC_*)`、`UNREGISTER_CODE(KC_*)`、`WAIT_MS(n)`。
- script / system / connectivity / power / arbitrary C 相当 token の rejection。
- `macro_integration.runner_plan.v1` の dry-run plan。`real_run_allowed=false`、`sends_hid_reports=false`、`direct_key_events_sock_write=false` を固定する。

未実装のまま残す範囲:

- 実 runner 接続。
- `KC_KMLn` / `KC_QMn` の Vial custom slot keycode。
- 実 macro 実行中の output switch / reload / emergency release cancel。

## Implementation gate

実装へ進める条件:

- KML syntax と QMK macro compatible syntax の最小仕様が分かれている。
- 保存先と lookup order が決まっている。
- first slice は runtime action 名だけにすることが決まっている。
- macro runner が shell script 実行や system action と混ざらない。

実装しない条件:

- `KC_SHn` と同じ shell script runner として扱う必要がある。
- Vial raw macro buffer を runtime source of truth にしないと成立しない。
- host IME / Unicode / Send String の高度化を同時に入れないと成立しない。
- output switch / emergency release で安全に中断できない。
