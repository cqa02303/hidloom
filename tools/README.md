# tools

実機操作や手動検証に使う補助ツールを置くフォルダです。

`script/` は自動回帰テストや一括 suite を中心にし、`tools/` は実機の daemon socket
へ直接イベントを流すような、運用・確認用のコマンドを置きます。

## Release / Buildroot audit helpers

次のhelperはpublic export、license/SBOM、Buildroot M4/M6 artifact、名称・privacy監査、
touch kiosk healthをbuild host上で検証します。

- `buildroot_legal_info.py`
- `buildroot_compliance_bundle.py`
- `buildroot_m4_jp_direct_keymap.py`
- `buildroot_m6_import_smoke.py`
- `buildroot_m6_runtime_smoke.py`
- `buildroot_m6_verify.py`
- `buildroot_source_prepare.py`
- `collect_license_evidence.py`
- `development_residue_hygiene.py`
- `generate_cyclonedx_sbom.py`
- `generated_binary_hygiene.py`
- `generate_hidloom_icons.py`
- `generate_third_party_inventory.py`
- `hidloom_name_audit.py`
- `local_environment_hygiene.py`
- `pid_codes_application.py`
- `public_usb_identity.py`
- `public_asset_inventory.py`
- `public_build_provenance.py`
- `public_community_health.py`
- `public_export.py`
- `public_export_manifest.py`
- `public_privacy_audit.py`
- `public_reference_audit.py`
- `public_release_bundle.py`
- `public_release_readiness.py`
- `public_repository_create.py`
- `public_repository_bootstrap.py`
- `public_repository_policy.py`
- `public_source_archive.py`
- `summarize_buildroot_legal_info.py`
- `public_sync_branch.py`
- `public_sync_plan.py`
- `repository_hygiene.py`
- `source_syntax_hygiene.py`
- `touch_kiosk_health_probe.py`
- `workspace_debris_hygiene.py`

`public_release_readiness.py`は既定でsource公開scopeを検査する。Buildroot image配布前は
`--require-binary-distribution --compliance-bundle <archive>`を追加し、raw legal-infoの収録待ちblockerが
同じBuildroot/toolchain用の検証済み対応source archiveで解決されていることまで確認する。

`public_usb_identity.py`は現行private互換profileと将来のpublic正式profileを同じcontractで検査する。
現行config/Vial定義とのdriftを拒否し、pid.codes merge evidenceが揃うまで正式profile bundleを生成しない。

`public_repository_create.py`はcanonical GitHub account、repositoryの404、`private=false`、説明、homepage、
feature/merge設定、branch/tag 0を検査する。通常はnon-mutating plan/auditだけを行い、完全一致する
`CREATE PUBLIC OWNER/REPOSITORY`確認文字列がある場合だけREADME/license/gitignoreを自動生成しない空repositoryを作る。
全API callはpolicyの`api_host=github.com`を`gh api --hostname`へ明示し、`GH_HOST`が別hostでも誤作成しない。
作成後の不一致でもrepositoryを自動削除またはrenameしない。

`public_repository_policy.py`は現行GitHub REST PATCHで明示管理できる説明、homepage、Issues/Projects/Wiki/template、
merge設定とsecurity設定だけを変更する。visibility/private/archive状態と、作成時に固定するDiscussions/legacy Downloadsは
audit-onlyであり、不一致時は停止して人間が調査する。legacy Downloadsはcreate POSTへ`false`を送るがrepository GETで
欠落または`null`になるため、その場合だけ`unobservable_fields`へ記録して合否から除外し、明示的な`true`はdriftとして拒否する。
API hostは同じcanonical policyから固定し、これらを自動でvisibility変更、unarchive、削除、再作成して修復しない。

`pid_codes_application.py`は申請用org/device pageをrepository外へ生成する。生成時はcanonical originへ作用するGit URL rewriteのない最新のcleanな
canonical upstream checkoutを必須にし、`HEAD`、`origin/HEAD`、online remote `HEAD`、記録済みcommit/date/path evidenceが
一致しなければ停止する。public repositoryのinitial sourceが参照可能になる前に申請PRを提出しない。
生成後はdisposableなupstream cloneへ2 filesだけを配置し、system Pythonを変更せず一時venvで公式validatorを実行する。
`python3 -m venv <temporary-venv>`、`<temporary-venv>/bin/pip install -r requirements.txt`、
`<temporary-venv>/bin/python -m test.validate_pids`の順とし、`No errors found!`と`git diff --check`を申請前証跡にする。
`ModuleNotFoundError: frontmatter`は申請内容の不合格ではなく、公式requirements未導入を示す。

`public_export.py`は`config/public-export.json` schema v2を正本に、Git indexの全pathをpublic source、
明示private-only、既定のgenerated outputへ完全分類する。allowlist外かつprivate-only patternにも一致しない
tracked pathを黙って落とさず、生成helperが未承認report/cacheを追加した場合もmanifestへ収録する前に拒否する。
公開reportには各分類の件数とunclassified 0を記録し、manifest verifierとreadinessが件数の型、合計、
selected file countとの一致を再検証する。fileの祖先でない空directoryもunexpected outputとして拒否する。
公開Markdownはroot `README.md`から全`docs/**/*.md`へ到達できることを検査し、directory indexを
`README.md`へ解決する。broken linkと孤立文書を同じdocumentation auditでblockし、readinessは実treeから
到達性を再計算してreportのsemantic driftも拒否する。
warning triageはreview済みpath globを明示し、全path catch-allは`*_required` dispositionだけを許可する。
したがって、review済みscope外のfileへpassword、token、SSID等のcredential語が追加された場合は、既存の
包括的例外へ自動吸収せず、pathと用途を個別reviewするまでpublic exportを停止する。

`repository_hygiene.py`は生成物や巨大重複に加え、NFC/casefold衝突、Windows予約名・禁止文字、
末尾dot/space、project policyを超えるlong pathをprivate Git indexとpublic manifestの双方で拒否する。
textはUTF-8 BOMなし、LF、final newlineあり、末尾空白なしを要求し、binary、空package marker、
executable shebangとtracked `*.sh`の実行bit契約も検査する。

`source_syntax_hygiene.py`はGit indexまたはpublic manifestに掲載されたPython、JSON、TOML、
YAML、shell、JavaScript、SVGをそれぞれのparserで検査する。rootやgeneratorを取りこぼす
directory限定`compileall`は使わず、private treeとstandalone public exportへ同じ境界を適用する。

`development_residue_hygiene.py`は同じtracked inventoryに対し、merge conflict marker、Pythonの
重複fallback・literal key・環境名・隣接文とdebug hook、shellの自己fallback・重複環境代入・xtrace、
JavaScriptのdebug console/debugger、Rustのplaceholder macroを拒否する。名称hard cutの機械置換で
旧aliasとcanonical名が同じ式へ収束した場合も、公開前にfail-closedで検出する。

`generated_binary_hygiene.py`はGit非追跡の`bin/`、ARM64 Rust、静的C helperの出力directoryを監査し、
hard cut前のretired software名を持つbinaryだけを`--clean`で除去する。canonical binaryと無関係な
operator fileは保持する。cross-build/native build wrapperはinstall前にこのcleanupを実行し、
`deploy_rpi_rust.sh`は出力directory全体ではなくcanonical Rust binary 4個だけをrsyncする。

`local_environment_hygiene.py`はignoredな`.env`を値非表示で監査し、retired software prefixの変数名、
重複、malformed assignment、symlink、group/other-readable modeを拒否する。値の変更は行わず、
retired keyにはcanonical `HIDLOOM_*`名だけを提示する。
`--rewrite-retired-keys`はkey名だけのdry-run planを出し、値とfileを変更しない。`--apply`は
`--confirm REWRITE-LOCAL-ENV-KEYS`が一致した場合だけ同一directoryのtemporary fileからatomic replaceし、
modeと値を維持する。secretを複製しないためbackupは作成せず、collision、構文不良、unsafe mode、symlink、
所有者不一致、inspection後の変更をfail-closedで拒否する。

`workspace_debris_hygiene.py`はsource領域に残るignored cache、Python bytecode、OS/editor一時物を検査する。
`--clean`はそのdisposable分類だけを削除し、`build/`、Rust `target/`、native `.build/`、virtual environment、
release output、backup、credential、mailboxを保持する。tracked file、symlink、backup、nested environment fileは
自動削除せずreview findingとして残す。

`public_community_health.py`はbug/feature issue form、security contact、pull request templateの
必須field、安全な報告導線、検証・互換・実機・公開checklistを検査し、release readinessを
community health fileの存在だけでなく内容にも連動させる。

## demo/

LED video demo など、実機の出力を変える producer / preview tool を置きます。
動画ファイルは `demo/prepare_led_video.py` で `demo/assets/` にローカル生成し、git には含めません。

例:

```bash
python3 demo/prepare_led_video.py
python3 tools/demo/play_led_video.py --backend ledd-direct --seconds 10 --max-brightness 64
python3 tools/demo/play_led_pattern.py --seconds 10 --max-brightness 64
```

`play_led_video.py` は `--max-brightness` で各 LED の RGB 最大チャンネルを
制限できます。動画再生は同時点灯が多く電流が跳ねやすいため、実機ではまず
`64` 前後から試してください。

`play_led_pattern.py` は外部動画、OpenCV、NumPyを使わず、標準libraryだけで
procedural patternを`ledd` direct-frame socketへ送ります。clean packageの`KC_SH2`
fallbackとしても使います。

### demo/led_direct_frame_metrics_watch.py

`ledd` の direct-frame metrics JSON を読み、長時間再生中の accepted / applied / ignored /
rejected frame、bytes、last frame、error を一定間隔で表示します。
HTTP UI を開かずに、LED video / direct-frame の長時間観測を行うための lightweight helper です。

例:

```bash
python3 tools/demo/led_direct_frame_metrics_watch.py --interval 1
python3 tools/demo/led_direct_frame_metrics_watch.py --interval 2 --count 30
LEDD_DIRECT_FRAME_STATUS=/tmp/ledd_direct_frame_status.json python3 tools/demo/led_direct_frame_metrics_watch.py
```

## hidloom_send/

KC_SH や shell script から軽く呼ぶ C helper command 群です。Python 起動待ちを避けるため、
`/tmp/key_events.sock`、`/tmp/i2c_events.sock`、`/tmp/ctrl_events.sock` へ直接送信します。

例:

```bash
tools/hidloom_send/build.sh
bin/hidloom-keytext "ABCabc\n"
bin/hidloom-oled alert "Saved" 2
bin/hidloom-notify warning "Script failed" 3
bin/hidloom-ctrl layer get
bin/hidloom-ctrl output bt
```

## hidloom_hidd/

Python `usbd` の HID report broker と同じ 64-byte frame を受け、`/dev/hidg0` /
`/dev/hidg2` へ native に report を書く Rust helper です。Vial 用の
`/dev/hidg1 <-> /tmp/viald_events.sock` Raw HID bridge も持ちます。起動直後の
keyboard input path を軽くするための M0 実装で、binary 名は `hidloom-hidd` です。

例:

```bash
tools/hidloom_hidd/build.sh
bin/hidloom-hidd
USBD_HID_REPORT_SOCKET=/tmp/usbd_hid_reports.sock bin/hidloom-hidd
USBD_HID_REPORT_SOCKET=/tmp/hidloom_hidd_smoke.sock HIDD_STATUS_PATH=/tmp/hidd-status.json bin/hidloom-hidd --frames 2
```

`hidloom-hidd` は `usbd.hid_report_broker` と同じ 64-byte datagram frame を受けます。
Raw HID bridge は `USBD_RAW_HID_PATH`、`VIALD_EVENTS_SOCK`、`USBD_REPORT_SIZE` を参照し、
`HIDD_RAW_HID_BRIDGE_ENABLED=0` で無効化できます。
`--frames N` は実機 smoke や regression test 用で、N frame 処理後に自然終了して status を書きます。
systemd unit は `system/systemd/hidloom-hidd.service` にあり、Python `usbd.service` と同じ
`/tmp/usbd_hid_reports.sock` を同時に owner しないよう `Conflicts=usbd.service` を持ちます。
fresh install では unit を配置しますが、既定では enable しません。

## build_rpi_rust.sh / sync_rpi_checkout.sh / deploy_rpi_rust.sh

x86_64 build hostからRaspberry Pi用Rust daemonをcross build /
deploy する運用 helper です。`build_rpi_rust.sh` は既定で
`aarch64-unknown-linux-musl` の static ARM64 binary を
`build/rpi-rust/aarch64-unknown-linux-musl/bin/` へ出力し、`sccache` があれば自動で使います。
`cross_build_host_check.sh`はrust target、`sccache`、SSH到達性、remote checkoutの存在を確認します。
`sync_rpi_checkout.sh` は remote checkout が clean な時だけ `origin/main` へ fast-forward します。

例:

```bash
tools/cross_build_host_check.sh --device 02
tools/sync_rpi_checkout.sh --device 02
tools/build_rpi_rust.sh
tools/deploy_rpi_rust.sh --device 02 --restart
tools/deploy_rpi_rust.sh --device 02 --smoke
```

`--device 02`はrepositoryで構成した`-02` targetへdeployします。
再現buildの詳細は`docs/ops/public-source-rebuild-runbook.md`を参照してください。

## package/

x86_64 build hostでRust daemonと`matrixd`をARM64 cross buildし、release bundle /
Debian package として実機へ適用する helper です。git pull / 実機 build を避けたい
時の入口です。手順の全体像と注意点は `docs/ops/release-packaging-runbook.md` に置き、
script ごとの option と短い例は `tools/package/README.md` に置きます。

標準は split Debian package です。core package と device profile package は同じ
version を同時に install し、`hidloom-profile <profile> --apply --backup --restart` で
runtime 定義と service policy を反映します。

標準キーボード用の例:

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
tools/package/deploy_deb_verify.sh --host <device> --smoke
```

`make package-*` / `package-opt-*` / `package-deb-*` は release bundle 互換 mode
または pre-.deb rehearsal 用です。通常の更新では使わず、過去 release への復旧や
比較が必要な場合だけ runbook を確認して使います。

詳細は `tools/package/README.md` と `docs/ops/release-packaging-runbook.md` を参照してください。

## keycode_action_inventory.py

`config/default/keycodes.json` から keycode action の完全一覧表を生成する docs helper です。
分類・特殊処理・出力先ごとの扱いは `docs/keycode/action-routing-matrix.md`、生成済み表は
`docs/keycode/action-inventory.md` に置きます。

例:

```bash
python3 tools/keycode_action_inventory.py --document --output docs/keycode/action-inventory.md
python3 tools/keycode_action_inventory.py --check --document
```

## remote_boot_baseline_collect.py / boot_marker_baseline.py

Raspberry Pi の boot marker を SSH 経由で回収し、`systemd-analyze` と
keyboard input path の readiness timeline を同じ artifact にまとめます。
summary では total boot だけでなく、`keyboard_ready`、`usb->input`、
`hidd->input`、`input->ssh`、`input->network` を表示します。起動短縮では
`systemd-analyze` の合計値より、まず `keyboard_ready` と `usb->input` を見ます。

例:

```bash
make boot-report DEVICE=01
make boot-report DEVICE=02
make boot-report-reboot DEVICE=01
make boot-report-reboot DEVICE=02
python3 tools/remote_boot_baseline_collect.py operator@<keyboard-ip> --label <keyboard-host> --samples 1 --sudo
python3 tools/remote_boot_baseline_collect.py pi@<keyboard-ip> --label <keyboard-host> --samples 1 --sudo
```

`DEVICE=01/02` は `RPI_01` / `RPI_02` の SSH target と `hidloom-<DEVICE>`
label を使います。別の host を一時的に使う場合は
`BOOT_REPORT_REMOTE=user@host BOOT_REPORT_LABEL=name` で上書きできます。
`boot-report-01/02` と `boot-report-reboot-01/02` は互換用 shortcut です。

`boot-report` は現在の boot から採取します。service を手動 restart した後は
systemd の `ActiveEnter` が boot 時刻ではなく restart 時刻を指すため、boot-critical
比較では `boot-report-reboot` で再起動直後の sample を採るのが確実です。

## hidloom_logicd_core/

Python `logicd` の boot-critical input path を段階的に native 化する Rust helper です。
M1 では keymap JSON / replay で `matrix event -> basic keyboard report -> broker frame` の parity を確認し、
M2 では `/tmp/matrix_events_shadow.sock` を listen する shadow daemon として起動できます。
binary 名は `hidloom-logicd-core` です。active owner へ昇格するまでは Python `logicd` の
`/tmp/matrix_events.sock` と衝突しない shadow 検証だけを行います。

例:

```bash
tools/hidloom_logicd_core/build.sh
bin/hidloom-logicd-core --check-config
LOGICD_CORE_KEYMAP_PATH=config/default/keymap.json bin/hidloom-logicd-core --replay /tmp/matrix-events.bin
LOGICD_CORE_MATRIX_SOCKET=/tmp/matrix_events_shadow.sock LOGICD_CORE_OUTPUT_ENABLED=0 bin/hidloom-logicd-core --serve
LOGICD_CORE_PREVIEW_LOG_PATH=/tmp/logicd-core-preview.ndjson bin/hidloom-logicd-core --serve
bin/hidloom-logicd-core --ctrl-release-all
python3 tools/logicd_core_shadow_replay.py /tmp/matrix-events.bin --socket /tmp/matrix_events_shadow.sock --status /run/hidloom/logicd-core-status.json
python3 tools/usbd_hid_report_capture.py --socket /tmp/logicd-python-capture.sock --count 2 --output /tmp/python-broker.ndjson
python3 tools/logicd_python_matrix_replay.py /tmp/matrix-events.bin --output /tmp/python-broker.ndjson
python3 tools/logicd_core_parity_compare.py --core-preview /tmp/logicd-core-preview.ndjson --broker-frames /tmp/python-broker.ndjson
python3 tools/logicd_core_parity_suite.py --max-basic 80 --output /tmp/logicd-core-parity-suite.json
python3 tools/logicd_core_active_owner_preflight.py --json
sudo python3 tools/logicd_core_active_owner_smoke.py --apply --json
```

`--serve` の既定 socket は `/tmp/matrix_events_shadow.sock`、既定 output は disabled です。
systemd shadow unit は `LOGICD_CORE_MATRIX_SOCKET_MODE=0666` で、通常ユーザーの replay / tee helper からも接続できます。
制御 socket は `/tmp/logicd_core_ctrl.sock` で、`status` / `set_output` / `release_all` / `reload` を JSON line で受けます。
systemd shadow unit は停止時に `bin/hidloom-logicd-core --ctrl-release-all` を実行し、押下中 state を null report へ戻します。
replay file は既存 `matrixd` の 4 byte packet (`P00\n` / `R00\n`) を連結した binary stream です。
`LOGICD_CORE_PREVIEW_LOG_PATH` を指定すると、shadow daemon は broker 送信を無効にしたまま
`shadow_report` NDJSON に broker kind、keyboard report、broker frame preview を追記します。
`tools/logicd_core_shadow_replay.py` は recorded stream を shadow socket へ送る helper で、status counter 到達待ちもできます。
`tools/usbd_hid_report_capture.py` は一時 broker socket に届いた datagram を NDJSON 化し、
`tools/logicd_core_parity_compare.py` は core preview と broker capture の kind / payload を byte 比較します。
`tools/logicd_python_matrix_replay.py` は Python `logicd` isolated runtime に同じ matrix stream を流し、
一時 broker socket の frame を NDJSON 化します。M0 core との canonical 比較では既定で
`usb_split_keyboard.enabled=false` にし、`--keep-split-keyboard` で split route を維持します。
`tools/logicd_core_parity_suite.py` は default keymap から M0 対象の basic key / modifier chord /
`MO(n)` sequence を生成し、Rust core と isolated Python `logicd` の keyboard payload を比較します。
unsupported action は別に数え、M0 active owner 昇格条件から除外します。
M1/M2 は `KC_*` basic key、modifiers、`KC_TRNS` fallthrough、`KC_NONE`、`MO(n)`、`KC_ZKHK`、
`usb_split_keyboard.route=all` / `jis_special_us_default` の broker kind 分岐を扱い、
それ以外は no-op として `unsupported_actions` に数えます。

## logicd_core_owner_recovery.py

`logicd-core-rs` active-owner 実験から Python `logicd` matrix owner へ戻す rollback helper です。
既定は dry-run で、実行する systemd command と確認対象だけを表示します。
`--apply` を付けた時だけ `hidloom-logicd-core.service` を stop / disable し、
`hidloom-hidd`、`logicd`、`matrixd` を start して、`logicd-core` が inactive / disabled に戻ったかを確認します。
通常ユーザーから実機で実行する場合は `--sudo` を付けます。

例:

```bash
python3 tools/logicd_core_owner_recovery.py --dry-run
python3 tools/logicd_core_owner_recovery.py --apply --sudo --json
```

## logicd_core_native_owner_restore.py

`logicd_core_owner_recovery.py` で Python `logicd` matrix owner へ退避した後、
通常の native `logicd-core-rs` active owner 構成へ戻す helper です。
rollback 時に退避した native `matrixd.service` system unit を
`/etc/systemd/system/matrixd.service` へ戻し、残っている一時 `/run` unit / drop-in を削除します。
そのうえで legacy `logicd.service` を stop / disable して、
`hidloom-hidd.service`、`hidloom-logicd-core.service`、`matrixd.service`、
`logicd-companion.service` を enable / start します。
既定は dry-run で、実行には `--apply` と、実機通常ユーザーでは `--sudo` を付けます。

例:

```bash
python3 tools/logicd_core_native_owner_restore.py --dry-run
python3 tools/logicd_core_native_owner_restore.py --apply --sudo --json
```

## logicd_core_native_owner_live_smoke.py

native `logicd-core-rs` が既定 owner として動いている状態を変えずに、
`/tmp/matrix_events.sock` へ短い matrix sequence を注入し、
`logicd-core-status.json` と `hidd-status.json` の counters で
`matrix_events -> broker_frames_sent -> hidloom-hidd frames_received` の live path を確認します。
Shift-only、basic key overlap、US-sub `KC_LANG1` を対象候補にし、最後に pressed state が 0 へ戻ることも確認します。

例:

```bash
python3 tools/logicd_core_native_owner_live_smoke.py --apply --json
```

## hid_release_roll_analyzer.py

`HIDD_FRAME_LOG_PATH` で採取した `hidloom-hidd` NDJSON から、zero report flush の直後に
同じ endpoint へ次の非zero keyboard report が来た rolling 入力候補を抽出します。
release merge window を調整した後の再発確認で、勘ではなく時刻差で切り分けるための
read-only helper です。

例:

```bash
python3 tools/hid_release_roll_analyzer.py /run/hidloom/input-capture/hidd.ndjson
python3 tools/hid_release_roll_analyzer.py /run/hidloom/input-capture/hidd.ndjson --json
python3 tools/hid_release_roll_analyzer.py /tmp/hidd.ndjson --threshold-ms 16 --threshold-ms 25
```

## logicd_core_action_classification.py

default keymap の action を native core が直接処理するもの、`logicd-companion`
へ委譲するもの、transparent / no-op に分類します。M6 で timed / composite
action を core に抱え込まず companion owner として扱う境界の確認に使います。

例:

```bash
python3 tools/logicd_core_action_classification.py --output /tmp/logicd-core-action-classification.json
```

## logicd_core_active_owner_preflight.py

`logicd-core-rs` を active owner 測定へ進める直前の read-only preflight helper です。
`hidloom-logicd-core` binary、systemd unit 状態、`--check-config` の split route、rollback dry-run、
boot marker helper、runtime status snapshot を確認し、reboot 測定へ進む前の不足を JSON で返します。
service restart / enable / reboot / HID 実送信は行いません。

例:

```bash
python3 tools/logicd_core_active_owner_preflight.py
python3 tools/logicd_core_active_owner_preflight.py --json
```

## logicd_core_active_owner_smoke.py

`logicd-core-rs` を一時的に `/tmp/matrix_events.sock` owner として起動する A/B smoke helper です。
`/run/systemd/system` の一時 drop-in で `hidloom-logicd-core.service` を output enabled にし、
Python `logicd.service` を runtime mask して止めた状態で modifier 優先の synthetic matrix tap を core socket へ直接 1 回送ります。
この smoke では物理 scanner の `matrixd.service` は起動せず、core owner と HID broker の最小経路を確認します。
既定では smoke 後に `logicd_core_owner_recovery.py` を使って Python owner へ戻し、一時 drop-in も削除します。
実 HID report を host へ送るため、実行には `--apply` と root 権限を明示してください。

例:

```bash
python3 tools/logicd_core_active_owner_smoke.py
sudo python3 tools/logicd_core_active_owner_smoke.py --apply --json
```

## remote_fresh_install.py

Fresh Raspberry Pi OS host へ、開発PC側の checkout を SSH/SCP で配置し、必要なら
`setup_fresh_rpi.sh` まで実行する helper です。デフォルトでは archive を作るだけで、remote へは触れません。
`--deploy` で repo 配置、`--run-setup` を追加した時だけ remote 側で `sudo ./setup_fresh_rpi.sh` を実行します。

例:

```bash
python3 tools/remote_fresh_install.py pi@<keyboard-ip>
python3 tools/remote_fresh_install.py pi@<keyboard-ip> --deploy
python3 tools/remote_fresh_install.py pi@<keyboard-ip> --deploy --run-setup --setup-arg=--no-reboot
python3 tools/remote_fresh_install.py pi@<keyboard-ip> --remote-dir hidloom-test --deploy
```

archive 作成時は `.git/`、`.venv/`、`build/artifacts/`、`daemon/matrixd/matrixd` などを除外します。
shebang 付き script、systemd unit、Buildroot asset は LF に正規化して転送するため、Windows checkout からでも
remote Linux 上でそのまま実行できます。

## matrix_action_runtime.py

任意の action を一時的に runtime keymap へ割り当て、`matrix_events.sock` に
press / release を注入するツールです。

用途:

- 物理スイッチを押さずに `matrix_events -> logicd -> action` 経路を確認する。
- `BT_STATUS` / `BT_POWER_TOGGLE` / `BT_PAIRING_TOGGLE` などの custom action を実機で確認する。
- 確認後は元の keymap action へ戻す。

例:

```bash
sudo python3 tools/matrix_action_runtime.py BT_STATUS --row 7 --col 0
sudo python3 tools/matrix_action_runtime.py BT_POWER_TOGGLE --row 7 --col 0
sudo python3 tools/matrix_action_runtime.py BT_PAIRING_TOGGLE --row 7 --col 0
sudo python3 tools/matrix_action_runtime.py BT_DISCONNECT --row 7 --col 0
```

`ctrl_events.sock` / `matrix_events.sock` は root 所有のため、実機では通常 `sudo` が必要です。

オプション:

```bash
sudo python3 tools/matrix_action_runtime.py ACTION \
  --layer 0 \
  --row 7 \
  --col 0 \
  --hold 0.08
```

`--no-restore` を付けると一時 remap を戻しません。通常の確認では使わないでください。

## sessiond_ctl.py

`sessiond` の socket へ start / stop / status / key / write request を送る手動確認用 CLI です。
PTY terminal mirror の no-HID smoke や、`KC_SH7` 経由の動作を切り分ける時に使います。

例:

```bash
python3 tools/sessiond_ctl.py status
python3 tools/sessiond_ctl.py start --shell /bin/bash
python3 tools/sessiond_ctl.py write "pwd\n"
python3 tools/sessiond_ctl.py key KC_C --modifier KC_LCTL
python3 tools/sessiond_ctl.py stop
```

## codex_task_mailbox.py

MCP server とローカル作業用 mailbox を共有する read-only task helper です。
task JSON を検証し、許可された状態確認だけを実行して result JSON / Markdown を
`done` または `failed` へ書きます。mailbox directory は実行時に作成します。

例:

```bash
python3 tools/codex_task_mailbox.py --help
python3 tools/codex_task_mailbox.py --validate /path/to/task.json
python3 tools/codex_task_mailbox.py --mailbox /path/to/codex_tasks --run /path/to/task.json --dry-run
python3 tools/codex_task_mailbox.py --mailbox /path/to/codex_tasks --run-next --dry-run
```

## calibrate_ads1115_stick.py

ADS1115 analog stick の中心値と物理的に到達できる最小 / 最大電圧を測り、
`config/default/i2cd.json` の `analog_stick.x/y.center/low/high` へ保存する helper です。
`i2cd` はこの実測値を使って `-100..100` に正規化するため、基板や部品個体差を
速度制御へ反映できます。

例:

```bash
python3 tools/calibrate_ads1115_stick.py
python3 tools/calibrate_ads1115_stick.py --write
python3 tools/calibrate_ads1115_stick.py --phase center --write
python3 tools/calibrate_ads1115_stick.py --phase range --write
python3 tools/calibrate_ads1115_stick.py --phase validate
sudo python3 tools/calibrate_ads1115_stick.py --phase center --write --manage-i2cd-service
sudo python3 tools/calibrate_ads1115_stick.py --phase watch --sweep-duration 10 --manage-i2cd-service
python3 tools/calibrate_ads1115_stick.py --config config/boards/ver1.0/conf/i2cd.json --write
```

最初は dry-run で値だけ確認し、問題なければ `--write` を付けます。
保存時は既定で `CONFIG.bak` を作ります。
`--phase center` は中心だけ、`--phase range` は最小 / 最大だけを非対話で測ります。
`--phase validate` は ADS1115 に触らず、保存済み `center` が `low` / `high` の内側にあるか、
両軸の `span` が `--min-range-volts` 以上かを JSON で検査します。
HTTP UI の Settings からも同じ 2 段階の測定を実行できます。HTTP UI の「測定」は dry-run、
「保存」は `config/default/i2cd.json` 更新です。Settings には現在保存されている calibration と、
low/high の `span`、center が範囲内かを示す `center_valid`、span が十分かを示す
`span_valid`、両方を満たすかを示す `valid`、無効時の `errors` も表示されます。
HTTP UI の `Min span volts` は Settings GET の `min_range_volts` で初期化されます。
`analog_stick.min_range_volts` がある場合はその値、未指定時は 0.1V です。range 測定の
誤操作防止しきい値と保存値検査の判定しきい値に使います。
HTTP UI の「保存値を検査」は `--phase validate` と同じく、ADS1115 に触らず保存済み JSON だけを検査します。
HTTP UI は測定中に `i2cd` を一時停止します。CLI で daemon 起動中に測る場合は
`--manage-i2cd-service` を付け、`sudo` で実行します。
`--phase watch` は保存せず、raw voltage、正規化値、測定中 span を表示します。
range 測定は、測定中にスティックを外周まで大きく回してください。両軸の span が小さすぎる場合は
未操作として保存を拒否します。
HTTP API から `range` を保存する場合は `confirm_range=true` が必要です。

## matrixd_stability_smoke.py

実機で `matrixd` の idle stability を観測する smoke helper です。`ctrl_events.sock` で
VialRGB effect を一時的に Multisplash へ切り替え、`key_events.sock` と
`ledd_events.sock` を同時監視し、service active state、`matrixd` priority、process snapshot、
daemon journal の気になる行を Markdown report に残します。

例:

```bash
sudo python3 tools/matrixd_stability_smoke.py --duration 60 --output /tmp/hidloom-smoke/matrixd-stability-smoke.md
sudo python3 tools/matrixd_stability_smoke.py --duration 30 --value 64 --output /tmp/hidloom-smoke/matrixd-stability-low.md
sudo python3 tools/matrixd_stability_smoke.py --duration 60 --value 180 --output /tmp/hidloom-smoke/matrixd-stability-high.md
```

既定では key event、`ledd` の `t=key` message、関係 daemon の warning/error 系 log、
inactive service を検出すると失敗終了します。観測だけに使う場合は `--allow-events` や
`--allow-log-warnings` を付けます。LED state は既定で元に戻します。実機 smoke の既定 brightness は
`v=160` です。`v=180` は high-brightness 再現確認として明示指定します。

## matrixd_led_stress_sweep.py

実機で keyboard に触れず、LED effect sweep と dummy splash stress 中に
`matrixd` の ghost input が出ないか確認する helper です。
`key_events.sock` を監視して実入力発生を fail とし、dummy splash は `matrix_events.sock` ではなく
`ctrl_events.sock` の diagnostic `LED key_event` から `ledd` へだけ送るため、
matrix / InteractionEngine 入力経路を汚さずに LED 負荷だけを上げられます。

例:

```bash
sudo python3 tools/matrixd_led_stress_sweep.py --quick --duration 30 --output /tmp/hidloom-smoke/matrixd-led-stress-quick.md
sudo python3 tools/matrixd_led_stress_sweep.py --duration 60 --output /tmp/hidloom-smoke/matrixd-led-stress-full.md
sudo python3 tools/matrixd_led_stress_sweep.py --effect risky:40:128:80:255:160 --duration 60
sudo python3 tools/matrixd_led_stress_sweep.py --effect dummy30:40:32:175:77:160:30 --duration 60
```

既定 scenario は LED off、solid low、現行 Multisplash、既知 risky Multisplash、
dummy splash 10Hz / 30Hz / 60Hz です。合格条件は `key_event_count=0`、主要 service active、
daemon warning/error なしです。`ledd_key_message_count` は dummy splash では増えるため、
入力発生の判定には使いません。

## matrixd_diagnostics_snapshot.py

キー取りこぼしや ghost が再発した直後に、後から見返すための Markdown snapshot を採取する helper です。
`matrixd` 設定、systemd unit、priority、HID gadget、process、recent journal、LED state、
短時間の `key_events.sock` / `ledd_events.sock` 監視結果を 1 ファイルにまとめます。
前回 boot と直近 journal から shutdown / reboot / systemctl restart / OOM / signal などの
候補行も抽出するため、`matrixd` / `logicd` の再起動が意図した操作か異常終了かを後から切り分けやすくします。
また、`logicd` ctrl socket の `ACTIVE` / `K` 応答、daemon thread の wait channel、
UNIX socket、open fd、kernel log、pressure / memory も保存するため、service は生きているのに
入力だけ引っ掛かる状態の切り分けにも使います。

例:

```bash
sudo python3 tools/matrixd_diagnostics_snapshot.py
sudo python3 tools/matrixd_diagnostics_snapshot.py --duration 30 --since "5 minutes ago"
sudo python3 tools/matrixd_diagnostics_snapshot.py --output /mnt/p3/matrixd-diagnostics/repro.md
```

既定では `/mnt/p3/matrixd-diagnostics/` があればそこへ保存し、なければ `/tmp/hidloom-smoke/` に保存します。
症状が出たら、何度か問題のキーを押しながら `--duration 30` 程度で採取します。

## touch_flick_composition_smoke.py

4.3 inch touch flick 定義をローカルで走査し、`romaji_us_ime` composition plan の coverage を集計する read-only helper です。
HTTP server や実機入力は不要で、`config/default/touch-panel/osoyoo-4.3/flick.json` の各 pad / direction が romaji tap sequence に解決できるかを確認します。

```bash
python3 tools/touch_flick_composition_smoke.py
python3 tools/touch_flick_composition_smoke.py --json
```

## touch_flick_cdp_probe.py

4.3 inch kiosk Chromium の実 DOM に Chrome DevTools Protocol 経由で PointerEvent を送り、touch flick UI の preview / dispatch 結果を確認する実機向け helper です。
host への実入力を伴う確認で使うため、通常は `送信: ON`、host IME profile、text-send safety gate を確認してから実行します。
対象 kiosk Chromium は `HIDLOOM_TOUCH_PANEL_REMOTE_DEBUGGING_PORT=9222` 付きで起動します。
`script/start_touch_panel_browser.sh` は remote debugging を `127.0.0.1` に bind するため、
SSH 経由で実行する場合は実機上の loopback CDP endpoint を使います。

```bash
python3 tools/touch_flick_cdp_probe.py --help
python3 tools/touch_flick_cdp_probe.py --named-preset --key punct --direction left
python3 tools/touch_flick_cdp_probe.py --composition-dispatch-boundary --key ka --direction center
```

`--named-preset` は標準 `osoyoo-4.3` の `punct:left` preset を対象に、
`、。？！定` label、`named-text` badge、`TEXT(kana_a)` title / preflight metadata、
text-plan preview、dispatch result をまとめて確認します。
`--composition-dispatch-boundary` は実送信を行わず、browser 上の resolve / composition plan / dispatch payload helper を通して、
composition plan が preview envelope にだけ残り、dispatch POST payload には `event` だけが入ることを確認します。

## interaction_conditional_cdp_probe.py

Interaction tab の Conditional Layers editor を Chrome DevTools Protocol 経由で操作する実機向け DOM smoke です。
対象 kiosk Chromium は `HIDLOOM_TOUCH_PANEL_REMOTE_DEBUGGING_PORT=9222` 付きで起動します。
probe は保存操作を行わず、in-page JSON editor に一時 rule を add / remove して、
summary row、dirty state、Conditional inspector clear、`active pending-save` 表示を確認したあと元の editor 内容へ戻します。

```bash
python3 tools/interaction_conditional_cdp_probe.py --help
python3 tools/interaction_conditional_cdp_probe.py --reload
```

## logicd_event_benchmark.py

`logicd` の key event path / output fan-out / script dispatch を測るため、
任意の action を一時的に runtime keymap へ割り当て、指定レートで matrix tap を連続注入します。
測定後は既定で元の action へ戻します。

例:

```bash
sudo python3 tools/logicd_event_benchmark.py KC_A --count 300 --rate-hz 30
sudo python3 tools/logicd_event_benchmark.py KC_CONNAUTO --count 120 --rate-hz 10
sudo python3 tools/logicd_event_benchmark.py KC_SH3 --count 10 --rate-hz 1
```

`tools/perf_baseline.py` と並行して使い、`logicd` の CPU / RSS と log を比較します。

## interaction_physical_runtime.py

InteractionEngine の物理キー試験に使う runtime keymap と test 用 interaction 定義を
一時的に設定・確認・復元するツールです。
keymap は `ctrl_events.sock` へ `M` / `G` / `K` を送るだけで保存しません。
Tap Dance / Combo / Key Override は `settings.interaction` 側の definition owner が必要なため、
`apply-all` は interaction 設定を backup して test 定義を投入し、`restore-all` で戻します。

例:

```bash
sudo python3 tools/interaction_physical_runtime.py apply-all
sudo python3 tools/interaction_physical_runtime.py preflight
sudo python3 tools/interaction_physical_runtime.py status
sudo python3 tools/interaction_physical_runtime.py plan
sudo python3 tools/interaction_physical_runtime.py restore-all
```

一時割り当て:

- Layer 1 の `1` から `7` に `OSL(2)`, `LT(2,KC_A)`, `MT(KC_LSFT,KC_A)`, `TT(2)`, `TD(TD0)`, `SC_LSPO`, `SC_RSPC`
- Layer 2 の `Q` / `W` に `KC_ESC` / `KC_TAB`

test 用 interaction 定義:

- `tap_dances.TD0`: 1 tap `KC_A`, 2 taps `KC_ESC`, 3 taps `KC_TAB`
- Combo: grave (`0,1`) + `1` (`0,2`) -> `KC_ESC`
- Key Override: `KC_LSFT` + `KC_1` -> `KC_ESC`

definition だけを操作したい場合:

```bash
sudo python3 tools/interaction_physical_runtime.py apply-definitions
sudo python3 tools/interaction_physical_runtime.py restore-definitions
```

## morse_browser_smoke.py

workstation などメモリに余裕がある環境で headless Chromium を起動し、Keyboard の
HTTP UI に接続して Morse builder の `Update Morse` と `Copy MORSE(name)` が
ブラウザ DOM 上で動くことを確認する helper です。
512MB Raspberry Pi 実機では Chromium がメモリを圧迫するため実行しません。

例:

```bash
python3 tools/morse_browser_smoke.py --url https://<keyboard-host>/ \
  --page-timeout 240 --startup-timeout 180 \
  --screenshot /tmp/hidloom-morse-builder-smoke.png
```

確認内容:

- `settings.interaction` editor に `morse_behaviors.ui_smoke` が追加される。
- Morse Tree の leaf / prefix / force_commit / cancel row が生成される。
- action 入力欄へ `MORSE(ui_smoke)` が入る。

## preview_ledd_direct_pattern.py

VialRGB direct control と同じ HSV frame pattern を、Raw HID 連続送信ではなく
`ledd` 内部の描画 thread として動かす比較用ツールです。

用途:

- `script/preview_vialrgb_direct.py` の `viald -> logicd -> ledd` 経路と比較する。
- socket packet 数を 1 回の開始命令まで減らした場合の `ledd` CPU と見た目を確認する。
- 12fps / 16fps / 20fps 相当の体感差を見る。

例:

```bash
sudo python3 tools/preview_ledd_direct_pattern.py --seconds 5 --fps 12 --pattern rainbow --restore --cpu
sudo python3 tools/preview_ledd_direct_pattern.py --seconds 5 --fps 16 --pattern chase --restore --cpu
sudo python3 tools/preview_ledd_direct_pattern.py --seconds 5 --fps 20 --pattern pulse --restore --cpu
```

比較対象:

```bash
python3 script/preview_vialrgb_direct.py --seconds 5 --fps 20 --pattern pulse --restore --cpu
```

## perf_baseline.py

速度・メモリ使用量チューニング前後の baseline を Markdown にまとめる helper です。
`systemctl`、`journalctl`、`ps`、git 状態、任意で validation suite を収集します。
途中で失敗した command があっても report に exit code と stderr を残して続行します。

例:

```bash
python3 tools/perf_baseline.py --output /tmp/hidloom-perf-before.md --run-validation
python3 tools/perf_baseline.py --output /tmp/hidloom-perf-after.md --ps-samples 5 --ps-interval 2
```

## boot_marker_baseline.py

Raspberry Pi OS と Buildroot の高速起動比較に使う boot marker を Markdown にまとめる helper です。
`systemctl show` の monotonic timestamp、boot journal、`/dev/hidg*`、任意で HTTP `/api/status` を採取し、
boot-critical socket snapshot、`hidd-status.json` / `logicd-core-status.json` も採取します。
`hidg ready`、USB enumerate、`logicd ready`、`logicd-core ready`、`usable keyboard` の比較材料を残します。
systemd や HTTP が無い環境でも、失敗した command は report に exit code と stderr を残して続行します。

例:

```bash
python3 tools/boot_marker_baseline.py --output /tmp/hidloom-boot-rpi-os-baseline.md
python3 tools/boot_marker_baseline.py --output /tmp/hidloom-boot-buildroot-m1.md --no-http-status
python3 tools/boot_marker_baseline.py --output /tmp/hidloom-boot-full-timeline.md --timeline-max-sec 0
sudo -n python3 tools/boot_marker_baseline.py --output /tmp/hidloom-boot-sudo.md --no-http-status
```

The report starts with `Readiness Timeline`, which combines systemd active timestamps and
classified journal markers. Known marker kinds include USB gadget setup, HID broker startup,
native/Python logic readiness, matrix scanner readiness, companion sockets, SSH listening, and
NetworkManager/DHCP readiness. Lines that look boot-relevant but do not match a known rule are
kept as `journal-discovered` candidates so new marker types can be promoted later instead of
being silently missed. By default the readable timeline is limited to the first 90 seconds of
boot; raw command output still keeps the configured journal tail. Timeline extraction uses a
full-current-boot journal grep in addition to the tail, so early boot markers are not pushed out
by later periodic daemon logs. Use `sudo -n` when the account cannot read all unit journals.

## remote_boot_baseline_collect.py

SSH 到達できる Raspberry Pi から、`boot_marker_baseline.py`、`systemd-analyze`、
`systemd-analyze blame`、`critical-chain`、module / configfs / `/dev/hidg*` snapshot を
まとめて回収する helper です。`<keyboard-host>` のような fresh OS baseline を、
Buildroot M0/M1 と比較する時に使います。
`--reboot-before-sample` を付けると各 sample の直前に remote reboot を要求し、
SSH 復帰後に採取するため、default owner の複数 reboot cycle 証跡を同じ形式で残せます。

例:

```bash
python3 tools/remote_boot_baseline_collect.py pi@<keyboard-ip> \
  --label <keyboard-host>-fresh-os \
  --samples 3 \
  --interval-sec 10
python3 tools/remote_boot_baseline_collect.py operator@<keyboard-ip> \
  --label <keyboard-host>-native-core \
  --samples 3 \
  --reboot-before-sample \
  --sudo
```

成果物は既定では `build/artifacts/<label>-remote-boot-baseline-<timestamp>/` に置きます。
`build/artifacts/` は git 管理外なので、測定 report を repository 本体へ混ぜずに残せます。

`summary.md` extracts key `Readiness Timeline` columns from each boot marker report:
`usb`, `hidd`, `core`, `input`, `sockets`, `ssh`, and `network`. This keeps repeated samples
comparable without opening every raw journal.

The helper runs `ssh` / `scp` from the local Python process. If plain PowerShell `ssh` works
but `remote_boot_baseline_collect.py` fails its SSH transport preflight, use a Python
environment that launches the same Windows OpenSSH context, or copy `tools/boot_marker_baseline.py`
to the device and run it directly.

## usb_enumeration_watch.py

Linux USB host 側で Buildroot M1 / Raspberry Pi OS の enumerate event を Markdown に残す helper です。
`udevadm monitor` と前後の `lsusb` を採取します。monitor の各行には watcher 開始からの
`+seconds` timestamp を付けます。kernel log も見る場合は `--include-kernel-log` を付けます。

例:

```bash
python3 tools/usb_enumeration_watch.py --duration 30 --output /tmp/hidloom-usb-enumeration-m1.md
python3 tools/usb_enumeration_watch.py --duration 45 --include-kernel-log --output /tmp/hidloom-usb-enumeration-rpi-os.md
```

## buildroot_m1_compare.py

`boot_marker_baseline.py` と `usb_enumeration_watch.py` の Markdown report から、
現行 Raspberry Pi OS baseline と Buildroot M1 の主要 marker を横並びにする helper です。
M1 側の report がまだ無い場合も、現行 baseline の summary と空欄の比較表を作れます。

例:

```bash
python3 tools/buildroot_m1_compare.py \
  --rpi-os /tmp/hidloom-boot-rpi-os-native-owner-baseline.md \
  --m1-boot /tmp/hidloom-boot-buildroot-m1.md \
  --m1-usb-watch /tmp/hidloom-usb-enumeration-m1.md \
  --output /tmp/hidloom-buildroot-m1-compare.md
```

## btd_bluez_pairing_window.py

Bluetooth pairing / reconnect の実機確認窓を開く helper です。btd service を起動し直さず、
pairable / advertisement / connected device / btd log tail をまとめて確認できます。

例:

```bash
python3 tools/btd_bluez_pairing_window.py --duration 120
python3 tools/btd_bluez_pairing_window.py --duration 120 --disconnect-on-exit
python3 tools/btd_bluez_pairing_window.py --duration 120 --send-on-notify
```

## bt_reconnect_watch.py

常用 systemd service のまま、iPhone / host restart 後の再接続状態を監視する helper です。
`bluetoothctl info`、HTTP `/api/status`、`journalctl -u btd` の reset marker を並べて表示します。

例:

```bash
python3 tools/bt_reconnect_watch.py --duration 120 --interval 2
```
