# Test Script Inventory

更新日: 2026-07-18

`script/test_*.py` と周辺手動ツールの棚卸し方針です。現時点ではテストが多いこと自体を
安全側とみなし、削除より分類を優先します。

## 分類

| 分類 | 置き場所 | 扱い |
|---|---|---|
| 回帰テスト | `script/test_*.py` | CI / 手元確認で繰り返し実行する |
| 実機 smoke test | `script/test_*.py` または `tools/*.py` | 実機・socket・systemd が必要。失敗理由を明記する |
| 手動検証 tool | `tools/*.py` | pairing window や reconnect watch など、操作補助として残す |
| root shell helper | repository root の `*.sh` | fresh install / USB gadget / runtime keymap smoke の入口として扱う |

## 現在の主要回帰テスト

現在 `script/test_*.py` は 336 本程度あり、標準 canonical suite は 224 entrypoints を実行する。
すべてを常に同じ重さで扱わず、目的別 suite で使い分ける。

### Suite entrypoints

通常の suite entrypoint は `script/suite_runner.py` の共通 runner を使う。
個別の suite file は、対象 test list と suite 名だけを持つ。実機 suite は `sudo` や
`tools/` helper の外部コマンドも含むため、専用 runner で失敗を集計する。

- `script/test_validation_suite.py`
  - clean/dirtyを問わずtracked sourceだけの一時snapshotで実行する標準回帰セット。
  - hardware / daemon socket なしで通るものを中心にし、全childへbytecode抑止を固定してsource checkoutへ
    ignored cache/build outputを残さない。
- `script/public_pr_gate.py`
  - public PRで必須にするbounded validation。tracked sourceだけの一時snapshotでpublic export、privacy、license、
    reference、repository hygieneと主要HID/Vial/USB/JIS/OLED smokeを実行する。
  - canonical suiteのsubsetだけを列挙し、full suite、cross-build target、全Rust testは`extended` jobへ残す。
- `script/test_validation_suite_isolation.py`
  - clean Git fixtureのcanonical childがignored build outputを作っても、元checkoutがbyte/状態ともcleanなままになることを固定する。
- `script/test_development_suite.py`
  - 開発時の広めの smoke suite。
  - btd / spid / output / HTTP status など複数サブシステムを横断する。
- `script/test_action_validation_suite.py`
  - action expansion / shared action defs / HTTP validation / Vial codec の小さな整合性確認。
- `script/test_btd_suite.py`
  - btd protocol / BlueZ adapter / GATT / advertising / pairing 周辺。
- `script/test_spid_suite.py`
  - spid と logicd pointing input 周辺。
- `script/test_pty_mirror_remote_suite.py`
  - PTY terminal mirror の実機なし確認セット。`sessiond` protocol / PTY wrapper / socket /
    CLI / `logicd` client / runtime routing / no-HID integration をまとめて回し、Windows Terminal
    focus や USB HID 実送信に入る前の切り分け入口にする。
  - `script/test_logicd_sessiond_client_text_profiles.py` は socket に依存せず、標準 text editor profile と
    cat receiver 互換 profile の text plan 分岐だけを確認する。
- `script/test_real_device_keyboard_suite.py`
  - keyboard 実機向け。`script/test_validation_suite.py`、Vial / VialRGB / Lighting live smoke、
    `tools/matrixd_stability_smoke.py` をまとめて実行する。
- `script/test_real_device_touch_panel_suite.py`
  - touch-panel 実機向け。`SW91` encoder 前提の keyboard validation suite は既定では流さず、
    touch flick / HTTP API / i2cd helper 系を確認する。
- `script/test_real_device_smoke_cleanup.py`
  - 実機 smoke が matrix press を送ったまま pressed state を残さないよう、runtime smoke script の
    release cleanup を静的に固定する。
- `script/test_logicd_core_active_owner_smoke_tool.py`
  - `tools/logicd_core_active_owner_smoke.py` の dry-run guard、systemd drop-in、synthetic matrix tap、
    restore path を静的に固定する。
- `script/test_logicd_core_active_owner_units.py`
  - `logicd-core -> matrixd -> logicd-companion` の systemd split と旧 `logicd.service` 復帰経路の境界を固定する。
- `script/test_logicd_matrix_tap_handler.py`
  - native owner 時の `matrix_tap_events.sock` handler が observed pressed matrix と LED / tester 向け tap state を更新し、HID hot path へ戻さない境界を固定する。
- `script/test_logicd_socket_env_overrides.py`
  - Python companion が `/tmp/matrix_events.sock` を bind しないための socket env override を固定する。
- `script/test_public_ci_workflow.py`
  - standalone public CI がrequired `validate`、main/manual/release向け`extended`、sync PR作成を分離し、
    bounded PR test集合がcanonical suiteのsubsetであることを固定する。
  - `extended`だけがbootstrap archive回帰、canonical full validation、cross target、locked Rust testを実行し、
    両validation jobがdiff hygieneを維持することを検査する。
- `script/test_public_community_health.py`
  - issue form、security contact、pull request templateの安全なcontribution導線と、全public-selected pathが
    private export workflowのpush filterで覆われることを固定する。
- `script/test_public_export.py`
  - private Git indexとstandalone public cloneのtracked pathをpublic source、private-only、generated outputへ
    完全分類し、未分類path、未承認生成物、孤立空directoryをmanifest収録前に拒否する。clean export全監査も同じfixtureで実行する。
- `script/test_github_workflow_security.py`
  - private/public双方のworkflowでUbuntu 24.04、job timeout、full-length action SHA、version comment、
    checkout credential無効化、Dependabot、action lockの一致を固定する。
- `script/test_public_repository_policy.py`
  - public repositoryのvisibility/main、feature/merge設定、secret scanning、private vulnerability reporting、Actions allowlist、
    required check、branch protectionを宣言policy、fake `gh api` audit、確認文字列付きapply fixtureで固定する。
- `script/test_public_repository_create.py`
  - authenticated owner、canonical repository不在、`private=false`、feature/merge設定、README/license/gitignore自動初期化なし、空branch/tag集合をfake `gh api`で検査し、完全一致する確認文字列なしの作成を拒否する。
- `script/test_public_repository_bootstrap.py`
  - 完全に空のremoteだけへmanifest掲載pathの初回`main`をnon-force pushし、誤確認、author欠落、export配下worktree、
    既存ref、ignored tracked lockfile欠落を拒否する。
- `script/test_public_source_archive.py`
  - public export Actions artifactがmanifest外fileを含めず、dotfile、実行bit、symlinkを保持し、
    host mode差を`0644`/`0755`へ正規化してbyte-identicalな`tar.zst`を生成することを固定する。

### Local Python environments

通常のローカル実行では MSYS Python (`C:\msys64\usr\bin\python.exe`, `python 3.12`) を使う。
この Python は MSYS 管理環境なので、system-wide `pip install` は行わない。
`python-pip` は pacman で導入済みだが、PEP 668 により system package 外の install は venv へ分ける。

HTTP API / route helper のうち `aiohttp` import が必要なテストは、workspace 内の `.venv/` を使う。
`.venv/` は `.gitignore` 対象で、現在 `aiohttp 3.14.0` を導入済み。
代表コマンド:

```powershell
.\.venv\bin\python.exe script/test_text_send_safety.py
.\.venv\bin\python.exe script/test_touch_panel_flick_input.py
.\.venv\bin\python.exe script/test_touch_flick_dispatch.py
.\.venv\bin\python.exe script/test_interaction_builder_ux.py
```

MSYS Python に `aiohttp` が無い場合でも、純粋な payload / resolver helper は import できるようにしている。
ただし HTTP response / route 登録まで実依存に近く確認する時は `.venv/` の Python を優先する。

### Interaction / keymap

- `script/test_interaction_engine_tap_hold.py`
- `script/test_interaction_engine_morse.py`
- `script/test_interaction_engine_caps_repeat_conditional.py`
  - Caps Word / Repeat Key / Conditional Layers の初期 runtime behavior と `active_snapshot().conditional` を確認する。
- `script/test_input_event_tap_output.py`
- `script/test_action_expansion.py`
- `script/test_layer_action.py`
  - `MO` / `TG` / `TO` / `DF` / `OSL` と、`active_snapshot().oneshot` の read-only status source を確認する。
- `script/test_native_outputd_ctrl.py`
  - native owner 時の `KC_CONSOLE` / `KC_USB` / `KC_BT` / `KC_CONNAUTO` が companion の debug output ではなく `hidloom-outputd` ctrl target へ変換されることを確認する。
- `script/test_logicd_host_led_output.py`
- `script/test_logicd_host_led_reader.py`
- `script/test_logicd_ledd_semantic_roles_snapshot.py`
- `script/test_shared_action_defs.py`
- `script/test_morse_behavior.py`
- `script/test_morse_feedback.py`
- `script/test_morse_feedback_api.py`
- `script/test_morse_ctrl_feedback.py`
- `script/test_morse_oled_alert.py`
- `script/test_morse_led_feedback.py`
- `script/test_i2cd_immediate_alert.py`
- `script/test_oled_alert_ascii.py`
  - default `KC_SHn` notification、Python側の固定alert文字列、logicd送信境界、i2cd受信境界がASCII-only OLEDへ非対応文字を渡さないことを確認する。
- `script/test_morse_browser_smoke_tool.py`
- `script/test_morse_interaction_config.py`
- `script/test_interaction_physical_runtime.py`
  - InteractionEngine 物理確認 helper の test 用 `settings.interaction` 定義 backup / apply / restore、重複投入防止、active companion優先とlegacy profile fallback reloadを確認する。
- `script/test_key_override_cross_clear.py`
  - Key Override suppression 中の output switch / reload / emergency release clear 境界を固定し、replacement release と後続 physical release no-op を確認する。
- `script/test_key_override_replacement_validation.py`
  - Key Override replacement が layer / system / script / connectivity action を reject し、通常 key action、modifier wrapper、MORSE action を許可する境界を確認する。

### HTTP UI / API

- `script/test_http_keymap_action_validation.py`
- `script/test_http_security.py`
  - HTTP private network guard、CSRF、audit field、safe header、WebSocket input validation の静的・小規模回帰確認。
- `script/test_http_security_module_split.py`
  - `daemon/http/auth_tls.py` と `daemon/http/security_middleware.py` へ分割した auth/TLS/security helper が `security_api.py` facade 経由で互換維持されていることを確認する。
- `script/test_http_vil_module_split.py`
  - `.vil` import の Vial macro buffer 展開処理が `daemon/http/vil_macro_import.py` に分離され、`daemon/http/vil_api.py` に低頻度の macro decode 詳細が戻らないことを確認する。
- `script/test_http_script_module_split.py`
  - script editor の module split を固定する。`scripts_api.py` に subprocess / tempfile / chmod が戻らず、`script_runner.py` が実行・check-run 一時 script 作成を持ち、`script_store.py` が path 設定を持つことを確認する。
- `script/test_http_remap_categories.py`
- `script/test_http_remap_keycode_coverage.py`
- `script/test_http_system_status.py`
  - `/api/status` の副作用なし helper、active logicd runtime environment選択、Wi-Fi row、Bluetooth host overview、btd / spid / direct-frame status の静的確認。
- `script/test_http_interaction_api.py`
  - HTTP config save後のreloadがactive `logicd-companion`を優先し、legacy `logicd` fallbackと両unit inactive errorを維持することを確認する。
- `script/test_http_keyboard_layout_labels.py`
- `script/test_http_keymap_api_save.py`
  - HTTP keymap remap が runtime 即時反映、debounce 保存予約、`S` 連打抑制を行うことを確認する。
- `script/test_http_keymap_active.py`
  - `/api/keymap/active` fallback が `oneshot` / `locked` / `conditional` を含む runtime layer schema を返すことを確認する。
- `script/test_runtime_keymap_permissions.py`
  - runtime keymap 保存が MCP / operator read-only diagnostics から読める `0644` permission を維持することを確認する。
- `script/test_http_layout_controls.py`
- `script/test_http_lighting_api.py`
  - Lighting API validation、effect category、Lighting tab の direct-frame metrics panel、read-only LED role preview summary、`lighting_role_preview_controls.js` の読み込み順と `Preview roles` / `Restore effect` UI helper を静的確認する。
- `script/test_http_lighting_layer_overlays.py`
  - Lighting tab の Layer overlay colors helper、Layer 1-7 の color / blend / changed-key option、legacy `layer_1` 置換、lock overlay 非破壊を確認する。
- `script/test_http_lighting_lock_indicators.py`
  - Lighting tab の Host lock LED 永続設定 helper と legacy `state_overlays` からの移行を確認する。
- `script/test_lighting_role_preview_api.py`
  - `daemon/http/lighting_role_preview_api.py` が preview / restore で `vialrgb_direct` / `vialrgb` / `vialrgb_get` を使い、`ROLE_PREVIEW_ROUTE` と `register_lighting_role_preview_route()` を持ち、`vialrgb_save` や永続 config 変更をしないことを固定する。
- `script/test_lighting_role_inspector_api.py`
  - `GET /api/lighting/role-inspector` の read-only role / source / reason schema、summary、UI helper wiring を固定する。
- `script/test_interaction_inspector.py`
  - `GET /api/interaction/inspector` の read-only Combo / Tap Dance / Key Override warning schema、route wiring、UI helper wiring、config 非書き換えを固定する。
- `script/test_morse_inspector.py`
  - Morse behavior の read-only inspector helper と Web UI asset wiring を固定する。
- `script/test_http_matrix_api.py`
- `script/test_http_settings_api.py`
- `script/test_http_settings_analog_map.py`
- `script/test_http_script_store.py`
- `script/test_http_script_check_run.py`
- `script/test_http_script_ui_assets.py`
- `script/test_script_report_metadata.py`
- `script/test_http_ui_assets.py`
  - remap search、script safety、Interaction summary、One Shot Layer / Conditional Layers の read-only runtime 表示、remap quick access / pin / recent / docs link の静的 asset 確認。
- `script/test_hidloom_icon_assets.py`
  - external avatar / faviconへ依存せず、HIDloom固有markのSVG / PNG / ICOを標準libraryだけで決定的に再生成できることを確認する。
- `script/test_public_asset_inventory.py`
  - 公開対象の画像・CAD・KiCad・バイナリ資産が由来台帳に完全一致し、未登録資産を公開 gate が拒否することを確認する。
- `script/test_public_reference_audit.py`
  - canonical public repository identityを固定し、旧private repository URL、owner配下の未承認repository、local repository remoteを公開 gate が拒否することを確認する。
- `script/test_rust_lockfile_policy.py`
  - 全Rust実行crateがtrackedかつnon-ignoredな`Cargo.lock`を持ち、CI、Makefile、package/cross-build wrapperのCargo build/test/fetchが`--locked`であることを確認する。
- `script/test_pid_codes_application.py`
  - pid.codesの予約範囲外候補、canonical repository/license、申請用org/device page、clean upstreamと`origin/HEAD`・online remote `HEAD`一致、記録証跡一致、未確認出力拒否、公式merge前のruntime適用禁止を確認する。
- `script/test_pid_codes_allocation.py`
  - 記録済みpid.codes PRのmerge、head、required checks、公式checkoutの最新性、掲載page完全一致、merge commit到達性、確認句なしの適用拒否、active runtime非変更を確認する。
- `script/test_buildroot_legal_summary.py`
  - M6 `legal-info`のexact package/source/license証跡を正規化し、source auditとbinary release gateを混同しないことを確認する。
- `script/test_buildroot_compliance_bundle.py`
  - pinned Buildroot source、Bootlin公式summary/readme、全component source/licenseをcontent-addressed bundleへ収録し、決定性と改ざん拒否を確認する。
- `script/test_text_send_safety.py`
  - Unicode / Send String safety の read-only policy、`mode=none` preview/no-op、named entry content validation、HTTP route wiring を確認する。
- `script/test_text_send_smoke_sequence.py`
  - `script/text_send_smoke_sequence.py` が dry-run default で `U+3042` / `TEXT(kana_a)` の tap sequence を返し、実送信には確認句を要求することを確認する。
- `script/test_touch_panel_flick_input.py`
  - 4.3 inch flick metadata、`osoyoo-4.3` profile guard、preview/no-op、cancel hook schema、HTTP route wiring を確認する。
- `script/test_touch_flick_dispatch.py`
  - logicd-facing touch flick dispatch guard が preview state / direction state を拒否し、explicit keycode `tap_action` と supported text action の `romaji_us_ime` tap sequence を press/release へ変換し、`TOUCH_FLICK` ctrl command が final dispatch envelope だけを受けることを確認する。
- `script/test_sequence_engine_primitives.py`
  - 将来の SequenceEngine adapter が共有する `SequenceEmission` の host-visible / feedback 境界、ordering、validation、press / release owner、suppression accounting、timer invalidation、final-action observer 境界を固定する。
- `script/test_sequence_engine_compatibility_guard.py`
  - `MORSE(name)` / `TD(name)` / `LT` / `MT` / `TT` の既存外部挙動と、SequenceEngine 内部名を保存 payload / HTTP UI に露出しない境界を固定する。
- `script/test_sequence_morse_profile.py`
  - `MorseBehaviorRuntime` を `SequenceProfile` adapter として包み、tap emission、feedback emission、timer identity が既存 Morse 挙動と一致することを確認する。

### Docs / inventory

- `script/test_repository_hygiene.py`
  - tracked treeとgit metadataを持たないpublic exportの両方で、backup/build/package/image/archive、
    `.gitkeep` placeholder、runtime mailbox state、未承認large file、全non-empty exact duplicate、
    exact path-set例外の拡張・stale・欠落、非実行shellの拒否を確認する。
- `script/test_source_syntax_hygiene.py`
  - Git indexとmanifest限定exportのPython、JSON、TOML、YAML、shell、JavaScript、SVGを検査し、
    各形式のmalformed fixtureとparser不足、bytecode cache非生成を確認する。
- `script/test_development_residue_hygiene.py`
  - Git indexとmanifest限定exportのmerge marker、debug hook、placeholder macro、自己fallback、
    重複環境名・隣接文を検査し、名称hard cutの機械置換残渣を再混入させない。
- `script/test_generated_binary_hygiene.py`
  - Git非追跡のhost/cross-build出力に残るretired binaryをfixtureで検出・選択除去し、
    native/cross-build wrapperのcleanupとRust deployのcanonical 4-file境界を固定する。
- `script/test_local_environment_hygiene.py`
  - ignored `.env`の値をstdout/stderrへ出さず、canonical example、retired variable name、重複、
    malformed assignment、symlink、unsafe modeを検査する。key-only dry-runのbyte不変、collision/誤token拒否、
    明示apply後のvalue/mode保持、temporary/backup不在も固定する。
- `script/test_workspace_debris_hygiene.py`
  - source領域のdisposable cacheだけを削除し、tracked file、symlink、backup、credential、
    build output、virtual environment、operator stateを保持する境界を固定する。
- `script/test_public_buildroot_rebuild.py`
- `script/test_buildroot_compliance_bundle.py`
- `script/test_public_release_bundle.py`
- `script/test_public_sync_branch.py`
  - clean exportからのBuildroot M6再構成、package/M6 provenance再検証、Release candidate集約、isolated sync branch pushをfixtureで確認する。
- `script/test_unimplemented_keycodes_doc.py`
- `script/test_man_pages.py`
  - `docs/man/man1|man5|man8` の manual page source、GitHub docs URL、package build 時の placeholder 展開、release candidate contents check を固定する。
- `script/test_keycode_action_inventory.py`
  - `docs/keycode/action-inventory.md` が `config/default/keycodes.json` から再生成可能な完全一覧として新鮮であり、
    `docs/keycode/action-routing-matrix.md` に分類・特殊処理・出力先ごとの読み方が残っていることを確認する。
- `script/test_macro_compatibility_plan_doc.py`
- `script/test_module_structure_http_split_doc.py`
  - `docs/architecture/module-structure.md` に HTTP module split、VIL macro buffer 保持理由、runtime script 保存方針、i2cd connectivity helper の責務が残っていることを確認する。
- `script/test_morse_documentation.py`
  - Morse behavior / Web UI / route TODO 文書と README 導線の鮮度を確認する。
- `script/test_morse_browser_smoke_tool.py`
  - workstation から実機 HTTP UI に向けて流す `tools/morse_browser_smoke.py` の確認項目が弱くならないよう静的に固定する。
- `script/test_morse_browser_dom.py`
  - Chromium を起動せず、Node 上の最小 DOM で Morse builder / Tree / action 挿入の browser-side logic を確認する。
- `script/test_morse_romaji_composition_design_doc.py`
  - Morse ローマ字入力補助が Wishlist から design TODO へ昇格し、touch flick composition plan と同じ read-only `romaji_us_ime` 境界で管理されることを確認する。
- `script/test_sequence_engine_design_doc.py`
  - Morse を軸に Tap Dance / Tap-Hold を内部 `SequenceEngine` / `SequenceEmission` へ寄せる設計、外部 action 互換、懸念 TODO の導線を確認する。
- `script/test_performance_tuning_plan_doc.py`
- `script/test_board_profiles.py`
  - `ver1.0` default / `ver0.1` prototype の board profile、marker fallback、`--prototype` guard、fresh install 導線を固定する。
- `script/test_device_profile_inventory.py`
  - `config/device-profiles/*.json` の id、runtime/config file 参照、service policy、profile package 入力を固定する。
- `script/test_apply_device_profile.py`
  - device profile apply の dry-run、backup、runtime file copy、drop-in、service policy plan を固定する。
- `script/migrate_runtime_scripts.py`
- `script/test_runtime_script_migration.py`
  - package更新時に既知の旧defaultだけをbackup付きで移行し、利用者編集とsymlinkを保持する境界を固定する。
- `script/test_power_shed_boot.py`
  - boot-time power shedding service、fresh install 登録、touch panel browser / USB gadget start delay の配線を固定する。
  - touch panel kiosk の blank/error tab repair について、DevTools opt-in、delay / attempts / interval、`about:blank` / `chrome-error://` 検出、`Page.navigate` 導線を固定する。
- `script/test_remote_fresh_install_tool.py`
  - `tools/remote_fresh_install.py` の archive 除外、LF 正規化、remote setup 導線を固定する。
- `script/test_usb_gadget_descriptor.py`
  - `setup_usb_gadget.sh` の keyboard / raw HID report descriptor が Host LED Output Report と Raw HID IN/OUT を含むことを確認する。
- `script/test_usb_gadget_fast_helper.py`
  - native USB gadget fast helper の descriptor 配列が shell fallback と一致し、JSON / regex parsing を持たないことを確認する。
- `script/test_hidloom_paths.py`
  - repository default config、board profile、runtime `/mnt/p3`、runtime script path の helper が現行 layout と環境変数 override の両方を返すことを確認する。
- `script/test_command_help_surfaces.py`
  - package に含める Python daemon、`matrixd`、C helper、Rust native command の `--help` entrypoint が起動処理へ進まず `usage:` を返すことを確認する。
- `script/test_logicd_usbd_report_broker_backend.py`
  - `logicd` が opt-in 時に keyboard / mouse / consumer の canonical payload を `usbd` HID report broker socket へ送ることを確認する。
- `script/test_usbd_hid_report_broker.py`
  - `usbd` USB HID report broker の 64-byte local frame codec、checksum、current multi-report profile adapter を確認する。
- `script/test_send_standard_keyboard_report.py`
  - 標準 keyboard report helper が direct 書き込み時は Report ID 付き、broker socket 送信時は canonical 8-byte payload として組み立てることを確認する。
- `script/test_windows_ime_custom_hid_sender.py`
  - optional Windows IME custom HID sender の payload 生成と引数処理を確認する。
- `script/test_windows_ime_raw_hid.py`
  - Raw HID multiplex の Windows IME frame codec と key event payload を確認する。
- `script/test_windows_ime_raw_hid_receiver_poc.py`
  - Windows host 側 Raw HID receiver PoC の report decode と表示形式を確認する。
- `script/test_windows_ime_raw_hid_sender.py`
  - Raw HID multiplex sender の frame 生成と CLI 引数処理を確認する。
- `script/test_perf_baseline_tool.py`
- `script/test_remote_boot_baseline_collect_tool.py`
  - `tools/remote_boot_baseline_collect.py` の SSH command 組み立て、remote 採取 script、
    reboot-before-sample 待機、summary renderer を固定する。
- `script/test_cross_build_host_check_tool.py`
  - `tools/cross_build_host_check.sh` の help / no-SSH preflight と、`Makefile` の cross-build host /
    checkout sync / deploy / smoke / boot report shortcut を固定する。
- `script/test_release_bundle_tools.py`
  - `tools/package/` の release bundle build / deploy / apply helper、Makefile shortcut、
    最小 bundle の dry-run apply を固定する。
- `script/test_buildroot_m1_compare_tool.py`
  - `tools/buildroot_m1_compare.py` の Raspberry Pi OS baseline / Buildroot M1 marker / USB enumerate
    比較表 renderer を固定する。
- `script/test_logicd_event_benchmark_tool.py`
- `script/test_matrixd_diagnostics_snapshot_tool.py`
  - `tools/matrixd_led_stress_sweep.py` と合わせ、ghost / 取りこぼし再現時の非接触 LED stress と snapshot 導線を固定する。
- `script/test_matrixd_led_stress_sweep_tool.py`
  - keyboard に触らず LED effect sweep / dummy splash stress を流し、`key_events.sock` の実入力発生だけを fail とする helper の scenario / report 境界を固定する。
- `script/test_matrix_input_latency_instrumentation_design_doc.py`
- `script/test_kicad_generation.py`
- `script/test_hidloom_send_tools.py`
- `script/test_hidloom_hidd_tool.py`
  - native `hidloom-hidd` broker の frame 互換、endpoint mapping、live status 更新。
- `script/test_hidloom_uidd_tool.py`
  - native `hidloom-uidd` の keyboard report -> Linux EV_KEY 差分変換、unsupported frame、dry-run status schema。
- `script/test_hidloom_outputd_tool.py`
  - native `hidloom-outputd` の usb/uinput/bt target forwarding、ctrl status schema、切替 / release_all 時 release frame。
  - native `hidloom-hidd` が既存 `usbd` HID report broker frame と互換に keyboard / mouse / consumer / US sub keyboard report を endpoint へ書くことを確認する。
  - long-running daemon として終了前に status counter を更新することも固定する。
- `script/test_hid_release_roll_analyzer.py`
  - `tools/hid_release_roll_analyzer.py` が `HIDD_FRAME_LOG_PATH` の NDJSON から zero report flush 直後の next press 候補を抽出し、release merge window 調整時の再発解析を固定する。
- `script/test_logicd_core_rs_tool.py`
  - native `hidloom-logicd-core` が matrix event replay から Python `HidState` と同じ basic keyboard report / broker frame を生成することを確認する。
  - shadow `--serve` が alternate matrix socket で status を更新し、output disabled では broker へ送らないことも固定する。
  - `tools/logicd_core_shadow_replay.py` から shadow socket へ recorded stream を流し、
    `LOGICD_CORE_PREVIEW_LOG_PATH` の `shadow_report` NDJSON と status counter が更新されることも固定する。
  - `tools/usbd_hid_report_capture.py` の broker datagram capture と
    `tools/logicd_core_parity_compare.py` の core preview / broker capture 比較も固定する。
  - `tools/logicd_python_matrix_replay.py` による isolated Python `logicd` replay と
    default keymap sequence の core / Python payload parity も固定する。
  - `tools/logicd_core_parity_suite.py` による default keymap 由来の M0-supported sequence
    一括比較と unsupported action 分類も固定する。
  - ctrl socket の `status` / `set_output` / `release_all` と、
    systemd `ExecStop` で使う `--ctrl-release-all` CLI が押下 state を解放することも固定する。
- `script/test_logicd_core_active_owner_preflight_tool.py`
  - `tools/logicd_core_active_owner_preflight.py` が binary、unit 状態、split route config、rollback dry-run、
    boot marker helper、runtime status snapshot を read-only で評価する境界を固定する。
- `script/test_logicd_core_owner_recovery_tool.py`
  - `tools/logicd_core_owner_recovery.py` の dry-run command plan と、Python `logicd` owner へ戻す
    rollback 判定を固定する。rollback 中は native `matrixd.service` を退避し、Python-owner
    system unit を一時導入する。
- `script/test_logicd_core_native_owner_restore_tool.py`
  - `tools/logicd_core_native_owner_restore.py` の dry-run command plan と、退避した native
    `matrixd.service` を戻して `logicd-core` / `matrixd` / `logicd-companion` owner に復帰する判定を固定する。
- `script/test_logicd_core_native_owner_live_smoke_tool.py`
  - `tools/logicd_core_native_owner_live_smoke.py` の matrix packet、layer-0 action selection、
    native owner live smoke の検査入口を固定する。
- `script/test_logicd_core_action_classification_tool.py`
  - `tools/logicd_core_action_classification.py` の native / delegated / transparent / no-op
    分類と、timed / composite action を companion 委譲へ寄せる境界を固定する。
- `script/test_daemon_readme_diagrams.py`
- `script/test_tools_readme.py`
- `script/test_keycode_expansion_plan_doc.py`
  - `docs/keycode/expansion-plan.md` が Basic HID command / Language / Locking / Mouse HID の現在の対応状況を古い追加候補として残していないことを確認する。
- `script/test_test_inventory_doc.py`
- `script/test_current_status_doc.py`
- `script/test_current_todo_completion.py`
  - `TODO_PRIORITY.md` の未完了キューが空で、直近フォーカスが自動完了ゲートと Current Status へ移っていることを確認する。
- `script/test_docs_archive.py`
- `script/test_docs_reorg.py`
  - `docs/REORG_PROGRESS.md`、`docs/research/`、移動済み調査メモへの導線、旧ファイル名参照の混入防止を固定する。
- `script/test_docs_links.py`
  - repository Markdown の `.md` link が移動後の実在 path を指していることを確認する。
- `script/test_daemon_specs_coverage.py`
  - `docs/daemon/specs/` が daemon directory、native tools、systemd service の仕様入口を漏らしていないことを確認する。
- `docs/ops/docs-reorg-review-summary.md`
  - docs 整理後の root 5 文書、カテゴリ分布、レビュー観点、確認済み検査を読むための summary。

### 2026-06-01 設計 TODO / first slice 棚卸し

- `script/test_autocorrect_safety_design_doc.py`
- `script/test_autocorrect_runtime.py`
  - default-off の ASCII Autocorrect runtime helper、dictionary validation、word buffer、boundary correction、system action clear を固定する。
- `script/test_basic_hid_keycode_completion_design_doc.py`
- `script/test_basic_hid_keycode_runtime.py`
  - Basic HID command key first slice が `config/default/keycodes.json`、keyboard HID report、Vial codec、HTTP keycode payload に接続されることを確認する。
- `script/test_qmk_unicode_map_runtime.py`
  - QMK Unicode map / mode groundwork helper が `UC(c)` / `UM(name)` / `UP(name,next)` / `UC_*` を read-only plan に分類し、codepoint validation、明示 host profile / unicode mode gate、tap dry-run preview を固定する。
- `script/test_logicd_mouse_acceleration.py`
  - `MS_ACL0`-`MS_ACL2` が logicd key-driven cursor / wheel profile として動き、Mouse HID report delta に反映されることを確認する。
- `script/test_bluetooth_multi_host_ui_design_doc.py`
- `script/test_bluetooth_host_rename_forget_design_doc.py`
- `script/test_boot_debug_eeprom_action_mapping_design_doc.py`
- `script/test_caps_word_status.py`
- `script/test_conditional_layer_inspector.py`
- `script/test_consumer_control_gatt_opt_in_design_doc.py`
- `script/test_digitizer_haptic_steno_feature_design_doc.py`
- `script/test_dynamic_macro_leader_design_doc.py`
- `script/test_dynamic_macro_leader_runtime.py`
- `script/test_macro_integration_runtime.py`
- `script/test_hardware_ports_buzzer_ir_design_doc.py`
- `script/test_host_profile_status.py`
- `script/test_interaction_builder_ux.py`
- `script/test_interaction_inspector_summary.py`
- `script/test_key_lock_state.py`
- `script/test_key_override_cross_clear.py`
- `script/test_key_override_replacement_validation.py`
- `script/test_key_override_runtime_suppression_design_doc.py`
- `script/test_kml_qmk_macro_keycode_design_doc.py`
- `script/test_layer_oneshot_completion_design_doc.py`
- `script/test_led_role_preset_sharing_design_doc.py`
- `script/test_led_role_semantic_override_design_doc.py`
- `script/test_led_pattern_metrics_runtime.py`
- `script/test_led_pattern_editor_long_run_design_doc.py`
- `script/test_lighting_key_alias_compatibility_design_doc.py`
- `script/test_magic_key_translation_design_doc.py`
- `script/test_matrixd_scanner_abstraction_design_doc.py`
- `script/test_midi_audio_output_design_doc.py`
- `script/test_midi_sequencer_audio_integration_design_doc.py`
- `script/test_mod_morph.py`
- `script/test_mouse_hid_extension_design_doc.py`
- `script/test_paw3805ek_mounted_cursor_settings_design_doc.py`
- `script/test_power_preset_status.py`
- `script/test_qmk_alias_completion_design_doc.py`
- `script/test_repeat_key_status.py`
- `script/test_system_control_programmable_hid_report_design_doc.py`
- `script/test_touch_panel_flick_input_design_doc.py`
- `script/test_touch_panel_profile.py`
- `script/test_unicode_send_string_safety_design_doc.py`
- `script/test_usb_host_identity_keymap_hot_swap_design_doc.py`
- `script/test_vial_advanced_macro_compatibility_design_doc.py`
- `script/test_windows_host_profile.py`
- `script/test_windows_ime_custom_hid.py`
- `script/test_windows_ime_custom_hid_descriptor.py`
  - Windows US custom HID IME profile、warning metadata、8 byte report descriptor helper の remote first slice を固定する。

### Generator / MCP support

- `script/test_make_windows_keyboard_layout_override_inf.py`
- `script/test_make_windows_keyboard_layout_override_reg.py`
  - `build/generators/` へ移動した Windows keyboard layout override 生成 helper の dry-run / help / 出力形式を固定する。
- `script/test_kicad_generation.py`
  - canonical KiCad schematic / PCBからmatrix、PCB、Vial生成物を一時treeで再生成し、tracked内容へのbyte一致と入力欠落時のfail-closedを固定する。
- `script/test_public_documentation_audit.py`
  - public exportから意図的に除外したprivate文書へのlinkをplain textへ変換し、未知の欠落targetとroot READMEから到達できない`docs/**/*.md`をblockerにする境界を固定する。directory indexとcode fence内の偽navigationも検証する。
- `script/test_mcp_keyboard_server.py`
  - `dev/mcp/keyboard/server.py` の portable target既定値、read-only tool schema、native owner service allowlist、package-first update guidance、代表 tool の smoke を固定する。
- `script/test_codex_task_mailbox.py`
  - `tools/codex_task_mailbox.py` のtask/result JSON契約、CLI相互排他、公開manual command、on-demand directory、MCP mailbox summaryを固定する。

## `script/` の非 test helper

`script/` には、回帰テストではないが repo 生成物・実機確認・開発補助に必要な helper もある。
これらは通常の suite には入れず、用途が明確な時だけ個別に実行する。

| script | 分類 | 役割 |
|---|---|---|
| `build/generators/analyze_kicad_matrix.py` | 生成補助 | KiCad schematic から matrix 推定情報を生成する |
| `build/generators/analyze_kicad_pcb.py` | 生成補助 | PCB 座標を `build/generated/pcb_analysis.json` 系へ反映する |
| `build/generators/analyze_kicad_pcb_led.py` | 生成補助 | PCB LED 座標を current `config/default/ledd.json` の matrix 座標 key へ反映する |
| `script/describe_windows_ime_custom_hid_descriptor.py` | 実機補助 | Windows IME custom HID の追加 endpoint descriptor 候補を dry-run 表示する |
| `build/generators/generate_final_matrix_report.py` | 生成補助 | KiCad 解析結果から matrix report を生成する |
| `build/generators/generate_touch_panel_vial.py` | 生成補助 | touch-panel virtual keyboard 用の Vial definition を profile ごとに生成する |
| `build/generators/mkvial.py` | 生成補助 | KLE slot 順、KiCad 解析、`config/default/vial-layout-overrides.json` から `config/default/vial.json` を生成する |
| `script/apply_board_profile.py` | install / 実機補助 | `config/boards/<version>/conf` を `config/default/` へ反映し、`/mnt/p3/board_profile.json` marker と runtime keymap reset を扱う |
| `script/apply_device_profile.py` | install / 実機補助 | installed device profile を `/mnt/p3` と systemd policy へ dry-run / backup / restart 付きで反映する |
| `script/apply_power_shed.sh` | install / 実機補助 | runtime keymap と touch panel browser の power shed 設定を実機へ反映する |
| `script/hidloom_hidd_live_smoke.py` | live smoke | `hidloom-hidd` owner の broker socket へ keyboard / modifier / US-sub / consumer / mouse と malformed / burst frame を送る |
| `script/device_profile_inventory.py` | install / 実機補助 | `config/device-profiles/*.json` を検査し、profile id / runtime files / service policy を列挙する |
| `script/ensure_httpd_tls_cert.sh` | install 補助 | HTTPD 用 self-signed TLS cert/key を初回生成する |
| `script/select_touch_panel_profile.py` | install / 実機補助 | display size から touch-panel profile を選び、runtime keymap / layout / Vial definition を配置する |
| `script/start_touch_panel_browser.sh` | install / 実機補助 | touch panel kiosk 用 Chromium を loopback HTTP UI へ起動し、CDP 有効時は blank/error tab を touch panel URL へ戻す |
| `tools/touch_kiosk_health_probe.py` | 実機補助 | touch panel kiosk の実 DOM を Chromium DevTools Protocol 経由で確認し、blank/error/empty body なら touch panel URL へ戻す |
| `script/showlog.sh` | 実機補助 | `logicd` / `httpd` journal を見る |
| `script/preview_vialrgb_direct.py` | live smoke | VialRGB direct frame を実機 socket へ連続送信する |
| `script/preview_vialrgb_effects.py` | live smoke | 実装済み VialRGB effect を実機で順に preview する |
| `script/print_vialrgb_supported.py` | live smoke | 実機 `viald` から supported VialRGB effect ID を読む |
| `script/send_btd_report.py` | live smoke | `btd` socket へ HID report candidate を送る |
| `script/send_standard_keyboard_report.py` | live smoke | usbd broker socket または診断用 direct path へ標準 keyboard HID report candidate を送る |
| `script/send_windows_ime_custom_hid_report.py` | live smoke | opt-in Windows IME custom HID report candidate を送る |
| `script/send_windows_ime_raw_hid_frame.py` | live smoke | Raw HID multiplex の Windows IME diagnostic frame を送る |
| `script/socket_test_helpers.py` | test support | Unix socket mode assertions shared by daemon smoke tests |
| `script/suite_runner.py` | test 補助 | suite entrypoint の共通実行 helper |
| `script/windows_ime_raw_hid_receiver_poc.py` | live smoke | Windows host 側 Raw HID multiplex receiver の PoC |

`script/start_touch_panel_browser.sh` の blank/error tab repair は
`HIDLOOM_TOUCH_PANEL_REMOTE_DEBUGGING_PORT` を設定した時だけ有効になり、
DevTools endpoint は既定 `127.0.0.1` の loopback に閉じます。
`HIDLOOM_TOUCH_PANEL_BROWSER_REPAIR_DELAY_SEC`、`HIDLOOM_TOUCH_PANEL_BROWSER_REPAIR_ATTEMPTS`、
`HIDLOOM_TOUCH_PANEL_BROWSER_REPAIR_INTERVAL_SEC` で retry timing を調整できます。

`tools/perf_baseline.py` は速度・メモリ使用量チューニング前後の baseline 収集 helper として
[performance-tuning-plan.md](performance-tuning-plan.md) と `tools/README.md` から使う。

今後、新しい非 test helper を `script/` に追加した場合は、この表へ載せる。
実機の daemon socket へ直接イベントを流して状態を変える汎用操作 tool は、原則 `tools/` に置く。

## repository root の shell helper

root 直下の shell script は、install / USB gadget / 実機 smoke の入口として残す。
新しく追加した場合は、この表へ載せる。

| script | 分類 | 役割 |
|---|---|---|
| `setup_fresh_rpi.sh` | install | fresh Raspberry Pi OS 向け bootstrap。apt / pip / boot config / systemd / `/mnt/p3` 初期化を行う |
| `setup_usb_gadget.sh` | install | USB HID composite gadget を configfs で構成する |
| `getkeymap.sh` | live smoke | `ctrl_events.sock` の `G` command で runtime keymap を読む |
| `setkeycode.sh` | live smoke | `ctrl_events.sock` の `M` command で runtime keymap を一時変更する |

旧 `test_getkeymap.sh` / `test_setkeycode.sh` は削除した。前者は daemon 不在時に成功扱いで
例を表示するだけで検査にならず、後者は live keymap を変更して復旧しなかった。wrapper の
回帰は `script/test_keymap_cli_helpers.py` の isolated Unix socket fixture で行い、実機変更は
backup/verify/save/rollback を明示した [SETKEYCODE.md](../../SETKEYCODE.md) に従う。

### Vial / VialRGB / VIL

- `script/test_vial_keycode_codec.py`
- `script/test_vial_protocol_local.py`
- `script/test_vial_custom_keycodes_config.py`
- `script/test_vil_layout_codec.py`
- `script/test_vil_import_warnings.py`
- `script/test_vialrgb_protocol.py`
- `script/test_vialrgb_persistence.py`

`script/test_vial_protocol.py` は `/tmp/viald_events.sock` が必要な実機 / daemon 接続テストです。
ローカル daemon 無し環境では失敗してよい。ローカル回帰は `script/test_vial_protocol_local.py` を使う。

実機 / daemon 接続を前提にする主な live smoke:

- `script/test_vial_protocol.py`
- `script/test_vialrgb_protocol.py`
- `script/test_vialrgb_persistence.py`
- `script/test_led_direct_frame_metrics_watch_tool.py`
- `script/test_vial_unlock_runtime.py`
- `script/test_vial_matrix_state_runtime.py`
- `script/test_vial_raw_hid_host.py`
- `script/test_vial_runtime_path.py`
- `script/test_vial_set_keycode.py`
- `script/test_viald_echo.py`
- `script/test_lighting_key_runtime.py`

これらは suite の常時実行対象には入れず、実機・socket・権限・host 側条件が揃った時だけ使う。
`script/test_real_device_keyboard_suite.py` は native owner が active の場合、旧 Python-owner 前提の
`test_vial_unlock_runtime.py` / `test_vial_matrix_state_runtime.py` / `test_vial_runtime_path.py` を既定で
skip し、Python-owner rollback 中にだけ `--include-python-owner-smoke` で含める。

### Bluetooth / btd

- `script/test_btd_suite.py`
- `script/test_btd_protocol.py`
- `script/test_btd_protocol_doc.py`
- `script/test_bluetooth_docs_current.py`
- `script/test_btd_backend.py`
- `script/test_btd_bluez_backend.py`
- `script/test_btd_gatt_app.py`
- `script/test_btd_pairing.py`
- `script/test_bt_reconnect_watch_tool.py`

### output / spid / ledd

- `script/test_output_router.py`
- `script/test_output_router_force.py`
- `script/test_logicd_output_switch_release.py`
- `script/test_logicd_mouse_output_mode.py`
- `script/test_logicd_mouse_acceleration.py`
- `script/test_logicd_matrix_input_priority.py`
  - `logicd` の matrix socket intake が packet parse と queue put に留まり、HID / LED / interaction の重い処理を持ち込まないことを確認する。
- `script/test_logicd_matrix_event_processing_boundary.py`
  - `logicd` の `process_matrix_event()` が pressed state / InteractionEngine dispatch に留まり、ファイルI/Oや保存処理を直接持ち込まないことを確認する。
- `script/test_logicd_output_router_boundary.py`
  - `OutputRouter` が matrix socket intake と直接結合せず、keyboard HID report fan-out component に留まることを確認する。
- `script/test_logicd_resolved_action_heavy_boundary.py`
  - BT / Wi-Fi / macro / output preparation など重い可能性がある処理が raw matrix processing ではなく resolved action 境界に留まることを確認する。
- `script/test_matrixd_scan_optimization.py`
- `script/test_matrixd_debounce.py`
  - `matrixd/debounce.[ch]` の count / time debounce、可変scan周期、高頻度raw確認、送信成功後commit semantics を確認する。
- `script/test_matrixd_build.py`
  - `matrixd.c` と `debounce.c` が実機なしの C build で壊れていないことを確認する。
- `script/test_i2cd_connectivity.py`
  - OLED connectivity icon row の output mode / Wi-Fi snapshot 変換を確認する。
  - Wi-Fi off / unavailable 非表示、powered 未接続 `wifi0` 通常表示、connected `wifi3` 反転表示を固定する。
- `script/test_i2cd_oled_icons.py`
  - BT / Wi-Fi / USB / Pi / auto / daemon status の可変幅 OLED icon bitmap file、icon ごとのコメント、`CONNECTIVITY_ICONS`、`icon_bitmap()`、bitmap hot reload を確認する。
- `script/test_i2cd_output_mode_label.py`
  - i2cd Ready 表示の出力モード行が text ではなく icon row を描き、active icon が反転描画されることを確認する。
- `script/test_logicd_daemon_status.py`
  - logicd が daemon status を集約して i2cd 向け JSON Lines payload として送ることを確認する。
- `script/test_i2cd_direct_frame_fps.py`
- `script/test_i2cd_warning_render.py`
- `script/test_spid_suite.py`
- `script/test_ledd_direct_frame.py`
- `script/test_ledd_direct_frame_socket.py`
- `script/test_ledd_direct_frame_apply.py`
- `script/test_ledd_direct_frame_fallback.py`
- `script/test_led_semantic_roles.py`
- `script/test_led_life_game_effect.py`
- `script/test_led_pattern_metrics_runtime.py`
- `script/test_led_video_ledd_direct.py`
- `script/test_demo_asset_paths.py`
  - 外部videoがないpackageでも標準libraryだけのprocedural patternへfallbackするSH2経路を固定する。

## 次の棚卸し作業

1. `script/test_validation_suite.py` の対象を定期的に現状の重要回帰テストへ更新する。
2. daemon/socket 前提のテストには、失敗時メッセージか skip 条件を明記する。
3. root 直下の shell helper が現行 API / install 手順でまだ有効か確認する。
4. 実機手動 tool は `tools/README.md` に一覧化する。
5. 実装済み機能を差し込むためだけの一時 patch helper と、その helper だけを確認する薄いテストは残さない。
6. InteractionEngine テストがさらに肥大化したら、`tap_hold` / `combo` / `tap_dance` /
   `key_override` に分割する。

## 直近の実行セット

軽いローカル確認:

```bash
python3 script/test_matrixd_debounce.py
python3 script/test_matrixd_build.py
python3 script/test_matrixd_scan_optimization.py
python3 script/test_logicd_matrix_input_priority.py
python3 script/test_logicd_matrix_event_processing_boundary.py
python3 script/test_logicd_output_router_boundary.py
python3 script/test_logicd_resolved_action_heavy_boundary.py
python3 script/test_i2cd_oled_icons.py
python3 script/test_i2cd_connectivity.py
python3 script/test_i2cd_output_mode_label.py
python3 script/test_http_security.py
```
