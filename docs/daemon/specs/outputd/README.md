# outputd / hidloom-outputd Detailed Spec

`hidloom-outputd` は native hot path の output router です。現行の boot-critical path は `matrixd -> logicd-core-rs -> hidloom-outputd -> hidloom-hidd` で、`hidloom-outputd` が `usb` / `uinput` / `bt` / `auto` target を保持します。

## 役割

- `logicd-core-rs` 由来の broker frame を受け取り、現在 target に応じて配送する。
- `usb` target では `hidloom-hidd` の `/tmp/usbd_hid_reports.sock` へ転送する。
- `uinput` target では `hidloom-uidd` の `/tmp/uidd_reports.sock` へ転送する。
- `bt` target では broker frame を `btd1` keyboard / mouse / consumer frame へ変換し、`btd` へ送る。
- `logicd-companion` からの `KC_USB` / `KC_CONSOLE` / `KC_BT` / `KC_CONNAUTO` control を受け、target を切り替える。
- status JSON で target、counter、forward error を診断可能にする。

## 非役割

- keymap / layer / macro / press-release 解決は `logicd-core-rs` または `logicd` の責務。
- USB endpoint open / descriptor / report write は `hidloom-hidd` の責務。
- `/dev/uinput` device 作成と EV_KEY 差分変換は `hidloom-uidd` の責務。
- BLE GATT / host pairing / advertising は `btd` の責務。

## 所有するリソース

- 実装: `tools/hidloom_outputd/`
- systemd: `system/systemd/hidloom-outputd.service`
- report socket: `/tmp/hidloom_output_reports.sock`
- control socket: `/tmp/hidloom_output_ctrl.sock`
- USB destination: `/tmp/usbd_hid_reports.sock`
- uinput destination: `/tmp/uidd_reports.sock`
- Bluetooth destination: `/tmp/btd_events.sock`
- status: `/run/hidloom/outputd-status.json`

## 起動順序

- `hidloom-outputd` は `hidloom-hidd` と `hidloom-uidd` の後に起動し、両方を `Wants=` する。
- `logicd-core-rs` は `hidloom-outputd` の後に起動し、core から outputd へ report を送る。
- `matrixd` は `logicd-core-rs` の後に起動する。
- `btd` は late service 側で起動するため、`bt` target は destination unavailable を診断可能にする。

## Output Target Semantics

| target | 挙動 |
|---|---|
| `usb` | broker frame を `hidloom-hidd` へ送る |
| `uinput` | broker frame を `hidloom-uidd` へ送る |
| `bt` | broker frame を `btd1` frame へ変換して `btd` へ送る |
| `auto` | USB ready なら `usb`、そうでなければ `uinput` を選ぶ。Bluetooth fallback は暗黙に含めない |

## 実装時に守る条件

- target 切替前後で stuck key を残さない。旧 target と新 target の両方へ release-all / null report 相当を送る。
- `KC_BT` は companion 内の旧 Python `OutputRouter` だけを切り替える状態へ戻さない。native hot path の target 変更として `hidloom-outputd` control socket へ届くことを確認する。
- target unavailable を silent success にしない。status / counter / warning で観測可能にする。
- report 種別を混同しない。keyboard、US-sub keyboard、mouse、consumer を target ごとの形式へ正しく配送する。
- `bt` target では broker frame から `btd1` protocol への変換を壊さない。
- `auto` に Bluetooth fallback を暗黙追加しない。BT は明示 `KC_BT` / `target=bt` の扱いに留める。
- control socket schema を変更する場合は `logicd-companion` と test を同じ変更で更新する。

## 移植時に維持する互換性

- report frame は既存 compatible broker frame を受け取る。
- control request は JSON Lines の `set_output_target` / `status` / `release_all` を維持する。
- status schema `hidloom-outputd.status.v1` を壊さない。
- `/tmp/hidloom_output_reports.sock` と `/tmp/hidloom_output_ctrl.sock` の default path を変えない。

## テスト観点

- `script/test_hidloom_outputd_tool.py`
  - `usb` target が hidd socket だけへ転送する。
  - `uinput` target が uidd socket だけへ転送する。
  - `bt` target が `btd1` frame へ変換する。
  - target switch / release_all で release frame が出る。
  - status schema と counter が更新される。
- `script/test_native_outputd_ctrl.py`
  - companion の output switch が native outputd ctrl target へ変換される。
- 実機 smoke
  - `KC_USB` 後に host USB へ出る。
  - `KC_CONSOLE` 後に Pi local console へ出る。
  - `KC_BT` 後に BLE host へ出る。
  - held key 中の target switch で stuck key が残らない。

## 既知の課題

- BT target は local regression 済みだが、実機 BLE host smoke は次回同期後の確認項目。
- `auto` の USB readiness 判定と hidd status の関係は、host disconnect / reconnect で追加確認する。
