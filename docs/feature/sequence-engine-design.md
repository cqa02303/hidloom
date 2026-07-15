# Sequence engine design

更新日: 2026-06-05

Morse の実行 engine を軸に、Tap Dance / Tap-Hold / 将来の Leader などを同じ
内部モデルで扱えるかを検討するための設計メモです。
外部から見える action 名や保存形式は QMK / Vial 互換を優先し、`MORSE(name)`、
`TD(name)`、`LT` / `MT` / `TT` などの既存表現は変えません。

## 目的

現状の `InteractionEngine` は Morse、Tap Dance、Tap-Hold でそれぞれ timer、
pending state、commit / cancel の考え方を持っています。Morse は dot / dash の
prefix tree、Tap Dance は tap count、Tap-Hold は hold 判定後の先行 press と
release を持つため、表面上の入力規則は違います。

一方で runtime の中核は共通化できます。

- 入力 event から内部 step を蓄積する。
- timeout / release / interrupt で state を確定または cancel する。
- 確定時に host へ送る action、LED / OLED / HTTP へ返す feedback、source key の
  suppress / restore を順序付きで出す。
- config reload、output switch、emergency release で中間 state を安全に破棄する。

この共通部は内部名 `SequenceEngine` として切り出し、Morse profile adapterから利用します。

## 対象範囲

初期対象は以下です。

| profile | 既存表現 | 内部 step | 確定方法 |
|---|---|---|---|
| Morse | `MORSE(name)` | press duration から `.` / `-` | leaf / fallback / timeout / force_commit |
| Tap Dance | `TD(name)` | tap count、または repeated tap step | tap dance term timeout / hold 判定 |
| Tap-Hold | `LT` / `MT` / `TT` など | press duration / interrupt | tap action、hold press、hold release |

Combo、Leader、Dynamic Macro は second slice 以降の評価対象です。Combo は source key
suppression と Key Override の順序に近く、2026-06-14 時点では SequenceProfile には入れず、
source suppression / priority engine として分離したまま扱います。

## related feature fit

SequenceEngine に寄せる対象は「時間や入力列を持つもの」と「副作用 emission を共通化するもの」に分けます。
すべてを profile として直接入れる必要はありません。

| feature | 統合候補 | 理由 | 初期判断 |
|---|---|---|---|
| Key Override | emission layer 候補 | trigger source の `suppress` / `restore`、replacement `press` / `release`、press 時 action pin が SequenceEmission と同じ形 | profile にはせず、SequenceEmission ordering と suppression accounting を共有する候補 |
| Combo | suppression engine 候補 | source key delay、成功時 source suppression、combo action hold / release を持つ | Key Override / Mod-Morph priority と競合するため、SequenceProfile には含めず既存 source suppression 経路に残す |
| Leader | profile 候補 | prefix sequence、timeout、matched action、cancel を持ち、Morse tree とかなり近い | 実装時は SequenceProfile 化しやすい |
| Dynamic Macro record | final-action observer 候補 | 記録すべきなのは中間 state ではなく最終 resolved action | engine 本体ではなく emission stream の consumer として扱う候補 |
| Dynamic Macro play | playback producer 候補 | 保存済み action 列を通常 output path へ流す | SequenceEngine の profile ではなく macro runner / playback queue 側で扱う |
| Key Toggle / Key Lock / Drag Lock | synthetic source 候補 | synthetic `press` / `release` と clear 時 release を持つ | lock state owner は専用 helperのまま、emission type と clear ordering だけ共有する候補 |
| Sticky Key / Sticky Modifier | profile 候補 | next key までの pending state、timeout / cancel、press / release ordering を持つ可能性がある | 実装前に SequenceEngine 適用を再評価する |
| One Shot Layer / Layer Lock | LayerManager state | layer state の source of truth が LayerManager にある | SequenceEngine 本体へは入れない |
| Conditional Layers | derived layer state | active layer snapshot から再計算される派生 state | SequenceEngine 本体へは入れない |
| Caps Word | final-action transformer | word 継続 / cancel と `S(KC_A)` 変換を持つが、入力列 engine ではない | profile にはせず、final action transformer のまま |
| Repeat Key | final-action history | sequence ではなく、最終 repeatable action の privacy-safe history | profile にはせず、emission 後の history consumer にする |
| Mod-Morph / Grave Escape | stateless resolver | held modifiers / active layer から action を置換するだけ | SequenceEngine には入れず、priority resolver として残す |
| Autocorrect | text pipeline | word buffer と Send String / IME policy が主対象 | SequenceEngine ではなく text-send safety / autocorrect owner 側 |

Key Override のような「中間入力列ではないが suppression / restore を持つ」機能は、
SequenceEngine 本体へ入れるよりも、`SequenceEmission` の共通 ordering rule を使うほうが安全です。
これにより、Key Override、Combo、Tap-Hold が同じ stuck-key safety policy を共有できます。

## 内部モデル

`SequenceEngine` は保存 payload を直接所有せず、profile adapter から渡される
runtime 定義を処理します。

- `SequenceProfile`
  - action 種別ごとの判定規則。
  - Morse なら dot / dash threshold と tree、Tap Dance なら count map と term、
    Tap-Hold なら tapping term / interrupt policy を持つ。
- `SequenceState`
  - active source key、step list、start time、deadline、press 時に pin した action、
    feedback queue を持つ。
- `SequenceEmission`
  - runtime から `InteractionEngine` へ返す副作用候補。
  - 例: `tap(action)`, `press(action)`, `release(action)`, `suppress(action)`,
    `restore(action)`, `feedback(event)`, `cancel(reason)`。
- `SequenceTimer`
  - profile が次 deadline を要求し、`InteractionEngine` が既存 event loop へ接続する。

重要なのは、Morse のような「最後に 1 action を tap する」だけでなく、Tap-Hold の
hold 成立時の先行 `press(action)` と、物理 release 時の `release(action)` も同じ
emission stream で扱うことです。

## emission ordering

stuck key を避けるため、emission の順序は仕様として固定します。

1. source key を隠す必要がある場合は `suppress(source_action)` を先に出す。
2. replacement / hold の `press(action)` を出す。
3. 確定 tap は `tap(action)` として press / release を同じ dispatch cycle で出す。
4. 物理 release、cancel、timeout では press 済み action を必ず `release(action)` する。
5. replacement 後も source physical key が残っている場合だけ `restore(source_action)` する。
6. `feedback(event)` は host HID ではなく UI / OLED / LED 向け event として扱い、
   host への key report ordering と混ぜない。

Key Override runtime suppression と同じく、press 時に解決した action を release まで
pin します。layer 変更や config reload が途中で入っても、release 側だけ別 action に
化けないことを受け入れ条件にします。

## migration plan

1. **型と境界だけを追加する**
   - `logicd.sequence_engine.SequenceEmission` と host-visible / feedback 境界は追加済み。
   - `SequenceProfile`、`SequenceStep`、`SequenceResult`、`SequenceTimerRef` の最小 interface は追加済み。
   - 既存 Morse / Tap Dance / Tap-Hold の挙動は変更しない。
2. **Morse adapter を作る**
   - `MorseBehaviorRuntime` の tree / fallback / force_commit / feedback を
     `MorseSequenceProfile` へ包む adapter は追加済み。
   - `MORSE(name)`、`MORSE_FEEDBACK`、既存 Web UI / inspector payload は変更しない。
3. **Tap Dance adapter を作る**
   - tap count、hold、tap_hold、term timeout を SequenceEngine の step / deadline に寄せる。
   - `TD(name)` の保存形式と Vial import-export 互換は変更しない。
4. **Tap-Hold adapter を評価する**
   - hold 成立時の先行 `press`、tap cancel、release ordering を sequence emission で表せるか確認する。
   - ここで stuck modifier / zero report / output switch の regression を厚くする。
5. **Combo / Leader / Dynamic Macro の扱いを判断する**
   - Combo は source suppression と priority 境界が強いため、SequenceProfile へは入れず
     Key Override / Mod-Morph と近い source suppression 経路に残す。

## acceptance criteria

- `MORSE(name)`、`TD(name)`、`LT` / `MT` / `TT` などの外部 action 名を変えない。
- 保存 payload、HTTP editor、Vial import-export の schema を first slice では変えない。
- `MORSE_FEEDBACK` は transport-neutral feedback のまま維持する。
- config reload、output switch、emergency release で active sequence が残らない。
- 既存テスト `script/test_interaction_engine_morse.py`、
  `script/test_interaction_engine_tap_hold.py`、
  `script/test_interaction_physical_runtime.py`、
  `script/test_key_override_cross_clear.py` が互換確認の中心になる。
- 実機がなくても first slice は unit / static test で完了でき、実機固有の確認は
  `実機確認待ち` として分離する。

## concerns

- 汎用化しすぎると、QMK / Vial 互換 action と local runtime action の意味が読みにくくなる。
- Tap-Hold の先行 `press` / 後続 `release` は順序を誤ると modifier や mouse button が残る。
- Tap Dance の `hold` / `tap_hold` は物理押下時間と count timeout の両方に関係するため、
  Morse の prefix tree と同じ commit モデルへ寄せすぎない。
- Morse feedback は host HID event ではないため、`tap(action)` と同じ queue に混ぜると
  UI / OLED / LED と host report の責務が曖昧になる。
- Combo source suppression、Key Override runtime suppression、Mod-Morph の priority が
  競合しやすい。
- Caps Word / Repeat Key は内部 sequence ではなく、最終的に host へ送った action を
  履歴対象にする必要がある。
- timer cancel / generation 管理がずれると、reload 後の stale timeout が新しい state を
  commit する可能性がある。
- Web UI / storage schema まで一度に統合すると blast radius が大きい。

## blocking issues before implementation

実装へ進める前に、以下を個別 TODO として固定します。ここが曖昧なまま refactor すると、
見た目は共通化できても stuck key や外部互換の破壊につながります。

### Press / release owner

host-visible な `press(action)` を出した機能が、対応する `release(action)` の owner です。
Tap-Hold、Combo、Key Override replacement、Key Lock synthetic source はすべてこの規則に従います。
release 時点で layer、modifier、Key Override 条件が変わっていても、press 時に pin した action を release します。

固定済み:

- [x] `SequencePressedAction` で `press` 済み action と owner を pin し、release 時点の resolver 状態に依存しない。
- [x] reset / output switch / emergency release は pinned action の release emission を先に作る規則として固定する。
- [x] 後続の物理 release が二重 release にならない guard を `script/test_sequence_engine_primitives.py` で固定する。

### Suppress / restore accounting

Key Override と Combo は source action を一時的に host から隠します。複数の replacement が同じ trigger を
suppress する可能性があるため、単純な bool ではなく reference count が必要です。

固定済み:

- [x] `SequenceSuppressionLedger` で `suppress(source_action)` / `restore(source_action)` の reference count owner を持つ。
- [x] trigger が replacement 中に物理 release された場合は restore しない規則を共通化する。
- [x] Combo source suppression と Key Override trigger suppression が同じ source action に触る場合は同じ ledger owner set に集約し、最後の owner が restore 判断を持つ。

### Timer generation and cancel

Morse、Tap Dance、Tap-Hold、Combo source delay、Leader は timer を使います。reload 後の stale timeout や、
古い generation の timeout が新しい state を commit する事故を防ぐ必要があります。

固定済み:

- [x] `SequenceTimerRef` / `SequenceTimerRegistry` で timer entry に feature id、source key、generation を必ず持たせる。
- [x] reset / config reload / output switch で timer generation を無効化する規則を固定する。
- [x] `on_tick()` 相当で generation が一致しない timer は no-op にする境界を `script/test_sequence_engine_primitives.py` で固定する。

### Resolver / transformer boundary

SequenceEngine は action resolver のすべてを吸収しません。Mod-Morph は stateless resolver、Caps Word は
final-action transformer、Repeat Key / Dynamic Macro record は final-action observer として扱います。

固定済み:

- [x] SequenceEngine 前に走る resolver と、SequenceEngine 後に走る transformer / observer の候補表を維持する。
- [x] Repeat Key / Dynamic Macro record は `feedback` / `suppress` / internal control action を履歴に入れず、`tap` / `press` / `release` だけを見る。
- [x] Caps Word は SequenceEngine 前の key-like action ではなく final host action transformer として残す方針を互換 guard で固定する。

### Feedback separation

Morse feedback は OLED / LED / HTTP 向けで、host HID report ではありません。SequenceEngine に feedback を入れる場合も、
HID dispatch queue と混ぜない transport-neutral event として扱います。

固定済み:

- [x] `feedback(event)` は host output path へ流れない data type にする。
- [x] `split_host_and_feedback()` と Morse profile tests で、feedback drain API と existing `MORSE_FEEDBACK` 互換を固定する。
- [x] Leader や Sticky へ feedback を広げる場合も、privacy-safe な runtime status と分ける。

### Compatibility and migration blast radius

first slice では内部 refactor に限定し、保存 payload、HTTP UI、Vial import-export、action 名は変えません。
UI / storage schema の統合は、runtime behavior が安定してから別 TODO として扱います。

検討TODO:

- [x] `MORSE(name)` / `TD(name)` / `LT` / `MT` / `TT` の外部表現を変えない static test を先に置く。`script/test_sequence_engine_compatibility_guard.py` で固定済み。
- [x] Web UI / inspector payload は既存 route / schema を維持し、SequenceEngine の内部名を露出しない。`script/test_sequence_engine_compatibility_guard.py` で固定済み。
- [x] behavior-change なしの Morse adapter を最初の実装 slice にする。`daemon/logicd/sequence_morse.py` と `script/test_sequence_morse_profile.py` で固定済み。

## investigation TODO

- [x] `SequenceEmission` の最小 schema と ordering rule を Python type と doc test で固定する。
- [x] profile interface に必要な hook を `on_press` / `on_release` / `on_timeout` /
      `on_interrupt` のどこまでにするか決める。
- [x] blocking issues before implementation の Press / release owner、Suppress / restore accounting、
      Timer generation、Resolver / transformer boundary、Feedback separation、Compatibility の各項目を
      first implementation 前に test TODO へ落とす。
- [x] Morse adapter を behavior change なしで追加し、既存 Morse tests をそのまま通す。`script/test_sequence_morse_profile.py` と既存 Morse regression で固定済み。
- [x] Tap Dance adapter は `hold` / `tap_hold` / count timeout の互換 test を先に増やす。2026-06-14 に stale hold timer guard、tap_hold、double-tap timeout regression を `script/test_interaction_engine_tap_hold.py` へ追加済み。
- [x] Tap-Hold adapter は先行 `press`、release pin、zero report、output switch clear の
      regression を先に追加する。2026-06-14 に clear before timeout、active hold release once、
      stale hold timer guard を `script/test_interaction_engine_tap_hold.py` へ追加済み。
- [x] Combo を SequenceEngine に入れるか、source suppression engine として分離するか判断する。
      2026-06-14 時点では source suppression / priority engine として分離し、SequenceProfile には含めない。
- [x] Key Override は profile ではなく `SequenceEmission` の `suppress` / `restore` ordering を共有する形で統合できるか確認する。
      2026-06-14 時点では `docs/keycode/key-override-runtime-suppression-design.md` と
      `script/test_key_override_cross_clear.py` の境界に合わせ、SequenceProfile には含めず
      suppression / restore ordering の共有候補に留める。
- [x] Leader は Morse に近い prefix sequence profile として、SequenceProfile 化する候補にする。
      `daemon/logicd/dynamic_macro_leader.py` の `LeaderRuntime` は pending / match / timeout / cancel
      を HID 非送信で固定済みのため、将来の SequenceProfile 候補として残し、live 接続は別 slice にする。
- [x] Dynamic Macro record / Repeat Key / Caps Word は SequenceEngine 本体ではなく、最終 emission / final action consumer として扱う境界を固定する。
      Dynamic Macro は最終 resolved action filter、Repeat Key は final action history、Caps Word は final host action transformer として扱う。
- [x] Key Lock / Drag Lock は synthetic press / release source と clear ordering だけを共有し、lock state owner は専用 helper のままにする。
      `logicd.key_lock.KeyLockState` を state owner にし、SequenceProfile には含めない。
- [x] Interaction inspector / runtime-status に active sequence を出す場合、action 名を
      どこまで表示するか privacy-safe に決める。初期は action 名を出さず、feature、phase、
      count / deadline / blocking reason などの metadata に留める。
- [x] 実機確認では tap-hold / tap dance / Morse を同じ入力 rhythm で打ち、stuck key、
      誤 commit、feedback 遅延がないか確認する。これは実装 TODO の blocker ではなく
      private workspace reference *(omitted from public export)* の追加観測へ移す。
