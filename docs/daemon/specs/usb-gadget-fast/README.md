# usb-gadget-fast Detailed Spec

`hidloom_usb_gadget_fast` は USB gadget setup の native fast path です。shell fallback と同じ descriptor / endpoint contract を維持しながら、boot early path を短くすることを目的にします。

## 役割

- configfs USB gadget を native helper で構築する。
- keyboard / mouse / consumer / Raw HID / US-sub keyboard の既存 descriptor 構成を維持する。
- `hidloom-usb-gadget.service` から setup backend として使われる。

## 非役割

- HID report の送出は `hidloom-hidd` / `hidloom-outputd` の責務。
- keymap / logic は扱わない。
- host OS の keyboard layout 判定を変更しない。

## 所有するリソース

- 実装: `tools/hidloom_usb_gadget_fast/`
- systemd: `system/systemd/hidloom-usb-gadget.service`
- fallback: `setup_usb_gadget.sh`

## 実装時に守る条件

- default descriptor profile を shell fallback と一致させる。
- VID/PID、manufacturer、product、Vial serialの明示環境overrideをshell fallbackと一致させる。
- `/dev/hidg0`、`/dev/hidg1`、`/dev/hidg2` の意味を変えない。
- Vial Raw HID の report length を変えない。
- optional custom HID / Windows IME diagnostic interface は default で追加しない。
- setup 失敗時は既存 gadget を壊す前に検出できる probe / fallback を優先する。
- `ExecStop` で UDC detach できることを維持する。

## テスト観点

- `script/test_usb_gadget_fast_helper.py`
  - descriptor constants。
  - configfs write order。
  - shell fallback との互換。
- `script/test_usb_gadget_descriptor.py`
  - descriptor / report length。
- 実機 smoke
  - `/dev/hidg0` / `/dev/hidg1` / `/dev/hidg2` が期待通り作られる。
  - Linux / Windows host で keyboard / mouse / consumer / Vial Raw HID が見える。
  - hidd restart 後に endpoint open が復帰する。

## 既知の課題

- Windows device identity / keyboard layout は descriptor だけでは解決しない。Windows IME route は別仕様で扱う。
