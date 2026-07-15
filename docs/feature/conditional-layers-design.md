# Conditional Layers / Tri Layer design

作成日: 2026-05-30
更新日: 2026-06-05

QMK / ZMK / KMK 先行機能候補のうち、`Conditional Layers` / `Tri Layer` を
`logicd` に入れる場合の設計です。
2026-05-30 に runtime 初期実装を追加済みです。
2026-06-01 には、実機なしで進められる follow-up として保存用 rule と runtime active state を分けて表示する read-only inspector helper を追加しました。
2026-06-05 には、Interaction summary に保存 rule 専用の add / remove editor を追加しました。

## Goal

Conditional Layers は、複数 layer が同時に active の時だけ別 layer を自動的に active にする機能です。
典型例は Lower + Raise -> Adjust の tri layer です。

優先する体験:

- `MO(1)` と `MO(2)` が同時に active の時だけ layer 3 を active にする。
- source layer のどちらかが外れたら、自動 layer も外れる。
- 自動 layer は user が直接 toggle した layer と区別する。
- `TO` / keymap reload / config reload で古い自動 layer を残さない。
- UI / inspector では保存 rule と現在 active な conditional layer を混ぜない。

## Config

`settings.interaction.conditional_layers` の最小 schema:

```json
[
  {
    "name": "lower_raise_adjust",
    "if_all": [1, 2],
    "then": 3
  }
]
```

field:

| field | 方針 |
| --- | --- |
| `name` | 任意の非空文字列。warning / UI 表示用。 |
| `if_all` | すべて active なら `then` を有効化する source layer list。2個以上。 |
| `then` | 自動的に active にする target layer。 |
| `mode` | 初期実装では作らない。将来 `if_any` などが必要になったら追加する。 |

validation:

- layer number は 0-31 の integer に限定する。
- `if_all` に `then` を含めない。
- `if_all` に duplicate layer を含めない。
- target layer を source とする cycle は無視して warning にする。
- target layer が複数 rule で重なっても許容するが、同じ target を active にするだけで優先順位は持たない。

## Owner / state

| 項目 | 方針 |
| --- | --- |
| runtime owner | `logicd` の `LayerManager` |
| config owner | `settings.interaction.conditional_layers` |
| persistence | conditional active state は永続化しない。config と keymap から毎回再計算する。 |
| status | `active_snapshot()` は `conditional` field と `all` に runtime state を出す。 |
| inspector | `logicd.conditional_layer_inspector` が saved rule と active state を read-only payload に分ける。 |
| notification | conditional layer が変化したら既存 layer status と同じく `ledd` / `i2cd` へ通知する。 |

`LayerManager` の内部 state は、手動 state と自動 stateを分ける:

- `_momentary`: `MO` / hold 系
- `_toggled`: `TG` / `TO`
- `_oneshot`: `OSL`
- `_locked`: `QK_LAYER_LOCK` / `QK_LLCK` 由来の runtime lock
- `_default_layer`: `DF`
- `_conditional`: conditional layer rule の計算結果

`_active_layers()` は `_conditional` を含めるが、`TO` / `DF` / manual toggle の対象としては扱わない。

## Inspector payload

`logicd.conditional_layer_inspector.conditional_layer_inspector_payload()` は、保存 rule と現在 active な runtime state を分けて返します。

```json
{
  "schema": "conditional_layers.inspector.v1",
  "rule_count": 1,
  "manual_active": [0, 1, 2],
  "active_conditional": [3],
  "rules": [
    {
      "name": "lower_raise_adjust",
      "if_all": [1, 2],
      "then": 3,
      "active": true,
      "source_active": [1, 2],
      "source_missing": [],
      "chain_ignored": false
    }
  ],
  "warnings": [],
  "chain_activation_supported": false,
  "read_only": true
}
```

方針:

- `rules[]` は保存用 rule の read-only view。
- `manual_active` は conditional 以外の runtime source layer。
- `active_conditional` は `LayerManager.active_snapshot().conditional` 由来。
- `chain_activation_supported=false` を明示する。
- conditional target が別 rule の source になっている場合は `chain_ignored=true` と warning を出す。
- `_locked` layer は manual source として扱う。

## Behavior

1. `MO` / `TG` / `TO` / `DF` / `OSL` / Layer Lock の処理後に conditional layers を再計算する。
2. source layer は `_momentary` / `_toggled` / `_oneshot` / `_locked` / `_default_layer` / layer 0 から見る。
3. `_conditional` 自身を source 判定へ含めない。chain activation は初期実装しない。
4. source がすべて active なら `then` を `_conditional` に入れる。
5. source が欠けたら `then` を `_conditional` から外す。
6. keymap reload / config reload / layer clear / daemon restart では `_conditional` を空にしてから再計算する。

`TO(N)` は manual transient state を clear する操作なので、`TO` 後に source 条件が満たされないなら conditional layer も残さない。

## UI / feedback

| surface | 方針 |
| --- | --- |
| HTTP status | `active.conditional` を read-only 表示できるようにする候補。 |
| HTTP Interaction UI | raw JSON editor と read-only inspector payload に加え、`settings.interaction.conditional_layers` 専用の add / remove editor を持つ。rule name、source layers、target layer、active / missing source、warning は一覧できる形にし、runtime active state は保存 payload と混ぜない。 |
| OLED | 既存 layer 表示は effective top layer を表示する。conditional 由来かどうかの表示は初期実装では必須にしない。 |
| LED | layer overlay は effective layer として扱う。conditional 専用色は作らない。同 priority の layer overlay が重なる場合は、通常の layer 解決と同じく数字が大きい layer を優先する。 |

専用 editor の最小操作:

- add: `name`、`if_all`、`then` を入力する。source は 2 個以上、layer number は 0-31、duplicate source と self target は UI で弾き、詳細 warning は既存 validation / inspector に寄せる。
- remove: summary row の削除操作で保存 rule だけを取り除く。
- reorder: 初期 rule は priority を持たないため保存順の意味を持たせない。表示順だけの reorder は作らない。
- validation warning: duplicate source、self target、non-integer layer、shared target、chain source を保存前に表示する。

first slice では raw JSON だけで設定編集は足りる方針だったが、2026-06-05 の follow-up で
source / target の誤読を減らす add / remove editor だけを追加した。
shared target と chain source は inspector warning の owner に残し、保存順 reorder は追加しない。

## Safety / non-goals

- conditional layer は keymap や config へ active state として保存しない。
- chain activation は初期実装しない。
- `if_any` / `unless` / layer expression は初期実装しない。
- target layer を user が `TG` した場合は、manual toggle と conditional active を別 state として扱う。
- target layer が source の keymap を隠すことは仕様通りとし、rule 設計時の注意として docs に残す。
- inspector は read-only とし、active state を保存 payload へ混ぜない。

## Static tests added with implementation

Runtime 初期実装:

- source layers が同時 active の時だけ target layer が `active.conditional` と `active.all` に出る。
- source layer が外れたら target layer が消える。
- `TO` / config reload / keymap reload で stale conditional layer が残らない。
- `_conditional` が source 判定に使われず、chain activation しない。
- invalid rule は warning になり、runtime state を壊さない。
- manual `TG(target)` と conditional target が混在しても、source が外れた時に manual toggle は残る。

Inspector follow-up:

- saved rule と runtime active state を分ける。
- `manual_active` と `active_conditional` を分ける。
- missing source を `source_missing` として出す。
- chain activation 非対応を `chain_activation_supported=false` と warning で示す。
- `_locked` layer を manual source として扱う。
- duplicate source、self target、non-integer layer、shared target の warning を固定する。

Editor follow-up:

- Interaction summary に `Conditional Layers editor` を出す。
- add は `name`、`if_all`、`then` だけを `settings.interaction.conditional_layers` へ追加する。
- remove は保存 rule だけを削除し、`active.conditional` や inspector payload を変更しない。
- UI 側で source 2 個以上、0-31 integer、duplicate source、self target を弾く。
- 保存順 reorder は追加しない。

## Implementation gate

実装済み:

- `LayerManager` に `_conditional` を追加しても既存 `MO` / `TG` / `OSL` / `TT` tests を壊さない。
- `settings.interaction` validation に conditional rule の正規化と warning を追加できる。
- `active_snapshot()` の schema 変更を HTTP / docs / tests で固定できる。
- read-only inspector helper を作り、保存 rule と runtime state を分けられる。
- Interaction summary の add / remove editor で保存 rule だけを編集し、runtime state を混ぜない。

後続候補:

- [x] 2026-06-05 に `<keyboard-host>` の kiosk Chromium 実 DOM で add / remove 表示を確認する。
- [x] 2026-06-05 に保存 rule 編集後、Conditional inspector が clear され、
  Conditional metric が `active pending-save` になって stale runtime snapshot を未保存 rule と混ぜないことを確認する。

実装しない条件:

- chain activation や expression DSL が初期要件になる。
- UI 専用 editor まで同時に必要になる。
- layer 数や keymap編集 UI の整理と同時に大きく変える必要が出る。
