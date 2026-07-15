# Layer Lock design

更新日: 2026-06-01

この文書は QMK / Vial の `QK_LAYER_LOCK` / `QK_LLCK` 相当の設計と初期実装状態をまとめます。
2026-06-01 時点では、実機なしで確認できる first slice として `LayerManager` の runtime lock state と静的テストまで実装済みです。
Vial custom keycode 割当、HTTP unlock button、OLED / LED feedback はまだ後続候補です。
初期対象は runtime lock state、`active_snapshot().locked`、`/api/keymap/active.locked`、Interaction summary / accordion header の read-only 表示に限定します。

## 現在の前提

- `LayerManager` は `_momentary`、`_toggled`、`_oneshot`、`_locked`、`_default_layer` を持つ。
- `MO(N)` は key release で解除する。
- `TG(N)` は明示 toggle として `_toggled` に入る。
- `TO(N)` は momentary / toggled / locked / oneshot を clear して target layer へ移る。
- `DF(N)` は default layer を変え、momentary / locked / oneshot を clear する。
- `OSL(N)` は `_oneshot` に入り、次の non-layer key 後に clear される。
- `QK_LAYER_LOCK` / `QK_LLCK` は runtime action 名として解釈する。
- Vial custom keycode 枠は 64 個制限があるため、first slice では `VIAL_CUSTOM_ACTIONS` へ追加しない。

## Semantics

Layer Lock は「現在有効な非 default layer を明示 lock し、同じ操作で解除する」機能として扱います。

初期実装:

- `QK_LAYER_LOCK` / `QK_LLCK` は press 時だけ処理する。
- lock 対象は `LayerManager.active_snapshot().all` のうち、default layer と layer 0 を除いた最上位 layer。
- lock 対象がない場合は no-op。
- 対象 layer がすでに locked なら unlock する。
- 対象 layer が locked でなければ `_locked` に入れる。

`TG(N)` との違い:

- `TG(N)` は keycode に layer number が埋め込まれた toggle。
- Layer Lock は「いま使っている layer」を固定する操作。
- UI / status では `toggled` と `locked` を分けて表示する。

`OSL(N)` との違い:

- `OSL(N)` は次の non-layer key 後に消える。
- Layer Lock は明示 unlock または clear event まで残る。
- `OSL(N)` だけが active の時に Layer Lock を押した場合、対象 layer を `_locked` へ移し、`_oneshot` からは消す。

## State owner

State owner は `logicd.keymap.LayerManager` です。

実装済み:

```python
self._locked: Set[int] = set()
```

`active_snapshot()`:

```json
{
  "momentary": [],
  "toggled": [],
  "oneshot": [],
  "locked": [2],
  "conditional": [],
  "all": [2, 0]
}
```

`active_snapshot().locked` は、既存の `active_snapshot().toggled` / `active_snapshot().oneshot` と同じ read-only runtime state として扱います。

`_active_layers()` は `_locked` を含めます。
layer lookup priority は現行と同じく layer number の高いものを優先し、state type で優先順位を変えません。

## Clear policy

Layer Lock state は永続化しません。

解除する event:

- `QK_LAYER_LOCK` / `QK_LLCK` を locked layer 上で再度押す。
- `TO(N)`。
- `DF(N)`。
- config reload / `LayerManager.load()`。
- output switch (`KC_CONNAUTO` / `KC_CONSOLE` / `KC_USB` / `KC_BT`)。
- layer clear / remove で対象 layer がなくなる。

後続確認:

- [x] 2026-06-05 に output switch の明示 clear path を `script/test_layer_lock_output_switch_clear.py`
  で固定する。`KC_USB` press 前に runtime `_locked` を clear し、LED / OLED status refresh を呼び、
  output switch key 以外の pressed matrix state を落としてから switch action を dispatch する。

解除しない event:

- unrelated key tap。
- `MO(N)` の release。
- `OSL(N)` の consume。
- `TG(N)` の toggle。ただし同じ layer が `toggled` と `locked` の両方に入った場合でも status は分ける。

## HTTP / OLED / LED policy

HTTP:

- `/api/keymap/active.locked` として read-only runtime state を返す。
- keymap editor の保存 payload には lock state を入れない。
- 初期実装では unlock button を作らない。

OLED:

- active lock は短い `LL 2` のような表示にする。
- `OSL` / Caps Word / host lock LED と見分けられる表示にする。
- first slice では未実装。

LED:

- optional overlay 名は `layer_lock` とする。
- host lock LED の `HOST_LED` overlay とは別扱いにする。
- first slice では未実装。

## Static tests

実装済み:

- `QK_LAYER_LOCK` / `QK_LLCK` は target-less layer action として parse される。
- active non-default layer がない時は no-op。
- `MO(2)` 中に lock すると release 後も layer 2 が active に残る。
- `OSL(1)` 中に lock すると `_oneshot` から `_locked` へ移る。
- locked layer で再度 lock key を押すと unlock する。
- `TO(N)`、`DF(N)`、`LayerManager.load()`、layer clear / remove で `_locked` が clear される。
- `active_snapshot()` に `locked` が出る。
- Vial custom keycode 枠にはまだ追加しないことを `script/test_shared_action_defs.py` で固定する。

後続候補:

- output switch 以外の emergency release / all keys release が Layer Lock を clear する必要があるか、
  実機 feedback owner を決める時に再確認する。
- HTTP UI の read-only 表示と、保存 payload に lock state を混ぜない DOM / API test。
- OLED / LED feedback の表示 test。

## Implementation gate

実装済み first slice:

- `LayerManager` に `_locked` を追加しても既存 `momentary` / `toggled` / `oneshot` の互換を壊さない。
- `QK_LAYER_LOCK` / `QK_LLCK` を runtime action 名として処理する。
- output switch の clear path を `input_events.py` に追加する。
- Sticky status design の `layers[].mode == "locked"` と矛盾しない `active_snapshot().locked` を使う。

まだ実装しないもの:

- Vial custom keycode への割当。
- OLED / LED overlay。
- lock state の永続化。

初期対象外の理由:

- Vial custom keycode は 64 枠制限があり、2026-06-05 時点で既存 64 件を使い切っているため追加しない。
  `QK_LAYER_LOCK` / `QK_LLCK` は HTTP Remap の Interaction tab `Runtime helpers` から割り当てる。
- HTTP unlock button は 2026-06-05 first slice で `POST /api/keymap/layer-lock/clear` として追加済み。
  runtime `_locked` だけを解除し、保存 payload には混ぜない。Interaction summary の `Unlock` button は
  `active_snapshot().locked` がある時だけ表示し、解除後に `/api/keymap/active` を再取得する。
- OLED / LED overlay は Caps Word / host lock LED / layer overlay と表示 owner が重なるため、`layer_lock` overlay policy と status freshness test が揃ってから追加する。
