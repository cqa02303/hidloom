# Keyboard MCP Server

`dev/mcp/keyboard/server.py` は、Codex や MCP client からキーボード実機・checkout・設定を
read-only で調べるための診断サーバです。キー入力送信、keymap 書き換え、service restart、
pull / commit / push などの状態変更は行いません。

実装ディレクトリの quick reference は [../../dev/mcp/keyboard/README.md](../../dev/mcp/keyboard/README.md)、
2026-06-13 時点の Codex CLI / MCP 環境確認、完了状況、次の予定は
private workspace reference *(omitted from public export)* を参照します。
実機で一時修正を試した後の標準的な戻し方は
[real-device-experiment-workflow.md](real-device-experiment-workflow.md) にまとめます。
状態変更を行う MCP tool を作る場合の別 server 設計は
[../policy/mcp-write-capable-tool-design.md](../policy/mcp-write-capable-tool-design.md) に分けます。

## 入口

| 目的 | 使うもの |
| --- | --- |
| 作業開始時に repo / 実機 / keymap / script をまとめて見る | [`get_development_snapshot`](#get_development_snapshot) |
| 実機側の service / HID / socket が揃っているか見る | [`run_preflight`](#run_preflight) |
| runtime keymap が読める権限か見る | [`check_runtime_access`](#check_runtime_access) |
| 1 つのキーがどの action / route / HID bytes になるか見る | [`inspect_key_position`](#inspect_key_position) |
| keycode 単体の出力先を確認する | [`explain_route_for_keycode`](#explain_route_for_keycode) |
| keyboard-side checkout を pull してよい状態か見る | [`get_repo_state`](#get_repo_state), [`get_repo_dirty_summary`](#get_repo_dirty_summary), [`get_checkout_hygiene_summary`](#get_checkout_hygiene_summary), [`get_checkout_drift_summary`](#get_checkout_drift_summary), [`get_pull_readiness_summary`](#get_pull_readiness_summary), [`get_checkout_cleanup_candidates`](#get_checkout_cleanup_candidates), [`get_checkout_preserve_diff_summary`](#get_checkout_preserve_diff_summary), [`get_checkout_backup_plan_summary`](#get_checkout_backup_plan_summary), [`get_manual_cleanup_verification_plan`](#get_manual_cleanup_verification_plan), [`get_cleanup_review_order_summary`](#get_cleanup_review_order_summary), [`get_reflection_cleanup_alignment_summary`](#get_reflection_cleanup_alignment_summary), [`get_temporary_change_restore_plan_summary`](#get_temporary_change_restore_plan_summary), [`get_real_device_experiment_workflow_summary`](#get_real_device_experiment_workflow_summary) |
| 実機 SSH 候補の到達性と checkout 状態を見る | [`get_real_device_access_summary`](#get_real_device_access_summary) |
| 実機作業開始時に見る順序をまとめる | [`get_real_device_work_start_summary`](#get_real_device_work_start_summary) |
| Codex CLI からこの MCP server を使える設定か見る | [`get_codex_mcp_status`](#get_codex_mcp_status) |
| 実機反映前にpackage-first更新とnative artifact除外を確認する | [`get_sync_safety_plan`](#get_sync_safety_plan), [`get_selective_sync_plan`](#get_selective_sync_plan) |
| 実機反映の手動 apply 前チェックリストを作る | [`get_reflection_apply_plan`](#get_reflection_apply_plan) |
| HTTP UI/API の実機 health を要約する | [`get_http_status_summary`](#get_http_status_summary) |
| USB/output 経路の readiness と注意点をまとめる | [`get_output_readiness_summary`](#get_output_readiness_summary), [`get_runtime_issue_summary`](#get_runtime_issue_summary) |
| HTTP UI / Vial / BLE の疎通をまとめて見る | [`get_interface_snapshot`](#get_interface_snapshot) |
| 更新系 API を設計する前の充足条件を見る | [`get_update_readiness_summary`](#get_update_readiness_summary) |
| `/mnt/p3` runtime JSON の状態を要約する | [`get_runtime_state_summary`](#get_runtime_state_summary) |

## 起動と確認

MCP client から stdio server として起動する場合:

```bash
python3 dev/mcp/keyboard/server.py --stdio
```

Codex CLI / Codex app から使うローカル設定は、global `~/.codex/config.toml` に stdio server として登録します。
この環境では次の形で `keyboard` server を登録済みです。

```bash
codex mcp add keyboard -- python3 /srv/hidloom/dev/mcp/keyboard/server.py --stdio
codex mcp get keyboard
```

登録後の認証表示が `Auth: Unsupported` になるのは stdio server では正常です。HTTP server ではないため
MCP レベルの bearer token / OAuth は使わず、起動できる OS user、Codex の trusted project 設定、
必要なら SSH login を認証境界にします。

CLI で 1 tool だけ実行する場合:

```bash
python3 dev/mcp/keyboard/server.py --tool get_development_snapshot --repo-root /srv/hidloom
python3 dev/mcp/keyboard/server.py --tool explain_route_for_keycode --keycode KC_HENKAN
python3 dev/mcp/keyboard/server.py --tool inspect_key_position --matrix 7,0
```

回帰確認:

```bash
python3 script/test_mcp_keyboard_server.py
python3 -m py_compile dev/mcp/keyboard/server.py script/test_mcp_keyboard_server.py
```

## 認証と公開境界

当面の推奨は `stdio` だけを有効にし、network listen する MCP endpoint は作らないことです。
理由は、この server が repo / 実機 runtime / journal を読む診断面であり、LAN 公開より
Codex が必要な時だけ process を起動する形のほうが認証境界を小さく保てるためです。

| 利用形態 | 認証境界 | 推奨度 | 備考 |
| --- | --- | --- | --- |
| local stdio | OS user、Codex trusted project、local file permissions | 推奨 | 現在の標準形 |
| SSH 越し stdio | SSH key、remote OS user、remote file permissions | 推奨 | 実機側 server を port 公開せず起動できる |
| loopback HTTP | local bearer token など | 後続候補 | browser / 複数 client 共有が必要になった時だけ |
| LAN / Internet HTTP | OAuth 2.1 / protected resource metadata / scoped token | 非推奨から開始 | read-only でも runtime 情報が出るため、必要性が出るまで作らない |

write-capable tool を追加する場合は、read-only `keyboard` server とは別 server / 別 tool allowlist に分けます。
少なくとも `keymap.write`、`service.restart`、`send_key`、`git` 操作は、dry-run plan と明示確認の設計が
できるまで MCP tool に入れません。
2026-06-13 時点の設計は [../policy/mcp-write-capable-tool-design.md](../policy/mcp-write-capable-tool-design.md) に固定済みです。
最初の実キー送信候補は MCP 本体ではなく、dry-run default の
[`script/text_send_smoke_sequence.py`](../../script/text_send_smoke_sequence.py) として実装し、
`--send --confirm SEND_TEXT_SMOKE_TO_FOCUSED_HOST` の時だけ focused host へ bounded sequence を送ります。

Remote 実機を Codex から使う場合は、HTTP ではなく SSH command の stdio 起動を第一候補にします。
2026-06-13 時点では、`<keyboard-host>` には Codex CLI と `~/.codex/config.toml` は未導入です。
そのため実機側を直接 Codex MCP host にするのではなく、desktop Codex から SSH で read-only tool を
実行する運用を標準にします。設定例は [codex-ssh-stdio-mcp-profile.md](codex-ssh-stdio-mcp-profile.md)
を参照します。

```bash
ssh keyboard.example 'cd /srv/hidloom && python3 dev/mcp/keyboard/server.py --stdio'
```

この場合も認証は SSH key と remote user 権限で扱い、MCP server 自体には secret を持たせません。

## 機能一覧

| tool | 主な用途 | 主な入力 | 状態変更 |
| --- | --- | --- | --- |
| [`get_status`](#get_status) | MCP server と主要 config / keymap の所在を確認 | なし | なし |
| [`get_usb_split_status`](#get_usb_split_status) | USB HID split の設定意図を確認 | なし | なし |
| [`explain_route_for_keycode`](#explain_route_for_keycode) | keycode 単体の output route を説明 | `keycode` | なし |
| [`run_preflight`](#run_preflight) | service / HID path / socket / route の事前確認 | `include_systemctl` | なし |
| [`get_keymap_summary`](#get_keymap_summary) | runtime keymap と system default の差分を要約 | `max_changes` | なし |
| [`collect_journal_excerpt`](#collect_journal_excerpt) | allowlist 済み service の journal 抜粋を取得 | `service`, `lines` | なし |
| [`check_runtime_access`](#check_runtime_access) | MCP process user の runtime path 権限を確認 | `paths` | なし |
| [`get_script_summary`](#get_script_summary) | `KC_SH*` script の所在・label・安全メタデータを要約 | なし | なし |
| [`preview_hid_report`](#preview_hid_report) | keycode の HID report bytes を送信せずに確認 | `keycode`, `modifiers` | なし |
| [`inspect_key_position`](#inspect_key_position) | matrix 座標の current/default action と route を確認 | `matrix` または `row`/`col` | なし |
| [`get_repo_state`](#get_repo_state) | checkout の branch / commit / dirty files を確認 | `repo_root`, `max_files` | なし |
| [`get_repo_dirty_summary`](#get_repo_dirty_summary) | dirty files を領域別に分類し、実機反映時の注意点を返す | `repo_root`, `max_files` | なし |
| [`get_checkout_hygiene_summary`](#get_checkout_hygiene_summary) | dirty checkout を hygiene bucket と推奨 action に変換する | `repo_root`, `max_files` | なし |
| [`get_checkout_drift_summary`](#get_checkout_drift_summary) | dirty checkout を反映由来候補と local runtime 変更に分ける | `repo_root`, `max_files`, `reflection_categories` | なし |
| [`get_pull_readiness_summary`](#get_pull_readiness_summary) | checkout が手動 pull 可能かを blocker と ahead/behind で要約する | `repo_root`, `max_files`, `reflection_categories` | なし |
| [`get_checkout_cleanup_candidates`](#get_checkout_cleanup_candidates) | dirty checkout を preserve / cleanup candidate / review に分ける | `repo_root`, `max_files`, `reflection_categories` | なし |
| [`get_checkout_preserve_diff_summary`](#get_checkout_preserve_diff_summary) | preserve candidate の diff metadata を本文なしで要約する | `repo_root`, `max_files`, `reflection_categories` | なし |
| [`get_checkout_backup_plan_summary`](#get_checkout_backup_plan_summary) | preserve candidate の backup checklist を read-only で返す | `repo_root`, `max_files`, `reflection_categories`, `backup_root` | なし |
| [`get_manual_cleanup_verification_plan`](#get_manual_cleanup_verification_plan) | 手動 cleanup / pull 前の最終 gate を返す | `repo_root`, `max_files`, `reflection_categories`, `backup_root`, `backup_confirmed` | なし |
| [`get_cleanup_review_order_summary`](#get_cleanup_review_order_summary) | cleanup 判断用の確認順序を read-only で返す | `repo_root`, `max_files`, `reflection_categories`, `backup_root`, `backup_confirmed` | なし |
| [`get_reflection_cleanup_alignment_summary`](#get_reflection_cleanup_alignment_summary) | cleanup candidate を local git ref と照合する | `repo_root`, `max_files`, `reflection_categories`, `reference` | なし |
| [`get_temporary_change_restore_plan_summary`](#get_temporary_change_restore_plan_summary) | 一時変更 stash の確認・復元計画を返す | `repo_root`, `stash_ref`, `max_stashes` | なし |
| [`get_real_device_experiment_workflow_summary`](#get_real_device_experiment_workflow_summary) | 実機一時実験 workflow の gate を返す | `repo_root`, `max_files`, `max_stashes` | なし |
| [`get_real_device_access_summary`](#get_real_device_access_summary) | 実機 SSH 候補の名前解決・疎通・remote checkout 状態を返す | `targets`, `repo_root`, `probe_ssh`, `timeout_sec` | なし |
| [`get_development_snapshot`](#get_development_snapshot) | 開発開始時の総合 snapshot を取得 | `repo_root`, `include_systemctl`, `max_files`, `max_changes` | なし |
| [`get_real_device_work_start_summary`](#get_real_device_work_start_summary) | 実機作業開始時の確認順序を返す | `repo_root`, `include_http_status`, `max_files`, `max_changes` | なし |
| [`get_codex_mcp_status`](#get_codex_mcp_status) | Codex CLI の MCP 登録と trust 状態を確認 | `config_path`, `repo_root`, `server_name` | なし |
| [`get_sync_safety_plan`](#get_sync_safety_plan) | split package更新、rsync exclude、native artifact警告を返す | `target`, `repo_root` | なし |
| [`get_selective_sync_plan`](#get_selective_sync_plan) | dirty category から targeted rsync plan と smoke 手順を返す | `target`, `repo_root`, `categories`, `max_files` | なし |
| [`get_reflection_apply_plan`](#get_reflection_apply_plan) | 手動実機反映前の operator checklist と stop condition を返す | `target`, `repo_root`, `categories`, `max_files`, `include_http_status` | なし |
| [`get_systemd_unit_summary`](#get_systemd_unit_summary) | allowlist 済み systemd unit の状態・drop-in・安全な env flag を要約 | `service`, `repo_root` | なし |
| [`get_codex_task_mailbox_summary`](#get_codex_task_mailbox_summary) | Codex task mailbox の件数、最新ファイル、結果ペアを要約 | `tasks_dir`, `max_items` | なし |
| [`get_http_status_summary`](#get_http_status_summary) | local HTTPS `/api/status` の health を要約 | `url`, `username`, `password`, `timeout_sec`, `verify_tls` | なし |
| [`get_output_readiness_summary`](#get_output_readiness_summary) | preflight と HTTP status を合わせた output readiness を返す | `include_systemctl`, `include_http_status` | なし |
| [`get_interface_snapshot`](#get_interface_snapshot) | HTTP UI/API、Vial service、BLE readiness をまとめる | `include_systemctl`, `include_http_status` | なし |
| [`get_update_readiness_summary`](#get_update_readiness_summary) | 更新系 API 候補の前提条件と未充足項目をまとめる | `repo_root`, `include_http_status` | なし |
| [`get_runtime_issue_summary`](#get_runtime_issue_summary) | runtime readiness issue の原因候補と次の read-only check を返す | `include_systemctl`, `include_http_status` | なし |
| [`get_runtime_state_summary`](#get_runtime_state_summary) | `/mnt/p3` runtime JSON の metadata と要約を返す | `include_keymap_diff`, `max_changes` | なし |

## 機能詳細

### `get_status`

MCP server version、repository root、主要ファイルの存在、default keymap の layer 数などを返します。
最初に「この server がどの checkout を見ているか」を確認したい時に使います。

関連:

- 実装: [../../dev/mcp/keyboard/server.py](../../dev/mcp/keyboard/server.py)
- 全体構成: [../architecture/system-overview.md](../architecture/system-overview.md)

### `get_usb_split_status`

USB gadget の keyboard / mouse / consumer / US sub split 設定を要約します。Windows JIS / US split の
期待形を確認する入口です。

現在の主な意図:

- JIS main keyboard は `/dev/hidg0`
- US sub keyboard は `/dev/hidg2`
- `jis_special_us_default` では通常 keyboard usage は US sub、JIS 固有 usage は JIS main
- mouse / consumer は設定された broker / endpoint route に従う

関連:

- Windows IME routing: [../input/windows-us-custom-hid-ime-routing-design.md](../input/windows-us-custom-hid-ime-routing-design.md)
- Windows JIS / US INF 実験: [../research/windows-jis-keyboard-vid-pid.md](../research/windows-jis-keyboard-vid-pid.md)
- USB report broker: [../daemon/specs/hidd/usb-gadget-multi-report-plan.md](../daemon/specs/hidd/usb-gadget-multi-report-plan.md)

### `explain_route_for_keycode`

`keycode` を 1 つ受け取り、`keyboard` / `mouse` / `consumer` / split keyboard class のどれとして扱うか、
どの endpoint に出す意図か、理由を返します。

例:

```bash
python3 dev/mcp/keyboard/server.py --tool explain_route_for_keycode --keycode KC_HENKAN
python3 dev/mcp/keyboard/server.py --tool explain_route_for_keycode --keycode KC_A
```

`KC_ZKHK`、`KC_RO`、`KC_KANA`、`KC_JYEN`、`KC_HENKAN`、`KC_MUHENKAN`、`KC_INT6`-`KC_INT9` は
JIS main 側に残す JIS 固有 keycode として扱います。`KC_LANG1` / `KC_LANG2` は
ImeOn/ImeOff 用として `jis_special_us_default` でも US sub route に従います。

関連:

- keycode UI: [../keycode/http-remap-keycode-ui.md](../keycode/http-remap-keycode-ui.md)
- IME routing: [../input/windows-us-custom-hid-ime-routing-design.md](../input/windows-us-custom-hid-ime-routing-design.md)

### `run_preflight`

実機や checkout が、作業前に必要な最低限の状態かを read-only で見ます。
`include_systemctl=false` にすると `systemctl` probe を省略でき、開発 PC や chroot でも軽く実行できます。

主に見るもの:

- `hidloom-usb-gadget`、`viald`、`hidd`、`logicd`、`matrixd`、`ledd`、`i2cd` の状態
- `/dev/hidg0`、`/dev/hidg1`、`/dev/hidg2`
- `/tmp/usbd_hid_reports.sock`、`/tmp/matrix_events.sock`、`/tmp/ledd_events.sock`
- USB split と代表 keycode route

関連:


### `get_keymap_summary`

runtime keymap と repository default keymap を比較し、layer 数、layer ごとの割り当て数、default からの
差分 sample、注意が必要な action を返します。実機上では `/mnt/p3/keymap.json` が存在すれば優先し、
読めない場合は structured error を返して fake diff は作りません。

注意 action の例:

- `KC_SH*` script
- shutdown / reboot / Wi-Fi power / Bluetooth forget
- text send 系 action

`/mnt/p3/keymap.json` が `root:root 600` の実機では、通常 user の MCP process から読めないことがあります。
その場合は [`check_runtime_access`](#check_runtime_access) の結果と合わせて見ます。

関連:

- runtime keymap 方針: [../hardware/board-profiles.md](../hardware/board-profiles.md)

### `collect_journal_excerpt`

allowlist された keyboard service の journal を、最大 200 行までの範囲で取得します。
広い log browser ではなく、[`run_preflight`](#run_preflight) で inactive や missing が出た後の追跡用です。

入力:

- `service`: `logicd` などの許可済み service 名
- `lines`: 1-200

関連:

- logging 方針: [../policy/logging-status-policy.md](../policy/logging-status-policy.md)
- daemon log output: [../daemon/logicd-log-output.md](../daemon/logicd-log-output.md)

### `check_runtime_access`

MCP process の user / group と、runtime path の stat / access を返します。
`get_keymap_summary` が permission error になった時や、MCP server を service 化する前の権限確認に使います。
runtime keymap が存在するのに読めない場合は、専用 group へ読取権限を渡す案と、簡易な `0644`
案を recommendation として返します。コマンドは実行しません。

default で見る path:

- `/mnt/p3/keymap.json`
- `/mnt/p3/led_state.json`
- `/mnt/p3/bluetooth_hosts.json`
- `/mnt/p3/script`
- `/mnt/p3`

関連:


### `get_script_summary`

`KC_SH*` script の label、runtime / fallback / missing、readability、行数、安全 metadata を返します。
script body は返しません。危険判定は HTTP script editor と同じ `script_metadata.py` の parser に寄せています。

関連:

- script safety metadata: [script-safety-metadata.md](script-safety-metadata.md)
- script smoke: [kc-sh-hid-text-cat-smoke.md](kc-sh-hid-text-cat-smoke.md)

### `preview_hid_report`

keycode と optional modifiers から、keyboard / consumer HID report bytes を作り、送信せずに返します。
route の説明と実際の bytes を切り分けたい時に使います。

`KC_ZKHK` は `logicd` 内部 marker 付きの canonical report として preview します。route adapter は
JIS main へ write する前に marker を消すため、preview は「内部表現の確認」です。

関連:

- USB report broker: [../daemon/specs/hidd/usb-gadget-multi-report-plan.md](../daemon/specs/hidd/usb-gadget-multi-report-plan.md)
- IME routing: [../input/windows-us-custom-hid-ime-routing-design.md](../input/windows-us-custom-hid-ime-routing-design.md)

### `inspect_key_position`

matrix 座標を 1 つ指定し、各 layer の current action、system default action、変更有無、注意 action、
必要に応じた route / HID report preview を返します。

入力は `matrix="row,col"` または `row` と `col` の組み合わせです。`include_reports=false` で
per-action report preview を省略できます。

例:

```bash
python3 dev/mcp/keyboard/server.py --tool inspect_key_position --matrix 7,0
python3 dev/mcp/keyboard/server.py --tool inspect_key_position --row 7 --col 0 --no-reports
```

関連:

- matrix 座標: [../hardware/keyswitch-matrix-map.md](../hardware/keyswitch-matrix-map.md)
- keycode UI: [../keycode/http-remap-keycode-ui.md](../keycode/http-remap-keycode-ui.md)

### `get_repo_state`

指定 checkout の branch、commit、upstream、last commit、dirty files を bounded に返します。
実機側 checkout を更新する前、または実機観測と手元 source の差を見たい時に使います。

入力:

- `repo_root`: 省略時は MCP server が見ている repository root
- `max_files`: dirty files の最大件数

関連:


### `get_repo_dirty_summary`

指定 checkout の dirty files を、実機反映や `git pull` 判断に使いやすいよう分類します。
`get_repo_state` が生の status 一覧に近い入口なのに対し、この tool は「どの領域の差分か」と
「runtime に効く変更か」を短く返します。

主な分類:

- `mcp`: `dev/mcp/keyboard`、`script/test_mcp_keyboard_server.py`、`codex_tasks`
- `docs`: `docs/`、top-level `README.md`
- `config`: `config/default/`
- `logicd` / `hidd` / `usbd` / `http`
- `usb_gadget`: `setup_usb_gadget.sh`
- `native_artifact`: `daemon/matrixd/matrixd`、`bin/hidloom-*`

`config`、`logicd`、`hidd`、`usbd`、`usb_gadget`、systemd unit 系は `runtime_behavior` として attention に載せます。
native binary は target build を壊しやすいため `native_binary` として別に目立たせます。
未追跡ファイルは本来の領域カテゴリを保ったまま `untracked` attention に載せます。

例:

```bash
python3 dev/mcp/keyboard/server.py --tool get_repo_dirty_summary --repo-root /srv/hidloom --max-files 80
```

関連:

- raw repo state: [`get_repo_state`](#get_repo_state)
- 実機反映 plan: [`get_sync_safety_plan`](#get_sync_safety_plan)

### `get_checkout_hygiene_summary`

[`get_repo_dirty_summary`](#get_repo_dirty_summary) の dirty entry を、実機反映前に見たい
hygiene bucket と推奨 action に変換します。実行はせず、git clean / file delete / rsync / checkout edit は
行いません。

主に返すもの:

- `untracked_directory` / `untracked_file` / `runtime_affecting` / `native_artifact` などの bucket count
- path ごとの `path_kind`、severity、recommended action
- reflection 前に止めるべき issue
- `get_repo_dirty_summary` 由来の category / status summary

例:

```bash
python3 dev/mcp/keyboard/server.py --tool get_checkout_hygiene_summary --repo-root /srv/hidloom --max-files 80
```

関連:

- dirty 分類: [`get_repo_dirty_summary`](#get_repo_dirty_summary)
- 実機反映 checklist: [`get_reflection_apply_plan`](#get_reflection_apply_plan)

### `get_checkout_drift_summary`

[`get_checkout_hygiene_summary`](#get_checkout_hygiene_summary) の結果をもとに、dirty checkout の由来を
大まかに分けます。特に、手動 `rsync` で載せた可能性が高い untracked path と、実機側で残っている
runtime-affecting tracked dirty を分けて見たいときに使います。

主に返すもの:

- `reflection_candidates`: `mcp` / `docs` など reflection category 内の untracked path
- `local_runtime_changes`: tracked な config / logicd / usbd / gadget などの runtime-affecting dirty
- `local_untracked_runtime`: untracked な runtime-affecting source
- `ordinary_dirty` / `backup_or_generated`
- pull / sync 前の recommendation

例:

```bash
python3 dev/mcp/keyboard/server.py --tool get_checkout_drift_summary --repo-root /srv/hidloom --max-files 80
```

関連:

- hygiene bucket: [`get_checkout_hygiene_summary`](#get_checkout_hygiene_summary)
- 手動反映 checklist: [`get_reflection_apply_plan`](#get_reflection_apply_plan)

### `get_pull_readiness_summary`

既存の local upstream ref と [`get_checkout_drift_summary`](#get_checkout_drift_summary) を使い、
手動 `git pull` の前に止めるべき blocker をまとめます。`git fetch` / `git pull` / `git clean` /
`git reset` / file delete / rsync / checkout edit は実行しません。

主に返すもの:

- branch / upstream / commit
- existing local upstream refs に基づく ahead / behind
- dirty checkout、reflection candidates、local runtime dirty などの blocker
- pull 前の checklist と recommendation

例:

```bash
python3 dev/mcp/keyboard/server.py --tool get_pull_readiness_summary --repo-root /srv/hidloom --max-files 80
```

関連:

- drift 分類: [`get_checkout_drift_summary`](#get_checkout_drift_summary)
- raw repo state: [`get_repo_state`](#get_repo_state)

### `get_checkout_cleanup_candidates`

[`get_checkout_drift_summary`](#get_checkout_drift_summary) を、実機 checkout 整備前の
`preserve` / `cleanup_candidates` / `review` bucket に変換します。`git clean` / `git reset` /
`git checkout` / `rm` / `rsync` / pull / fetch / file edit は実行しません。

主に返すもの:

- preserve: runtime-affecting local changes
- cleanup candidates: targeted reflection artifact や generated / backup 候補
- review: ordinary dirty files
- destructive 操作の代わりに使う read-only check

例:

```bash
python3 dev/mcp/keyboard/server.py --tool get_checkout_cleanup_candidates --repo-root /srv/hidloom --max-files 80
```

関連:

- drift 分類: [`get_checkout_drift_summary`](#get_checkout_drift_summary)
- pull 可否: [`get_pull_readiness_summary`](#get_pull_readiness_summary)

### `get_checkout_preserve_diff_summary`

[`get_checkout_cleanup_candidates`](#get_checkout_cleanup_candidates) の `preserve` 対象について、
diff 本文なしの metadata だけを返します。tracked file は `git diff --numstat` と `git diff --name-status`、
untracked file は path kind と size だけを返し、diff hunk / file body / untracked file content は返しません。

主に返すもの:

- preserve candidate 数
- tracked / untracked / binary count
- tracked file の insertions / deletions / name-status
- untracked file の size
- redaction note

例:

```bash
python3 dev/mcp/keyboard/server.py --tool get_checkout_preserve_diff_summary --repo-root /srv/hidloom --max-files 80
```

関連:

- cleanup bucket: [`get_checkout_cleanup_candidates`](#get_checkout_cleanup_candidates)
- pull 可否: [`get_pull_readiness_summary`](#get_pull_readiness_summary)

### `get_checkout_backup_plan_summary`

[`get_checkout_preserve_diff_summary`](#get_checkout_preserve_diff_summary) の preserve candidate を、
手動 backup 用 checklist に変換します。backup directory の候補、対象 file list、概算 size、手動 command 例を
返しますが、directory 作成、archive 作成、`git diff` 実行、file write、pull / clean / reset / rsync は行いません。

主に返すもの:

- backup root 候補
- backup 対象 file list
- tracked / untracked count
- estimated file bytes
- 手動 command 例

例:

```bash
python3 dev/mcp/keyboard/server.py --tool get_checkout_backup_plan_summary --repo-root /srv/hidloom --max-files 80
```

関連:

- preserve diff metadata: [`get_checkout_preserve_diff_summary`](#get_checkout_preserve_diff_summary)
- cleanup bucket: [`get_checkout_cleanup_candidates`](#get_checkout_cleanup_candidates)

### `get_manual_cleanup_verification_plan`

手動 cleanup / pull の直前に使う read-only gate です。
[`get_checkout_cleanup_candidates`](#get_checkout_cleanup_candidates)、
[`get_checkout_backup_plan_summary`](#get_checkout_backup_plan_summary)、
[`get_pull_readiness_summary`](#get_pull_readiness_summary) を合わせて、未確認 backup、cleanup candidate、
ordinary dirty、pull blocker をまとめます。`backup_confirmed=true` は operator assertion であり、
archive 内容の検証は行いません。

主に返すもの:

- status と blockers
- backup_confirmed の扱い
- preserve / backup / cleanup / review / pull blocker count
- cleanup / pull 前の verification steps
- 関連 tool 名

例:

```bash
python3 dev/mcp/keyboard/server.py --tool get_manual_cleanup_verification_plan --repo-root /srv/hidloom --max-files 80
python3 dev/mcp/keyboard/server.py --tool get_manual_cleanup_verification_plan --repo-root /srv/hidloom --max-files 80 --backup-confirmed
```

状態変更しないこと:

- backup 作成
- `git clean` / `git reset` / `rm`
- `git fetch` / `git pull`
- `rsync`
- service restart
- file edit

関連:

- backup checklist: [`get_checkout_backup_plan_summary`](#get_checkout_backup_plan_summary)
- cleanup bucket: [`get_checkout_cleanup_candidates`](#get_checkout_cleanup_candidates)
- pull 可否: [`get_pull_readiness_summary`](#get_pull_readiness_summary)

### `get_cleanup_review_order_summary`

手動 cleanup / pull 前の確認対象を優先順に並べます。
[`get_checkout_cleanup_candidates`](#get_checkout_cleanup_candidates) の `preserve` / `cleanup_candidates` /
`review` を、preserve、cleanup directory、cleanup file、ordinary review の順に並べ、
各 path に read-only inspection command 例を付けます。

主に返すもの:

- ordered_review
- preserve / cleanup directory / cleanup file / review count
- gate status と blocker count
- 次の operator loop
- 関連 tool 名

例:

```bash
python3 dev/mcp/keyboard/server.py --tool get_cleanup_review_order_summary --repo-root /srv/hidloom --max-files 80
```

状態変更しないこと:

- backup 作成
- `git clean` / `git reset` / `rm`
- `git fetch` / `git pull`
- `rsync`
- service restart
- file edit

関連:

- final gate: [`get_manual_cleanup_verification_plan`](#get_manual_cleanup_verification_plan)
- cleanup bucket: [`get_checkout_cleanup_candidates`](#get_checkout_cleanup_candidates)

### `get_reflection_cleanup_alignment_summary`

cleanup candidate を local git reference と照合します。default は checkout の upstream、なければ
`origin/main` です。`git fetch` は実行せず、すでに存在する local ref だけを使います。

主に返すもの:

- reference と reference_available
- cleanup candidate count
- present_in_ref / absent_in_ref count
- directory / file candidate count
- 各 candidate の reference state と read-only check

例:

```bash
python3 dev/mcp/keyboard/server.py --tool get_reflection_cleanup_alignment_summary --repo-root /srv/hidloom --max-files 80 --reference origin/main
```

状態変更しないこと:

- `git fetch` / `git pull`
- `git clean` / `git reset` / `rm`
- `rsync`
- service restart
- file edit

関連:

- review order: [`get_cleanup_review_order_summary`](#get_cleanup_review_order_summary)
- cleanup bucket: [`get_checkout_cleanup_candidates`](#get_checkout_cleanup_candidates)

### `get_temporary_change_restore_plan_summary`

実機更新前に `git stash push -u` で退避した一時変更を、MCP client から read-only で確認します。
stash 一覧、選択 stash の summary、手動 inspection / restore command 例を返します。
`git stash apply` / `git stash branch` / `git stash drop` は実行しません。
標準運用では、一時修正そのものを保存し続けるのではなく、実験結果だけを記録して
実機 checkout を clean に戻し、正式変更は repository で実装してから pull します。

主に返すもの:

- stash list
- selected stash summary
- manual restore command 例
- 推奨 restore flow

例:

```bash
python3 dev/mcp/keyboard/server.py --tool get_temporary_change_restore_plan_summary --repo-root /srv/hidloom --max-stashes 8
python3 dev/mcp/keyboard/server.py --tool get_temporary_change_restore_plan_summary --repo-root /srv/hidloom --stash-ref 'stash@{0}'
```

状態変更しないこと:

- `git stash apply`
- `git stash branch`
- `git stash drop`
- `git clean` / `git reset`
- `git fetch` / `git pull`
- `rsync`
- service restart
- file edit

関連:

- pull 可否: [`get_pull_readiness_summary`](#get_pull_readiness_summary)
- final gate: [`get_manual_cleanup_verification_plan`](#get_manual_cleanup_verification_plan)
- 実機実験 workflow: [real-device-experiment-workflow.md](real-device-experiment-workflow.md)

### `get_real_device_experiment_workflow_summary`

[real-device-experiment-workflow.md](real-device-experiment-workflow.md) の運用を守るための read-only gate です。
dirty checkout、pull readiness、stash 状態をまとめ、実験変更を記録して戻すべきか、
clean pull へ進めるかを返します。

主に返すもの:

- workflow status
- dirty / pull / stash summary
- required operator records
- read-only checks
- 実験記録後に operator が実行する manual command 例

例:

```bash
python3 dev/mcp/keyboard/server.py --tool get_real_device_experiment_workflow_summary --repo-root /srv/hidloom --max-files 80
```

状態変更しないこと:

- `git stash`
- `git reset` / `git clean`
- `git fetch` / `git pull`
- `rsync`
- service restart
- file edit

関連:

- 実機実験 workflow: [real-device-experiment-workflow.md](real-device-experiment-workflow.md)
- temporary restore plan: [`get_temporary_change_restore_plan_summary`](#get_temporary_change_restore_plan_summary)
- pull 可否: [`get_pull_readiness_summary`](#get_pull_readiness_summary)

### `get_real_device_access_summary`

実機作業前に、どの SSH target を使うべきかを決めるための read-only summary です。
候補ごとに host name resolution、bounded SSH probe、remote checkout の branch / commit /
dirty 状態を返します。`keyboard.example` のようなaliasが不安定な時は、
実機で確認したnumeric IPを明示できます。文書や既定値にはDHCP addressを固定しません。
SSH probe 失敗時は `error_kind` として host key verification、authentication、
name resolution、timeout などを分類し、次に見るべき環境差を recommendation に出します。
さらに `next_read_only_checks` に、`ssh-keygen -F`、`ssh-keyscan`、`getent hosts` などの
確認コマンド例を返します。これらは operator が確認して実行するための例で、MCP tool は実行しません。

例:

```bash
python3 dev/mcp/keyboard/server.py --tool get_real_device_access_summary --access-target keyboard.example
```

状態変更しないこと:

- `git fetch` / `git pull`
- `git stash` / `git reset` / `git clean`
- `rsync`
- rebuild / service restart
- file edit

関連:

- SSH stdio profile: [codex-ssh-stdio-mcp-profile.md](codex-ssh-stdio-mcp-profile.md)
- 実機実験 workflow: [real-device-experiment-workflow.md](real-device-experiment-workflow.md)
- 実機反映前 plan: [`get_reflection_apply_plan`](#get_reflection_apply_plan)

### `get_development_snapshot`

作業開始時の総合 snapshot です。以下を 1 回でまとめます。

- [`get_repo_state`](#get_repo_state)
- [`get_repo_dirty_summary`](#get_repo_dirty_summary)
- [`get_checkout_hygiene_summary`](#get_checkout_hygiene_summary)
- [`check_runtime_access`](#check_runtime_access)
- [`run_preflight`](#run_preflight)
- [`get_keymap_summary`](#get_keymap_summary)
- [`get_script_summary`](#get_script_summary)
- [`get_codex_mcp_status`](#get_codex_mcp_status)
- [`get_real_device_access_summary`](#get_real_device_access_summary) (`include_real_device_access` 有効時)
- [`get_sync_safety_plan`](#get_sync_safety_plan)
- [`get_selective_sync_plan`](#get_selective_sync_plan)
- [`get_systemd_unit_summary`](#get_systemd_unit_summary)
- [`get_codex_task_mailbox_summary`](#get_codex_task_mailbox_summary)
- [`get_http_status_summary`](#get_http_status_summary)
- [`get_output_readiness_summary`](#get_output_readiness_summary)
- [`get_runtime_issue_summary`](#get_runtime_issue_summary)
- [`get_runtime_state_summary`](#get_runtime_state_summary)

実機に入っている source が古い、dirty files が多い、runtime keymap が読めない、service は動いているが
HID route の期待と違う、といった「作業前に見落としやすい差」を一つの返り値で確認するための入口です。
実機作業を始める時は `--include-real-device-access` を付けると、SSH target の候補選定も同じ
snapshot に含められます。既定では network probe を行わず、local snapshot を軽く保ちます。

関連:


### `get_real_device_work_start_summary`

実機作業を始める時の read-only start checklist です。
[`get_development_snapshot`](#get_development_snapshot) を材料に、次の順で確認項目を返します。

- target selection
- local checkout
- runtime access
- output readiness
- next action

`blockers` には、実機 SSH 到達性、dirty checkout、runtime keymap 権限、output readiness issue を集約します。
runtime / output の blocker には、unreadable path や issue sample、次に見る read-only command 例も含めます。
状態変更しないこと:

- `git fetch` / `git pull`
- `git stash` / `git reset` / `git clean`
- `rsync`
- rebuild / service restart
- key send
- file edit

### `get_codex_mcp_status`

local Codex CLI からこの MCP server を使える状態かを、secret を返さずに要約します。

主に見るもの:

- `codex` CLI が PATH 上にあるか
- `~/.codex/config.toml` または指定 `config_path` が読めるか
- 対象 `repo_root` が Codex trusted project か
- `mcp_servers.<server_name>` が設定済みか
- `keyboard` server の command / args がこの checkout の `dev/mcp/keyboard/server.py --stdio` を指すか

返さないもの:

- `env` の値
- bearer token env var 名
- HTTP header 値

例:

```bash
python3 dev/mcp/keyboard/server.py --tool get_codex_mcp_status
python3 dev/mcp/keyboard/server.py --tool get_codex_mcp_status --server-name keyboard
```

関連:

- Codex 登録手順: [#起動と確認](#起動と確認)
- 認証方針: [#認証と公開境界](#認証と公開境界)

### `get_sync_safety_plan`

実機反映前に、native binary を Raspberry Pi へ上書きせず、x86 hostで作った同一versionの
core/profile split packageを使うためのread-only planを返します。
`rsync`、cross-build、package install、service restartは実行しません。
checkout全体のrsync例はlegacy/recovery用としてだけ返し、Raspberry Pi上のproject buildは案内しません。

主に返すもの:

- `daemon/matrixd/matrixd` と `bin/hidloom-*` の `file` 結果
- x86-64 artifact の architecture warning
- `rsync --exclude` 一覧
- x86 cross-build hostで実行するpackage command
- core/profile同時install、profile apply、active check command

例:

```bash
python3 dev/mcp/keyboard/server.py --tool get_sync_safety_plan --target keyboard.example
```

関連:

- TOP の同期注意: [../../README.md#実機への同期注意](../../README.md#実機への同期注意)

### `get_selective_sync_plan`

[`get_repo_dirty_summary`](#get_repo_dirty_summary) のカテゴリを使い、実機へ targeted sync するための
read-only plan を返します。既定カテゴリは `mcp` と `docs` で、MCP server を実機に載せて試す通常ループに
合わせています。これはread-only診断の開発用反映だけに限定し、runtime/native更新のsplit package経路を
置き換えません。

主に返すもの:

- selected category と selected path
- `rsync -az --relative ...` の例
- 実機側で実行する smoke command
- selected category 外にある runtime-affecting dirty files
- native artifact の block 情報

実行しないもの:

- `rsync`
- test / smoke command
- rebuild / service restart
- git 操作

例:

```bash
python3 dev/mcp/keyboard/server.py --tool get_selective_sync_plan --category mcp --category docs
```

関連:

- dirty 分類: [`get_repo_dirty_summary`](#get_repo_dirty_summary)
- 広域同期前の安全確認: [`get_sync_safety_plan`](#get_sync_safety_plan)

### `get_reflection_apply_plan`

[`get_selective_sync_plan`](#get_selective_sync_plan) と
[`get_update_readiness_summary`](#get_update_readiness_summary) を合わせ、手動で実機反映する直前の
operator checklist を返します。更新系 API ではなく、`rsync` / `ssh` / test / restart / git は実行しません。

主に返すもの:

- selected category / path
- 情報用 confirmation token と `REFLECT ...` phrase
- 手動で実行する `rsync` / `ssh` command 文字列
- review / reflect / smoke / document / commit_push の phase
- blocker と stop condition
- update readiness と selective sync の source summary

selected path に directory が含まれる場合は、広すぎる `rsync` になりやすいため
`selected_directory` blocker として返します。

実行しないもの:

- `rsync`
- `ssh`
- test / smoke command
- rebuild / service restart
- git 操作
- confirmation の受付や apply

例:

```bash
python3 dev/mcp/keyboard/server.py --tool get_reflection_apply_plan --category mcp --category docs --include-http-status
```

関連:

- targeted rsync plan: [`get_selective_sync_plan`](#get_selective_sync_plan)
- 更新系 API 前提確認: [`get_update_readiness_summary`](#get_update_readiness_summary)

### `get_systemd_unit_summary`

allowlist された keyboard service について、systemd runtime state と repository 内 unit file の要約を返します。
`systemctl show` と unit file の両方を見るため、実機で drop-in が効いているか、repo の unit と runtime unit が
どの程度対応しているかを短く確認できます。

主に返すもの:

- `LoadState` / `ActiveState` / `SubState`
- runtime の `FragmentPath` / `DropInPaths`
- `User` / `Group` / `WorkingDirectory`
- `ExecStart` が存在するか
- environment 名の一覧
- allowlist 済みの非 secret operational flag の値
- repo 内 unit file の path、`Environment=` 名、`ExecStart=` / `ExecStartPre=` の要約

返さないもの:

- allowlist 外の environment 値
- unit file 全文
- journal 本文

`hid_broker.broker_ready=false` のように、service 自体は active だが HTTP health が注意を出している時に使います。
例えばnative ownerなのに、`hidloom-hidd`、`hidloom-outputd`、`hidloom-logicd-core`の
socket environmentが欠けている場合、broker readinessがfalseの理由を説明できます。

例:

```bash
python3 dev/mcp/keyboard/server.py --tool get_systemd_unit_summary --unit-service hidloom-logicd-core
python3 dev/mcp/keyboard/server.py --tool get_systemd_unit_summary
```

関連:

- service preflight: [`run_preflight`](#run_preflight)
- HTTP health: [`get_http_status_summary`](#get_http_status_summary)
- unit files: [../../system/systemd/hidloom-hidd.service](../../system/systemd/hidloom-hidd.service), [../../system/systemd/hidloom-outputd.service](../../system/systemd/hidloom-outputd.service), [../../system/systemd/hidloom-logicd-core.service](../../system/systemd/hidloom-logicd-core.service), [../../system/systemd/logicd-companion.service](../../system/systemd/logicd-companion.service)

### `get_codex_task_mailbox_summary`

desktop Codex と keyboard-side Codex worker の連携 mailbox を read-only で要約します。
manual operation のままでも、未処理 task が残っているか、最新 result が JSON / Markdown のペアになっているかを
MCP client から確認できます。

主に返すもの:

- `codex_tasks/inbox` / `running` / `done` / `failed` の file count
- `.sample` を除外した active count
- 最新ファイルの path / size / mtime
- task/result JSON の `id` / `status` / `mode` / `summary` / check count
- `done` / `failed` の `.result.json` と `.result.md` のペア有無

返さないもの:

- result Markdown 本文
- command stdout / stderr の本文
- task に含まれる任意の長い body

例:

```bash
python3 dev/mcp/keyboard/server.py --tool get_codex_task_mailbox_summary --max-items 3
```

関連:

- 開発開始 snapshot: [`get_development_snapshot`](#get_development_snapshot)

### `get_http_status_summary`

実機上の local HTTPS `/api/status` を読み、HTTP UI / API 側の health を短く返します。
既定では `https://127.0.0.1/api/status` に `admin:<hostname>` で接続し、credential は返しません。

主に返すもの:

- daemon process の active summary
- HID gadget connected / UDC state
- output mode / target
- `hid_broker` readiness
- text-send runner / blocking reasons
- Bluetooth paired / connected count
- Wi-Fi power / connected state
- SPID socket state

例:

```bash
python3 dev/mcp/keyboard/server.py --tool get_http_status_summary
python3 dev/mcp/keyboard/server.py --tool get_development_snapshot --include-http-status
```

関連:

- HTTP UI: [../../daemon/http/README.md](../../daemon/http/README.md)

### `get_output_readiness_summary`

`run_preflight` と `get_http_status_summary` を合わせ、USB/output 経路の「使える状態」と注意点を
1 つの返り値にまとめます。

`core_preflight_ok` と `usb_keyboard_routes_ok` が true なら、通常の keyboard route 確認には進めます。
一方で `hid_broker.broker_ready=false` や text-send safety gate は `issues` に info / warning として残し、
作業範囲に応じて見る形です。

`spid` は SPI mouse sensor 用の optional daemon です。センサ未配線の実機では
`processes.optional_inactive=["spid"]` として残しますが、output readiness の issue にはしません。

例:

```bash
python3 dev/mcp/keyboard/server.py --tool get_output_readiness_summary --include-http-status
```

関連:

- preflight: [`run_preflight`](#run_preflight)
- HTTP health: [`get_http_status_summary`](#get_http_status_summary)

### `get_runtime_issue_summary`

[`get_output_readiness_summary`](#get_output_readiness_summary) の issue を、原因候補と次の read-only check に
変換します。systemd 情報も見る場合は、`hid_broker.broker_ready=false` が `logicd` 側の
`LOGICD_USBD_HID_REPORT_BROKER` 未設定によるものか、`hidd` / legacy `usbd` 側の socket owner 設定によるものかを
切り分けます。

主に返すもの:

- issue area / severity / summary
- probable cause
- blocking reasons
- 次に見る read-only command

実行しないもの:

- service restart
- unit file 編集
- key sending
- runtime state 変更

例:

```bash
python3 dev/mcp/keyboard/server.py --tool get_runtime_issue_summary --include-http-status
```

関連:

- readiness 元情報: [`get_output_readiness_summary`](#get_output_readiness_summary)
- systemd unit: [`get_systemd_unit_summary`](#get_systemd_unit_summary)

### `get_interface_snapshot`

HTTP UI/API、Vial service、BLE の状態を、作業開始時に 1 回で見るための snapshot です。
[`run_preflight`](#run_preflight)、[`get_http_status_summary`](#get_http_status_summary)、
[`get_runtime_state_summary`](#get_runtime_state_summary) を組み合わせ、credential、Bluetooth address、
full runtime JSON は返しません。

返すもの:

- HTTP `/api/status` の取得可否、process / HID / output / Wi-Fi summary
- `viald` / `httpd` / `btd` の service active state
- Vial の service / HID readiness
- Bluetooth powered / pairable / discoverable / paired count / connected count
- runtime Bluetooth host metadata の最小 summary

実行しないもの:

- Bluetooth pair / forget
- Vial command probe
- service restart
- HTTP 設定変更
- runtime JSON 書き換え

例:

```bash
python3 dev/mcp/keyboard/server.py --tool get_interface_snapshot --include-http-status
```

関連:

- HTTP status: [`get_http_status_summary`](#get_http_status_summary)
- runtime state: [`get_runtime_state_summary`](#get_runtime_state_summary)

### `get_update_readiness_summary`

将来の更新系 MCP API を作る前に、どの領域にどんな前提条件が残っているかを read-only でまとめます。
更新は行わず、`plan_*` / `dry-run` / `apply_*` の設計材料だけを返します。

対象領域:

- keymap update
- service restart
- selective sync
- output mode change
- Bluetooth host management
- key / text send

返すもの:

- 各領域の readiness と status
- apply 前に必要な validation / rollback / confirmation 条件
- runtime keymap access、dirty checkout、sync safety、HTTP status の要約
- update-capable tool を read-only server と分ける recommendation

実行しないもの:

- keymap write
- service restart
- rsync
- output mode 変更
- Bluetooth pair / forget
- key send / text send
- git 操作

例:

```bash
python3 dev/mcp/keyboard/server.py --tool get_update_readiness_summary --include-http-status
```

関連:

- write 境界: [../policy/http-mcp-transport-design.md](../policy/http-mcp-transport-design.md)
- runtime access: [`check_runtime_access`](#check_runtime_access)
- selective sync: [`get_selective_sync_plan`](#get_selective_sync_plan)

### `get_runtime_state_summary`

`/mnt/p3` の runtime JSON を読み、実機固有の現在状態を短く返します。対象は keymap、LED state、
Bluetooth host metadata、board profile です。

返すもの:

- file size / mode / owner / mtime / short digest
- keymap layer count と default との差分 sample
- LED mode / speed / HSV
- Bluetooth host metadata の件数と最小 metadata
- board version / device name / prototype

返さないもの:

- full keymap JSON
- Bluetooth address
- script body

例:

```bash
python3 dev/mcp/keyboard/server.py --tool get_runtime_state_summary --include-keymap-diff
```

関連:

- runtime access: [`check_runtime_access`](#check_runtime_access)
- keymap diff: [`get_keymap_summary`](#get_keymap_summary)

## 実機での既知メモ

`<keyboard-host>` では、read-only smoke で service、socket、`/dev/hidg0-2` が揃っていることを確認済みです。
`/mnt/p3/keymap.json` は read-only smoke 後に通常 user から読める状態へ調整済みです。

`get_systemd_unit_summary` の実機 smoke では、`hidloom-hidd` owner と
現在の active owner では `hidloom-logicd-core.service` と `hidloom-hidd.service`、
および `hid_broker.broker_ready` を確認します。legacy `LOGICD_USBD_HID_REPORT_BROKER`
は Python `logicd` / `usbd` rollback 経路の診断項目です。
HTTP status の `hid_broker.broker_ready` は owner、logicd opt-in、broker socket を合わせて判定します。

runtime keymap の permission error が再発した場合でも、MCP tool は「読めないこと」を正しく返し、
空 keymap として扱いません。
必要なら MCP server の実行 user / group、または runtime keymap の読み取り権限を別途設計します。

## 今後の拡張候補

現行の read-only MCP server として大きな未充足はありません。
次の項目は実装漏れではなく、必要になった時だけ再開する watch item です。

- Windows / Linux / macOS host-side smoke。
- USB broker route を変更する時の host-side smoke と read-only 切り分け。
- 実機 SSH host key / alias 整備。現状は desktop-driven SSH の numeric IP path を標準にします。
- 同じ手動観測が繰り返された時だけ追加する read-only wrapper。
- HTTP transport を採用する場合の bearer token / OAuth 設計:
  [../policy/http-mcp-transport-design.md](../policy/http-mcp-transport-design.md)。

状態変更を伴う操作は、MCP tool へ入れる前に private workspace reference *(omitted from public export)* か
private workspace reference *(omitted from public export)* で境界を明確にします。
