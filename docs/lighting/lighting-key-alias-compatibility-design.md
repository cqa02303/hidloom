# Lighting key alias compatibility design

作成日: 2026-06-01

この文書は QMK / Vial の RGB / Lighting key alias と、local VialRGB / LED effect action の互換性を整理するための設計です。実装前に alias canonicalization、HTTP picker、Vial import/export、runtime side effect の境界を固定します。

## Goal

- QMK / Vial の lighting alias を local action に安全に対応させる。
- RGB matrix / backlight / underglow / direct-frame / semantic role を混同しない。
- HTTP picker と Vial import/export の表記ゆれを減らす。
- unknown lighting key は silent no-op ではなく warning にする。

## Action families

| family | examples | 初期扱い |
| --- | --- | --- |
| RGB toggle / mode | `RGB_TOG`, `RGB_MOD`, `RGB_RMOD` | VialRGB runtime action 候補 |
| RGB hue / sat / val | `RGB_HUI`, `RGB_HUD`, `RGB_SAI`, `RGB_VAI` | 候補 |
| RGB speed | `RGB_SPI`, `RGB_SPD` | 候補 |
| RGB matrix | `RGB_MATRIX_*` | local VialRGB との対応を確認してから |
| Backlight | `BL_TOGG`, `BL_UP` | LED strip とは別 family として扱う |
| Direct frame | local only | QMK alias とは分ける |
| Semantic role | local only | Lighting key alias とは分ける |

## Canonicalization policy

- local canonical action を source of truth にする。
- QMK / Vial alias は import / validation 時に canonicalize する。
- alias map は shared action defs か lighting metadata へ寄せる候補。
- unknown alias は warning。
- Vial custom keycode 64 枠を不用意に消費しない。

## Runtime boundary

- Lighting key action は `daemon/logicd/lighting.py` の owner 候補。
- ledd effect renderer は state を受け取る consumer。
- direct-frame preview / role preview は runtime-only route として扱う。
- semantic role override / preset sharing は別設計。

## UI policy

- HTTP picker は Lighting group を持つ。
- family ごとに説明を出す。
- unsupported alias は disabled / warning。
- RGB matrix と VialRGB local effect の対応が不明なものは experimental とする。

## Safety policy

- lighting action は keyboard HID output を出さない。
- direct-frame preview は restore path 必須。
- persistent save と runtime preview を分ける。
- unknown alias を no-op で隠さない。
- LED off / restore は Power preset とは owner を分ける。

## Static tests to add with implementation

設計 first slice では doc test だけを追加する。実装へ進む場合は以下を追加する。

- alias canonicalization。
- unknown lighting alias warning。
- HTTP picker Lighting group。
- Vial import/export round-trip。
- direct-frame preview が settings を変更しない。
- semantic role override と lighting key alias が別 field であること。

## Implementation gate

実装へ進める条件:

- canonical lighting action map がある。
- VialRGB state owner と ledd consumer の境界が固定されている。
- direct-frame / role preview の restore path が維持できる。

実装しない条件:

- semantic role と effect key alias を同じ field に保存する必要がある。
- unknown alias を警告なしに受け入れる必要がある。
