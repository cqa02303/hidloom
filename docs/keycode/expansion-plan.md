# Keycode Expansion Plan

作成日: 2026-05-19

現在の keycode 実装状況と、今後追加予定の QMK/Vial 互換 keycode を整理したメモです。

## 現在の状態

既に対応済み:

- 基本 USB HID keyboard page
- Basic HID command usage first slice (`KC_EXECUTE` / `KC_HELP` / `KC_MENU` / `KC_SELECT` / `KC_STOP` / `KC_AGAIN` / `KC_CANCEL` / `KC_CLEAR` など)
- `KC_SYSTEM_REQUEST` の単独 Keyboard Page usage `0x9A`
- `KC_LANG6`-`KC_LANG9`
- `KC_KP_EQUAL_AS400`
- `KC_LOCKING_CAPS_LOCK` / `KC_LOCKING_NUM_LOCK` / `KC_LOCKING_SCROLL_LOCK`
- Consumer page media keys
- Mouse keys
- `MS_BTN1`-`MS_BTN5`
- `MS_ACL0`-`MS_ACL2`
- Layer actions (`MO/TG/TO/DF/OSL`)
- Modifier wrappers (`S(kc)`, `LCTL(kc)` など)
- Space Cadet
- RGB aliases
- BT control actions
- Vial custom keycodes

## 追加候補

### Command / Application 系 follow-up

2026-06-07 の Basic HID runtime slice で、Keyboard Page 内の command usage は
`config/default/keycodes.json` / Vial codec / HTTP keycode payload / runtime report に追加済み。
`KC_SYSTEM_REQUEST` は単独 usage と host 入力欄目視確認まで対応済み。
`<keyboard-host>` から `KC_HELP` / `KC_SYSTEM_REQUEST` を単独送信した smoke では、入力欄へ可視文字は出ず、
marker text と `Ctrl+Enter` は正常に届いた。host OS の SysRq modifier 組み合わせ動作は
private workspace reference *(omitted from public export)* の実機確認待ちに残す。

残りの follow-up は、host OS ごとの反応差を実機で確認したあとに、
表示 label や script helper 候補を増やす必要があるか判断する。

## System Control 系

候補:

- `KC_SYSTEM_POWER`
- `KC_SYSTEM_SLEEP`
- `KC_SYSTEM_WAKE`

注意:

これらは通常 keyboard report page ではなく、
Generic Desktop / System Control page が必要になる可能性がある。

現状の HID gadget descriptor のままでは不十分な可能性がある。

## Language 6-9

2026-06-07 の Basic HID runtime slice で対応済み。
Linux uinput fallback は host layout / keycode が曖昧なため `linux=null` にしている。

## Locking keys

2026-06-07 の Basic HID runtime slice で対応済み。
通常の `KC_CAPSLOCK` / `KC_NUMLOCK` / `KC_SCROLLLOCK` とは alias 化せず、
別 usage として扱う。

## Mouse Keys follow-up

`MS_BTN1`-`MS_BTN5` と `MS_ACL0`-`MS_ACL2` は対応済み。
`MS_BTN6`-`MS_BTN8` は Mouse HID report の button bit / descriptor 拡張が必要なため、
[../hid/mouse-hid-extension-design.md](../hid/mouse-hid-extension-design.md) で扱う。

## 実装時に同期が必要な場所

新しい keycode を追加するときは、以下を同期する必要がある。

### 1. keycode定義

```text
config/default/keycodes.json
```

### 2. Vial codec

```text
daemon/viald/keycode_codec.py
```

### 3. HTTP validation

```text
daemon/http/keymap_actions.py
```

### 4. shared action definitions

```text
daemon/logicd/shared_action_defs.py
```

### 5. regression tests

```text
script/test_vial_keycode_codec.py
script/test_shared_action_defs.py
```

## 今後の方針

現在、single source of truth 化を進めている。

最終目標:

```text
shared_action_defs.py
        ↓
HTTP validation
Vial codec
runtime
regression tests
```

可能なら将来的には:

```text
config/default/keycodes.json
        ↓
auto-generated metadata
```

まで進めたい。
