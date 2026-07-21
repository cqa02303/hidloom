# BLE GATT HID Specification

更新日: 2026-07-15

Bluetooth HID backend は BLE HID over GATT を実装済みのtransportとして使用します。
この文書は、btd 側で公開する GATT service / characteristic と、logicd から渡す
keyboard / mouse / Consumer Control report の境界を定義します。

## 前提

`logicd -> btd` の socket protocol は `btd1` framed protocol を標準にし、
legacy raw 8-byte keyboard report は互換用に受け付ける。

Device Information ServiceのPnP IDはUSB identity profileと同じ
`HIDLOOM_USB_VENDOR_ID` / `HIDLOOM_USB_PRODUCT_ID`から生成します。
pid.codes割当前はdevelopment profileだけを使用します。PID待ちは`stable-public` binary公開だけを停止し、
`source-public`同期と`internal-rc`検証は継続します。
Raspberry Pi OSでは`/etc/hidloom/usb-identity.env`を`btd.service`と
`hidloom-usb-gadget.service`が共有し、片側だけのidentity変更を防ぎます。

```text
logicd OutputRouter
  ↓ framed keyboard / mouse / consumer HID report
BtdReportSender
  ↓ /tmp/btd_events.sock
btd
  ↓ KeyboardReport
BlueZBackend
  ↓ BLE HID Input Report characteristic
host
```

keyboard payload:

```text
[modifier][reserved][key1][key2][key3][key4][key5][key6]
```

現時点の frame:

```text
[magic=btd1][type][len][payload]
```

`type=0x01` は keyboard、`type=0x02` は mouse、`type=0x03` は JSON control、
`type=0x04` は Consumer Control。

## 対象 report

- Keyboard: 対応する
- Mouse: 対応する
- Consumer Control: socket / runtime は対応済み。GATT公開は `BTD_CONSUMER_CONTROL=1` の opt-in
- Feature report: 後回し
- Output report: NumLock / CapsLock 等の LED output report に対応する

## HID over GATT で必要になるもの

### GAP / advertising

目的:

- host から Bluetooth keyboard として見えるようにする
- pairing / reconnect の入口にする

検討項目:

- device name
- appearance: keyboard 相当
- discoverable / pairable state
- bonded host の扱い

2026-05-21:

- `btd.advertising.BlueZDbusAdvertisingAdapter` に BlueZ
  `LEAdvertisingManager1.RegisterAdvertisement` 実行 path を追加。
- advertisement は `Type=peripheral`, HID service UUID, keyboard appearance
  (`0x03c1`), local name を公開する。
- 実機で advertisement 登録が成功し、登録中は `ActiveInstances=1`、終了後は
  `ActiveInstances=0` に戻ることを確認。
- `BTD_PAIRING_MODE=1` / `BTD_PAIRING_ADAPTER=bluetoothctl` で、btd 起動中だけ
  `Pairable=yes` + BLE HID advertisement になり、adapter `Discoverable` は既定で
  `no` のまま維持することを確認。

### HID Service

HID over GATT 用の service を登録する。

必要になる characteristic 候補:

- HID Information
- HID Report Map
- HID Control Point
- Protocol Mode
- Input Report: Keyboard
- Input Report: Mouse
- Input Report: Consumer Control
- Output Report: Keyboard LEDs
- Boot Keyboard Input Report
- Boot Keyboard Output Report
- Report Reference descriptor
- Client Characteristic Configuration descriptor

Input Report と Output Report は同じ Report ID 1 を使い、Report Reference descriptor の
type (`input` / `output`) で区別する。
Mouse Input Report は Report ID 2、Consumer Control Input Report は opt-in 時に Report ID 3 を使う。

### Report Map

Keyboard report は現行 USB keyboard report と同じ 8-byte 形式を維持する。

```text
modifier: 1 byte
reserved: 1 byte
keys: 6 bytes
LED output: 1 byte
```

この report map は `logicd.hid_report.HidState.build()` の出力と一致させる。
GATT Input Report の `Value` は Report ID を前置しない8-byte keyboard payload のままにする。
Mouse は4-byte payload、Consumer Control は2-byte little-endian usage payload のままにする。

Keyboard の 6-key array は 8-bit の Keyboard/Keypad usage をそのまま送るため、
Report Map の logical maximum / usage maximum は `0xFF` として宣言する。
`0x65` までに絞る boot keyboard descriptor では、`KC_HENKAN` / `KC_MUHENKAN`
に相当する International4/5 (`0x8A` / `0x8B`) や、`KC_LANG1` / `KC_LANG2`
に相当する LANG1/2 (`0x90` / `0x91`) を host が無視する可能性がある。
USB gadget の keyboard report descriptor も同じく `0x00`-`0xFF` を許可する。

## btd 内部責務

`BlueZBackend` に閉じ込める責務:

- BlueZ / D-Bus との接続
- GATT application 登録
- HID service / characteristic 登録
- advertising 開始 / 停止
- host connection state の追跡
- keyboard / mouse / Consumer Control report characteristic の notify
- stop / disconnect 時の null report 送信

`BtdServer` と `btd.protocol` は、framed keyboard / mouse / consumer / control を受ける境界とし、
raw 8-byte keyboard report は互換用に維持する。

## all-key-release

null report:

```text
00 00 00 00 00 00 00 00
```

送信候補:

- btd stop 時
- host disconnect 検知時
- backend disable 時
- logicd から null report を受けた時

原則:

- logicd は key state の source of truth
- btd は最後に送信可能なら null report を送る
- 送れなくても btd / logicd を落とさない

## 実装順

### Step 1: BlueZ / D-Bus backend

- BlueZ system bus に接続する
- 失敗しても btd が落ちない
- `BlueZBackend.status()` に service / host state を反映する

### Step 2: GATT application 登録

- service 登録だけを行う
- characteristic は read / notify に対応する
- keyboard report は Step 3 で notify する

2026-05-21:

- `btd.gatt_adapter.BlueZDbusGattRegistrationAdapter` に opt-in の BlueZ D-Bus 登録 path を追加。
- `dbus-next` がある環境では `org.bluez.GattManager1.RegisterApplication` を呼び、`ObjectManager` / `GattService1` / `GattCharacteristic1` / `GattDescriptor1` を export する。
- `dbus-next` がない環境では backend を無効化し、`btd` daemon と socket 受付は継続する。
- 実機 `<keyboard-host>` に `python3-dbus-next` を導入し、`GattManager1.RegisterApplication`
  が成功することを確認。

### Step 3: Keyboard Input Report notify

- btd が受けた `KeyboardReport.report` を characteristic value として notify する
- logging backend と同じ report が送られることを確認する

2026-05-21:

- notify-capable keyboard Input Report characteristic の `Value` 更新を追加。
- `0000040000000000` が keyboard Input Report characteristic notify 処理まで届くことを確認。
- `StartNotify` / `StopNotify` をログ化し、`BlueZBackend.status().host_connected` が
  keyboard Input Report の notify 購読状態を反映できるようにした。
- Report ID 1 の keyboard report として、`logicd -> btd` の8byte payload と
  GATT Input Report characteristic `Value` を一致させた。
- `BTD_PAIRING_AGENT` / `--pairing-agent` を追加し、host 相性確認時に
  bluetoothctl agent capability を選べるようにした。
- Device Information Service (manufacturer / model / PnP ID) と Battery Service
  (Battery Level) を追加し、BLE HID peripheral として host に見せる情報を増やした。

2026-05-22:

- iOS が HOGP keyboard として受理するよう、Keyboard LED Output Report characteristic
  と Boot Keyboard Output Report characteristic を追加した。
- iPhone で `Paired=yes` / `Bonded=yes` / `Trusted=yes` / `Connected=yes` を確認。
- iOS から Keyboard Output Report へ `WriteValue value=0100` が来ることを確認。
- `WriteValue` を `logicd` の `HOST_LED` ctrl message へ渡す実装前設計は
  [host-led-output-report-design.md](host-led-output-report-design.md) に分離した。
- `script/send_btd_report.py` で Windows/Command key tap と `Cmd-H` を送り、
  iOS 側で HOME 相当の反応を確認。
- `LOGICD_OUTPUTS=bt` / fan-out 設定で、物理キー入力から
  `logicd -> btd -> BLE HID -> iPhone` の通常経路に keyboard Input Report が
  流れることを確認。
- `BTD_GATT_TRACE=1` の時だけ GATT Read/Write/Notify value を INFO に出し、
  通常運用では DEBUG に抑制するようにした。

### Step 4: Pairing / reconnect

- power / pairable / discoverable と GATT registration の関係を整理する
- bonded host への reconnect を確認する

2026-05-22:

- 常用設定は `BTD_PAIRING_MODE=0` のまま、HTTP `POST /api/bluetooth/pairing`
  と key action `BT_PAIRING_ON/OFF` で必要時だけ `Pairable` / `Discoverable` を開く。
- iOS 実機では `DisplayYesNo` agent で数字入力なしの再接続が成立した。
- ペアリング窓を閉じた後も `Discoverable=no` / `Pairable=no` のまま
  `Paired=yes` / `Bonded=yes` / `Trusted=yes` / `Connected=yes` を維持できることを確認。
- `tools/bt_reconnect_watch.py` を追加し、常用 btd service を起動し直さずに
  `bluetoothctl info`、HTTP `/api/status`、btd reset marker を並べて観測できるようにした。
- `BtPasskeyInput` は数字 / Enter / Backspace / Esc だけを消費する。
  数字入力が不要な iOS 再接続では、ペアリング窓中でも通常キー入力を通す。

### Step 5: stuck prevention

- disconnect / stop / restart で null report を送れるか確認する
- 送れない場合の log と fail-safe を整理する

2026-05-22:

- `btd` stop/restart 時は BlueZ backend stop path で null report を送る。
- `logicd` stop/restart 時は現在の OutputRouter writer 経由で null report を送る。
- BLE Input Report の `StopNotify` で GATT characteristic 内部値を null report に戻す。
- BlueZ が `StopNotify` を呼ばずに host link が落ちる場合があるため、
  `BTD_DISCONNECT_MONITOR_INTERVAL` を追加し、connected device が 0 になった時点でも
  Keyboard Input Report / Boot Keyboard Input Report の内部値を null report に戻す。
- host が `StartNotify` した時点でも keyboard input value を null report へ初期化する。
- 実機で A press 中に Pi 側 `bluetoothctl disconnect` を行い、
  `BlueZ GATT keyboard input reset to null report characteristics=2` を確認。
  iPhone は bonded/trusted のまま再接続できた。

### Step 6: Consumer Control Input Report

2026-05-22:

- `logicd -> btd` framed protocol に `type=0x04` / 2-byte Consumer Control report を追加。
- `logicd` の media key / Consumer Control action は、output mode が `bt` の時に
  `BtdReportSender` から btd へ送る。
- GATT Report Map は既定では keyboard / mouse のまま維持し、`BTD_CONSUMER_CONTROL=1` の
  opt-in 時だけ Report ID 3 の Consumer Control Input Report を追加する。
- BlueZ backend / dry-run backend / GATT adapter で consumer notify と null reset を実装。
- 実機互換性確認は未実施。iOS / Windows / macOS / Linux / Android で opt-in 時の
  descriptor cache と media key の反応を確認する。

## 実機確認

最初の対象 host は、実機で確認しやすいものから選ぶ。

候補:

- Linux PC
- Windows PC
- Android
- iPadOS
- macOS

確認項目:

- pairing できる
- keyboard として認識される
- A key が入力される
- Shift + A が入力される
- release で押しっぱなしにならない
- reconnect できる
- btd restart 後に復旧できる

## 未決定事項

- BlueZ D-Bus 実装に使う Python library / 方式: `dbus-next`
- GATT application object path / service path 命名: `/org/hidloom/btd`
- advertising object の持ち方: `/org/hidloom/btd/advertisement0000`
- host ごとの pairing agent capability は `DisplayYesNo` を iOS 実機で確認済み。
  他 host は必要に応じて比較する
- Consumer Control GATT opt-in の iOS / Windows / macOS / Linux / Android 互換性確認
