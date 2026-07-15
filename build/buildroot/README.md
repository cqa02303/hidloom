# Buildroot experiment assets

Raspberry Pi Zero 2 W fast boot experiment 用の tracked assets です。
ここは現行 Raspberry Pi OS の install path ではなく、別 microSD / 別 Buildroot image に入れる
最小構成だけを置きます。

## Layout

| path | role |
| --- | --- |
| `hidloom-external/` | Buildroot `BR2_EXTERNAL` skeleton |
| `hidloom-external/configs/hidloom_m1_defconfig` | Raspberry Pi Zero 2 W M1 entrypoint |
| `hidloom-external/configs/hidloom_m2_defconfig` | M1 gadget + delayed one-shot key M2 entrypoint |
| `hidloom-external/configs/hidloom_m6_defconfig` | offline Vial appliance M6 entrypoint |
| `hidloom-external/board/hidloom/linux-m1-usb-gadget.fragment` | configfs / HID gadget kernel fragment |
| `hidloom-external/board/hidloom/rootfs_overlay/` | M1/M2 rootfs overlay |

## M1 Goal

M1 は USB HID keyboard gadget だけを起動します。
`logicd`、`matrixd`、Raw HID / Vial、HTTP、Bluetooth、OLED、LED は載せません。

rootfs overlay には次だけを入れます。

- `/etc/init.d/S20hidloom-hid-gadget`: boot 時に M1 gadget を作る init script。
- `/usr/bin/hidloom-hid-gadget-m1`: configfs で `/dev/hidg0` keyboard を作る。
- `/usr/bin/hidloom-hid-key-tap-m1`: M2 手動確認用。明示実行時だけ 1 key tap を送る。

## M2 Goal

M2 は M1 overlay を維持し、追加の `rootfs_overlay_m2` だけで起動10秒後に
HID usage `0x04` (`Keyboard a and A`) を一度だけ press/release します。
Windows 側で安全な空の入力欄へ focus してから電源を入れます。
M2 product name は `CQA02303v5 M2 One-shot Keyboard` とし、M1と区別します。
`m2_wait_start` / `m2_tap_start` / `m2_tap_done` を boot marker へ残します。

## Buildroot Usage

Buildroot checkout 側で、この repository の `BR2_EXTERNAL` を指定して M1 defconfig を展開する。
この defconfig は Buildroot upstream の `raspberrypizero2w_defconfig` を土台にし、
rootfs overlay、USB gadget kernel fragment、`dwc2` peripheral mode の firmware 設定だけを足す。

```bash
make BR2_EXTERNAL=/path/to/hidloom/build/buildroot/hidloom-external hidloom_m1_defconfig
make
```

x86_64 build hostではhost dependencyとして`cpio` / `bc`が必要です。Ubuntuの
`/usr/bin/install` が uutils implementation の場合、Buildroot の dependency check を
通すため system-wide alternatives は変更せず、build 専用 PATH で GNU implementation を使います。

```bash
mkdir -p /tmp/hidloom-build-hostbin
ln -sf /usr/bin/gnuinstall /tmp/hidloom-build-hostbin/install
PATH=/tmp/hidloom-build-hostbin:$PATH make
```

時間のかかるtoolchain / kernel / rootfs buildはx86_64 hostで
cross-build し、Raspberry Pi 実機では実行しません。実機は完成した別 microSD image の
boot marker / USB enumerate / key tap 確認だけに使います。

Buildroot の版を変える時は、先に上流の `configs/raspberrypizero2w_defconfig` と
`hidloom_m1_defconfig` を見比べ、kernel tarball、device tree、firmware package option を更新する。

menuconfig で追加確認するもの:

- Linux kernel / firmware / device tree が Raspberry Pi Zero 2 W に合っている。
- `dwc2` peripheral mode が使える。
- configfs と USB gadget HID function が有効。
- rootfs overlay に `board/hidloom/rootfs_overlay` を指定する。

初回 image では network / SSH を要求せず、USB host 側の enumerate と serial console / LED / boot log で見る。

## M6 reproducible build

M6は手作業で既存output treeを書き換えず、x86_64 build host上で次を実行する。

```bash
tools/buildroot_m6_build.sh
```

上流Buildrootは`config/buildroot-source.json`のcommitへ固定する。checkoutが無い場合は
`tools/buildroot_source_prepare.py`が取得し、既存checkoutではorigin、HEAD、tracked差分を検証する。
public sourceだけからpackageとM6を再生成する入口は
`docs/ops/public-source-rebuild-runbook.md`を参照する。

wrapperは4個のnative Rust binaryを`armv7-unknown-linux-musleabihf`へcross-buildし、M6 defconfigを
新しいoutput treeへ展開してからBuildroot imageを生成する。`post-build-m6.sh`はoffline applianceに
必要な`logicd` companion、`viald`、`i2cd`、`ledd`、設定だけをrootfsへstageする。Wi-Fi、HTTP、
Bluetooth daemonはstageしない。設定だけを確認する場合は次を使う。

```bash
tools/buildroot_m6_build.sh --configure-only
```

source archive取得だけを再開する場合は`--source`、source取得後にBuildrootのlicense/source evidenceを
生成する場合は`--legal-info`を指定する。後者は`legal-info/hidloom-summary.json`も生成し、source auditと
binary release blockerを分離して記録する。どちらもimage検証を誤って要求しない。

### M6 binary compliance bundle

`legal-info`単体の警告を無視してimageを公開しない。Bootlin公式summary 27行から重複を統合した25 component、
source archive 24件、license file 41件は`config/buildroot-toolchain-components.json`へSHA-256固定する。
固定内容を更新する場合だけ公式siteからlockを再生成する。

```bash
make buildroot-compliance-lock
```

M6 `legal-info`、HIDloomが使用した固定Buildroot source、Bootlin toolchain builder source、Bootlin全component
source/licenseを一つのcontent-addressed archiveへまとめ、展開後の全file、manifest、内部hardlinkを検証する。

```bash
make buildroot-compliance-bundle
make buildroot-compliance-verify
```

既定成果物は`build/artifacts/hidloom-buildroot-m6-compliance.tar.zst`。cache済みobjectは再利用し、未取得fileだけを
公式URLから取得してlockのsize/SHA-256と照合する。trackedな`docs/ops/buildroot-m6-legal-summary.json`は
`legal-info`単体の状態を表すため`binary_release_ready=false`のまま保持し、完成archive内の
`COMPLIANCE_MANIFEST.json`と`BUILDROOT_LEGAL_SUMMARY.json`だけが`binary_release_ready=true`になる。

### M6 boot policy

M6はmicroSD applianceとして、rootを`/dev/mmcblk0p2`のext4へ固定する。initramfs、USB mass-storage、
kernel logo、UART consoleはkernel fragmentで無効化する。USB HID gadgetに必要なDWC2/configfs HIDは
維持する。HDMIの`tty1`はローカル保守用に残し、firmwareで1920x1080 60 Hz（DMT mode 82）へ固定する。
rainbow splash、boot delay、cursor、通常kernel info logは表示しない。

UART consoleを外すため、起動失敗時の一次復旧は別microSDへ戻すか、microSD boot partitionの
`cmdline.txt`へ`console=ttyAMA0,115200`、`config.txt`へ`enable_uart=1`を一時追加して行う。

生成後は`tools/buildroot_m6_verify.py --output build/artifacts/buildroot-m6-output`が必須binary、init、
永続設定seedと`sdcard.img`を検査する。既存releaseとの完全一致を確認するときだけ
`--expect-release-sha`を付ける。source revisionやfilesystem metadataが変わればSHAは変わり得るため、
通常buildでは機能artifact検証を合否にする。
さらに`tools/buildroot_m6_import_smoke.py`がtarget ARM PythonをQEMUで実行し、path compatibility、
Vial、logic companion、OLED/I2C、LEDの全importを確認する。`luma.core`/`luma.oled`はexternal
Buildroot packageとしてversion、source hash、MIT license hashを固定する。
