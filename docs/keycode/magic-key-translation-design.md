# Magic key translation design

作成日: 2026-06-01

この文書は QMK Magic key のうち、Raspberry Pi 実装で意味があるもの・ないものを分けるための設計です。
2026-06-01 時点では実装へは進まず、runtime option、persistent config、dangerous reset、debug setting、alias translation、テスト範囲を固定します。

## Goal

- QMK Magic key をそのまま EEPROM / bootloader 前提で解釈しない。
- Raspberry Pi 実装で意味がある action だけを local action へ対応させる。
- runtime toggle と persistent setting を分ける。
- destructive reset と debug toggle を混同しない。

## Candidate classes

| class | examples | 初期扱い |
| --- | --- | --- |
| swap modifier | `MAGIC_SWAP_CONTROL_CAPSLOCK` | host profile / modifier map と連携候補 |
| debug | `MAGIC_TOGGLE_DEBUG` | debug action design 側と連携候補 |
| EEPROM / reset | `MAGIC_UNSWAP_*`, reset 系 | dangerous。初期は no-op + warning |
| NKRO toggle | `MAGIC_TOGGLE_NKRO` | HID report descriptor / backend 依存。後続 |
| GUI disable | `MAGIC_NO_GUI` | key filter / modifier map 候補 |

## Policy

- Magic key は alias / compatibility layer として扱う。
- runtime setting だけ変えるものと persistent config を変えるものを分ける。
- host profile / keymap profile / modifier map と重なるものは conflict warning。
- EEPROM reset 相当は Boot / EEPROM design に委譲。
- NKRO など report descriptor に関係するものは default no-op + warning。

## UI / import policy

- HTTP picker では Advanced / Compatibility group に置く。
- Vial import で Magic key が来た場合は local compatibility warning を出す候補。
- unknown Magic key は warning。
- save payload には canonical local action を保存する。

## Safety policy

- destructive reset は実装しない。
- persistent setting 変更は confirmation 必須。
- output switch / reload 中は runtime toggle を拒否する候補。
- Magic key で host profile を暗黙変更しない。

## Static tests to add with implementation

設計 first slice では doc test だけを追加する。実装へ進む場合は以下を追加する。

- known Magic key alias が classification される。
- unknown Magic key warning。
- reset 系 Magic key は destructive path へ直行しない。
- runtime toggle と persistent setting が分離される。
- host profile modifier map と conflict warning。

## Implementation gate

実装へ進める条件:

- Magic key の owner family が決まっている。
- persistent setting 変更の confirmation がある。
- alias warning schema がある。

実装しない条件:

- QMK EEPROM semantics をそのまま再現する必要がある。
- report descriptor を runtime で切り替える必要がある。
