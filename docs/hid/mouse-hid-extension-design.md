# Mouse HID extension design

作成日: 2026-06-01

この文書は mouse movement / wheel / button / drag lock / PAW3805EK などを含む Mouse HID 拡張の設計です。Keyboard HID と混ぜず、mouse report owner と action validation を整理します。

## Goal

- Mouse button / wheel / relative movement の keycode 対応を整理する。
- PAW3805EK mounted cursor と keymap action の mouse output を同じ report owner に寄せる。
- Drag Lock / Key Lock と mouse button state の source を分ける。
- USB / BLE / uinput の mouse report 差分を隠蔽する。

## Scope

初期対象:

- `KC_BTN1`-`KC_BTN5`
- `MS_BTN1`-`MS_BTN5`
- `KC_WH_U` / `KC_WH_D` / `KC_WH_L` / `KC_WH_R`
- `MS_UP` / `MS_DOWN` / `MS_LEFT` / `MS_RGHT`
- `MS_ACL0` / `MS_ACL1` / `MS_ACL2`
- Drag Lock preset
- PAW3805EK dx/dy transform

初期対象外:

- absolute pointer
- digitizer / touch
- multi-touch gesture
- high resolution scroll

## Runtime slice

2026-06-07 first runtime slice:

- `MS_ACL0` / `MS_ACL1` / `MS_ACL2` を `logicd` の key-driven mouse movement profile として実装した。
- Profile は runtime only で、keymap action 押下時に低速 / 標準 / 高速へ切り替える。
- 対象は `KC_MS_*` / `KC_WH_*` による key-driven cursor / wheel 出力のみ。`spid` raw motion、joystick cursor、BLE / USB report map は変更しない。
- Vial v5 mouse special keycode `253`-`255` と HTTP keycode payload に接続した。

2026-06-07 alias slice:

- `MS_BTN1`-`MS_BTN5` を既存 `KC_BTN1`-`KC_BTN5` と同じ 5-button Mouse HID report usage へ接続した。
- `MS_BTN6`-`MS_BTN8` は report bit 拡張が必要なため、引き続き初期対象外にする。

## Owner / state

- mouse report owner は `logicd` output path。
- sensor raw motion owner は `spid`。
- Key Lock synthetic source は `key_lock` helper。
- physical button / synthetic lock / sensor motion を source 分離する。
- output switch / emergency release で mouse zero report を出す。

## Safety policy

- stuck button を避けるため zero report path を必須にする。
- synthetic lock と physical press を混ぜない。
- sensor failure は keyboard output を止めない。
- movement rate limit / queue backpressure を持つ候補。
- BLE mouse report 対応は host 互換確認後に広げる。

## UI policy

- HTTP picker は mouse group を keyboard group と分ける。
- Drag Lock は unsafe ではないが stuck button warning を出す候補。
- PAW3805EK settings は device settings 側に置く。
- Mouse HID output availability を System panel に read-only 表示する候補。

## Static tests to add with implementation

- mouse keycode validation。
- button press/release report。
- wheel report。
- output switch / emergency release zero report。
- physical / synthetic source 分離。
- PAW3805EK sensor failure が keyboard output を止めない。

## Implementation gate

実装へ進める条件:

- mouse report owner が決まっている。
- zero report path がテストで固定できる。
- BLE / USB / uinput backend の mouse report 差分を隠蔽できる。

実装しない条件:

- absolute pointer / multi-touch を同時に入れる必要がある。
- source 分離なしで Drag Lock を実装する必要がある。
