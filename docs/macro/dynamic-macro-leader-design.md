# Dynamic Macro / Leader design

作成日: 2026-06-01

この文書は QMK Dynamic Macro / Leader key 相当を実装する前の設計です。
2026-06-01 時点では実装へは進まず、runtime state、record buffer、再生中の入力扱い、output switch / reload 時の破棄、UI feedback、テスト範囲を固定します。

## Goal

- Dynamic Macro と Leader を、既存 InteractionEngine の stateful feature として安全に扱う。
- 記録・再生・通常入力を明確に分ける。
- output switch / config reload / emergency release で stale state を残さない。
- Macro / Script / KML / QMK macro compatible runner と責務を混ぜない。

## Feature candidates

| feature | 候補 keycode | 初期扱い |
| --- | --- | --- |
| Dynamic Macro record slot 1 | `DYN_REC_START1` / `DYN_REC_STOP` | 候補。名前は QMK 互換 alias と local 名の両方を検討 |
| Dynamic Macro record slot 2 | `DYN_REC_START2` / `DYN_REC_STOP` | 候補。slot 数は 2 から始める |
| Dynamic Macro play slot 1 | `DYN_MACRO_PLAY1` | 候補 |
| Dynamic Macro play slot 2 | `DYN_MACRO_PLAY2` | 候補 |
| Leader start | `LEADER` | 候補。leader sequence timeout を持つ |

初期実装では、record / play / leader を同時に大きく入れない。
Dynamic Macro の state owner を先に固定し、Leader は別 section として扱う。

## Dynamic Macro state owner

候補 owner は `InteractionEngine` または専用 `DynamicMacroState`。

State:

```text
idle
recording(slot)
playing(slot)
```

Buffer:

- runtime memory にだけ置く。
- 初期実装では永続化しない。
- slot は 1 / 2 の固定候補。
- 保存するのは resolved tap action の列。
- key press / release をそのまま録るのではなく、再生可能な action event へ正規化する。

## Record policy

記録する候補:

- 通常 keyboard tap action。
- modifier wrapper を含む単発 tap action。
- mouse button / wheel のうち、既存 macro path で単発 tap として安全なもの。

記録しない候補:

- record / play control 自身。
- script / system / connectivity / power action。
- output switch action。
- keymap / layer mutation action。
- Morse / Tap Dance / Combo / Key Override の中間 state。
- Autocorrect internal correction sequence。

方針:

- 最終 resolved action を記録する。
- physical matrix position は記録しない。
- 何を記録対象外にしたかは debug / inspector warning に出す候補。

## Play policy

- 再生は通常 output path へ action event を流す。
- 再生中に新しい physical input が来た場合の扱いは実装前に固定する。
- 初期候補は「再生中の新規入力で再生を cancel」。
- 再生中の output switch / reload / emergency release でも cancel。
- 再生中に Dynamic Macro play を再入させない。
- replay した action を Repeat Key history に残すかは別途テストで固定する。

## Clear / cancel policy

Dynamic Macro state と buffer の扱い:

| event | state | buffer |
| --- | --- | --- |
| record stop | idle | 対象 slot に保持 |
| config reload | idle | clear 候補 |
| keymap reload | idle | clear 候補 |
| output switch | idle | clear または keep を実装前に固定。安全側は clear |
| emergency release | idle | clear |
| daemon restart | idle | clear |

初期実装では `output switch` で buffer も clear する安全側候補。

## Leader design

Leader は sequence timeout を持つ prefix key として扱う。

State:

```text
idle
leader_pending(sequence, deadline)
```

候補 config:

```json
{
  "settings": {
    "interaction": {
      "leader": {
        "enabled": false,
        "timeout": 0.7,
        "sequences": {
          "A,B": "KC_ESC"
        }
      }
    }
  }
}
```

方針:

- default disabled。
- leader sequence は key action 名の列で表す。
- raw matrix position ではなく resolved action を使う。
- timeout / cancel / fallback を明示する。
- Leader pending 中に layer / output switch / system action が来たら cancel。

## UI / feedback

HTTP:

- 初期は read-only status / validation から始める。
- Dynamic Macro の buffer 内容を全部表示するかは privacy / 誤操作の観点で後続判断。
- Leader sequence editor は、実装前に action picker と validation を固定する。

OLED:

- `Rec 1`、`Play 1`、`Leader` のような短い status を候補にする。
- long sequence は表示しない。

LED:

- 専用 overlay は初期不要。
- 使う場合は `dynamic_macro` / `leader_pending` として host lock overlay と分ける。

## Relation to other features

| feature | 境界 |
| --- | --- |
| Macro / KML / QMK macro | Dynamic Macro は runtime 記録。KML / QMK macro は file / named runner。保存 owner を混ぜない。 |
| Repeat Key | replay action を repeat history に入れるかは別途固定。internal control action は保存しない。 |
| Autocorrect | Autocorrect internal Backspace / replacement sequence は記録しない。 |
| Morse / Tap Dance / Combo | 中間 state は記録せず、最終 resolved action だけを見る。 |
| Script / System / Connectivity | 初期記録対象外。 |

## Static tests to add with implementation

設計 first slice では doc test だけを追加する。
実装へ進む場合は以下を追加する。

- state transition: idle -> recording -> idle -> playing -> idle。
- record control action 自身を buffer に入れない。
- script / system / connectivity / power action を記録しない。
- output switch / reload / emergency release で recording / playing を cancel。
- daemon restart で buffer が永続化されない。
- Leader timeout / cancel / matched sequence。
- Leader pending 中の output switch / layer reset で cancel。

## 2026-06-10 runtime groundwork

`daemon/logicd/dynamic_macro_leader.py` を追加し、Dynamic Macro / Leader の no-device
runtime groundwork を固定した。これは live InteractionEngine へ HID report を送らず、
`dynamic_macro.runtime.v1` / `leader.runtime.v1` の read-only state と plan を返す。

完了した範囲:

- runtime-only 2 slot Dynamic Macro buffer。
- `DM_REC1` / `DM_REC2` / `DM_RSTP` / `DM_PLY1` / `DM_PLY2` と local alias の control mapping。
- recordable final action filter。`KC_*`、modifier wrapper、`U+XXXX`、mouse tap 系は許可し、record / leader control、script / system / connectivity / power、output switch、layer、named macro、intermediate state は拒否する。
- playback re-entry guard と recording / playing の排他。
- output switch / reload / emergency release などから呼べる cancel boundary。初期方針どおり buffer は clear 側を default にする。
- Leader settings validation、default disabled、sequence key validation、pending / match / timeout / cancel。

未実装のまま残す範囲:

- 実キーでの録音・再生体感確認。
- live InteractionEngine からの event 接続。
- playback action を通常 output path へ流す runner 接続。
- Dynamic Macro buffer の永続化。

## Implementation gate

実装へ進める条件:

- record buffer の owner と保存しない方針が固定できる。
- replay 中の physical input policy が決まっている。
- output switch / reload / emergency release の cancel path がある。
- Leader sequence の action 名 validation が固定できる。

実装しない条件:

- Dynamic Macro を永続化しないと成立しない。
- script / system / connectivity action の記録が必須になる。
- replay 中の入力と安全に混在できない。
- Leader sequence に raw matrix position が必須になる。
