# Action Validation Unification Plan

作成日: 2026-05-19
更新日: 2026-05-19

現在の action validation 状況と、今後の統一方針をまとめたメモです。

## 現在の状態

現在、action string は複数 subsystem で扱われている。

- runtime parser
- HTTP validation
- Vial codec
- interaction validation
- regression tests

以前は subsystem ごとに独自 validation を持っていた。

現在は:

```text
daemon/logicd/shared_action_defs.py
```

へ徐々に集約中。

## 現在 shared 化済み

### modifier wrappers

例:

```text
S(KC_1)
LCTL(KC_A)
```

### layer actions

例:

```text
MO(1)
TG(2)
OSL(3)
```

### Vial custom actions

例:

```text
BT_*
RGB_*
KC_USB
```

### action classifier helpers

実装済み:

```python
parse_shared_layer_action(action)
is_layer_action(action)
is_layer_action_in_range(action, max_layers=32)
is_wrapper_action(action)
is_animation_action(action)
is_unicode_action(action)
is_macro_action(action)
is_script_action(action)
```

HTTP keymap validation は、layer action / wrapper action の判定に shared helper を使う。

## まだ subsystem ごとの差が残っているもの

### script actions

例:

```text
SCRIPT(foo)
```

classifier helper は追加済みだが、HTTP validation / runtime / import-export での扱いはまだ統一途中。

### macro actions

例:

```text
MACRO:name
```

classifier helper は追加済みだが、KML / QMK macro compatibility / script runner の dispatch 方針は別途整理する。

### animation actions

例:

```text
ANIM(3)
```

classifier helper は追加済み。HTTP validation で許可するかは UI policy 次第。

### unicode actions

例:

```text
U+3042
```

classifier helper は追加済み。HTTP validation で許可するかは UI policy 次第。

## 今後の方針

将来的には:

```text
shared_action_defs.py
```

へ:

- regex definitions
- parser helpers
- validation helpers
- metadata

を集約する。

## staged migration plan

### Stage 1

完了済み:

- shared modifier wrappers
- shared layer actions
- shared Vial custom actions
- shared Vial custom maps

### Stage 2

完了済み:

```python
is_layer_action(action)
is_layer_action_in_range(action)
is_wrapper_action(action)
```

HTTP validation は `is_layer_action_in_range()` と `is_wrapper_action()` を利用する。

### Stage 3

一部完了:

```python
is_macro_action(action)
is_script_action(action)
is_unicode_action(action)
is_animation_action(action)
```

残り:

- HTTP validation で許可するかどうかの policy 決定
- interaction validation への適用
- Vial import/export での扱い整理

### Stage 4

validation strictness policy 分離:

- runtime parser
- HTTP validation
- import/export validation

## 最終目標

```text
shared_action_defs.py
        ↓
runtime
HTTP validation
Vial codec
interaction validation
tests
```

## 注意点

validation を厳しくしすぎると:

- future actions
- experimental actions
- script actions

を阻害する可能性がある。

そのため:

- runtime parser
- UI validation
- import/export validation

の厳しさを分ける可能性がある。
