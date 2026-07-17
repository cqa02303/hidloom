# Failure Patterns

実機テストや運用で見つけた失敗の恒久メモです。
単発の実行結果は private workspace reference *(omitted from public export)* に残し、
ここには再発時にすぐ検出、復旧、回帰確認できる形でまとめます。

## 記録テンプレート

```text
## <短い名前>

- symptom:
- likely cause:
- detect:
- recovery:
- regression check:
- evidence:
```

## LED startup breathing color storm

- symptom: 起動中の breathing で LED が意図しない色へ激しく変わり続ける。
- likely cause: `startup_effect` や割り込み処理より先に、LED 端子とランドの接触不良、DIN / VDD / GND、共通 GND、電源余裕を疑う。
- detect: 起動時に再現し、端子周囲を押す、またははんだを盛り直すと挙動が変わる。
- recovery: ランドとの接続だけに頼らず、端子周囲を取り囲むように広くはんだを乗せる。
- regression check: 起動直後の breathing、短時間 effect sweep、通常 brightness で色乱れが再発しないことを見る。
- evidence: 2026-07-02 に実機で、端子周囲を広くはんだ付けすると解消することを確認。

## KC_SH helper command missing

- symptom: `KC_SH3` など shell action が `/mnt/p3/script/KC_SH*.sh` まで到達するが `exit_code=127` で失敗する。またはhelper本体がpackageにあってもoperator shellからcommand名だけで起動できない。
- likely cause: package payload に `hidloom-notify`、`hidloom-key`、`hidloom-keytext`、`hidloom-oled`、`hidloom-ctrl` など helper command が含まれていない、または `/usr/bin` entrypointがなく`PATH`から解決できない。
- detect: `logicd-companion` log の `exit_code=127`、direct script 実行時のcommand not found、`dpkg-deb -c`で`/usr/lib/hidloom/bin/<helper>`と対応する`/usr/bin/<helper>` symlinkの両方を確認する。
- recovery: helper本体をpackage payloadへ含め、`/usr/bin`から`/usr/lib/hidloom/bin`へのpackage-owned symlinkを作る。checkout固有の`PATH`追加で隠さない。
- regression check: `script/test_release_bundle_tools.py`と`tools/package/release_candidate_check.sh`で5 commandのtarget/symlink一致を検査し、実機ではdirect scriptと`tools/matrix_action_runtime.py KC_SH3 --row 9 --col 1`の両方でexit 0、OLED / notify side effectを確認する。
- evidence: 2026-07-04 に `0.0.1766+git47a23ec` でhelper payload追加後、direct scriptとruntime matrix pathが復旧。2026-07-14にsplit core packageへ5個の`/usr/bin` entrypointとpackage fixture回帰を追加した。

## Touch kiosk about:blank with healthy tab URL

- symptom: touch-panel 画面が白く、Chrome DevTools `/json/list` の target URL は正しく見えるが、実際の page context は `about:blank` で body が空。
- likely cause: browser repair path が tab-list URL だけを信頼し、`location.href` と DOM body を確認せずに healthy と判断する。
- detect: `tools/touch_kiosk_health_probe.py`、または DevTools `Runtime.evaluate` で `location.href` と `document.body.innerHTML.length` を見る。
- recovery: browser startup / repair path で page context を直接評価し、空 body または `about:blank` なら kiosk URL へ navigate する。
- regression check: forced `about:blank` injection、repair、reboot 後 kiosk health probe、`wsStatus=Ready`。
- evidence: 2026-07-05 に `script/start_touch_panel_browser.sh` と health probe で修復確認。

## logicd-core route state stuck after US sub key

- symptom: key release 後に `pressed_matrix=0` / `pressed_keys=0` でも `routing.state.us_sub_key_active=true` が残る。
- likely cause: US sub routed key の release 後 cleanup が不足し、route-specific active flag が落ちない。
- detect: `logicd_core_native_owner_live_smoke.py --apply --json` 後の `/run/hidloom/logicd-core-status.json`。
- recovery: route-state cleanup を修正し、primary / modifier mirror / US sub / zenkaku-hankaku active flag を release 後に false へ戻す。
- regression check: native owner live smoke 後に `primary_key_active=false`、`primary_modifier_mirror_active=false`、`us_sub_key_active=false`、`zenkaku_hankaku_active=false`。
- evidence: 2026-07-05 に `0.0.1793+git1a8bdfed` を `<keyboard-host>` へ入れて復旧確認。

## Buildroot legal-info stops before source evidence

- symptom: `make ... legal-info`がdependency checkまたは`cp: cannot stat .../dl/<package>/<archive>`で停止する。
- likely cause: hostの`install`がuutils版、または既存outputのdownload cacheからsource archiveが消えている。
- detect: `tools/buildroot_legal_info.py --output <output> --execute --report <report>`のreturncodeとstderr、`<output>/.config`、Buildroot `dl/`を確認する。
- recovery: host設定を変更せずhelperの一時GNU `install` wrapperを使い、current outputで`--prepare-source --execute`してsourceを再取得する。`.config`がないoutputは再生成する。
- regression check: helper returncode 0、`legal-info/manifest.csv`存在、license/source directoryとchecksum生成。

## M6 source rehearsal exceeds command time budget

- symptom: clean M6 outputで`make source`がBootlin toolchainやkernel archiveの取得中にrunnerの120秒上限で終了する。
- detect: `build/artifacts/buildroot-m6-source-rehearsal.log`末尾がdownload progressで、HTTP errorやhash mismatchではなくcommand timeoutになっていることを確認する。
- cause candidate: 初回source setは80 MiB超のtoolchainを含み、回線速度に対して短いcommand timeoutを指定している。M6 defconfigやpackage選択の失敗ではない。
- recovery: Raspberry Pi実機では再実行せずx86_64 build hostで同じoutput treeを使い、十分なtimeoutで`make source`を再開する。Buildrootの一時downloadは次回取得で検証・再取得される。
- regression check: `make source` returncode 0の後、`tools/buildroot_legal_info.py --output build/artifacts/buildroot-m6-output --execute`と通常image buildを通す。

## M6 has no UART recovery console

- symptom: M6 fast-boot imageがHDMI login promptまで進まず、UART adapterにもconsole outputが出ない。
- detect: boot partitionの`config.txt`に`enable_uart=0`、`cmdline.txt`に`console=ttyAMA0`がないことを確認する。
- cause candidate: M6では通常運用の起動時間と不要device probeを優先し、UART consoleを意図的に無効化している。
- recovery: 既存Raspberry Pi OS microSDへ戻す。M6 imageを診断する場合はWindows image hostのmicroSD readerでboot partitionを開き、`config.txt`へ`enable_uart=1`、`cmdline.txt`へ`console=ttyAMA0,115200`を一時追加する。
- regression check: 通常M6へ戻す前に一時設定を削除し、HDMI 1920x1080、USB enumerate、usable keyboard時刻を再確認する。

## Buildroot Python daemons fail after path-module rename

- symptom: clean M6でLT delegated action、Vial、OLED/I2C、LEDがまとめて動作せず、native matrix/HIDだけが部分的に動く。
- detect: targetで`PYTHONPATH=/usr/share/hidloom:/usr/share/hidloom/daemon python3 -c 'import hidloom_paths, logicd.logicd, viald.viald, i2cd.i2cd, ledd.ledd'`を実行し、`ModuleNotFoundError: hidloom_paths`を確認する。
- cause: software namespaceのhard cut時に、Buildroot M6 stagingがcanonical `hidloom_paths.py`をrootfsへコピーしていなかった。
- recovery: `post-build-m6.sh`でcanonical path moduleをstageし、clean imageを再生成する。旧imageへの手動追記はしない。
- regression check: artifact verifierで`/usr/share/hidloom/hidloom_paths.py`を必須化し、ARM target Pythonでdaemon importをpassさせる。
- evidence: 2026-07-13、x86_64 host clean M6でcanonical `/usr/share/hidloom` payload、ARM imports、runtime smokeをpass。

## Buildroot companion exits when transitive Python package is omitted

- symptom: M6は起動してUSB enumerateするが、JIS側のdelegated keyが動かず、OLEDが`booting`、LEDがstartup effectのままになる。
- likely cause: `logicd.logicd`自体のimportは通る一方、runtime config適用時に初めて読む`usbd.hid_report_broker`がrootfsに無く、`logicd-companion`が起動直後に終了する。
- detect: ARM target Pythonでcompanionを実際に起動し、`ModuleNotFoundError: No module named 'usbd'`を確認する。実機では`cat /var/log/logicd-companion.log`と`test -s /run/logicd-companion.pid`を確認する。
- recovery: `post-build-m6.sh`で`daemon/usbd`をstageし、clean imageを再生成する。旧M3 router initもM6 rootfsから削除する。
- regression check: `tools/buildroot_m6_import_smoke.py`で`logicd.config_runtime`と`usbd.hid_report_broker`をimportし、`tools/buildroot_m6_runtime_smoke.py`でcompanion生存と`KC_RO`/`KC_A` split routingを確認する。
- evidence: 2026-07-13、r2 targetをQEMU ARMでforeground実行して再現。r3 buildでruntime smoke、ext4 fsck、payload検査をpass。

## logicd-core control test reads stale status snapshot

- symptom: full validation中、release fallback testだけが`injected_keys=1`を一度観測するが、単独再実行ではpassする。
- likely cause: broker release frame受信直後に非同期更新されるstatus fileを読み、release前のvalid JSON snapshotを取得する競合。
- detect: `script/test_logicd_core_rs_tool.py`のfallback testが失敗し、直後の単独実行はpassする。
- recovery: 同期応答を返すlogicd-core control socketの`status` requestで状態を取得する。
- regression check: fixture parity testを3回連続実行し、全回で`injected_keys=0` / `pressed_keys=0`を確認する。
- evidence: 2026-07-13、初回validationで1回再現、control statusへ変更後3回連続pass。

## KiCad generator silently reuses stale matrix analysis

- symptom: `build/generators/mkvial.py`が成功するがmatrix generatorはsource missingを表示し、既存`build/generated/keymap_matrix_analysis.json`を再利用する。
- likely cause: KiCad projectをsubdirectoryへ移した後も`analyze_kicad_matrix.py`が旧`kicad/keymap.kicad_sch`を参照し、missing inputをexit 0で終了する。呼び出し側もdependency失敗を無視する。
- detect: clean public exportで`python3 build/generators/mkvial.py`を実行し、`スキーマファイルが見つかりません`の後もVial生成が続くことを確認する。
- recovery: [generated artifact README](../../build/generated/README.md)記載のcanonical schematicを入力にし、sourceまたはdependency script欠落時はnon-zeroで停止する。tracked生成物はcanonical inputから再生成する。
- regression check: `make generated-artifact-check`で一時treeのmatrix / PCB / Vial生成物がtracked内容へbyte一致し、schematicを除いたfixtureが失敗することを確認する。
- evidence: 2026-07-14、standalone public exportの再生成監査で旧path参照とstale JSON fallbackを検出。

## Private machine or operator identity leaks into public export

- symptom: clean exportのdocs、tool名、test fixture、manifest pathに内部build/Windows host名または個人usernameが残る。
- detect: `tools/public_export.py`が`private_machine_hostname` / `private_personal_username` blockerを内容のlineまたはpathのline `0`として報告する。
- likely cause: 実機証跡のmachine名を再現可能なrole名と分離せず、active public sourceへ直接書いている。Unicodeのword boundaryだけでは日本語へ隣接するASCII hostnameを見逃す。
- recovery: public対象は`x86_64 build host` / `Windows test host` / `operator`等のrole名へ置換し、private実機証跡はexport対象外へ置く。tool/test/Make targetにmachine名が入っている場合は互換aliasを残さずhard renameする。
- regression check: `script/test_public_export.py`の日本語隣接fixtureで両identityのcontent/pathをblockし、実clean exportの同findingが0件であることを確認する。
- evidence: 2026-07-14、clean exportでmachine固有名62件と個人username 62件を検出し、公開対象を0件へ移行した。

## Clean export passes audit but shipped regression fails in a public clone

- symptom: clean export/readinessはpassするが、別Git cloneの`script/test_validation_suite.py`が除外済みarchive/status、`<keyboard-ip>`、`<keyboard-host>`、または欠落した説明fileで失敗する。
- detect: clean exportを一時Git repositoryへcommitして別directoryへcloneし、export treeを手修正せずfull validation suiteを実行する。
- likely cause: testがprivate-only文書を必須入力にする、sanitization対象文字列をparser/display幅fixtureへ使う、または実装とtestが参照するtracked説明fileをpublic allowlistへ含めていない。
- recovery: private-only断言だけをsource modeでskipしpublic code/docs断言は維持する。意味を持つfixtureは架空のportable値へ変更し、必要な説明fileは生成binaryを含めない明示allowlistへ追加する。
- regression check: standalone public cloneで`python3 script/test_validation_suite.py`と`python3 script/test_remote_fresh_install_tool.py`を完走し、privacy/reference/documentation auditもblocker 0を確認する。`script/test_public_ci_workflow.py`で公開CIにも同じfull suiteが残ることを検査する。
- evidence: 2026-07-14、archive依存3 code tests、private/public混在docs tests、Morse archive link、IP/hostname fixture、`bin/README.md`欠落を修正し、1164-source-file exportのfull suiteがpassした。

## Public CI drifts from the canonical validation suite

- symptom: private treeとstandalone public cloneのfull suiteはpassするが、公開CIが古い個別test一覧だけを実行し、新規regressionを検査しない。
- detect: `.github/workflows/public-ci.yml`に`script/test_validation_suite.py`がない、runnerが浮動label、または必要なsystem Python dependency、bootstrap、locked Cargo test、diff hygieneのいずれかが欠落する。
- likely cause: test追加時に手動列挙のworkflowを更新し忘れ、開発側のcanonical validation入口とCI側の入口が分岐する。
- recovery: Ubuntu 24.04とapt依存を固定し、bootstrap archive確認後に`script/test_validation_suite.py`を一度だけ実行する。locked Rust testと`git diff --check`は独立gateとして維持する。
- regression check: `script/test_public_ci_workflow.py`でworkflow契約を静的検査し、standalone public cloneでも同testとfull suiteを完走する。
- evidence: 2026-07-14、公開CIの個別test列挙をcanonical full suiteへ置換し、1165-source-file exportの独立cloneでpassを確認した。

## Mutable GitHub Action reference bypasses dependency review

- symptom: workflowが`actions/checkout@v6`等のmutable tagを参照し、同じsource revisionでも後日のCI実行内容が変わり得る。
- detect: `script/test_github_workflow_security.py`がfull-length SHA、version comment、`config/github-actions-lock.json`との一致、runner、timeout、checkout credential無効化を検査する。
- likely cause: Marketplace例をそのまま貼る、Dependabot候補のworkflowだけを更新する、またはprivate workflowをpublic CIと別policyで管理する。
- recovery: 公式release tagのcommitとlicenseを確認し、全workflow参照とaction lockを同時更新する。公開CIで使うactionはthird-party inventoryとSBOMも再生成する。
- regression check: private treeとstandalone public cloneで`script/test_github_workflow_security.py`、`script/test_third_party_inventory.py`、`script/test_public_release_readiness.py`を実行し、mutable action fixtureがreadinessで拒否されることを確認する。
- evidence: 2026-07-14、4 workflows / 5 jobs / 8 action usesをUbuntu 24.04、timeout付き、3 reviewed action SHAsへ固定し、公開SBOMへ2 CI action dependenciesを追加した。2026-07-15、private Dependabot PR #50 / #51がworkflowだけを`actions/checkout` 7.0.0 / `actions/cache` 6.1.0へ更新して同じgateで停止したため、公式tag SHA確認後にworkflow、lock、inventory、SBOM contract、policy fixtureをcommit `84173f90283b`で単一更新した。private run `29457857985`、`29457857977`、`29457857993`はsuccessし、重複PRはcloseされた。

## GitHub artifact upload drops public dotfiles and executable modes

- symptom: Actionsからclean export artifactを取得すると`.github/workflows/public-ci.yml`や`.gitignore`がなく、shell/Python helperの実行bitも失われる。
- detect: directoryを`actions/upload-artifact`へ直接渡しているか確認する。既定ではdotfileが除外され、archive upload後のfile modeは保持されない。
- likely cause: local clean export directoryが完全なため、artifact actionによる再包装時のhidden-fileとpermission semanticsを検査していない。
- recovery: `tools/public_source_archive.py`で`PUBLIC_EXPORT_MANIFEST.json`掲載fileとmanifest自身だけを決定的`tar.zst`へ格納し、通常fileを`0644`/`0755`へ正規化して、そのarchiveとSHA reportをuploadする。
- regression check: `script/test_public_source_archive.py`でhost mode差をまたぐbyte再現性、`.github`、0755 executable、0644 regular file、symlink、manifest外file除外、欠落listed file拒否を確認する。
- evidence: 2026-07-14、public export artifact workflowのraw directory uploadをportable source archiveへ置換した。

## Tracked shell entrypoint loses its executable mode

- symptom: fresh cloneで`./path/to/helper.sh`がpermission deniedとなる一方、既存checkoutやfresh-install helper経由では実行できる。
- detect: workspace permissionではなく`git ls-files --stage`または`PUBLIC_EXPORT_MANIFEST.json`のmodeを正本にし、tracked `*.sh`が実行bitを持つか`tools/repository_hygiene.py`で確認する。
- likely cause: script追加時にcontentだけをstageしたか、install helperの`chmod +x`がsource側のmode欠落を隠している。
- recovery: direct/manual entrypointのGit modeを`100755`へ修正する。Python moduleのようにinterpreterを明示して呼ぶfileへ一律に実行bitを付けない。
- regression check: `script/test_repository_hygiene.py`でGit indexとraw public manifestの非実行shellを拒否し、非実行のPython moduleは許可する。
- evidence: 2026-07-14、tracked `*.sh` 51本を監査し、manual fallback `KC_SH7.sh`とUSB gadget build wrapperの2本だけが`100644`だった。両方を`100755`へ修正し、schema v4 policyへ固定した。

## New public helper is omitted from the tools index

- symptom: canonical validationが`missing tools/README.md entry`で停止する。
- detect: 新しい`tools/*.py`を追加した状態で`python3 script/test_tools_readme.py`を実行する。
- likely cause: helper実装と公開・運用文書は更新したが、`tools/README.md`の全tool indexを更新していない。
- recovery: `tools/README.md`の該当分類へhelper名を追加し、個別test後にcanonical full suiteを最初から再実行する。
- regression check: `script/test_tools_readme.py`がtracked top-level toolを列挙し、未掲載名を拒否する。
- evidence: 2026-07-14、`public_source_archive.py`の一覧漏れをprivate full suiteで検出し補完した。

## Public publication tools create their own unlisted bytecode

- symptom: clean exportのreadinessまたは2回目のsync planが`no_unlisted_files=false`となり、`tools/__pycache__/*.pyc`だけをmanifest外fileとして報告する。
- likely cause: readiness、sync plan、archive、release/build provenance helperまたは単体回帰が隣接Python moduleをimportし、監査対象directory内へbytecode cacheを生成してからmanifest境界を再検査する。
- detect: untouched clean exportでpublication helperを連続実行し、実行前後のmanifest外pathと`find tools -name __pycache__`を比較する。
- recovery: export内でlocal moduleをimportするprocessはimport前に`sys.dont_write_bytecode = True`を設定し、生成済み`__pycache__`をexportから除去して再生成する。
- regression check: readiness、sync dry-run、sync executeと`test_remote_fresh_install_tool.py`をbytecode有効環境で連続実行し、`no_unlisted_files=true`、`export.rglob('__pycache__')`が空、standalone public cloneがcleanであることを確認する。
- evidence: 2026-07-14、repository policy validator統合時のreadiness、source provenance verifier統合時のsync plan、portable path fixtureの`repository_hygiene` importに加え、public cloneでrepository作成helperとremote fresh-install単体回帰を直接実行した際にも再発可能性を確認した。全importing publication tool/testへbytecode抑止を拡張し、bytecode有効環境のdirect execution、manifest限定clone、raw exportのすべてでunlisted file 0を確認した。

## Public sync plan omits ignored tracked lockfiles

- symptom: sync planの手順どおり新規public repositoryへstageすると、manifest掲載の`Cargo.lock`がindexへ入らず、実行helperと手動手順の結果が一致しない。
- likely cause: private repositoryではtrackedだが`.gitignore`対象のlockfileがあり、planだけが`git add -A`、実行helperは`git add -f -A`を使っている。
- detect: clean exportを新規Git repositoryへ置き、plan表示のstage commandを実行してmanifest pathと`git ls-files`を比較する。
- recovery: manifest境界を検査済みのclean exportだけを対象に`git add -f -A`でstageし、manifest掲載fileとmanifest自身以外がindexへ入っていないことを再確認する。
- regression check: `script/test_public_release_readiness.py`でplan commandが`git add -f -A`を使い、`git add -A`へ戻っていないことを固定する。standalone clone rehearsalでもmanifest path集合とtracked path集合を完全一致させる。
- evidence: 2026-07-14、repository policy milestoneのfresh public repository rehearsal準備中に、2つのtracked Cargo lockfileが通常addでは欠落する経路を検出した。

## Seeded GitHub repository prevents a clean public initial history

- symptom: 公開手順の一方は空repositoryを要求する一方、credential手順はGitHub生成README付き`main`を要求し、clean exportを初回commitにできない。
- likely cause: 通常syncのdraft PRにbase branchが必要な条件と、初回public historyをclean exportから始める条件を同じ手順へ混在させた。
- detect: `tools/public_repository_create.py plan`が`private=false`、`auto_init=false`でlicense/gitignore templateを含まず、merge commitも無効にすることを確認し、作成auditとinitial push前の`git ls-remote --heads --tags <remote>`がbranch/tag 0を示すことを検査する。
- recovery: repositoryを完全に空で作り直すか、既に公開利用されている場合は履歴を改変せず通常PRでclean exportへ移行する。force pushや既存ref自動削除は行わない。
- regression check: `script/test_public_repository_create.py`でowner不一致、既存repository、private/seeded repository、誤確認をfake GitHub API上で拒否し、`script/test_public_repository_bootstrap.py`で空bare remoteへのmanifest限定`main`だけが成功することを確認する。
- evidence: 2026-07-14、Phase 6 TODOとpublic sync credential runbookの初期化手順が矛盾していることを横断監査で検出した。

## Public root guide is a stale development completion report

- symptom: public rootのUSB guideが「セットアップ完了」と断言し、削除済み`send_key.sh`やlayout fileを案内し、未割当`0x1d6b:0x0105`を通常のdevice identityとして表示する。
- likely cause: 初期bring-up時の作業結果を入口文書として残し、実装のnative backend化、optional interface追加、public VID/PID policyへ追従させていない。
- detect: root guideが参照するpathの存在を確認し、descriptor source、`/dev/hidg0`/`hidg1`/optional `hidg2`/`hidg4`、pid.codes移行blockerと比較する。
- recovery: 完成報告を現行referenceへ置換し、暫定VID/PIDを開発rehearsal専用と明記する。値の正はconfig/scriptへ戻し、存在しないhelper手順を削除する。
- regression check: `script/test_usb_gadget_descriptor.py`でguide title、暫定ID警告、pid.codes blocker、canonical source、全interface、stale path不在を実descriptorと同時に検査する。
- evidence: 2026-07-14、public completion TODOの証跡監査でroot USB guideの削除済み2 pathと古い2-interface説明を検出した。

## Public operations guide drifts from the installed runtime contract

- symptom: public root文書がcheckout内でのRaspberry Pi native build、削除済みpath、旧`logicd.service`、存在しないhelper、またはrequiredでないHID endpointを通常手順として案内する。ad-hoc testがlive keymapを書き換えて復旧しないこともある。
- likely cause: bring-up時の完了報告と一時smokeを公開入口へ残し、split package、native core/companion、package-owned command、required/optional HID endpointへ追従させていない。
- detect: clean exportへ旧service/path/HID commandの横断`rg`を実行し、`script/test_fresh_install_docs.py`、isolated socket fixtureの`script/test_keymap_cli_helpers.py`、package extraction fixtureを実行する。
- recovery: fresh OSは`setup_fresh_rpi.sh --prepare-only`までに限定し、x86_64 hostでcore/profileをcross-buildして同一versionを同じapt transactionでinstallする。文書は`hidloom-logicd-core` + `logicd-companion`とrequired `hidg0`/`hidg1`、optional `hidg2`/`hidg4`へ揃え、復旧しないlive wrapperは削除する。
- regression check: `script/test_fresh_install_docs.py`、`script/test_daemon_readme_diagrams.py`、`script/test_keymap_cli_helpers.py`、`script/test_release_bundle_tools.py`、clean exportのcanonical validationをpassさせる。
- evidence: 2026-07-14、root install/release/keymap文書4件と関連active運用文書を現行contractへ移行し、危険なroot test wrapper 2件を削除。1173-file clean exportでblocker 0、旧標準operational reference 0を確認した。

## Read-only MCP preflight requires a disabled legacy owner

- symptom: 標準`keyboard-ver1` profileでnative ownerがすべてactiveでも、MCP `run_preflight`の`services_ok`がfalseになり、案内された復旧手順がRaspberry Pi上のcheckout buildや無効な`logicd.service`再起動を要求する。
- likely cause: MCP service allowlistとsync safety planがnative core移行前の`hidd` alias、`logicd.service`、target-side buildを標準契約として保持している。
- detect: `config/device-profiles/keyboard-ver1.json`のenable/disable一覧と`dev/mcp/keyboard/server.py`の`DEFAULT_SERVICES`、`get_sync_safety_plan`を比較し、disabled unitや`remote_rebuild_commands`が標準結果へ残っていないか確認する。
- recovery: default allowlistを`hidloom-hidd`、`hidloom-uidd`、`hidloom-outputd`、`hidloom-logicd-core`、`logicd-companion`へhard cutする。旧`logicd`/`usbd`/`spid`は明示診断時だけ許可し、更新案内はx86 cross-buildした同一versionのcore/profile split packageへ戻す。
- regression check: `script/test_mcp_keyboard_server.py`でlegacy ownerがdefaultから除外され、native unit metadataとsafe environment、package-first commands、Raspberry Pi build案内不在を確認する。`script/test_codex_task_mailbox.py`でmanual/task/result sampleも同じservice列へ固定する。
- evidence: 2026-07-14、公開対象MCP server/READMEとprivate mailbox sampleを現行native ownerへ更新し、両testをcanonical public validation suiteへ追加した。

## Public sanitizer mutates executable MCP target fixtures

- symptom: private treeのMCP testはpassするが、clean public exportをcommitしたstandalone cloneではSSH確認commandの期待値が`ssh-keygen -F <keyboard-ip>`とquoted placeholderへ分岐して失敗する。公開MCP既定targetも複数の同一placeholderへ変換される。
- likely cause: executable source/testへprivate username、RFC1918 address、内部hostname、個人home pathを直接埋め、公開時text replacementにruntime semanticsまで依存している。
- detect: clean exportを別Git repositoryへcommit/cloneし、`python3 script/test_mcp_keyboard_server.py`を実行する。private/public双方のtest sourceを比較し、target fixtureや既定tupleがsanitizationで変わっていないか確認する。
- recovery: runtime既定値を`keyboard.example`と`/srv/hidloom`へ移し、numeric IPが必要なtest fixtureはRFC 5737 TEST-NET addressを使う。SSH userと実checkout pathはhost configまたは実行時引数で解決し、実DHCP addressや個人homeはsourceへ固定しない。
- regression check: `script/test_mcp_keyboard_server.py`をcanonical suiteへ含め、private treeとmanifest限定standalone public cloneの両方で実行する。test内のportable target/default assertionも固定する。
- evidence: 2026-07-14、初回standalone public clone validationで新規canonical MCP testが失敗して検出。portable defaults/fixtureへ変更後、manifest限定cloneのcanonical 206件と追加MCP/mailbox testをpassした。

## Config save reloads an inactive legacy logicd unit

- symptom: HTTPでinteraction、settings、VIL macroを保存すると内容は書けるが502になり、native ownerのruntimeへ反映されない。status UIもdisabledな`logicd.service`のenvironmentを表示する。
- likely cause: native owner移行後もHTTP helperと物理test helperが`systemctl reload logicd`を固定実行し、status APIも同unitだけを照会している。標準keyboard profileではactive ownerが`logicd-companion` + `hidloom-logicd-core`である。
- detect: `systemctl is-active logicd-companion logicd`とHTTP保存responseの`reload.unit`を比較し、`script/test_http_interaction_api.py`、`script/test_http_system_status.py`、`script/test_interaction_physical_runtime.py`を実行する。
- recovery: activeな`logicd-companion`を優先してSIGHUP reloadし、companionがinactiveでlegacy `logicd`がactiveなtouch-panel profileだけfallbackする。どちらもactiveでなければ別unitへ黙って送らず明示errorにする。status environmentも同じ選択順にする。
- regression check: native fixtureはcompanionの`is-active`とreloadだけ、legacy fixtureはcompanion inactive確認後に`logicd` reload、両方inactive fixtureはerrorになる。実機反映時はresponseの`unit`、service journal、保存後actionを確認する。
- evidence: 2026-07-14、HTTP reload helper、status environment、interaction physical helperをactive-unit選択へ統一し、local fixtureをpassした。

## Standalone clone Rust link exhausts the temporary filesystem quota

- symptom: standalone public cloneのlocked Cargo testがlink時の`ld terminated with signal 7 [Bus error]`で止まり、再実行では`Disk quota exceeded (os error 122)`を報告する。
- likely cause: tmpfs上へ複数のclean export、clone、Cargo `target/`を保持し、memoryには余裕があっても`/tmp`のfilesystemまたはuser quotaを使い切る。
- detect: source failureと判断する前に`df -h /tmp`、`du -sh /tmp/hidloom*`、対象`target/`容量を確認し、同じsourceが別treeでpassした証跡と比較する。
- recovery: 自分が作成した古い検証treeだけをexact pathで削除し、最終cloneは一つの明示`CARGO_TARGET_DIR`を4 manifestで共有して再実行する。Raspberry Pi実機へbuildを移さない。
- regression check: standalone cloneで4つの`cargo test --locked --manifest-path ...`を完走し、終了後の`git status --short`が空であることを確認する。
- evidence: 2026-07-14、final bootstrap cloneのCargo linkに加え、今回のpublic package fixtureでも`dpkg-deb`がquota exceededを報告した。自分が作成した旧検証treeだけを削除後、canonical 206件と共有targetの0/2/3/19 testsを完走し、worktree cleanを確認した。

## Owner-derived software identifiers escape the retired-name audit

- symptom: package/service/pathはHIDloomへ移行済みでも、MCP `serverInfo`、BLE D-Bus object path、manufacturer、system drop-in、project schema、deterministic credential saltにpre-HIDloom owner由来tokenが残る。
- likely cause: 旧監査がservice prefixと旧repository slugを中心にしており、separatorや用途が異なる補助識別子をhardware profileまたはGitHub owner参照と区別できない。
- detect: active treeへ`tools/hidloom_name_audit.py`を実行し、公開exportでは`retired_software_owner_namespace`と`retired_dbus_namespace` blockerが0件であることを確認する。
- recovery: software識別子を`hidloom-keyboard`、`/org/hidloom/btd`、`HIDloom`、`90-hidloom-*`、`hidloom.*`へhard cutする。GitHub owner URLと`cqa02303v5` hardware profileだけを明示的に許可し、互換aliasは追加しない。
- regression check: name audit fixtureでpublic repository URLとhardware profileを許可し、owner由来server名とD-Bus pathを拒否する。MCP/BLE/Buildroot/setup/public exportの個別testもcanonical値を固定する。
- evidence: 2026-07-14、公開前の広域namespace検索で6用途の残存を検出し、実装・文書・scannerを同一変更で移行した。private/public canonical 206件、public export blocker 0、standalone public cloneのlocked Cargo 0/2/3/19件とclean worktreeを確認した。

## Retired-name audit requires Git metadata absent from the source archive

- symptom: Git checkoutではretired-name auditがpassするが、Release候補から展開したsource archiveで`fatal: not a git repository`と`git ls-files`の例外を出し、公開source単体の名称監査を完走できない。
- likely cause: repository hygiene、source syntax、development residueはGit indexがない場合に`PUBLIC_EXPORT_MANIFEST.json`へ切り替える一方、`hidloom_name_audit.py`だけがGit indexを直接inventoryとしていた。Release source archiveは意図的に`.git`を含まない。
- detect: `*-source.tar.zst`を一時directoryへ展開し、`.git`がないことを確認してから`python3 tools/hidloom_name_audit.py --root <extracted-root>`を実行する。
- recovery: inventoryを`repository_hygiene.tracked_files`へ統一し、root自身がGit top-levelならindex、そうでなければschema v2 public manifest掲載fileとmanifest自身を使う。archiveへGit metadataや互換用の偽repositoryを追加しない。
- regression check: Git fixtureとGit metadataを持たないraw manifest fixtureの双方で許可名をpassし、retired contentを拒否する。実Release source archiveでも1194-file inventory、名称finding 0、manifest外file 0を確認する。
- evidence: 2026-07-15、`0.1.0-dev.0bf20462a2c4`候補はbundle/checksum/binary-distribution gateをpassした後、追加raw archive名称監査だけがGit必須で停止した。manifest fallback実装後は同じarchiveをGit metadataなしでpassした。

## Private test artifact becomes a broken canonical Release link

- symptom: 移行前の非公開試験artifactを説明する公開文書が、canonical repositoryの`/releases/tag/<tag>`へlinkして404になる。文面も現在のpublic Releaseで取得できるように見える。
- likely cause: repository名称のhard cutで旧repository URLだけを新canonical slugへ機械置換し、tag / Releaseをpublic repositoryへ移行しない判断をlinkのavailabilityと分離しなかった。
- detect: 公開export中のcanonical `https://github.com/cqa02303/hidloom/releases/tag/`を抽出し、`config/publication-policy.json`の`published_release_tags`に未宣言のtagを`public_reference_audit.py`でblockする。実repositoryのRelease一覧とも公開前に照合する。
- recovery: 移行しない過去artifactへのURLと「published」表現を削除し、非公開試験bundle、pinned sourceからの再build、checksum照合として記録する。公開済みReleaseを文書から参照する場合だけtagをpolicyへ明示追加する。
- regression check: canonical repositoryの未宣言Release URLをfixtureへ追加して`undeclared_public_release_reference`を確認し、同tagをsorted/uniqueな宣言一覧へ追加した場合だけpassさせる。private/local repository拒否も同時に維持する。
- evidence: 2026-07-15、M1/M2/M3の公開候補文書6か所と、M4および旧package tagのprivate運用記録6か所が、移行していない新public repositoryのReleaseへ誤linkしていることを検出した。過去artifactをRelease非移行へ訂正し、宣言制reference gateを追加した。

## Dirty worktree export claims the current HEAD as its source

- symptom: 未commitの変更を含むpublic exportでも`PUBLIC_EXPORT_REPORT.json`が現在のHEADだけをsource commitとして記録し、同じcommitからbyte再現できないartifactをsyncまたはreleaseへ渡せる。
- likely cause: exportがtracked pathをGit objectではなくworking treeからcopyする一方、provenanceは`git rev-parse HEAD`だけを参照し、source状態をpublication contractへ含めていなかった。
- detect: source fileまたはuntracked fileを作成した状態でexportを実行し、dirty拒否、既存destination非破壊、明示draftの`source_provenance.mode=dirty-worktree`と`publishable=false`を確認する。
- recovery: 公開用exportはclean HEADから再生成する。局所検証だけは`--draft --allow-dirty-source`を使い、生成物をsync、bootstrap、archive、package、releaseへ渡さない。
- regression check: report/manifest v2でprovenance完全一致、clean publishable、selected snapshot SHA-256、正規化file modeを検査する。dirty draftはintegrity-only検証だけを許可し、readinessと全publication consumerで拒否する。
- evidence: 2026-07-14、post-commit export照合時にworking tree内容と記録HEADが分離し得ることを検出した。clean source gateとconsumer側の独立拒否へ変更し、private/public canonical 206件、public export blocker 0、manifest限定1184-path cloneのlocked Cargo 0/19/3/2件とclean worktreeを確認した。

## Internal handoff document survives the broad public docs allowlist

- symptom: public exportにoperator workflow、次回作業入口、host別handoff、完了済みの日付付きprogress/status/auditが残り、個別device、古いpackage状態、agent session、private artifact pathを現行手順のように公開する。
- likely cause: `docs/`全体を公開候補にしてprivate文書を個別除外しているため、新規または分類漏れ文書が通常のMarkdownとして選択される。
- detect: clean exportのMarkdown filenameを走査し、`*-handoff.md`、`*-next-start.md`、`*-(progress|status|audit)-YYYY-MM-DD.md`、内部workflow/layout inventoryが0件であることを確認する。
- recovery: 恒久仕様・再現runbookはsession非依存の文面とtimeless filenameへ整理する。一時引継ぎと個別証跡はprivate-onlyとして`config/public-export.json`へ追加し、公開入口の文中linkは自己完結する説明へ置換する。
- regression check: `private_documentation_path` scanner、`script/test_public_documentation_audit.py`、`script/test_public_export.py`がselected transient documentを拒否し、公開README/indexのplaceholderとbroken linkを0件に保つ。
- evidence: 2026-07-14、既存public exportの引継ぎ・次回作業・完了済み進捗/監査8文書を追加除外し、Windows研究資料のmachine-specific instance suffixとagent session表現を一般化した。clean snapshot exportは1164 source files、237 Markdown、private link 126件、private navigation 83行、broken link 0、blocker 0だった。

## Public regression test still requires a private-only document

- symptom: private canonical suiteとpublic export fixtureはpassするが、manifest限定standalone public cloneのfull suiteがprivate-only文書の`FileNotFoundError`で停止する。
- likely cause: test本体は公開対象でも、固定的な文書辞書へprivate運用文書を無条件登録し、export後の欠落を通常source欠落と区別していない。
- detect: clean exportをmanifest限定Git repositoryへcommit/cloneし、`python3 script/test_validation_suite.py`を実行する。個別には`python3 script/test_fresh_install_docs.py`で再現する。
- recovery: public契約の文書だけを常時検査し、private workspace markerが存在する時だけprivate-only文書を追加検査する。公開側で存在しない文書をdummy作成したりexportへ戻したりしない。
- regression check: `script/test_public_export.py`のexported checksへ該当testを含め、private treeとstandalone public cloneの両方で同じtestをpassさせる。
- evidence: 2026-07-14、`real-device-next-start.md`と日付付きdaemon coverage auditをprivate-onlyへ移した直後の1176-path public cloneで2件を検出した。前者は`docs/CURRENT_STATUS.md`をprivate workspace markerとして条件化し、後者は現行spec directory/mappingを正本としてaudit存在時だけhistorical照合するよう修正した。

## Unassigned pid.codes candidate is treated as an allocated runtime ID

- symptom: pid.codes候補を選んだだけでruntime descriptor、Windows driver、Vial identityへ設定し、同時申請または申請却下時に別projectとVID/PIDが衝突する。
- likely cause: 候補選定、stale/dirty checkoutやURL rewriteされたremoteでの空き確認、pull request merge、runtime移行を一つの「PID決定」として扱い、外部割当状態と確認元refをmetadataへ持たない。
- detect: `config/public-usb-identity.json`の`status`と適用guardを確認し、最新の公式pid.codes checkoutに候補directoryがないことを`tools/pid_codes_application.py --upstream-checkout`で再確認する。checkoutのstatus、`HEAD`、`origin/HEAD`、online remote `HEAD`、記録済みcommit/dateも照合する。
- recovery: 候補は`candidate-unassigned`へ戻し、現在の開発identityを維持する。cleanなfresh cloneで再確認してavailability evidenceを更新し、public source URLが参照可能になってから申請する。公式merge後だけpublic profile、descriptor、Windows driver、Vial UID/serial/product stringを同一migrationとして更新する。
- regression check: `script/test_pid_codes_application.py`がVID 1209予約範囲、canonical repository/license、申請page、upstream未指定出力、Git URL rewrite、dirty checkout、local-only HEAD、remote照会失敗、stale remote-tracking HEAD、記録証跡不一致、既存candidate、`activation_allowed=false`を固定し、public readinessがidentity/version/copyright/PID metadata driftを拒否する。
- evidence: 2026-07-14、公式pid.codes `HEAD`=`origin/HEAD`=online remote `HEAD`、ref=`refs/remotes/origin/master`、commit `a454efc3291bba72162ac3878cdda0942dd8efa7`で`1209/484C`と`org/cqa02303/`が未使用であることを再確認した。同時にpublic repository URLは404で未作成と確認したため、申請bundleは生成検証までとしPR提出はinitial public source後に順序化した。2026-07-15にもfresh公式checkoutで同commit、両path未使用、申請用2 filesの再生成を確認した。

## Unlocked build hides a missing public Cargo lockfile

- symptom: private treeとstandalone rehearsalではRust testが通るが、未使用cacheから始まるpublic CIの`cargo fetch --locked`がlockfile欠落で停止する。
- likely cause: 実行binary crateの`Cargo.lock`を一律ignoreし、回帰suite内のunlocked `cargo build`が欠けたlockfileを生成してから後段の`cargo test --locked`を実行している。後段は生成済みfileを使うため、公開Gitに含まれないことを検出できない。
- detect: build前のclean checkoutで全`tools/*/Cargo.toml`にtracked sibling `Cargo.lock`があること、`git ls-files -ci --exclude-standard`が空であること、production build/test/fetch commandが同じ行で`--locked`を指定することを確認する。
- recovery: executable crateのlockfileを全て追跡し、`.gitignore`のlockfile例外を削除する。Makefile、通常cross-build、Buildroot native build、CIを`--locked`へ統一し、fresh public cloneではunlocked buildより先にmetadata/fetch gateを実行する。
- regression check: `tools/repository_hygiene.py`がtracked-ignoreとCargo manifestのcompanion lock欠落を拒否し、`script/test_rust_lockfile_policy.py`が全crateのroot packageとactive build surfaceを横断検査する。standalone public cloneでは最初のRust commandから`cargo fetch/test --locked`を使う。
- evidence: 2026-07-14、`hidloom-outputd`と`hidloom-uidd`のlockfileがworkspaceには生成済みだがGit/public manifestには無い状態を検出した。既存rehearsalは先行non-locked buildによりこの欠落を隠していた。

## Raw legal-info blockers are mistaken for unresolved binary release blockers

- symptom: clean source exportは公開可能なのに`binary_distribution_ready=false`だけが表示され、既に作成・検証済みの対応source archiveが2件を解決しているかを同じreadiness commandで確認できない。archive verifierをexport内で実行すると未掲載`tools/__pycache__`が残り、後段manifest gateも失敗する。
- likely cause: tracked legal summaryはbundle収録前のraw Buildroot `legal-info`を正しく表す一方、source公開scopeとbinary配布scopeを結果上で区別していない。subprocess側のpublic Python toolもbytecode生成を明示停止していない。
- detect: source scopeの`binary_distribution_status`、raw blocker ID、compliance archive指定時の`resolved_release_blockers`を比較する。archive検証後はexportのmanifest未掲載fileと`__pycache__`も走査する。
- recovery: raw summaryは改変せず`binary_release_ready=false`を維持する。image配布時だけ`public_release_readiness.py --require-binary-distribution --compliance-bundle <archive>`を使い、archive全体、Buildroot commit、Bootlin version、解決blocker集合を照合する。公開verifierは`sys.dont_write_bytecode`を有効にする。
- regression check: fixtureでarchive未指定、source/toolchain不一致、正しいarchive、zstd改ざんを順に検査する。release manifestにも`binary_release_ready`と`resolved_release_blockers`を保存し、toolchain不一致を拒否する。最後にexportのunlisted fileが0件であることを確認する。
- evidence: 2026-07-14、実M6 archive 1,107,762,220 bytes / SHA-256 `037c0989cfdccc01d3abe588a003affb46016fdd02f638ca7f6e77054e455ece`を更新後verifierで再検証し、raw 2件の解決、Buildroot `67449130e9fdd71a38ca26539dddfa8c882b1977`、Bootlin `2025.08-1`、`binary_release_ready=true`を確認した。

## Shared Cargo target leaks into path-sensitive canonical tests

- symptom: standalone public cloneで4 crateを共有`CARGO_TARGET_DIR`へtestした直後にcanonical suiteを実行すると、Rust buildは成功するが`tools/<crate>/target/release`の固定binaryを起動できず`FileNotFoundError`になる。
- likely cause: operator shellの`CARGO_TARGET_DIR`をsuite childへ継承し、Cargoだけが共有directoryへ出力する一方、既存fixtureはrepository-local `target/release`をcontractとしている。
- detect: `CARGO_TARGET_DIR=/tmp/shared-target python3 script/test_validation_suite.py`または`run_suite`経由のRust fixtureを実行し、shared target使用後にlocal binary pathが欠けないか確認する。
- recovery: standaloneの明示Cargo testには共有targetを使ってよいが、canonical child test環境から`CARGO_TARGET_DIR`だけを除去する。他のPATHやcache設定は維持し、Raspberry Pi実機へbuildを移さない。
- regression check: `suite_runner.test_environment`へsentinelを渡し、PATH保持と`CARGO_TARGET_DIR`除去をvalidation suite起動時にassertする。外側へshared targetを設定した状態でpath固定Rust fixtureをpassさせる。
- evidence: 2026-07-14、manifest限定1183-path cloneのlocked Rust 4 crate後にcanonical suiteが`hidloom-logicd-core`で再現した。suite environmentを隔離後、同じ外側overrideを設定したfixture parityがpassし、shared target directoryが生成されないことを確認した。

## Linux-only path names break public checkout on Windows or macOS

- symptom: GitHub上ではtreeを閲覧できるが、Windows/macOS cloneで予約device名、禁止文字、末尾dot/space、caseだけが異なるdirectory、Unicode正規化衝突、long pathによりcheckoutが失敗またはfileが上書きされる。
- likely cause: Linuxのcase-sensitive filesystemで作成・検証したtracked pathを、そのままcross-platform public repositoryへ同期する。content scannerとgenerated artifact gateだけではfilename portabilityを証明できない。
- detect: `tools/repository_hygiene.py`で全tracked prefixをNFC/casefoldし、Windows予約名・禁止code point・末尾文字・UTF-16 lengthを検査する。Git metadataがないexportでは`PUBLIC_EXPORT_MANIFEST.json`を同じinventoryとして使う。
- recovery: collisionするpathをcanonical spellingへ統合し、予約名や禁止文字をportable filenameへrenameする。allowlistや`core.longpaths`必須化で回避しない。
- regression check: fixtureで`CON.txt`、colon、末尾dot、NFD、case-only directory衝突、180 UTF-16 unit超過、255 unit超過component、非Unicode pathを拒否し、現行private indexとstandalone public manifestをpassさせる。
- evidence: 2026-07-14、現行1238 tracked pathsを監査し、衝突・禁止名・NFC違反0、最長relative path 99 UTF-16 unitsを確認した。schema v2で導入したportable path policyをschema v3のcontent policyと共にrepository hygiene gateへ固定した。

## Checkout or generators silently change tracked text bytes

- symptom: Linux checkoutではcleanでもWindows checkout後にmanifest hashが変わる、またはgenerator再実行でfinal newlineと行末空白だけのdiffが毎回発生する。
- likely cause: `.gitattributes`が一部shell pathだけをLFへ固定し、残りのtext encoding/EOLとgenerator出力形式を暗黙のeditor既定値へ任せている。binary、空file、executable modeの例外境界も明文化されていない。
- detect: `tools/repository_hygiene.py`でprivate Git indexとraw public manifestの全fileを走査し、UTF-8 decode、BOM、CR byte、final LF、行末space/tab、空file、実行shebangを検査する。生成helper実行前後のbyte比較も行う。
- recovery: sourceとgenerated outputをUTF-8 BOMなし/LF/final newlineありへ正規化し、generator側のwriterも同時に直す。Markdown hard breakはlistまたは段落へ置換し、例外allowlistで隠さない。
- regression check: CRLF、BOM、非UTF-8、final newline欠落、行末空白、未許可empty、shebangなしexecutableをfixtureで拒否する。明示PNG binaryと2個の空package markerはpassさせ、`.gitattributes`契約も照合する。
- evidence: 2026-07-14、1238 tracked filesからCRLF/BOM/非UTF-8/executable anomaly 0件、末尾空白12 files、final newline欠落12 filesを検出した。重複を含む23 filesを正規化し、KiCad生成物のfreshness、raw public exportのmanifest外file 0を確認した。

## Deep checkout makes Unix socket fixtures exceed the kernel path limit

- symptom: 個別testとprivate cloneはpassするが、深いdirectoryに作ったstandalone public cloneだけが`OSError: AF_UNIX path too long`で停止する。
- likely cause: fixture socketをcheckout配下または長い`TMPDIR`配下の`TemporaryDirectory`へ作り、Linuxのfilesystem Unix socket path上限107 bytesを超える。source/runtimeのsocket protocol failureではない。
- detect: checkoutと`TMPDIR`を合わせて100 bytes前後まで深くし、`script/test_keymap_cli_helpers.py`を実行する。失敗時は`server.bind()`へ渡したpathをbyte長で確認する。
- recovery: 大容量のtest workspaceは指定`TMPDIR`へ維持し、filesystem socketだけをmode 0700の短い`/tmp/hl-s-*` directoryへ分離する。固定共有socket名や既存socketの削除で回避しない。
- regression check: test自身が108 bytesを超えるsynthetic `TMPDIR`を設定し、shared `temporary_unix_socket_path()`でget/set/errorの3 routeを完走する。standalone public cloneのcanonical suiteも同じ深いvalidation rootでpassさせる。
- evidence: 2026-07-14、content hygiene検証用public cloneでcanonical 322件中`test_keymap_cli_helpers.py`が再現した。短いprivate cloneではpassしていたためpath長へ切り分け、socket専用temporary pathとdeep-`TMPDIR`回帰を追加した。

## Directory-limited compile checks miss publishable source syntax

- symptom: public CIのPython compileはpassする一方、root、generator、macro、test、JSON/YAML/TOML、shell、JavaScript、SVGに壊れた構文が残り、利用時または別のjobで初めて失敗する。
- likely cause: `compileall`へ一部directoryだけを列挙し、Git/public manifestの実際の公開inventoryと検査対象が一致していない。非Python形式はcontent encodingが正しくても構文を検査していない。
- detect: Git indexまたは`PUBLIC_EXPORT_MANIFEST.json`を正本に`tools/source_syntax_hygiene.py`を実行し、形式別件数とparser availabilityを確認する。
- recovery: malformed sourceを各形式のparserが受理する内容へ修正し、必要なPyYAML、Node、shell parserをhost/CIへ導入する。未検査directoryの追加やparser不在時のskipで回避しない。
- regression check: Python、JSON、TOML、YAML、shell、JavaScript、SVGの各malformed fixtureを拒否し、manifest限定exportでも同じtestをpassさせ、`__pycache__`を生成しないことを確認する。
- evidence: 2026-07-14、全1238 tracked filesを棚卸しして606 Python、69 JSON、5 TOML、8 YAML、71 shell、20 JavaScript、2 SVGがpassした。従来のpublic CI commandが`hidloom_paths.py daemon script tools`だけを対象としていたため、inventory-based gateへ置換した。

## Public-selected changes bypass the private export workflow

- symptom: public sync直前の手動gateでは問題を検出できるが、README、daemon、config、community fileなど通常の公開対象変更ではprivate `Public export artifact check`が起動せず、privacy/readiness regressionの早期feedbackがない。
- likely cause: workflow `paths`をexport tool本体と一部config/testだけへ列挙し、`config/public-export.json`のinclude prefixes/filesと独立に保守する。
- detect: Git indexの全tracked pathへpublic export selectionを適用し、選択された各pathがworkflowのroot fileまたはprefix patternに一致するか検査する。
- recovery: root file、`.github/**`、全public include prefixをworkflow triggerへ含め、個別tool名の追加追従に依存しないsupersetへする。
- regression check: `script/test_public_community_health.py`で現行selected pathの未被覆を0件にし、root-only `*`がnested pathを誤って覆うと判定しないfixtureを維持する。PR templateとissue formの欠落・内容劣化もreadinessで拒否する。
- evidence: 2026-07-14、従来filterが通常のroot文書、daemon、Buildroot、hardware sourceを覆っていないことを検出した。最初のprefix統合も個別includeの`bin/` 2 filesを漏らしたためfixtureで検出し、18個のroot/prefix patternへ統合した。

## Unclassified tracked paths disappear from the public export

- symptom: private repositoryへ新しいroot fileまたはprivate workflowを追加してもclean exportは成功するが、public treeへ入らず、private-onlyとして除外した記録も残らない。生成helperがcacheや未承認reportを置いた場合はmanifestへ黙って収録される。
- likely cause: allowlistに一致したpathだけをcopyし、includeにもexcludeにも一致しないtracked pathを暗黙に無視する。manifest生成もdestinationの全fileを正本にするため、予定外の生成物を正当化してしまう。
- detect: `config/public-export.json` schema v2とGit indexを`tools/public_export.py`で照合し、`source_selection.unclassified_paths`、private-only件数、generated output exact setを確認する。
- recovery: 公開すべきpathはincludeへ追加し、内部運用pathは具体的な`exclude_globs`へ分類する。生成物はcanonical 12 files以外を削除し、generatorの出力境界を修正する。広いroot除外やmanifestへの予定外file追加で通さない。
- regression check: `script/test_public_export.py`で未分類tracked fixture、missing include、unsafe path、generated set drift、unexpected destination file/空directoryを拒否する。`script/test_public_release_readiness.py`はmanifest整合を維持したreport件数改ざんも`source_selection_ready=false`で拒否する。private treeはpublic 1180 / private-only 67 / generated 0、standalone public cloneはpublic 1180 / private-only 0 / generated 12へ完全分類する。
- evidence: 2026-07-14、1247 tracked pathsのうち67件が非公開だったが、private workflow 3件、Copilot instruction、`AGENTS.md`の5件はallowlist外という理由だけで暗黙除外されていた。exact private-onlyへ分類し、export前後のfile set gateを追加した。

## Clean canonical checkout accumulates ignored build output

- symptom: canonical suiteはpassし`git status`もcleanだが、その直後のpublic readinessが大量の`build/artifacts/buildroot-upstream`、Rust `target/`、native `.build/`をmanifest外fileとして拒否する。
- likely cause: validationをsource clone内で直接build/testし、ignored outputをmanifest inventoryの外に作る。canonical suiteのsnapshot隔離後も、その前後に直接実行したCargo/native buildは別経路なのでsource cloneを汚し得る。build outputはignoreされるため通常のstatus/diff checkに現れない。
- detect: clean standalone public cloneでcanonical suiteを実行した後、`public_release_readiness.py --allow-pending-pid`の`unlisted_files`とignored pathを確認する。
- recovery: outer canonical invocationはtracked sourceだけのtemporary Git snapshotを使う。standalone cloneで追加Cargo testを行う場合は`CARGO_TARGET_DIR`をclone外へ置くか、一時cloneに限って`cargo clean`後にreadinessを再実行する。主checkoutに対する`git clean`を通常手順にしない。
- regression check: clean fixtureのnested testがignored `build/ignored-output`を生成しても、temporary snapshot削除後の元fixtureに`build/`がなく、`git status --ignored`も空であることを確認する。
- evidence: 2026-07-14、manifest自身を含む1188-path public cloneでcanonical 210 entrypointsのpass後に12,000件超のmanifest外build pathを検出した。suiteのclean早期returnを除去し、常時snapshotへ統一した。同日1192-path cloneで先行Cargo test 4 crateの`target/`だけが再検出され、`cargo clean`後はunlisted 0、readiness passへ復旧した。

## Hard-cut replacement leaves duplicate canonical code

- symptom: retired compatibility nameはgrepから消えているが、同じcanonical環境変数を二度評価・設定し、shellが自分自身へfallbackし、service/build scriptが同じ行を二度実行する。browser debug output、placeholder macro、production commentのTODO marker、`NotImplemented` symbolも構文gateを通過する。
- likely cause: `OLD_NAME`と`HIDLOOM_NAME`を機械的に同じcanonical tokenへ置換し、alias削除後の式・statement・collectionを意味単位で簡約していない。通常のsyntax、名称grep、runtime happy pathはいずれも重複を拒否しない。
- detect: `tools/development_residue_hygiene.py`でGit indexまたは`PUBLIC_EXPORT_MANIFEST.json`を走査し、Python ASTの重複operand/key/environment collection/production adjacent statement、shell自己fallback・重複環境代入、debug hook、merge marker、production comment marker、Pythonの`NotImplemented` class/raise、JavaScript/Rust残渣を検出する。
- recovery: canonical値を一度だけ評価・exportする形へ簡約し、同一bodyの分岐を統合する。未実装optionは実装するかpublic surfaceから削除する。marker-like文字列dataとtest commentを禁止せず、production implementationへ例外allowlistを作らない。
- regression check: Git index fixtureとGit metadataを持たないraw public manifest fixtureで全finding種別を拒否し、readinessの`development_residue_ready`、private export/sync workflow、public CI、canonical suiteを同じtestへ接続する。
- evidence: 2026-07-14、HIDloom hard cut後にPython 8箇所、shell 12箇所、systemd 1箇所、Buildroot 1箇所、MCP環境名 1箇所、browser debug出力 1箇所と、それを固定していたtest 2箇所を検出した。2026-07-15にはcomment markerとunfinished Python symbol/raiseへ範囲を拡張し、tracked inventory全体のfinding 0を基準化した。

## Validation imports leak bytecode into the source checkout

- symptom: outer suite完走後にmanifest外`script/__pycache__`が残る、canonical前半のtestがlocal moduleをimportした直後、または手動syntax確認後に後続workspace debris gateが`tools/__pycache__`を拒否して停止する。
- likely cause: outer processだけが`sys.dont_write_bytecode`を設定し、`suite_runner`から起動する各Python childのbytecode生成をoperator環境の暗黙値へ任せている。さらに`python -m py_compile`は明示的なbytecode生成commandなので`PYTHONDONTWRITEBYTECODE=1`でもcacheを書く。clean Git statusはignored cacheを検出しない。
- detect: bytecode抑止環境変数なしでclean snapshotのcanonical suiteを実行し、workspace debris testのfindingとsuite後のrepository内`__pycache__`を確認する。
- recovery: outer suiteはlocal import前に`sys.dont_write_bytecode = True`を設定し、共通child environmentへ`PYTHONDONTWRITEBYTECODE=1`を強制する。手動syntax確認はinventory-based source syntax gateを使い、`py_compile`が必要なら`PYTHONPYCACHEPREFIX`をrepository外へ向ける。既存cacheは限定helperの`--clean`で除去し、`git clean`を通常復旧にしない。
- regression check: suite起動時に外部値`PYTHONDONTWRITEBYTECODE=0`を`1`へ上書きし、PATH保持、`CARGO_TARGET_DIR`除去と併せてassertする。canonical前半からworkspace debris gateまでと、suite後のreadiness/cache 0を確認し、手動確認後も`script/test_workspace_debris_hygiene.py`を通す。
- evidence: 2026-07-14、outer import由来のpublic cache 1件と別clean snapshotのchild import cacheを修正した。同日のdocumentation audit最終確認では手動`py_compile`がmain checkoutの`script/`と`tools/`へ2 cache directoryを作ることを検出し、限定cleanup後にbuild/venv/operator state不変、finding 0へ復旧した。

## Repository policy apply cannot safely repair audit-only fields

- symptom: repository policy auditがvisibility、archive、Discussions、legacy Downloadsのdriftを検出するが、同じapplyを再実行してもreadyにならない。
- likely cause: visibility/private/archiveは事故時の影響が大きいため自動変更せず、Discussions/legacy Downloadsは現行GitHub REST `Update a repository`のPATCH fieldに含まれない。作成時contractとread-only auditを、PATCHで修復できる設定と同一視している。
- detect: `tools/public_repository_policy.py plan`の`repository_audit_only_fields`を確認し、audit issueがそのfieldを指すか切り分ける。PATCH bodyへ未定義fieldまたはvisibility/private/archiveが入っていないことも確認する。
- recovery: repositoryを削除、rename、visibility変更、unarchiveして自動復旧しない。GitHub上の実状態と変更履歴を人間が確認し、承認済みの個別操作で戻した後にread-only auditを再実行する。通常PATCH operationの途中失敗だけは同じidempotent applyを再実行できる。
- regression check: planへaudit-only field集合と停止方針を固定し、repository PATCH bodyとの非交差、Discussions driftのaudit failure、誤確認時API call 0をfixtureで検査する。
- evidence: 2026-07-15、repository policy schema v2の最終レビューで監査対象とPATCH bodyの差を再確認し、GitHub REST API version `2026-03-10`のdocumented update fieldsへ限定した。

## Repository GET omits the create-only legacy Downloads field

- symptom: canonical public repositoryの作成は成功し、public、size 0、branch/tag 0だが、直後のcreate auditが`repository.has_downloads:mismatch`だけで停止する。
- likely cause: GitHub RESTのcreate requestは`has_downloads`を受け付ける一方、update requestには同fieldがなく、API version `2026-03-10`のrepository GETはfieldを欠落または`null`で返す。送信した`false`と観測不能を同じdriftとして扱っていた。
- detect: create POST bodyに`has_downloads=false`があることを確認し、repository GETのfield存在/valueとcreate auditの`unobservable_fields`を比較する。固定OpenAPIではcreate/update双方のproperty集合も照合する。
- recovery: repositoryを削除、再作成、visibility変更しない。create POSTの`false`は維持し、GETの欠落/`null`だけを未観測として記録する。APIが明示的に`true`を返した場合は引き続きdriftとして停止する。
- regression check: fake createはPOST bodyの`false`を完全一致で検査し、後続GETからfieldを省略してもreadyになること、`unobservable_fields`へ1件記録されること、明示`true`ではcreate/policy auditが失敗することを固定する。
- evidence: 2026-07-15、明示確認後に`cqa02303/hidloom`を作成した際に再現した。公式`github/rest-api-description` commit `3ac56be088d6fcac6feb513c2b89540765f10981`はcreateだけに`has_downloads`を持ち、live GETはfieldを省略した。修正後のlive create auditはcanonical/public/empty/settingsの4 checksすべてtrue、issue 0、未観測1件になった。

## Ambient GH_HOST redirects public repository mutations

- symptom: planは`cqa02303/hidloom`を表示するが、createまたはpolicy applyが意図したGitHub.comではなくGitHub Enterprise等の同名owner/repositoryへ作用する。
- likely cause: `gh api`へhostnameを明示せず、operator shellの`GH_HOST`、current authentication context、またはCLI既定hostへ接続先を委ねる。owner/name確認だけでは異なるhost上の同名accountを区別できない。
- detect: create/policy planの`api_host`が`github.com`であることと、fake API logを含む全command argsに`--hostname github.com`があることを確認する。`GH_HOST=github.enterprise.invalid`を設定したfixtureでも同じhost固定を要求する。
- recovery: mutationを停止し、実際に作用したhostとrepository stateをread-onlyで確認する。誤hostのrepositoryを自動削除、rename、visibility変更せず、個別の復旧判断を行う。
- regression check: policy schemaはcanonical `api_host`以外を拒否し、create/audit/applyの全fake API callがambient `GH_HOST`を上書きすることを検査する。plan/result/audit JSONにもhostを記録する。
- evidence: 2026-07-15、実public repository作成前の安全監査で両GitHub clientがhostname未指定だったことを検出し、policy schema v3とCLI fixtureへ固定した。

## Broad credential triage hides new sensitive paths

- symptom: clean exportのuntriaged warningは0のままだが、review済みscope外のfileへpassword、token、SSID等を追加しても既存の`implementation_security_keyword`へ自動分類され、個別reviewなしでreadinessを通過する。
- likely cause: `credential_word`の最終triage ruleが`path_glob: "*"`をnon-required dispositionへ割り当て、より具体的なruleに一致しない全pathを安全とみなす。
- detect: `config/public-export.json`のcatch-all dispositionを確認し、未知pathにcredential語を置いたfixtureが`*_required`になることを検査する。実exportではcredential warningのpath/disposition一覧とaction-required集合を照合する。
- recovery: 現在の意図的なdocumentation、implementation、configuration pathを明示globへ移し、catch-allを`credential_classification_required`にする。新規pathは内容を確認して最小scopeのreview済みglobへ追加するか、不要なcredential語・秘密情報を除去する。
- regression check: export contractはnon-required catch-allを`permissive-warning-triage-catch-all`で拒否し、未知fixtureをrequired、既知fixtureをreview済みdispositionへ分類する。canonical exportではpid.codes移行12件以外のrequired warningを0件に保つ。
- evidence: 2026-07-15、1075 warningの標本監査でcredential 232件中73件が`daemon/**`、58件が全体fallbackに依存していた。implementation pathをfile単位で列挙し、catch-allをfail-closedへ変更した。

## Clean snapshot validation cannot fetch pinned Buildroot source

- symptom: canonical suiteの`test_public_buildroot_rebuild.py`が`buildroot_source_prepare.py`のnon-zeroだけを示して停止し、source変更と無関係なclean snapshotでも再現する。
- likely cause: clean snapshotにはignored `build/artifacts/buildroot-upstream` cacheが含まれず、pinned sourceをGitLabから取得する。DNSまたはnetwork unavailable時は`git fetch`が失敗する。
- detect: prepare helperを一時destinationへ直接実行してGit errorを確認する。local cacheを使う場合はconfigured repository URL、pinned commit、tracked statusをそれぞれ照合し、古いcheckoutを黙って利用しない。
- recovery: network復旧後に通常fetchを再実行するか、canonical origin、pinned commit、tracked diff 0を検証済みのlocal checkoutだけをsnapshotのignored cache pathへ接続する。source config、commit、export内容、test期待値を変更して回避しない。
- regression check: local repository fixtureでclone/verify contractを維持し、clean private/public snapshotでは検証済みcacheを使ってBuildroot configureとcanonical suiteを完走する。公開CIのonline fetchは別途初回Actionsで確認する。
- evidence: 2026-07-15、GitLab hostname解決失敗を直接prepareで確認し、local checkout `67449130e9fdd71a38ca26539dddfa8c882b1977`、canonical origin、tracked diff 0を照合後にvalidationへ使用した。

## Public CI runner lacks the cross-build Rust target

- symptom: clean public `main`のcanonical suiteが終盤の`test_cross_build_host_check_tool.py`で停止し、`missing: rust target aarch64-unknown-linux-musl`を出す。それ以前のsource、privacy、runtime、native build回帰はpassする。
- likely cause: development hostにはcross-build targetが導入済みだが、fresh GitHub-hosted runnerの初期toolchainへ同targetがあると仮定し、Public CIが明示的にinstallしていない。
- detect: failed Actions logで`rustup target list --installed`相当のhost-check出力を確認し、workflow内の`rustup target add aarch64-unknown-linux-musl`がcanonical suiteより前に一度だけ実行されるか検査する。
- recovery: Public CIへcross-build targetの明示導入stepを追加して再実行する。host-checkをskipしたり、test期待値をmissing許容へ弱めたり、開発hostだけの状態でpass扱いにしない。
- regression check: `script/test_public_ci_workflow.py`でtarget導入commandの一意性とcanonical suiteより前の順序を固定し、standalone public branchの`Public CI / validate`をpassさせる。
- evidence: 2026-07-15、public初回commit `f2b99c4b3be50ba40b6acac52b6062e2d356115b`のActions run `29389956649`で再現した。runnerは`rustup`、`cargo`、`rust-lld`を持っていたがtargetだけがなく、canonical suite 218 entrypoint中のhost-checkで停止した。

## OLED layout regression depends on the CI runner hostname

- symptom: local canonical suiteではpassする`test_i2cd_direct_frame_fps.py`がGitHub-hosted runnerだけで罫線座標のexact assertionに失敗する。FPS label、daemon badge、描画処理自体はそれ以前まで正常である。
- likely cause: testがmodule import時の`socket.gethostname()`由来globalをそのまま使い、短いdevelopment hostnameでは1行、長いephemeral runner hostnameでは2行へwrapする。後続要素のY座標が1行分ずれるため、固定座標がhost identityを暗黙fixtureにする。
- detect: failed logのasserted separator座標と`i2cd._HOSTNAME`の表示幅を確認し、同testを短い値と長い値で実行してnode行数と下流Y座標を比較する。
- recovery: ready画面の固定geometryを検査するtestでは短いhostname fixtureを明示設定し、`finally`でglobalを復元する。長いhostnameのwrap behaviorは専用testで独立に検査する。
- regression check: FPS表示あり/なしの両ready testが同じ短いfixtureを使い、`test_long_node_name_wraps_to_two_lines`だけが長いfixtureと2行配置を要求する。standalone public CIでcanonical suiteを再実行する。
- evidence: 2026-07-15、cross-build target修正branch `8efdde63b52fc900ee0943d0726246c05a4ca005`のActions run `29392276992`でhost-check通過後に再現した。失敗点は`[(1, 33), (62, 33)]`の罫線だけで、ambient hostnameをfixture化して切り離した。

## Compressed archive middle-byte tamper remains semantically valid

- symptom: 同じpublic commitのpush validationはpassする一方、pull-request validationではcompliance bundle tamper fixtureがreadiness exit 2を返さず停止する。untampered bundleのverifyとbinary readinessはどちらもpassする。
- likely cause: `.tar.zst`の中央byteを反転するだけでは、zstd versionや圧縮layoutによってtar padding等の意味を持たない領域に当たり、展開・payload checksum検査をすべて通る場合がある。byte差分とsemantic corruptionを同一視している。
- detect: tampered commandのreturn codeとstdout/stderrをassertionへ含め、同じfixtureを複数runner/eventで実行する。archive先頭magicと検証対象payloadのどちらを壊したかを区別する。
- recovery: invalid archive経路のfixtureはzstd magic headerを決定的に破壊し、verifierが展開前に必ず拒否する入力にする。semantic payload改ざんは展開directory内の収録fileを変更して再packする別fixtureで検査する。
- regression check: `script/test_public_release_readiness.py`がheader破損bundleをexit 2、issue `compliance-bundle-verification-failed`で拒否し、失敗時はchild stdout/stderrを表示する。push/pull_request双方のPublic CIでcanonical suiteをpassさせる。
- evidence: 2026-07-15、public draft PR #3のrun `29394739762`で中央byte反転がexit 2にならず再現した。同じcommitのpush run `29393880518`では同fixtureがpassしており、publication sourceではなくtamper生成の非決定性と切り分けた。

## Pre-policy GitHub defaults abort repository audit

- symptom: 空repositoryを初回pushした後、policy適用前のread-only auditが`selected-actions`の409 Conflictでerror payloadを返し、未保護`main`まで監査できない。
- likely cause: Actionsが`allowed_actions=all`の間はselected-actions APIが409を返し、branch protection未設定時はprotection APIが404を返す。どちらも期待されるpolicy driftだが、transport failureと同一扱いにしていた。
- detect: 実repositoryでactions permissions、selected-actions、workflow permissions、private vulnerability reporting、branch protectionを個別GETし、成功payloadと409/404を区別する。audit結果がerror schemaではなく、全差分を持つaudit schemaになることを確認する。
- recovery: repository設定を変更せず、actions permissionsが`selected`でない場合はselected-actions GETを省略し、未保護branchの404を空snapshotとして比較する。その後、明示確認付きpolicy applyまで`ready=false`を維持する。
- prevention: fake GitHub fixtureで`allowed_actions=all`、selected-actions 409、branch protection 404を同時再現し、5 GET、selected-actions省略、actions/branch双方のdrift issueを固定する。未知statusや、selected設定後のAPI failureは引き続きerrorとして停止する。
- evidence: 2026-07-15、`cqa02303/hidloom`のpolicy適用前auditでselected-actionsが409、branch protectionが404、workflow PR approvalが`false`であることをread-only確認した。repository policy、visibility、branch、workflowは変更していない。

## Public bootstrap regression misclassifies linked Git worktrees

- symptom: `script/test_public_repository_bootstrap.py`をlinked worktreeで実行すると、private sourceからclean exportを作らずworktree rootをpublic exportとしてbootstrap planへ渡し、`PUBLIC_EXPORT_REPORT.json`欠落等で停止する。
- likely cause: private checkout判定が`(ROOT / ".git").is_dir()`だけを使う。通常cloneでは`.git` directoryだが、`git worktree add`先では`.git`はgitdirを示すfileである。
- detect: linked worktree rootの`.git` typeを確認し、bootstrap testが一時exportを生成したかを確認する。public exportには`.git`自体が存在してはならない。
- recovery: source checkout判定を`.git`のfile/directoryに依存しないexistence判定へ変更する。public export側の`.git`拒否contractは緩和しない。
- regression check: `.git` file markerを持つfixtureをcheckout、markerなしdirectoryをexportとして判定し、通常clone、linked worktree、standalone public exportの各実行modeでbootstrap testを通す。
- evidence: 2026-07-15、exact staged treeをlinked worktreeで検証中に再現し、判定helperとfile marker fixtureを追加した。

## Incremental cross-build output redeploys retired binaries

- symptom: tracked sourceとclean public exportの名称監査はpassするが、hostのignored `bin/`とcross-build `bin/`にhard cut前の実行物が残り、Rust deployがcanonical binaryと一緒に実機checkoutへ再送する。
- likely cause: build wrapperがcanonical filenameだけを上書きし、出力directoryの旧fileを削除しない。`deploy_rpi_rust.sh`も必要な4 fileを検証した後にdirectory全体をrsyncするため、検証対象外のstale artifactを含める。
- detect: `tools/generated_binary_hygiene.py`でlocal `bin/`、`build/rpi-rust/*/bin`、`build/rpi-hidloom-send/*/bin`、`build/rpi-usb-gadget-fast/*/bin`と明示出力先を走査する。deploy scriptのrsync sourceがcanonical 4 fileに限定されていることも確認する。
- recovery: `--clean`でretired prefixを持つ通常file/symlinkだけを削除し、canonical/unrelated fileとdirectory/special fileは勝手に消さない。各build wrapperはinstall前にcleanupし、deployは4つのcanonical Rust pathを個別引数で送る。
- regression check: repository内4種類とrepository外の明示bin fixtureを検出・除去し、canonical/unrelated file保持、retired directory拒否、8 build/deploy wrapperのcleanup、directory rsync不在を固定する。raw public exportでも同じtestを実行する。
- evidence: 2026-07-14、host `bin/` 5件、ARM64 C helper 5件、Rust GNU/musl各4件、USB gadget 1件の計19 retired binaryを検出した。tracked sourceには存在せず従来gateの対象外だったが、Rust deployのdirectory rsyncで実機へ混入し得たため選択除去した。

## Ignored local dotenv retains retired variable names

- symptom: tracked/public name auditはpassするが、desktopからの実機accessだけがcanonical `HIDLOOM_*`設定を受け取れない。
- detect: `python3 tools/local_environment_hygiene.py`でignored `.env`のassignment名、重複、syntax、symlink、modeを検査する。stdout/stderrへvalueやassignment全文を出さない。
- likely cause: software namespace hard cutがtracked sourceとruntime configだけを対象にし、credentialを含むignored local fileを意図的に変更対象外へ置いた。
- recovery: `--rewrite-retired-keys`のdry-runでkey mappingだけを確認し、operator承認後に明示token付き`--apply`を使う。atomic replaceでmode `0600`とvalue byteを維持し、secret-bearing backupやcompatibility aliasを作らない。
- regression check: canonical/missing/retired/duplicate/malformed/unsafe mode/symlinkに加え、dry-run byte不変、誤token、canonical collision、tracked value内のretired文字列非置換、atomic apply後のmode/value、temporary/backup不在を確認する。全outputにfixture valueがないことをassertする。
- evidence: 2026-07-14、development checkoutの`.env`は31 assignmentすべてがretired prefix、canonical name 0件だった。dry-runは31 mappingを返し、SHA-256、inode、1447-byte size、mode `0600`が不変で、applyは実行していない。

## Line-oriented ignored inventory hides disposable caches

- symptom: Git indexとpublic exportはcleanだがsource directoryに古い`__pycache__`やpytest cacheが残る。ignored pathのtop-level集計には実在しない引用符付きrootも表示される。
- detect: `python3 tools/workspace_debris_hygiene.py`を実行する。ignored pathの全体集計が必要な場合は`git ls-files --others --ignored --exclude-standard -z`をNUL区切りで解析する。
- likely cause: bytecode隔離導入前の直接実行がcacheを残し、line-orientedなGit出力は非ASCII pathをC-style quoteする。162万件規模のBuildroot outputが小さいsource cacheを件数上も隠す。
- recovery: `--clean`でdisposable cacheだけを削除する。`build/`、Rust `target/`、native `.build/`、venv、release output、backup、credential、mailboxは削除せず、review findingを人間が判断する。
- regression check: cache/bytecode/coverageだけが消え、preserved root、root `.env`、backup、nested environment file、tracked debris、symlinkと外部targetが残ることをfixtureで確認する。値やfile内容はstdout/stderrへ出さない。
- evidence: 2026-07-14、NUL-safe inventoryでignored 1,622,414 pathsは`build/`、830 pathsは`.venv/`と確認した。source領域のcache directory 10個だけを除去し、再監査finding 0、`.env` mode `0600`、build/venv件数不変だった。

## Small exact copies bypass a large-file duplicate gate

- symptom: repository hygieneはpassするが、project directoryごとの同一README、生成BOM、局所`.gitignore`など小さいcopyがtracked treeへ残り、どれが正本か公開利用者に伝わらない。
- likely cause: exact duplicate検査を1 MiB以上へ限定し、hardware sourceの巨大copyだけを事故とみなしていた。生成物や短いpolicy fileはsize threshold未満なので無条件に通過する。
- detect: Git indexまたは`PUBLIC_EXPORT_MANIFEST.json`の全non-empty fileをSHA-256でgroup化し、`config/repository-hygiene.json`の完全なpath-set例外と照合する。
- recovery: 再生成可能なKiCad CSV/JSONを削除し、project READMEは親へ、native `.build/` ignoreはrootへ統合する。独立配布packageのlicense/hash、self-contained profile/projectだけを理由付きで許可する。
- regression check: 1 byte以上の未承認pair、許可pairへの第三file追加、許可fileの内容分岐、path欠落をfixtureで拒否する。canonical private treeとmanifest限定public exportでは全許可pathの存在とbyte一致を確認する。
- evidence: 2026-07-14、14 duplicate groupを分類し、再生成物4 files、重複README 2 files、局所ignore 2 filesを削除した。残る10 groupはexact path-set例外へ固定し、repository hygieneとfixture回帰をpassした。

## Unassigned public USB identity leaks into runtime defaults

- symptom: 公開用VID/PID候補やHIDloom descriptor stringを決めた直後、現行Windows/Vial互換設定まで書き換わる、未割当候補を実機へ適用できる、またはUSB descriptorとBLE PnP IDが別値になる。
- likely cause: pid.codes申請metadata、現行runtime identity、将来のpublic identityを同じ設定objectで管理し、割当状態、生成可否、USB/`btd`へのenvironment配布を別々の手順に任せている。
- detect: `python3 tools/public_usb_identity.py`でprofile、現行`config/default/config.json`、3つのVial定義、BLE PnP source、2つのsystemd consumer、assignment evidenceを一括検査する。`candidate-unassigned`中の`public_formal --output`が非zeroになることも確認する。
- recovery: runtimeは`development_compatibility`へ戻し、public profileを`blocked-until-pid-codes-merge`、release許可false、allocation evidence nullへ戻す。`/etc/hidloom/usb-identity.env`を削除してUSB gadgetと`btd`を再起動し、片側だけへdescriptorを手作業適用しない。
- regression check: `script/test_public_usb_identity.py`が互換値drift、公開manufacturer/product/serial/Vial name/UID drift、BLE default drift、共有EnvironmentFile欠落、割当前生成、source tree内出力、unsafe overwriteを拒否し、割当済みfixtureだけで決定的`usb-identity.env` bundleを生成する。
- evidence: 2026-07-14、schema v2でprivate互換とpublic正式profileを分離した。2026-07-15、schema v5でBLE PnP IDを同じVID/PIDへ接続し、USB gadgetと`btd`が固定pathの同一environment fileを読む契約を追加した。

## Selectable unfinished backend survives publication audit

- symptom: CLI helpやconfigurationでbackend/transportを選択できるが、選ぶと`NotImplemented`例外、常時error、または実処理のないclassへ到達する。
- likely cause: interface設計用のstubと実装済みbackendを同じselectorへ登録し、選択肢の存在を将来計画として残したまま公開準備を進める。
- detect: CLI `choices`、backend factory、enumを実装classと照合し、`tools/development_residue_hygiene.py`でproductionの`NotImplemented` class/raiseを検査する。READMEが実装済み経路だけを案内することも確認する。
- recovery: 公開時点で動かない選択肢、stub class、専用例外を削除し、実装済み経路だけへhard cutする。将来候補はruntime selectorではなく設計文書のunsupported境界に置く。
- regression check: `script/test_spid_backend.py`でADNS-3530をunknownとして拒否し、`script/test_btd_backend_selection.py`と`script/test_btd_bluez_backend.py`でBLE以外のtransport surfaceがないことを固定する。
- evidence: 2026-07-15、未実装ADNS-3530 backendとBlueZ classic/auto transport surfaceを削除し、PAW3805EKとBLE HOGPだけを現行実装として残した。

## Public specification retains private completion history

- symptom: standalone public cloneの仕様文書がprivate archive、内部TODO、日付付き進捗を参照するか、完了済み項目を大量に列挙して現行仕様を見つけにくくする。
- likely cause: private側の作業台帳を公開対象のdesign/keycode文書として流用し、完了時にcontractだけへ圧縮していない。
- detect: selected public Markdownからprivate-only pathとarchive linkを走査し、design backlog、unsupported一覧、status文書が現行sourceだけで意味を持つか確認する。standalone cloneで対応するdocumentation testを実行する。
- recovery: 完了履歴を削除して現行decision、supported/unsupported境界、検証入口だけを残す。実装済みTODO文書はstatus/referenceへ改名し、private archiveへのlinkを公開側へ戻さない。
- regression check: `script/test_current_todo_completion.py`、`script/test_unimplemented_keycodes_doc.py`、`script/test_morse_documentation.py`、`script/test_public_documentation_audit.py`をprivate treeとpublic cloneの両方でpassさせる。
- evidence: 2026-07-15、design backlogとkeycode文書を自己完結する現行contractへ圧縮し、Morse HTTP route TODOを実装済みstatusへ移した。

## Public documentation has no route from the repository README

- symptom: public exportのbroken linkは0件だが、仕様templateやnested runbookへREADME/indexから辿れず、公開利用者には存在しない文書と同じ状態になる。
- likely cause: link targetの存在だけを検査し、公開rootからのgraph reachabilityを確認していない。カテゴリ直下の一覧testもnested directoryや先頭underscoreの文書を覆わない。
- detect: `PUBLIC_DOCUMENTATION_AUDIT.json.summary.orphaned_documents`を確認し、`python3 script/test_public_documentation_audit.py`でroot `README.md`から全`docs/**/*.md`への到達性を再計算する。
- recovery: 文書を正しいカテゴリindexからlinkするか、不要・内部運用文書なら削除または明示private-onlyへ分類する。code fence内の例示linkや生成reportの手書き変更で到達済みにしない。
- regression check: directory linkを配下`README.md`へ解決し、fenced-code内だけに現れるlinkをnavigationとして数えず、孤立fixtureを`public_documentation_orphan`で拒否する。readinessはmanifest hashを更新した偽のorphan countも実treeとの再計算差分で拒否する。
- evidence: 2026-07-14、公開対象Markdown graphで187件を監査し、`docs/daemon/specs/_template.md`と`docs/ops/kc-sh/README.md`の2件だけが孤立していた。各正本indexへ導線を追加し、documentation audit schema v2へ到達数と孤立pathを固定した。

## Branch protection requires a workflow display name instead of a check name

- symptom: Public CIはpassしているが、policy適用直後にPRが`CLEAN`から`BLOCKED`へ変わり、required checksは0件と表示される。
- likely cause: branch protectionのcontextへworkflow表示名とjob IDを連結した`Public CI / validate`を設定した。GitHubのcheck run名はjob ID由来の`validate`なので一致しない。
- detect: branch protection APIの`required_status_checks.contexts`、commit check-runs APIの`name`、`gh pr checks --required`を比較する。combined statusがpendingかつstatus 0件でもcheck-runsに`validate` successがあれば名称不一致を疑う。
- recovery: required contextを実check run名`validate`へ修正してpolicyを再適用する。status checkを無効化したりadmin bypassでmergeしたりしない。
- regression check: `script/test_public_repository_policy.py`で期待contextを`validate`へ固定し、`script/test_public_ci_workflow.py`で同名job IDがworkflowに存在することを検査する。
- evidence: 2026-07-15、PR #8のhead `0372d1570a1e0c2032862876eaa9feb96fd854e4`には`validate` successが2件あったが、適用済みpolicyは`Public CI / validate`を要求してPRを`BLOCKED`にした。

## Nonblocking logicd-core control response is truncated

- symptom: GitHub Actionsの`Public CI`が`Full regression suite`で停止し、`script/test_logicd_core_rs_tool.py`のcontrol socketがJSON途中までを受信した後、改行を待ってtimeoutする。同じruntime sourceでもprocess schedulingによりpassする場合がある。
- likely cause: accepted control streamをnonblockingにしたまま`writeln!`で大きなstatus JSONを一度だけ書き、partial writeまたは`WouldBlock`を無視していた。clientが同時に読み進めない環境では応答後半が永久に失われる。
- detect: control timeoutへ受信済みbyteを含め、hexを復号してJSON prefixがあり末尾改行がないことを確認する。process exitやRust panicがなく、受信長が完全なstatus responseより短ければtimeout延長ではなくserver write pathを疑う。
- recovery: responseをclient別queueへ積み、nonblocking writeのpartial byte数だけqueueを進める。`WouldBlock`では保持して次のpollで再送し、read half-close後もpending responseをflushしてからclientを除去する。mutation commandを無条件retryしない。
- regression check: Rust unit testで1245-byte partial writeの直後に`WouldBlock`を返し、次回flushで4097 bytesが完全一致することを確認する。Python integrationではstatus request 256件を読み始めずに溜め、全responseが改行付きで復号できることを確認してからcanonical validationとGitHub Actionsを通す。
- evidence: 2026-07-15、private run `29412512202`、`29414487191`、`29415647440`、`29418520277`が2秒timeoutで失敗した。test deadlineを10秒へ延長したrun `29450659981`も失敗したが、診断には完全なstatusより短い1245 bytesの有効JSON prefixが残り、末尾改行がなかったためserver partial writeを特定した。exact pre-fix binaryは256-response backpressure回帰でtimeoutし、queue実装は同回帰25回、Rust 20 tests、canonical 218 entrypointsをpassした。

## Public split package release is rejected as multiple deb assets

- symptom: public Releaseに`hidloom-core`とdevice profileの2個の`.deb`が正しく存在しても、download helperが`expected exactly one .deb asset`で停止し、fresh Raspberry Pi OSへ標準package経路で導入できない。
- likely cause: legacy single package用の「`.deb` 1個 + `.deb.sha256` 1個」契約を、split packageとBuildroot imageをまとめるpublic Releaseでも使い続けている。
- detect: Release asset一覧に`hidloom-core_*_arm64.deb`、`hidloom-profile-<profile>_*_arm64.deb`、`SHA256SUMS`がある状態で`tools/package/install_github_release_deb.sh --tag <tag>`を実行し、asset数だけで拒否されるか確認する。
- recovery: profileを明示してcore/profileだけを選択し、`SHA256SUMS`、package名、arm64 architecture、同一version、profileのexact core dependencyを検証する。remoteでは2個を同じapt/dpkg transactionへ渡し、install後に`hidloom-profile <profile> --apply --backup --restart`を実行する。legacy releaseだけを単一package fallbackへ残す。
- regression check: `script/test_release_bundle_tools.py`でfake GitHub Releaseと実Debian fixtureを作り、2 assetのdownload/checksum/metadata、同一apt transaction、profile適用を確認する。`script/test_public_release_bundle.py`でRelease notesがRaspberry Pi OS packageとBuildroot M6 imageの両方を案内することも固定する。
- evidence: 2026-07-16、`keyboard-ver1`のcore/profile fixtureでdownload-onlyとremote install commandをpassした。GitHub Release、Raspberry Pi、Buildroot runtimeは変更していない。

## Bot-created sync PR requires first-time contributor approval

- symptom: sync branchのpush `validate`とdraft PR作成はsuccessするが、直後の`pull_request` runがjob 0件、conclusion `action_required`で終了し、PRはCI未完了の`UNSTABLE`になる。
- likely cause: public repositoryのfork PR approval policyが`first_time_contributors`で、`Public CI / open-sync-pr`が作成した最初のPRのactor `github-actions[bot]`にmerged contributionがない。source、workflow syntax、selected action allowlistの失敗ではない。
- detect: PR authorが`github-actions[bot]`、headが同一repositoryの期待`sync/*` branch、run eventが`pull_request`、head SHAがpush済みcommitと一致、jobs APIが0件、push runの`validate`がsuccessであることをすべて確認する。jobまたはlogがある通常のCI failureと混同しない。
- recovery: repository ownerがGitHub UIまたは`POST /repos/{owner}/{repo}/actions/runs/{run_id}/approve`で対象runだけを承認し、生成された`validate` jobをsuccessまで監視する。repository全体のapproval policy、branch protection、required check、Actions allowlistを弱めず、PRをadmin bypassでmergeしない。
- regression check: runbookはbot初回PRの検出条件、単一run承認、pull-request `validate`再確認を要求する。実同期ではpush/pull_request両runのhead SHA一致、PR `MERGEABLE` / `CLEAN`、policy audit issue 0、public `main`不変を証跡化する。
- evidence: 2026-07-16、draft PR #9のrun `29465864588`がactor `github-actions[bot]`、same-repository head `f1e08b0a432cf6c8add0db62bf017f256508a72b`、jobs 0件で`action_required`になった。owner approvalはHTTP 201で受理され、run `validate`は14m57sでsuccess、PRは`CLEAN`になった。push run `29465211535`もsuccessし、public `main`とapproval policyは変更していない。

## Merge auto-delete removes the sync source branch

- symptom: PRを正常にsquash mergeした直後、監査済みsource branch `sync/*`が404になり、merge済みPRのhead SHAだけがsource commitを参照する。
- likely cause: canonical public repository policyが`delete_branch_on_merge=true`で、branch保持可否をmerge前に決めず既定の自動削除を受け入れた。merge source、tree、CIの失敗ではない。
- detect: merge前後のrepository `delete_branch_on_merge`、PR head SHA、`git/ref/heads/<branch>`、public `main`、merge commit treeを比較する。main treeがPR head treeと一致し、branchだけが404ならauto-deleteと判断する。
- recovery: 同名`sync/*`を直ちに再作成しない。branch作成pushはPublic CIと`open-sync-pr`を再起動し、差分のない重複PR作成を試みるためである。保持が必要ならmerge前に明示承認を得てauto-deleteを一時停止し、merge後にcanonical `true`へ戻してpolicy auditする。削除後の復元はPR head SHAを使う個別判断とし、自動化しない。
- regression check: public sync runbookはmerge前のbranch保持決定、auto-delete一時停止時の承認・復元・audit、保持不要時の削除証跡を要求する。post-merge監査はmain/head tree一致、main CI success、open PR 0、policy issue 0を確認する。
- evidence: 2026-07-16、PR #9をhead `f1e08b0a432cf6c8add0db62bf017f256508a72b`からsquash mergeし、public `main`は`b5f1933dda5741977ef93499a149b50c195e34e5`になった。両treeは`2d465b75e610692aa699a5cf4a7ee36bd6b2ce09`で一致し、main run `29468677881`もsuccessしたが、source branchはcanonical auto-deleteにより404になった。重複automationを避けるため復元していない。

## pid.codes validator dependency failure is mistaken for application rejection

- symptom: fresh pid.codes checkoutで`python3 -m test.validate_pids`を実行すると、申請pageを検査する前に`ModuleNotFoundError: No module named 'frontmatter'`で終了する。
- likely cause: upstream validatorの`requirements.txt`を導入していないhost Pythonで直接実行した。front matter、owner、PID競合、licenseの不合格ではない。
- detect: tracebackが`import frontmatter`で停止し、validator自身のerror一覧や`No errors found!`が出ていないことを確認する。生成前のfresh clone `HEAD=origin/HEAD=online remote HEAD`と候補path未使用も別に確認する。
- recovery: disposable cloneと一時venvを使い、`python3 -m venv <temporary-venv>`、`pip install -r requirements.txt`、`python -m test.validate_pids`の順で再実行する。system Pythonへinstallせず、upstreamへのcommit / pushやruntime VID/PID適用は行わない。
- regression check: HIDloom側の`script/test_pid_codes_application.py`と`script/test_public_usb_identity.py`に加え、生成した2 filesをdisposable upstream cloneへ置いた公式validatorと`git diff --check`をpassさせる。patchが空でないことと変更fileが2件だけであることも確認する。
- evidence: 2026-07-16、公式commit `a454efc3291bba72162ac3878cdda0942dd8efa7`で初回実行は`frontmatter`不足により終了した。隔離venvへ`python-frontmatter==1.3.0`と`PyYAML==6.0.3`を導入した再実行は`No errors found!`、2 files / 15 insertionsのpatchは725 bytes / SHA-256 `76f255e3280497461eb0b0fbec260f35b5029447263a1c646c40888d892bc6c0`だった。

## pid.codes owner directory text trips the retired-name audit

- symptom: identity helperとpid.codes validatorはpassするが、GitHub Actionsのfull regression suiteが`test_hidloom_name_audit.py`で停止し、status文書のowner directory行だけをfindingにする。
- likely cause: pid.codes directoryを末尾slashなしで記録し、repository owner文字列を含む旧software path検出へ一致させた。候補競合、license、runtime identity、hardware名の不一致ではない。
- detect: `tools/hidloom_name_audit.py`のfindingを列挙し、該当行が公式directoryを示すか、retired software command / package / socketを示すかを区別する。GitHub Actionsでは`Public CI / validate`の`Full regression suite` logを確認する。
- recovery: 公式directoryを`1209/484C/`と`org/cqa02303/`のようにslash終端で記録する。retired-name patternやactive source audit対象を緩めず、owner aliasや互換software名を追加しない。
- regression check: `script/test_hidloom_name_audit.py`、`script/test_current_status_doc.py`、docs gate、隔離snapshotの`script/test_validation_suite.py`をpassさせる。public exportでも同じactive source auditを維持する。
- evidence: 2026-07-16、private commit `cf89c4e37405`のPublic CI run `29490175164`はstatus文書1行だけを検出して停止した。slash終端へ正規化後、focused auditとCI同等full validation suiteはpassした。

## Split package dry-run misses a hard-cut file owner

- symptom: core/profileを同じ`apt-get -s install`で確認すると成功するが、actual installのcore unpackが`trying to overwrite`で停止し、新profileだけがunpacked状態になる。
- likely cause: pre-hard-cut packageがcanonical unit/profile pathを所有しているが、新package metadataには意図的にretired package名の`Conflicts` / `Replaces`を残していない。apt simulationは異名package間のfile ownership collisionを展開前に検出しない。
- detect: install前に`dpkg-query -S /lib/systemd/system/btd.service /usr/share/hidloom/profiles/<profile>/profile.json`を実行し、ownerが`hidloom`、`hidloom-core`、対象`hidloom-profile-<profile>`以外なら停止する。失敗後は`dpkg-query -W -f='${db:Status-Abbrev} ${binary:Package} ${Version}\n'`と`dpkg --audit`でpartial stateを確認する。
- recovery: unpackedだけの新profileを除去し、`dpkg --audit`、failed units 0、旧runtime activeを確認する。旧core/profile `.deb`とsystemd unitをbackupした上で、旧2 packageの明示removeと新core/profileのinstallを同じapt transactionで実行し、`hidloom-profile <profile> --apply --backup --restart`を通す。
- regression check: release installerのownership preflight、split verifierのinstalled/arm64/same-version検査、native owner live smoke、authenticated HTTPS `/api/status`の`hid_broker.broker_ready=true`、output target `auto`、reboot後failed units 0を確認する。
- evidence: 2026-07-16、`<keyboard-host>`への`0.0.1936+git6b2a88e2`初回split installで再現した。partial profileを除去して旧runtimeを維持し、rollback `.deb`を保存後、hard-cut transactionで新core/profileを導入した。service 11件active、`NRestarts=0`、HID/native-owner smoke pass、output target `auto`まで復旧した。

## Host PC restart looks like device power instability

- symptom: package installとcontrolled reboot後のhealthはpassするが、数分後にSSHが`No route to host`またはtimeoutとなり、復帰後の`/proc/sys/kernel/random/boot_id`が変わる。次bootでjournalがunclean/corruptとして退避され、boot filesystemのdirty bitが自動除去される。
- likely cause: USB接続先または給電元PCのOS update/restartは、Pi側ではclean shutdownを伴わない電源断またはUSB電源resetに見える。systemd watchdog、package maintainer script、電源・cable・microSD不良を疑う前に、試験時間帯のhost OS restart履歴と給電経路を確認する。
- detect: 各remote操作前後でboot IDと`uptime -s`を記録し、`journalctl --list-boots`、`journalctl -b -1 -e`、current bootの`unclean|corrupt|dirty bit`、watchdog値、failed units、package stateを採取する。同時にoperatorへhost update/restartとUSB給電の有無を確認し、SSH断だけをWi-Fi不良やpackage不良と決めつけない。
- recovery: host update完了まで追加rebootとwrite負荷を止め、到達できるwindowで`dpkg --audit`、failed units、output targetを確認して`auto`へ戻す。host安定後に同一boot IDで10分以上のread-only soakをやり直す。host restartがなかった場合だけ5V給電、cable、LED電流、microSD/board faultへ調査を広げる。
- regression check: host安定後の10分以上のread-only soak、split verifier、必要なら1回だけのlive smoke、output `auto`、failed units 0を確認する。Windows host Raw HID/VialとOLED/LED/stickはhost update完了後に物理確認する。
- evidence: 2026-07-16、`<keyboard-host>`の`0.0.1937+git8ab81f9e`試験中にboot IDが複数回変化したが、利用者から接続先Windows PCのupdate再起動が同時間帯に複数回走ったと報告された。PC安定後は2026-07-16T11:48:34Zから12:00:10Zまで11分36秒、60/60回reachable、boot ID `102f8804-0aa6-4f3e-96bf-78857819d581`不変でpassし、終了時もfailed units 0、package `ii`、output `auto`だった。

## Reused Buildroot PYC_ONLY target loses importable modules

- symptom: cached M6 outputから`sdcard.img`は生成されるが、artifact verifierが`luma/*/__init__.pyc`欠落で停止する。部分再配置後はQEMU import smokeが`encodings.aliases`欠落またはhostの`~/.local`にあるPillowを読んで失敗する。
- likely cause: `BR2_PACKAGE_PYTHON3_PYC_ONLY=y`のfinalized targetを再利用した際、source `.py`は既に削除されている一方、古いpackage stampにより欠落bytecodeがtargetへ再配置されない。smokeがhost user siteを許すと、target欠落をhost packageで誤補完する。
- detect: `tools/buildroot_m6_verify.py`、`tools/buildroot_m6_import_smoke.py`、`tools/buildroot_m6_runtime_smoke.py`を必ず連続実行し、targetの`encodings`、Pillow、CBOR2、luma、WS281x、SMBus2 bytecodeを確認する。QEMU tracebackにhost home pathが含まれた場合も失敗とする。
- recovery: `tools/buildroot_m6_build.sh`を再実行する。wrapperは必要bytecode欠落時だけPython本体とM6依存packageのBuildroot `*-reinstall`を行い、その後imageと3 smokeを再生成する。手作業でimageへfileを追加しない。
- regression check: static asset testでcache repair package集合、`PYTHONNOUSERSITE=1`、`PYTHONHOME`除去を固定し、実cached outputでartifact verify、target-only ARM import、JIS/US routing、companion初期化をpassさせる。
- evidence: 2026-07-16、clean public export `cae3f14e4029`のcached M6再生成でluma bytecode、標準`encodings`、Pillow sourceの順に欠落を検出した。必要package再配置とhost user-site隔離後、source `947a9e4d3c1b`のimage SHA-256 `fa10d3df3857325b37c8a93bed2b01b931a608b601ea60ce4fe02276db660608`で3 smokeとpublic build provenanceをpassした。

## M6 rebuild leaves unlisted Cargo output in the public export

- symptom: M6 image、provenance、binary compliance verificationはpassするが、同じpublic exportで実行したrelease readinessだけが`no_unlisted_files=false`となり、4 Rust crateの`target/`と`buildroot-hostbin/install`を列挙する。
- likely cause: native ARM buildがCargo既定のcrate-local `target/`を使用し、Buildroot host wrapperもsource root基準の`build/artifacts`へ作られる。image不良、manifest改ざん、private情報混入ではなく、build後source treeと事前生成manifestの境界違反である。
- detect: `tools/public_build_rehearsal.sh --buildroot-image`後、同じexportで`tools/public_release_readiness.py --require-binary-distribution`を実行し、`unlisted_files`が0か確認する。image checksumとbinary readinessだけでsource publication readinessを代用しない。
- recovery: disposable export内の生成済みcrate-local `target/`とhost wrapperだけを除去し、manifest掲載sourceを変更せずreadinessを再実行する。恒久経路では`BUILDROOT_OUTPUT`をexport外へ置き、native `CARGO_TARGET_DIR`、binary directory、host wrapperをその外部work directoryへ集約する。
- regression check: static Buildroot asset testで外部`CARGO_TARGET_DIR`と`HIDLOOM_BUILD_HOSTBIN` forwardingを固定する。clean export、外部Buildroot output、image/provenance生成、release readinessの順で`unlisted_files=[]`、source/binary両readyを確認する。
- evidence: 2026-07-16、source `947a9e4d3c1b`のM6候補で初回readinessはimage/compliance passのままgenerated pathを列挙してexit 2になった。disposable生成物だけを除去した再評価はblocker 0、unexpected required 0、unlisted 0、source/binary両readyでpassした。

## M6 Raw HID exists but Vial client does not list the keyboard

- symptom: M6は約6秒でkeyboard入力可能となり、JIS key、OLED、LEDも動作するが、Windows Vial clientのdevice listにkeyboardが出ない。
- likely cause: M6がM4 gadget overlayを継承し、Raw HID `usage_page=0xFF60` / `usage=0x61`と`/dev/hidg1` bridgeは持つ一方、USB serialを過去のstage marker `m4-native-split`へ固定していた。Vial GUIの通常検出はserialに`vial:f64c2b3c` magicを要求するためprotocolへ到達する前に除外される。
- detect: image targetのgadget script、Windows `hid.enumerate()`のMI_01 serial、Raw HID usage page/usageを確認する。`/dev/hidg1`や`viald` socketの存在だけでVial検出可能と判断しない。
- recovery: development compatibility profileではUSB serialを`vial:f64c2b3c`へ戻し、gadgetを再列挙する。未割当のpublic VID/PIDやformal suffixへ変更せず、現在の`1d6b:0105`を維持する。
- regression check: Buildroot asset testとM6 artifact verifierでserial magic包含とstage marker不在を固定する。Windows host smokeもMI_01だけでなくserial magicを検査し、Vial clientで接続、keymap read/write、再起動保持、cable再接続を確認する。
- evidence: 2026-07-16、source `947a9e4d3c1b`のM6実機でUSB約6秒、JIS変換/無変換、OLED、LEDはpassしたがVial認識はfailした。生成imageのgadget scriptが`m4-native-split`を設定していることを確認し、Vial protocol/bridgeより前のenumeration filter不一致と特定した。
- fixed candidate: source `8b9cad2eb781`から再生成したimage SHA-256 `2e52208455eea17ca033d8c373b9d81ca30625f3d2752e61403837b6014503aa`はVial serial magicを含むartifact gate、ARM import、split route、companion、provenance、source/binary readinessをpassした。Windows Vial clientでも認識、keymap read/write、再起動後保持、USB再接続、LED effect変更をpassし、初回failを解消した。

## M6 console login fails when two gettys share tty1

- symptom: `KC_CONSOLE`でWindowsへのHID入力は停止し、HDMI login promptへusername `pi`も届くが、passwordの一部がechoされたように見え、`Login incorrect`になる。起動画面で`Welcome to Buildroot`と`buildroot login:`が二重に表示される。OLEDがUSB表示のままなのは別の表示ロジック不具合である。
- cause: Buildroot generic gettyのportが既定`console`のままで、Raspberry Pi post-buildがHDMI用`tty1` gettyも追加していた。kernel cmdlineは`console=tty1`なので`/dev/console`と`/dev/tty1`は同じterminalを指し、2個のBusyBox gettyがusername/passwordを競合してreadした。prompt前typeaheadは最初の候補だったが、重複gettyで説明できる。
- detect: 最終rootfsの`/etc/inittab`からcommentでない`/sbin/getty`行を列挙する。M6は`tty1::respawn:/sbin/getty ... tty1 ...`の1行だけが正常。`console::...getty`と`tty1::...getty`の2行があるimageは不合格とする。credential hash、wheel/sudoers、uinput `p` / `i` / Enterも別gateで確認する。
- recovery: `hidloom_m6_defconfig`で`BR2_TARGET_GENERIC_GETTY_PORT="tty1"`を固定し、M6 post-buildで過去のactive getty行を除去してcanonical `tty1` 1行を再生成する。これによりclean buildだけでなく、旧target treeを使う増分buildもsingle gettyへ収束させる。重複gettyを含む`b757ff4a0e6f`以前のM6 candidateは使用せず、single-getty verifierをpassした再生成imageへ書き換える。
- regression check: `tools/buildroot_m6_verify.py`でactive gettyが`tty1` 1個だけか強制する。`script/test_hidloom_outputd_tool.py`と`tools/buildroot_m6_runtime_smoke.py`でnative/ARMの`USB -> uinput -> pi/Enter -> USB`往復とrelease frameをpassさせる。実機ではpromptが1組だけであること、`pi` / `pi`、`sudo -v`、`sudo id -u=0`、OLED Pi/USB復帰を確認する。
- evidence: 2026-07-16のsource `8b9cad2eb781`および`b757ff4a0e6f` imageの最終rootfsにactive gettyが`console` / `tty1`の2行あることを確認した。同imageのcredential hashは`pi`と一致し、隔離ARM BusyBox loginは認証後まで到達、native/ARM uinput往復はLinux key 25 / 23 / 28のpress/releaseをpassしたため、入力データではなくterminal owner競合と特定した。
- fixed candidate: source `f4a5690b06f0`から再生成したimage SHA-256 `5ec1342a0d5d6e8705419998f4298a8782fe2dcf713955f864fe053c14ea17ff`は、旧target treeを使った増分buildでもfinal rootfsをcanonical `tty1` getty 1行へ収束させた。artifact/import、credential/sudo、JIS/US split、native/ARM uinput往復、companion、provenance、source/binary readinessはpassし、実機のprompt/login/sudo/USB復帰は翌日確認待ちである。

## M6 first enumeration briefly leaves Ctrl active

- symptom: M6起動直後、物理Ctrlを押していないのにWindowsでCtrlがactiveに見えることがあり、USB cableの抜き差しで解消する。
- likely cause: `hidloom-hidd`はUSB gadget bind後にendpointをopenするが、最初のinput frameより前にnull keyboard reportを送っていなかった。hostが同一identityの一時的なpressed stateを保持した場合、次の通常reportまたは再enumerationまで解除が保証されない。過去M4のReport ID `0x01`誤解釈なら再接続後も恒常的に再発するため、今回の一過性症状とは区別する。
- detect: exact imageのgadget scriptでmain `hidg0`がReport ID `0x01`付き9-byte descriptor、US sub `hidg2`がReport IDなし8-byte descriptorであることを先に確認する。正常な修正版では`/run/hidloom/hidd-status.json`の`counters.startup_release_reports`が`2`になる。mainがReport IDなし8 byteなら旧M4型descriptor mismatch、descriptor正常でcounterが0ならstartup release不足として扱う。
- recovery: 現行imageではUSBを再接続してmodifierを解除する。恒久対応imageでは`hidloom-hidd`起動時にmainへ`01` + 8 zero bytes、US subへ8 zero bytesをinput処理前に送り、endpoint未準備時は成功まで再試行する。
- regression check: `script/test_hidloom_hidd_tool.py`でendpoint別startup reportを確認し、ARMv7 binaryを`tools/buildroot_m6_runtime_smoke.py`のQEMU smokeで実行する。`tools/buildroot_m6_verify.py`はmain 9-byte/Report ID `0x01`、sub 8-byte/no Report ID、startup-release対応binaryを必須化する。実機はキーに触れずcold boot/USB接続を3回行い、Ctrl非activeを確認する。
- evidence: 2026-07-16、single-getty f4 imageで1回観測した。exact imageのdescriptorとARM binary hashはsource buildと一致し、旧M1 descriptor混入は否定した。native、遅延endpoint fixture、ARM startup null-report回帰、canonical full validation suiteは追加後にpassした。source `4f3c40736a79`からclean cross-buildしたstartup-release image SHA-256 `ab8523d47002e8c8999c7153dcfcf920f7ce9a069110c1a163806634b09af4f0`もdescriptor gate、ARM startup release、split route、uinput往復、provenance、source/binary readinessをpassした。後続remote hardeningではendpoint準備前にqueueしたCtrl inputよりzero reportが先行すること、final rootfsのARM binary/scriptがtargetとbyte一致すること、rootfs SHA-256 `f603f43292f4e90fc035e2b98f743cb15e386586435a869462d12b59b54abdf3`がraw image第2partitionへ同一payloadとして埋め込まれていること、破損fixtureが不一致になることもpassし、物理cold boot 3回だけが確認待ちである。

## OLED pixel click remains in drag-paint state

- symptom: HTTP OLED editorで1 pixelを左clickしてbuttonを離した後、別pixelへcursorを移動するだけで点灯が続く。grid外をclickすると停止する。
- likely cause: 通常描画でも`renderOledPixelGrid()`が全cellを置換し、`pointerdown`対象DOMをevent sequence途中で削除していた。browserがそのpointerの`pointerup`をwindowへ届けない場合、`painting=true`が残り、後続`pointerover`をdragと誤認する。
- detect: click/release後、mouse buttonを押さずに別pixelへ移動して変化するか確認する。開発側では通常描画pathにgrid全体の再生成がないこと、`pointerover.buttons`とpaint button maskを照合することを確認する。
- recovery: 現行UIではgrid外をclickするかpageを再読込してstale painting stateを解除する。恒久修正版では通常描画をcell単位更新へ変更し、pointerup/cancel、window blur、document非表示で状態を解除する。
- regression check: `python3 script/test_oled_pointer_editing.py`のNode VMで`buttons=0`のpointeroverが描画0回かつpainting解除、左/右button dragだけが各1回描画になることを確認する。`script/test_oled_customization.py`でbutton guard、capture-phase release、cell単位更新を固定し、実browserで左/右click、drag、grid外releaseを確認する。
- evidence: 2026-07-17、`<keyboard-host>`のpackage `0.0.1965+git4e2096c1`で利用者が再現した。source調査で通常click直後のgrid全置換とrelease guard不足を確認し、修正後のNode VM、JavaScript構文、HTTP UI/OLED customization回帰はpassした。source `121d7d6b`のpackage `0.0.1967+git121d7d6b`へ更新後、標準live smoke、service/API、配信中JS guard、runtime保持をpassし、利用者の実browserでも意図しない連続描画の解消、icon編集、保存、再起動後保持を確認した。

## Promoted OLED daemon icons exceed the fixed row gap

- symptom: HTTP editorで調整したdaemon iconをpackage既定へ移すとOLED icon testは通るが、daemon status描画testでactive badgeの下端が固定14px領域を越える。
- likely cause: 旧iconは有効pixelが最大6行で固定`row_gap=7`に収まっていたが、新iconは7行を使う。bitmap schemaの8x8制約や横幅では検出できず、2段目が1段目または次のReady項目へ重なる。
- detect: `_draw_daemon_status_row`を実bitmapで描画し、各active rectangle下端が返却した消費領域内か確認する。bitmap validationだけで合格にしない。
- recovery: iconの最下段を削って見た目を変えず、各daemon rowのtrimmed vertical bounds最大高に1px gapを加えて次行位置と返却高を計算する。
- regression check: `script/test_i2cd_output_mode_label.py`で実iconから期待row heightを算出し、badge下端が次項目開始位置より前か確認する。`script/test_i2cd_oled_icons.py`、customization、Buildroot asset gateも通す。
- evidence: 2026-07-17、`<keyboard-host>`の保存icon 17件をsource既定へ昇格した際に検出した。11件の変更を維持したままdynamic row heightへ変更し、全17 iconのruntime一致とReady既定順不変、関連OLED回帰をpassした。

## Profile restart returns before control sockets are ready

- symptom: split package更新後の`hidloom-profile keyboard-ver1 --apply --backup --restart`は成功するが、直後の`hidloom-ctrl output auto`が`connect /tmp/ctrl_events.sock: No such file or directory`で失敗する。数秒後は同じcommandが成功する。
- likely cause: `systemctl restart`はserviceのactive到達で戻るが、Python companionとoutput daemonがUnix socketをbindする処理はその後に完了する。package不良、profile copy失敗、永続設定破損ではない。
- detect: package/profile applyのexit codeを分けて記録し、`systemctl is-active logicd-companion hidloom-outputd`と`test -S /tmp/ctrl_events.sock` / `test -S /tmp/hidloom_output_ctrl.sock`を確認する。socket未生成だけなら起動競合として扱い、直ちにpackage rollbackしない。
- recovery: 両socketがsocket nodeとして現れるまで最大15秒pollし、その後`hidloom-ctrl output auto`を再実行して`/run/hidloom/outputd-status.json`の`target=auto`を確認する。timeout時はservice journal、failed units、profile markerを採取してからrollbackを判断する。
- regression check: `keyboard-ver1.services.ready_sockets`に両pathを保持し、`script/test_apply_device_profile.py`で実Unix socketの即時pass、missing socket timeout、dry-runの`wait-socket`表示を確認する。実機package更新後はprofile applyの直後に追加sleepなしで`hidloom-ctrl output auto`が成功することを確認する。
- evidence: 2026-07-17、`<keyboard-host>`を`0.0.1973+git757d0871`へ更新した際に1回再現した。package installとprofile file反映は成功し、socket生成後の再実行、主要service、HID/native smoke、HTTPS status、output `auto`はすべてpassした。

## Adding a test leaves the exact inventory counts stale

- symptom: Public CIのfull regressionが終盤の`script/test_test_inventory_doc.py`だけで停止し、`script/test_*.py`本数またはcanonical entrypoint数のassertionが失敗する。同じsourceのrepository hygieneとpublic export artifact checkはpassする。
- likely cause: 新しい`script/test_*.py`を追加してcanonical suiteへ登録した際、`docs/ops/test-script-inventory.md`先頭の棚卸し数値を同じcommitで更新していない。機能test、export、workflow runnerの失敗ではない。
- detect: `find script -maxdepth 1 -name 'test_*.py'`相当の実数と`script/test_validation_suite.py`のliteral `TESTS`件数を文書の数値と比較し、`python3 script/test_test_inventory_doc.py`をlocalで再現する。log中の意図したnegative-path warningは末尾のtracebackと区別する。
- recovery: 棚卸し文書の2数値を現行実数へ更新し、inventory test、docs link/current status、clean snapshotのcanonical suiteを順に通す。testやworkflowを無効化してgreenにしない。
- regression check: 新しいtest fileまたはsuite entrypointを追加するcommitでは`script/test_test_inventory_doc.py`をfocused gateに含める。public sync前はprivate Public CI、public export artifact check、repository hygieneの全結果を確認する。
- evidence: 2026-07-17、source `b429bf30`、`4b95957f`、`7ebbf19d`、`2291056f`のPublic CI 4 runがすべて332対333 testsの同一assertionで失敗した。isolated clean snapshotで332→333、219→220へ更新するとinventory gateはpassした。

## OLED layout fixture keeps an obsolete absolute coordinate

- symptom: test inventory修正後のcanonical full regressionが`script/test_i2cd_direct_frame_fps.py`で停止し、Ready画面のdaemon区切り線を旧座標`33/34`に要求する。
- likely cause: 保存iconの既定昇格に合わせてdaemon rowを実bitmap高から算出する可変高さへ変更したが、FPS fixtureだけが区切り線とoutput badgeの絶対座標を固定していた。実描画は新しいicon高に合わせて後続項目を下へ移動しており、重なりやFPS欠落ではない。
- detect: `python3 script/test_i2cd_direct_frame_fps.py`で再現し、FakeDrawのline、badge rectangle、Layer text位置を列挙する。区切り線がdaemon bitmapの算出高直後にあり、output badgeとLayerがその下ならstale fixtureとして扱う。
- recovery: 特定icon版だけのpixel座標へ置換せず、`_daemon_status_icon_rows()`と各iconのvertical boundsから期待消費高を算出し、区切り線、output badge、Layerの相対順序を検証する。
- regression check: `script/test_i2cd_direct_frame_fps.py`、`script/test_i2cd_output_mode_label.py`、`script/test_oled_customization.py`とcanonical suiteをpassさせる。icon既定値やReady行高を変える時は絶対座標fixtureを追加しない。
- evidence: 2026-07-17、inventory件数修正後のprivate full regressionで検出した。実描画のdaemon区切り線は`35/36`、output badgeはその下、Layerはさらに下であり、可変高から期待位置を導くfixtureへ修正した。
