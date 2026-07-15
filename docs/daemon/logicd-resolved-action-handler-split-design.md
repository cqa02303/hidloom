# logicd resolved action handler split design

更新日: 2026-06-02

この文書は、`daemon/logicd/input_events.py` の `handle_resolved_action()` を将来的に action family ごとへ分割するための設計TODOです。

## 背景

`handle_resolved_action()` は、matrix input path の後段で resolved action を処理する境界です。
現在は以下の責務が同じ関数に集まっています。

- output switch 前の transient state clear
- host LED overlay fallback
- layer action
- animation action
- lighting key action
- Bluetooth passkey / BT action
- Wi-Fi action
- BT output preparation
- macro / HID report action

matrix socket intake と `process_matrix_event()` は軽量に保つ方針を静的テストで固定済みです。
一方で、`handle_resolved_action()` 自体は今後さらに肥大化しやすいため、実装を急がず分割方針を先に固定します。

関連:

- [matrixd/stability-docs.md](specs/matrixd/stability-docs.md)
- [daemon/logicd/README.md](../../daemon/logicd/README.md)

## 基本方針

- raw matrix socket intake は packet parse と queue put に留める。
- `process_matrix_event()` は matrix press state、InteractionEngine、resolved event dispatch に留める。
- BT / Wi-Fi / macro / output preparation など重い可能性がある処理は resolved action 境界に置く。
- ただし resolved action 境界内でも、action family ごとに helper を分けて見通しを保つ。
- 分割時も action 処理順序は変えない。
- 分割時も既存 test を先に通し、追加 test で順序と責務を固定する。

## 分割候補

初期候補:

```text
handle_output_switch_pre_action()
handle_host_led_overlay_action()
handle_layer_resolved_action()
handle_animation_resolved_action()
handle_lighting_resolved_action()
handle_bt_passkey_resolved_action()
handle_bt_resolved_action()
handle_wifi_resolved_action()
handle_bt_output_prepare_action()
handle_macro_resolved_action()
```

最初から過剰に class 化しない。
まずは `daemon/logicd/input_events.py` 内の private helper に分割し、テストで境界を固定してから必要に応じて module 分割を検討します。

## 処理順序

現行順序は維持する。

1. output switch action の前処理
   - runtime shortcuts clear
   - layer lock clear
2. host LED overlay fallback
3. layer action
4. animation action
5. lighting key action
6. BT passkey input
7. BT action
8. Wi-Fi action
9. `KC_BT` output preparation
10. macro / HID report action

この順序は、互換性と副作用の見通しのために重要です。

## 受け入れ条件

分割実装を行う場合、最低限以下を満たす。

- `script/test_logicd_matrix_input_priority.py` が通る。
- `script/test_logicd_matrix_event_processing_boundary.py` が通る。
- `script/test_logicd_output_router_boundary.py` が通る。
- `script/test_logicd_resolved_action_heavy_boundary.py` が通る。
- 既存の layer / lighting / BT / Wi-Fi / macro 関連テストが通る。
- `handle_resolved_action()` の外部 signature を変えない。
- `process_matrix_event()` に BT / Wi-Fi / macro / output preparation を戻さない。
- action family helper は直接 socket intake を触らない。

## 初期実装しないこと

- `handle_resolved_action()` の class 化。
- action registry / plugin 化。
- HTTP UI から action handler 順序を変更できる仕組み。
- BT / Wi-Fi / macro の実挙動変更。
- output target policy の変更。

## 実機なし first slice

実機なしで進めるなら、次の小さな順序にする。

1. 現行 `handle_resolved_action()` の順序を静的テストで固定する。
2. 1つずつ private helper に切り出す。
3. 各 helper に短いコメントを付け、重い action が raw matrix path へ戻らないようにする。
4. `daemon/logicd/README.md` に resolved action boundary を短く記録する。

## 実機確認

実機では、以下だけ確認する。

- 通常キー入力の遅延が増えない。
- output switch action の挙動が変わらない。
- BT / Wi-Fi action の alert / OLED 表示が変わらない。
- macro action が従来通り送信される。

## 現時点の判断

2026-06-02 時点では、分割実装はまだ行わない。
まずは設計TODOとして残し、matrixd / logicd input path の安定化が一区切りした後に、必要になったら helper 化する。
