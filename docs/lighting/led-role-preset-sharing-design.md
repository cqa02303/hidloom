# LED role preset sharing / import-export design

作成日: 2026-06-01

この文書は LED semantic role / role override / effect preset を、local file として保存・import/export するための設計です。
2026-06-01 時点では実装へは進まず、preset file format、versioning、manual override との関係、import confirmation、UI 境界を固定します。

## Goal

- LED role tuning / semantic override を再利用しやすくする。
- effect preset と semantic role preset を混同しない。
- import 時に既存 manual override を意図せず上書きしない。
- 外部共有は後続とし、まず local file import/export を安全に設計する。

## Preset categories

| category | 内容 | 初期扱い |
| --- | --- | --- |
| `semantic_roles` | LED role override / role map | 候補 |
| `vialrgb_effect` | VialRGB mode / hue / speed / value など | 候補 |
| `overlay_theme` | host lock / layer / caps word などの overlay 色 | 後続 |
| `combined` | 上記をまとめる | 初期は避ける |

方針:

- 初期は category を分ける。
- combined preset は import の影響範囲が広いため後続。
- category ごとに validation と confirmation を分ける。

## File format candidate

```json
{
  "schema": "hidloom.led_role_preset.v1",
  "category": "semantic_roles",
  "name": "thumb-heavy",
  "created_by": "local",
  "roles": {
    "led:0": "modifier",
    "led:1": "layer_key"
  },
  "notes": "example"
}
```

方針:

- JSON を初期形式にする。
- `schema` と `category` は必須。
- unknown category は reject。
- unknown role は warning / reject。
- import preview を先に出し、save とは分ける。

## Storage policy

候補:

```text
/mnt/p3/presets/led/semantic_roles/<name>.json
/mnt/p3/presets/led/effects/<name>.json
config/default/presets/led/semantic_roles/<name>.json
config/default/presets/led/effects/<name>.json
```

- `/mnt/p3` は user preset。
- `config/default/` は sample / factory default。
- file name は `[A-Za-z0-9_.-]{1,64}` に限定する。

## Import policy

- import は preview / validation / apply の 3段階候補。
- manual override を上書きする場合は confirmation 必須。
- unknown LED index / unknown role は warning。
- runtime preview は settings に保存しない。
- apply 後に restore したい場合は backup snapshot を残す候補。

## Export policy

- export は category ごとに分ける。
- semantic role export は effective role ではなく manual override を第一候補にする。
- auto role result を export する場合は source を `auto_snapshot` と明記する。
- effect runtime state と semantic role override を混ぜない。

## UI policy

HTTP Lighting tab:

- preset list は local files を read-only で表示する。
- import は preview summary を出す。
- apply は explicit button。
- export は current category を選んで行う。
- community upload / ranking は初期対象外。

## Safety policy

- external URL import は初期対象外。
- preset import で system / script / connectivity action を扱わない。
- unknown schema は reject。
- large file は size limit を設ける。
- preset apply は VialRGB runtime effect と semantic role override の owner を混ぜない。

## Static tests to add with implementation

設計 first slice では doc test だけを追加する。
実装へ進む場合は以下を追加する。

- schema / category validation。
- unknown role reject / warning。
- manual override overwrite confirmation。
- import preview が settings を変更しない。
- export は category ごとに分かれる。
- external URL import が無効。

## Implementation gate

実装へ進める条件:

- semantic role override schema が固定されている。
- category 別 import/export の validation が作れる。
- import preview と apply が分かれている。
- preset apply が runtime effect state を混ぜない。

実装しない条件:

- external sharing / ranking まで同時に必要になる。
- combined preset だけで始める必要がある。
- confirmation なしで manual override を上書きする必要がある。
