# Raspberry Pi Zero 2 W Keyboard Package and M6 Image

Raspberry Pi Zero 2 Wと`cqa02303v5` keyboard hardwareでHIDloomを試すための
binary配布・導入ページです。同じ公開sourceから、通常運用向けRaspberry Pi OS packageと
高速起動向けBuildroot M6 imageを作成します。Raspberry Pi 4 touch kioskは
[Touch Panel Package](raspberry-pi-4-touch-panel-package.md)を選びます。

## 二つの導入方式

| 方式 | 適した用途 | Network / UI | 更新方法 |
|---|---|---|---|
| Raspberry Pi OS package | 開発、設定変更、Wi-Fi、SSH、HTTP UI | Wi-Fi、SSH、Vial、HTTP UI | 同じversionのcore/profileを同時install |
| Buildroot M6 image | USB接続後すぐ使うoffline keyboard appliance | USB HID、USB Raw HID/Vial、local console | 専用microSDを書き換え |

M6はWi-Fi、SSH、httpdを含みません。Raspberry Pi OS microSDを上書きせず、別のmicroSDを
M6専用にすると確実にrollbackできます。

## Releaseを選ぶ

[HIDloom Releases](https://github.com/cqa02303/hidloom/releases)から、説明に
`keyboard-ver1`と`Buildroot M6`が書かれたprereleaseまたはstable releaseを選びます。
`RELEASE_MANIFEST.json`の`publication.ready`が`true`でなく、keyboardの`hardware_smoke`が
`pass`でない候補は公開配布用ではありません。touch profileを含むReleaseでは
`touch_hardware_smoke`も`pass`で、正のtouch-ready時間が必要です。
keyboardの`hardware_smoke`はRaspberry Pi OS packageと、同じReleaseに含まれるexact M6 imageの
両方をpassした時だけ設定する集約結果です。`usable_keyboard_seconds`はM6 imageで測定します。

同じReleaseから次をdownloadします。

- `hidloom-core_<version>_arm64.deb`
- `hidloom-profile-keyboard-ver1_<version>_arm64.deb`
- `hidloom-profile-touch-waveshare-8.8_<version>_arm64.deb`（Raspberry Pi 4 touch用）
- `hidloom-<release>-buildroot-m6.img.zst`
- `hidloom-<release>-source.tar.zst`
- `hidloom-<release>-buildroot-compliance.tar.zst`
- `SHA256SUMS`

一つのRelease pageと`SHA256SUMS`にZero 2 W package、M6 image、Raspberry Pi 4 touch profileを
並べるため、用途に必要なassetだけを選べます。core packageは両Raspberry Pi OS構成で共通ですが、
公開gateはkeyboardとtouch panelの実機smokeを別々に要求します。

downloadしたdirectoryで全assetを検証します。

```bash
sha256sum -c SHA256SUMS
```

## Raspberry Pi OS packageを使う

Raspberry Pi ImagerでRaspberry Pi OS Lite 64-bitをmicroSDへ書き込み、Wi-FiとSSHを設定します。
source archiveを展開し、Raspberry Pi上でproject binaryをbuildせず、OS依存packageとservice
policyだけを準備します。

```bash
tar --zstd -xf hidloom-<release>-source.tar.zst
cd hidloom-<release>
sudo ./setup_fresh_rpi.sh --prepare-only
sudo reboot
```

再起動後、完全に同じversionのcore/profileを同じapt transactionでinstallし、profileを適用します。

```bash
sudo apt-get install -y \
  ./hidloom-core_<version>_arm64.deb \
  ./hidloom-profile-keyboard-ver1_<version>_arm64.deb
sudo hidloom-profile keyboard-ver1 --apply --backup --restart
```

package、profile、service、USB outputを確認します。

```bash
dpkg-query -W 'hidloom-core' 'hidloom-profile-keyboard-ver1'
cat /mnt/p3/device_profile.json
systemctl --failed --no-pager
systemctl is-active hidloom-usb-gadget hidloom-hidd hidloom-outputd \
  hidloom-logicd-core logicd-companion matrixd i2cd ledd viald httpd
cat /run/hidloom/outputd-status.json
```

host PCで文字入力、JP変換/無変換、US sub key、LT tap/hold、Vial認識、keymap保存、
Matrix Tester、OLED、LED、analog stickを確認します。

## Buildroot M6 imageを使う

M6用の別microSDを用意し、imageを展開します。

```bash
zstd -d hidloom-<release>-buildroot-m6.img.zst
```

Raspberry Pi Imagerの **Use custom** で展開後の`.img`を選び、Raspberry Pi Zero 2 W用microSDへ
書き込みます。電源を切ってmicroSDを交換し、HDMIは必要な場合だけ接続します。

M6の境界は次のとおりです。

- boot sourceはmicroSDのみ
- boot splashとserial consoleは無効
- maintenance HDMIは1920x1080固定
- Wi-Fi、SSH、httpdは非搭載
- VialはUSB Raw HID経由
- local console初期accountは`pi` / `pi`

USB接続からhost PCへ通常キー入力が届くまでの秒数を記録し、次を確認します。

1. 初回接続とUSB再接続でCtrlやmodifierが固着しない。
2. JP変換/無変換、US sub key、LT tap/holdが動作する。
3. Vialでkeymap読込、1キー変更、再起動後保持、Matrix Tester、LED effect変更ができる。
4. OLED、LED、analog stickが動作する。
5. F11でUSBからPi consoleへ切り替わり、OLED表示も変わる。
6. `pi` / `pi`でloginし、passwordがechoされず、`sudo -v`が成功する。
7. USBへ戻した後にhost入力が復帰し、shutdown keyで正常停止する。

## 更新とrollback

Raspberry Pi OSは以前の同一version core/profile setを同じtransactionで再installし、profileを
再適用します。M6はpackage単位で更新せず、新しい検証済みimageを別microSDへ書き込みます。
問題があれば保存しておいたRaspberry Pi OS microSDへ戻します。
