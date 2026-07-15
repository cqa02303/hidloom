# Boot Service Helpers Detailed Spec

ここでは daemon 本体ではないが、起動順、復旧性、boot time、touch panel profile に影響する one-shot / timer service を扱います。

対象:

- `hidloom-usb-gadget.service`
- `hidloom-bluetooth-unblock.service`
- `hidloom-late-services.service`
- `hidloom-network-late.service`
- `hidloom-power-shed.service`
- `hidloom-touch-panel-profile.service`
- `ledd-shutdown.service`

## 役割

- USB gadget を早期に用意する。
- boot-critical input path を network / UI / Bluetooth より先に成立させる。
- network / Bluetooth / UI を late service として遅延起動する。
- PC USB 給電時の起動ピークを緩和する。
- touch panel profile を `logicd` / `httpd` / `viald` より前に選ぶ。
- shutdown 時に LED を安全表示へ戻す。

## 非役割

- keymap / HID report / matrix scan の処理は行わない。
- daemon の runtime protocol owner にはならない。
- recovery 不能な永続設定変更を silent に行わない。

## 起動順序で守る条件

- `hidloom-usb-gadget.service` は `DefaultDependencies=no`、`WantedBy=sysinit.target` を維持し、USB HID endpoint を早く出す。
- `logicd-core-rs` は `hidloom-outputd` の後、`matrixd` の前に起動する。
- `matrixd` は `logicd-core-rs` を `Requires=` する。
- `logicd-companion` は matrix socket owner にならず、`LOGICD_MATRIX_SOCKET=none` とする。
- `logicd-companion` の direct HID fan-out は通常 disabled にし、native outputd ctrl へ寄せる。
- `httpd` は `logicd-companion` の後に起動する。
- `viald` は USB gadget と touch panel profile の後に起動する。
- `late-services` は `ledd` を起動しない。`ledd` は早期起動済みとして扱う。
- `late-services` は `viald` / `httpd` / optional Bluetooth を `--no-block` で起動し、boot-critical path を待たせない。
- `network-late` は NetworkManager を timer 経由で遅延起動し、Wi-Fi recovery は残す。

## Power / Boot Guard

- `hidloom-power-shed.service` は `logicd.service` / `usbd.service` に依存しない。
- CPU max / governor の調整は boot peak 緩和であり、入力機能の owner ではない。
- audio / camera / display / splash / network wait の削減は fresh install の再現性テストと合わせて扱う。
- Wi-Fi persistent off は recovery path が検証されるまで通常実装にしない。

## Touch Panel Profile Guard

- `hidloom-touch-panel-profile.service` は `logicd` / `httpd` / `viald` より前に runtime keymap / layout を配置する。
- `/mnt/p3/keymap.json` は repo default より優先されるため、touch panel profile 選択時は runtime file owner を明示する。
- kiosk repair / Chromium remote debugging は loopback に限定し、LAN 公開しない。

## テスト観点

- `script/test_power_shed_boot.py`
  - boot-critical service ordering。
  - native hot path の service dependency。
  - late service / network timer。
  - native tools build and install path。
- `script/test_install_account_portability.py`
  - fresh install で service path が account 非依存に展開される。
- `script/test_touch_panel_profile.py`
  - touch panel profile selector と runtime keymap / layout。
- 実機 smoke
  - cold boot 後に USB keyboard endpoint が先に見える。
  - late services が遅れても key input path が成立する。
  - touch panel profile 選択後に HTTP layout と Vial layout がずれない。

## 既知の課題

- boot time 改善は service ordering だけでなく host enumeration timing も見る。
- helper service は成功しても、実際の endpoint / status JSON ができているかを別途確認する。
