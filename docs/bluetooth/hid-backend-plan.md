# Bluetooth HID Backend Plan

作成日: 2026-05-19
更新日: 2026-05-22

Raspberry Pi Zero 2 W を Bluetooth HID Keyboard / Mouse として出力先に追加するための
実装計画と経緯です。

現行の正は [../daemon/specs/btd/socket-protocol.md](../daemon/specs/btd/socket-protocol.md) と private workspace reference *(omitted from public export)*
です。この文書は計画メモも含むため、実装済みになった項目は「現在の状態」で上書きして
読んでください。

## 現在の状態

現在は BT control layer、`logicd -> btd` report sink、BlueZ D-Bus backend、BLE HID over
GATT keyboard / mouse service、HTTP pairing API、OLED/LED pairing indicator まで実装済みです。

iPhone 実機では BLE HOGP keyboard / mouse として pairing / bonding / trust / connect され、
`logicd -> btd -> BLE HID -> iOS` の入力到達と mouse 移動を確認済みです。iOS では
Windows/Command tap と `Cmd-H` が HOME として反応しました。

BT control layer:

```text
key action
  ↓
BtManager
  ↓
bluetoothctl / systemctl / rfkill
```

keyboard / mouse / consumer report path:

```text
logicd OutputRouter
  ↓ framed keyboard / mouse / consumer HID report
BtdReportSender
  ↓ Unix socket: /tmp/btd_events.sock
btd
  ↓
LoggingBackend or BlueZBackend
  ↓
BLE HID over GATT
  ↓
Bluetooth host
```

対応済み BT action:

- `BT_STATUS`
- `BT_POWER_ON`
- `BT_POWER_OFF`
- `BT_POWER_TOGGLE`
- `BT_PAIRING_ON`
- `BT_PAIRING_OFF`
- `BT_PAIRING_TOGGLE`
- `BT_DISCONNECT`
- `BT_FORGET_DEVICE`

btd 側の追加済み:

- `daemon/btd/btd.py`
- `daemon/btd/backend.py`
- `daemon/btd/bluez_backend.py`
- `daemon/btd/gatt_adapter.py`
- `daemon/btd/gatt_app.py`
- `daemon/btd/gatt_hid.py`
- `daemon/btd/advertising.py`
- `daemon/btd/pairing.py`
- `daemon/btd/protocol.py`
- `system/systemd/btd.service`
- `daemon/btd/README.md`
- `docs/daemon/specs/btd/socket-protocol.md`
- `script/send_btd_report.py`
- `script/test_btd_socket_boundary.py`
- `script/test_btd_protocol.py`
- `script/test_btd_backend.py`
- `script/test_btd_bluez_backend.py`
- `script/test_btd_backend_selection.py`
- `script/test_btd_gatt_adapter.py`
- `script/test_btd_gatt_app.py`
- `script/test_btd_gatt_hid.py`
- `tools/btd_bluez_pairing_window.py`
- `tools/bt_reconnect_watch.py`

logicd 側の追加済み:

- `daemon/logicd/output_router.py`
- `daemon/logicd/btd_sender.py`
- `daemon/logicd/bt_manager.py`
- `daemon/logicd/bt_passkey.py`
- `LOGICD_OUTPUTS=bt`
- `LOGICD_OUTPUTS=gadget,uinput,bt,debug` fan-out
- `LOGICD_OUTPUTS=auto` 初期構成と、`LOGICD_OUTPUTS=bt` / fan-out 実機構成
- `tests/test_btd_sender.py`
- `tests/test_output_router.py`

残タスク:

- iPhone Bluetooth off/on 時の stuck-key / stuck reconnect 追確認
- 複数 host / bond policy の整理
- Windows / macOS / Linux / Android での互換性確認
- Consumer Control report の host OS 互換性確認
- pairing 中、passkey 入力待機中、通常時の LED/OLED 表示の最終調整

## 方針

Bluetooth HID backend は `logicd` に直接内蔵しない。

推奨構成:

```text
logicd
  ↓ canonical HID reports
btd
  ↓ BlueZ / D-Bus / BLE HID over GATT
Bluetooth host
```

## BLE HID over GATT を既定にする

Bluetooth HID の主経路は **BLE HID over GATT** を既定にする。

理由:

- PC / tablet / phone など現代的な host を広く対象にしやすい
- GATT service / characteristic 単位で keyboard report の境界を設計しやすい
- 実装済みtransportを1経路に限定し、設定だけ存在する未提供機能を作らない
- btd の `BlueZHidTransport` は実装済みの `ble` だけを表す

`btd` socket protocol は現在 `btd1` framed keyboard / mouse / consumer / control を標準にし、
legacy raw 8-byte keyboard report は互換用に維持します。

## daemon 分離する理由

### 1. logicd の安定性を優先する

`logicd` は keyboard scan / keymap / USB HID 出力の中心なので、BlueZ の不安定さや pairing state の影響を受けにくくする。

### 2. Bluetooth は長寿命 state を持つ

BT HID には以下のような状態がある。

- adapter powered
- pairable / discoverable
- paired devices
- connected device
- HID service registration
- reconnect state
- host trust state

これらは `logicd` の key event loop とは別責務。

### 3. BlueZ adapter を差し替えやすくする

同じBLE HID modelに対して:

- BlueZ D-Bus backend
- dry-run adapter
- pairing / advertising adapter

を差し替えやすくする。

## btd daemon 構成

現在:

```text
daemon/btd/
  __init__.py
  btd.py
  backend.py
  bluez_backend.py
  gatt_adapter.py
  gatt_app.py
  gatt_hid.py
  advertising.py
  pairing.py
  protocol.py
  btd.service
  README.md
```

現在の役割:

- Unix socket で framed keyboard / mouse / consumer / control を受ける
- `KeyboardReport` / `MouseReport` として parse する
- backend interface へ渡す
- `LoggingBackend` で log する
- `BlueZBackend` で BLE HID over GATT service を公開する
- 接続中 host へ keyboard / mouse / consumer report を notify する
- pairing / reconnect / disconnect を補助する

今後拡張する役割:

- Consumer Control report の host OS 互換性確認
- 複数 host policy の管理
- host 別 reconnect 優先順位の管理

## logicd との接続方式

採用方式: HID report bytes を直接送る。

```text
logicd output processor
  ↓ keyboard / mouse HID report
OutputRouter
  ↓ bt backend
BtdReportSender
  ↓ /tmp/btd_events.sock
btd
```

理由:

- 既存の `HidState.build()` を再利用できる
- modifier stuck の責務を logicd に集約できる
- btd 側で key state を再構築しなくてよい
- btd は送信と接続管理に集中できる

現時点では keyboard / mouse / consumer report と reconnect advertising 用 control frame を扱う。

## OutputRouter との関係

`bt` は `gadget` / `uinput` / `debug` と同じ output backend として扱う。

例:

```bash
LOGICD_OUTPUTS=bt,debug PYTHONPATH=daemon python3 -m logicd.logicd
LOGICD_OUTPUTS=gadget,uinput,bt,debug PYTHONPATH=daemon python3 -m logicd.logicd
```

`btd` が落ちている場合、`BtdReportSender` は report を drop する。他 backend への出力は止めない。

## BlueZ backend 境界

`daemon/btd/bluez_backend.py` は BlueZ D-Bus backend として実装済みです。以下の責務を `BlueZBackend` 内に閉じ込めています。

```python
async def start() -> None
async def stop() -> None
async def send_keyboard_report(report: KeyboardReport) -> None
async def send_mouse_report(report: MouseReport) -> None
```

内部責務:

- Bluetooth adapter / service の準備
- BLE HID GATT service registration
- host 接続状態の管理
- keyboard / mouse / consumer report characteristic への送信
- stop / disconnect 時の null report 送信
- pairing window / advertising の補助
- disconnect monitor による stale keyboard report reset

外側の `btd.btd.BtdServer` と `btd.protocol` は transport-neutral な report 境界として扱う。

## Transport 境界

公開CLIと環境変数が受け付けるBluetooth HID transportは、実装済みのBLE HID over GATTだけです。
別transportを追加する場合は、report送信、pairing、reconnect、all-key-releaseを実装・検証してから設定面を追加します。

維持条件:

- 最小構成で keyboard report を送信できる
- 再起動後の復旧手順が明確
- btd が落ちても logicd を巻き込まない
- all-key-release を安全に送れる
- Windows / Linux / Android など主要 host で確認しやすい

## all-key-release 方針

キー押しっぱなし防止を優先する。

送信候補:

- btd stop 時
- host disconnect 検知時
- backend switch / disable 時
- logicd から null report を受けた時

原則:

- logicd は key state の source of truth
- btd は最後に送れるなら null report を送る
- 送れない場合でも btd / logicd を落とさない

## 実装フェーズ

### Phase 0: BT control layer

完了済み:

- BT control layer
- BT keycodes
- Vial custom keycode registration
- shared_action_defs への定義集約

### Phase 1: btd daemon boundary

完了済み:

- daemon boundary
- Unix socket boundary
- protocol helper
- backend interface
- logging backend
- BlueZ backend
- backend selection option
- BLE-only transport contract
- regression tests
- BLE HOGP backend

確認コマンド:

```bash
python3 script/test_btd_protocol.py
python3 script/test_btd_backend.py
python3 script/test_btd_bluez_backend.py
python3 script/test_btd_backend_selection.py
python3 script/test_btd_socket_boundary.py
python3 script/test_btd_gatt_adapter.py
python3 script/test_btd_gatt_app.py
python3 script/test_btd_gatt_hid.py
```

### Phase 2: 実機状態確認

確認:

```bash
systemctl status bluetooth --no-pager
rfkill list bluetooth
bluetoothctl show
bluetoothctl paired-devices
```

key action 確認:

- `BT_STATUS`
- `BT_POWER_TOGGLE`
- `BT_PAIRING_TOGGLE`
- `BT_DISCONNECT`

btd 確認:

```bash
PYTHONPATH=daemon python3 -m btd.btd --backend logging
python3 script/send_btd_report.py 0000040000000000
```

### Phase 3: logicd -> btd report sink

完了済み:

- `logicd.btd_sender.BtdReportSender`
- `LOGICD_OUTPUTS=bt`
- btd socket unavailable 時の drop policy
- `tests/test_btd_sender.py`

確認コマンド:

```bash
python3 -m unittest tests.test_btd_sender tests.test_output_router
```

実機での追加確認:

```bash
PYTHONPATH=daemon python3 -m btd.btd --backend logging
LOGICD_OUTPUTS=bt,debug PYTHONPATH=daemon python3 -m logicd.logicd
```

### Phase 4: BLE HID over GATT 調査実装

完了済み:

- `BlueZBackend` の BLE GATT service registration
- HID Information / Report Map / HID Control Point / Protocol Mode / Input Report characteristic
- Keyboard Output Report / Boot Keyboard Output Report
- Report Reference descriptor / CCCD
- Device Information / Battery Service
- 接続状態の log 出力
- keyboard report characteristic 送信 API
- iOS pairing / connect / HOME 入力確認
- mouse Input Report characteristic
- iOS mouse 移動確認

当初は keyboard report の送信確認を優先した。現在は mouse report も実装済みで、
Consumer Control は socket protocol / runtime 経路を実装済み。GATT公開は
`BTD_CONSUMER_CONTROL=1` の opt-in。

### Phase 5: HID keyboard report 送信

完了済み:

- keyboard / mouse / consumer report
- modifier / normal key の同時押し
- release report
- disconnect / stop 時の null report
- StartNotify / StopNotify 時の stale report reset
- BlueZ connected-device monitor による disconnect reset

### Phase 6: output selector / status 統合

実装済み:

- USB only
- BT only
- USB + BT mirror
- auto
- HTTP `/api/status` への output backend 状態表示
- HTTP `/api/bluetooth/pairing` による pairing on/off/toggle
- System UI の Pair on/off button

継続調整:

- reconnect 状態の UI 表示
- 複数 host がある場合の表示と操作

## 実機テスト項目

### Keyboard basics

- A-Z
- Enter / Esc / Backspace
- modifier
- Shift + number
- multiple key press
- key release

### Stuck prevention

- Ctrl 押下中に disconnect
- Shift 押下中に reconnect
- host sleep / wake
- daemon restart

### Pairing / reconnect

- initial pairing
- reboot後 reconnect: 継続確認
- host側BT off/on
- paired device remove

### OS別確認

- Windows
- macOS
- Linux
- Android
- iPadOS

## 注意点

- `BT_POWER_OFF` は BT HID output も落とすため、BT output 実装後は安全確認が必要。
- `BT_FORGET_DEVICE` は paired host を消すため、誤爆しにくい配置にする。
- 接続断時は必ず all key release を送る設計にする。
- btd が落ちても logicd は落ちないこと。
- packet size / framing を変える必要がある場合は、実装前に相談する。

## 次回実装の最初の一歩

1. Raspberry Pi reboot 後、iPhone が再接続して keyboard report を受けることを確認する。
2. iPhone 側 Bluetooth off/on 後の reconnect と stale key reset を確認する。
3. pairing / passkey / connected / disconnected の LED/OLED 表示を実使用に合わせて磨く。
4. Windows / macOS / Linux / Android の順に host 互換性を確認する。
