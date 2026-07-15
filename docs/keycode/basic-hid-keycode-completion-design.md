# Basic HID keycode completion design

作成日: 2026-06-01

この文書は QMK / Vial 互換の基本 HID keycode を補完するための設計です。実装前に、USB HID usage、Linux input keycode、alias、host layout 依存、HTTP picker、Vial import/export の境界を固定します。

## Goal

- 基本 keyboard keycode の未対応を棚卸しし、HTTP remap / Vial import / runtime validation の差を減らす。
- QMK alias と local action 名を一元化する。
- host layout 依存の文字入力と physical HID usage を混同しない。
- 危険な system / power / macro action は basic HID と分ける。

## Scope

初期対象:

- `KC_A`-`KC_Z`
- `KC_1`-`KC_0`
- punctuation / symbols
- navigation / editing
- function keys
- keypad keys
- modifier keys

初期対象外:

- system control
- consumer control
- lighting
- macro / script
- Unicode / Send String
- mouse movement

## Mapping layers

| layer | 役割 |
| --- | --- |
| local action name | `KC_A` など runtime が扱う文字列 |
| QMK alias | `KC_ENT` -> `KC_ENTER` など |
| USB HID usage | keyboard report へ入る usage id |
| Linux input keycode | uinput fallback 用 |
| HTTP picker group | UI 表示分類 |
| Vial codec | raw keycode import/export |

方針:

- local canonical action を source of truth にする。
- alias は validation / import で canonicalize する。
- host layout の文字は扱わず、HID usage として扱う。

## Completion inventory

- Basic alphanumeric
- Symbol aliases
- Navigation / editing
- Function keys F1-F24
- Keypad / numpad aliases
- International / language keys は後続で host layout warning 付き
- Application / menu keys

## UI policy

- HTTP picker は category ごとに整理する。
- duplicate alias は canonical action へまとめる。
- unsupported key は disabled / warning 表示にする。
- Vial import で unknown keycode が出たら raw value と warning を保持する候補。

## Safety policy

- Basic HID completion は side-effect-free key に限定する。
- System / Power / Consumer / Lighting は別 design に分ける。
- host layout が必要な表示は warning を出す。
- alias 追加で既存 custom action code をずらさない。

## Static tests to add with implementation

設計 first slice では doc test だけを追加する。実装へ進む場合は以下を追加する。

- canonical action map に duplicate がない。
- QMK alias が canonicalize される。
- USB HID usage と uinput keycode が分離される。
- HTTP picker に basic key が出る。
- Vial import/export で canonical action が round-trip する。
- side-effect action が basic HID group に混ざらない。

## Implementation gate

実装へ進める条件:

- canonical action map の source が決まっている。
- alias 追加で Vial custom action 64 枠に影響しない。
- host layout 依存 key の warning 方針がある。

実装しない条件:

- text input / Unicode と同時に扱わないと成立しない。
- system / power / consumer action と同じ map に混ぜる必要がある。
