# Buildroot Fast Boot Experiment

更新日: 2026-07-05

Raspberry Pi Zero 2 W の高速起動を試すための Buildroot 実験メモ。
結論として、そろそろ試す価値はある。ただし Raspberry Pi OS をすぐ置き換えるのではなく、
別 microSD / 別 image の A/B 実験として、USB HID keyboard と最小 daemon から段階的に測る。

Raspberry Pi OS package との選択基準と利用者向け導入入口は
[INSTALL.md](../../INSTALL.md) を参照してください。

## 継続運用方針

- 主開発・改良・機能追加は従来の Raspberry Pi OS 構成で行う。
- Buildroot はWi-Fi/httpdを前提としないoffline keyboard applianceとして並行維持する。
- 主系変更ごとにBuildrootへの搭載を、効果、依存、起動時間、容量、保守性、攻撃面から判断する。
- 判断結果は「搭載」「非搭載」「後送り」のいずれかとして本書へ記録する。
- defconfig、overlay、cross-build/runtime staging helper、検証、Release手順を常に更新し、任意のcommitからimageを再生成できる状態を維持する。
- keymap、Vial definition、device profileなど共有データは両構成で互換性を保つ。

## 公開方針

- 現在のrepositoryはprivateの主開発・履歴保管用として維持する。
- public化する場合は既存repositoryのvisibilityを直接変更せず、監査済みclean exportの公開用repositoryを作成する。
- 公開側には再現可能なsource、Buildroot build手順、ライセンス、image、checksumを含める。
- private履歴、実機IP/hostname、credential、内部運用資料、再配布条件が不明なassetは公開側へ同期しない。
- 公開Releaseだけを置くbinary dumpにはせず、対応sourceとbuild手順を同時に提供する。

## 目的

- 電源投入から keyboard として使えるまでの時間を短くできるか測る。
- Raspberry Pi OS 側で既に入っている systemd / desktop service 削減と比べ、Buildroot 化の差分を定量化する。
- `logicd` / `usbd` / `matrixd` の最小構成が、汎用 distro なしで安定起動できるか確認する。
- Bluetooth、HTTP UI、Vial、OLED、LED などを後から足した時に、起動時間と保守性がどこで悪化するか見る。

## 方針

Buildroot 実験は、現行 runtime の完全移植ではなく、fast boot profile の探索として扱う。
実験 image は repository 本体と切り離し、現行 Raspberry Pi OS image を rollback path として残す。

- 既存の Raspberry Pi OS microSD は温存する。
- Buildroot image は別 microSD で作る。
- 最初の成功条件は USB HID gadget の enumerate と、固定 key report の送信に絞る。
- Python daemon 群を全部載せる前に、起動時刻の baseline を取る。
- 実機でしか判断できないため、実装 TODO ではなく ops 実験として進める。

## 2026-07-05 方針更新

`<keyboard-host>` / `<keyboard-host>` の package / device profile split が通過したため、
次の大きな実験として Buildroot M1-M3 を進める。目的は Raspberry Pi OS の全面置き換えではなく、
keyboard として使える最小経路が現行 OS よりどれだけ早く成立するかを判断すること。

進行は次の順序に固定する。

1. 現行 OS 側の最新 baseline を取り直す。
   package split 後の `hidloom-core` / board profile package 構成で、
   `hidg ready`、`matrixd ready`、`logicd ready`、`input-to-HID ready`、`usable keyboard` を優先する。
   `systemd-analyze` total や late service 起動時刻は背景情報として残す。
2. Buildroot M1 image を別 microSD へ書き、USB HID gadget enumerate を測る。
   ここでは network、HTTP UI、Vial、Bluetooth、OLED、LED は載せない。
3. M1 が安定したら M2 として固定 key report を安全な host 入力欄へ送る。
   host 側 focus が安全でない時は key tap を実行せず、enumerate までで止める。
4. M3 で `matrixd` と minimal `logicd` 相当だけを載せ、実キー押下から HID report までを測る。
   Python companion、HTTP、Vial、Bluetooth、OLED、LED は M3 の合否後に個別評価する。
5. M3 の `input-to-HID ready` / `usable keyboard` が現行 OS baseline より明確に速い場合だけ、
   M4 以降で current core daemon の持ち込みを検討する。

合否判断は M3 を主な decision point にする。M1 enumerate が速くても、M3 で実キー入力の差が小さい場合は、
Buildroot 化は当面の本線にせず、現行 Raspberry Pi OS の unit / dependency 最適化を優先する。

この実験で書き換えてよいのは別 microSD image と一時 artifact だけ。
既存 Raspberry Pi OS microSD、package release、device profile、host 側設定を変更する場合は、
その変更理由と rollback 手順を別途 runbook または checklist に残す。

## 主指標

この実験の主指標は total boot time ではなく、物理入力 path が成立するまでの時間にする。
GUI、network、cloud-init、desktop daemon が遅くても、keyboard として使う最小経路が先に立ち上がるなら
fast boot profile として価値がある。

優先して比較する順序:

1. `hidg ready`: `/dev/hidg0` が作られ、keyboard report を書ける。
2. `USB enumerate`: host 側に HID keyboard として見える。
3. `matrixd ready`: matrix scan loop が開始する。
4. `logicd ready`: matrix event を受け、resolved action を出せる。
5. `input-to-HID ready`: matrix event から `/dev/hidg0` への keyboard report まで届く。
6. `usable keyboard`: 実キー押下が host の安全な入力欄へ届く。

`systemd-analyze` の total や `graphical.target` は背景情報として残すが、合否には使わない。
Raspberry Pi OS 側で GUI や network が後から完了しても、上記 1-6 が早く成立するなら十分に成功扱いにする。

## 測定ポイント

`systemd-analyze` 相当がない構成でも比較できるよう、kernel log、serial console、GPIO / LED marker、
journal 相当の timestamp を組み合わせる。

| marker | 意味 |
| --- | --- |
| power on | 電源投入、または USB host 接続開始 |
| kernel start | UART / early printk / boot log の最初 |
| rootfs mounted | init が動き始めた時刻 |
| configfs ready | `/sys/kernel/config` が使える時刻 |
| hidg ready | `/dev/hidg0` / `/dev/hidg1` が作成された時刻 |
| USB enumerate | host 側に keyboard / Raw HID として見えた時刻 |
| logicd ready | `/tmp/ctrl_events.sock` などが受付可能になった時刻 |
| matrixd ready | scan loop が開始し、初回 event を送れる時刻 |
| input-to-HID ready | matrix event から HID keyboard report までの最小 path が通った時刻 |
| usable keyboard | 実キー押下が host へ届く時刻 |
| optional UI ready | HTTP / Vial / OLED / LED が利用可能になった時刻 |

比較時は「OS 起動完了」ではなく、`input-to-HID ready` と `usable keyboard` を主指標にする。

## フェーズ

| phase | 内容 | 合格条件 |
| --- | --- | --- |
| M0 | Buildroot vanilla boot | Pi Zero 2 W で serial console または SSHless local log を見られる |
| M1 | USB HID gadget only | `dwc2` / `libcomposite` / configfs で host に HID keyboard として enumerate する |
| M2 | minimal key path | 固定 key report、または小さい C helper で `/dev/hidg0` へ書ける |
| M3 | `matrixd` + minimal `logicd` | 実キー押下が host へ届く。HTTP / Vial / Bluetooth / LED / OLED はまだ足さない |
| M4 | current core daemons | `logicd` / `usbd` / `viald` / `matrixd` を載せ、Raw HID / Vial readiness を見る |
| M5 | full device candidates | `httpd` / `i2cd` / `ledd` / `btd` / `spid` を必要順に追加し、起動時間と RSS を比較する |

M3 までで Raspberry Pi OS より十分速くならない場合、Buildroot 化の優先度は下げる。
M3 が速い場合だけ、Python runtime と周辺 daemon の持ち込みを評価する。

## 依存リスク

現行構成は以下の依存があり、全部を Buildroot に載せると image 作成と保守が重くなる。

- Python 3 runtime と `aiohttp` / `dbus-next` / `Pillow` / `numpy` / `opencv`。
- `luma.oled`、`rpi_ws281x`、I2C / SPI / PWM / uinput。
- BlueZ D-Bus と BLE HID over GATT。
- TLS certificate generation、HTTP UI、Vial Raw HID bridge。
- configfs USB gadget、複数 HID interface、Windows JIS main / US sub keyboard identity。

そのため、Buildroot の初期 slice では Bluetooth、HTTP UI、OpenCV、OLED、LED animation を外す。
必要なら後続 phase で個別に足し、起動時間への影響を測る。

## Raspberry Pi OS 側 baseline

Buildroot と比較する前に、現行 OS で同じ marker を取る。

```bash
systemctl status hidloom-usb-gadget hidloom-hidd hidloom-uidd hidloom-outputd hidloom-logicd-core matrixd logicd-companion usbd viald httpd i2cd ledd btd --no-pager
journalctl -b -u hidloom-usb-gadget -u hidloom-hidd -u hidloom-outputd -u hidloom-logicd-core -u matrixd -u logicd-companion -u usbd -u viald -u httpd -u i2cd -u ledd -u btd --no-pager
ls -l /dev/hidg0 /dev/hidg1 /dev/hidg2
curl -k -u "admin:$(hostname)" https://127.0.0.1/api/status
python3 tools/perf_baseline.py --output /tmp/hidloom-rpi-os-boot-baseline.md
python3 tools/boot_marker_baseline.py --output /tmp/hidloom-boot-rpi-os-baseline.md
```

2026-06-21 の `<keyboard-host>` native owner baseline は次の通り。
`logicd-core-rs` / `hidloom-hidd` active owner、`ledd` 早期起動、late services 25s 構成で採取した。

| marker | seconds |
| --- | ---: |
| systemd startup total | 24.540 |
| multi-user.target reached | 16.424 |
| hidloom-usb-gadget active | 15.558 |
| hidloom-hidd active | 15.607 |
| logicd-core active | 15.630 |
| matrixd active | 15.649 |
| i2cd active | 15.775 |
| ledd active | 15.782 |
| logicd-companion active | 16.090 |
| btd active | 26.170 |
| viald active | 26.361 |
| httpd active | 26.393 |

同じ snapshot では `/tmp/usbd_hid_reports.sock`、`/tmp/matrix_events.sock`、
`/tmp/logicd_core_ctrl.sock` が存在し、hidd status は `write_errors=0` / `dropped_reports=0`、
logicd-core status は `pressed_matrix=0` / `pressed_keys=0` だった。
レポートは実機上の `/tmp/hidloom-boot-rpi-os-native-owner-baseline.md` に保存した。

追加で host 側から USB enumerate 時刻を取れる場合は、Windows Device Manager / Linux `dmesg -w` /
`lsusb -v` の観測を合わせる。

2026-07-11 に `<keyboard-host>` の split-package keyboard runtime で再起動付き baseline を取得した。
artifact は
`build/artifacts/<keyboard-host>-reboot-split-remote-boot-baseline-20260711T052822Z/`。
`keyboard_ready=13.995s`、`usb->input=1.835s`、USB gadget active `12.160s`、
hidd active `12.186s`、logicd-core active `13.542s`、matrix/input ready `13.995s` だった。
`tools/buildroot_m1_compare.py` へ同 report を入力し、Raspberry Pi OS 側 marker を埋めた比較表
`<keyboard-host>-rpi-os-side-buildroot-m1-compare.md` も同 artifact directory に生成した。
M1 側は別 microSD 実験後に boot marker と host USB enumerate report を追加して埋める。
Linux host では以下で前後の `lsusb` と `udevadm monitor` を Markdown に残す。
`udevadm monitor` の各行には watcher 開始からの `+seconds` timestamp が付く。

```bash
python3 tools/usb_enumeration_watch.py --duration 30 --output /tmp/hidloom-usb-enumeration-rpi-os.md
```

## Fresh OS baseline device

`pi@<keyboard-ip>` / `<keyboard-host>` は Raspberry Pi Zero 2 W Rev 1.0 の fresh OS test case として使える。
2026-06-17 時点では HID gadget と keyboard 基板は未接続のため、`usable keyboard` や USB enumerate の
合格判定には使わない。用途は、Buildroot M0/M1 と比べる前の fresh Raspberry Pi OS 系 baseline として、
OS 起動時間、kernel / module readiness、configfs mount、HIDloom service 未導入状態を確認すること。

初回 read-only 確認では以下だった。

- host: `<keyboard-host>`
- model: `Raspberry Pi Zero 2 W Rev 1.0`
- OS: Debian GNU/Linux 13 trixie
- kernel: `6.12.75+rpt-rpi-v8` aarch64
- `systemd-analyze`: `1min 22.743s`、`graphical.target` は userspace `57.585s`
- failed units: 0
- configfs: `/sys/kernel/config` mount 済み
- `dwc2` / `libcomposite`: 未ロード
- `/dev/hidg*`: なし
- HIDloom services: 未導入 / inactive

`systemd-analyze blame` の上位は、`NetworkManager.service` 約31秒、`cloud-init-main.service` 約7.8秒、
`dev-mmcblk0p2.device` 約7.6秒、`accounts-daemon.service` 約4.0秒、
`rpi-resize-swap-file.service` 約4.0秒だった。
Buildroot M1 では network、cloud-init、graphical target、account / desktop 周辺を外すため、
M0/M1 比較で差が出る見込みがある。
module availability の read-only 確認では、`usb_f_hid.ko.xz`、`g_hid.ko.xz`、
`libcomposite.ko.xz` が存在し、`dwc2` と `configfs` も module metadata に見えている。
fresh OS 上では未ロードだが、kernel 側の gadget 前提は揃っている。

この device では local helper を一時コピーして baseline report を作れる。

```bash
scp tools/boot_marker_baseline.py pi@<keyboard-ip>:/tmp/hidloom-boot_marker_baseline.py
ssh pi@<keyboard-ip> \
  'python3 /tmp/hidloom-boot_marker_baseline.py --output /tmp/hidloom-boot-fresh-os-baseline.md'
```

繰り返し回収する場合は local から次を使う。

```bash
python3 tools/remote_boot_baseline_collect.py pi@<keyboard-ip> \
  --label <keyboard-host>-fresh-os \
  --samples 3 \
  --interval-sec 10
```

今回の local copy は git 管理外 artifact として
`build/artifacts/<keyboard-host>-fresh-os-baseline/` に置いた。
追加で `remote_boot_baseline_collect.py --samples 3` を実行し、
`build/artifacts/<keyboard-host>-fresh-os-remote-boot-baseline-20260617T144344Z/` に
3 サンプル分の report を回収した。同一 boot 内では `systemd-analyze` と top blame は 3 回とも一致し、
`/dev/hidg*` は無し、gadget module は未ロードのままだった。
module availability 入りの snapshot は
`build/artifacts/<keyboard-host>-fresh-os-modules-remote-boot-baseline-20260617T144533Z/` に置いた。

sudoers 整備後、`sudo -n reboot` で再起動し、SSH 復帰直後の repeated baseline も回収した。
`build/artifacts/<keyboard-host>-after-reboot-remote-boot-baseline-20260617T145751Z/` の 3 サンプルでは、
`systemd-analyze` が `5.736s (kernel) + 1min 2.819s (userspace) = 1min 8.556s`、
top blame が `19.396s NetworkManager.service` で一致した。前回の同一 boot 内 baseline
`22.776s + 59.967s = 1min 22.743s` と比べ、kernel 時間に大きな揺れがある。
Buildroot M1 比較では、最低でも reboot 直後 baseline を複数回取って範囲で見る。
追加で reboot cycle 02 / 03 を取り、3 cycle の範囲は kernel `5.736s`-`6.601s`、
userspace `52.564s`-`62.819s`、total `59.166s`-`68.556s` だった。
top blame は全 cycle で `NetworkManager.service`。集約は
`build/artifacts/<keyboard-host>-reboot-cycle-summary.md` に置いた。
ただし `<keyboard-host>` は HID gadget と keyboard 基板が無いため、この total boot baseline は
Buildroot M1/M3 の合否判定には使わない。今後 `-01` と同じ runtime 条件、または M3 相当の構成で測る時は、
`matrixd ready`、`logicd ready`、`input-to-HID ready`、`usable keyboard` の各 marker を優先する。

SSH host key が fresh OS 化で変わっている場合は、既存 `known_hosts` をすぐ書き換えず、
一時 `UserKnownHostsFile` で fingerprint を確認してから恒久更新する。
DHCP 環境などで user が明示的に許可した場合は、`ssh-keygen -R <keyboard-ip>` 後に
`StrictHostKeyChecking=accept-new` で現在の host key へ更新してよい。

## Buildroot image の最小要件

- Raspberry Pi Zero 2 W 対応 kernel / firmware / device tree。
- `dwc2` peripheral mode。
- configfs と `libcomposite`。
- HID gadget function。
- `uinput` は M3 以降で必要。
- I2C / SPI / PWM は M5 以降で必要。
- rootfs は read-only でもよいが、runtime config と keymap persistence の保存先を別途決める。

## Repository assets

M1 用の tracked assets は [../../build/buildroot/README.md](../../build/buildroot/README.md) に置く。

| path | 役割 |
| --- | --- |
| `build/buildroot/hidloom-external` | Buildroot `BR2_EXTERNAL` skeleton |
| `configs/hidloom_m1_defconfig` | Pi Zero 2 W M1 image の Buildroot entrypoint |
| `board/hidloom/linux-m1-usb-gadget.fragment` | configfs / HID gadget kernel option fragment |
| `board/hidloom/config_zero2w_m1.txt` | `dwc2` peripheral mode を有効にする firmware config |
| `board/hidloom/cmdline_m1.txt` | `dwc2` / `libcomposite` を early module load する cmdline |
| `rootfs_overlay/etc/init.d/S20hidloom-hid-gadget` | boot 時に M1 keyboard gadget を作る init script |
| `rootfs_overlay/usr/bin/hidloom-hid-gadget-m1` | configfs で `/dev/hidg0` boot keyboard だけを作る helper |
| `rootfs_overlay/usr/bin/hidloom-hid-key-tap-m1` | M2 手動 smoke 用。明示実行時だけ 1 key tap を送る |

`S20hidloom-hid-gadget` は key report を送らない。host へ実入力を送る確認は、
enumerate 時刻を記録した後に `hidloom-hid-key-tap-m1 /dev/hidg0 04` を手動実行する。

2026-06-17 に Buildroot upstream shallow checkout commit `67449130` で
`make BR2_EXTERNAL=... O=build/artifacts/buildroot-m1-output hidloom_m1_defconfig`
まで通ることを確認した。展開後 `.config` には rootfs overlay、kernel fragment、Pi Zero 2 W DTS、
firmware config / cmdline、`kmod`、`genimage`、120 MiB ext4 rootfs の設定が入っている。
確認 summary は git 管理外 artifact の
`build/artifacts/buildroot-m1-defconfig-smoke/summary.md` に置いた。

2026-07-11にx86_64 build hostで同commit
`67449130e9fdd71a38ca26539dddfa8c882b1977` の M1 full cross-build が完了した。
`build/artifacts/buildroot-m1-output/images/sdcard.img` は 153 MiB の MBR image で、
FAT boot partition と 120 MiB rootfs partition を含む。kernel config は
`CONFIG_USB_DWC2=y`、`CONFIG_USB_F_HID=y`、`CONFIG_USB_CONFIGFS=y`、
`CONFIG_USB_CONFIGFS_F_HID=y`、`CONFIG_CONFIGFS_FS=y`。rootfs image 内に
`S20hidloom-hid-gadget`、`hidloom-hid-gadget-m1`、`hidloom-hid-key-tap-m1` と
`m1_start` / `hidg_ready` / `m1_udc_bound` marker が入ることを確認した。
`sdcard.img` の SHA-256 は
`499bf6f7dd67227a75332cdb07f6a6cf52f23c3668d68d1a72d0e4cd8bd79b06`。
build summary は `build/artifacts/buildroot-m1-output/summary.md` に置いた。
Raspberry Pi 実機では build を行わず、完成 image を別 microSD へ書いた後の M1 boot / enumerate
だけを確認する。

移行前の非公開試験では、raw `sdcard.img`、圧縮版
`hidloom-buildroot-m1-20260711.img.zst`、両方のSHA-256 fileをWindows image hostへ渡した。
この過去artifactはpublic repositoryのReleaseへ移行しない。再試験では同じpinned sourceから
x86_64 hostで再buildし、Raspberry Pi Imagerへraw `sdcard.img`を直接渡す。圧縮版を転送に使う
場合は、展開後のimage hashを上記raw SHA-256と照合する。

## M1 runbook

事前準備:

- 現行 OS microSD は保管し、Buildroot 用に別 microSD を使う。
- image buildはx86_64 build VM、microSD書き込みは物理readerを持つWindows hostで行う。
  Raspberry Pi実機ではbuildしない。
- Windows image hostへ転送後、PowerShell
  `Get-FileHash .\sdcard.img -Algorithm SHA256` が文書記載の SHA-256 と一致することを確認する。
- Raspberry Pi Imager の `Use custom` で image を選び、reader / capacity を見て専用 Buildroot
  microSD を識別する。Windows system disk と保存済み Raspberry Pi OS microSD は選ばない。
- USB host 側では安全な入力欄、または入力を受けても問題ない検証用 buffer を用意する。
- host 側 USB enumerate watcher と Pi 側 boot marker の開始時刻をできるだけ揃える。
- 実験 artifact は `build/artifacts/` または `/tmp` へ置き、成功した比較結果だけ docs へ要約する。

1. x86_64 build hostでM1 imageをcross-buildする。

   ```bash
   make BR2_EXTERNAL=/path/to/hidloom/build/buildroot/hidloom-external hidloom_m1_defconfig
   make
   ```

2. `sdcard.img`をWindows image hostへ転送し、PowerShellでchecksumを確認する。

   ```powershell
   Get-FileHash .\sdcard.img -Algorithm SHA256
   ```

3. Windows image hostのRaspberry Pi Imagerで`Use custom`を選び、専用の別microSDへ書く。
   Imager の post-write verification を有効にし、完了後に安全に取り外す。

4. USB host 側で watcher を起動する。

   ```bash
   python3 tools/usb_enumeration_watch.py --duration 30 --output /tmp/hidloom-usb-enumeration-m1.md
   ```

5. Buildroot M1 microSD の Raspberry Pi Zero 2 W を USB host へ接続する。
6. Pi 側で `/tmp/hidloom-boot-markers.log` を確認できる場合は保存する。
   M1 helper は `m1_start`、`hidg_ready`、`m1_udc_bound` を記録する。
7. host 側で HID keyboard として見えたら、Pi 側で次を手動実行して M2 の最小入力を確認する。

   ```bash
   hidloom-hid-key-tap-m1 /dev/hidg0 04
   ```

8. `04` は HID usage `Keyboard a and A`。安全な入力欄に focus してから実行する。
9. 確認後は `/tmp/hidloom-usb-enumeration-m1.md` と `/tmp/hidloom-boot-markers.log` を比較する。
   host 側 report は `+seconds`、Pi 側 marker は `/proc/uptime` 秒なので、
   power-on / reconnect の操作時刻を揃えるほど比較しやすい。

10. 現行 Raspberry Pi OS baseline と M1 report を横並びにする。

   ```bash
   python3 tools/buildroot_m1_compare.py \
     --rpi-os /tmp/hidloom-boot-rpi-os-native-owner-baseline.md \
     --m1-boot /tmp/hidloom-boot-buildroot-m1.md \
     --m1-usb-watch /tmp/hidloom-usb-enumeration-m1.md \
     --output /tmp/hidloom-buildroot-m1-compare.md
   ```

   M1 側で `boot_marker_baseline.py` をまだ動かせない場合も、
   `--m1-usb-watch` だけで host USB enumerate の最初の event を比較表へ残せる。

## 成功 / 中止基準

成功:

- M1 で USB HID keyboard enumerate が安定する。
- M2 で明示操作時だけ固定 key tap が送られ、意図しない起動時入力が発生しない。
- M3 で `matrixd ready` から HID report 送信までの最小 path が現行 OS より明確に速い。
- `usable keyboard` が GUI / network / optional daemon 完了を待たずに成立する。
- rollback が microSD 差し替えだけで済む。

中止または保留:

- M3 までで `input-to-HID ready` / `usable keyboard` の差が小さい。
- Python / BlueZ / HTTP / Vial を足した段階で保守負荷が大きすぎる。
- Windows JIS main / US sub keyboard identity や Raw HID / Vial bridge が不安定になる。
- 実機復旧経路が Wi-Fi / SSH 依存になり、keyboard としての安全性が下がる。

## 実機確認待ち

2026-07-11 M1 first boot result:

- Windows image hostで書いた別microSDからBuildroot login promptまで起動した。
- HDMI boot log は `M1 HID gadget bound to 3f980000.usb` を `3.007240s`、
  USB high-speed detection を `3.181451s` に記録し、Windows も USB device を検出した。
- OLED / key LED 消灯と物理 key 無反応は M1 の想定内。M1 は USB HID gadget only で、
  `matrixd` / input routing / `ledd` / `i2cd` を含まない。
- 次の判定は console から明示実行する M2 `hidloom-hid-key-tap-m1 /dev/hidg0 04`。
  物理 key 入力は M3 の minimal matrix-to-HID image で評価する。

2026-07-11 M2 image build:

- `hidloom_m2_defconfig` と M2専用 `rootfs_overlay_m2` を追加した。
- M1 gadget bind後、起動10秒待って HID usage `0x04` を一度だけ80ms tapする。
- product name は `CQA02303v5 M2 One-shot Keyboard`。marker は
  `m2_wait_start` / `m2_tap_start` / `m2_tap_done`。
- x86_64 hostでのfull cross-build、rootfs executable/content検査、M1 imageへのone-shot非混入が通過した。
- 移行前の非公開試験用bundleへraw image、30 MiB圧縮版、両checksumを収録し、圧縮assetの
  transfer verifyも通過した。この過去artifactはpublic repositoryのReleaseへ移行しない。
  raw image SHA-256 は
  `afc6d9d9175ac1c6e671dd20e02fc425d0ab5c481c5ef0c701f41a1d5896816b`。
- Windows側は安全な空入力欄へfocusしてからM2を起動する。想定結果は小文字 `a` 1文字だけで、
  repeatや起動ごとの複数送信はfailとする。
- 2026-07-11のWindows host smokeではWindows IMEが有効だったため、one-shot `a` tapは
  `あ` 1文字として入力された。これは期待どおりのhost側IME解釈で、Buildroot `/dev/hidg0` から
  WindowsへのM2固定report経路はpass。次はM3のminimal physical matrix-to-HID pathへ進む。

2026-07-11 M3 image build:

- existing C `matrixd` と minimal `hidloom-m3-router` を Buildroot local package 化した。
- M3 は physical charlieplex edge を `/tmp/matrix_events.sock` で受け、proof用に全physical keyを
  HID usage `0x04` (`a`) へ変換する。releaseはzero report。boot時自動tapはない。
- marker は `m3_router_ready` / `m3_matrix_connected` / `m3_physical_press` /
  `m3_hid_report_sent` / `m3_physical_release`。
- first image はkernelに`CONFIG_RASPBERRYPI_GPIOMEM`がなく、`/dev/gpiomem`を作れないため
  USB enumerate後もphysical keyが無反応だった。M3専用kernel fragmentへ
  `CONFIG_RASPBERRYPI_GPIOMEM=y`を追加し、initにもdevice不在をconsoleへ出すguardを追加した。
- 修正版full cross-buildとrootfs検査が通過。raw SHA-256は
  `52c9a9af216b475888e87d534431b522e5e4ee4c6bf7b8f6e21df1c935ce7873`。
- 移行前の非公開試験用bundleは旧assetを削除して修正版へ置換した。この過去artifactは
  public repositoryのReleaseへ移行しない。
- 修正版のWindows host実機確認ではHDMIに`M3 matrixd starting with /dev/gpiomem`が出て、
  USB high-speed `3.153413s`、host address assignment `3.188918s`。全tested physical keyが
  fixed mappingどおり`A`/`a`としてWindowsへ到達した。M3 physical matrix-to-HID gateはpass。

2026-07-11 M4 preparation:

- `armv7-unknown-linux-musleabihf` targetと`rust-lld` linkerを固定し、x86_64 build hostで
  `hidloom-logicd-core` / `hidloom-outputd` / `hidloom-hidd` の32-bit ARM static cross-buildが通過した。
- `tools/buildroot_m4_native_build.sh` は3 binaryを
  `build/artifacts/buildroot-m4-native/bin/`へ再現生成する。
- 次のM4 image sliceはM3 fixed-`a` routerを外し、full keymapを読むnative core、outputd、hiddを
  single keyboard endpointへ接続する。Raw HID/Vialとdual keyboard identityはその後に追加する。
- M4 first-slice imageを生成し、`hidloom-hidd -> hidloom-outputd -> hidloom-logicd-core -> matrixd`の順で
  起動する。`S29hidloom-m4-preflight`は3 socketを待ち、成功時に
  `M4 native HID/keymap route ready`をconsoleへ出す。
- first imageはcoreがdefault shadow socket/output disabledのままで、consoleに
  `M4 ERROR: native route sockets not ready`を出した。active matrix socket、outputd report socket、
  output enableを明示した修正版へreleaseを置換した。
- 次の実機smokeで起動直後からCtrlが押下状態になる現象を検出した。起動時GPIO transitionが
  最初のdebounced pressとして送信される経路を原因候補とし、`matrixd`へ設定可能な
  `startup_quiet_ms`を追加した。M4は500 msの間、debounce stateだけをcommitしてeventを
  forwardingしない。ただし実機でCtrl固定は継続し、この仮説は否定された。
- 真因はM1由来のReport IDなし8-byte boot keyboard descriptorと、productionどおり
  Report ID `0x01`を付加する`hidloom-hidd`の不一致だった。M4 gadgetを`hidg0` JP composite、
  `hidg1` Raw HID予約、`hidg2` US sub keyboardへ変更し、split routingも有効化した。
  再修正版raw SHA-256は
  `a7f78ab39523df5cd23a738f8f75f01ab1a75a26873de7cc6ce8370496cce0f0`。
- 実機ではmodifierが復旧した一方、`LT(1,KC_LANG2)` / `LT(2,KC_LANG1)`は無反応だった。
  native coreはtimed actionを`/tmp/logicd_delegate_events.sock`へ委譲するが、M4には
  companion listenerがない。ADS1115 readerである`i2cd`も未搭載のためanalog stickも無反応。
- 次の切り分けimageでは`tools/buildroot_m4_jp_direct_keymap.py`により2キーだけを
  `KC_LANG2` / `KC_LANG1`へ直接化する。これでJP endpointを確認し、layer-tapとanalogは
  companion/i2cd native化後に戻す。
- `<keyboard-host>`実機でM4.1のJP/US出し分けはpassした。これによりdescriptor、hidd、
  outputd、split routingは正常と確定した。`LT(...)`はcompanion不在のため不動、I2C経路を
  起動していないためOLED/ADS1115 stickは不動、LED daemon不在のためLED消灯だった。
- 次imageはkeymapを原状へ戻し、companion、I2C/OLED/ADS1115、LEDをservice readiness付きで
  追加する。M4.1 direct-routeはendpoint診断用artifactとして残す。

2026-07-11 M5 peripheral image:

- Buildroot targetへPython 3、Pillow、cbor2、smbus2、rpi-ws281xをcross-buildし、pure Pythonの
  luma.core / luma.oledとproduction `logicd` companion、`i2cd`、`ledd`を配置した。
- 起動順はnative hidd/outputd/coreの後にcompanion、I2C modules、matrixd、i2cd、leddとした。
  keymapはM4.1のdirect diagnosticを外し、元の`LT(1,KC_LANG2)` / `LT(2,KC_LANG1)`へ戻した。
- boot configへ`dtparam=i2c_arm=on`を追加し、`i2c-bcm2835` / `i2c-dev`を起動時にloadする。
- build host検証はARM Pythonによる全daemon/import、rootfs `e2fsck -fn`、必須binary/init file、
  boot configをpass。raw SHA-256は
  first imageのOLED BusyBox readinessとuinput sink欠落を修正したraw SHA-256は
  `b8968bcc7e2b00195288c9d6f961529507871b331419cb65718b092ea5832680`。
- HDMI/serial console login用に`pi`（UID/GID 1001、home `/home/pi`、shell `/bin/sh`）を追加した。
  実験imageの初期passwordは`pi`。ネットワークログイン用途には使用しない。

2026-07-11 M6 focused Vial image:

- Buildrootはoffline keyboard applianceのまま維持し、Wi-Fi/httpdは追加しない。
- 既存`hidg1` Raw HID interfaceに`hidloom-hidd` bridgeを接続し、Python `viald`を先行起動する。
  Vialは3 layers、32-byte report、save-on-setで動作する。
- `/mnt/p3/{keymap.json,vial.json,config.json}`を永続領域としてseedした。Vial保存成功後は
  companionがnative coreへ`reload`を送り、再起動なしで通常キーの変更も反映する。
- Python XZ/lzmaをcross-buildへ追加。ARM QEMU上のviald Unix socketへ32-byte要求を送り、
  protocol version応答を受信した。local protocol/keycode testsとext4 fsckもpass。
- M6 raw SHA-256は
  `86e05798c7c89ae0a0811b6026b880b0635fd7f8c82379e8ec982e1a2a7cd394`。
- 初回M6ではuinput経由でlogin promptへ`pi`を入力できたが認証に失敗した。Virtual Keyboard生成と
  username/password入力到達からuinputはpass。BusyBox既定password algorithmがSHA-256なのに
  shadowをSHA-512で作成していたため、`pi` hashをSHA-256（`$5$`）へ修正した。
- console保守用にBuildroot `sudo` packageを追加し、`pi`を`wheel`へ所属させた。
  `%wheel ALL=(ALL:ALL) ALL`のpassword認証を使い、NOPASSWDにはしない。
- corrected M6の`<keyboard-host>`実機smokeではuinput `3.302305s`、USB high-speed
  `3.304085s`、host address `3.339609s`、I2C ready `3.370135s`、login prompt上の
  virtual input ready `5.575736s`を観測し、ケーブル挿入から約6秒で実キー入力可能だった。
- 2026-07-12に、M3 output treeへ手作業で追加していたM5/M6差分を
  `hidloom_m6_defconfig`、`rootfs_overlay_m6`、`post-build-m6.sh`へ回収した。
  `tools/buildroot_m6_build.sh`が4 native binaryのcross-build、defconfig展開、image生成、artifact検証を
  一括実行する。以後のM6 imageはこのclean output経路を標準とし、既存M3 outputの直接変更は禁止する。
- clean M6 defconfig展開、4 native ARM static binaryのcross-build、空rootfsへの193ファイルstaging、
  既存corrected M6 imageのSHA検証はpassした。初回`make source`はBootlin toolchain等の取得中に
  runnerの120秒上限へ達したため、clean imageとlegal-infoの完走はbuild host上の長時間rehearsalへ残す。
- M6専用fast-boot policyとしてUART console、firmware splash、kernel logo、initramfs、USB mass-storageを
  無効化し、rootをmicroSD `/dev/mmcblk0p2`へ固定した。HDMI `tty1`は保守用に残し、1920x1080 60 Hzへ
  固定する。M1-M3のserial recovery設定は比較・rollback用として変更しない。
- x86_64 host clean buildはsource取得とincremental再開を含めて完走した。生成imageはext4 `e2fsck -fn`、
  M6 runtime artifact、image内`pi`/`wheel`/SHA-256 password hash、kernel disable設定をpassした。
- 実機確認用artifactは
  `build/artifacts/buildroot-m6-output/images/hidloom-buildroot-m6-fastboot-20260713.img`
  （243270144 bytes、SHA-256
  `8931f0258af7afc3b7f6c149e309e708b15b95ffa11365dd9d0bd4766af479e3`）。zstd版は40785369 bytes、
  SHA-256 `d90920a86ff4bfd18f4c96bbaea3e8b0262a5ef76a9ddfbc997771363b7aafc3`。
- 上記初版fastboot artifactは`hidloom_paths.py`とluma packages欠落が判明したため使用禁止。
  修正版は`hidloom-buildroot-m6-fastboot-r2-20260713.img`（243270144 bytes、SHA-256
  `90ced740c83775cbd5ba84d9a1ea135a9c1942f8dd1e48f8d50ed0fb3923609d`）。zstd版は40889911 bytes、
  SHA-256 `528527ee9b971e011ee3e8d1d6cdb3b1395c3c9f4a0d84b9a48b76be0f29b3cc`。
- 2026-07-13 milestone横断監査では、保存済みM1～M5の必須rootfs fileとext4 fsckはpassした。
  M1～M4はPython runtimeを搭載せず、M5は旧self-contained `hidloom_paths.py`を含むため、今回のrename欠落は
  clean M6だけに限定された。一方、M5で手動配置していた`luma.core`/`luma.oled`もclean M6から欠落して
  いたためexternal Buildroot package化した。M6 build完了条件へARM target上の8 module import smokeを追加した。
- r2実機ではUSB enumerateと起動はpassしたが、JIS側key、OLED ready遷移、LED startup解除がfailした。
  3症状の共通原因は、clean stagingから`daemon/usbd`が欠落し、`logicd-companion`が
  `ModuleNotFoundError: No module named 'usbd'`で起動直後に終了していたことだった。さらにM3 overlay由来の
  不要な`S25hidloom-m3-router`も残っていた。
- r3では`daemon/usbd`をstageし、旧M3 router initを削除した。companion stderr/stdoutは
  `/var/log/logicd-companion.log`へ保存する。build完了条件には単純importに加え、ARM companionを4秒間実行して
  `runtime initialized`後も生存すること、およびARM native coreで`KC_RO`がJIS main、`KC_A`がUS subへ
  routeされることを追加した。
- `hidloom-buildroot-m6-fastboot-r2-20260713.img`は上記欠陥のため使用禁止。実機確認用r3は
  `build/artifacts/buildroot-m6-output/images/hidloom-buildroot-m6-fastboot-r3-20260713.img`
  （243270144 bytes、SHA-256 `c862b3a0a598e0d59f202d3ec87181089202b28c896813bf57ff5c43ea4914a8`）。
  zstd版は40895906 bytes、SHA-256 `d8dd3eedcf670c5805d775aae07aa919c08b2ff7cab5fda669ca0194bd38c1ae`。
  rootfs `e2fsck -fn`、image内`usbd/hid_report_broker.py`、旧router不在、companion log設定を確認済み。
- 2026-07-13に`<keyboard-host>`でr3を実機確認した。JIS/US split、LT tap/hold、OLEDの`booting`解除、
  LEDのstartup effect解除とkey reaction、analog stick、再起動後の状態維持はすべてpassした。
  M6 r3を現行Buildroot実機合格artifactとする。Raspberry Pi OS microSDはrollback用に保持している。
- HIDloom hard cut後、x86_64 build hostで旧outputを退避して`./tools/buildroot_m6_build.sh`をclean実行した。
  生成した`hidloom-buildroot-m6-hardcut-20260713.img`は243270144 bytes、SHA-256
  `780840e3f50949504a347ceed321be35702a83cc2cc3c5b7eabab067d7c6723a`。zstd版は約39 MiB、SHA-256
  `94e7071ce957c76eb63b90e12c0b436984971b06c58e97063a6067d6c026a592`。
  artifact verifierは13必須file、sudoers 0440、microSD-only/UART-off/1080p policyをpassし、QEMU ARM上で
  Python daemon import、JIS/US split routing、companionのruntime initialization後4秒生存を確認した。
  software runtimeは`/usr/share/hidloom`へ一本化され、旧install pathやfallbackは含まない。

- `<keyboard-host>` fresh OS baseline は reboot cycle 3 回分まで取得済み。
  total `59.166s`-`68.556s` は背景値として扱い、M1/M3 の合否には使わない。
- 現行 Raspberry Pi OS の `input-to-HID ready` baseline は `<keyboard-host>` で取得済み。
  host 側 `usable keyboard` の観測時刻は未取得。
- Buildroot M1 の USB enumerate 時刻。
- Buildroot M3 の実キー入力時刻。
- Vial / HTTP / OLED / LED / Bluetooth を追加した時の起動時間、RSS、安定性。
