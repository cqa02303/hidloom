# LED role editor / semantic override design

作成日: 2026-06-01

この文書は LED role の自動判定に対して、ユーザーが semantic role を手動 override するための設計です。
2026-06-01 時点では実装へは進まず、保存形式、auto role inspector、preview / restore、conflict warning、UI 境界を固定します。

## Goal

- 自動 role 判定を壊さず、必要な LED だけを手動 override できるようにする。
- role override は LED index / matrix position / semantic role を明確に分ける。
- preview は side-effect-free を基本にし、実LED preview は restore path 必須にする。
- VialRGB effect / host lock overlay / layer overlay と semantic override を混同しない。

## Current baseline

- LED role preview / real-LED route は実装済み。
- Auto role inspector / LED role tuning design は read-only 設計済み。
- Lighting tab には preview / restore の安全境界がある。
- LED Life Game effect など、effect 側と semantic role 側の責務を分ける必要がある。

## Storage candidate

```json
{
  "settings": {
    "lighting": {
      "role_overrides": {
        "led:0": {
          "role": "modifier",
          "source": "manual",
          "note": "thumb modifier"
        },
        "matrix:1,2": {
          "role": "layer_key",
          "source": "manual"
        }
      }
    }
  }
}
```

方針:

- `led:<index>` は physical LED index を指定する。
- `matrix:<row>,<col>` は key position に紐づく LED role を指定する候補。
- 初期実装ではどちらか一方に絞るか、UI で明示的に区別する。
- role name は known semantic role の allowlist に限定する。
- unknown role は warning / reject。

## Role source priority

候補 priority:

1. manual override
2. board profile explicit role
3. auto role inspector result
4. fallback role

方針:

- auto role inspector は manual override を上書きしない。
- manual override は config reload 後も保持される。
- runtime preview は persistent override と分ける。
- role source を status / inspector に出す。

## UI policy

HTTP Lighting tab:

- 初期は read-only inspector + manual override editor 候補。
- role picker は known roles のみ。
- LED index と matrix position の指定方法を混ぜない。
- preview button は save ではないことを明示する。
- restore button は実LED preview で必須。
- bulk edit は後続。

Warning:

- unknown LED index。
- matrix position に LED がない。
- auto role と manual override が異なる。
- host lock / layer overlay / effect state と role を混同している可能性。

## Runtime / preview boundary

- saved override は `settings.lighting.role_overrides`。
- preview override は runtime-only。
- effect renderer は effective role snapshot を読む。
- renderer は role override config を直接保存しない。
- real-LED preview は before state を保存し、restore path を持つ。

## Relation to LED role preset sharing

- semantic override は local setting。
- preset sharing / import-export は別設計で扱う。
- preset import 時も manual override を上書きするかは confirmation 必須候補。

## Static tests to add with implementation

設計 first slice では doc test だけを追加する。
実装へ進む場合は以下を追加する。

- known role allowlist validation。
- unknown LED index warning。
- manual override が auto role より優先される。
- preview override が settings に保存されない。
- real LED preview に restore path がある。
- HTTP save payload が effect runtime state を混ぜない。

## Implementation gate

実装へ進める条件:

- LED index と matrix position のどちらを first UI にするか決まっている。
- known semantic role allowlist がある。
- preview / save / restore の UI 表示が分かれている。
- auto role inspector と manual override の priority がテストで固定できる。

実装しない条件:

- effect state と semantic role を同じ保存 field に混ぜる必要がある。
- restore path なしで実LED preview を行う必要がある。
- unknown role を自由文字列で保存する必要がある。
