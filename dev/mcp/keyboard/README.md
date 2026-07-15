# Keyboard MCP server

This directory contains the first read-only MCP server slice for HIDloom
keyboard diagnostics.

The server intentionally starts as a diagnostic surface, not a keyboard control
surface. It reads local repository configuration and explains the intended USB
split and keycode routing.

Full feature list and per-tool details:
[../../../docs/ops/keyboard-mcp-server.md](../../../docs/ops/keyboard-mcp-server.md)

## Tools

| tool | Purpose | Writes device state |
| --- | --- | --- |
| `get_status` | Summarize config, keymap, and server metadata | no |
| `get_usb_split_status` | Explain the configured keyboard / mouse / consumer / US sub endpoint shape | no |
| `explain_route_for_keycode` | Explain whether a keycode routes as keyboard, mouse, consumer, or split keyboard | no |
| `run_preflight` | Collect service, HID path, socket, USB split, and representative route diagnostics | no |
| `get_keymap_summary` | Summarize current keymap layers, system-default diffs, and attention actions | no |
| `collect_journal_excerpt` | Collect a bounded journal excerpt for an allowed keyboard service | no |
| `check_runtime_access` | Report current MCP process identity and runtime path access | no |
| `get_script_summary` | Summarize `KC_SH*` script labels, source paths, readability, and safety metadata | no |
| `preview_hid_report` | Preview keyboard or consumer HID report bytes for a keycode | no |
| `inspect_key_position` | Inspect current/default actions for one matrix position across layers | no |
| `get_repo_state` | Summarize branch, commit, upstream, and dirty files for a checkout | no |
| `get_repo_dirty_summary` | Classify checkout dirty files by area and attention level | no |
| `get_checkout_hygiene_summary` | Summarize dirty checkout hygiene issues before pull or manual reflection | no |
| `get_checkout_drift_summary` | Attribute dirty checkout drift to likely reflection or local-runtime buckets | no |
| `get_pull_readiness_summary` | Summarize whether a checkout is ready for a manual git pull | no |
| `get_checkout_cleanup_candidates` | Suggest read-only preserve, cleanup-candidate, and review buckets | no |
| `get_checkout_preserve_diff_summary` | Summarize preserve-candidate diffs without diff hunks or file bodies | no |
| `get_checkout_backup_plan_summary` | Return a read-only backup plan for preserve candidates | no |
| `get_manual_cleanup_verification_plan` | Return a read-only final gate before manual cleanup or pull | no |
| `get_cleanup_review_order_summary` | Return a read-only prioritized review order for cleanup decisions | no |
| `get_reflection_cleanup_alignment_summary` | Compare cleanup candidates with a local git ref without fetching | no |
| `get_temporary_change_restore_plan_summary` | List temporary stashes and manual restore commands without applying them | no |
| `get_real_device_experiment_workflow_summary` | Gate the temporary experiment workflow before revert and clean pull | no |
| `get_real_device_access_summary` | Check candidate real-device SSH access and checkout state | no |
| `get_development_snapshot` | Combine repo, runtime access, preflight, keymap, and script summaries | no |
| `get_real_device_work_start_summary` | Return ordered read-only start checks for real-device work | no |
| `get_codex_mcp_status` | Summarize Codex CLI MCP registration and trust state without returning secrets | no |
| `get_sync_safety_plan` | Return package-first update guidance, rsync excludes, and native artifact warnings | no |
| `get_selective_sync_plan` | Return a targeted rsync plan for selected dirty-file categories | no |
| `get_reflection_apply_plan` | Return a read-only operator checklist before manual real-device reflection | no |
| `get_systemd_unit_summary` | Summarize allowlisted systemd unit state, drop-ins, and safe environment flags | no |
| `get_codex_task_mailbox_summary` | Summarize Codex task mailbox counts, latest files, and result pairs | no |
| `get_http_status_summary` | Summarize local HTTP `/api/status` health without returning credentials | no |
| `get_output_readiness_summary` | Combine preflight and HTTP health into output-route readiness and issues | no |
| `get_interface_snapshot` | Summarize HTTP, Vial, and BLE readiness without pairing or writing settings | no |
| `get_update_readiness_summary` | Summarize prerequisites before any future update-capable MCP tools | no |
| `get_runtime_issue_summary` | Summarize runtime readiness issues with likely causes and next checks | no |
| `get_runtime_state_summary` | Summarize `/mnt/p3` runtime JSON state without returning full contents | no |

## Local checks

Run from the repository root:

```powershell
python script\test_mcp_keyboard_server.py
python -m py_compile dev\mcp\keyboard\server.py script\test_mcp_keyboard_server.py
```

Manual one-shot examples:

```powershell
python dev\mcp\keyboard\server.py --tool get_status
python dev\mcp\keyboard\server.py --tool get_usb_split_status
python dev\mcp\keyboard\server.py --tool explain_route_for_keycode --keycode KC_HENKAN
python dev\mcp\keyboard\server.py --tool run_preflight --no-systemctl
python dev\mcp\keyboard\server.py --tool get_keymap_summary --max-changes 20
python dev\mcp\keyboard\server.py --tool collect_journal_excerpt --service hidloom-logicd-core --lines 80
python dev\mcp\keyboard\server.py --tool check_runtime_access
python dev\mcp\keyboard\server.py --tool get_script_summary
python dev\mcp\keyboard\server.py --tool preview_hid_report --keycode KC_HENKAN
python dev\mcp\keyboard\server.py --tool inspect_key_position --matrix 7,0
python dev\mcp\keyboard\server.py --tool get_repo_state --repo-root /srv/hidloom
python dev\mcp\keyboard\server.py --tool get_repo_dirty_summary --repo-root /srv/hidloom
python dev\mcp\keyboard\server.py --tool get_checkout_hygiene_summary --repo-root /srv/hidloom --max-files 80
python dev\mcp\keyboard\server.py --tool get_checkout_drift_summary --repo-root /srv/hidloom --max-files 80
python dev\mcp\keyboard\server.py --tool get_pull_readiness_summary --repo-root /srv/hidloom --max-files 80
python dev\mcp\keyboard\server.py --tool get_checkout_cleanup_candidates --repo-root /srv/hidloom --max-files 80
python dev\mcp\keyboard\server.py --tool get_checkout_preserve_diff_summary --repo-root /srv/hidloom --max-files 80
python dev\mcp\keyboard\server.py --tool get_checkout_backup_plan_summary --repo-root /srv/hidloom --max-files 80
python dev\mcp\keyboard\server.py --tool get_manual_cleanup_verification_plan --repo-root /srv/hidloom --max-files 80
python dev\mcp\keyboard\server.py --tool get_cleanup_review_order_summary --repo-root /srv/hidloom --max-files 80
python dev\mcp\keyboard\server.py --tool get_reflection_cleanup_alignment_summary --repo-root /srv/hidloom --max-files 80 --reference origin/main
python dev\mcp\keyboard\server.py --tool get_temporary_change_restore_plan_summary --repo-root /srv/hidloom --max-stashes 8
python dev\mcp\keyboard\server.py --tool get_real_device_experiment_workflow_summary --repo-root /srv/hidloom --max-files 80
python dev\mcp\keyboard\server.py --tool get_real_device_access_summary --access-target keyboard.example
python dev\mcp\keyboard\server.py --tool get_development_snapshot --repo-root /srv/hidloom
python dev\mcp\keyboard\server.py --tool get_development_snapshot --include-real-device-access --repo-root /srv/hidloom
python dev\mcp\keyboard\server.py --tool get_real_device_work_start_summary --include-http-status --max-files 20
python dev\mcp\keyboard\server.py --tool get_codex_mcp_status
python dev\mcp\keyboard\server.py --tool get_sync_safety_plan --target keyboard.example
python dev\mcp\keyboard\server.py --tool get_selective_sync_plan --target keyboard.example --category mcp --category docs
python dev\mcp\keyboard\server.py --tool get_reflection_apply_plan --target keyboard.example --category mcp --category docs --include-http-status
python dev\mcp\keyboard\server.py --tool get_systemd_unit_summary --unit-service hidloom-logicd-core
python dev\mcp\keyboard\server.py --tool get_codex_task_mailbox_summary --max-items 3
python dev\mcp\keyboard\server.py --tool get_http_status_summary
python dev\mcp\keyboard\server.py --tool get_output_readiness_summary --include-http-status
python dev\mcp\keyboard\server.py --tool get_interface_snapshot --include-http-status
python dev\mcp\keyboard\server.py --tool get_update_readiness_summary --include-http-status
python dev\mcp\keyboard\server.py --tool get_runtime_issue_summary --include-http-status
python dev\mcp\keyboard\server.py --tool get_runtime_state_summary --include-keymap-diff
```

## MCP stdio launch

Use this command from an MCP client that supports stdio servers:

```text
python dev/mcp/keyboard/server.py --stdio
```

Local Codex registration for this checkout:

```text
codex mcp add keyboard -- python3 /srv/hidloom/dev/mcp/keyboard/server.py --stdio
codex mcp get keyboard
```

This stdio server does not use MCP-level bearer token or OAuth authentication.
Access is bounded by the OS user that can launch the process, Codex trusted
project settings, and normal filesystem permissions.

The server implements the minimum JSON-RPC methods used by MCP clients:

- `initialize`
- `tools/list`
- `tools/call`
- `notifications/initialized`

## Keymap summary

`get_keymap_summary` compares the active keymap with the repository system
default. On a keyboard-side host it prefers `/mnt/p3/keymap.json` when present;
otherwise it falls back to `config/default/keymap.json`. It reports per-layer assignment
counts, sample changes from default, and attention actions such as scripts,
shutdown, Wi-Fi power, Bluetooth forget, and text-send actions.

If the MCP process cannot read `/mnt/p3/keymap.json`, the tool returns a
structured read error and skips diff calculation instead of treating the
unreadable keymap as empty.

Use `check_runtime_access` before installing the MCP server as a service. It
reports the current user/group set and read/write/execute access for runtime
paths such as `/mnt/p3/keymap.json`. If the runtime keymap exists but is not
readable, it returns non-executed permission-fix recommendations.

## Journal excerpts

`collect_journal_excerpt` is bounded to known keyboard services and caps output
at 200 lines. It is intended for follow-up after `run_preflight` reports an
inactive service, not as a broad log browser.

## Script summary

`get_script_summary` reports `KC_SH*` labels, runtime-vs-fallback source paths,
readability, and safety metadata without returning script contents. It uses the
same `script_metadata.py` danger parser as the HTTP script editor.

## HID report preview

`preview_hid_report` returns canonical HID payload bytes and multi-report-ID
bytes for keyboard and consumer keycodes without opening any HID device or
broker socket. Use it to cross-check routing and bytes before a manual smoke.
`KC_ZKHK` is shown as the internal marker payload used by `logicd`; the route
adapter clears that marker before writing the JIS main report.

## Matrix position inspection

`inspect_key_position` reports the current and system-default action for a
single matrix coordinate across all layers. It can include route and HID report
previews for supported actions, which is useful when tracing one physical key
from keymap to output bytes.

## Repository state

`get_repo_state` runs read-only git commands to report branch, commit, upstream,
last commit, and a bounded list of dirty files. Use it before asking a
keyboard-side checkout to pull or before interpreting runtime observations
against local source changes.

`get_repo_dirty_summary` classifies dirty files into areas such as `mcp`,
`docs`, `config`, `logicd`, `hidd`, `usbd`, `usb_gadget`, `native_artifact`, and
`untracked`. It highlights runtime-affecting changes and untracked files so a
desktop Codex can decide whether targeted sync is enough or a broader pull would
need human review first.

`get_checkout_hygiene_summary` converts dirty checkout entries into
operator-facing buckets such as `untracked_directory`, `runtime_affecting`,
`native_artifact`, and `delete_or_missing`. Use it before
`get_reflection_apply_plan` when a real-device checkout has broad untracked
directories or many files that need a narrower manual sync decision.

`get_checkout_drift_summary` builds on the hygiene summary and separates likely
targeted-rsync artifacts from local runtime-affecting changes. It is a heuristic
read-only view for deciding whether to pull, preserve local edits, or narrow the
next reflection plan.

`get_pull_readiness_summary` combines local upstream ahead/behind information
with checkout drift blockers. It does not fetch or pull; it uses existing local
upstream refs to say whether a manual pull is blocked, unnecessary, or ready.

`get_checkout_cleanup_candidates` converts drift groups into `preserve`,
`cleanup_candidates`, and `review` buckets. It is still read-only and does not
return destructive commands; use the listed checks before deciding what to keep
or clean manually.

`get_checkout_preserve_diff_summary` summarizes only preserve-candidate diff
metadata: tracked file name-status and numstat, plus untracked file size. It
does not return diff hunks, file bodies, or untracked file contents.

`get_checkout_backup_plan_summary` turns those preserve candidates into a
read-only backup checklist with file list, estimated size, and manual command
examples. It does not create directories, write archives, or run git commands.

`get_manual_cleanup_verification_plan` is the final read-only gate before a
human runs cleanup or pull. It combines cleanup buckets, backup status, and pull
readiness, then reports blockers and verification steps. It does not create
backups, clean, reset, remove, fetch, pull, rsync, restart, or edit files.

`get_cleanup_review_order_summary` turns the cleanup buckets into a practical
review order: preserve items first, then cleanup directories, cleanup files, and
ordinary review items. It only returns read-only inspection command examples.

`get_reflection_cleanup_alignment_summary` checks cleanup candidates against a
selected local git reference such as `origin/main`. It does not fetch; it only
uses refs already present in the checkout to separate candidates that exist in
the reference from candidates that need more investigation.

`get_temporary_change_restore_plan_summary` lists temporary stashes and returns
manual inspection / restore commands. It is useful after updating a device by
stashing local experiments first. It does not apply, branch, drop, clean, reset,
pull, fetch, rsync, restart, or edit files.

`get_real_device_experiment_workflow_summary` gates the standard experiment
workflow. It reports whether temporary checkout changes need to be recorded and
reverted before a clean pull, and returns manual command examples without running
stash, reset, clean, pull, fetch, rsync, restart, or edits.

`get_real_device_access_summary` checks candidate SSH targets before real-device
work. It resolves host names, optionally runs bounded read-only SSH probes, and
reports the remote checkout branch/commit/dirty status. It does not pull, fetch,
stash, reset, clean, rsync, rebuild, restart, or edit files. Failed SSH probes
are classified, so host-key, authentication, timeout, and name-resolution
problems are easier to separate. The result also includes `next_read_only_checks`
with inspection command examples such as `ssh-keygen -F` or `getent hosts`.

## Development Snapshot

`get_development_snapshot` is the compact "start of work" view. It combines
repo state, runtime path access, service/HID/socket preflight, keymap summary,
script summary, and Codex MCP registration status without returning full logs or
script contents. Add `--include-real-device-access` when a pass needs to choose
or verify the real-device SSH target; the default keeps network probes out of
ordinary local snapshots.

`get_real_device_work_start_summary` uses the development snapshot to return an
ordered start checklist for real-device work: target selection, local checkout,
runtime access, output readiness, and the next action. It stays read-only and
does not run pull, rsync, rebuild, restart, key send, or file edits.

## Codex MCP Status

`get_codex_mcp_status` reads local Codex config and reports whether the Codex
CLI is present, this checkout is trusted, and the `keyboard` MCP server points
at this checkout's stdio command. It redacts environment values, bearer token
environment variable names, and HTTP header values.

## Sync Safety Plan

`get_sync_safety_plan` returns a read-only package-first real-device update plan.
It lists rsync excludes for native binaries such as `daemon/matrixd/matrixd` and
`bin/hidloom-*`, reports local artifact architecture with `file` when available,
and provides x86 cross-build plus same-version core/profile install commands.
Broad checkout rsync is retained only as an explicitly labeled legacy/recovery example;
the plan never recommends building project binaries on the Raspberry Pi.

`get_selective_sync_plan` uses `get_repo_dirty_summary` categories to build a
targeted `rsync -az --relative` command for selected categories. The default is
`mcp` and `docs`, matching a development-only read-only MCP iteration loop.
It is not a runtime deployment path and never replaces the split package update.
Runtime-affecting dirty files outside the selection are reported separately so
broad sync does not look safer than it is.

`get_reflection_apply_plan` combines the selective sync plan and update readiness
summary into a read-only operator checklist. It returns selected paths, stop
conditions, an informational confirmation phrase, manual `rsync` / `ssh` command
strings, and post-reflection smoke commands. It does not run any command or
accept confirmation. It is limited to development-only MCP/docs reflection; native
or runtime updates use split packages. If selected paths include a directory, the
plan reports a blocker so the operator can narrow the file list before manual `rsync`.

## Systemd Unit Summary

`get_systemd_unit_summary` reports allowlisted systemd unit state, fragment
path, drop-in paths, user/group, ExecStart presence, and environment names. It
returns values only for a small allowlist of non-secret operational flags, and
redacts any other environment values. Use it when HTTP health reports a mismatch
such as `hid_broker.broker_ready=false` and you need to see whether service unit
environment or drop-ins explain it.

## Codex Task Mailbox Summary

`get_codex_task_mailbox_summary` reports the mailbox directories under
`codex_tasks`: file counts, active counts excluding `.sample` files, recent task
or result JSON metadata, and result JSON/Markdown pair presence. It summarizes
JSON fields such as task id, status, mode, summary, and check counts, but does
not return Markdown bodies or command stdout/stderr from result files.

## HTTP Status Summary

`get_http_status_summary` fetches local HTTPS `/api/status` and returns a
bounded health summary for processes, HID connection, output mode, HID broker
readiness, text-send readiness, Bluetooth, Wi-Fi, and SPID sockets. It uses
`admin:<hostname>` by default and never returns credentials.

## Output Readiness Summary

`get_output_readiness_summary` combines `run_preflight` and
`get_http_status_summary` into a compact output-route readiness view. It keeps
core USB keyboard readiness separate from informational items such as
`hid_broker.broker_ready=false`, text-send safety gates, and optional SPID inactivity.

`get_runtime_issue_summary` turns readiness issues into likely causes and next
read-only checks. For example, it can connect `hid_broker.broker_ready=false` to a
missing `LOGICD_USBD_HID_REPORT_BROKER` unit environment flag when systemd
metadata is available.

## Interface Snapshot

`get_interface_snapshot` summarizes HTTP UI/API, Vial service readiness, and BLE
status in one read-only payload. It combines service state, HTTP `/api/status`,
and runtime Bluetooth host metadata without pairing, forgetting, calling Vial
commands, restarting services, or writing settings.

## Update Readiness Summary

`get_update_readiness_summary` is a read-only map for future update-capable MCP
design. It summarizes prerequisites for keymap updates, service restarts,
selective sync, output mode changes, Bluetooth host management, and key/text
send without performing any of those operations. Use it before designing
`plan_*` / `apply_*` tools.

## Runtime State Summary

`get_runtime_state_summary` summarizes runtime JSON files under `/mnt/p3`:
keymap metadata/diff, LED mode, Bluetooth host metadata count, and board
profile. It returns file sizes, modes, mtimes, and short digests, but not full
runtime JSON contents, Bluetooth addresses, or script bodies.

## Real-device smoke

When a keyboard target is available, keep this read-only:

```sh
python3 dev/mcp/keyboard/server.py --tool get_real_device_access_summary --access-target keyboard.example
systemctl is-active hidloom-usb-gadget viald hidloom-hidd hidloom-uidd hidloom-outputd hidloom-logicd-core logicd-companion matrixd ledd i2cd httpd btd
ls -l /dev/hidg0 /dev/hidg1 /dev/hidg2
ls -l /tmp/usbd_hid_reports.sock /tmp/matrix_events.sock /tmp/ledd_events.sock
python3 dev/mcp/keyboard/server.py --tool get_usb_split_status
python3 dev/mcp/keyboard/server.py --tool explain_route_for_keycode --keycode KC_HENKAN
```

Expected configured intent for the current split:

- main keyboard path: `/dev/hidg0`;
- US sub split path: `/dev/hidg2`;
- mouse and consumer reports stay on the configured broker / endpoint route;
- `jis_special_us_default` routes ordinary keyboard usages to the US sub
  keyboard path, and JIS-specific usages such as `KC_ZKHK`, `KC_RO`,
  `KC_KANA`, `KC_JYEN`, `KC_HENKAN`, and `KC_MUHENKAN` to the JIS main path.
- `KC_LANG1` / `KC_LANG2` remain on the default US sub route for ImeOn/ImeOff
  under `jis_special_us_default`.

Host enumeration still needs real-device confirmation. This MCP server reports
repository configuration and known routing intent; it does not prove the host
accepted the descriptor.
