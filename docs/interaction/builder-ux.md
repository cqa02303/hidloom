# Interaction Builder UX

作成日: 2026-06-01

この文書は Combo / Tap Dance / Key Override / Timing builder の UX 境界をまとめます。
2026-06-01 時点では、実機なしで進められる first slice として `daemon/http/interaction_builder_ux.py` の read-only metadata helper、`GET /api/interaction/builder-ux`、Interaction tab の builder subtitle / hover helper、Combo row / col key block layout、keyboard 表示からの `Pick key` source selector、静的テストを追加しました。
2026-06-04 に Tap Dance / Key Override を含む action input へ role 別 helper を追加し、既存 Remap action picker を優先して再利用する `Pick` / read-only `Plan` の操作境界を固定しました。metadata は subtitle / inline warning / input helper に分散し、追加 textarea で縦に伸ばさない方針にしました。
同日、`interaction.builder_ux.polish.v1` として Tap Dance / Key Override の polish を完了扱いにし、
Tap Dance は `TD(name)` definition と keymap assignment を分離、Key Override は action name editor として固定、
warning は inspector validation owner に寄せる dedupe rule を固定しました。
2026-06-05 に Tap Dance summary の `Edit` 対象を追跡し、既存定義を読み戻して name を変更した場合も
旧 name を残さず同じ定義として置き換えるようにしました。別の既存 name への rename は上書きせず警告します。

## Goal

Interaction tab の builder を、既存 `settings.interaction` schema を壊さずに使いやすくします。
特に Combo の source key は keycode ではなく物理 matrix position なので、Tap Dance / Key Override の action picker と混同しない表示にします。

## Builder metadata

`daemon/http/interaction_builder_ux.py` は以下を返します。

```json
{
  "result": "ok",
  "schema": "interaction.builder_ux.v1",
  "route": "/api/interaction/builder-ux",
  "read_only": true,
  "builders": {
    "combo": {},
    "tap_dance": {},
    "key_override": {},
    "timing": {}
  },
  "selection_modes": {
    "matrix_position": {},
    "action_picker": {}
  },
  "polish_status": {
    "schema": "interaction.builder_ux.polish.v1",
    "status": "first_slice_complete"
  }
}
```

各 builder の metadata は次の field を持ちます。

| field | 意味 |
| --- | --- |
| `key` | builder 識別子。保存 key ではない。 |
| `title` | UI 見出し。 |
| `subtitle` | hover overlay / short help 用の短い説明。 |
| `source_policy` | source key / action picker の使い分け。 |
| `save_scope` | どの `settings.interaction` field に反映するか。 |
| `warnings` | 初見補助用の注意。 |

## Source / action boundary

### Combo

Combo は複数の物理キーを同時押しした時に action を出します。

- source は keycode ではなく matrix position。
- 保存先は `settings.interaction.combos[]`。
- 将来 UI では rendered keymap から source key を選ぶ操作を優先する。
- row / col 直接入力は fallback として残す。
- 同じ source key を複数 combo で共有すると誤爆しやすいので inspector warning と合わせる。

### Tap Dance

Tap Dance は同じ物理キーの tap 回数で action を切り替えます。

- builder は `TD(name)` の定義を編集する。
- keymap 側には別途 `TD(name)` を割り当てる必要がある。
- 保存先は `settings.interaction.tap_dances{}`。
- source key の matrix position はこの builder では保存しない。
- summary の `Edit` から読み戻した定義は、name を変えて保存しても旧 name を残さず置換する。
- rename 先が別の既存定義と衝突する場合は保存しない。

### Key Override

Key Override は指定 trigger が押されている時だけ対象 key action を置き換えます。

- trigger / key / replacement は action 名。
- row / col ではない。
- 保存先は `settings.interaction.key_overrides[]`。
- Mod-Morph と同じ key にかかる場合は inspector / conflict warning を確認する。

### Timing

Timing は global timing knobs です。

- source key はない。
- 保存先は `settings.interaction` の timing fields。
- 小さすぎる値は実機で取りこぼしやすく、大きすぎる値は入力遅延として体感される。

## UI policy

first slice:

- helper は read-only。
- HTTP route は `GET /api/interaction/builder-ux`。
- helper は config を保存しない。
- helper は既存 HTML / JS の保存 flow を変更しない。
- subtitle は Interaction tab の builder 見出し直下へ compact help として表示し、`source_policy` / `save_scope` は hover helper に使う。
- Combo の row / col fallback 入力は key 単位の block として扱い、異なる key の row / col が横並びで混ざらないようにする。
- Combo の `Pick key` は keyboard 表示へ一時遷移し、次に押した matrix key を source row / col へ入れる。Interaction editor へ戻る時は再 fetch しない。
- Tap Dance / Key Override は既存 Remap action picker を優先して再利用し、fallback picker も検索 / 選択 / 確定を持つ。
- metadata は subtitle / inline warning / action input helper に分散し、追加 textarea を増やさない。
- DOM 静的テストで Tap Dance / Key Override picker helper の存在を固定する。
- Tap Dance は `TD(name)` の definition owner であり、keymap assignment は `Copy TD` / Remap flow へ分ける。
- Key Override は action name editor であり、matrix position は Combo 専用とする。
- warning 表示は summary metric / accordion `Warn N` / builder inline warning を inspector validation owner にし、helper text は editor scope だけを説明する。

後続候補:

- 実使用で足りない専用 editor 操作が見えた時だけ、Tap Dance / Key Override の入力補助を追加する。

## Static tests

実装済み:

- builder metadata に `combo` / `tap_dance` / `key_override` / `timing` が揃っている。
- Combo は matrix position / row-col fallback として扱う。
- Tap Dance は `TD(name)` 定義であり、source matrix position を保存しない。
- Key Override は action picker / action 名を扱う。
- `GET /api/interaction/builder-ux` と Interaction tab subtitle / hover helper が接続されている。
- Combo row / col fallback は key 単位の block layout で表示される。
- Combo source key は keyboard 表示から click / tap 選択できる。
- Tap Dance / Key Override / Combo action input には role 別 helper があり、`Pick` は共有 Action picker、`Plan` は read-only Text Send preview を開く。
- `interaction.builder_ux.polish.v1` は Tap Dance / Key Override の editor scope、assignment flow、warning dedupe rule を固定する。
- helper は read-only で設定を保存しない。

## Non-goals

- first slice では DOM を大きく組み替えない。
- first slice では保存 schema を変えない。
- first slice では実機打鍵の良し悪しを判定しない。
