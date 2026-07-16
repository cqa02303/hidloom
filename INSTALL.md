# HIDloom Installation Options

HIDloom は、同じ公開 Release から次の 2 方式を選んで導入できます。
通常の開発・更新やネットワーク管理を重視する場合は Raspberry Pi OS、電源投入から
キーボードとして使えるまでの短さを重視する場合は Buildroot M6 を選びます。

| 項目 | Raspberry Pi OS + split package | Buildroot M6 image |
|---|---|---|
| 主な用途 | 通常運用、開発、機能追加 | 高速起動する専用 keyboard appliance |
| 導入方法 | fresh 64-bit OS に 2 個の `.deb` を同時 install | image を専用 microSD に書き込み |
| 更新方法 | package 更新と profile 再適用 | image を再生成して書き換え |
| ネットワーク | Raspberry Pi OS 側で利用可能 | offline。Wi-Fi、SSH、httpd は含まない |
| キーマップ | Vial、HTTP UI、runtime keymap | USB Raw HID 経由の Vial |
| 復旧 | package rollback または OS backup | Raspberry Pi OS の microSD に差し替え |

## Release Assets

公開 Release では、少なくとも次の asset を確認します。

- `SHA256SUMS`
- `hidloom-core_<version>_arm64.deb`
- `hidloom-profile-keyboard-ver1_<version>_arm64.deb`
- `hidloom-<version>-buildroot-m6.img.zst`
- 対応 source と Buildroot compliance archive

download 後は、同じ directory で checksum を検証します。

```bash
sha256sum -c SHA256SUMS
```

## Option A: Raspberry Pi OS Package

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
