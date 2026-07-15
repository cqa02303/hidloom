# Package / device profile split plan

更新日: 2026-07-06

この文書は runtime core と keyboard / device profile を分離した時の計画と完了条件を残す。
2026-07-06 時点では、`hidloom-core` と device profile package への分離は
`-01` / `-02` の `keyboard-ver1`、`-40` の `touch-waveshare-8.8` で実機確認済み。
通常運用では core package と profile package を同じ version で同時に install し、
`hidloom-profile <profile> --apply --backup --restart` で `/mnt/p3` の runtime 定義と
systemd service policy を反映する。

M3 の「single package のまま runtime apply」は実装前段階の検討としては残すが、
現在の本線では superseded。以後の作業は split package 前提で扱う。

## 背景

旧 single package は daemon / native binary / default config / board config / touch-panel config を
ひとつの `hidloom` payload にまとめていた。
標準キーボードの `-01` / `-02` では一時的にこれで運用できたが、`-40` は次の差分を持つ。

- touch-panel-only input で `matrixd` を使わない。
- `480x1920` display の `waveshare-8.8` profile を使う。
- `/mnt/p3/keymap.json` / `keyboard-layout.json` / `vial.json` / `flick.json` を
  touch-panel profile から展開する必要がある。
- `logicd.service`、`httpd.service`、`viald.service`、kiosk browser を維持する一方で、
  standard keyboard の native core / matrix / LED / OLED policy とは異なる。
- 既存の `/etc/systemd/system` unit が package unit を shadow している場合がある。

そのため、core package を入れることと、実機の入力定義 / service policy を選ぶことを分ける。

## Package model

### Core package

候補名:

```text
hidloom-core
```

責務:

- daemon source と Python modules
- native binaries
- shared helper commands
- common systemd unit templates
- HTTP / Vial / OLED / LED / Bluetooth / HID broker implementation
- default scripts
- man pages and package manifest

配置:

```text
/usr/lib/hidloom/
/lib/systemd/system/
/usr/share/man/
/var/lib/hidloom/package-manifest.json
```

core package は `/mnt/p3/keymap.json` などの mutable runtime definition を
勝手に上書きしない。欠けている default script の初期コピーだけは既存方針どおり許可する。

### Profile packages

候補名:

```text
hidloom-profile-keyboard-ver1
hidloom-profile-keyboard-ver0-prototype
hidloom-profile-touch-waveshare-8.8
hidloom-profile-touch-osoyoo-4.3
```

責務:

- `keymap.json`
- `keyboard-layout.json`
- `vial.json`
- `matrixd.json` if matrix scan exists
- `ledd.json` / `i2cd.json` if the profile owns those peripherals
- `flick.json` for touch-panel profiles
- profile metadata
- service policy

配置案:

```text
/usr/share/hidloom/profiles/<profile-id>/
  profile.json
  runtime/
    keymap.json
    keyboard-layout.json
    vial.json
    flick.json
  config/
    matrixd.json
    ledd.json
    i2cd.json
```

profile package は install だけで `/mnt/p3` を無条件に上書きしない。
apply command により、backup を作ってから runtime definition と unit policy を反映する。
first slice の profile package は core package の exact version に依存するため、
core と profile の `.deb` は同じ version で同時に apt install する。

## Profile metadata

`profile.json` は machine-readable な最小 schema にする。

```json
{
  "schema": "cqa02303v5.device-profile.v1",
  "id": "touch-waveshare-8.8",
  "label": "Touch panel Waveshare 8.8",
  "kind": "touch-panel",
  "display": {
    "match": ["1920x480", "480x1920"],
    "default_orientation": "portrait"
  },
  "runtime_files": [
    "keymap.json",
    "keyboard-layout.json",
    "vial.json",
    "flick.json"
  ],
  "services": {
    "enable": [
      "hidloom-usb-gadget.service",
      "hidloom-hidd.service",
      "logicd.service",
      "httpd.service",
      "viald.service"
    ],
    "disable": [
      "matrixd.service",
      "hidloom-logicd-core.service",
      "logicd-companion.service",
      "hidloom-outputd.service",
      "hidloom-uidd.service",
      "i2cd.service",
      "ledd.service",
      "usbd.service",
      "btd.service"
    ]
  },
  "dropins": {
    "logicd.service": {
      "LOGICD_MATRIX_ROWS": "16",
      "LOGICD_MATRIX_COLS": "16",
      "LOGICD_OUTPUTS": "auto"
    }
  }
}
```

この schema は初期案であり、first slice では validation と dry-run だけでよい。

## Apply command

候補 command:

```bash
sudo hidloom-profile apply touch-waveshare-8.8 --dry-run
sudo hidloom-profile apply touch-waveshare-8.8 --backup --restart
```

first implementation では既存 Python helper を拡張してもよい。

候補:

```text
script/apply_device_profile.py
```

責務:

- installed profile 一覧を出す。
- `/mnt/p3/device_profile.json` に選択結果を記録する。
- runtime files を `/mnt/p3` へ展開する。
- 既存 runtime files は timestamp 付き backup を作る。
- profile metadata の service policy を dry-run 表示する。
- non-dry-run では enable / disable / drop-in 生成 / daemon-reload / optional restart を行う。
- `/etc/systemd/system` の legacy unit shadow がある場合は警告し、package unit への移行手順を表示する。

`apply_board_profile.py` は物理基板 wiring 差分の既存入口として維持し、
device profile は package / runtime / service policy の上位概念として扱う。
将来統合する場合も、first slice では互換を壊さない。

## Migration plan

### M0: documentation and static guards

- この設計文書を追加する。
- `TODO_PRIORITY.md` と `CURRENT_STATUS.md` から参照する。
- package runbook に core/profile split の方針を追記する。
- docs link tests を通す。

### M1: profile inventory helper

- `config/default` / `config/boards` / `config/default/touch-panel` から
  profile candidate を列挙する read-only helper を追加する。
- `touch-waveshare-8.8` と `touch-osoyoo-4.3` の `profile.json` first draft を追加する。
- `script/test_device_profile_inventory.py` で id、required files、service policy を固定する。
- first slice として `config/device-profiles/*.json` と
  `script/device_profile_inventory.py` を追加済み。ここでは `/mnt/p3` や systemd へは
  まだ書き込まず、M2 の dry-run apply で変更計画を表示する。

### M2: dry-run apply

- `script/apply_device_profile.py --list` と `--dry-run` を追加する。
- `/mnt/p3` 書き込みなしで、copy plan、backup plan、service enable / disable plan を表示する。
- `<keyboard-host>` に対して dry-run し、現行 `/etc/systemd/system` shadow と
  touch-panel runtime 不足を検出できることを確認する。
- 2026-07-05 に `hidloom-profile touch-waveshare-8.8 --dry-run --backup --restart` で確認済み。

### M3: runtime apply without package split

Status: superseded by M4 split package implementation.

- 現行 single package のまま、installed `/usr/lib/hidloom` から
  `touch-waveshare-8.8` profile を `/mnt/p3` へ展開できるようにする。
- `httpd` / `viald` / `logicd` を維持し、`matrixd` / LED / OLED など不要 service を
  profile policy に沿って止める。
- `-40` で package install + device profile apply + smoke を通す。
- 2026-07-05 に separated core/profile package 上で実施済み。不要 native keyboard chain は
  `systemctl mask` で reboot 後も active へ戻らないようにした。

### M4: package split

Status: implemented.

- `hidloom-core` と profile packages を build できるようにする。
- profile package は `Depends: hidloom-core (= same version)` または
  compatible version range を持つ。
- release candidate gate に core/profile package contents check を追加する。
- `-01` / `-02` は `keyboard-ver1`、`-40` は `touch-waveshare-8.8` で確認する。
- 2026-07-05 に first target として `hidloom-core`
  `0.0.1782+git40d214b` と
  `hidloom-profile-touch-waveshare-8.8`
  `0.0.1782+git40d214b` を build し、`-40` で install / apply / reboot smoke を通した。
  core だけを先に更新すると apt が mismatch profile package を remove 対象にするため、
  core/profile は同じ version で同時に install する運用にする。
- 2026-07-05 に `tools/package/release_candidate_check.sh --split-profile touch-waveshare-8.8`
  を追加し、core/profile package contents、sha256、exact version dependency、
  retired checkout path 混入なしを local candidate gate で確認できるようにした。
  `0.0.1784+gitc0b40f16` で build 付き split gate が通過済み。
- `keyboard-ver1` / `keyboard-ver0-prototype` profile package も `0.0.1784+gitc0b40f16`
  artifact で build と split gate が通過済み。
- 2026-07-06 時点で `-01` / `-02` は `keyboard-ver1`
  `0.0.1797+git8ace528d`、`-40` は `touch-waveshare-8.8`
  `0.0.1796+gitdfe0fc5d` で install / apply / reboot smoke 済み。
- 2026-07-05 に standard keyboard `-02` を split package 構成へ移行する前提として、
  `hidloom-core` は legacy single package `hidloom` に対する
  `Replaces` / `Conflicts` を持つようにした。これにより `/usr/lib/hidloom`
  配下を旧 package と共存させず、core + profile の構造へ apt で置換する。

### M5: stable migration

Status: partially complete; package structure is validated, release publication policy remains separate.

- legacy `hidloom` package は transitional package にするか、core package の alias として扱う。
- release runbook に標準キーボードと touch-panel の install / rollback 手順を分けて記録する。
- GitHub Release note に tested profile matrix を記載する。

## Acceptance criteria

- Standard keyboard `-01` / `-02` は package unit root `/usr/lib/hidloom` で従来どおり起動する。
- Touch-panel `-40` は current package root と selected profile だけで runtime definition を再構築できる。
- Profile apply は dry-run で copy / backup / service changes をすべて表示する。
- Non-dry-run は `/mnt/p3` の既存 runtime files を backup してから変更する。
- Package unit shadow がある場合は検出し、意図せず古い checkout から起動しない。
- `script/test_real_device_touch_panel_suite.py` と package smoke が通る。
- Release note には tested device profile を明記する。

## Current status on <keyboard-host>

2026-07-05 時点の確認:

- SSH target は local discovery で確認済み。実 IP は docs に固定しない。
- Debian 13 trixie / `aarch64`。
- display は `480x1920` で、auto selection は `waveshare-8.8`。
- current `.deb` は apt dry-run install 可能。
- current `.deb` には touch-panel profile files と `select_touch_panel_profile.py` が含まれる。
- current `.deb` install だけでは `/mnt/p3/keymap.json` などは展開されない。
- existing `/etc/systemd/system` units が package units を shadow する。
- kiosk browser と `httpd` / `viald` / `logicd` は旧 checkout unit 由来で起動中。

このため、`-40` を package layout へ移行する前に M1-M3 を実装する。
