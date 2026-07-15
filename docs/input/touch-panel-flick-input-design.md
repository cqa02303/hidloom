# Touch Panel Flick Input Design

作成日: 2026-06-01

この文書は 4.3 inch `osoyoo-4.3` touch-panel-only profile で、スマートフォン風のフリック入力を追加するための設計 TODO です。
既存の `https://127.0.0.1/?keyboard=1` kiosk keyboard、`config/default/touch-panel/osoyoo-4.3/` の 800x480 profile、PointerEvent 低遅延入力を壊さずに、小画面向けの日本語入力導線を足すことを目的にします。
2026-06-01 first slice として、`GET /api/touch-panel/flick` の read-only metadata、`osoyoo-4.3` profile guard、browser-side flick preview/no-op UI、`pointercancel` / tab switch / shutdown menu cancel hook を追加済みです。
800x480 kiosk 向けには fixed fullscreen panel、4-row pad grid、6-column IME controls、ellipsis / nowrap の text fit 制約を追加し、button text が viewport からはみ出さない静的条件を固定しています。
`POST /api/touch-panel/flick/resolve` は pad/control + direction から最終 resolved action と disabled `dispatch_event` だけを返し、preview state を logicd 送信用 payload に混ぜない契約を固定しています。
browser-side preview の pointerup / IME control click もこの endpoint を通し、`dispatch_event.enabled=false` / `dispatch=preview_noop` の envelope だけを表示します。通信失敗時は local preview fallback に閉じ、実送信は行いません。
`daemon/logicd/touch_flick_dispatch.py` は logicd-facing guard として、`preview_state` / requested / resolved direction を含む payload を拒否し、現行 `preview_noop` event は blocked preview-only として扱います。`dispatch_touch_flick_event` は明示 `enabled=true` / `dispatch=tap_action` / `output=keycode` の final action を normal input dispatcher の press/release へ変換します。`output=text` は `POST /api/interaction/text-send-safety/plan` の runner / host profile gate を満たした時だけ `text_send.real_send_plan.v1` の keyboard tap sequence へ展開します。
`POST /api/touch-panel/flick/dispatch` は HTTP dispatch bridge として resolver済み `event` object だけを `TOUCH_FLICK` command / ctrl command へ転送します。これにより、HTTP から logicd へ送る段では gesture preview ではなく final dispatch envelope だけを受け付けます。
2026-06-03 に first send slice として、`GET /api/touch-panel/flick` の `dispatch_policy` は
`browser_may_call_dispatch=true` / `browser_default_enabled=false` / `browser_requires_local_enable=true` になりました。
ブラウザ UI は `送信: ON` を明示した時だけ dispatch bridge を呼びます。送信対象は `output=keycode` または
preflight 済みの `output=text` final action です。text output は dispatch 前に
`POST /api/interaction/text-send-safety/plan` の action-level preflight を通し、`real_send_allowed=true` の時だけ dispatch します。
`host_ime_profile` は Windows 11 / Microsoft IME の候補 profile と `あいうえお、。ーがぱぁゃア日本語` の `local U+XXXX` smoke 結果を read-only に返しますが、`active_profile=None` / `explicit_profile_required=true` のため、ブラウザ UI は `host-profile-required` を表示して実送信しません。

## Goal

- 800x480 / 4.3 inch で、QWERTY より押しやすい kana flick layer を提供する。
- 既存 `osoyoo-4.3` profile の QWERTY / number / nav layer は残す。
- flick 判定は browser-side UI helper に閉じ、`logicd` へは最終 action だけを送る。
- keyboard-side GUI conversion は gesture から kana / punctuation / key action を選ぶ resolver までに留め、かな漢字変換、candidate selection、辞書学習は host IME 側の責務にする。
- host IME / layout の自動判定はしない。日本語入力は `KC_KANA` / `KC_LANG1` / macro token など既存 action と明示設定で扱う。

## Prerequisite

かなを直接入力する flick mode は、先に UTF / Unicode / Send String の安全な入力経路が必要になる可能性が高いです。
そのため実装順は [unicode-send-string-safety-design.md](unicode-send-string-safety-design.md) を先行条件にします。
2026-06-01 に `<keyboard-host>` / Windows 11 / Microsoft IME で、既存 local `U+XXXX` path から `あいうえお、。ーがぱぁゃア日本語` の実入力 smoke は通っています。
この結果は Windows IME profile 向け kana / punctuation / kanji 出力の候補経路として使えますが、host profile 明示、runner cancel path、UI warning が接続されるまでは flick UI 側から default enabled にしません。

- UTF / Unicode action の host mode と default `none` 方針が決まっている。
- named text / send string storage と validation が決まっている。
- runner cancel path が output switch / reload / emergency release / pointercancel と矛盾しない。
- host IME / layout warning を HTTP UI へ出せる。
- flick pad の kana / text output は text-send runner / host profile / cancel path が揃うまで read-only metadata / preview までに留める。
- IME control などの keycode output は、明示的な `送信: ON` の時だけ `TOUCH_FLICK` dispatch bridge へ送る。

## Non-goals

- 物理 matrix scan の gesture 化はしない。
- 既存 keymap schema を壊さない。
- host IME 変換中かどうかを検出しない。
- keyboard-side の一般かな漢字変換 engine、辞書、学習、candidate UI は作らない。
- 実装初期段階では multi-touch chord や handwriting を扱わない。
- フリック候補を `logicd` runtime state として持たない。

## UI model

初期候補は 12-key phone-style pad です。

```text
あ か さ
た な は
ま や ら
IME わ BSPC
```

各 pad は center / up / right / down / left の最大 5 action を持ちます。
例:

| key | center | up | right | down | left |
| --- | --- | --- | --- | --- | --- |
| あ | あ | う | え | お | い |
| か | か | く | け | こ | き |
| さ | さ | す | せ | そ | し |
| わ | わ | を | ん | ー | 、 |

小書きや濁点 / 半濁点は first slice では固定しません。
後続で、long press / modifier pad / candidate popup のどれで扱うかを実機の指サイズと誤爆率で決めます。
PC host IME 向け入力では、スマホフリックと違って host 側の composition を操作する必要があります。
そのため `変換`、`無変換`、`確定`、候補選択の操作を flick pad または IME control pad に必ず用意します。

## Event boundary

フリック入力は `daemon/http/static/keyboard.js` 側の pointer flow を利用します。

- `pointerdown`: pad center と開始座標を記録する。
- `pointermove`: threshold を超えたら direction preview を出す。
- `pointerup`: center / up / right / down / left の最終 action を決める。
- `pointercancel` / tab switch / shutdown menu: preview を消し、action を送らない。

`logicd` へは既存の keydown / keyup 相当または macro action 経路で最終 action だけを渡します。
フリック中の preview や direction state は HTTP UI が owner で、保存 payload には混ぜません。
2026-06-01 first implementation slice として、`resolve_flick_pad_action` / `resolve_ime_control_action`
の read-only helper を追加し、pad/control から最終 action だけを `preview_noop` dispatch として解決する契約を固定しました。
browser-side preview も `resolveTouchFlickPreviewAction` / `resolveTouchFlickImePreviewAction` を通し、
API helper と同じ final action only の形へ寄せています。
server-side resolve endpoint の `POST /api/touch-panel/flick/resolve` は `resolved_action` と
`dispatch_event` を返しますが、`dispatch_event.enabled=false` / `dispatch=preview_noop` のままにし、
Unicode / Send String runner と host IME profile warning が接続されるまで実送信しません。
browser-side の `resolveTouchFlickDispatchEnvelope` は `csrfFetch` でこの endpoint を呼び、
unsafe envelope や通信失敗時は `resolve_endpoint_unavailable` の local preview fallback に落とします。
HTTP dispatch bridge の `POST /api/touch-panel/flick/dispatch` は `event` object だけを受け取り、
`preview_state` / requested / resolved direction を拒否してから `TOUCH_FLICK` ctrl command へ渡します。
`dispatch_policy` は `allowed_event.enabled=true` / `dispatch=tap_action` / `output=keycode` だけを将来の送信候補にし、
`explicit_host_profile`、`host_ime_warning`、`unicode_send_string_runner_cancel_path`、`text_send_plan_preflight` が揃うまで
browser UI からはまだ呼ばず、resolve endpoint の disabled envelope を preview 表示する段階に留めます。
`host_ime_profile.profiles[]` には Windows 11 / Microsoft IME profile 候補を read-only で置き、
`KC_SPC` / `KC_ENTER` / `KC_ESC` / `KC_UP` / `KC_DOWN` の control mapping と Unicode smoke sample を表示できます。

## Action output

初期実装では action output を 2 段階で検討します。

1. ASCII / keycode で表せるものは既存 key action と同じ tap として送る。
2. kana / punctuation は [unicode-send-string-safety-design.md](unicode-send-string-safety-design.md) の UTF / Unicode / Send String 経路が安全に扱えることを確認してから、macro token または explicit action として扱う。

日本語かなを直接送る場合は、host ごとに IME の状態や layout が違うため default enabled にしません。
`KC_KANA` / `KC_LANG1` を出す IME toggle pad は作れますが、host IME state の自動同期はしません。
2026-06-15 の Windows 実機確認で、Microsoft IME の
「かな入力/ローマ字入力を Alt + カタカナひらがなローマ字キーで切り替える」を ON にすると、
`Alt + KC_KANA` と `Alt + KC_HENKAN` がかな入力 / ローマ字入力 toggle として動作した。
さらに USB / BLE keyboard descriptor は LED Output usage `Kana` まで宣言済みで、
`logicd.host_led_output` も `kana` bit を decode できるため、host から返る Kana LED output を
かな入力状態の advisory signal として使えます。
Kana LED は toggle 直後に即時反応せず、かな入力 ON 後の次の 1 key 入力で反応する場合があります。
そのため touch flick のかな profile では、かな入力を本線にしつつ、Kana LED を遅延ありの
safety guard / warning signal として扱います。
JP profile では touch flick の変換 / 無変換 control に dedicated key を使える可能性が高い。
Windows 11 / Microsoft IME では existing local `U+XXXX` path の `hex -> F5 -> Enter` smoke が通っているため、次段の kana action は named `TEXT(kana_...)` から explicit Windows IME profile へ解決する候補にします。
改行 / Backspace / Enter は text code point ではなく key action として扱います。

## Macro-backed Layer Keys And Display Labels

Touch panel の layer switch key は、実行 sequence と画面表示を分離します。
基板を持つ通常 keyboard でも同じ layer switch sequence を使えるよう、IME mode 切替や layer 移動の実行は
QMK macro compatible action / local macro action 側へ寄せます。Touch panel profile は、その action をどう表示するかだけを
`action_labels` として持ちます。

例:

```json
{
  "action_labels": {
    "QMK_MACRO(layer_kana)": "あいう",
    "QMK_MACRO(layer_alpha)": "ABC",
    "QMK_MACRO(layer_symbol)": "☆123"
  }
}
```

touch-panel keymap の左列は、`TO(0)` / `TO(1)` / `TO(2)` を直接置く代わりに macro action を置く候補にします。

```json
[
  "QMK_MACRO(layer_symbol)",
  "KC_FLICK(0,0)",
  "KC_FLICK(0,1)",
  "KC_FLICK(0,2)",

  "QMK_MACRO(layer_alpha)",
  "KC_FLICK(0,3)",
  "KC_FLICK(0,4)",
  "KC_FLICK(0,5)",

  "QMK_MACRO(layer_kana)",
  "KC_FLICK(0,6)",
  "KC_FLICK(0,7)",
  "KC_FLICK(0,8)"
]
```

macro の中身は QMK macro compatible runner の source of truth に置きます。
`INT0` / `INT1` と呼んでいた IME 切替は、この project では次の keycode として扱います。

| 意図 | keycode | 用途 |
| --- | --- | --- |
| 日本語 / かな入力側へ寄せる | `KC_LANG1` | `QMK_MACRO(layer_kana)` / `QMK_MACRO(layer_symbol)` の前置き tap |
| 英数入力側へ寄せる | `KC_LANG2` | `QMK_MACRO(layer_alpha)` の前置き tap |

QMK macro compatible subset の記述例:

```c
// layer_kana.qmk
TAP_CODE(KC_LANG1);
WAIT_MS(0);
TAP_CODE16(TO(0));

// layer_alpha.qmk
TAP_CODE(KC_LANG2);
WAIT_MS(0);
TAP_CODE16(TO(1));

// layer_symbol.qmk
TAP_CODE(KC_LANG1);
WAIT_MS(0);
TAP_CODE16(TO(2));
```

`TO(n)` は既存の QMK / Vial 互換 layer action として扱います。
QMK macro compatible runner では、通常の keycode tap と同じ入口で `TAP_CODE16(TO(n))` を受け付け、
touch panel / runtime layer action のために別名 command を増やさない方針にします。
first slice では Vial codec と同じく `0 <= n < 16` を対象にします。

`WAIT_MS(n)` は IME mode tap 後に host 側の切替反映を待つための任意 delay です。
QMK の `SEND_STRING(...)` で使う `SS_DELAY(ms)` や、QMK JSON macro の `{"action": "delay", "duration": ms}` に相当する timing step として扱います。
初期値は `WAIT_MS(0)` とし、Windows / macOS / Linux の実入力確認で `KC_LANG1` / `KC_LANG2` の直後に待ちが必要な場合だけ増やします。

表示解決は action 文字列ベースで行います。

1. keymap action が `QMK_MACRO(layer_kana)` なら、`action_labels` に一致する label `あいう` を使う。
2. `action_labels` に無い action は既存の `key_labels.json` / action label resolver に任せる。
3. 同じ action が layer0 / layer1 / layer2 のどこに現れても同じ label を表示する。

実行解決は macro runner 側で行います。

1. Web UI / matrix runtime が `QMK_MACRO(layer_kana)` を final action として送る。
2. QMK macro compatible runner が `KC_LANG1` を tap する。
3. runner が必要なら `WAIT_MS(n)` で host IME の反映を待つ。
4. runner が `TAP_CODE16(TO(0))` を QMK / Vial 互換 layer action として実行する。
5. Touch panel UI は layer0 表示へ切り替わり、左列の表示は `action_labels` に従って `☆123` / `ABC` / `あいう` のままになる。

この分離により、QMK macro action は物理 keyboard の keymap でも再利用できます。
Touch panel 固有の表示文言は `action_labels` に閉じるため、物理 keyboard 側の keycap / Vial 表示とは混ざりません。

`action_labels` は表示専用であり、実行内容や安全 policy を持ちません。
macro sequence の validation、delay、cancel、output switch / reload / emergency release の中断条件は
[macro/kml-qmk-macro-keycode-design.md](../macro/kml-qmk-macro-keycode-design.md) と
[macro/compatibility-plan.md](../macro/compatibility-plan.md) 側で扱います。

## Conversion Ownership

変換責務は hybrid にします。

- keyboard-side GUI: flick gesture、direction、modifier pad、小書き / 濁点 / 半濁点の補助、literal kana / punctuation / fixed snippet への解決だけを持つ。
- host IME: composition state、かな漢字変換、candidate selection、辞書、学習、application context を持つ。
- `U+XXXX` path: literal character を安全に送るための host-profile-specific runner として使い、一般的な日本語 IME engine の代替にはしない。

理由:

- host IME は既に文脈、辞書、候補 UI、学習、アプリごとの入力状態を持っている。
- keyboard-side で一般変換まで持つと、候補 UI、辞書更新、個人情報、取り消し、host との composition 二重管理が増える。
- 4.3 inch UI では候補一覧よりも、誤爆しにくい flick resolver と明示 warning のほうが重要。
- 定型句や固定 kanji は named `TEXT(name)` と explicit confirmation で扱えるが、通常入力の変換 owner にはしない。

## Host IME Controls

スマホフリックとの差分として、PC host IME の操作を第一級の UI として扱います。

必須操作:

- `変換`: host IME の conversion / next candidate を呼ぶ。US keyboard でも扱える `KC_SPC` を第一候補にする。
- `無変換`: dedicated JIS key は使わず、未変換のまま確定する US keyboard compatible action として `KC_ENTER` を使う。
- `確定`: current composition / candidate を確定する。通常は `KC_ENTER`。
- `候補選択`: candidate list 内の next / previous / direct pick を扱う。初期は `KC_SPC` / `KC_UP` / `KC_DOWN` / `KC_ENTER` の組み合わせを候補にする。
- `戻る / cancel`: composition や candidate list を閉じる。初期は `KC_ESC`。

配置方針:

- kana pad と同じ画面に最低限の `変換` / `無変換` / `確定` / `BSPC` を置く。
- 候補選択は dedicated IME control pad、long press、または nav layer のどれに置くかを 800x480 実機で確認する。
- `変換` / `無変換` / `確定` は text code point ではなく key action として扱う。
- host ごとに keycode semantics が違うため、US keyboard compatible keycodes (`KC_SPC` / `KC_ENTER` / `KC_ESC` / `KC_UP` / `KC_DOWN`) だけで Windows IME profile を先に実機 smoke し、他 host では warning / disabled を default にする。
- 2026-06-01 first implementation slice として、`GET /api/touch-panel/flick` に read-only `ime_controls` metadata を追加し、browser-side preview/no-op UI に IME control pad を表示する。実送信はまだ行わない。

## Profile / settings boundary

対象は `osoyoo-4.3` です。

- `config/default/touch-panel/osoyoo-4.3/keyboard-layout.json` は既存 QWERTY layout の source として残す。
- flick pad は最初から runtime Vial definition に混ぜず、kiosk UI overlay / alternate view として検討する。
- profile selection は `script/select_touch_panel_profile.py` の `osoyoo-4.3` 判定を使う。
- `waveshare-8.8` は初期対象外。横長画面では既存 QWERTY を優先する。

## Acceptance Criteria

- [x] 4.3 inch kiosk で flick pad / QWERTY / number-nav を切り替える preview UI がある。
- [x] flick pad は `osoyoo-4.3` profile でだけ candidate として有効になる。
- [x] pointer threshold、direction、cancel 条件が静的テストで固定されている。
- [x] `pointercancel` / tab switch / shutdown menu で未確定 action を送らない。
- [x] UTF / Unicode / Send String の明示的な no-op / preview mode が決まっている。
- [x] host IME / layout 依存の action は default disabled または explicit warning 付きにする。
- [x] keyboard-side GUI conversion と host IME conversion の責務分担を固定する。
- [x] PC host IME 向けに `変換`、`無変換`、`確定`、候補選択操作が必要なことを固定する。
- [x] `ime_controls` metadata と browser-side IME control preview/no-op UI を追加する。
- [x] pad / IME control から最終 action だけを返す read-only resolver helper を追加する。
- [x] server-side resolve endpoint で preview state を含まない disabled `dispatch_event` を返す。
- [x] browser-side preview が resolve endpoint の disabled `dispatch_event` を表示する。
- [x] logicd-facing guard で preview state 混入を拒否し、現行 event を blocked preview-only として扱う。
- [x] explicit `tap_action` / `keycode` event だけを press/release へ変換する logicd helper を追加する。
- [x] `TOUCH_FLICK` ctrl command で resolver済み final dispatch envelope だけを受け付ける。
- [x] `POST /api/touch-panel/flick/dispatch` で HTTP から `logicd` へ preview state ではなく最終 resolved action だけを送る bridge を追加する。
- [x] `dispatch_policy.browser_may_call_dispatch=true` / `browser_default_enabled=false` / `browser_requires_local_enable=true` で、browser UI は明示 `送信: ON` の時だけ dispatch bridge を呼ぶ。
- [x] text output dispatch 前に `POST /api/interaction/text-send-safety/plan` の action-level preflight を要求する metadata を追加する。
- [x] Windows 11 / Microsoft IME の read-only `host_ime_profile` 候補と `host-profile-required` UI warning を追加する。
- [x] browser UI から keycode dispatch bridge を明示ONで呼ぶ first send slice を追加する。
- [x] kana / text output は text-send preflight が `real_send_allowed=true` の時だけ browser UI から dispatch bridge へ流す。
- [x] 800x480 でボタン text がはみ出さない静的 CSS 制約を固定する。
- [ ] 実機で片手親指操作の誤爆率、入力遅延、戻る導線を確認する。

## First Slice

実機なしで進める first slice:

- [x] flick schema / pad metadata helper を read-only に追加する。
- [x] `osoyoo-4.3` profile だけを対象にする guard を固定する。
- [x] DOM 静的テストで flick pad container、direction preview、cancel hook、profile guard の存在を固定する。
- [x] Host IME control metadata / preview UI として `変換`、`無変換`、`確定`、候補選択、cancel を追加する。
- [x] `resolve_flick_pad_action` / `resolve_ime_control_action` で final action only の read-only contract を固定する。
- [x] browser-side preview も `resolveTouchFlickPreviewAction` / `resolveTouchFlickImePreviewAction` で final action only に寄せる。
- [x] `POST /api/touch-panel/flick/resolve` で final action only の disabled dispatch envelope を固定する。
- [x] browser-side pointerup / IME control click を `resolveTouchFlickDispatchEnvelope` に接続する。
- [x] `daemon/logicd/touch_flick_dispatch.py` で final action only の dispatch guard を固定する。
- [x] `dispatch_touch_flick_event` で preview/no-op は送らず、explicit keycode tap と preflight 済み text tap sequence だけを dispatch する。
- [x] logicd ctrl `TOUCH_FLICK` を final dispatch envelope の入口として追加する。
- [x] `POST /api/touch-panel/flick/dispatch` で final dispatch envelope only の HTTP -> logicd bridge を追加する。
- [x] `dispatch_policy` と `送信: ON` UI 表示で、dispatch route discovery と実送信を分離する。
- [x] `送信: ON` の時だけ browser-side pointerup / IME control click が `POST /api/touch-panel/flick/dispatch` を呼ぶ。
- [x] `text_send_plan_preflight` metadata で `TEXT(...)` / Unicode text output の action-level preflight route を固定する。
- [x] named text assignment flow は Settings の `settings.send_strings` を source、`flick.json` action を pad owner とし、
  `TEXT(name)` / `SEND_STRING(name)` を copy / assign / summary / badge / title / text-plan preview で確認する metadata flow に固定する。
- [x] 標準 `osoyoo-4.3` の `flick.json` に named text preset を1件実配置する。
  `punct` pad left direction は `TEXT(kana_a)`、pad label は `、。？！定` とし、
  `touch_panel.flick.named_text_summary.v1` / resolver / dispatch envelope / composition smoke の分類で固定する。
- [x] `<keyboard-host>` の API / dispatch 経路で named text preset を確認する。
  `GET /api/touch-panel/flick` は `named_text.entry_count=1`、
  `POST /api/interaction/text-send-safety/plan` の `TEXT(kana_a)` は `real_send_allowed=true`、
  `POST /api/touch-panel/flick/dispatch` は `ctrl.events=12` / `ctrl.text_send_taps=6` を返す。
- [x] 実 DOM の named text preset 表示確認 helper を追加する。
  `tools/touch_flick_cdp_probe.py --named-preset --key punct --direction left` は label / badge / title /
  text-plan preview / dispatch result をまとめて確認する。
- [x] `host_ime_profile` と `host-profile-required` UI 表示で、explicit host profile 未選択時の no-op を固定する。
- [x] 800x480 kiosk 向けに pad / IME controls / preview の text fit CSS を固定する。
- [x] `windows_ime_hex_f5` / `linux_ctrl_shift_u` の text-send tap dry-run sequence を実送信 runner の最小単位として使えるようにする。

実機ありで進める first slice:

- [x] Windows 11 / Microsoft IME で既存 local `U+XXXX` path から `あいうえお、。ーがぱぁゃア日本語` を実入力確認する。
- [x] 2026-06-03 に `<keyboard-host>` (`<keyboard-ip>`) の `/api/status` で
  `runtime_profile.profile=osoyoo-4.3`、800x480 profile guard を確認する。
- [x] 2026-06-03 に `<keyboard-host>` の `GET /api/touch-panel/flick` が
  `available=true` / `profile_guard.matches_target=true` を返すことを確認する。
- [x] 2026-06-03 に `<keyboard-host>` の `POST /api/touch-panel/flick/resolve` で
  flick pad (`a` + `left` -> `U+3044`) と IME control (`convert` -> `KC_SPC`) が
  final action only の dispatch envelope を返すことを確認する。
- [x] 2026-06-03 に `<keyboard-host>` の preview/no-op `POST /api/touch-panel/flick/dispatch` が
  source field を省いた event に対して `source_must_be_touch_panel_flick`, `enabled=false`, `events=0` を返し、
  preview/no-op が実送信されないことを確認する。
- [x] 2026-06-03 に `<keyboard-host>` の CSRF 付き `POST /api/touch-panel/flick/dispatch` で
  `KC_ESC` / `output=keycode` / `tap_action` / `enabled=true` が logicd まで届き、`events=2` を返すことを確認する。
- [x] 2026-06-03 に `<keyboard-host>` の CSRF 付き `POST /api/touch-panel/flick/dispatch` で
  `U+3042` / `output=text` は `text_send_runner_not_connected` / `events=0` として blocked になることを確認する。
- [x] 2026-06-03 に `<keyboard-host>` の `config/default/config.json` へ `unicode.mode=windows_ime_hex_f5`、
  `unicode.host_profile=win11-ime`、`text_send_runner.connected=true` をバックアップ付きで設定し、
  `POST /api/interaction/text-send-safety/plan` が `U+3042` に対して `real_send_allowed=true` と
  `KC_3` `KC_0` `KC_4` `KC_2` `KC_F5` `KC_ENTER` の sequence を返すことを確認する。
- [x] 2026-06-05 に `<keyboard-host>` で `punct:left` の named text preset API / dispatch を確認する。
  `TEXT(kana_a)` plan は `real_send_allowed=true` / `tap_dry_run.sequence_count=1`、
  resolve は `output=text` / `dispatch=tap_action` / `enabled=true`、
  dispatch は `schema=touch_panel.flick.dispatch.v1` / `ctrl.events=12` / `ctrl.text_send_taps=6`。
- [x] 2026-06-05 に `<keyboard-host>` の kiosk Chromium 実 DOM を
  `HIDLOOM_TOUCH_PANEL_REMOTE_DEBUGGING_PORT=9222` の loopback CDP 経由で確認する。
  `punct:left` は `、。？！定` label、named badge、title、`named-text:1` status、
  metadata entry、`text-plan:ready` preview、dispatch result が通る。
- [ ] `<keyboard-host>` の kiosk 画面で送信 ON 時の host 入力結果を肉眼確認する。
- [x] 2026-06-03 に `<keyboard-host>` の CSRF 付き `POST /api/touch-panel/flick/dispatch` で
  `U+3042` / `output=text` / `tap_action` / `enabled=true` が `text_send.real_send_plan.v1` 経由で
  logicd まで届き、`events=12` を返すことを確認する。
- [x] 2026-06-03 に host PC の入力欄へ実送信し、即時 runner では `３` だけが入力される場合があること、
  0.180 秒間隔の `KC_3` `KC_0` `KC_4` `KC_2` `KC_F5` `KC_ENTER` では `あ` が入力されることを確認する。
- [x] 2026-06-03 に `<keyboard-host>` へ 0.180 秒間隔 runner を同期し、CSRF 付き
  `POST /api/touch-panel/flick/dispatch` で `U+3042` が `events=12` / `text_send_taps=6` /
  `text_send_tap_gap_sec=0.18`、続く `C(KC_ENTER)` が `events=2` を返すことを確認する。
- [x] 2026-06-03 に `tools/touch_flick_cdp_probe.py` で kiosk Chromium の実 DOM に PointerEvent を送り、
  `送信: ON` の browser UI 経由で `a` pad の `left/right/up/down` flick が `U+3044` / `U+3048` /
  `U+3046` / `U+304A` を `tap_action` として送り、preview が `send-ready / ok` になることを確認する。
- [x] 2026-06-03 に同じ probe で `a` center と `ka` pad の `left/up/right/down` flick を確認し、
  host 側に `あきくけこ` が入力されることを確認する。IME control は `commit` (`KC_ENTER`) と
  `cancel` (`KC_ESC`) が UI click 経路で `send-ready / ok` になることを確認する。
- [x] 2026-06-03 に `ka:center`、`sa/ta/na/ha/ma/ra/wa/punct` の主要 5 direction と
  `ya:center/up/down` を一括 probe し、44/44 件で `send-ready / ok`、NG 0 件であることを確認する。
- [x] 2026-06-03 に `mark:center/up/right/down/left` と `ya:left/right` を一括 probe し、
  host 側に `゛ぁゃょ゜」「` が入力されることを確認する。IME control の `convert` (`KC_SPC`)、
  `candidate_next` (`KC_DOWN`)、`candidate_prev` (`KC_UP`)、`nonconvert` (`KC_ENTER`)、
  `commit` (`KC_ENTER`)、`cancel` (`KC_ESC`) も UI 経路で通り、13/13 件で `send-ready / ok`、
  NG 0 件であることを確認する。
- [x] 2026-06-03 に連続物理入力で 6ms hold / 12ms tap gap では host 側に sequence 断片が混入することを確認した。
  browser-side text dispatch を queue で直列化した後に同じ 6ms / 12ms を再試験し、
  `あいうえおかきくけこ` が期待どおり入力されることを確認する。
- 4.3 inch kiosk で pad size、direction threshold、誤爆率を見る。
- 800x480 実機で CSS 制約どおりに文字省略と hit target が自然に見えるか確認する。
- 実機画面の browser UI で `送信: ON` から `あ` row を限定的に送信し、IME / layout 依存 warning の見え方と host 側入力結果を確認する。

補足:

- 2026-06-03 時点で `<keyboard-host>` は `operator@<keyboard-ip>` で SSH 操作できる。
- 2026-06-03 に `<keyboard-host>` へ `text_send_safety_api.py` / `daemon/logicd/text_send_safety.py` も同期し、
  flick dispatch の text block 境界と text-send safety test を実機側で確認した。

## Open Questions

- literal kana / punctuation 出力は UTF / Unicode / Send String 経路に寄せ、かな漢字変換は host IME に任せる。
- 漢字変換前提の入力は direct Unicode ではなく、US keyboard / ローマ字入力の IME composition mode として
  [feature/design-todo-backlog.md](../feature/design-todo-backlog.md) に昇格済み。かな入力 mode は JIS 配列依存が強いため後回しにする。
- 小書き / 濁点 / 半濁点を long press、modifier pad、candidate popup のどれで扱うか。
- `変換` を `KC_SPC` として扱う場合の candidate list 挙動を host profile ごとにどう warning 表示するか。
- 候補選択 UI を dedicated IME control pad、long press、nav layer のどれに置くか。
- flick mode を top-level app tab にするか、keyboard-only kiosk の overlay view にするか。
- 4.3 inch で QWERTY と flick pad の切替ボタンをどこへ置くか。
## 2026-06-04 Composition Plan Slice

`POST /api/touch-panel/flick/composition-plan` was added as a read-only planning route.
It resolves the same final action shape as `/api/touch-panel/flick/resolve`, then maps supported kana Unicode actions to `romaji_us_ime` tap sequences for a US keyboard host IME.

- `U+3042` maps to `KC_A`.
- `U+3044` maps to `KC_I`.
- `U+304B` maps to `KC_K`, `KC_A`.
- `U+304D` maps to `KC_K`, `KC_I`.
- `KC_SPC`, `KC_ENTER`, and `KC_ESC` remain IME control key actions, not text codepoints.
- Dakuten, handakuten, small kana, comma, period, long vowel mark, full-width digits, and US shifted symbol aliases now use explicit romaji/keycode policy.
- Katakana, emoji, IME-specific marks, non-ASCII symbols, JIS-kana layout dependent keys, and named text actions now have explicit `blocking_reasons` policy.
- Remaining blocked text actions are classified as `composition_mode_requires_unicode_action`, `composition_policy_ime_specific_mark`, `composition_policy_jis_kana_dependent`, or `composition_policy_non_ascii_symbol`.
- `GET /api/touch-panel/flick` exposes the same policy through `composition_mode.initial_scope`, `blocked_outputs`, and `blocking_reason_policy`.
- `tools/touch_flick_composition_smoke.py` reports `blocked_policy_complete=true` and `unclassified_blocked_reasons=[]` for the default `osoyoo-4.3` flick definition.

This slice does not dispatch keyboard reports from the browser. It only gives the UI and tests a stable boundary for previewing host-IME composition input without mixing preview state into the `TOUCH_FLICK` dispatch envelope.
The browser flick preview now calls this route after `/api/touch-panel/flick/resolve` and appends `romaji:<keys>` or `composition:<blocking_reasons>` to the preview line.
2026-06-05 に `touchFlickDispatchPayload()` を追加し、browser dispatch POST は `{ event }` だけを送ることを明示した。
`<keyboard-host>` の kiosk Chromium 実 DOM では `ka:center` の `U+304B` plan が `KC_K` / `KC_A` の read-only preview metadata として残り、dispatch payload に `composition_plan` が入らないことを確認済み。
