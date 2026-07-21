# HIDloom License Evidence Runbook

更新日: 2026-07-14

## 目的

third-party inventoryを、実際に再配布するcomponentとtarget package managerが導入する外部依存へ分離し、
配布artifactのlicense/source evidenceを確定する。開発hostで見えたversionをtarget imageの確定情報として扱わない。

現在のinventoryは56件で、再配布対象31件は31件ともmetadata確認済み、Debian/Pythonの23件は
`external-install-dependency`としてsplit Debian packageへ内包しない。公開CIのGitHub Actions 2件は
`ci-action-reference`としてfull SHAとMIT licenseを固定し、配布artifactへ内包しない。binary release用の対応source bundleは別gateとする。

## Host-observed evidence

```bash
python3 tools/collect_license_evidence.py /tmp/hidloom-license-evidence
```

このcommandは次を収集する。

- installed Debian package versionと`/usr/share/doc/<package>/copyright`
- installed Python distribution metadata、license classifier、LICENSE/COPYING/NOTICE file
- SHA-256付き`LICENSE_EVIDENCE.json`

reportのscopeは`host-observed-only`であり、target Raspberry Pi OSやrelease imageの証明にはならない。
package build containerまたはtarget rootfsに対して同じcollectorを実行し、配布versionと一致させる。

## Buildroot legal-info

dry-run:

```bash
python3 tools/buildroot_legal_info.py \
  --output build/artifacts/buildroot-m6-output
```

source downloadを含む実行:

```bash
python3 tools/buildroot_legal_info.py \
  --output build/artifacts/buildroot-m6-output \
  --prepare-source --execute \
  --report build/artifacts/buildroot-m6-legal-info-result.json
```

helperは利用可能なら`/usr/bin/gnuinstall`を一時PATHで使い、hostのalternativesを変更しない。
`legal-info/manifest.csv`、license texts、source archivesをrelease evidenceとして保存する。
実行成功時は`legal-info/hidloom-summary.json`も生成される。tracked baselineを更新する場合は次を使う。

```bash
python3 tools/summarize_buildroot_legal_info.py \
  build/artifacts/buildroot-m6-output/legal-info \
  --output docs/ops/buildroot-m6-legal-summary.json
```

2026-07-14のM6結果はtarget package 20件、source archive 20件、license metadata 20件を確認済み。
`hidloom-matrixd`とlegacy M3 routerにはGPL-3.0-or-laterの`COPYING`とhash metadataを追加した。

Bootlin external toolchainはBuildroot package metadata上のlicense file未定義を、同一archiveの公式evidenceで補う。

- archive SHA-256: `97d6fbaf19832002f3d6aa8fd31b2d29c1dc7b0752f4ae8ed35860fd33c1f9b4`
- [Bootlin release matrix](https://toolchains.bootlin.com/releases_armv7-eabihf.html)
- [exact toolchain README](https://toolchains.bootlin.com/downloads/releases/toolchains/armv7-eabihf/readmes/armv7-eabihf--glibc--stable-2025.08-1.txt)
- [exact license/source summary](https://toolchains.bootlin.com/downloads/releases/toolchains/armv7-eabihf/summaries/armv7-eabihf--glibc--stable-2025.08-1.csv)

URL、evidence file hash、toolchain構成は`config/buildroot-toolchain-evidence.json`へ固定する。

公式summaryに現れる27行は25 componentへ統合し、source archive 24件とlicense file 41件を
`config/buildroot-toolchain-components.json`へsize/SHA-256付きで固定する。lockを更新する場合:

```bash
python3 tools/buildroot_compliance_bundle.py lock --refresh
```

binary imageへ添付する対応source archiveは次で作成・検証する。

```bash
python3 tools/buildroot_compliance_bundle.py build --fetch-missing
python3 tools/buildroot_compliance_bundle.py verify \
  build/artifacts/hidloom-buildroot-m6-compliance.tar.zst
python3 tools/public_release_readiness.py . \
  --channel internal-rc \
  --compliance-bundle build/artifacts/hidloom-buildroot-m6-compliance.tar.zst
```

archiveはM6 `legal-info`全体、HIDloom用Buildroot commit、Bootlin builder commit、公式README/summary、
全component source/licenseを含む。objectはSHA-256で一度だけ格納し、package/filename対応は
`COMPLIANCE_MANIFEST.json`に残す。

## Completion gate

1. public sourceからM6 outputを再生成する。
2. 同じoutputで`--prepare-source --execute`を成功させる。
3. `manifest.csv`とsource/license directoriesのchecksumを生成し、summaryの`source_audit_ready=true`を確認する。
4. Debian/Python evidenceを実際のpackage build環境から採取する。
5. `THIRD_PARTY_NOTICES.md`とCycloneDX SBOMを確定versionへ更新する。
6. pinned Buildroot sourceとBootlin component source/licenseをrelease compliance bundleへ収録する。
7. bundle内manifestの`binary_release_ready=true`を確認してからimageを公開する。
8. 公開CI actionのworkflow参照、`config/github-actions-lock.json`、SBOMが同じversion/SHAであることを確認する。

## Current evidence

- Ubuntu 26.04 development host: Debian 21件中15件を観測、Python direct-PyPI 2件は未導入。
- M6: exact target 20件はsource/license audit完了。`source_audit_ready=true`。
- M6 compliance bundle: target 20件、host 40件、Bootlin 25 component、component source 24件とbuilder source 1件、license file 41件を収録し、`binary_release_ready=true`。
- Tracked legal-info baseline: bundle外の状態を正確に示すため、2件の収録待ちwarningと`binary_release_ready=false`を維持する。`public_release_readiness.py`のsource scopeではこれを公開source blockerへ数えず、compliance archive指定時だけbinary scopeとして解決済み2件、Buildroot commit、Bootlin versionを照合する。
- M3/M4の旧outputはrelease evidenceに流用せず、必要時は対応defconfigから再生成する。
