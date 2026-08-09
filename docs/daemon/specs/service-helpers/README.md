# Boot Service Helpers Detailed Spec

ここでは daemon 本体ではないが、起動順、復旧性、boot time、touch panel profile に影響する one-shot / timer service を扱います。

対象:

- `hidloom-usb-gadget.service`
- `hidloom-early-input-handoff-prepare.service`
- `hidloom-early-input-handoff-finalize.service`
- `hidloom-bluetooth-unblock.service`
- `hidloom-late-services.service`
- `hidloom-network-late.service`
- `hidloom-power-shed.service`
- `hidloom-touch-panel-profile.service`
- `ledd-shutdown.service`

## 役割

- USB gadget を早期に用意する。
- initramfs native input chainをrelease-safeに停止し、通常input chainのreadyを別phaseで確認する。
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
- `hidloom-usb-gadget.service` はsystemd専用wrapperを通し、early markerがある時はread-only adopterの完全一致だけを受理する。
  markerなしfresh bootまたはUDC emptyのnormal restart residueだけ従来createへ進み、bound不一致時はUDCを変更しない。
- `hidloom-early-input-handoff-prepare.service`はUSB gadgetの前に必ず実行し、path Conditionを使わない。
  valid E3 markerがある場合だけPID identityをpidfdへ固定し、4 status PID、固定socket topology、
  `/proc/net/unix`のkernel socket inodeとprocess FD、両HID character endpointとhidd FDを照合する。
  その後にlogical release、core停止後のoutputd/hidd queue drain、両keyboard endpoint zero write、ordered stopを
  証明する。証明できなければUSBを開始しない。
  markerなし通常bootはhelper内で`not-applicable`とする。
- `hidloom-early-input-handoff-finalize.service`は通常hidd/outputd/core/matrixdの後に実行し、prepareとは別の
  complete証跡を作る。通常側もstatus PID/executable、socket/endpointの実ownerをprocess FDへ結合する。
  ready判定はdaemon/socketの健全性を対象とし、未送信のidle coreが示す`broker.available=false`や
  利用者の正当なkey holdを待ち条件にしない。通常成功時はconfigfs/UDCを変更しないが、early chainの
  安全な終端を証明できない緊急復旧だけはverified UDC unbindでhostを切断する。gadget adopterの責務は持たない。
- `hidloom-hidd.service` はUSB gadgetを`After=`だけでなく`Requires=`し、adopt/create失敗時にendpoint ownerを開始しない。
- 独立enableされる`hidloom-outputd.service`、`hidloom-logicd-core.service`、`matrixd.service`も
  prepareを`Requires=`かつ`After=`し、E3 discovery/auth/release失敗時にearly chainと通常chainを同時起動しない。
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
  - USB gadget service wrapperとhidd hard dependency。
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
- early adopterのaccepted manifestはdevice/kernel/package固有であり、generic core packageへ埋め込まずdisabled配置時にroot-owned fileとして設置する。
