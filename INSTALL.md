# HIDloom Installation Options

HIDloom は、同じ公開 Release から2種類のOSと3つの構成を選んで導入できます。
通常のキーボードとタッチパネルkioskは Raspberry Pi OS、電源投入からキーボードとして
使えるまでの短さを重視する場合は Buildroot M6 を選びます。

| 構成 | 対象 | 導入方法 | ネットワーク/UI |
|---|---|---|---|
| Raspberry Pi OS Keyboard | Raspberry Pi Zero 2 W + keyboard hardware | fresh 64-bit OS にcoreと`keyboard-ver1` profileを同時install | Wi-Fi、SSH、Vial、HTTP UI |
| Raspberry Pi OS Touch Panel | Raspberry Pi 4 + Waveshare 8.8inch DSI touch display | fresh Desktop 64-bit OS にcoreと`touch-waveshare-8.8` profileを同時install | Wi-Fi、SSH、Vial、touch kiosk HTTP UI |
| Buildroot M6 image | Raspberry Pi Zero 2 W + keyboard hardware | imageを専用microSDに書き込み | offline。USB Raw HID経由のVialのみ |

Raspberry Pi OS構成はpackage更新とprofile再適用で更新し、package rollbackまたはOS backupで
復旧します。Buildroot M6はimageを再生成して書き換え、保存しておいたRaspberry Pi OSの
microSDへ差し替えて復旧します。

## Release Assets

公開 Release では、少なくとも次の asset を確認します。

- `SHA256SUMS`
- `hidloom-core_<version>_arm64.deb`
- `hidloom-profile-keyboard-ver1_<version>_arm64.deb`
- `hidloom-profile-touch-waveshare-8.8_<version>_arm64.deb`
- `hidloom-<version>-buildroot-m6.img.zst`
- 対応 source と Buildroot compliance archive

download 後は、同じ directory で checksum を検証します。

```bash
sha256sum -c SHA256SUMS
```

## Option A1: Raspberry Pi OS Keyboard Package

Releaseからのdownload、Raspberry Pi OS package、Buildroot M6の書き込みを一つの手順で見る場合は
[Raspberry Pi Zero 2 W Keyboard Package and M6 Image](docs/hardware/raspberry-pi-zero-2-w-keyboard-release.md)
を参照してください。

Raspberry Pi OS 64-bit の fresh install を起動し、対象 Release の source checkout または
source archive で platform preparation を実行します。Raspberry Pi 上では project binary を
build しません。

```bash
sudo ./setup_fresh_rpi.sh --prepare-only
```

再起動後、同じ Release・同じ version の core と keyboard profile を、必ず同じ apt
transaction で install します。

```bash
sudo apt-get install -y \
  ./hidloom-core_<version>_arm64.deb \
  ./hidloom-profile-keyboard-ver1_<version>_arm64.deb
sudo hidloom-profile keyboard-ver1 --apply --backup --restart
```

GitHub CLI とこの source tree がある場合は、download、checksum、package metadata、version
整合を helper で検証できます。

```bash
tools/package/install_github_release_deb.sh \
  --repository cqa02303/hidloom \
  --tag <tag> \
  --profile keyboard-ver1
```

実機固有の準備、依存 package、health check、rollback は
[FRESH_INSTALL.md](FRESH_INSTALL.md) を参照してください。

## Option A2: Raspberry Pi OS Touch Panel Package

Releaseからのdownloadを含む最短手順は
[Raspberry Pi 4 Touch Panel Package](docs/hardware/raspberry-pi-4-touch-panel-package.md)を参照してください。

タッチパネル構成は Raspberry Pi 4、
[Waveshare 8.8inch DSI Capacitive Touch Display](https://www.waveshare.com/8.8-dsi-touch-a.htm)、
Raspberry Pi OS Desktop 64-bit、Chromiumを使います。ケーブルや電源を含む一覧は
[Touch Panel Modeの必要パーツ](docs/hardware/touch-panel-vial-layout-notes.md#touch-panel-modeの必要パーツ)
を参照してください。Buildroot M6 imageはタッチパネルkiosk用ではありません。

fresh OSではDesktopの自動ログインを有効にします。platform準備でDesktop serviceを残し、
物理matrix、Bluetooth、OLED/LED daemonを使わないtouch-panel-only policyを選びます。

```bash
sudo env HIDLOOM_KEEP_DESKTOP=1 \
  ./setup_fresh_rpi.sh --prepare-only --touch-panel-only
```

準備用再起動後、同じRelease・同じversionのcoreとtouch profileを同じapt transactionで
installし、profileを適用します。

```bash
sudo apt-get install -y \
  ./hidloom-core_<version>_arm64.deb \
  ./hidloom-profile-touch-waveshare-8.8_<version>_arm64.deb
sudo hidloom-profile touch-waveshare-8.8 --apply --backup --restart
```

Desktopへログインする一般ユーザーで、検証済みのWaveshare 8.8inch用kiosk autostartを作ります。

```bash
mkdir -p "$HOME/.config/autostart"
cat >"$HOME/.config/autostart/hidloom-touch-panel-browser.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=HIDloom Touch Panel Browser
Comment=Open the local HIDloom Web UI in fullscreen after the desktop starts
Exec=env HIDLOOM_TOUCH_PANEL_REMOTE_DEBUGGING_PORT=9222 HIDLOOM_TOUCH_PANEL_PROFILE=waveshare-8.8 HIDLOOM_TOUCH_PANEL_SIZE=1920x480 HIDLOOM_TOUCH_PANEL_OUTPUT=DSI-1 HIDLOOM_TOUCH_PANEL_OUTPUT_TRANSFORM=270 HIDLOOM_TOUCH_PANEL_WINDOW_SIZE=1920x480 /usr/lib/hidloom/script/start_touch_panel_browser.sh
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
sudo reboot
```

再起動後にprofile、service、Goodix touch device、kiosk DOMを確認します。

```bash
dpkg-query -W 'hidloom-core' 'hidloom-profile-touch-waveshare-8.8'
cat /mnt/p3/device_profile.json
systemctl --failed --no-pager
systemctl is-active hidloom-usb-gadget hidloom-hidd logicd httpd viald
grep -A8 -i Goodix /proc/bus/input/devices
python3 /usr/lib/hidloom/tools/touch_kiosk_health_probe.py --require-ready
```

GitHub Releaseからbuild host経由で導入する場合は、keyboard profileの代わりに
`--profile touch-waveshare-8.8`を指定できます。

```bash
tools/package/install_github_release_deb.sh \
  --repository cqa02303/hidloom \
  --tag <tag> \
  --profile touch-waveshare-8.8 \
  --host <user>@<touch-panel-ip> \
  --install --apt
```

## Option B: Buildroot M6 Image

Raspberry Pi Imager の **Use custom** で展開後の image を専用 microSD に書き込みます。

```bash
zstd -d hidloom-<version>-buildroot-m6.img.zst
```

Buildroot M6 は Wi-Fi、SSH、httpd を含まない offline appliance です。Vial は USB Raw HID
経由で使います。maintenance HDMI は 1920x1080 固定で、初期 local console credential は
`pi` / `pi` です。長期利用前に password を変更してください。

既存の Raspberry Pi OS microSD は上書きせず、rollback path として保持します。image の
再現 build と実機確認項目は
[Buildroot Fast Boot Experiment](docs/ops/buildroot-fast-boot-experiment.md) を参照してください。

## Source Rebuild

両方式の package、image、対応 source を同じ revision から再生成する手順は
[Public Source Rebuild Runbook](docs/ops/public-source-rebuild-runbook.md) にあります。

touch-panel向けの配布assetとRelease説明を再生成する入口は次です。

```bash
tools/public_build_rehearsal.sh --package --profile touch-waveshare-8.8
tools/package/build_touch_panel_release.sh
```

Zero 2 W向けkeyboard packageとM6 imageを同じdirectoryへまとめる入口は次です。

```bash
tools/public_build_rehearsal.sh --all --profile keyboard-ver1
tools/package/build_zero2w_keyboard_release.sh
```

同じGitHub Releaseへtouch profileも並べる最終候補では、同じsourceからtouch package setも作り、
一つの`SHA256SUMS`へ統合します。

```bash
OUT_DIR=build/public-touch-rebuild \
  tools/public_build_rehearsal.sh --package --profile touch-waveshare-8.8
tools/package/build_zero2w_keyboard_release.sh \
  --touch-package-dir build/public-touch-rebuild \
  --touch-provenance build/public-touch-rebuild/PUBLIC_BUILD_PROVENANCE.json
```
