# logicd-core-rs M0 Implementation Spec

作成日: 2026-06-19

この文書は、起動直後の物理キー入力を Python `logicd` より早く usable にするための
Rust daemon `logicd-core-rs` M0 実装仕様である。
上位構成と移行方針は [../../native-fast-input-core-design.md](../../native-fast-input-core-design.md)、
HID transport 側の詳細は [../hidd/m0-implementation-spec.md](../hidd/m0-implementation-spec.md) を参照する。

M0 は Python `logicd` の全移植ではない。
matrix event から basic keyboard HID report までの最短 path を native 化し、
複雑な control plane は Python sidecar に残す。

## 結論

`logicd-core-rs` M0 は「常用入力の最低限」を担当する。
最初から macro、Vial keymap write、touch flick、Morse、text send、SPID、analog stick、
Bluetooth output、LED feedback を取り込まない。

M0 の成功条件は、次の 3 点に限定する。

- `matrixd` が送る既存 4 byte packet を受けられる。
- runtime/default keymap から basic `KC_*` / modifier / layer fallback を解決できる。
- 8 byte keyboard report を既存 broker frame で `hidd-rs` または Python `usbd` へ送れる。

## M0 の責務

M0 で持つもの:

- `/tmp/matrix_events.sock` 互換の `AF_UNIX` / `SOCK_STREAM` server。
- `matrixd` 4 byte packet parse。
- matrix bounds validation。
- pressed matrix state。
- keymap snapshot load。
- basic layer lookup。
- basic keyboard / modifier HID state。
- broker frame encode and send to `/tmp/usbd_hid_reports.sock`。
- all-keys-up emergency release。
- read-only status。
- minimal control socket: status / reload / release_all / mode。

M0 で持たないもの:

- HTTP API。
- Vial protocol。
- keymap write / save。
- macro engine。
- tap dance / combo / oneshot / layer lock の完全互換。
- Morse / touch flick / sessiond PTY / text send。
- SPID / analog / rotary encoder high-level actions。
- LED feedback owner。
- Bluetooth output switching。

## Existing Matrix Protocol

`matrixd` は `SOCK_STREAM` で 4 byte packet を送る。

| byte | meaning |
| ---: | --- |
| 0 | event type: ASCII `P` press or `R` release |
| 1 | row as uppercase hex char |
| 2 | col as uppercase hex char |
| 3 | newline `\n` |

Parser compatibility:

- packet length must be 4。
- byte 0 must be `P` or `R`。
- row / col are parsed as base-16 chars。
- out-of-range event is ignored and counted。
- duplicate press / release is ignored at matrix state layer。

M0 must keep this protocol unchanged so existing `matrixd` can connect without rebuild.

## Keymap Input

M0 reads keymap snapshot from the same priority as Python runtime.

1. runtime keymap: `/mnt/p3/keymap.json`
2. default keymap: `config/default/keymap.json`

M0 should also read keycodes from:

1. runtime keycodes: `/mnt/p3/keycodes.json`
2. default keycodes: `config/default/keycodes.json`

Path should be configurable for tests:

| env | default |
| --- | --- |
| `LOGICD_CORE_KEYMAP_PATH` | `/mnt/p3/keymap.json` |
| `LOGICD_CORE_DEFAULT_KEYMAP_PATH` | repo default keymap path |
| `LOGICD_CORE_KEYCODES_PATH` | `/mnt/p3/keycodes.json` |
| `LOGICD_CORE_DEFAULT_KEYCODES_PATH` | repo default keycodes path |
| `LOGICD_CORE_MATRIX_SOCKET` | `/tmp/matrix_events.sock` |
| `LOGICD_CORE_HID_REPORT_SOCKET` | `/tmp/usbd_hid_reports.sock` |
| `LOGICD_CORE_CTRL_SOCKET` | `/tmp/logicd_core_ctrl.sock` |
| `LOGICD_CORE_STATUS_PATH` | `/run/hidloom/logicd-core-status.json` |
| `LOGICD_CORE_PREVIEW_LOG_PATH` | unset |

JSON parsing policy:

- Missing runtime file falls back to default。
- Invalid runtime JSON falls back to default and reports status warning。
- Invalid default JSON is fatal。
- Unknown top-level fields are ignored。
- Unknown action strings are treated as unsupported no-op and counted。
- Numeric HID code and object-style keycode definitions must match current `keycodes.json` compatibility.

Rust should use `serde` with typed structs plus `#[serde(default)]` for optional fields.
This is safer than ad-hoc C string parsing for complex keymap JSON and gives better error reporting.
2026-06-20 時点の M1/M2 first slice は `tools/hidloom_logicd_core/` にあり、
`config/default/keycodes.json` を source of truth として読む。

## Layer Scope

M0 supports only low-risk layer semantics.

Supported in M0:

| action | behavior |
| --- | --- |
| `KC_*` basic keyboard | press/release updates HID state |
| modifier `KC_LCTRL` etc. | press/release updates modifier bits |
| `KC_TRNS` | fallback to lower layer |
| `KC_NONE` | explicit no-op |
| `MO(n)` | momentary layer while key is held |
| `TG(n)` | toggle layer on press |
| `TO(n)` | clear transient/toggled state and switch to target layer on press |
| `DF(n)` | set default layer on press |
| `OSL(n)` | one-shot layer for the next non-layer key press |

Deferred to M1+:

| action | M0 behavior |
| --- | --- |
| layer lock | unsupported no-op |
| `LT(n,kc)` | initially unsupported unless parser parity is trivial |
| macro / text / custom actions | unsupported no-op |
| mouse actions | unsupported no-op |
| consumer actions | unsupported no-op |

The native core owns deterministic layer actions that do not require timers or ambiguous tap/hold decisions.
Timed or composite actions such as `LT(n,kc)`, `MT(...)`, `TT(n)`, Tap Dance, macros, mouse, text, and scripts remain delegated to the Python companion.

## Action Resolution

For each matrix event:

1. validate row / col。
2. ignore duplicate edge:
   - press when already pressed。
   - release when not pressed。
3. on press, resolve action using current active layers。
4. store `row,col -> resolved action` for release parity。
5. apply layer state change if action is `MO(n)` / `TG(n)` / `TO(n)` / `DF(n)` / `OSL(n)`。
6. update HID state if action is basic key/modifier。
7. send broker keyboard frame if HID state changed。
8. on release, use stored press action, not a newly resolved action。
9. clear stored action and layer state as needed。

Release must use the action captured on press.
Otherwise a momentary layer release can release the wrong key after layer state changes.

## HID State

Keyboard report format:

```text
[modifier, 0x00, key1, key2, key3, key4, key5, key6]
```

Modifier mapping:

| HID keycode | bit |
| ---: | ---: |
| `0xE0` | `0x01` |
| `0xE1` | `0x02` |
| `0xE2` | `0x04` |
| `0xE3` | `0x08` |
| `0xE4` | `0x10` |
| `0xE5` | `0x20` |
| `0xE6` | `0x40` |
| `0xE7` | `0x80` |

Normal keys:

- HID code `1..0xDF` can occupy the six key slots。
- Duplicate key code is not inserted twice。
- More than six simultaneous normal keys are ignored in M0 and counted as rollover drops。
- Mouse codes `>= 0x200` are ignored in M0。
- HID code `0` is no-op。

M0 must match Python `HidState` for supported keycodes.

## Broker Output

M0 sends existing 64 byte broker frames to `LOGICD_CORE_HID_REPORT_SOCKET`.

Keyboard route:

- canonical M0 parity tests force `usb_split_keyboard.enabled=false` and compare `kind=keyboard` payloads.
- runtime config may enable `usb_split_keyboard`; `route=all` and `route=jis_special_us_default` are supported in preview / broker frame generation.
- `jis_special_us_default` sends normal keyboard usages to `kind=us_sub_keyboard`, JIS special usages (`0x87`-`0x8f`) to `kind=keyboard`, and maps internal `KC_ZKHK` to usage `0x35` on `kind=keyboard` while leaving `KC_GRV` on the US sub route.

Frame encoding must match `daemon/usbd/hid_report_broker.py`:

- magic `CQAU`
- version `0x01`
- kind `0x01` for keyboard, `0x04` for US sub keyboard
- payload length `8`
- flags `0`
- XOR checksum

Socket behavior:

- client is `SOCK_DGRAM`。
- missing broker socket causes reconnect/backoff but matrix socket stays up。
- when broker becomes available, send current HID state immediately。
- on shutdown, send null report best-effort。

## Python Sidecar Boundary

M0 and Python control plane must not both own `/tmp/matrix_events.sock`.
Two deployment modes are allowed.

### Mode A: core owns matrix, Python is sidecar

Recommended target mode.

- `matrixd -> logicd-core-rs`
- `logicd-control.py -> logicd-core-rs ctrl socket`
- Python `logicd` does not listen on `/tmp/matrix_events.sock`。
- Python reads status and sends explicit commands only。

### Mode B: shadow mode

Recommended validation mode.

- Python `logicd` remains active owner。
- `logicd-core-rs` listens on alternate socket, for example `/tmp/matrix_events_shadow.sock`。
- A tee or synthetic replay sends same events to shadow。
- Shadow computes reports but does not send to broker unless `LOGICD_CORE_OUTPUT_ENABLED=1`。
- When `LOGICD_CORE_PREVIEW_LOG_PATH` is set, shadow mode writes `shadow_report` NDJSON
  with event coordinates, 8 byte keyboard report, and encoded broker frame for byte parity comparison.
- The daemon listens on `LOGICD_CORE_CTRL_SOCKET` while accepting matrix clients, so `status`,
  `release_all`, `reload`, and `set_output` do not wait for additional matrix input.

Shadow mode is required before real-device owner switch.

## Control Socket

M0 ctrl socket is JSON line protocol.
It is intentionally small and read-mostly.

Commands:

```json
{"t":"status"}
{"t":"reload"}
{"t":"release_all"}
{"t":"set_output","enabled":true}
```

Responses:

```json
{"schema":"logicd-core.status.v1","process":true}
{"result":"ok","layers":3,"keycodes":268}
{"result":"ok","released":true}
{"result":"ok","output_enabled":true}
```

M0 does not accept keymap write commands.
Runtime keymap mutation remains Python-owned until a later phase defines a transaction protocol.

## Status

Status schema:

```json
{
  "schema": "logicd-core.status.v1",
  "process": true,
  "mode": "active",
  "output_enabled": true,
  "matrix_socket": {
    "path": "/tmp/matrix_events.sock",
    "listening": true
  },
  "broker_socket": {
    "path": "/tmp/usbd_hid_reports.sock",
    "available": true,
    "last_error": ""
  },
  "keymap": {
    "source": "/mnt/p3/keymap.json",
    "layers": 4,
    "warnings": []
  },
  "state": {
    "pressed_matrix": 0,
    "pressed_keys": 0,
    "modifier": 0,
    "active_layers": [0]
  },
  "counters": {
    "matrix_events": 0,
    "ignored_duplicates": 0,
    "out_of_range_events": 0,
    "unsupported_actions": 0,
    "rollover_drops": 0,
    "broker_frames_sent": 0,
    "broker_send_errors": 0,
    "reloads": 0
  }
}
```

Status file is written atomically to `/run/hidloom/logicd-core-status.json`.
It must never block matrix event processing.

## Systemd

Service name:

- `hidloom-logicd-core.service`

M3 active-basic 以降は、Python `logicd` を boot-critical owner から外し、
native core と Python companion を systemd 上の別 unit として管理する。
完了までの全体計画は [../../native-fast-input-core-design.md](../../native-fast-input-core-design.md#systemd-分割後の完了までの作業予定) に固定する。

Ordering:

- `After=hidloom-hidd.service`
- `Wants=hidloom-hidd.service`
- `Before=matrixd.service`
- `Before=logicd-companion.service` または移行期の `Before=logicd.service`

Rollout phases:

1. `logicd-core-rs` shadow service, output disabled。
2. shadow replay parity with captured matrix events。
3. active service owns `/tmp/matrix_events.sock`, output enabled。
4. `matrixd.service` connects to core instead of Python `logicd`。
5. Python `logicd` becomes delayed companion or starts after core without matrix listener。
6. core-owned `input-to-HID ready` marker is used for boot timing, while companion readiness is non-critical。

Unit sketch:

```ini
[Unit]
Description=HIDloom native logicd core
After=hidloom-hidd.service
Wants=hidloom-hidd.service
Before=matrixd.service
Before=logicd-companion.service

[Service]
Type=simple
ExecStart=@HIDLOOM_REPO_ROOT@/bin/hidloom-logicd-core --serve
Restart=always
RestartSec=0.2
RuntimeDirectory=hidloom

[Install]
WantedBy=multi-user.target
```

Companion unit sketch:

```ini
[Unit]
Description=HIDloom logicd companion control plane
After=hidloom-logicd-core.service matrixd.service
Wants=hidloom-logicd-core.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 -S -m logicd.logicd --companion
Restart=always
RestartSec=0.5
RuntimeDirectory=hidloom

[Install]
WantedBy=multi-user.target
```

The first active-basic slice may keep the existing Python `logicd.service` name for rollback,
but it must not listen on `/tmp/matrix_events.sock` while core owns that socket.
If companion mode is not implemented yet, Python `logicd` should be disabled or delayed during
the active-owner rehearsal.

## Failure Behavior

| failure | behavior |
| --- | --- |
| keymap runtime invalid | fallback to default, warn in status |
| default keymap invalid | fatal startup error |
| broker socket missing | keep matrix socket alive, retry broker, send current state on reconnect |
| matrix client disconnect | keep pressed state, optional release_all after configurable timeout |
| core shutdown | send null report best-effort |
| core restart | start with empty pressed state and send null report once broker is available |
| unsupported action | no-op, count, optional debug log |
| too many simultaneous keys | keep first six, count rollover drops |

Matrix client disconnect policy needs real-device confirmation.
If `matrixd` disconnects while keys are physically held, release_all is usually safer than holding stale keys.

## Test Plan

Current local regression entrypoint:

- `cargo test` in `tools/hidloom_logicd_core/`
- `python3 script/test_logicd_core_rs_tool.py`

The current shadow unit is opt-in / disabled by default:

- `system/systemd/hidloom-logicd-core.service`
- `LOGICD_CORE_MATRIX_SOCKET=/tmp/matrix_events_shadow.sock`
- `LOGICD_CORE_OUTPUT_ENABLED=0`
- `LOGICD_CORE_MATRIX_SOCKET_MODE=0666`
- `LOGICD_CORE_PREVIEW_LOG_PATH=/run/hidloom/logicd-core-preview.ndjson`

2026-06-20 real-device shadow result on `<keyboard-host>`:

- ARM64 release build passed.
- `bin/hidloom-logicd-core --check-config` loaded the real default keymap/keycodes.
- `python3 script/test_logicd_core_rs_tool.py` passed on the device.
- `hidloom-logicd-core.service` started as disabled shadow service and listened on `/tmp/matrix_events_shadow.sock`.
- Non-root synthetic `P00\nR00\n` injection updated status to `matrix_events=2`, `report_previews=2`, `broker_frames_sent=0`, `pressed_matrix=0`.
- Service was stopped after the smoke; `logicd`, `matrixd`, and `hidloom-hidd` stayed active.

2026-06-20 local M2 replay helper update:

- `LOGICD_CORE_PREVIEW_LOG_PATH` writes preview-only `shadow_report` NDJSON while output remains disabled.
- `tools/logicd_core_shadow_replay.py` can send a recorded 4 byte matrix stream to `/tmp/matrix_events_shadow.sock`
  and optionally wait for `/run/hidloom/logicd-core-status.json` counters.
- `tools/usbd_hid_report_capture.py` records broker datagrams from a temporary capture socket as NDJSON.
- `tools/logicd_core_parity_compare.py` compares core preview reports with captured Python broker frames, including broker kind.
- `tools/logicd_python_matrix_replay.py` replays the same matrix stream through an isolated Python `logicd`
  runtime and writes temporary broker socket frames as NDJSON. It forces `usb_split_keyboard.enabled=false`
  by default for canonical keyboard payload comparison; `--keep-split-keyboard` keeps the configured split route.
- `tools/logicd_core_parity_suite.py` derives M0-supported basic key / modifier chord / `MO(n)`
  sequences from the default keymap, compares Rust core reports with isolated Python `logicd` reports,
  and reports unsupported actions separately.
- `tools/logicd_core_active_owner_preflight.py` checks the native core binary, systemd unit state,
  split route config, rollback dry-run, boot marker helper, and runtime status snapshots without
  restarting services or sending HID reports.
- The parser accepts both matrixd newline terminator and existing Python helper NUL terminator for packet byte 3.
- `script/test_logicd_core_rs_tool.py` covers replay helper -> shadow socket -> preview log -> status counter,
  plus capture / compare helper behavior.

2026-06-20 real-device M2 preflight on `<keyboard-host>` / `<keyboard-host>`:

- `<keyboard-host>` received the logicd-core-rs changes without changing the active Python `logicd` owner.
- ARM64 release binary built and installed to `bin/hidloom-logicd-core`.
- `bin/hidloom-logicd-core --check-config` loaded `keycodes=268` and `layers=3`.
- Disabled shadow unit was installed with `LOGICD_CORE_OUTPUT_ENABLED=0` and
  `LOGICD_CORE_PREVIEW_LOG_PATH=/run/hidloom/logicd-core-preview.ndjson`.
- Temporary shadow service start plus synthetic `P00\nR00\n` replay updated status to
  `matrix_events=2`, `report_previews=2`, `broker_frames_sent=0`, and `output_enabled=false`.
- Preview log recorded the default-keymap `0,0` report `0000520000000000` followed by a null report.
- After stopping the shadow service, `logicd`, `matrixd`, and `hidloom-hidd` stayed active, and
  `hidloom-hidd` status still had `write_errors=0` / `dropped_reports=0`.
- `<keyboard-host>` passed `python3 script/test_logicd_core_rs_tool.py`.
- `<keyboard-host>` has no Rust toolchain, but the capture / compare helpers were synced and their
  datagram smoke passed.
- After adding isolated Python replay, `<keyboard-host>` passed `python3 script/test_logicd_core_rs_tool.py`
  again, including core preview vs Python broker-frame byte parity for the default keymap `P70\nR70\n`
  sequence. `logicd`, `matrixd`, and `hidloom-hidd` remained active while `logicd-core` was inactive after smoke.
- After adding the keymap parity suite, `<keyboard-host>` passed `sequences=68`, `matched=68`,
  `unsupported_actions=29`, `result=ok`. `<keyboard-host>` received the helper and passed CLI smoke
  without a Rust toolchain. M2 shadow parity is complete enough to stop treating replay source as a blocker.
- After adding deterministic layer actions (`MO` / `TG` / `TO` / `DF` / `OSL`) on 2026-06-21,
  the latest `<keyboard-host>` parity suite passed `sequences=65`, `matched=65`,
  `unsupported_actions=29`, `result=ok`.
- Local M3 control preflight added a nonblocking matrix/control socket loop and regression coverage for
  `status`, `set_output`, `release_all`, and `reload` JSON-line commands.
- `<keyboard-host>` passed the M3 control smoke in shadow mode: `P70` made
  `pressed_matrix=1` / `pressed_keys=1`, `release_all` returned `released=true` and reset both to zero,
  `report_previews=2`, and `reload` returned `layers=3` / `keycodes=268`. The shadow unit was stopped
  afterward; `logicd`, `matrixd`, and `hidloom-hidd` stayed active and `logicd-core` remained disabled.
- The shadow unit now calls `hidloom-logicd-core --ctrl-release-all` from `ExecStop` and preserves
  `/run/hidloom` across stop for post-stop diagnostics. On `<keyboard-host>`, stop smoke from a
  pressed `P70` state ended with `pressed_matrix=0`, `pressed_keys=0`, `report_previews=2`, and
  journal output `{"released":true,"result":"ok"}`. Restart smoke also released the old process
  before the new process came back with empty pressed state. The unit was stopped afterward and
  stayed disabled while `logicd`, `matrixd`, and `hidloom-hidd` remained active.
- `ExecStopPost` now calls `hidloom-logicd-core --mark-stopped`, removes stale shadow sockets, and updates
  the preserved status snapshot to `process=false` / `matrix_socket.listening=false` /
  `ctrl_socket.listening=false`. This prevents boot marker reports from treating an inactive shadow
  unit as still listening.
- `tools/boot_marker_baseline.py` now includes `hidloom-logicd-core.service`, boot-critical socket
  snapshots, and hidd / logicd-core status snapshots. On `<keyboard-host>`, the stopped shadow service
  is reported as inactive, with shadow sockets absent and status marked stopped.
- `tools/logicd_core_owner_recovery.py` provides an idempotent rollback command back to Python
  `logicd` matrix ownership. It stops / disables `hidloom-logicd-core.service`, marks the native
  core stopped when the binary is present, starts `hidloom-hidd`, `logicd`, and `matrixd`, then reports
  final service states. `<keyboard-host>` passed `--apply --sudo --json` with `logicd-core` inactive /
  disabled and the normal daemons active.

Unit tests:

- matrix packet parser parity。
- duplicate edge suppression。
- keymap priority runtime over default。
- invalid runtime fallback。
- invalid default fatal。
- basic `KC_A` press/release HID report。
- modifier press/release bit mapping。
- six-key rollover limit。
- `KC_TRNS` lower-layer fallback。
- `KC_NONE` no-op。
- `MO(n)` press captures higher layer, release uses captured action。
- unsupported action counter。
- broker frame encode checksum。
- broker missing/reconnect behavior。
- ctrl status/reload/release_all。
- owner recovery dry-run / state evaluation。

Python parity references:

- `daemon/logicd/protocol.py`
- `daemon/logicd/hid_report.py`
- `daemon/logicd/keymap.py`
- `script/test_input_event_tap_output.py`
- `script/test_logicd_usbd_report_broker_backend.py`
- `script/test_logicd_matrix_event_processing_boundary.py`

Captured replay tests:

1. Record matrix event stream from Python active mode。
2. Feed same stream to `logicd-core-rs` shadow mode using `tools/logicd_core_shadow_replay.py`。
3. Capture preview-only `shadow_report` NDJSON with `LOGICD_CORE_PREVIEW_LOG_PATH`。
4. Feed stream to Python `logicd` with broker output captured by `tools/usbd_hid_report_capture.py`
   on a temporary broker socket。
5. Compare supported keyboard broker frames byte-for-byte with `tools/logicd_core_parity_compare.py`。
6. Ignore unsupported action frames only when status records them explicitly。

Real-device smoke:

1. boot with shadow mode and confirm no change in live input。
2. press normal key, modifier chord, Fn layer key, release in varied order。
3. compare Python output and core shadow output counters。
4. switch core active for USB keyboard output only。
5. confirm first key after boot works before Python control plane is ready。
6. restart Python sidecar and confirm typing continues。
7. restart core and confirm all keys release。
8. rollback to Python active mode。

## Migration Checklist

Before active rollout:

- `hidd-rs` or Python broker is stable and has a single socket owner。
- shadow mode can run without owning `/tmp/matrix_events.sock`。
- replay fixtures cover the board's actual keymap。
- `/api/status` can show whether active owner is Python or native core。
- rollback unit or documented command exists。
- `tools/boot_marker_baseline.py` records:
  - gadget configured
  - hidd socket listening
  - logicd-core matrix socket listening
  - matrixd connected
  - `hidd-status.json` / `logicd-core-status.json` snapshots

Still required before active owner rollout:

- boot-to-first-key marker measurement for native core owner mode。
- live active-owner smoke with output enabled, including keyboard / US sub route, after the reboot marker measurement is acceptable。
  - first broker frame sent

After active rollout:

- Python `logicd` matrix listener is disabled or moved to sidecar mode。
- duplicate LED / key event fan-out is not happening。
- Vial keymap read/write behavior is either disabled, proxied, or clearly documented。
- stuck-key prevention is tested with service restarts。

## Open Questions

- `MO(n)` を M0 に含めるか、初期は完全 basic keyboard のみにするか。
- runtime keymap reload 時、押下中の key を release_all するか、captured action を維持するか。
- Python sidecar との status merge を HTTP 側で行うか、core status をそのまま exposed field にするか。
- Vial keymap write を core に即時 reload させる transaction owner はどこにするか。
- matrixd reconnect 時の release_all timeout を何秒にするか。

## Acceptance Criteria

M0 is accepted only when:

- Existing `matrixd` binary connects without rebuild.
- Existing broker frame receiver accepts core output without source change.
- Supported key outputs match Python `HidState` byte-for-byte.
- Unsupported actions are visible and do not crash the core.
- Shadow replay can run on the real keymap.
- Active mode reduces boot-to-first-key marker compared with Python-only baseline.
- Rollback to Python `logicd` active mode is documented and tested.
