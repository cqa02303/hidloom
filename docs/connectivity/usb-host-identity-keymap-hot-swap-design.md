# USB host identity / keymap hot swap design

作成日: 2026-06-01

この文書は USB 接続先や host profile に応じて keymap / profile / layer set を切り替える構想の安全設計です。
2026-06-01 時点では実装へは進まず、host identity の限界、manual profile、hot swap の危険性、rollback、UI 境界を固定します。

## Goal

- host ごとの keymap / profile 切替を検討できるようにする。
- 自動判定に過度に依存しない。
- keymap hot swap で入力不能になる事故を避ける。
- Vial / HTTP / runtime keymap の source of truth を壊さない。

## Current baseline

- Bluetooth host profile は manual profile として設計済み。
- USB gadget は host identity を安定して取得できるとは限らない。
- Runtime keymap は HTTP / Vial / config と連携している。
- output switch / config reload / keymap reload で transient state を clear する方針がある。
- US keyboard と JP thin keyboard を同居させる実装は、先に
  [daemon/specs/hidd/usb-gadget-multi-report-plan.md](../daemon/specs/hidd/usb-gadget-multi-report-plan.md) の Phase 1 で
  `/dev/hidg0` に US keyboard / mouse / consumer control を統合し、Vial Raw HID `/dev/hidg1` を維持する。

## Host identity policy

USB host identity は初期実装では自動判定しない。

理由:

- USB gadget 側から接続先 OS / device を安定識別できるとは限らない。
- hub / dock / KVM 経由で情報が変わる可能性がある。
- host identity を間違えると keymap が意図せず切り替わる。

初期候補:

- manual host profile selection。
- output target profile selection。
- user-selected active profile。
- Bluetooth host address は別経路として扱う。

## Keymap hot swap scope

候補:

| scope | 初期扱い |
| --- | --- |
| modifier map only | 比較的安全な候補 |
| layer enable / default layer | 慎重に検討 |
| full keymap swap | 初期対象外 |
| Vial layout swap | 初期対象外 |
| lighting profile swap | 別設計で扱う候補 |

方針:

- 初期は full keymap swap ではなく、host profile metadata / modifier map から始める。
- full keymap swap は rollback / safe layer / local key がある場合だけ検討する。
- Vial が見ている keymap と runtime keymap が乖離しないようにする。

## Storage candidate

```json
{
  "settings": {
    "host_keymap_profiles": {
      "manual_default": {
        "modifier_map": {},
        "default_layer": 0,
        "keymap_profile": null,
        "enabled": true
      }
    }
  }
}
```

方針:

- `keymap_profile=null` を初期値にする。
- modifier map / default layer は明示設定。
- full keymap profile は別ファイル候補だが初期は未使用。

## Hot swap safety

- swap 前に all keys release / zero report。
- one-shot / layer lock / key lock / repeat history / autocorrect buffer を clear。
- swap 失敗時は前 profile へ戻す。
- safe fallback profile を持つ。
- HTTP / local key で restore できる導線を残す。
- active typing 中の自動 swap はしない。

## UI policy

HTTP:

- 初期は read-only active profile / candidate profile 表示。
- manual select は confirmation 付き候補。
- full keymap swap は初期 UI に出さない。
- Vial save 中 / unlock 中は profile swap を禁止する候補。

OLED:

- `Profile iOS` のような短い表示候補。
- 常時表示はしない。

## Relation to other features

| feature | 境界 |
| --- | --- |
| Host profile | host metadata と modifier / layout の軽い差分。 |
| Vial keymap | source of truth の衝突に注意。full swap は初期対象外。 |
| HID multi-report consolidation | endpoint 節約と JP thin keyboard 追加の前提。Raw HID / Vial は統合しない。 |
| Power preset | output target / radio state とは分ける。 |
| Layer Lock / Key Lock | hot swap 前に transient state clear。 |

## Static tests to add with implementation

設計 first slice では doc test だけを追加する。
実装へ進む場合は以下を追加する。

- full keymap swap は default disabled。
- manual profile selection は confirmation 必須。
- swap 前に transient state clear。
- failed swap rollback。
- Vial save / unlock 中に swap しない。
- USB host identity 自動判定に依存しない。

## Implementation gate

実装へ進める条件:

- manual profile selection の UX がある。
- modifier map など小さい scope から始められる。
- rollback / safe fallback がある。
- Vial / HTTP / runtime keymap source of truth を壊さない。

実装しない条件:

- USB host identity 自動判定が必須になる。
- full keymap swap から始める必要がある。
- rollback なしで keymap を切り替える必要がある。
