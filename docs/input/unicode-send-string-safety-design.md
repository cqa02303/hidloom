# Unicode / Send String safety design

作成日: 2026-06-01

この文書は QMK Unicode / Send String 相当を高度化する前の安全設計です。
2026-06-01 時点では実行 runner へは進まず、host layout / IME / OS mode / macro runner との境界、初期対応 syntax、誤入力時の中断条件、テスト範囲を固定します。
first slice として `daemon/logicd/text_send_safety.py` と `GET /api/interaction/text-send-safety` に read-only safety metadata と named text content validation を追加済みです。
2026-06-03 の次段では、同 payload を `text_send.safety.v2` へ更新し、explicit host profile gate、real-send gate、HTTP warning scope、Interaction summary の preview/no-op 表示を追加しました。
続く cancel path first slice として `TextSendRuntimeState`、ctrl `TEXT_SEND_CANCEL`、output switch / config reload / daemon shutdown からの cancel hook を追加しました。さらに active cancel / emergency release では `release_all()` と keyboard `null_report` を通し、runtime state に `zero_report_sent` を記録します。runner timeout contract として `deadline_at` / `runner_timeout` cancel も固定済みです。
Action-level preflight として `POST /api/interaction/text-send-safety/plan` を追加し、任意の action から `text_send.real_send_plan.v1` を read-only に返します。Runner 実装前の dry-run として `text_send.tap_dry_run.v1` を追加し、`GET /api/interaction/text-send-safety` の capability metadata と plan 内の preview の両方で `linux_ctrl_shift_u` と `windows_ime_hex_f5` の keyboard tap sequence を read-only に preview します。dry-run は HID report を送信しません。
2026-06-03 の touch flick first-send では、`windows_ime_hex_f5` を `logicd_keyboard_tap_runner` の最小実送信 sequence として使い、`U+3042` を `KC_3` `KC_0` `KC_4` `KC_2` `KC_F5` `KC_ENTER` に展開できることを確認しました。実 host 入力では即時連打だと最初の `３` だけが入る場合があり、0.180 秒の key tap 間隔を入れた sequence で `あ` 入力を確認しました。末尾の `KC_ENTER` は IME code conversion の確定用で、アプリ側への送信は別 action の `C(KC_ENTER)` などで扱います。
2026-06-10 に最小実行 runner として `daemon/logicd/text_send_runner.py` を追加しました。runner は `text_send.real_send_plan.v1` が `real_send_allowed=true` を返す action だけを対象にし、shell / system / connectivity / power action は実行しません。送信は既存の `dispatch_action_event` を使った keyboard tap のみで、`TextSendRuntimeState` の busy guard、timeout、cancel state を共有します。touch flick の text dispatch は、runner が許可する `U+XXXX` / `TEXT(name)` / `SEND_STRING(name)` をこの runner へ流し、許可されない Unicode action は従来の `romaji_us_ime` composition fallback に留めます。host OS への実入力 smoke は未実施です。
2026-06-12 に `/api/status.text_send` を追加し、`GET /api/interaction/text-send-safety` の詳細 payload から unicode mode、explicit host profile、runner ready、named text validation count、blocking reasons を運用確認向けに要約できるようにしました。実入力 smoke 前に mode 未設定、runner 未接続、host profile 未設定を status panel で切り分けます。
2026-06-13 に `script/text_send_smoke_sequence.py` を追加しました。これは `U+3042` と `TEXT(kana_a)` を
同じ `text_send.real_send_plan.v1` gate で確認し、dry-run では `KC_3` `KC_0` `KC_4` `KC_2`
`KC_F5` `KC_ENTER` の sequence だけを表示します。実送信は `--send --confirm SEND_TEXT_SMOKE_TO_FOCUSED_HOST`
を明示した時だけ行い、デフォルトの出力先は Windows JIS / US split の通常文字経路に合わせて
`us_sub_keyboard` broker です。host 側の安全な入力欄へ focus していることを operator が確認するまで、
実キー送信は行いません。

## Goal

- Unicode / Send String を、危険な一括送信ではなく中断可能な入力補助として扱う。
- host OS / IME / keyboard layout に依存する挙動を明示する。
- text send は host IME の一般変換 engine を置き換えず、literal character / fixed snippet の安全な送信に限定する。
- KML / QMK macro runner、Autocorrect、Vial macro import/export と責務を混ぜない。
- output switch / reload / emergency release で stale input が残らないようにする。

## Current baseline

- `daemon/logicd/macro.py` には local `U+XXXX` style action の処理がある。
- 通常 key action / modifier wrapper / macro dispatch は既存 output path を使う。
- host layout / IME state は現時点では自動検出しない。
- `.vil` macro buffer import/export は runtime text send の source of truth ではない。
- `daemon/logicd/text_send_safety.py` は `U+XXXX` / `SEND_STRING(name)` / `TEXT(name)` / `UC_MODE(mode)` を分類し、`daemon/logicd/text_send_runner.py` が許可済み action だけを keyboard tap sequence として実行する。
- `GET /api/interaction/text-send-safety` は `mode=none`、explicit host profile、real-send gate、named storage、content validation、cancel trigger、HTTP warning を read-only に返す。
- `POST /api/interaction/text-send-safety/plan` は `{ "action": "TEXT(name)" }` から action-level preflight plan を返す。HTTP route 自体は実送信しない。
- `text_send.tap_dry_run.v1` は実 runner 実装前の keyboard tap preview だけを返す。`sends_hid_reports=false`。
- `GET /api/interaction/text-send-safety` は `tap_dry_run.supported_modes` / `unsupported_modes` を返す。
- Interaction tab は `Text Send` / `Host Profile` の read-only status と、blocking reason を summary に表示する。
- `TextSendRuntimeState` は実行中 runner 名、`deadline_at`、最後の cancel reason、最後の zero report reason を持つ。runner 本体はこの state を busy / timeout / cancel guard として使う。
- ctrl `TEXT_SEND_CANCEL` は `explicit_cancel` / `emergency_release` などの cancel reason を正規化して runtime state を clear する。
- logicd の output switch、SIGHUP config reload、daemon shutdown は text send cancel hook を呼ぶ。
- active text send cancel と `emergency_release` は `release_all()` 後に keyboard `null_report` を送る。送信済み status は `zero_report_sent=true` として返す。
- `runner_timeout` は `cancel_if_timed_out(now)` で active runner を clear し、同じ zero report path に入る。
- 2026-06-01 に `<keyboard-host>` / Windows 11 / Microsoft IME で、既存 local `U+XXXX` path の実入力 smoke を確認済み。`tools/matrix_action_runtime.py` で一時 remap した `7,0` から `hex -> F5 -> Enter` の IME code conversion path を通し、`あいうえお、。ーがぱぁゃア日本語` が入力できた。

## Candidate actions / syntax

初期候補:

| action | 意味 | 初期扱い |
| --- | --- | --- |
| `U+3042` | Unicode code point 送信 | 既存 local action の延長。OS mode が必要。 |
| `SEND_STRING(name)` | named string を送る | 候補。直接文字列を action 名に埋め込まない。 |
| `TEXT(name)` | named text snippet を送る alias | 候補。`SEND_STRING(name)` へ正規化するか検討。 |
| `UC_MODE(mode)` | Unicode 入力方式を切り替える | 候補。初期実装では persistent にはしない。 |

初期実装では、keymap action に任意の長文を直接入れません。
保存する場合は named entry を使います。

## Storage policy

候補:

```json
{
  "settings": {
    "send_strings": {
      "hello": {
        "text": "hello",
        "mode": "tap_sequence",
        "enabled": true,
        "confirm": false
      }
    },
    "unicode": {
      "mode": "none"
    }
  }
}
```

方針:

- long text は keymap action ではなく named entry として保存する。
- `mode=none` の時、Unicode action は warning または no-op にする。
- host OS / IME / layout が未確定なら default で大きな文字列送信を有効にしない。
- Vial raw macro buffer と send string storage は分ける。

## Host mode boundary

Unicode 入力方式は host に依存する。

候補:

| mode | 備考 |
| --- | --- |
| `none` | Unicode 送信しない。default 候補。 |
| `linux_ctrl_shift_u` | Linux desktop の `Ctrl+Shift+u` 入力候補。 |
| `mac_unicode_hex` | macOS Unicode Hex Input 前提。host 設定依存。 |
| `win_alt_code` | Windows Alt code 系。layout / numpad 依存が大きい。 |
| `tap_sequence` | ASCII / keycode に展開できる範囲だけ tap sequence で送る。 |

自動 OS 判定はしない。
Host profile が将来入っても、Unicode mode は manual profile の明示設定として扱う。
`settings.unicode.host_profile` / `settings.unicode.profile` / `settings.unicode.manual_host_profile` のいずれかが明示されるまで、real send は preview/no-op として表示する。
既存 local `U+XXXX` path は Windows 11 / Microsoft IME の `hex -> F5 -> Enter` 入力で smoke 済みですが、将来の設定名はまだ固定しません。
newline は Unicode code point 送信ではなく、`KC_ENTER` などの key action として扱います。

## Conversion ownership

Unicode / Send String runner は、かな漢字変換 engine ではありません。

- keyboard-side GUI は gesture や UI 操作を action / code point / named text に解決する。
- host IME は composition state、candidate selection、dictionary、learning、application context を持つ。
- `U+XXXX` は literal character の送信経路として扱い、host IME の candidate UI を代替しない。
- fixed phrase や固定 kanji は named `TEXT(name)` と warning / confirmation で扱えるが、通常文の変換 owner にはしない。
- かな漢字変換を keyboard-side で持たないことで、host 側の変換状態との二重管理、辞書 privacy、rollback の問題を避ける。

## Runner boundary

- Send String runner は shell script を実行しない。
- KML / QMK macro compatible runner とは別 module にする候補。
- Autocorrect は Send String runner を利用する可能性はあるが、辞書 / trigger / replacement owner は別にする。
- Macro runner が text send を呼ぶ場合も、中断条件は共通にする。
- system / connectivity / power action は text runner からは初期対象外にする。

## Minimal Real-Send Step Contract

`text_send.real_send_plan.v1` is read-only metadata. It defines the smallest allowed
real-send path before a runner is connected.

Allowed minimal scope:

- `begin_runtime_state`
- `emit_keyboard_taps_only`
- `cancel_on_output_switch`
- `cancel_on_config_reload`
- `cancel_on_emergency_release`
- `cancel_on_runner_timeout`
- `send_zero_report_on_cancel`

Forbidden steps:

- `shell_script`
- `system_action`
- `connectivity_action`
- `power_action`
- `direct_text_in_keymap`
- `vial_macro_buffer`
- `newline_codepoint`

`TEXT(name)` / `SEND_STRING(name)` must resolve `settings.send_strings[name]`,
validate the named entry, require explicit host profile, require non-`none`
Unicode mode, and require `text_send_runner.connected=true` before the plan can
say `real_send_allowed=true`. This still does not execute HID reports; it only
states that the future runner has enough metadata to use the already-defined
cancel / timeout / zero-report path. Newline remains a key action such as
`KC_ENTER`, never a Unicode code point.

## Runner Connection / No-Op Release Contract

`text_send.runner_connection.v1` is read-only metadata for the future runner
connection. `text_send_runner.connected=true` alone is not enough to leave
preview/no-op.

Required runner connection:

- `method=logicd_keyboard_tap_runner`
- `target=active_output_keyboard`
- `cancel_path=text_send_runtime_state`
- `zero_report_on_cancel=true`
- finite `timeout_sec`

No-op release conditions:

- `explicit_host_profile`
- `unicode_mode_not_none`
- `runner_connected`
- `runner_method_logicd_keyboard_tap_runner`
- `runner_target_active_output_keyboard`
- `runner_cancel_path_text_send_runtime_state`
- `runner_zero_report_on_cancel`
- `runner_timeout_configured`
- `named_entry_valid_when_required`

If any condition is missing, `TEXT(...)` / `SEND_STRING(...)` remains
preview/no-op. The runner may only emit keyboard tap reports through the active
keyboard output path, and it must reuse `TextSendRuntimeState`,
`TEXT_SEND_CANCEL`, runner timeout, and the zero-report-on-cancel path.

## Safety policy

中断 / clear 条件:

- output switch
- config reload
- keymap reload
- emergency release / stuck-key recovery
- daemon shutdown
- explicit cancel action
- runner timeout

制限候補:

- 初期 max length は短めにする。
- control character は初期禁止。
- newline / tab は明示 opt-in にする。
- hidden / zero-width character は warning にする。
- password / secret 用途には使わないと明記する。
- HTTP UI では preview と warning を出す。

## UI policy

HTTP:

- 初期は read-only design / validation helper から始める。
- editor を作る場合も、keymap action に長文を直接保存しない。
- dangerous / long / newline / control char warning を出す。
- host mode が `none` の時は Unicode action を warning 表示する。
- explicit host profile が未設定の時は `explicit_host_profile_required` を warning 表示する。
- Send String runner 未接続の時は `send_string_runner_not_connected` を warning 表示し、`TEXT(...)` / `SEND_STRING(...)` の実送信を許可しない。

OLED:

- 長文表示はしない。
- 実行中 / canceled / failed の短い alert だけ候補。

LED:

- 専用 overlay は作らない。

## Relation to other features

| feature | 境界 |
| --- | --- |
| KML / QMK macro keycode | runner は別。KML / QMK macro から Send String を呼ぶ場合も中断条件を共有する。 |
| Autocorrect | 辞書 / trigger owner は別。replacement 実行に Send String を使う可能性だけある。 |
| Vial macro import/export | raw macro buffer は互換保存用。Send String storage の source of truth にはしない。 |
| Host profile | Unicode mode を manual host profile の一部にする候補。ただし自動 OS detection はしない。 |

## QMK Unicode Map Groundwork

2026-06-10 の remote-only slice で `daemon/logicd/qmk_unicode.py` を追加した。
この helper は `UC(c)` / `UM(name)` / `UP(name,next)` / `UC_*` mode action を
`qmk_unicode.action_plan.v1` として read-only に分類する。`settings.unicode.map`
または `settings.unicode_map` の named codepoint を `qmk_unicode.map.v1` として
検証し、surrogate / `0x10FFFF` 超過 / 空名 / 重複正規化を拒否する。

QMK Unicode はまだ実 HID 送信や永続 mode mutation を行わない。実行 gate は
explicit host profile と non-`none` Unicode mode を要求し、tap preview は既存の
`text_send.tap_dry_run.v1` を使う。`UC_LINX` / `UC_WIN` / `UC_WINC` などの mode action
は preview-only として扱い、`UC_MAC` / `UC_EMAC` や cycle action は未対応 reason を返す。

## Static tests to add with implementation

設計 first slice では doc test と read-only helper test を追加済みです。
runner 実装へ進む場合は以下を追加する。

- [x] action name classification: `U+XXXX`, `SEND_STRING(name)`, `TEXT(name)`、`UC_MODE(mode)`。
- [x] named text entry name validation。
- [x] named text entry content validation: length、control char、newline opt-in、zero-width warning。
- [x] Windows 11 / Microsoft IME で既存 local `U+XXXX` path の real-device smoke。
- [x] keyboard-side GUI conversion と host IME conversion の責務分担。
- [x] `unicode.mode=none` で Unicode action が実行されない。
- [x] explicit host profile 未設定時に real send gate が閉じ、HTTP warning が出る。
- [x] Interaction summary に Text Send preview/no-op と Host Profile required が表示される。
- [x] output switch / reload / explicit cancel / daemon shutdown の cancel hook が runtime state を clear する。
- [x] active cancel / emergency release で `release_all()` と keyboard `null_report` を送る。
- [x] zero report 送信済み status を `zero_report_sent` / `last_zero_report_reason` として残す。
- [x] runner timeout は `deadline_at` / `runner_timeout` cancel / zero report path で固定する。
- 実送信 step の最小範囲を固定する。
- Vial macro buffer を Send String storage と混ぜない。
- script / system / connectivity / power action を text runner から実行しない。

- [x] `text_send.real_send_plan.v1` fixes the minimal real-send step scope.
- [x] forbidden steps include `shell_script`, `system_action`, `connectivity_action`, `power_action`, `direct_text_in_keymap`, `vial_macro_buffer`, and `newline_codepoint`.
- [x] `text_send.runner_connection.v1` fixes the runner connection method and no-op release conditions.
- [x] `text_send.tap_dry_run.v1` fixes the first read-only tap-sequence preview before the real runner.
- [x] `qmk_unicode.map.v1` validates QMK Unicode named map entries without sending HID reports.
- [x] `qmk_unicode.action_plan.v1` classifies `UC(c)`, `UM(name)`, `UP(name,next)`, and `UC_*` as read-only action plans.
- [x] `script/text_send_smoke_sequence.py` validates `U+3042` and `TEXT(kana_a)` smoke sequences with dry-run default and an explicit real-send confirmation phrase.

## Implementation gate

実装へ進める条件:

- 初期 host mode と default `none` 方針が決まっている。
- named string storage と validation が決まっている。
- runner cancel path が output switch / reload / emergency release とつながる。
- KML / QMK macro / Autocorrect との責務境界が維持できる。

実装しない条件:

- host OS / IME 自動判定が必須になる。
- keymap action に任意長の文字列を直接保存する必要がある。
- secret / password 送信用途を想定する必要がある。
- runner cancel が実装できない。

## 2026-06-10 runner first slice

完了した範囲:

- `daemon/logicd/text_send_runner.py` は `text_send.real_send_plan.v1` を実行前 gate として使う。
- `real_send_allowed=false` の action は keyboard report を出さず blocked を返す。
- `TEXT(name)` / `SEND_STRING(name)` は named entry validation、explicit host profile、Unicode mode、runner connection が揃う時だけ実行する。
- `windows_ime_hex_f5` と `linux_ctrl_shift_u` の dry-run tap sequence を、既存 `dispatch_action_event` の press / release へ変換する。
- runner 中は `TextSendRuntimeState.active=true` とし、busy runner は `text_send_runner_busy` で拒否する。
- timeout 到達時は `runner_timeout` cancel state に入る。
- touch flick text dispatch は、許可済み text-send action を runner に流す。runner が許可しない Unicode action は既存 `romaji_us_ime` composition fallback を維持する。

実機確認待ち:

- Windows 11 / Microsoft IME / US keyboard で `TEXT(kana_a)` と `U+3042` が期待通り入力されること。
- 0.180 秒 gap が実機で過不足ないこと。
- 実入力中の `TEXT_SEND_CANCEL`、output switch、config reload、emergency release が host 側に stuck key を残さないこと。

## 2026-06-13 guarded smoke helper

確認だけ行う dry-run:

```bash
python3 script/text_send_smoke_sequence.py
python3 script/text_send_smoke_sequence.py --action TEXT(kana_a)
```

実機へ送る場合は、host 側で安全なテキスト入力欄へ focus してから以下を使う。

```bash
python3 script/text_send_smoke_sequence.py --send --confirm SEND_TEXT_SMOKE_TO_FOCUSED_HOST
python3 script/text_send_smoke_sequence.py --action TEXT(kana_a) --send --confirm SEND_TEXT_SMOKE_TO_FOCUSED_HOST
```

この helper は config を永続変更しません。引数 `--settings` を指定しない場合は、bounded smoke 用の
ready fixture を使って plan gate と tap sequence を検証します。実運用の default config は
`unicode.mode=none` / host profile 未設定のままにし、意図しない文字列送信を防ぎます。
