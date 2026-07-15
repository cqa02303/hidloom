# Interaction inspector design

作成日: 2026-05-30
更新日: 2026-06-01

Combo / Tap Dance / Key Override の既存設定を read-only に診断する inspector の設計です。
2026-05-30 に初期実装済みです。
2026-06-01 には実機なしで進められる follow-up として、warning payload から保存前表示に使いやすい `validation_summary` を作る helper、Interaction summary / accordion header の read-only save hint 表示、builder inline warning 表示を追加しました。
この文書は見える化する warning、schema、HTTP route、UI 位置、保存系 editor と混ぜない境界の source として残します。

## Goal

Interaction inspector は、新しい入力挙動を追加するものではなく、
`settings.interaction` にある既存設定の衝突、誤爆しやすい組み合わせ、term の過短、
layer / keymap との不整合を確認するための read-only tool です。

優先する体験:

- Combo / Tap Dance / Key Override の件数と warning 数がすぐ見える。
- 問題がある設定だけでなく、正常な設定も summary として見える。
- 実機打鍵前に、matrix 範囲外、存在しない action、同じ source key の取り合いを静的に発見できる。
- 保存や自動修正はしない。修正は既存 Interaction editor / raw JSON editor 側で行う。
- 保存前の UI は `validation_summary.save_hint` を見て、`ok` / `review` / `blocked` を分けられる。

## Scope

初期 inspector が見る対象:

| target | checks |
| --- | --- |
| Combo | key 数、matrix 範囲、duplicate key、同一 key set 重複、source key 共有、`combo_term` 過短/過長候補 |
| Tap Dance | name、tap count、hold / tap_hold 併用、per-entry `term`、未定義 action、似た name |
| Key Override | trigger / negative_trigger / key / replacement、layer mask、同一条件の重複、replacement の妥当性 |

Morse は既に [morse/behavior-current.md](../morse/behavior-current.md) と
`/api/interaction/morse-inspector` に専用 inspector があるため、初期対象には含めない。

## HTTP route

route:

```text
GET /api/interaction/inspector
```

この route は read-only です。
`config/default/config.json`、runtime keymap snapshot、matrix metadata を読むだけにし、`logicd` runtime state を変更しません。

最小 response:

```json
{
  "schema": {
    "route": "/api/interaction/inspector",
    "version": 1
  },
  "summary": {
    "combos": 2,
    "tap_dances": 1,
    "key_overrides": 1,
    "warnings": 3
  },
  "validation_summary": {
    "schema": "interaction.inspector.validation_summary.v1",
    "read_only": true,
    "severity_counts": {"error": 0, "warning": 2, "info": 1},
    "total_warnings": 3,
    "has_errors": false,
    "has_warnings": true,
    "save_hint": "review",
    "sections": {
      "combos": {"items": 2, "status": "warning", "warnings": 2},
      "tap_dances": {"items": 1, "status": "ok", "warnings": 0},
      "key_overrides": {"items": 1, "status": "ok", "warnings": 0}
    }
  },
  "sections": {
    "combos": [],
    "tap_dances": [],
    "key_overrides": []
  },
  "warnings": []
}
```

section item の共通 field:

| field | 意味 |
| --- | --- |
| `id` | UI 表示用の安定 ID。保存 key ではない。 |
| `label` | 人間向け表示。 |
| `status` | `ok` / `warning` / `error`。 |
| `source` | `settings.interaction.combos[0]` のような参照文字列。 |
| `warnings` | その item に紐づく warning list。 |
| `details` | key list、action、term、layer mask などの read-only detail。 |

## Validation summary

`daemon/http/interaction_inspector_summary.py` は inspector payload から UI 向けの compact summary を作ります。

方針:

- read-only helper とし、settings / payload の中身を書き換えない。
- severity は `error` / `warning` / `info` を数える。
- unknown severity は安全側に `warning` として数える。
- `save_hint` は `error` があれば `blocked`、warning があれば `review`、何もなければ `ok`。
- section ごとに item 数、worst status、warning 数を出す。
- raw config 断片や action 名を増やして出す helper にはしない。

## Warning policy

warning severity:

| severity | 意味 |
| --- | --- |
| `info` | 仕様上問題はないが、確認するとよいもの。 |
| `warning` | 誤爆や期待違いの可能性があるもの。 |
| `error` | validation では無視される、または runtime で動かない可能性が高いもの。 |

初期 warning 候補:

- Combo の key が matrix 範囲外。
- Combo の key 数が 2 未満。
- Combo に duplicate key がある。
- 複数 combo が同じ key set を持つ。
- Combo 同士が source key を共有し、長い combo と短い combo が競合しやすい。
- `combo_term` が極端に短い、または長い。
- Tap Dance name が空、または action map が空。
- Tap Dance の `term` が global `tap_dance_term` から大きく外れている。
- Key Override の trigger / key / replacement が action validation を通らない。
- Key Override の layer mask が現在の layer 数と合わない。

## UI

配置候補:

- Interaction tab の summary 付近に read-only panel として置く。
- 既存 raw editor / builder とは別 panel にする。
- 初期状態では collapsed でもよいが、warning 数は header に表示する。

表示方針:

- 編集 button は置かない。
- item の source path を表示し、ユーザーが raw JSON の該当箇所を探せるようにする。
- warning が 0 件でも、件数 summary は表示する。
- Morse inspector とは別にするが、将来 accordion UI へ統合できる構造にする。
- 保存前 UI は `validation_summary.save_hint` を使うが、保存可否の最終判断は既存 validation / save path 側に残す。

## Boundaries

- inspector は config を保存しない。
- inspector は runtime keymap を変更しない。
- inspector は validation helper を再利用するが、validation warning と UI explanation を混ぜすぎない。
- 実打鍵の体感判断は行わない。term の過短/過長は「候補」として表示するだけにする。
- validation summary は UI hint であり、自動修正や保存処理を実行しない。

## Static tests added with implementation

初期 inspector:

- `GET /api/interaction/inspector` route constant と route registration がある。
- response に `schema.route`, `summary`, `sections`, `warnings` がある。
- combo duplicate key / duplicate key set / matrix 範囲外 warning が出る。
- tap dance empty action map / per-entry term warning が出る。
- key override invalid action / layer mask warning が出る。
- UI asset が route を fetch し、warning count と section rows を描画する。
- inspector が config file を書き換えない。

Validation summary follow-up:

- warning severity を `error` / `warning` / `info` に集計する。
- unknown severity は `warning` として扱う。
- section item の worst status を集計する。
- `save_hint` が `blocked` / `review` / `ok` を返す。
- summary attach が元 payload を mutate しない。
- inspector payload に `validation_summary` が付く。
- Interaction summary に `Save check`、accordion header に `Save ok/review/blocked` が出る。
- Combo / Tap Dance / Key Override builder に inspector warning が inline 表示される。
- save hint 表示を足しても保存 path 自体は変更しない。

## Implementation gate

実装済み:

- 既存 `logicd.interaction_config` の validation helper を read-only に再利用できる。
- HTTP route は config / keymap snapshot だけを読み、保存処理から分離できる。
- Interaction tab に warning summary を足しても、既存 editor の保存 flow を変えずに済む。
- `validation_summary` を追加しても既存 `summary` / `sections` / `warnings` を壊さない。
- Interaction tab の save hint 表示は read-only で、既存 save path を block しない。
- builder inline warning は inspector の read-only section warning を表示するだけで、builder 入力や保存 payload を書き換えない。

後続候補:

- Combo / Tap Dance / Key Override builder の source key picker / layout 改善へつなぐ。

実装しない条件:

- 自動修正や専用 editor を同時に求められる。
- 実打鍵の良し悪しを inspector だけで判定する必要がある。
- Morse graphical editor と同時に大きく UI を組み替える必要がある。
