# btd Socket Protocol

作成日: 2026-05-19
更新日: 2026-05-22

`logicd` と `btd` の間で HID report と制御メッセージを受け渡すための socket protocol
です。

iPhone 実機では BLE HOGP keyboard / mouse として pairing / bonding / trust / connect され、
`logicd -> btd -> BLE HID -> iOS` の keyboard 入力、mouse 移動、output 切替まで確認済みです。
Consumer Control は socket protocol / runtime 経路を実装済みです。BLE GATT への公開は
既存bond済みhostのHID descriptor cacheを壊さないよう既定OFFにし、`BTD_CONSUMER_CONTROL=1`
の opt-in で確認します。

## 目的

現在の構成:

```text
logicd OutputRouter
  ↓ keyboard / mouse / consumer HID report
BtdReportSender
  ↓ Unix socket /tmp/btd_events.sock
btd
  ↓ BlueZ BLE HID over GATT backend
Bluetooth host
```

`btd` は Bluetooth 接続管理と HID 送信に集中し、`logicd` は key state / layer / macro /
HID report 生成に集中します。

## 現在の protocol

現行の標準 protocol は `btd1` magic 付き binary frame です。

```text
[magic:4][type:1][len:1][payload:len]
```

`magic` は ASCII bytes の `btd1` です。

| type | payload | 用途 |
|---|---|---|
| `0x01` | 8 bytes | Keyboard HID report |
| `0x02` | 4 bytes | Mouse HID report |
| `0x03` | JSON bytes | Control message |
| `0x04` | 2 bytes | Consumer Control HID report |

### keyboard report

Keyboard payload は USB keyboard HID report と同じ固定 8 bytes です。

```text
[modifier][reserved][key1][key2][key3][key4][key5][key6]
```

例:

null report:

```text
00 00 00 00 00 00 00 00
```

`KC_A` press:

```text
00 00 04 00 00 00 00 00
```

framed `KC_A` press:

```text
62 74 64 31 01 08 00 00 04 00 00 00 00 00
```

### mouse report

Mouse payload は固定 4 bytes です。

```text
[buttons][x][y][wheel]
```

null mouse report:

```text
00 00 00 00
```

framed mouse report:

```text
62 74 64 31 02 04 00 01 ff 00
```

### consumer control report

Consumer Control payload は USB consumer HID report と同じ little-endian 2 bytes です。
press は usage ID、release は `0x0000` を送ります。

```text
[usage_lo][usage_hi]
```

例:

Volume Up press:

```text
e9 00
```

framed Volume Up press:

```text
62 74 64 31 04 02 e9 00
```

### control frame

Control payload は UTF-8 JSON object です。現時点の用途は reconnect advertisement の
一時制御です。

```json
{"command":"reconnect_advertising","enabled":true}
```

Control frame は HID report ではなく、`btd` runtime state を動かす補助メッセージです。

## legacy raw keyboard compatibility

`btd` は互換性のため、magic の無い raw 8-byte keyboard report も受け付けます。

```text
00 00 04 00 00 00 00 00
```

新規コードは framed protocol を使います。legacy raw は古い手動送信ツールや切替途中の
安全弁として残します。

## BLE HID over GATT 方針

Bluetooth HID transport は **BLE HID over GATT** のみを提供します。

`btd` の BlueZ backend は keyboard / mouse の Input Report を GATT characteristic へ写像します。
Consumer Control Input Report は `BTD_CONSUMER_CONTROL=1` の時だけ GATT Report Map に追加します。

実装済みの GATT 要素:

- HID Service `0x1812`
- HID Information
- Report Map
- Protocol Mode
- HID Control Point
- Keyboard Input Report
- Keyboard Output Report
- Boot Keyboard Input Report
- Boot Keyboard Output Report
- Mouse Input Report
- Consumer Control Input Report (`BTD_CONSUMER_CONTROL=1` の opt-in)
- Report Reference descriptor
- Client Characteristic Configuration descriptor
- Device Information Service
- Battery Service

## logicd 側の現状

`logicd` は `OutputRouter` の `bt` backend 経由で btd へ送ります。

`auto` は通常 `gadget` / `uinput` を優先し、USB 未接続時など必要な時だけ BT を選びます。
Bluetooth だけに限定する場合は `KC_BT` または `LOGICD_OUTPUTS=bt` を使います。

```bash
LOGICD_OUTPUTS=bt,debug PYTHONPATH=daemon python3 -m logicd.logicd
```

接続先 socket は既定で `/tmp/btd_events.sock`。開発時は `BTD_EVENTS_SOCK` で上書きできます。

```bash
BTD_EVENTS_SOCK=/tmp/test_btd.sock LOGICD_OUTPUTS=bt,debug PYTHONPATH=daemon python3 -m logicd.logicd
```

`btd` が停止中、または socket が存在しない場合、`BtdReportSender` は report を drop します。
`gadget` / `uinput` / `debug` など他 backend への出力は止めません。

## all input release policy

Bluetooth 接続断、`btd` 再起動、host disconnect、output target 切替時は、可能であれば
null keyboard report、null mouse report、null consumer report を送ります。

```text
keyboard: 00 00 00 00 00 00 00 00
mouse:    00 00 00 00
consumer: 00 00
```

目的:

- modifier stuck 防止
- Ctrl/Shift 押しっぱなし防止
- mouse button stuck 防止
- media key stuck 防止
- host 側に古い移動・ボタン状態を残さない

責務分担:

- `logicd` は key / pointer state の source of truth として通常の release report を生成する
- `btd` は stop / disconnect 時、送信可能なら null report を最後に送る
- 送れない場合でも `btd` / `logicd` を落とさない

## 実装状況

完了:

1. legacy raw 8-byte keyboard report 受信
2. framed keyboard report `0x01`
3. framed mouse report `0x02`
4. JSON control frame `0x03`
5. framed Consumer Control report `0x04`
6. `logicd` の `bt` backend から btd socket への keyboard / mouse / consumer 送信
7. BlueZ backend への keyboard / mouse / consumer interface
8. BLE HID GATT service registration
9. 接続中 host への keyboard / mouse report notify
10. disconnect/restart 時の null report

残タスク:

- iPhone 側 Bluetooth off/on 時の stuck key 最終目視確認
- iPhone Bluetooth off/on でも stuck reconnect 自動復旧が効くかの追確認
- 複数 host / bond policy の整理
- Consumer Control GATT opt-in の iOS / Windows / macOS / Linux / Android 互換性確認は、実装前設計TODOへ昇格済み
- Windows / macOS / Linux / Android での互換性確認
- pairing 状態と passkey 入力状態の表示を最終調整

## Consumer Control

```text
[magic:4][type=0x04][len=2][usage_lo][usage_hi]
```

payload は 2-byte usage 固定です。press は該当 usage ID、release は `0x0000` です。
GATT Report Map では、`BTD_CONSUMER_CONTROL=1` の時だけ Report ID 3 の
Consumer Control Input Report として公開します。既定では既存bond済みhostの
keyboard / mouse descriptor を維持します。
HTTP / Vial / key action の media key は既存の Consumer Control usage をそのまま使います。

## テスト

主な test:

```bash
python3 script/test_btd_suite.py
python3 script/test_btd_protocol.py
python3 script/test_btd_bluez_backend.py
python3 script/test_btd_backend_selection.py
python3 script/test_btd_gatt_adapter.py
python3 script/test_btd_gatt_app.py
python3 script/test_btd_gatt_hid.py
python3 -m unittest tests.test_btd_sender
python3 -m unittest tests.test_output_router
```

手動送信:

```bash
python3 script/send_btd_report.py
python3 script/send_btd_report.py 0000040000000000
```

logicd から btd logging backend への手動確認:

```bash
PYTHONPATH=daemon python3 -m btd.btd --backend logging
LOGICD_OUTPUTS=bt,debug PYTHONPATH=daemon python3 -m logicd.logicd
```

## 未決定事項

- Consumer Control GATT opt-in の host OS 互換性確認は、実装前設計TODOへ昇格済み
- reconnect 時の host 選択方法
- 複数 paired host がある場合の優先順位
- output backend 状態の HTTP / OLED / LED 表示の最終仕様
