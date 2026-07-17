# Public Source Rebuild Runbook

監査済みclean exportまたは将来のpublic cloneだけから、Raspberry Pi OS向けsplit Debian packageと
offline Buildroot M6 imageを再生成する手順です。時間のかかる処理はx86_64 Linux build hostで行い、
Raspberry Pi実機ではbuildしません。

## Host requirements

Ubuntu系hostでは少なくとも次を用意します。

```bash
sudo apt-get install -y \
  build-essential crossbuild-essential-arm64 dpkg-dev fakeroot file git \
  python3 rsync tar zstd
rustup target add aarch64-unknown-linux-musl armv7-unknown-linux-musleabihf
```

Buildroot自身が追加host dependencyを検出した場合は、その診断に従って追加します。
`config/buildroot-source.json`はBuildroot repository URLと検証済みcommitを固定しています。
`tools/buildroot_source_prepare.py`は空の保存先にはそのrevisionを取得し、既存checkoutでは
origin、HEAD、tracked差分を検証します。異なるrevisionを暗黙にcheckoutし直しません。

## Public source integrity

clean exportには`PUBLIC_EXPORT_REPORT.json`と`PUBLIC_EXPORT_MANIFEST.json`が含まれます。
両方の`source_provenance`が一致し、`mode=clean-head`、`publishable=true`であることを含めて、
artifact build前にreadiness、file hash、modeを確認します。dirty sourceから明示生成したdraftはbuildへ使えません。

```bash
python3 tools/public_release_readiness.py . --allow-pending-pid
```

`--allow-pending-pid`はpid.codes割当前の開発rehearsalにだけ使用します。公開Releaseでは割当済み
VID/PIDへ移行し、この例外を外します。

public repositoryへcommitした後も、package versionはpublic側commitではなく
`PUBLIC_EXPORT_REPORT.json.source_provenance.base_commit`へ結び付けます。この値はreadinessがclean HEADと
検証した場合だけ採用します。`tools/public_export_manifest.py`はmanifest掲載fileのsize/SHA-256/modeと
report/manifest provenanceを検証し、package source treeへそのfileだけを展開します。
public clone内に残った過去のbuild outputや未掲載fileはpackageへ入りません。

## Raspberry Pi OS packages

標準配布物は同じversionの`hidloom-core`とdevice profile packageです。標準キーボード用を
native cross-buildからchecksum検証まで一括実行します。

```bash
tools/public_build_rehearsal.sh --package
```

生成先は`build/public-rebuild`です。`OUT_DIR=/path/to/output`で変更できます。

```text
hidloom-<source-sha>-aarch64.tar.zst
hidloom-core_<version>_arm64.deb
hidloom-profile-keyboard-ver1_<version>_arm64.deb
```

helperはARM64 Rust daemon、matrixd、USB gadget helper、command helperをx86_64 host上で
cross-buildし、bundle、core package、`keyboard-ver1` profile packageを作成します。各
`.sha256`を検証し、`dpkg-deb --info`でpackage metadataを読めることまで確認します。
同時に`build/public-rebuild/PUBLIC_BUILD_PROVENANCE.json`を生成して再検証します。このreportは
export report/manifest、source commit、bundle/core/profileのmetadata、全artifactのsize/SHA-256を
一つのcontractへ固定します。

```bash
python3 tools/public_build_provenance.py verify \
  build/public-rebuild/PUBLIC_BUILD_PROVENANCE.json \
  --source . \
  --package-dir build/public-rebuild
```

## Buildroot M6 image

上流source取得とM6 defconfig展開だけを先に確認できます。この経路ではnative binaryやimageを
buildしないため短時間です。

```bash
tools/public_build_rehearsal.sh --buildroot-configure
```

完全なM6 imageを作成し、artifact、ARM Python import、JIS/US split route、companion runtimeを
検証します。

```bash
tools/public_build_rehearsal.sh --buildroot-image
```

packageとimageを連続して作る場合:

```bash
tools/public_build_rehearsal.sh --all
```

既定のBuildroot sourceは`build/artifacts/buildroot-upstream`、outputは
`build/artifacts/buildroot-m6-output`です。保存先を分離する場合は次のように指定します。

```bash
BUILDROOT_DIR=/srv/buildroot/hidloom-pinned \
BUILDROOT_OUTPUT=/srv/buildroot/hidloom-m6-output \
tools/public_build_rehearsal.sh --buildroot-image
```

`BUILDROOT_OUTPUT`をpublic export外へ置くと、native Rustの共有`CARGO_TARGET_DIR`とBuildroot用
host wrapperも同じ外部work directoryへ配置される。image build後に同じexportでrelease readinessを
評価する場合はこの分離を必須とし、manifest外の`tools/*/target`や`build/artifacts`を残さない。

完成imageは`$BUILDROOT_OUTPUT/images/sdcard.img`です。Release用の名前、raw/zstd checksum、SBOM、
対応sourceは公開前に同じprovenance recordへまとめます。

`public_build_rehearsal.sh`はpackageと同じ`PUBLIC_BUILD_PROVENANCE.json`へ、固定Buildroot
repository/commit、clean checkout、M6 `.config`/defconfig SHA-256、public source external tree一致、
image SHA-256、runtime payload digest、artifact/import/runtime verifier結果を記録します。
Buildrootだけを別出力へ記録する例:

```bash
OUT_DIR=build/public-m6-rebuild \
PROVENANCE=build/public-m6-rebuild/PUBLIC_BUILD_PROVENANCE.json \
BUILDROOT_OUTPUT=build/artifacts/public-m6-output \
tools/public_build_rehearsal.sh --buildroot-image

python3 tools/public_build_provenance.py verify \
  build/public-m6-rebuild/PUBLIC_BUILD_PROVENANCE.json \
  --source . \
  --buildroot-source build/artifacts/buildroot-upstream \
  --buildroot-output build/artifacts/public-m6-output
```

## Buildroot corresponding source

imageと同じoutputで`legal-info`を生成し、対応source archiveを作る。Bootlin component lockは公式README/summaryと
全component source/licenseのsize/SHA-256を固定し、通常buildではlockを更新しない。

```bash
python3 tools/buildroot_legal_info.py \
  --output build/artifacts/buildroot-m6-output \
  --prepare-source --execute
make buildroot-compliance-bundle
make buildroot-compliance-verify
```

成果物`build/artifacts/hidloom-buildroot-m6-compliance.tar.zst`にはM6 target/host legal-info、固定Buildroot source、
Bootlin公式evidence、25 componentの対応source/license、toolchain builder source、全file checksumを含む。
`config/buildroot-toolchain-components.json`を更新する場合だけ`make buildroot-compliance-lock`を明示実行し、差分を監査する。

trackedな`docs/ops/buildroot-m6-legal-summary.json`はbundle収録前のraw `legal-info`を表すため、
`binary_release_ready=false`と2件の収録待ちblockerを維持する。source公開readinessとbinary配布readinessは別scopeで確認する。

```bash
# source公開だけを確認する。binary archive未指定でも成功できる。
python3 tools/public_release_readiness.py . --allow-pending-pid

# image配布前は対応source archiveを指定し、2件が実際に解決されたことまで確認する。
python3 tools/public_release_readiness.py . \
  --allow-pending-pid \
  --require-binary-distribution \
  --compliance-bundle build/artifacts/hidloom-buildroot-m6-compliance.tar.zst
```

後者はarchive自身の全checksumとsource/license対応を検証し、Buildroot commit、Bootlin toolchain version、
`resolved_release_blockers`が現在のpublic sourceと一致しないarchiveを拒否する。

## Public release candidate bundle

packageとM6 imageのbuildが終わったら、公開assetを一つの検証可能なdirectoryへまとめます。
`--buildroot-output`はraw imageを単にcopyするのではなく、artifact verifier、ARM import smoke、
ARM runtime smokeを再実行します。core/profile package versionがclean exportのsource commitと一致しない場合も
停止します。

```bash
python3 tools/public_release_bundle.py \
  --source . \
  --buildroot-output build/artifacts/buildroot-m6-output \
  --core-package build/public-rebuild/hidloom-core_<version>_arm64.deb \
  --profile-package build/public-rebuild/hidloom-profile-keyboard-ver1_<version>_arm64.deb \
  --compliance-bundle build/artifacts/hidloom-buildroot-m6-compliance.tar.zst \
  --output build/public-release-0.1.0-rc.1 \
  --version 0.1.0-rc.1
```

生成directoryには次を含めます。

- manifest掲載fileだけから作る決定的source archive
- Buildroot M6 raw imageとzstd image
- `hidloom-core`と`keyboard-ver1` profile package
- Buildroot/Bootlin対応source・licenseの検証済みcompliance archive
- `LICENSE`、SBOM、third-party notices、public export report/manifest
- `RELEASE_MANIFEST.json`、offline境界を記載した`RELEASE_NOTES.md`、portable `SHA256SUMS`

buildやCargoがclean export内へ生成した未掲載artifactはsource archiveへ入りません。生成後の通常確認:

```bash
python3 tools/public_release_bundle.py --verify build/public-release-0.1.0-rc.1
```

実機確認を記録する前はmanifestの`hardware_smoke.status`が`pending`なので、公開用gateは失敗します。
`-02`で全項目とusable-keyboard時間を確認した候補だけを`pass`として再生成し、次を通します。

```bash
python3 tools/public_release_bundle.py \
  --verify build/public-release-0.1.0-rc.1 \
  --require-hardware-pass
```

## Final hardware smoke

build完了は実機合格を意味しません。別microSDへimageを書き込み、Raspberry Pi Zero 2 Wで
USB enumerate、JP/US route、LT、Vial保存、OLED、LED、stick、uinput、shutdownを確認します。
既存Raspberry Pi OS microSDはrollback pathとして保持します。
