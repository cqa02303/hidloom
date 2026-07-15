# Fresh Raspberry Pi OS Install

この手順は Raspberry Pi OS 64-bit を HIDloom の通常運用へ導入するためのものです。
標準構成は、x86_64 build host で cross-build した `hidloom-core` と device profile の
split Debian package です。Raspberry Pi 実機では project binary を build しません。

Buildroot は別 microSD を使う offline appliance 実験です。Raspberry Pi OS の代替手順では
ありません。Buildroot M6 は [buildroot-fast-boot-experiment.md](docs/ops/buildroot-fast-boot-experiment.md)
を参照してください。

## 1. 前提

- Raspberry Pi OS 64-bit が起動する microSD
- package を作る x86_64 Linux build host
- 初期準備スクリプトと `.deb` を実機へ転送できる手段
- 復旧用として保持する、変更前の microSD または image backup

標準キーボードの profile は `keyboard-ver1` です。prototype は
`keyboard-ver0-prototype`、touch panel は該当する touch profile を選びます。

実機の username、hostname、IP address は環境ごとに異なります。この文書では
`<user>@<keyboard-ip>` と表記します。固定値を unit や script へ埋め込まないでください。

## 2. Build Host で検証・作成

clean な source revision で canonical validation を通します。

```bash
git status --short --branch
python3 script/test_validation_suite.py
git diff --check
```

標準キーボード用 package を作成します。

```bash
make core-deb-package
make keyboard-ver1-profile-deb
```

生成物は `build/packages/` に置かれます。core と profile は同じ source revision から
作り、Debian version が一致することを確認します。

```bash
CORE=$(ls -1t build/packages/hidloom-core_*_arm64.deb | head -n 1)
PROFILE=$(ls -1t build/packages/hidloom-profile-keyboard-ver1_*_arm64.deb | head -n 1)
CORE_VERSION=$(dpkg-deb -f "$CORE" Version)
PROFILE_VERSION=$(dpkg-deb -f "$PROFILE" Version)
printf 'core=%s\nprofile=%s\n' "$CORE_VERSION" "$PROFILE_VERSION"
test "$CORE_VERSION" = "$PROFILE_VERSION"
(cd build/packages && sha256sum -c "$(basename "$CORE").sha256")
(cd build/packages && sha256sum -c "$(basename "$PROFILE").sha256")
```

`make core-deb-package` と profile target は committed `HEAD` を package source とします。
未コミット差分を release package に含めないでください。

## 3. Fresh OS の Platform 準備

`--prepare-only` は Raspberry Pi OS の boot/module、device permission、console、logging、
Bluetooth policy を準備します。project binary の build、`/mnt/p3` runtime keymap の初期化、
repository checkout 由来の systemd unit install は行いません。

準備に必要な2ファイルだけを転送できます。

```bash
rsync -a --relative \
  setup_fresh_rpi.sh \
  system/install/setup_fresh_rpi.sh \
  <user>@<keyboard-ip>:~/hidloom-bootstrap/
ssh <user>@<keyboard-ip> \
  'cd ~/hidloom-bootstrap && sudo ./setup_fresh_rpi.sh --prepare-only'
```

既定では準備後に再起動します。package を転送済みで最後にまとめて再起動したい場合でも、
USB peripheral mode と I2C overlay が有効になる前に service を起動しないため、まず準備用の
再起動を完了する方法を推奨します。

準備内容の確認だけなら、先に help を表示できます。

```bash
./setup_fresh_rpi.sh --help
```

主な platform 設定:

- `dtoverlay=dwc2,dr_mode=peripheral`
- `dtparam=i2c_arm=on` と `i2c-dev`
- `dwc2`、`libcomposite`、`uinput` module
- `/dev/hidg*` の input group permission
- audio、desktop/server の不要 service 抑止
- persistent journal と hardware watchdog off
- NetworkManager を残した Wi-Fi recovery path

`--no-bluetooth` は Bluetooth を boot/runtime policy の両方で無効化します。
`--no-peripherals` は platform 準備時の OLED/LED 用追加 Python package を省略します。
最終的に有効にする daemon は device profile の service policy が正です。

## 4. Split Package を同時 Install

準備用再起動後、同じ version の core/profile package を転送します。

```bash
scp "$CORE" "$PROFILE" <user>@<keyboard-ip>:/tmp/
```

実機で2 package を同じ apt transaction に入れ、profile を明示適用します。

```bash
ssh <user>@<keyboard-ip> "sudo apt-get install -y \
  /tmp/$(basename "$CORE") \
  /tmp/$(basename "$PROFILE") && \
  sudo hidloom-profile keyboard-ver1 --apply --backup --restart"
```

profile package は immutable 定義を `/usr/share/hidloom/profiles/keyboard-ver1` へ置きます。
`hidloom-profile` が runtime keymap、layout、Vial definition、matrix/LED/I2C config を
`/mnt/p3` へ反映し、既存ファイルは `--backup` で退避します。

package の配置:

| Path | 内容 |
|---|---|
| `/usr/lib/hidloom` | package 管理の application/runtime source |
| `/lib/systemd/system` | package 管理の unit/timer |
| `/usr/share/hidloom/profiles` | device profile 定義 |
| `/var/lib/hidloom/package-manifest.json` | install package manifest |
| `/mnt/p3` | 実機固有の mutable runtime state |

## 5. 起動後の自動確認

package、profile、failed unit、主要 service を記録します。

```bash
dpkg-query -W 'hidloom-core' 'hidloom-profile-*'
cat /mnt/p3/device_profile.json
systemctl --failed --no-pager
systemctl is-active \
  hidloom-usb-gadget \
  hidloom-hidd \
  hidloom-uidd \
  hidloom-outputd \
  hidloom-logicd-core \
  logicd-companion \
  matrixd \
  i2cd \
  ledd
systemctl status hidloom-late-services.timer viald httpd btd --no-pager
ls -l /dev/hidg0 /dev/hidg1
test ! -e /dev/hidg2 || ls -l /dev/hidg2
test ! -e /dev/hidg4 || ls -l /dev/hidg4
```

late service timer は Vial、HTTP、Bluetooth を入力経路より後に起動します。直後に inactive でも、
timer と journal を確認してから失敗と判断してください。

health snapshot:

```bash
for path in \
  /run/hidloom/hidd-status.json \
  /run/hidloom/logicd-core-status.json \
  /run/hidloom/outputd-status.json; do
  test ! -r "$path" || cat "$path"
done
curl -k -u "admin:$(hostname)" https://127.0.0.1/api/status
journalctl -u hidloom-usb-gadget -u hidloom-hidd \
  -u hidloom-logicd-core -u logicd-companion -u matrixd \
  -u viald -u i2cd -u ledd -b --no-pager -p warning
```

## 6. 実機で確認する項目

- Host が keyboard / Raw HID interface を enumerate する
- JIS key と modifier を含む物理 matrix 入力が正しい
- Vial client が接続し、変更が再起動後も保持される
- OLED が `booting` から runtime status 表示へ進む
- LED が boot effect から通常 effect へ進む
- analog stick と shutdown key が機能する
- output target を変更した試験後、`hidloom-outputd` が `auto` に戻る

起動経路を変更した場合、total boot time ではなく `input-ready`、`keyboard_ready`、
`usb->input` を記録します。実機 checklist は
private workspace reference *(omitted from public export)* を使います。

## 7. Rollback

- 変更前の Raspberry Pi OS microSD をそのまま保持する
- package downgrade/restore は core と profile を同じ version で同時に行う
- profile 再適用時は `--backup` を付ける
- `/mnt/p3` の backup を確認してから runtime state を戻す
- test で output target を変更した場合は `auto` へ戻して status を再確認する

既存 checkout の rsync deploy、`/opt` release、pre-.deb layout は legacy/recovery/比較用です。
通常の fresh install や更新には使いません。詳細は
[release-packaging-runbook.md](docs/ops/release-packaging-runbook.md) を正とします。

## Legacy Checkout Bootstrap

`sudo ./setup_fresh_rpi.sh` は repository checkout を実機で build し、checkout path から
unit を install する旧 bootstrap を互換・復旧用に残しています。Raspberry Pi での native build、
package 管理外 unit、runtime state の上書きを伴うため、標準導入では実行しません。
