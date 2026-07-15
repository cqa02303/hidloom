# usbd Detailed Spec

`usbd` は USB / HID report broker 系の互換性を扱う daemon です。`hidd` / `uidd` と役割が重なる段階では、どの component が host-facing report を所有するかを明確にします。

## 役割

- HID report broker として、上位から受け取った report を USB 側へ届ける。
- report 種別、report ID、payload length の整合を維持する。
- USB route の状態を diagnostic 可能にする。

## 非役割

- key action の解決は `logicd` の責務。
- gadget descriptor の高速初期化は専用 helper / `hidd` 側仕様を優先する場合がある。

## 所有するリソース

- 実装: `daemon/usbd/`
- config: `daemon/usbd/usbd-hid-report-broker.conf`
- 入力: report broker channel
- 出力: USB HID path

## 実装時に守る条件

- report 種別を混同しない。
- USB route が未準備でも daemon 全体の異常終了に直結させない。
- `hidd` 併用時、同じ report を USB へ二重送出しない。
- host reconnect 後に stuck key を残さない。
- legacy broker flag は現行 native owner path と混ぜない。
- descriptor / Raw HID report length の変更は default で行わず、opt-in profile と host compatibility matrix を先に用意する。
- Windows IME custom HID / Raw HID multiplex は診断 route として扱い、標準 keyboard HID route の成功と混同しない。

## テスト観点

- report broker valid / invalid payload。
- USB route unavailable。
- hidd 併用時の owner 切替。
- Linux / Windows host enumeration。
- Vial Raw HID visibility and report length。
