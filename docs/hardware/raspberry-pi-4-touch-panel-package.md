# Raspberry Pi 4 Touch Panel Package

Raspberry Pi 4とWaveshare 8.8inch DSI touch displayでHIDloomのtouch kioskを試すための
binary package配布・導入ページです。Buildroot M6 imageではなく、Raspberry Pi OS Desktop
64-bitへ同じversionの`hidloom-core`と`touch-waveshare-8.8` profileを導入します。
Raspberry Pi Zero 2 W keyboardまたはM6 imageは
[Keyboard Package and M6 Image](raspberry-pi-zero-2-w-keyboard-release.md)を選びます。

## 対象ハードウェア

- Raspberry Pi 4 Model B
- [Waveshare 8.8inch DSI Capacitive Touch Display](https://www.waveshare.com/8.8-dsi-touch-a.htm)
- Raspberry Pi 4とdisplayに必要な電源、DSI cable、microSD
- USB HID deviceとして接続するhost PC

panel、cable、電源を含む詳細は
[Touch Panel Modeの必要パーツ](touch-panel-vial-layout-notes.md#touch-panel-modeの必要パーツ)
を参照してください。

## Releaseを選ぶ

[HIDloom Releases](https://github.com/cqa02303/hidloom/releases)から、説明に
`touch-waveshare-8.8`と書かれたprereleaseまたはstable releaseを選びます。
`RELEASE_MANIFEST.json`またはtouch単体候補の`PACKAGE_RELEASE_MANIFEST.json`で
`release_channels.selected=stable-public`かつ`selected_ready=true`でない候補は公開配布用ではありません。統合Releaseではさらに
`touch_hardware_smoke.status=pass`と正の`touch_ready_seconds`を確認します。USB VID/PIDの正式割当前に
作成した内部preview packageは配布しません。

次のassetを同じdirectoryへdownloadします。

- `hidloom-core_<version>_arm64.deb`
- `hidloom-profile-touch-waveshare-8.8_<version>_arm64.deb`
- `hidloom-<version>-source.tar.zst`
- `SHA256SUMS`

`core`と`profile`の`<version>`は完全に同じものを選びます。

```bash
sha256sum -c SHA256SUMS
```

## Fresh OSを準備する

Raspberry Pi ImagerでRaspberry Pi OS Desktop 64-bitをmicroSDへ書き込み、Desktopの自動login、
network、SSHを設定します。source archiveを展開し、project binaryをRaspberry Pi上でbuildせず、
OS側の依存packageとservice policyだけを準備します。

```bash
tar --zstd -xf hidloom-<version>-source.tar.zst
cd hidloom-<version>-source
sudo env HIDLOOM_KEEP_DESKTOP=1 \
  ./setup_fresh_rpi.sh --prepare-only --touch-panel-only
```

準備完了後に一度rebootします。

## Binary packageを導入する

二つのpackageを必ず同じapt transactionでinstallし、profileを適用します。

```bash
sudo apt-get install -y \
  ./hidloom-core_<version>_arm64.deb \
  ./hidloom-profile-touch-waveshare-8.8_<version>_arm64.deb
sudo hidloom-profile touch-waveshare-8.8 --apply --backup --restart
```

## Touch kioskを自動起動する

Desktopへloginする一般userでautostart entryを作成します。

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

## 動作確認

reboot後、画面表示とtouch操作が可能になるまでの時間を記録し、package、profile、service、
Goodix touch device、kiosk DOMを確認します。

```bash
dpkg-query -W 'hidloom-core' 'hidloom-profile-touch-waveshare-8.8'
cat /mnt/p3/device_profile.json
systemctl --failed --no-pager
systemctl is-active hidloom-usb-gadget hidloom-hidd logicd httpd viald
grep -A8 -i Goodix /proc/bus/input/devices
python3 /usr/lib/hidloom/tools/touch_kiosk_health_probe.py --require-ready
```

host PCでUSB keyboard入力、Vial認識、keymap保存も確認します。失敗時は
`journalctl -u hidloom-usb-gadget -u hidloom-hidd -u logicd -u httpd -u viald -b --no-pager`
を保存します。

## 更新とrollback

更新時も同じversionのcore/profileを同じtransactionでinstallし、profileを再適用します。
試用前のmicroSD imageを保存しておく方法が最も確実なrollbackです。package単位で戻す場合は、
以前の同version setを再installしてからprofileを再適用します。
