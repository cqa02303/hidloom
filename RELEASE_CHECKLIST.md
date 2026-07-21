# Release Checklist

HIDloom の source、Raspberry Pi OS split package、Buildroot M6、public release を同じ
revision から作るための checklist です。該当しない section は release notes に
`not applicable` と理由を記録します。

利用者向けの 2 方式と asset 契約は [INSTALL.md](INSTALL.md) を基準にします。

## 1. Source Revision

- [ ] 変更目的と scope が説明できる
- [ ] `git status --short --branch` が clean
- [ ] 意図しない generated file、cache、credential、実機固有値がない
- [ ] tracked/public pathにWindows予約名、禁止文字、casefold衝突、long pathがない
- [ ] tracked/public textがUTF-8 BOMなし、LF、final newlineあり、末尾空白なしで、全`*.sh`が実行可能になっている
- [ ] merge marker、debug hook、placeholder macro、名称移行由来の自己fallback/重複文がない
- [ ] ignored build/bin出力にretired software名の実行物がなく、deploy対象がcanonical fileへ限定されている
- [ ] source領域のignored cache/bytecode/editor一時物がなく、build・venv・operator stateをcleanup対象にしていない
- [ ] local `.env`が0600かつcanonical `HIDLOOM_*`名だけを使い、値がlog/reportへ出ていない
- [ ] local key migrationが必要な場合はdry-runを確認し、collisionなし・明示token・backupなしのatomic rewriteだけを使った
- [ ] release 対象 commit SHA を記録した
- [ ] release version が`config/project-identity.json`の初回版またはその後継として説明できる
- [ ] rollback 対象の直前 package/image を保持した

```bash
git status --short --branch
git diff --check
git log --oneline -8
python3 tools/repository_hygiene.py
python3 tools/source_syntax_hygiene.py
python3 tools/development_residue_hygiene.py
python3 tools/generated_binary_hygiene.py
python3 tools/workspace_debris_hygiene.py
python3 tools/local_environment_hygiene.py
python3 tools/local_environment_hygiene.py --rewrite-retired-keys
python3 tools/public_community_health.py
python3 tools/pid_codes_application.py
```

## 2. Host-side Validation

Raspberry Pi では build/test の重い処理を実行せず、x86_64 build host で行います。

- [ ] canonical validation が pass
- [ ] tracked source 7形式のsyntax gateがpass
- [ ] tracked development residue gateがprivate/public inventoryの双方でpass
- [ ] issue/PR/security contribution導線とprivate export trigger coverageがpass
- [ ] tracked generated artifact が canonical input と一致
- [ ] 4つの Rust crate が locked dependency で pass
- [ ] test 後も worktree が clean

```bash
python3 script/test_validation_suite.py
make generated-artifact-check
for manifest in \
  tools/hidloom_hidd/Cargo.toml \
  tools/hidloom_uidd/Cargo.toml \
  tools/hidloom_outputd/Cargo.toml \
  tools/hidloom_logicd_core/Cargo.toml; do
  cargo test --locked --manifest-path "$manifest"
done
git diff --check
git status --short
```

## 3. Split Debian Package

- [ ] `hidloom-core` と device profile を同じ source revision から作成
- [ ] core/profile の version と architecture が一致
- [ ] public bundle の `SHA256SUMS` が core/profile の両方を検証
- [ ] core/profile を同じ apt transaction で install する release notes になっている
- [ ] `hidloom-profile <profile> --apply --backup --restart` を明記
- [ ] Release notes が Raspberry Pi OS package と Buildroot M6 image の選択肢を明記

標準キーボード:

```bash
tools/package/release_candidate_check.sh --split-profile keyboard-ver1
```

release candidate check は clean tree、validation、cross-build、package metadata、contents、
checksum を確認します。通常更新では checkout rsync、`/opt` release、pre-.deb rehearsal を
使いません。

## 4. Fresh Raspberry Pi OS

- [ ] [FRESH_INSTALL.md](FRESH_INSTALL.md) の `--prepare-only` で platform を準備
- [ ] project binary を実機で build していない
- [ ] package unit が `/lib/systemd/system` から読み込まれる
- [ ] `/etc/systemd/system` に旧 checkout unit shadow がない
- [ ] `/mnt/p3/device_profile.json` が対象 profile
- [ ] `systemctl --failed` が空、または既知の無関係 failure のみ

```bash
dpkg-query -W 'hidloom-core' 'hidloom-profile-*'
cat /mnt/p3/device_profile.json
systemctl --failed --no-pager
systemctl show -p FragmentPath \
  hidloom-hidd hidloom-uidd hidloom-outputd hidloom-logicd-core \
  logicd-companion matrixd i2cd ledd viald
```

`spid.service` は PAW sensor 搭載前提ではないため、default enable/active を必須にしません。

## 5. Native Input Path

- [ ] required service が active
- [ ] `hidloom-hidd`、`logicd-core`、`outputd` status JSON が更新される
- [ ] `/dev/hidg0` multi-report と `/dev/hidg1` Raw HID/Vial が存在
- [ ] optional `/dev/hidg2` US sub と `/dev/hidg4` Windows IME は profile と一致
- [ ] Host USB enumerate 後に usable keyboard になる
- [ ] JIS key、modifier、LT、layer、analog stick routing が正しい

```bash
systemctl is-active \
  hidloom-usb-gadget \
  hidloom-hidd \
  hidloom-uidd \
  hidloom-outputd \
  hidloom-logicd-core \
  logicd-companion \
  matrixd
ls -l /dev/hidg0 /dev/hidg1
test ! -e /dev/hidg2 || ls -l /dev/hidg2
test ! -e /dev/hidg4 || ls -l /dev/hidg4
cat /run/hidloom/hidd-status.json
cat /run/hidloom/logicd-core-status.json
cat /run/hidloom/outputd-status.json
```

起動時間は `systemd-analyze` total ではなく、`input-ready`、`keyboard_ready`、
`usb->input` を主指標にします。

## 6. Vial and Runtime Keymap

- [ ] `hidloom-late-services.timer` が起動し、`viald` が active
- [ ] Vial client が keyboard definition を取得
- [ ] keymap 変更が実打鍵へ反映
- [ ] save 後、再起動しても `/mnt/p3/keymap.json` が保持
- [ ] Raw HID disconnect/reconnect 後に Vial が復旧

```bash
systemctl status hidloom-late-services.timer viald --no-pager
journalctl -u hidloom-usb-gadget -u viald -b -n 200 --no-pager
hidloom-ctrl keymap
```

## 7. OLED, LED, I2C, Shutdown

- [ ] `i2cd` と `ledd` が active
- [ ] OLED が `booting` から daemon/runtime status へ進む
- [ ] LED が boot effect から通常 effect へ進む
- [ ] configured I2C device が検出される
- [ ] shutdown key/button が安全な shutdown を開始する

```bash
systemctl status i2cd ledd ledd-shutdown --no-pager
/usr/sbin/i2cdetect -y 1
journalctl -u i2cd -u ledd -u ledd-shutdown -b --no-pager -p warning
```

OLED/LED 未搭載 profile では、service policy と release notes に非搭載であることを明記します。

## 8. Optional Network, HTTP, Bluetooth

これらは Raspberry Pi OS profile の optional/late service です。offline Buildroot M6 の
合否条件には含めません。

- [ ] network を使う profile は OS-managed recovery path を維持
- [ ] HTTP を使う profileは HTTPS `/api/status` が応答
- [ ] credential は device policy と一致し、release notes に平文秘密値を書かない
- [ ] Bluetooth を使う profile は `btd` backend、pairing、reconnect を確認

```bash
systemctl status httpd btd bluetooth --no-pager
curl -k -u "admin:$(hostname)" https://127.0.0.1/api/status
systemctl show btd -p Environment --no-pager
```

## 9. Test Cleanup and Recovery State

- [ ] `hidloom-outputd` target を `debug`/`usb`/`uinput` に変えた試験後は `auto` へ復旧
- [ ] temporary unit override、socket、fixture、mount を除去
- [ ] restart/reboot 後の health snapshot を保存
- [ ] package/profile version、device role、pass/fail、rollback 状態を記録

```bash
hidloom-ctrl output auto
cat /run/hidloom/outputd-status.json
systemctl --failed --no-pager
```

## 10. Clean Public Export

- [ ] private repository の履歴を直接公開しない
- [ ] 全tracked pathがpublic source/private-only/generated outputへ分類され、unclassifiedとunexpected outputが0
- [ ] allowlist manifest、deny scan、privacy/reference/docs audit が pass
- [ ] standalone public clone で canonical validation と locked Rust tests が pass
- [ ] public repository policy plan/audit が canonical config と一致
- [ ] pending VID/PID は`stable-public`だけのblockerとしてrelease notesに残す
- [ ] `internal-rc` binaryをpublic GitHub Releaseへuploadしない

```bash
make public-export-check
python3 /tmp/hidloom-public-export/tools/public_release_readiness.py \
  /tmp/hidloom-public-export --channel source-public
```

初回 public repository は GitHub 側で README/LICENSE を生成しない空 repository とし、
`tools/public_repository_bootstrap.py` の non-force、manifest-bounded 手順を使います。

## 11. Buildroot M6 Artifact

- [ ] Raspberry Pi OS と Buildroot の搭載/非搭載差分を確認
- [ ] fixed Buildroot source、runtime staging、artifact import smoke が pass
- [ ] raw/zstd image、SBOM、license、notices、checksum を同じ bundle に収録
- [ ] offline、Wi-Fi/httpd 非搭載、`pi / pi`、rollback microSD を release notes に記載
- [ ] `-02` 実機で USB HID、Vial、LT、JIS/US、OLED、LED、stick、uinput、shutdown を確認

```bash
make buildroot-compliance-verify
python3 tools/public_release_readiness.py . \
  --channel internal-rc \
  --compliance-bundle build/artifacts/hidloom-buildroot-m6-compliance.tar.zst
python3 tools/public_release_bundle.py --verify <release-directory>
python3 tools/public_release_bundle.py \
  --verify <release-directory> \
  --require-channel-ready internal-rc
python3 tools/public_release_bundle.py \
  --verify <stable-release-directory> \
  --require-channel-ready stable-public
```

## 12. Release Notes

- [ ] source commit、package/profile version、image version を記載
- [ ] user-visible changes と incompatible changes を記載
- [ ] tested device role と実行した command を記載
- [ ] automated test と operator/physical test を分離
- [ ] known limitations、external blockers、rollback を記載
- [ ] checksum verification command を記載
