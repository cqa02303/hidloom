# System control / programmable HID report design

作成日: 2026-06-01

この文書は System Control / Programmable HID Report 系の action を Raspberry Pi 実装で扱う前の設計です。
2026-06-01 時点では実装へは進まず、system power / sleep / wake、raw HID report、consumer control との境界、危険操作の confirmation、テスト範囲を固定します。

## Goal

- System Control と Consumer Control と Keyboard HID を混同しない。
- raw / programmable HID report を無制限に許可しない。
- power / sleep / wake など host に強い副作用がある action は明示 opt-in にする。
- Vial Raw HID / Matrix Test / LED direct-frame と programmable report を混ぜない。

## Candidate action families

| family | examples | 初期扱い |
| --- | --- | --- |
| System Control | `KC_SYSTEM_POWER`, `KC_SYSTEM_SLEEP`, `KC_SYSTEM_WAKE` | 設計候補。default disabled |
| Consumer Control | volume / media / brightness | Consumer Control GATT / HID design 側と連携 |
| Programmable report | `HID_REPORT(name)` | 初期は read-only design のみ |
| Raw HID command | Vial / Matrix / LED direct-frame | 既存 protocol owner を維持 |

## Owner boundary

- Keyboard report は `logicd` keyboard output owner。
- Consumer report は consumer control output owner。
- System Control report は separate report ID / backend support が必要。
- Raw HID / Vial packet bridge は `hidloom-hidd`、protocol 解釈は `viald` の owner。
- Programmable HID は arbitrary bytes ではなく named, validated report だけ候補。

## Safety policy

- default disabled。
- power / sleep / wake は Advanced / Dangerous group。
- programmable report は schema validation と allowlist 必須。
- HTTP から arbitrary byte report を直接送らない。
- output switch / reload / emergency release で pending report を破棄する。
- audit log に action / report name / result を残す候補。

## Storage candidate

```json
{
  "settings": {
    "hid_reports": {
      "safe_media_mode": {
        "enabled": false,
        "report_type": "system_control",
        "usage": "sleep",
        "confirm": true
      }
    }
  }
}
```

方針:

- named report だけを扱う。
- raw bytes は初期対象外。
- report type は enum。
- usage は allowlist。

## UI policy

- HTTP picker では System Control を basic HID と分ける。
- enable / send には warning。
- Vial import で system key が来ても basic key と混ぜない。
- OLED は `System sleep blocked` のような短い alert 候補。

## Static tests to add with implementation

設計 first slice では doc test だけを追加する。
実装へ進む場合は以下を追加する。

- default disabled。
- arbitrary byte report が validation を通らない。
- named report の report_type / usage allowlist。
- system control action が basic HID group に混ざらない。
- output switch / reload / emergency release で pending report clear。
- audit log が残る。

## Implementation gate

実装へ進める条件:

- System Control report descriptor / backend support が決まっている。
- named report allowlist がある。
- HTTP から raw bytes を送らない UI 境界がある。

実装しない条件:

- arbitrary HID report bytes をユーザー入力で送る必要がある。
- system power action を default 有効にする必要がある。
- Vial Raw HID protocol と programmable report を同じ owner にする必要がある。
