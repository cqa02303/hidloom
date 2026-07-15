# Sticky Key / Sticky Layer status design

更新日: 2026-06-05

この文書は Sticky Key / Sticky Layer の timeout、cancel、lock state を
HTTP / OLED / LED overlay で見える化する前の実装前設計です。
2026-05-31 に既存 `OSL(N)` の read-only status 表示の first step を追加済みです。
2026-06-05 に既存 `OSL(N)` の count を `/api/status.interaction.one_shot_layer.active_count` /
System panel `Interaction` row へ read-only 接続済みです。
新しい sticky behavior の実装はまだ行わず、既存の `OSL(N)` と
将来の one-shot modifier / sticky key / layer lock を混同しないための境界を固定します。

## 現在の前提

- `OSL(N)` は実装済みで、`logicd.keymap.LayerManager` が `_oneshot` を持つ。
- `LayerManager.active_snapshot()` / `/api/keymap/active` は `momentary`、`toggled`、`oneshot`、`locked`、`conditional`、`all` を返す。
- `active_snapshot()` の `oneshot` / `locked` / `conditional` は read-only runtime state で、保存 payload とは混ぜない。
- `logicd.interaction_engine.InteractionEngine` は non-layer key の処理後に one-shot layer を consume する。
- `OSM(mod)`、`OS_LCTL` などの One Shot Modifiers は未実装。
- Sticky Key / Sticky Layer の lock state と timeout は未実装。

この設計では `active_snapshot().oneshot` を既存 `OSL(N)` の source of truth とし、
将来の sticky modifier / sticky key の状態は別枠で追加します。

## Scope

初期実装で扱うもの:

- 既存 `OSL(N)` の read-only status 表示。Interaction summary と accordion header では
  `/api/keymap/active.oneshot` から `One Shot Layer` / `OSL N` を表示する。
- 既存 `OSL(N)` の System panel count 表示。`INTERACTION_STATUS` / `/api/status.interaction` では
  layer 番号の詳細を出さず、`one_shot_layer.active_count` だけを表示する。
- 既存 `QK_LAYER_LOCK` / `QK_LLCK` の read-only status 表示。Interaction summary と accordion header では
  `/api/keymap/active.locked` から `Locked Layer` / `Lock N` を表示する。
- 将来の one-shot modifier / sticky key / layer lock を載せられる status schema。
- HTTP System または Interaction tab の read-only 表示。
- OLED の短い active / cancel 表示。
- LED overlay の optional な active 表示。

初期実装で扱わないもの:

- `OSM(mod)` / `OS_LCTL` などの modifier one-shot 実装。
- Sticky Key / Sticky Layer の lock key 実装。
- Caps Word、host Caps Lock、Conditional Layers との統合表示。
- HTTP から sticky 状態を編集、解除、lock する操作。

## State owner

Sticky 系 runtime state の owner は `logicd` です。

- `OSL(N)` の one-shot layer state は引き続き `LayerManager` が持つ。
- one-shot modifier / sticky key を追加する場合は `InteractionEngine` か小さな sticky state helper が持つ。
- `httpd`、`i2cd`、`ledd` は read-only consumer にする。
- active state は永続化しない。
- daemon restart / config reload / output switch / emergency release では sticky state を残さない。

## Status schema candidate

既存実装では `/api/keymap/active.oneshot` が `OSL(N)` の表示元です。
Interaction tab の read-only summary / accordion header は、この field だけを読み、保存 payload には混ぜません。
System panel は詳細 layer 番号を出さず、`INTERACTION_STATUS` 由来の
`one_shot_layer.active_count` だけを `OSL N` として表示します。
将来の status 拡張では `/api/status.interaction.sticky` または
`GET /api/interaction/sticky-status` のような read-only schema に寄せます。

候補:

```json
{
  "sticky": {
    "layers": [
      {
        "layer": 1,
        "mode": "oneshot",
        "source": "OSL(1)",
        "expires_at": null,
        "locked": false,
        "cancel_reason": null
      }
    ],
    "modifiers": [],
    "keys": [],
    "summary": {
      "active": 1,
      "locked": 0,
      "warnings": 0
    }
  }
}
```

Schema policy:

- `layers[]` は `OSL(N)` と将来の layer lock / sticky layer を扱う。
- `modifiers[]` は `OSM(mod)` / `OS_LCTL` などを実装した時に追加する。
- `keys[]` は key lock / drag lock などを実装した時に追加する。
- `locked=false` と `expires_at=null` は、現行 `OSL(N)` が lock / timeout を持たないことを明示する。
- `cancel_reason` は最後に解除された理由を短時間だけ出す用途にし、永続 log にはしない。

## Cancel / timeout / lock policy

現行 `OSL(N)`:

- 次の non-layer key 処理後に consume する。
- layer action だけでは consume しない。
- `TO(N)` は `LayerManager.to_layer()` により one-shot を clear する。
- config reload / daemon restart / output switch / emergency release では残さない。
- timeout と lock state は持たない。

将来の one-shot modifier / sticky key:

- timeout は `settings.interaction.sticky.timeout_ms` のような明示設定を追加するまで実装しない。
- lock state は unlock 条件、emergency release、output switch 時の全解除を先にテストで固定する。
- cancel key を導入する場合も、`KC_ESC` などに暗黙で割り当てず、設定と表示を先に決める。

## UI policy

HTTP:

- System panel と Interaction tab に read-only status として表示する。
- System panel は `one_shot_layer.active_count` の count だけを出し、詳細は Interaction tab に残す。
- 保存 UI、解除 button、lock button は初期実装しない。
- 既存 `active.oneshot` は表示互換のため維持する。

OLED:

- active `OSL(N)` は短い `OSL 1` のような status 表示にする。
- cancel / timeout / lock の表示は将来 state が入った時だけ出す。
- Caps Lock / Caps Word と同じ文言や同じ overlay 色にしない。

LED:

- optional overlay 名は `sticky_layer` / `sticky_modifier` のように分ける。
- host lock LED の `HOST_LED` overlay と混ぜない。
- 初期実装では LED overlay なしでもよい。HTTP status が先。

## Static tests to add with implementation

- `OSL(N)` active 中に status が `layers[].source == "OSL(N)"` として見える。
- non-layer key 後に one-shot layer が消える。
- layer action だけでは one-shot layer が残る。
- `TO(N)`、config reload、output switch、emergency release で sticky state が消える。
- HTTP UI は read-only 表示だけを持ち、保存 payload に sticky status を混ぜない。
- 将来 `OSM(mod)` を足す時は `layers[]` ではなく `modifiers[]` に出る。

## Implementation gate

実装へ進める条件:

- 既存 `OSL(N)` の status 表示だけを first step にできる。
- `LayerManager.active_snapshot()` の互換を壊さない。
- HTTP / OLED / LED のどれも sticky state の writer にならない。
- one-shot modifier や lock state は、状態 owner と解除条件を追加テストで固定してから実装する。

実装しない条件:

- Sticky 表示が Caps Lock / Caps Word / Conditional Layers と見分けにくくなる。
- status schema が editor の保存 payload と混ざる。
- emergency release / output switch で active state が残る可能性がある。
