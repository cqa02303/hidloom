# Release bundle tools

x86_64 build hostからRaspberry Pi実機へ、git pull / 実機buildではなく
作成済み package を適用するための tools です。
全体の運用手順、確認観点、rollback 方針は
`docs/ops/release-packaging-runbook.md` にまとめています。この README は
`tools/package/` の script と Make target の quick reference として保ちます。

## Build

```bash
tools/package/build_release_bundle.sh --allow-dirty
make package
```

生成物:

```text
build/packages/hidloom-<git_sha>-aarch64.tar.zst
build/packages/hidloom-<git_sha>-aarch64.tar.zst.sha256
```

bundleはgit `HEAD`のrepository snapshotに、x86_64 hostで作ったARM64 binaryを
差し込んで作ります。未コミットの作業ツリー差分は payload に含めません。

含まれる native binary:

- `bin/hidloom-hidd`
- `bin/hidloom-uidd`
- `bin/hidloom-outputd`
- `bin/hidloom-logicd-core`
- `bin/hidloom-usb-gadget-fast`
- `bin/hidloom-key`
- `bin/hidloom-keytext`
- `bin/hidloom-oled`
- `bin/hidloom-notify`
- `bin/hidloom-ctrl`
- `daemon/matrixd/matrixd`

Rust daemon は `tools/build_rpi_rust.sh` と同じ
`aarch64-unknown-linux-musl` static build を使います。`matrixd` は
`aarch64-linux-gnu-gcc -static` で ARM64 static binary にします。
`KC_SHn` script から呼ぶ `hidloom-notify` などの `tools/hidloom_send` helper も
同じく ARM64 static binary として同梱します。

## Deploy

現在の標準 deploy は Debian package です。既存 checkout への展開や `/opt` release
mode は legacy / recovery 用として残していますが、通常更新では使いません。
fresh Raspberry Pi OS は、先に `setup_fresh_rpi.sh --prepare-only` で boot/module と
device permission を準備し、実機で project binary をbuildせずsplit packageをinstallします。

標準キーボード用の流れ:

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
tools/package/deploy_deb_unit_switch.sh --device 01 --restart
tools/package/deploy_deb_verify.sh --device 01 --profile keyboard-ver1 --smoke
```

legacy checkout へ展開する互換 mode の安全確認:

```bash
tools/package/deploy_release_bundle.sh --device 02 --dry-run
make package-dry-run-02
```

既存 checkout へ適用して native input path service を再起動:

```bash
tools/package/deploy_release_bundle.sh --device 02 --restart
make package-deploy-02
```

`/opt/hidloom/current` へ切り替える release mode の安全確認:

```bash
tools/package/deploy_release_bundle.sh --device 02 --opt-release --dry-run
make package-opt-dry-run-02
```

release mode で適用して native input path service を再起動:

```bash
tools/package/deploy_release_bundle.sh --device 02 --opt-release --restart
make package-opt-deploy-02
```

checkout mode は `/home/pi/hidloom` などの既存 checkout を更新します。
release mode は `/opt/hidloom/releases/<package>` へ payload を展開し、
`/opt/hidloom/current` symlink を active root として systemd unit へ反映します。
この mode では実機側の git checkout が起動経路に不要になります。

## Legacy Pre-.deb Layout Rehearsal

`.deb` 化前に使っていた固定 root 確認用 mode です。現行の標準更新には使いません。
過去の release bundle を調査する場合や、package unit shadow の再現が必要な場合だけ使います。
payload を `/usr/lib/hidloom` に展開し、package-managed unit の
`@HIDLOOM_REPO_ROOT@` を `/usr/lib/hidloom` へ置換します。

この mode でも、実機で更新される定義ファイルは従来どおり外部マウント
`/mnt/p3` 側を正とします。`/usr/lib/hidloom/config/default` や
`/usr/lib/hidloom/config/profiles` は package が提供する default /
fallback で、Vial / HTTP / script editor から保存される
`/mnt/p3/keymap.json`、`/mnt/p3/led_state.json`、`/mnt/p3/oled_customization.json`、
`/mnt/p3/bluetooth_hosts.json`、`/mnt/p3/script`、HTTP TLS key などは
`/mnt/p3` に置きます。
つまり `/usr/lib/hidloom` はアプリ本体と既定値、`/mnt/p3` は実機固有の
mutable state です。
package `postinst` は fresh OS へ直接 install した時の起動失敗を避けるため、
`/mnt/p3` と `/mnt/p3/script` を作成し、`/usr/lib/hidloom/config/default/script`
から欠けている script だけ初期コピーします。既存の runtime script は上書きしません。

安全確認:

```bash
tools/package/deploy_release_bundle.sh --device 02 --deb-layout --dry-run
make package-deb-dry-run-02
```

固定 root へ適用して native input path service を再起動:

```bash
tools/package/deploy_release_bundle.sh --device 02 --deb-layout --restart
make package-deb-deploy-02
```

この rehearsal mode では、まだ unit は `/etc/systemd/system` へ生成します。
最終的な `.deb` では package 管理下の unit を `/lib/systemd/system` に置き、
local override だけを `/etc/systemd/system` に残します。
戻す場合は `make package-rollback-02` で `/opt/hidloom/current` release へ戻せます。

## Debian Package Build

release bundle から、実際の Debian package payload を生成します。

```bash
tools/package/build_deb_package.sh --build-bundle
make deb-package
```

生成物:

```text
build/packages/hidloom_0.0.<git_rev_count>+git<git_sha>_arm64.deb
build/packages/hidloom_0.0.<git_rev_count>+git<git_sha>_arm64.deb.sha256
```

Core / device profile package:

```bash
make core-deb-package
make DEVICE_PROFILE=touch-waveshare-8.8 profile-deb-package
make keyboard-ver1-profile-deb
make keyboard-ver0-profile-deb
```

This creates the core package plus a matching profile package such as
`hidloom-profile-touch-waveshare-8.8`. The profile package depends on
the exact same core package version. Install core and profile together, then
run `hidloom-profile <profile> --apply --backup --restart`. The profile package
installs immutable profile files under `/usr/share/hidloom/profiles/<profile>`;
it does not overwrite `/mnt/p3` until `hidloom-profile` is run.

`.sha256` は別環境で download した directory でも `sha256sum -c` できるよう、
absolute path ではなく basename を記録する portable sha256 形式です。

`.deb` の配置:

- `/usr/lib/hidloom`: application root。release bundle payload をここへ置く。
- `/usr/bin`: `hidloom-key`、`hidloom-keytext`、`hidloom-oled`、`hidloom-notify`、
  `hidloom-ctrl` の package-managed command symlink と `hidloom-profile`。
- `/lib/systemd/system`: package 管理下の systemd unit / timer。
- `/usr/share/man`: commands / daemons / config の小さな manual page。
- `/var/lib/hidloom/package-manifest.json`: installed package manifest。
- `/mnt/p3`: package payload には含めない。runtime mutable state の正。

`.deb` の Depends は、fresh OS へ直接 install した時に runtime が明らかに起動不能な
依存不足を dpkg 段階で止めるため、`python3-aiohttp`、`python3-dbus-next`、
`python3-luma.oled`、`python3-pil`、`i2c-tools`、`openssl`、`rfkill`、`socat` を含めます。
`rpi_ws281x` は無い場合も `ledd` が stub mode で起動できるため package Depends には入れず、
LED 実出力を使う fresh setup では `setup_fresh_rpi.sh` の pip install で入れます。

manual page は package 本体に同梱します。man には installed 環境で必要な最小の
usage、socket、環境変数、関連 command だけを置き、詳細仕様や設計背景は
GitHub docs URL へ流します。`build_deb_package.sh` は `docs/man` の
`@HIDLOOM_VERSION@` / `@HIDLOOM_GIT_SHA@` placeholder を package build 時に展開し、
`/usr/share/man/man1`、`man5`、`man8` へ gzip して配置します。

local で legacy single package の中身を確認する例:

```bash
dpkg-deb --info build/packages/hidloom_0.0.<git_rev_count>+git<git_sha>_arm64.deb
dpkg-deb --contents build/packages/hidloom_0.0.<git_rev_count>+git<git_sha>_arm64.deb
```

legacy single package を `-02` へ copy して、実際には install せずに
dependency-aware な `apt-get -s install` まで確認:

```bash
tools/package/deploy_deb_package.sh --device 02 --dry-run --apt
make deb-package-dry-run-01
make deb-package-dry-run-02
```

legacy single package `.deb` を dependency-aware に install:

```bash
tools/package/deploy_deb_package.sh --device 02 --install --apt
make deb-package-install-01
make deb-package-install-02
```

`postinst` は `systemctl daemon-reload` と対象 unit の enable までを行い、
fresh OS 直接 install 時は `/mnt/p3` と欠けている default script だけを初期化します。
この helper は remote の `systemctl show FragmentPath` も確認し、`/etc/systemd/system`
に rehearsal 生成 unit が残っている場合は `shadowed-by-etc` と表示します。
`/etc/systemd/system` の unit は package が置く `/lib/systemd/system` より優先されるため、
actual install 前に backup / removal / daemon-reload / restart の移行手順を別途通します。

`.deb` install 後に `/etc/systemd/system` の rehearsal unit を退避し、
`/lib/systemd/system` の package unit を有効化する helper:

```bash
tools/package/deploy_deb_unit_switch.sh --device 02 --dry-run
make deb-unit-switch-dry-run-01
make deb-unit-switch-dry-run-02
```

実行:

```bash
tools/package/deploy_deb_unit_switch.sh --device 02 --restart
make deb-unit-switch-01
make deb-unit-switch-02
```

`switch_deb_systemd_units.sh` は実機上で `/etc` unit を
`/var/backups/hidloom/systemd-pre-deb/<timestamp>` へ保存してから削除します。
dry-run は package unit がまだ `/lib/systemd/system` にない場合に
`missing-package-unit` と `dry-run: switch is blocked until package units exist`
を表示するため、actual switch は `.deb` install 後に行います。
`/etc` unit がすでに無い upgrade 後でも、`--restart` を付ければ package unit のまま
package-managed services を再起動します。

package install / reboot 後の確認:

```bash
tools/package/deploy_deb_verify.sh --device 02 --profile keyboard-ver1
tools/package/deploy_deb_verify.sh --device 02 --profile keyboard-ver1 --smoke
make deb-verify-01
make deb-verify-02
make deb-verify-smoke-01
make deb-verify-smoke-02
```

verify helperは`hidloom-core`と`hidloom-profile-<profile>`がinstalled、arm64、同一version
であることを検査します。`--smoke`は終了時と失敗時のどちらでもoutput targetを`auto`へ戻し、
戻し後の`outputd-status.json`を表示します。SSHは既定10秒のconnect timeoutとkeepaliveを使い、
必要な場合だけ`--connect-timeout <sec>`で変更します。

build から smoke までまとめて実行:

```bash
make deb-deploy-01
make deb-deploy-02
```

`deb-deploy-02` は `deb-package`、`deb-package-install-02`、
`deb-unit-switch-02`、`deb-verify-smoke-02` を順に実行します。標準 `.deb`
deploy は clean git worktree 必須です。未コミット差分を含めたい場合は先に commit します。

split package を使う場合は、`deb-deploy-*` ではなく core/profile package を同じ
version で明示 install します。core だけを先に更新すると、apt が version mismatch の
profile package を remove 対象にすることがあります。

## GitHub Releases Distribution

`.deb` 本体は git 追跡対象にせず、配布する binary artifact は GitHub Releases に添付します。
最初から stable release とは扱わず、まず local candidate gate を通し、
必要に応じて `gh release create --prerelease` で実機投入候補として公開します。

最低限の candidate gate:

```bash
make release-candidate-check
```

core/profile split package の candidate gate:

```bash
tools/package/release_candidate_check.sh --split-profile touch-waveshare-8.8
```

この target は GitHub upload や実機 install を行わず、local validation、`.deb` build、
`dpkg-deb --info`、`dpkg-deb --contents`、`.sha256`、runtime path に効く
systemd unit / default script 内の旧 checkout path 混入なしを確認し、
release note draft を生成します。
prerelease / stable の判断、release note に書く検証状態、実機 smoke 後の昇格条件は
`docs/ops/release-packaging-runbook.md` の
「GitHub Releases で配布する時の考え方」を参照します。

GitHub prerelease に載せる前の dry-run:

```bash
make release-prerelease-plan
```

実際に tag 作成、tag push、`gh release create --prerelease` を行う場合:

```bash
make release-prerelease-publish
```

`publish_github_prerelease.sh` は既定 dry-run です。`--execute` がない限り
GitHub upload は行いません。`--execute` で公開した場合は、upload 後に
`tools/package/verify_github_release_assets.sh --tag <tag>` を自動実行し、GitHub から
download した legacy single package の `.sha256` が portable で通ることまで確認します。
public bundle の標準は、以下の core/profile と `SHA256SUMS` の経路です。

公開後に GitHub Releases から別 directory へ core/profile asset を download し、
`SHA256SUMS`、package名、arm64 architecture、同一version、profileのexact core dependencyを
確認する場合:

```bash
make release-download-verify RELEASE_TAG=v0.0.<git_rev_count>+git<git_sha>
```

この target は `tools/package/verify_github_release_assets.sh` を呼び出し、GitHub release
asset の download と checksum 検証だけを行い、tag、release、実機には変更を加えません。

別環境で GitHub Release から split `.deb` を取得して install する場合は、
`tools/package/install_github_release_deb.sh` を使い、download / checksum verify を
必ず同じ入口で通します。download だけ:

```bash
make release-deb-download RELEASE_TAG=v0.0.<git_rev_count>+git<git_sha>
```

既定 repository/profile は `cqa02303/hidloom` / `keyboard-ver1` です。別の release や
profile は `RELEASE_REPOSITORY` / `RELEASE_PROFILE` で明示します。

実機へ core/profile を copy して、同じ transaction の `dpkg --dry-run -i`:

```bash
make release-deb-dry-run RELEASE_TAG=v0.0.<git_rev_count>+git<git_sha> DEVICE=01
make release-deb-dry-run RELEASE_TAG=v0.0.<git_rev_count>+git<git_sha> DEVICE=02
```

実機へ同じ transaction で `dpkg -i` installし、profileを適用:

```bash
make release-deb-install RELEASE_TAG=v0.0.<git_rev_count>+git<git_sha> DEVICE=01
make release-deb-install RELEASE_TAG=v0.0.<git_rev_count>+git<git_sha> DEVICE=02
```

`release-deb-install` は core/profile の package DB を変更し、
`hidloom-profile keyboard-ver1 --apply --backup --restart`まで実行しますが、dependency installは
行わない低レベル入口です。通常は先に
`release-deb-dry-run` を通します。install 後は `make deb-unit-switch-01` /
`make deb-unit-switch-02`、`make deb-verify-smoke-01` /
`make deb-verify-smoke-02` へ進みます。

別環境での標準 install flow をまとめて実行する場合は、
`tools/package/deploy_github_release_deb.sh` を使います。dry-run は release asset の
download / checksum verify、remote `apt-get -s install`、unit switch dry-run までです。

```bash
make release-deb-deploy-dry-run RELEASE_TAG=v0.0.<git_rev_count>+git<git_sha> DEVICE=01
make release-deb-deploy-dry-run RELEASE_TAG=v0.0.<git_rev_count>+git<git_sha> DEVICE=02
```

dry-run が通ってから install flow を実行します。これは `apt-get install` による dependency-aware install、package unit への
switch / restart、`deb-verify --smoke` まで進めます。

```bash
make release-deb-deploy RELEASE_TAG=v0.0.<git_rev_count>+git<git_sha> DEVICE=01
make release-deb-deploy RELEASE_TAG=v0.0.<git_rev_count>+git<git_sha> DEVICE=02
```

fresh OS や一時 IP の個体に入れる時は、`DEVICE` の代わりに explicit remote を指定できます。

```bash
make release-deb-deploy-dry-run RELEASE_TAG=v0.0.<git_rev_count>+git<git_sha> RELEASE_DEB_REMOTE=pi@192.168.0.x
make release-deb-deploy RELEASE_TAG=v0.0.<git_rev_count>+git<git_sha> RELEASE_DEB_REMOTE=pi@192.168.0.x
```

scriptを直接使う`--device 01|02`は`HIDLOOM_RPI_01` / `HIDLOOM_RPI_02`を必要とします。
公開環境やfresh OSでは`--host USER@HOST`または`RELEASE_DEB_REMOTE`を優先します。

stable 昇格前の read-only gate:

```bash
make release-stable-check RELEASE_TAG=v0.0.<git_rev_count>+git<git_sha>
```

この target は `tools/package/check_github_release_stable_ready.sh` を呼び出し、GitHub release
note に `not tested` / `skipped` / `known risk` / `prerelease candidate` などが残っていないこと、
`-01` install + smoke、`-02` verify、failed units 0、rollback 確認が記録されていること、
release asset の download verify が通ることを確認します。prerelease flag は変更しません。

2026-06-27 に `-02` で `hidloom_0+git57081a2_arm64.deb` を install し、
`/etc` unit を `/var/backups/hidloom/systemd-pre-deb/20260627T015825Z` へ退避して
package unit へ切り替え済みです。`systemctl show FragmentPath` は
`/usr/lib/systemd/system/*.service` を指し、HID smoke と
`logicd_core_native_owner_live_smoke.py --apply --json` は通過しました。
`0+git<sha>` version は SHA の辞書順で downgrade 判定されうるため、
以後の package は `0.0.<git_rev_count>+git<sha>` を使います。
その後 `0.0.1682+git63d1bdf` へ upgrade し、再起動後も
`/usr/lib/systemd/system/*.service` の package unit が active/running、
`NRestarts=0`、HID smoke / logicd-core native owner smoke 通過を確認しました。
`f279d2c` 以降は `deb-verify-smoke-02` と `deb-deploy-02` で同じ確認を再実行できます。
`dirty_worktree_ignored=true` の manifest は標準 verify で失敗扱いにします。

2026-06-27 に `-01` も `deb-deploy-01` で package layout へ移行しました。
`/etc` unit は `/var/backups/hidloom/systemd-pre-deb/20260627T022928Z` へ退避済みです。
再起動後も `hidloom 0.0.1686+git1d7f9eb` が
`/usr/lib/systemd/system/*.service` から active/running、`NRestarts=0`、HID smoke /
logicd-core native owner smoke 通過を確認しました。

同日、`-01` と `-02` を `hidloom 0.0.1687+gite69ac40` へ揃えました。
両方とも `/usr/lib/systemd/system/*.service` の package unit が active/running、
`NRestarts=0`、manifest clean、HID smoke / logicd-core native owner smoke 通過です。
その後 `0.0.1720+gitd8f9c96` で `-02` も全 runtime / late unit を
package unit へ移行し、`/home/pi/hidloom` を
`/home/pi/hidloom.disabled-20260627T153347` へリネーム退避しました。
`-02` は main input device のため、この回は HID live smoke を省略し、
read-only verify と HTTP status で確認しました。

## Retiring Device Checkouts

Package-managed deployment が安定した後は、実機側 git checkout を runtime path
から外します。`system/systemd/*.service` / `*.timer` は package に含め、
`switch_deb_systemd_units.sh` は `/etc/systemd/system` の legacy unit を退避しつつ
以前の `UnitFileState` (`enabled` / `disabled` / `static` など) を保ちます。

checkout を消す前に、まず検証機でリネーム退避します。

```bash
mv /home/USERNAME/hidloom /home/USERNAME/hidloom.disabled-$(date +%Y%m%dT%H%M%S)
sudo systemctl restart hidloom-hidd hidloom-uidd hidloom-outputd hidloom-logicd-core matrixd logicd-companion httpd i2cd ledd btd viald
systemctl --failed --no-pager
```

`systemctl show -p FragmentPath -p ExecStart -p WorkingDirectory ...` と
`grep -R /home/.../hidloom /etc/systemd/system /usr/lib/systemd/system`
で checkout 参照が残っていないことを確認します。リネーム退避で数日運用して
問題がなければ削除します。

## Rollback

直前の installed release へ戻す dry-run:

```bash
tools/package/deploy_release_rollback.sh --device 02 --previous --dry-run
make package-rollback-dry-run-02
```

直前の installed release へ戻して native input path service を再起動:

```bash
tools/package/deploy_release_rollback.sh --device 02 --previous --restart
make package-rollback-02
```

特定 release へ戻す場合:

```bash
tools/package/deploy_release_rollback.sh --device 02 --release hidloom-dadefd2-aarch64 --dry-run
```

rollback は `/opt/hidloom/current` symlink を切り替え、release 内の
`system/systemd/*.service` から package-managed unit を再生成します。
対象 release に `build/package-manifest.json` があれば
`/var/lib/hidloom/package-manifest.json` も戻します。

## Notes

- `--dry-run` は bundle manifest と binary file type だけを確認します。
- `--restart` を付けた時だけ service restart します。
- package payload は git `HEAD` 由来です。未コミット変更を実機へ入れたい場合は、
  先に commit してください。
- pre-.deb rehearsal mode は legacy 固定 root の起動確認用です。通常の更新では
  使いません。実 `.deb` の生成は `build_deb_package.sh` で行います。
- `.deb` 化後も `/mnt/p3` の runtime 定義を package payload で上書きしません。
  初期投入や migration が必要な場合だけ、明示的な maintainer script で扱います。
- 旧 package tooling で作った release には `build/package-manifest.json` が release
  内に残っていない場合があります。その場合でも symlink と systemd unit は戻せます。
