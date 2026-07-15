# Bluetooth Implementation Plan

作成日: 2026-05-19
更新日: 2026-05-22

Raspberry Pi Zero 2 W を Bluetooth keyboard / mouse として使うための実装計画と、
現在の到達点です。

詳細な HID over GATT 構造は [ble-gatt-hid-spec.md](ble-gatt-hid-spec.md)、`logicd -> btd` の socket protocol は [../daemon/specs/btd/socket-protocol.md](../daemon/specs/btd/socket-protocol.md)、実機チェック項目は private workspace reference *(omitted from public export)* を参照してください。

## 現在の状態

BLE HID over GATT keyboard / mouse は実装済みです。

実機確認済み:

- iPhone が BLE HOGP keyboard として pairing / bonding / trust / connect する
- `logicd -> btd -> BLE HID -> iPhone` で keyboard report が届く
- `logicd -> btd -> BLE HID -> iPhone` で mouse report が届く
- iOS で Windows/Command tap と `Cmd-H` が HOME 相当動作になる
- `LOGICD_OUTPUTS=auto` の初期状態では、`gadget` -> `uinput` の順で利用可能な単一出力を選ぶ
- BT は `KC_BT` / `LOGICD_OUTPUTS=bt` / 明示 fan-out で使う。auto fallback に含める確認時のみ
  `LOGICD_AUTO_BT_FALLBACK=1` を指定する
- 明示的な fan-out は `LOGICD_OUTPUTS=gadget,bt` のように指定して行う
- 通常 `systemctl reboot` 後、daemon active / iPhone reconnect / GATT notify / HOME report が復帰する
- `BT_PAIRING_ON/OFF` と HTTP Pair on/off で `Discoverable` / `Pairable` が切り替わる
- iPhone connected/bonded/trusted を維持したまま pairing window を閉じられる

残り:

- iPhone 側 Bluetooth off/on 時の stuck-key 有無の最終目視確認
- iPhone Bluetooth off/on 後に stuck reconnect 自動復旧が効くかの追確認
- 複数 host / 複数 bond の運用方針
- Consumer Control の実機互換性確認

## 構成

```text
keymap / Vial / HTTP UI / physical matrix
  ↓
logicd input action dispatch
  ├─ BT_* control action -> BtManager -> bluetoothctl / BlueZ control
  └─ normal key action -> HID report
        ↓
      OutputRouter
        ├─ USB gadget
        ├─ uinput
        ├─ debug
        └─ bt
             ↓ btd1 framed keyboard / mouse / consumer report
           btd
             ↓ BlueZ D-Bus
           BLE HID over GATT
             ↓
           Bluetooth host
```

`BT_*` は Bluetooth control action です。`KC_BT` は output selector であり、Bluetooth power / pairing を直接変更しません。

## 実装済み BT action

| Action | 目的 |
|---|---|
| `BT_STATUS` | 現在の BT 状態を logicd log / OLED alert 経由で確認する |
| `BT_POWER_ON` | Bluetooth を on にする |
| `BT_POWER_OFF` | Bluetooth を off にする |
| `BT_POWER_TOGGLE` | Bluetooth 電源を toggle する |
| `BT_PAIRING_ON` | pairable / discoverable を on にする |
| `BT_PAIRING_OFF` | pairable / discoverable を off にする |
| `BT_PAIRING_TOGGLE` | ペアリングモードを toggle する |
| `BT_DISCONNECT` | 接続中デバイスを切断する |
| `BT_FORGET_DEVICE` | paired devices を remove する |

## 実装済みファイル

logicd:

- `daemon/logicd/bt_manager.py`
- `daemon/logicd/bt_passkey.py`
- `daemon/logicd/btd_sender.py`
- `daemon/logicd/input_events.py`
- `daemon/logicd/ctrl.py`
- `daemon/logicd/runtime_notifications.py`

btd:

- `daemon/btd/btd.py`
- `daemon/btd/bluez_backend.py`
- `daemon/btd/gatt_hid.py`
- `daemon/btd/gatt_app.py`
- `daemon/btd/gatt_adapter.py`
- `daemon/btd/advertising.py`
- `daemon/btd/pairing.py`
- `daemon/btd/protocol.py`

HTTP / UI:

- `daemon/http/bluetooth_api.py`
- `daemon/http/system_api.py`
- `daemon/http/static/status_panel.js`
- `daemon/http/static/index.html`

tools:

- `tools/btd_bluez_pairing_window.py`
- `tools/bt_reconnect_watch.py`
- `script/send_btd_report.py`

## 常用 systemd 設定

Fresh setup では `btd.service.d/hogp.conf` と `logicd.service.d/*` に以下を入れます。

```ini
[Service]
Environment=BTD_BACKEND=bluez
Environment=BTD_BLUEZ_ENABLE=1
Environment=BTD_GATT_ADAPTER=bluez-dbus
Environment=BTD_ADVERTISING_ADAPTER=bluez-dbus
Environment=BTD_ADVERTISING_MODE=pairing
Environment=BTD_ADVERTISING_MONITOR_INTERVAL=1
Environment=BTD_ADVERTISING_IDLE_MONITOR_INTERVAL=60
Environment=BTD_GATT_SECURITY=encrypt
Environment=BTD_PAIRING_MODE=0
Environment=BTD_PAIRING_ADAPTER=bluetoothctl
Environment=BTD_PAIRING_AGENT=DisplayYesNo
Environment=BTD_STATUS_INTERVAL=30
Environment=BTD_DISCONNECT_MONITOR_INTERVAL=2
Environment=BTD_DISCONNECT_IDLE_MONITOR_INTERVAL=60
Environment=BTD_STUCK_RECONNECT_POLLS=3
Environment=BTD_STUCK_RECONNECT_COOLDOWN=30
Environment=BTD_OUTPUT_ON_CONNECT=bt
Environment=BTD_OUTPUT_ON_DISCONNECT=auto
```

```ini
[Service]
Environment=LOGICD_OUTPUTS=auto
Environment=BTD_PAIRING_AGENT=DisplayYesNo
Environment=BTD_PAIRING_PASSKEY_FILE=/tmp/btd_pairing_passkey.txt
Environment=BT_PAIRING_DISCOVERABLE=0
```

初期状態では BT output へ fan-out しません。Bluetooth へ出力したい場合は `KC_BT` などで
明示的に output target を切り替えます。
`BT_PAIRING_ON` は既定で `Pairable=yes` と BLE HID advertisement だけを使い、
adapter 全体の `Discoverable` は `no` のままにします。iPhone で二重表示される場合を
避けるためです。旧挙動が必要な確認時だけ `BT_PAIRING_DISCOVERABLE=1` を指定します。
`BTD_OUTPUT_ON_CONNECT=bt` により、pairing/reconnect で host 接続を検出した時点で
logicd の output target を `bt` へ切り替えます。
`BTD_OUTPUT_ON_DISCONNECT=auto` により、全 host 切断後は output target を `auto` へ戻します。

通常 reboot で watchdog reset ループのように見える状態を避けるため、fresh setup は systemd hardware watchdog を無効化します。

```ini
[Manager]
RuntimeWatchdogSec=off
RebootWatchdogSec=off
KExecWatchdogSec=off
```

前回 boot の原因追跡用に journald は永続化します。

```ini
[Journal]
Storage=persistent
SystemMaxUse=64M
RuntimeMaxUse=32M
```

## 実機確認コマンド

状態:

```bash
systemctl status hidloom-logicd-core logicd-companion btd httpd bluetooth --no-pager
systemctl show -p RuntimeWatchdogUSec -p RebootWatchdogUSec -p KExecWatchdogUSec
bluetoothctl show
bluetoothctl info 14:35:B7:EF:AB:72
curl -k -u admin:$(hostname) https://127.0.0.1/api/status | jq .bluetooth
```

HOME 相当 report 送信:

```bash
python3 script/send_btd_report.py 08000b0000000000
sleep 0.12
python3 script/send_btd_report.py 0000000000000000
```

Pairing window:

```bash
curl -k -u admin:$(hostname) -X POST https://127.0.0.1/api/bluetooth/pairing \
  -H 'Content-Type: application/json' \
  -d '{"mode":"on"}'
```

```bash
curl -k -u admin:$(hostname) -X POST https://127.0.0.1/api/bluetooth/pairing \
  -H 'Content-Type: application/json' \
  -d '{"mode":"off"}'
```

Forget paired devices:

```bash
curl -k -u admin:$(hostname) -X POST https://127.0.0.1/api/bluetooth/forget
```

Reconnect watcher:

```bash
python3 tools/bt_reconnect_watch.py --mac 14:35:B7:EF:AB:72 --duration 60
```

## 注意点

- `BT_FORGET_DEVICE` と HTTP `Forget` は paired devices を消すので、誤爆しにくい場所に置く。
- `BT_POWER_OFF` は接続中の BT HID 出力も切る。
- `BT_PAIRING_ON` / `BT_PAIRING_TOGGLE` は pairable と BLE HID advertisement を開くため、必要時だけ使う。
- iOS は Classic HID ではなく BLE HID over GATT を要求する前提で扱う。
- `logicd -> btd` の socket protocol は `btd1` framed keyboard / mouse / consumer / control を標準にする。
- legacy raw 8-byte keyboard report は互換用に維持する。
- Consumer Control は `type=0x04` / 2-byte usage payload として実装済み。
  GATT Report ID 3 は `BTD_CONSUMER_CONTROL=1` の opt-in で公開し、残りは host OS ごとの
  descriptor cache と media key 互換性確認。
