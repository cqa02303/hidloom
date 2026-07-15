# btd Detailed Spec

`btd` は Bluetooth HID / GATT / pairing を扱う daemon です。host profile、pairing state、USB route との切替で stuck key や誤 route が起きないようにします。

## 役割

- BLE advertising、pairing、GATT HID service を提供する。
- `hidloom-outputd` の `bt` target から受け取った Bluetooth 向け `btd1` frame を host へ届ける。
- host connection / pairing state を diagnostic 可能にする。

## 非役割

- keymap / layer / macro 解決は `logicd` の責務。
- USB HID report 送出は `hidd` / `usbd` の責務。

## 所有するリソース

- 実装: `daemon/btd/`
- socket protocol: [socket-protocol.md](socket-protocol.md)
- 関連 docs: [../../../bluetooth/README.md](../../../bluetooth/README.md)
- 入力: report send request、pairing / control request
- 出力: BLE GATT HID report、connection status

## 実装時に守る条件

- disconnected host へ report を成功扱いで送らない。
- pairing / forget / rename の state 変更を host profile と整合させる。
- USB route との切替時に release / clear を失わない。
- `hidloom-outputd` から届く keyboard / US-sub keyboard / mouse / consumer frame の種別を混同しない。
- BlueZ / DBus error を daemon crash に直結させない。
- active host は paired list だけで決めない。`hid_notify_ready` / `report_delivered` / `unknown` など source を明示する。
- btd restart、unpair、per-host forget 後は active host を `unknown` に戻す。
- per-host forget は dry-run / normalized address / resolved BlueZ object path を確認してから実行する。
- connected host の forget は既定で禁止または強い warning にする。

## テスト観点

- advertising start / stop。
- pair / reconnect / forget。
- report send while disconnected。
- USB route との切替。
- active host source and stale metadata。
- `hidloom-outputd` `bt` target からの `btd1` frame。

## 関連文書

- [socket-protocol.md](socket-protocol.md): `btd1` frame、legacy raw keyboard compatibility、control frame、consumer control frame。
- [../../../bluetooth/ble-gatt-hid-spec.md](../../../bluetooth/ble-gatt-hid-spec.md): BLE HID GATT / report map の仕様整理。
