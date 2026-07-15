# QMK alias completion design

作成日: 2026-06-01
更新日: 2026-06-05

この文書は QMK alias を HTTP picker / Vial import / runtime validation でどこまで対応するかの設計です。
2026-06-01 時点では実装へは進まず、canonical action、alias source、conflict warning、custom keycode 64 枠への影響、テスト範囲を固定しました。
2026-06-05 に first implementation slice として、runtime dispatch 前の canonical alias map と
HTTP Interaction metadata / picker wiring を追加しました。

## Goal

- QMK 由来の別名を local canonical action へ安全に正規化する。
- alias 追加で runtime action の意味を変えない。
- Vial custom keycode 64 枠を不用意に消費しない。
- HTTP picker / `.vil` import / config validation の表記ゆれを減らす。

## Alias classes

| class | examples | 初期扱い |
| --- | --- | --- |
| Basic key aliases | `KC_ENT` -> `KC_ENTER`, `KC_ESC` | Basic HID 側 |
| Modifier aliases | `KC_LCTRL` -> `KC_LCTL` | canonicalize 候補 |
| Layer aliases | `QK_LAYER_LOCK` / `QK_LLCK` | runtime action 済み |
| Lighting aliases | `RGB_TOG`, `BL_TOGG` | Lighting alias design 側 |
| System aliases | `QK_BOOT`, `EEP_RST` | Boot / EEPROM design 側 |
| Macro aliases | `QK_MACRO_*` | Vial / QMK macro design 側 |

## Canonicalization policy

- local canonical action を source of truth にする。
- alias map は feature family ごとに分ける。
- first slice では alias canonicalization を `logicd.action_expansion` の dispatch 前展開で行い、保存 payload は書き換えない。
- validation / import 時の canonical replacement は後続の warning schema と一緒に扱う。
- user-facing UI は canonical action を基本表示する。
- original alias を保存する必要がある場合は import warning / source metadata に残す候補。

2026-06-05 runtime canonical aliases:

| alias | canonical |
| --- | --- |
| `KC_CAPS_LOCK` | `KC_CAPSLOCK` |
| `KC_NUM_LOCK` | `KC_NUMLOCK` |
| `KC_SCROLL_LOCK` | `KC_SCROLLLOCK` |
| `KC_PRINT_SCREEN` / `KC_PSCRN` | `KC_PSCREEN` |
| `KC_PAGE_UP` / `KC_PG_UP` | `KC_PGUP` |
| `KC_PAGE_DOWN` / `KC_PG_DOWN` | `KC_PGDN` |
| `KC_BACKSLASH` | `KC_BSLASH` |
| `KC_SEMICOLON` | `KC_SCOLON` |
| `KC_APOSTROPHE` | `KC_QUOTE` |
| `KC_RETURN` | `KC_ENTER` |

## Conflict policy

- 同じ alias が複数 family に属する場合は reject / warning。
- unknown alias は no-op ではなく warning。
- alias 追加で existing custom action index をずらさない。
- alias は runtime state を作らない。

## UI / import policy

HTTP:

- picker では canonical action を基本表示し、2026-06-05 first slice では `canonical_aliases` metadata から
  canonical action と alias の両方を候補 / search 対象にする。

Vial import:

- known alias は canonical action へ変換。
- unknown keycode / alias は raw value と warning を保持する候補。

Config save:

- canonical action で保存する。
- transient state や original alias は保存 payload に混ぜない。

## Static tests to add with implementation

2026-06-05 first slice では runtime dispatch、HTTP metadata、UI wiring、HTTP validation の静的テストを追加済み。
Vial import/export と warning schema へ進む場合は以下を追加する。

- alias map に duplicate canonical conflict がない。
- known alias が canonicalize される。runtime dispatch は追加済み。
- unknown alias warning。
- custom action 64 枠を消費しない。
- HTTP picker search で alias から canonical action が見つかる。Interaction picker metadata wiring は追加済み。
- Vial import/export round-trip。

## Implementation gate

実装へ進める条件:

- feature family ごとの alias owner が決まっている。
- canonical action map が single source に近づいている。
- conflict warning schema がある。

実装しない条件:

- alias を保存時にも original 表記で保持しないと成立しない。
- alias 追加で Vial custom keycode index を変える必要がある。
