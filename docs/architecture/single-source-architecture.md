# Single Source Action Architecture

作成日: 2026-05-19

現在進めている「single source of truth 化」の設計メモです。

## 背景

以前は:

- runtime parser
- HTTP validation
- Vial codec
- tests

がそれぞれ別に action 名を持っていました。

例:

```text
MO/TG/TO/DF/OSL
```

や:

```text
BT_*
RGB_*
KC_USB
```

などが複数箇所へ重複定義されていました。

そのため:

- OSL が runtime だけ対応
- HTTP validation が拒否
- Vial codec が export/import 失敗

のようなズレが発生していました。

## 現在の設計

現在は:

```text
daemon/logicd/shared_action_defs.py
```

を中心に整理している。

## shared_action_defs.py が持つもの

### modifier wrappers

例:

```text
S
LCTL
RGUI
```

### layer actions

```text
MO
TG
TO
DF
OSL
```

### Vial layer action base

```text
MO -> 0x5100
TG -> 0x5300
DF -> 0x5200
```

### Vial custom actions

例:

```text
BT_*
KC_USB
RGB_*
OSL(*)
```

### custom action maps

- action -> keycode
- keycode -> action

## 現在参照しているもの

### HTTP validation

```text
daemon/http/keymap_actions.py
```

### runtime parser tests

```text
script/test_shared_action_defs.py
```

### shared regression tests

```text
script/test_vial_keycode_codec.py
```

## 残り

### Vial codec の完全移行

対象:

```text
daemon/viald/keycode_codec.py
```

削除予定:

```python
_VIAL_CUSTOM_ACTIONS
_VIAL_CUSTOM_BY_ACTION
```

置換:

```python
shared_vial_custom_actions()
shared_vial_custom_action_map()
shared_vial_custom_action_reverse_map()
```

## 最終目標

```text
shared_action_defs.py
        ↓
runtime
HTTP validation
Vial codec
tests
```

将来的には:

```text
config/default/keycodes.json
        ↓
auto-generated metadata
```

まで進めたい。
