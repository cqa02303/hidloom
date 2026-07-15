# hidd / hidloom-hidd Detailed Spec

`hidd` / `hidloom-hidd` は boot-critical input path の HID endpoint を軽量に扱うための native component です。Python 起動時間に引きずられない入力経路を作る一方、USB host から見える HID report contract を壊さないことを最優先にします。

## 役割

- HID report を低遅延で host へ届ける。
- boot-critical keyboard path を Python daemon 起動前から利用可能にする。
- report descriptor、report ID、report length、send ordering の互換性を守る。
- 現行 native path では `hidloom-outputd` から USB target の report を受ける。

## 非役割

- keymap / layer / macro の解決は `logicd` または `logicd-core-rs` の責務。
- matrix scan は `matrixd` の責務。
- gadget descriptor の永続的な system 設定変更は setup helper / systemd unit の責務。

## 所有するリソース

- 実装: `tools/hidloom_hidd/`
- systemd: `system/systemd/hidloom-hidd.service`
- 関連仕様: [m0-implementation-spec.md](m0-implementation-spec.md)
- USB gadget / broker plan: [usb-gadget-multi-report-plan.md](usb-gadget-multi-report-plan.md)
- 入力: `/tmp/usbd_hid_reports.sock` の compatible broker frame
- 出力: HID gadget endpoint / uinput equivalent path
- 状態: connected endpoint、last report、clear report policy

## 起動順序

- gadget endpoint が未準備の場合は、失敗理由を明確に出し、再試行方針を持つ。
- `logicd` 未起動でも `hidd` 自体は起動できる。
- 起動直後、host に stuck key を見せないため clear report または zero state の方針を固定する。
- service restart 時、古い report を再送しない。
- `hidloom-outputd` より前に起動し、outputd から届く USB target frame を受ける。

## 入力

- report payload は report ID / length / type を検証する。
- 不正 payload は endpoint に流さず error として扱う。
- source が複数ある場合、owner を一意に決め、二重送出を避ける。
- Python legacy `usbd` broker path と `hidloom-outputd` path を同時 owner にしない。

## 出力

- descriptor と report body の整合を崩さない。
- short write / EPIPE / endpoint missing を区別してログに残す。
- host reconnect 後、必要な clear state を送れる。

## 関連文書

- [behavior-contract.md](behavior-contract.md)
- [compatibility-checklist.md](compatibility-checklist.md)
- [test-matrix.md](test-matrix.md)
- [../../../ops/hidloom-hidd-deep-test-plan.md](../../../ops/hidloom-hidd-deep-test-plan.md)
- [usb-gadget-multi-report-plan.md](usb-gadget-multi-report-plan.md)

## 既知の課題

- host 側観測は Linux 側だけでは不十分な場合がある。Windows / macOS host から見た enumeration、report timing、stuck key の観測を test-matrix に残す。
