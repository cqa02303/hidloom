# Layer / one-shot completion design

作成日: 2026-06-01

この文書は layer keycode 群、one-shot modifier / one-shot layer、layer lock 周辺の互換性を補完するための設計です。既存 `LayerManager`、Caps Word、Repeat Key、Key Lock と衝突しないように境界を固定します。

## Goal

- QMK/Vial の layer / one-shot 系 keycode の対応方針を整理する。
- transient state と saved keymap を混同しない。
- `OSL` / `OSM` / `MO` / `TG` / `TO` / `DF` / Layer Lock の status を分ける。
- stuck modifier / stuck layer を避ける。

## Current baseline

- `LayerManager` は `momentary` / `toggled` / `oneshot` / `locked` / `conditional` を持つ。
- `MO` / `TG` / `TO` / `DF` / `OSL` / `QK_LAYER_LOCK` は runtime handling 済み。
- Sticky state status は separate design として存在する。

## Candidate keycodes

| keycode | 意味 | 初期扱い |
| --- | --- | --- |
| `OSL(n)` | one-shot layer | 実装済み |
| `OSM(mod)` | one-shot modifier | 候補 |
| `OS_ON` / `OS_OFF` / `OS_TOGG` | one-shot enable control | 後続 |
| `TT(n)` | tap-toggle layer | 設計候補 |
| `LT(n,kc)` | layer-tap | tap-hold 側との統合候補 |
| `LM(n,mod)` | layer + modifier | 後続 |
| `QK_LAYER_LOCK` | current layer lock | first slice 実装済み |

## State owner

- layer state owner は `LayerManager`。
- one-shot modifier owner は `InteractionEngine` または dedicated sticky state helper 候補。
- status は active layer status と sticky state status を分ける。
- saved keymap へ transient state を保存しない。

## Safety policy

- output switch / reload / emergency release で one-shot / locked / transient state を clear。
- stuck modifier を避けるため、modifier zero report と state clear を同じ path に置く。
- `LT` / `TT` は tap-hold timing と同時に扱う。
- layer keycode は HID output へ送らない。

## UI policy

- HTTP status は `momentary` / `toggled` / `oneshot` / `locked` / `conditional` を分ける。
- editor は keycode family ごとに説明を出す。
- one-shot modifier は Caps Lock / Caps Word / Key Lock と見分ける。
- OLED は短い `OSL 2` / `OSM Sft` のような表示候補。

## Static tests to add with implementation

- one-shot modifier press / consume / timeout。
- output switch / reload / emergency release clear。
- `LT` / `TT` timing edge。
- status に transient state が出るが save payload に混ざらない。
- Layer Lock と `TG` / `OSL` の state が混ざらない。

## Implementation gate

実装へ進める条件:

- one-shot modifier owner が決まっている。
- clear path と zero report が固定できる。
- tap-hold 系との優先順位が決まっている。

実装しない条件:

- transient state を keymap config に保存する必要がある。
- layer keycode を HID output として送る必要がある。
