# Release packaging runbook

この文書は、x86_64 cross-build hostで作ったpackageをRaspberry Pi実機へ入れる時の運用手順です。
各 script の細かい option は [tools/package/README.md](../../tools/package/README.md)、
再現可能なcross buildは[public source rebuild runbook](public-source-rebuild-runbook.md)を参照します。

## 目的

実機で `git pull` や native build を行わず、host 側で作った payload を実機へ配布します。
現在の本線は Debian package layout です。

- application / default root: `/usr/lib/hidloom`
- package-owned systemd units: `/lib/systemd/system`
- installed manifest: `/var/lib/hidloom/package-manifest.json`
- runtime mutable state: `/mnt/p3`

`/mnt/p3/keymap.json`、`/mnt/p3/led_state.json`、
`/mnt/p3/bluetooth_hosts.json`、`/mnt/p3/script`、HTTP TLS key は package payload に含めません。
package はアプリ本体と既定値を届け、実機固有の mutable state は外部 mount 側を正にします。

Touch-panel 型や基板差分は、core package と device profile package を分けて扱います。
profile package は `/usr/share/hidloom/profiles/<profile>` に immutable な
profile files を入れ、runtime definition と service policy は
`hidloom-profile <profile> --apply --backup --restart` で `/mnt/p3` と systemd に反映します。
core と profile は同じ version を同時に install します。

## 実機 profile

標準 helper の `--device` は次の実機を指します。

| device | host | 既存 checkout |
|---|---|---|
| `01` | `operator@<keyboard-ip>` | `/home/USERNAME/hidloom` |
| `02` | `pi@<keyboard-ip>` | `/home/pi/hidloom` |

一時 target へ向ける場合だけ、script に `--host` と必要な path option を直接渡します。
Make target は標準 profile 用です。

## 成果物

`make package` は release bundle を作ります。

```bash
make package
```

生成物:

```text
build/packages/hidloom-<git_sha>-aarch64.tar.zst
build/packages/hidloom-<git_sha>-aarch64.tar.zst.sha256
```

bundle には git `HEAD` の repository snapshot、ARM64 Rust daemon、
ARM64 static `matrixd`、`build/package-manifest.json` が入ります。
未コミット差分は payload に入りません。未コミット差分を実機へ入れたい場合は、先に commit します。

`make deb-package` は bundle から legacy single Debian package を作ります。
現在の標準は `hidloom-core` と device profile package の split 構成です。

```bash
make deb-package
```

生成物:

```text
build/packages/hidloom_0.0.<git_rev_count>+git<git_sha>_arm64.deb
build/packages/hidloom_0.0.<git_rev_count>+git<git_sha>_arm64.deb.sha256
```

split package の標準成果物:

```bash
make core-deb-package
make keyboard-ver1-profile-deb
make DEVICE_PROFILE=touch-waveshare-8.8 profile-deb-package
```

生成物:

```text
build/packages/hidloom-core_0.0.<git_rev_count>+git<git_sha>_arm64.deb
build/packages/hidloom-profile-<profile>_0.0.<git_rev_count>+git<git_sha>_arm64.deb
```

version は `0.0.<git_rev_count>+git<git_sha>` を使います。
過去の `0+git<sha>` 形式は SHA の辞書順で downgrade 扱いになることがあるため、再利用しません。
`.sha256` は GitHub Releases から別 directory へ download しても `sha256sum -c` できるよう、
absolute path ではなく basename を記録する portable sha256 形式にします。

`.deb` の Depends には `python3-aiohttp`、`python3-dbus-next`、`python3-luma.oled`、
`python3-pil`、`i2c-tools`、`openssl`、`rfkill`、`socat` を含めます。fresh OS へ直接 install する場合、
これらが欠けていれば dpkg / apt の段階で止め、service 起動後の import error まで進ませないためです。
`rpi_ws281x` は無い場合も `ledd` が stub mode で起動できるため Depends には入れず、
LED 実出力が必要な fresh setup では `setup_fresh_rpi.sh` の pip install で扱います。
package `postinst` は `/mnt/p3` と `/mnt/p3/script` を作成し、欠けている default script を
`/usr/lib/hidloom/config/default/script` から初期コピーします。既存runtime scriptは原則保持し、
`config/default/script-migrations.json`に完全一致する既知の旧defaultだけを隣接backup後に移行します。
利用者編集またはsymlinkは自動置換しません。

## GitHub Releases で配布する時の考え方

`.deb` 本体は git 追跡対象にしません。git には source、packaging script、
検査手順、release note の元になる記録を置き、配布する binary artifact は
GitHub Releases に添付します。

ただし GitHub Releases は利用者から見ると公式配布物に見えるため、最初から
stable release として扱いません。次の段階を分けます。

| 段階 | 目的 | GitHub 上の扱い | 必須条件 |
|---|---|---|---|
| local candidate | host で作った `.deb` が配布候補になるか確認する | upload しない | clean worktree、validation suite、package contents、sha256、old checkout path 混入なし |
| prerelease | 実機投入候補を別環境から取得しやすくする | `gh release create --prerelease` | local candidate 合格、release note に検証状態と既知リスクを書く |
| stable release | 別環境へ入れてよい基準を満たした版 | prerelease ではない GitHub Release | `-01` install + smoke、`-02` read-only verify または smoke、failed units 0、rollback 手順確認 |

`prerelease` は「動作確認途中の候補」であり、「安定版」ではありません。
main input device で live smoke を省略した場合や、片方の実機だけで確認した場合は、
release note に `not tested` / `skipped` と理由を明記します。

## Release candidate gate

GitHub Release に載せる前に、host 側で release candidate gate を通します。
この gate は「実機に入れれば必ず動く」ことを保証するものではなく、
「配布物として明らかに壊れているものを GitHub Releases に置かない」ための最低条件です。

標準候補:

```bash
make release-candidate-check
```

core/profile split package 候補:

```bash
tools/package/release_candidate_check.sh --split-profile touch-waveshare-8.8
```

Raspberry Pi 4 touch-panel向けは、clean public sourceでprofileを指定してbuildし、対応source、
SBOM、quickstart、release notes、portable checksumを専用directoryへまとめます。

```bash
tools/public_build_rehearsal.sh --package --profile touch-waveshare-8.8
tools/package/build_touch_panel_release.sh
python3 tools/package/build_profile_release_bundle.py verify \
  build/touch-panel-release
```

この時点ではtag作成もuploadも行いません。実機smoke後の内部候補は次を通します。

```bash
python3 tools/package/build_profile_release_bundle.py verify \
  build/touch-panel-release --require-channel-ready internal-rc
```

このgateはpublic build provenance、Raspberry Pi 4実機のdevice名、touch-ready時間を要求しますが、
PID割当は要求しません。正式公開時は`--channel stable-public`で同じsourceから再生成し、
`--require-channel-ready stable-public`を要求します。

Zero 2 W keyboard package、touch profile、Buildroot M6を同じReleaseへ載せる場合は、
`build_zero2w_keyboard_release.sh`で作った統合bundleからGitHub Release planを生成する。
既定はdry-runで、全asset checksum、対応source内verifier、正式USB identity、keyboard実機smoke、
source commitと`HEAD`一致、clean worktree、`origin=cqa02303/hidloom`を確認し、tag/uploadは行わない。

```bash
python3 tools/package/publish_public_release_bundle.py \
  --bundle build/zero2w-keyboard-release \
  --output-plan build/artifacts/public-release-publish-plan.json
```

`stable-public ready=true`、keyboardとtouchのhardware smoke `pass`、final public source build、
人間によるplan確認の後にだけ
exact確認句付きでdraft prereleaseを作成する。legacy `publish_github_prerelease.sh`は単一またはsplit
package用であり、統合bundleには使わない。

```bash
python3 tools/package/publish_public_release_bundle.py \
  --bundle build/zero2w-keyboard-release \
  --require-ready
python3 tools/package/publish_public_release_bundle.py \
  --bundle build/zero2w-keyboard-release \
  --execute \
  --confirm 'CREATE DRAFT cqa02303/hidloom v0.1.0'
```

helperは`internal-rc`を常に拒否します。既存Releaseと既存tagも拒否し、`gh release create --draft --prerelease --target <source-commit>`へ
`SHA256SUMS`掲載全assetを渡す。
作成後は全assetを別directoryへdownloadし、対応source archive内の`public_release_bundle.py`で
publication/hardware gateを含むdeep verifyを行う。公開済みまたはdraftをread-onlyで再確認する入口:

```bash
python3 tools/package/verify_github_public_release_bundle.py \
  --tag v0.1.0 \
  --repository cqa02303/hidloom
```

人間がGitHub上の差分、Release本文、asset一覧を確認するまでdraftを維持する。最終公開は別操作として
`gh release edit v0.1.0 --repo cqa02303/hidloom --draft=false`を実行し、誤ったdraftは公開せず削除する。

`make release-candidate-check` は upload を行わず、clean worktree、validation suite、
`.deb` build、package metadata / contents、sha256、退避済み checkout path 混入なしを確認し、
`build/packages/release-note-v<version>.md` に release note draft を出します。
`--split-profile` では core package と matching profile package を同時に build/check し、
profile package が同じ version の core package に依存することも確認します。

手動で分けて確認する場合は、次を実行します。

```bash
git status --short
python3 script/test_validation_suite.py
make deb-package
python3 script/test_release_bundle_tools.py
python3 script/test_docs_links.py
git diff --check
```

生成された `.deb` について次を確認します。

```bash
dpkg-deb --info build/packages/hidloom_0.0.<git_rev_count>+git<git_sha>_arm64.deb
dpkg-deb --contents build/packages/hidloom_0.0.<git_rev_count>+git<git_sha>_arm64.deb
sha256sum -c build/packages/hidloom_0.0.<git_rev_count>+git<git_sha>_arm64.deb.sha256
```

contents check では最低限、次を見ます。

- `/usr/lib/hidloom/bin/hidloom-hidd`
- `/usr/lib/hidloom/bin/hidloom-uidd`
- `/usr/lib/hidloom/bin/hidloom-outputd`
- `/usr/lib/hidloom/bin/hidloom-logicd-core`
- `/usr/lib/hidloom/bin/hidloom-usb-gadget-fast`
- `/usr/lib/hidloom/daemon/matrixd/matrixd`
- `/lib/systemd/system/*.service` / `*.timer`
- `/usr/share/man/man1|man5|man8/*.gz`
- `/var/lib/hidloom/package-manifest.json`

さらに package member path、systemd unit、default script に、退避済み checkout へ戻る参照がないことを確認します。

man page は runtime package 本体に含めます。サイズは小さく保ち、installed
環境での quick reference として `--help` より少し詳しい usage、socket、
環境変数、関連 command を記載します。詳細仕様、設計背景、更新されやすい
troubleshooting は `SEE ALSO` の GitHub docs URL へ流し、package build 時に
manifest の git sha を URL へ埋め込みます。

```bash
dpkg-deb --contents build/packages/hidloom_0.0.<git_rev_count>+git<git_sha>_arm64.deb | grep -E '/home/(pi|operator)/hidloom' && exit 1 || true
```

実際の file content に対する grep は、package を一時展開して実行経路に効く script / unit だけ確認します。
docs、archive、README には過去の `/home/pi/hidloom` 記録や「戻らない」説明が残るため、
payload 全体 grep は使いません。

```bash
tmpdir=$(mktemp -d)
dpkg-deb -x build/packages/hidloom_0.0.<git_rev_count>+git<git_sha>_arm64.deb "$tmpdir"
find \
  "$tmpdir/usr/lib/hidloom/config/default/script" \
  "$tmpdir/usr/lib/hidloom/system/systemd" \
  "$tmpdir/lib/systemd/system" \
  \( -name 'KC_SH*.sh' -o -name '*.service' -o -name '*.timer' \) \
  -type f -print0 | xargs -0 grep -n '/home/pi/hidloom\|/home/USERNAME/hidloom' && exit 1 || true
rm -rf "$tmpdir"
```

`make release-candidate-check` は、この節の項目を自動化する target です。
合格した `.deb` path、sha256、version、git sha、release note draft の path だけを出し、
tag 作成、GitHub upload、実機 install は行いません。

## GitHub prerelease / stable release の流れ

candidate gate 合格後、まず prerelease として GitHub Releases に置きます。
実行前には dry-run plan を確認します。

```bash
make release-prerelease-plan
```

`release-prerelease-plan` は GitHub upload、tag 作成、tag push を行わず、
`gh release create --prerelease` で実行されるコマンドだけを表示します。

実行:

```bash
make release-prerelease-publish
```

tag は既定で Debian version と同じ `v0.0.<git_rev_count>+git<git_sha>` にします。
`tools/package/publish_github_prerelease.sh --tag TAG --execute` を使えば明示 tag も指定できます。
`release-prerelease-publish` は clean worktree、candidate gate、`.deb` / `.sha256` /
release note draft の存在を確認してから、tag 作成、`git push origin <tag>`、
`gh release create --prerelease` を実行します。公開後は同じ helper 内で
`verify_github_release_assets.sh --tag <tag>` を呼び、GitHub から download した
`.sha256` が portable で `sha256sum -c` を通ることも確認します。
`.deb` の version suffix が現在の `HEAD` short sha と一致しない場合は止まるため、
commit 後は必ず `make release-candidate-check` を再実行してから publish plan を確認します。

公開済み public bundle を後から再確認する場合は、GitHub Releases から別 directory へ
core/profile assetと`SHA256SUMS`をdownloadして整合を確認します。

```bash
make release-download-verify RELEASE_TAG=v0.0.<git_rev_count>+git<git_sha>
```

`release-download-verify` はtag、release、実機を変更せず、core/profileと`SHA256SUMS`を
downloadしてportable checksum、package名、arm64 architecture、同一version、profileの
exact core dependencyを確認します。legacy single package releaseでは`.deb.sha256`へfallbackします。

## GitHub Release から別環境へ install する手順

stable release を別環境へ入れる時は、まず download と checksum verify だけを行います。

```bash
make release-deb-download RELEASE_TAG=v0.0.<git_rev_count>+git<git_sha>
```

標準 profile の実機へ低レベル手順で入れる場合は、同じ Release のcore/profile assetを使い、
同じremote `dpkg` transactionでdry-runします。

```bash
make release-deb-dry-run RELEASE_TAG=v0.0.<git_rev_count>+git<git_sha> DEVICE=01
make release-deb-dry-run RELEASE_TAG=v0.0.<git_rev_count>+git<git_sha> DEVICE=02
```

dry-run が通ってから同じtransactionの`dpkg -i` installとprofile適用をします。

```bash
make release-deb-install RELEASE_TAG=v0.0.<git_rev_count>+git<git_sha> DEVICE=01
make release-deb-install RELEASE_TAG=v0.0.<git_rev_count>+git<git_sha> DEVICE=02
```

この入口は `tools/package/install_github_release_deb.sh` を呼び、GitHub Release の
`hidloom-core`、`hidloom-profile-keyboard-ver1`、`SHA256SUMS`をdownloadし、checksum、
package名、arm64 architecture、version、exact dependencyを検証してからremoteへcopyします。
`release-deb-download` は実機を変更しません。`release-deb-dry-run` は remote へ copy して
両packageの`sudo dpkg --dry-run -i`まで、`release-deb-install`は両packageの
`sudo dpkg -i`と`hidloom-profile keyboard-ver1 --apply --backup --restart`まで進めます。
この分割手順は dependency install を行わないため、fresh OS では通常、下の標準 flow を使います。

install 後は、package unit restart と smoke を明示的に実行します。

```bash
make deb-unit-switch-01
make deb-verify-smoke-01
make deb-unit-switch-02
make deb-verify-smoke-02
```

上の分割手順を標準 flow としてまとめて実行する場合は、次を使います。

```bash
make release-deb-deploy-dry-run RELEASE_TAG=v0.0.<git_rev_count>+git<git_sha> DEVICE=01
make release-deb-deploy-dry-run RELEASE_TAG=v0.0.<git_rev_count>+git<git_sha> DEVICE=02
```

`release-deb-deploy-dry-run` は `tools/package/deploy_github_release_deb.sh` を呼び、
release asset の download / checksum verify、remote `apt-get -s install`、unit switch dry-run
までを実行します。package DB、systemd unit、service state は変更しません。

dry-run が通ったら install flow を実行します。

```bash
make release-deb-deploy RELEASE_TAG=v0.0.<git_rev_count>+git<git_sha> DEVICE=01
make release-deb-deploy RELEASE_TAG=v0.0.<git_rev_count>+git<git_sha> DEVICE=02
```

`release-deb-deploy` は `apt-get install` による dependency-aware install、package unit への switch / restart、
`deb-verify --smoke` まで進めます。smoke を省く必要がある場合だけ、script を直接
`tools/package/deploy_github_release_deb.sh --tag TAG --device 02 --install --no-smoke`
で呼びます。

fresh OS や一時 IP の個体で標準 `DEVICE=01/02` にまだ入っていない時は、Make から
explicit remote を渡します。

```bash
make release-deb-deploy-dry-run RELEASE_TAG=v0.0.<git_rev_count>+git<git_sha> RELEASE_DEB_REMOTE=pi@192.168.0.x
make release-deb-deploy RELEASE_TAG=v0.0.<git_rev_count>+git<git_sha> RELEASE_DEB_REMOTE=pi@192.168.0.x
```

公開releaseの既定は`RELEASE_REPOSITORY=cqa02303/hidloom`と
`RELEASE_PROFILE=keyboard-ver1`です。別repository/profileを検証する場合だけoverrideします。
scriptの`--device`を直接使う場合は`HIDLOOM_RPI_01` / `HIDLOOM_RPI_02`を設定し、
fresh OSや公開利用者には`--host USER@HOST`を使います。

release note には最低限、次を書きます。

- package file name、version、git sha、sha256
- local validation の結果
- package contents check の結果
- `-01` / `-02` install、unit switch、verify、smoke の結果
- skipped test と理由
- known risk
- rollback 手順

stable release に昇格するのは、実機確認後です。
次の番号付き手順は legacy single package release 用です。split package release では、
core/profile exact version dependency、tested profile matrix、`hidloom-profile <profile> --apply`
結果も release note に記録します。

1. `make deb-package-dry-run-01` / `make deb-package-dry-run-02`
2. `make deb-package-install-01`
3. `make deb-unit-switch-01`
4. `make deb-verify-smoke-01`
5. `make deb-package-install-02`
6. `make deb-unit-switch-02`
7. `make deb-verify-02`、可能なら `make deb-verify-smoke-02`
8. `systemctl --failed --no-pager` が failed units 0
9. release note に実機結果を追記
10. `make release-stable-check RELEASE_TAG=v0.0.<git_rev_count>+git<git_sha>`
11. GitHub Release の prerelease flag を外す

`-02` が main input device の時は live smoke を省略してもよいですが、その場合は
stable 判断を「limited stable」として扱い、release note に
`HID live smoke skipped on -02 because it is the main input device` のように残します。

`release-stable-check` は read-only です。GitHub release note に `not tested` / `skipped` /
`known risk` / `prerelease candidate` / `No route to host` が残っている場合や、
`-01` install + smoke、`-02` verify、failed units 0、rollback 確認が記録されていない場合は
失敗します。あわせて `verify_github_release_assets.sh` で release asset の download verify も行います。
この gate が通ってから、手動で `gh release edit <tag> --prerelease=false` を実行します。

## Script 責務

package helper は、次の責務に分けています。手順を変える時は、どの層を変えるのかを先に決めます。

| script / target | 責務 | 実機変更 |
|---|---|---|
| `tools/package/build_release_bundle.sh` / `make package` | git `HEAD` snapshot と ARM64 binary から release bundle を作る | なし |
| `tools/package/build_zero2w_keyboard_release.sh` | clean public sourceのkeyboard split package、M6 image、対応source/compliance、quickstartを一つの公開候補directoryへまとめる | tag、upload、実機変更なし |
| `tools/package/publish_public_release_bundle.py` | 統合bundleの全asset planを作り、全gateと確認句が揃った時だけdraft prereleaseを作成する | `--execute`時だけGitHub draft/tagを作成 |
| `tools/package/verify_github_public_release_bundle.py` | GitHub Release全assetをdownloadし、checksumと対応source内verifierを再実行する | なし |
| `tools/package/build_deb_package.sh` / `make deb-package` | release bundle から legacy single Debian package payload と maintainer script を作る | なし |
| `tools/package/build_deb_package.sh --package-id hidloom-core` / `make core-deb-package` | split core package を作る | なし |
| `tools/package/build_device_profile_deb.sh` / `make profile-deb-package` | split device profile package を作る | なし |
| `tools/package/deploy_deb_package.sh` | `.deb` を実機へ copy し、標準 Make target では `apt-get -s install` または `apt-get install` を実行する。script 直呼びでは `--apt` なしの `dpkg` check/install も可能 | `--install` の時だけ package DB を変更 |
| `tools/package/deploy_deb_unit_switch.sh` | remote に unit switch helper を送り、package unit への切り替えを実行する | non-dry-run で `/etc` unit を退避、systemd reload、必要なら restart |
| `tools/package/deploy_deb_verify.sh` | split core/profileのinstalled state、arm64、同一version、manifest、systemd state、smokeを確認する | `--smoke` の時だけlive smokeを実行し、終了時にoutput targetを`auto`へ戻す |
| `tools/package/deploy_release_bundle.sh` | 互換 mode の release bundle copy / apply を remote 実行する | non-dry-run で checkout、`/opt`、または rehearsal root を更新 |
| `tools/package/deploy_release_rollback.sh` | `/opt/hidloom/current` release root を戻す | non-dry-run で symlink、unit、必要なら service state を変更 |

host 側 build script は実機を変更しません。実機を変更する境界は `deploy_*` script です。
dry-run は「変更しないで観測する」ための入口で、install / switch / restart / smoke は明示 option にします。

## Path 契約

Debian package layout では、次の境界を崩さないことを package 変更の前提にします。

| path | 所有者 | 変更してよいもの |
|---|---|---|
| `/usr/lib/hidloom` | Debian package | application、default config、script、native binary |
| `/lib/systemd/system` | Debian package | package-owned systemd unit |
| `/var/lib/hidloom/package-manifest.json` | Debian package / deploy helper | installed manifest |
| `/mnt/p3` | 実機 runtime state | keymap、LED state、Bluetooth hosts、user script、TLS key |
| `/etc/systemd/system` | local override / legacy rehearsal | package unit を shadow するため、通常は空または明示 override のみ |

Raspberry Pi OS では `/lib/systemd/system` が `/usr/lib/systemd/system` として見える構成があります。
`dpkg-deb --contents` では package payload の `/lib/systemd/system` を確認し、
実機では `systemctl show -p FragmentPath` の実解決 path を確認します。
どちらで表示されても、`/etc/systemd/system` に同名 unit が残っていないことが重要です。

## 標準 deploy

現在の標準手順は split `.deb` を build して、core/profile を同じ version で install、
profile apply、unit switch、smoke verify まで通す流れです。

既にpackageが入っている実機へpreviewを更新する場合は、sibling temporary commitのhash辞書順を
新旧判定に使わず、copy/install前にDebian versionが単調増加していることを確認します。

```bash
candidate=$(dpkg-deb -f build/packages/hidloom-core_<version>_arm64.deb Version)
installed=$(ssh <device> "dpkg-query -W -f='\${Version}' hidloom-core 2>/dev/null || true")
test -z "$installed" || dpkg --compare-versions "$candidate" gt "$installed"
```

このcheckが失敗したcandidateは`--allow-downgrades`で導入せず、monotonic versionのclean snapshotから
core/profileを再生成します。その後の`apt-get -s install`でも両packageがupgrade表示であることを確認します。

```bash
make core-deb-package
make keyboard-ver1-profile-deb
scp build/packages/hidloom-core_<version>_arm64.deb \
  build/packages/hidloom-profile-keyboard-ver1_<version>_arm64.deb \
  <device>:/tmp/
ssh <device> 'sudo apt-get install -y \
  /tmp/hidloom-core_<version>_arm64.deb \
  /tmp/hidloom-profile-keyboard-ver1_<version>_arm64.deb && \
  sudo hidloom-profile keyboard-ver1 --apply --backup --restart'
make deb-unit-switch-01
make deb-verify-smoke-01
```

legacy single package の一括 deploy target も残しています。

```bash
make deb-deploy-01
make deb-deploy-02
```

どちらの場合も `.deb` deploy は clean git worktree を前提にします。
`dirty_worktree_ignored=true` の manifest は、標準 verify で失敗扱いにします。

## Legacy single package 段階 deploy

legacy single package の初回移行、復旧確認、手順変更後は段階実行します。
split package では core/profile を同じ apt transaction で install するため、この
`deb-package-install-*` 系 target をそのまま標準手順として使いません。

```bash
make deb-package
make deb-package-dry-run-01
make deb-package-dry-run-02
```

dry-run は `.deb` を実機へ copy し、`dpkg-deb --info`、主要 path の contents check、
`sudo apt-get -s install` までを確認します。ここでは install しません。

install:

```bash
make deb-package-install-01
make deb-package-install-02
```

標準 Make target は `--apt` を付けて実行するため、fresh OS で package Depends が不足している場合も
`apt-get` が依存関係込みで解決します。`dpkg` だけの low-level check が必要な時は
`tools/package/deploy_deb_package.sh --device 02 --dry-run` のように script を直接呼びます。

install 後、過去の rehearsal で `/etc/systemd/system` に unit が残っている場合、
package unit より `/etc` unit が優先されます。`shadowed-by-etc` が出た場合は unit switch を通します。

```bash
make deb-unit-switch-dry-run-01
make deb-unit-switch-dry-run-02
make deb-unit-switch-01
make deb-unit-switch-02
```

`deb-unit-switch-XX` は `/etc/systemd/system` の対象 unit を
`/var/backups/hidloom/systemd-pre-deb/<timestamp>` へ退避し、
systemd daemon-reload、package unit enable、package-managed service restart を行います。
package unit がまだ存在しない段階の dry-run は `missing-package-unit` を出し、実行を止めます。

確認:

```bash
make deb-verify-01
make deb-verify-02
make deb-verify-smoke-01
make deb-verify-smoke-02
```

`deb-verify-XX` は`hidloom-core`と対象profile packageのinstalled state、arm64、同一version、manifest、systemd FragmentPath、
対象 unit の active state / `NRestarts` を読みます。
`deb-verify-smoke-XX` はさらに HID smoke と logicd-core native owner smoke を実行します。

## Preflight と失敗時の分岐

手順変更や初回移行では、次の順で止めどころを作ります。

1. host で `make deb-package` が通るか。
2. 実機 dry-run で package metadata と contents が期待通りか。
3. `apt-get -s install` が依存関係と package manager 上の受け入れ条件を満たすか。
4. package所有権preflightでincoming unit/profile pathを別packageが所有していないか。
5. install 後に `shadowed-by-etc` が出るか。
6. unit switch dry-run で `will-backup-remove`、`already-package-unit`、`missing-package-unit` のどれが出るか。
7. switch 後に FragmentPath が package unit 側を指すか。
8. `deb-verify-smoke-XX` で live smoke が通るか。

代表的な分岐:

- `dirty_worktree_ignored=true`: 標準 deploy では失敗扱い。必要なら commit して作り直す。
- `package ownership collision`: apt simulationだけでは異名package間のfile所有権衝突を検出できない。旧core/profileのrollback `.deb`を保存し、旧2 packageの明示removeと新2 packageのinstallを同じapt transactionで行う。partial unpack後は先に`dpkg --audit`とservice healthを確認する。
- `shadowed-by-etc`: install はできているが systemd は `/etc` unit を見ている。unit switch を通す。
- `missing-package-unit`: `.deb` 未 install、package contents 欠落、または unit dir 変更の可能性がある。switch しない。
- `missing-both-units`: package unit も legacy unit も見えない。service restart より先に package contents と unit dir を確認する。
- `NRestarts` 増加: package path の binary / config / socket readiness を確認し、smoke の前後で journal を見る。

## Legacy 互換 mode

Debian package layout へ移る前の互換 mode も残しています。
通常作業では新規採用しません。過去 release の復旧、比較、package unit shadow の
再現調査が必要な場合だけ使います。

既存 checkout へ bundle を展開:

```bash
make package-dry-run-02
make package-deploy-02
```

`/opt/hidloom/current` symlink を active root にする release mode:

```bash
make package-opt-dry-run-02
make package-opt-deploy-02
```

legacy 固定 root rehearsal:

```bash
make package-deb-dry-run-02
make package-deb-deploy-02
```

rehearsal mode は payload を `/usr/lib/hidloom` へ置きますが、
unit はまだ `/etc/systemd/system` に生成します。実 `.deb` では package 管理下の unit を
`/lib/systemd/system` に置きます。

## Rollback

`/opt/hidloom/current` release mode から直前の installed release へ戻す場合:

```bash
make package-rollback-dry-run-02
make package-rollback-02
```

特定 release へ戻す場合は script を直接使います。

```bash
tools/package/deploy_release_rollback.sh --device 02 --release hidloom-dadefd2-aarch64 --dry-run
```

`.deb` install 後に `/etc` unit switch を戻す必要がある場合は、
`/var/backups/hidloom/systemd-pre-deb/<timestamp>` の backup を確認し、
どの unit を戻すかを明示してから作業します。package unit と `/etc` unit の混在は
`systemctl show -p FragmentPath` で必ず確認します。

## 確認観点

package 変更後は、少なくとも次を確認します。

- `bash -n tools/package/*.sh`
- `python3 script/test_release_bundle_tools.py`
- `python3 script/test_docs_reorg.py`
- `python3 script/test_docs_links.py`
- `git diff --check`

実機では次を見ます。

- `dpkg-query -W hidloom-core hidloom-profile-keyboard-ver1`
- `/var/lib/hidloom/package-manifest.json`
- `systemctl show -p FragmentPath hidloom-hidd.service hidloom-logicd-core.service matrixd.service httpd.service i2cd.service`
- target unit の `ActiveState=active`、`SubState=running`、`NRestarts=0`
- HID smoke
- logicd-core native owner smoke

## 注意点

- clean worktree で build しないと、manifest と payload の追跡性が落ちます。
- `/mnt/p3` は package payload で上書きしません。`postinst` は fresh OS 向けに directory と欠けている default script だけを初期化します。
- `/etc/systemd/system` の unit は `/lib/systemd/system` より優先されます。
- package manager の dry-run 成功だけでは systemd が package unit を使う保証になりません。
- `--restart` や smoke は入力 path を一時的に切り替えるため、実行前後に FragmentPath と service state を残します。
- 旧 release bundle には `build/package-manifest.json` がない場合があります。その場合も symlink と unit は戻せますが、manifest の戻しはできません。
