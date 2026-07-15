# Digitizer / Haptic / Steno feature design

作成日: 2026-06-01

この文書は HID digitizer、haptic feedback、steno 入力などの大型機能候補を、既存 keyboard / mouse / LED / audio 設計と分けて整理するための設計です。
2026-06-01 時点では実装へは進まず、各機能の owner、HID report、hardware dependency、UI 境界、実機確認範囲を固定します。

## Goal

- 大型機能を keyboard core に混ぜず、候補として分離する。
- HID report descriptor 変更が必要なものを default 無効にする。
- haptic / digitizer / steno の owner と hardware dependency を明確にする。
- 実機なしで実装に入らない。

## Feature candidates

| feature | 内容 | 初期扱い |
| --- | --- | --- |
| Digitizer | absolute pointer / pen / touch report | HID descriptor 変更が必要。設計のみ |
| Haptic | vibration / click feedback | hardware port が必要。設計のみ |
| Steno | chorded steno input / protocol output | keymap / combo と競合。設計のみ |
| Sequencer | MIDI / audio sequence | MIDI sequencer design 側 |

## Digitizer boundary

- Mouse HID extension とは分ける。
- absolute coordinate / touch contact / pen pressure は keyboard report とは別 descriptor。
- USB / BLE host compatibility が大きい。
- default disabled。
- HTTP から raw digitizer report を送らない。

## Haptic boundary

- Hardware ports / buzzer / IR design と連携。
- haptic actuator pin / driver / duty / duration の board profile が必要。
- keyboard scan / LED timing を阻害しない non-blocking output が必要。
- default disabled。
- power preset / low power で stop する候補。

## Steno boundary

- Combo / chorded input と競合する可能性が高い。
- steno mode は explicit mode にする候補。
- normal keymap と同時に発火しないよう suppression が必要。
- output は keyboard text / protocol / serial など別設計が必要。
- default disabled。

## UI policy

- 初期は Wishlist / design status 表示のみ。
- enable button は作らない。
- hardware dependency と HID descriptor dependency を明示する。
- 実機確認 checklist に移すまで implementation TODO にしない。

## Safety policy

- descriptor 変更が必要なものは opt-in。
- hardware pin が必要なものは board profile 必須。
- output switch / reload / emergency release で stop / clear。
- keyboard core の latency を増やさない。
- direct raw report / arbitrary actuator control は初期対象外。

## Static tests to add with implementation

設計 first slice では doc test だけを追加する。実装へ進む場合は以下を追加する。

- default disabled。
- digitizer descriptor opt-in。
- haptic board profile pin required。
- steno mode explicit。
- output switch / emergency release clear。
- raw report / arbitrary actuator control reject。

## Implementation gate

実装へ進める条件:

- 実機 hardware / host compatibility の確認対象がある。
- HID descriptor 変更の rollback がある。
- board profile dependency が固定できる。
- keyboard core latency を測定できる。

実装しない条件:

- descriptor 変更を default 有効にする必要がある。
- hardware dependency なしで haptic を有効化する必要がある。
- steno mode を通常 keymap と同時発火させる必要がある。
