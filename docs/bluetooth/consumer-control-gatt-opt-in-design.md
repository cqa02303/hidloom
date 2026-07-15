# Consumer Control GATT opt-in design

作成日: 2026-06-01

この文書は BLE HID over GATT で Consumer Control Input Report を公開する前の opt-in 設計です。
2026-06-01 時点では実装へは進まず、既存 socket / runtime 経路と GATT 公開の境界、host 互換性確認、rollback 条件を固定します。

## 現在の前提

- `logicd -> btd` framed protocol では `type=0x04` を Consumer Control として扱う。
- Consumer Control report payload は 2-byte little-endian usage。
- `docs/daemon/specs/btd/socket-protocol.md` と `ble-gatt-hid-spec.md` では socket / runtime 側の Consumer Control は対応済み扱い。
- BLE GATT 側の Consumer Control Input Report は opt-in として扱う。
- Keyboard / Mouse BLE HID 経路は既存の常用 path を壊さない。

## Goal

- 既存の Keyboard / Mouse BLE HID を壊さず、Consumer Control を必要な環境だけで有効にする。
- host OS ごとの互換性差分を観測できるようにする。
- 既存 bond / pairing / reconnect への影響を切り分けられるようにする。
- 問題があれば `BTD_CONSUMER_CONTROL=0` で即座に戻せる。

## Opt-in flag

候補:

```text
BTD_CONSUMER_CONTROL=1
```

方針:

- default は `0`。
- `1` の時だけ Consumer Control Input Report characteristic と Report Map entry を公開する。
- runtime socket protocol は flag に関係なく Consumer Control frame を受けられるが、GATT 非公開時は BLE notify しない。
- status には `consumer_control_gatt_enabled` として出す候補。
- HTTP System panel には read-only で opt-in 状態を表示する候補。

## GATT shape candidate

- Report ID: `3`
- Report Type: Input
- Payload: 2-byte little-endian Consumer Usage ID
- Value: Report ID を前置しない 2-byte payload
- Notify: host が CCCD を StartNotify した時だけ送る

Report Map は Keyboard / Mouse と同じ HID Service の中に含める候補とする。
別 service にはしない。

## Owner / data flow

| layer | owner |
| --- | --- |
| key action / Consumer Control usage 生成 | `logicd` |
| framed socket transport | `logicd.btd_sender` / `btd.protocol` |
| GATT characteristic / report map / notify | `btd.bluez_backend` / `btd.gatt_hid` |
| opt-in flag | `btd` startup environment |
| status display | `btd.status` / HTTP System panel |

`httpd` は flag の表示だけを行い、Consumer Control GATT の直接 owner にはしない。

## Compatibility check matrix

実装前に確認対象を固定する。

| host | 確認項目 |
| --- | --- |
| iOS | keyboard pairing / reconnect が壊れない。volume / media key が反応するか。既存 bond への影響。 |
| macOS | keyboard / mouse / consumer の report map を受理するか。media key 反応。 |
| Windows | pairing / reconnect / device category / media key 反応。 |
| Linux BlueZ host | `btmon` / input event で Consumer Control が見えるか。 |
| Android | pairing / reconnect / media key 反応。 |

## Rollback policy

- `BTD_CONSUMER_CONTROL=0` で Consumer Control GATT を公開しない。
- opt-in を切った後も keyboard / mouse の Report ID は変えない。
- 既存 bond が壊れる場合は、default `0` のまま維持する。
- host が古い report map を cache する可能性があるため、test 手順では unpair / forget を含める。

## Status / UI policy

HTTP:

- System panel に read-only `Consumer Control GATT: on/off` を表示する候補。
- enable/disable button は初期実装では作らない。
- `.env` / systemd environment を変える操作は手動にする。

OLED:

- 常時表示はしない。
- pairing / debug 時だけ `CC GATT on` のような短い表示を出す候補。

Docs:

- `ble-gatt-hid-spec.md` からこの文書へリンクする。

## Safety / non-goals

- default 有効化しない。
- HTTP から btd environment を直接書き換えない。
- HTTP から systemd environment を直接書き換えない。
- Consumer Control を Keyboard report に混ぜない。
- Report ID 1 / 2 を変更しない。
- Keyboard / Mouse の reconnect を犠牲にしない。

## Static tests to add with implementation

設計 first slice では doc test だけを追加する。
実装へ進む場合は以下を追加する。

- default `BTD_CONSUMER_CONTROL=0`。
- `BTD_CONSUMER_CONTROL=1` の時だけ Consumer Control Report Map / characteristic が含まれる。
- flag off で Consumer Control frame を受けても GATT notify しない。
- keyboard / mouse report ID が変わらない。
- status に opt-in state が出る。
- btd restart 後の status が environment と一致する。

## Implementation gate

実装へ進める条件:

- Keyboard / Mouse BLE HID の安定性を維持できる。
- report map / characteristic の on/off を flag で切り替えられる。
- iOS / macOS / Windows / Linux / Android の最低限の確認手順がある。
- rollback が `BTD_CONSUMER_CONTROL=0` と unpair / re-pair 手順で説明できる。

実装しない条件:

- default 有効化が必要になる。
- Keyboard / Mouse Report ID を変えないと実装できない。
- host 側で既存 bond が頻繁に壊れる。
- HTTP から systemd environment を自動で書き換える必要がある。
