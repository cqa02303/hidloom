# hidd-rs M0 Implementation Spec

作成日: 2026-06-19

この文書は、Python `usbd.py` の boot-critical HID report broker 部分を
Rust daemon `hidloom-hidd` へ置き換えるための M0 実装仕様である。
上位構成と移行方針は [../../native-fast-input-core-design.md](../../native-fast-input-core-design.md) を参照する。

2026-06-19 時点で M0 は `tools/hidloom_hidd/` に実装済みで、binary 名は `hidloom-hidd`。
設計中の呼称として残っている `hidd-rs` は、この実装を指す。
2026-06-20 以降は `<keyboard-host>` の既定 USB HID owner として昇格済みで、
legacy Python `usbd.service` は通常 inactive の rollback / A/B 診断用である。

M0 の目的は、USB gadget 作成後できるだけ早く `/tmp/usbd_hid_reports.sock`
互換 socket を開き、`logicd` または `logicd-core-rs` から届く HID report frame を
既存と同じ endpoint へ安全に流すことである。

## 結論

`hidloom-hidd` M0 は `hidloom-usb-gadget-fast` に吸収しない。
gadget setup は oneshot、HID broker は常駐 state machine であり、restart / rollback /
status / endpoint reopen の責務が異なるためである。

M0 は次の互換性を最優先する。

- Unix datagram socket protocol は既存 `usbd.hid_report_broker` と同一。
- `/dev/hidg0` multi-report endpoint と `/dev/hidg2` US sub keyboard endpoint の mapping は同一。
- keyboard pacing、release merge、mouse coalesce、write retry は既存 `usbd.py` と同等。
- `logicd` 側の broker writer を変更せずに A/B 切り替えできる。

## M0 の責務

M0 で持つもの:

- `/tmp/usbd_hid_reports.sock` 互換の `AF_UNIX` / `SOCK_DGRAM` server。
- HID broker frame decode / validate / checksum。
- `/dev/hidg0` / `/dev/hidg2` endpoint open / write / reopen。
- `keyboard` / `mouse` / `consumer` / `us_sub_keyboard` の report adaptation。
- keyboard duplicate suppression、release merge、rate pacing。
- mouse motion coalesce、button transition immediate flush。
- shutdown 時の best-effort null report。
- read-only status file または status socket。

M0 で持たないもの:

- keymap semantics。
- text send、IME、host layout policy。
- Vial Raw HID protocol の解釈。Raw HID packet bridge は 2026-06-20 に
  `/dev/hidg1 <-> viald` bridge として `hidloom-hidd` へ追加済み。
- Vial state machine。`hidloom-hidd` は固定長 packet を中継し、`viald` が protocol を解釈する。
- Bluetooth HID。
- HTTP API。

## Protocol

既存 broker frame は固定 64 byte である。

| offset | size | name | value |
| --- | ---: | --- | --- |
| 0 | 4 | magic | ASCII `CQAU` |
| 4 | 1 | version | `0x01` |
| 5 | 1 | kind | report kind |
| 6 | 1 | payload_len | kind ごとの payload 長 |
| 7 | 1 | flags | M0 は `0x00` のみ受ける |
| 8 | 24 | payload | payload body。未使用 byte は `0x00` |
| 32 | 31 | reserved | all zero |
| 63 | 1 | checksum | byte 0-62 の XOR |

定数:

| name | value |
| --- | ---: |
| `FRAME_MAGIC` | `CQAU` |
| `FRAME_VERSION` | `0x01` |
| `FRAME_SIZE` | 64 |
| `PAYLOAD_OFFSET` | 8 |
| `PAYLOAD_CAPACITY` | 24 |
| `CHECKSUM_OFFSET` | 63 |

Kind:

| kind | value | payload length |
| --- | ---: | ---: |
| `keyboard` | `0x01` | 8 |
| `mouse` | `0x02` | 4 |
| `consumer` | `0x03` | 2 |
| `us_sub_keyboard` | `0x04` | 8 |

Invalid frame policy:

- frame size が 64 byte でない場合は reject。
- magic / version / checksum / reserved zero / payload length が不正な場合は reject。
- unknown kind は reject。
- reject は counter を増やし、daemon は継続する。
- invalid frame の payload を endpoint へ書いてはならない。

## Endpoint Mapping

M0 は現行 `adapt_current_multi_report_profile()` と同じ mapping にする。

| kind | endpoint | output report |
| --- | --- | --- |
| `keyboard` | `/dev/hidg0` | `[0x01] + 8 byte keyboard payload` |
| `mouse` | `/dev/hidg0` | `[0x02] + 4 byte mouse payload` |
| `consumer` | `/dev/hidg0` | `[0x03] + 2 byte consumer payload` |
| `us_sub_keyboard` | `/dev/hidg2` | `8 byte keyboard payload` |

Report ID:

| report | id |
| --- | ---: |
| keyboard | `0x01` |
| mouse | `0x02` |
| consumer | `0x03` |

`/dev/hidg2` は standalone keyboard endpoint であるため Report ID を付けない。
この差は Vial / host descriptor と一致していなければならない。

## Environment

M0 は既存環境変数を優先して読み、未指定時は既存値に合わせる。

| env | default | meaning |
| --- | --- | --- |
| `USBD_HID_REPORT_SOCKET` | `/tmp/usbd_hid_reports.sock` | datagram socket path |
| `USBD_HID_REPORT_PATH` | `/dev/hidg0` | multi-report HID endpoint |
| `USBD_US_SUB_HID_REPORT_PATH` | `/dev/hidg2` | US sub keyboard endpoint |
| `USBD_HID_WRITE_RETRY_TIMEOUT_SEC` | `0.25` | endpoint write retry total |
| `USBD_HID_WRITE_RETRY_INTERVAL_SEC` | `0.002` | endpoint write retry interval |
| `USBD_MOUSE_REPORT_HZ` | `125` | mouse motion flush upper rate |
| `USBD_KEYBOARD_REPORT_HZ` | `500` | keyboard report pacing rate |
| `USBD_KEYBOARD_REPORT_DEDUP` | `1` | duplicate keyboard report suppression |
| `USBD_KEYBOARD_RELEASE_MERGE_WINDOW_SEC` | `0.016` | release/next press merge window |
| `HIDD_STATUS_PATH` | `/run/hidloom/hidd-status.json` | read-only status snapshot |
| `HIDD_SOCKET_MODE` | `0666` | socket mode after bind |

M0 では `USBD_HID_REPORT_SOCKET_ENABLED` は service selection 側で扱う。
`hidloom-hidd` が起動しているときは socket を常に bind する。

現在の補助 CLI:

- `tools/hidloom_hidd/build.sh`: release build して `bin/hidloom-hidd` へ配置する。
- `bin/hidloom-hidd --frames N`: datagram を N 件処理して自然終了する。temp endpoint や実機 smoke で使う。

## Runtime Loop

起動手順:

1. config / env を読む。
2. stale socket path が socket であれば unlink する。
3. datagram socket を bind し、`HIDD_SOCKET_MODE` を適用する。
4. `/dev/hidg0` と `/dev/hidg2` を open する。失敗しても daemon は継続する。
5. status を初回出力する。
6. receive loop へ入る。

Loop 方針:

- `poll` / `epoll` で socket receive と timer deadline を同時に扱う。
- datagram は 1 frame = 1 datagram として扱う。
- frame decode 後、kind ごとの scheduler へ渡す。
- scheduler の due time が来たら endpoint write を実行する。
- signal 受信時は null report を best-effort で送って終了する。

擬似コード:

```text
while running:
    timeout = min(mouse_due, keyboard_due, release_merge_due)
    event = poll(socket, timeout)

    if event == socket_readable:
        frame = recv_exact_datagram(max=64)
        decoded = decode_frame(frame)
        if decoded.invalid:
            counters.invalid_frames += 1
            continue
        dispatch(decoded.kind, decoded.payload)

    flush_release_merge_if_due()
    flush_keyboard_pacer_if_due()
    flush_mouse_scheduler_if_due()
    write_status_if_dirty_or_interval()
```

## Keyboard Scheduler

Keyboard-like kinds:

- `keyboard`
- `us_sub_keyboard`

それぞれ endpoint と Report ID が異なるため、scheduler state は route ごとに分ける。
ただし algorithm は同一にする。

Required behavior:

- 同一 report の連続送信は `USBD_KEYBOARD_REPORT_DEDUP=1` のとき抑制する。
- report interval は `1 / USBD_KEYBOARD_REPORT_HZ` を下限にする。
- release report は `USBD_KEYBOARD_RELEASE_MERGE_WINDOW_SEC` だけ保留できる。
- 保留中に別 key の press が来た場合、release を省略して次 press を送れる。
- 保留中に同一 key の再 press が来た場合、release と press を両方送る。
- 保留中に同一 modifier の再 press が来た場合、release と press を両方送る。
- mouse / consumer report が来た場合、保留中 release を先に flush する。
- shutdown 時は保留 release を捨てず、null report を best-effort で送る。

Release merge は host 側の key repeat / IME / modifier 状態へ影響するため、M0 の最重要 parity 項目である。

## Mouse Scheduler

Mouse payload は `[buttons, dx, dy, wheel]` の 4 byte である。

Required behavior:

- motion は `USBD_MOUSE_REPORT_HZ` の周期で coalesce する。
- dx / dy / wheel は signed i8 範囲へ clamp する。
- button bit の変化は即時 flush する。
- button held state は motion report に反映する。
- mouse report 前に keyboard release merge が保留されている場合は keyboard 側を先に flush する。

## Write Retry

`write_exact(endpoint, report)` は次のように振る舞う。

- write が full length なら success。
- `EINTR` は retry。
- short write は counter を増やし、残りを書こうとせず report 単位で retry する。
- `ENODEV` / `ESHUTDOWN` / `EIO` は endpoint を close し、reopen retry へ移る。
- retry total が `USBD_HID_WRITE_RETRY_TIMEOUT_SEC` を超えたら drop し、last_error を status へ残す。

HID gadget endpoint は通常 full report write か error であり、partial write を report split として扱ってはならない。

## Status

M0 は HTTP に依存しない read-only status を出す。
初期実装は `/run/hidloom/hidd-status.json` の atomic rename write でよい。

Schema:

```json
{
  "schema": "hidd.status.v1",
  "process": true,
  "protocol": "usbd-hid-report-broker.v1",
  "socket": {
    "path": "/tmp/usbd_hid_reports.sock",
    "listening": true,
    "mode": "0666"
  },
  "endpoints": {
    "hidg0": {
      "path": "/dev/hidg0",
      "open": true,
      "last_error": "",
      "last_open_mono_ms": 0
    },
    "hidg2": {
      "path": "/dev/hidg2",
      "open": true,
      "last_error": "",
      "last_open_mono_ms": 0
    }
  },
  "counters": {
    "frames_received": 0,
    "keyboard_reports": 0,
    "us_sub_keyboard_reports": 0,
    "mouse_reports": 0,
    "consumer_reports": 0,
    "invalid_frames": 0,
    "write_errors": 0,
    "dropped_reports": 0
  }
}
```

Status file 更新は HID write path を block してはならない。
atomic write が失敗した場合は log のみで継続する。M0 実装では起動直後と frame 処理後、
および `--frames` 自然終了時に status を更新する。systemd から SIGTERM で停止した場合は
停止直前 counter の最終 write を保証しないため、live counter は処理後 update を読む。

## Systemd

Service name:

- `hidloom-hidd.service`

Ordering:

- `After=hidloom-usb-gadget.service`
- `Wants=dev-hidg0.device dev-hidg2.device`
- `Before=basic.target multi-user.target`
- `Conflicts=usbd.service`

M0 の切り替え方:

- Python `usbd.service` と `hidloom-hidd.service` が同じ `/tmp/usbd_hid_reports.sock` を bind してはならない。
- M0 rollout は `usbd` の HID report broker 部分だけを止めるか、service selection で `hidloom-hidd` を owner にする。
- Raw HID bridge も `hidloom-hidd` が持つ。Python `usbd` を併用する場合は、Python 側の broker socket bind
  と `/dev/hidg1` owner が二重にならない設定を必須にする。

Unit source:

```ini
[Unit]
Description=HIDloom native HID report broker (hidloom-hidd)
After=hidloom-usb-gadget.service
Wants=dev-hidg0.device dev-hidg2.device
Before=basic.target multi-user.target
Conflicts=usbd.service

[Service]
Type=simple
ExecStart=@HIDLOOM_REPO_ROOT@/bin/hidloom-hidd
WorkingDirectory=@HIDLOOM_REPO_ROOT@
User=root
Group=root
Restart=on-failure
RestartSec=0.2
Environment=USBD_HID_REPORT_SOCKET=/tmp/usbd_hid_reports.sock
Environment=USBD_HID_REPORT_PATH=/dev/hidg0
Environment=USBD_US_SUB_HID_REPORT_PATH=/dev/hidg2
Environment=HIDD_STATUS_PATH=/run/hidloom/hidd-status.json
RuntimeDirectory=hidloom

[Install]
WantedBy=multi-user.target
```

Tracked template is `system/systemd/hidloom-hidd.service`. Fresh install installs the unit but does not
enable it by default.

## Rollback

Rollback は service owner を戻すだけで完結させる。現行運用では helper を使う。

```bash
python3 tools/logicd_core_owner_recovery.py --apply
python3 tools/logicd_core_native_owner_restore.py --apply
```

手動で境界を確認する場合の最小操作:

1. `systemctl disable --now hidloom-hidd.service`
2. `systemctl start usbd.service`
3. 必要なら `systemctl restart logicd.service`
4. `/tmp/usbd_hid_reports.sock` が Python `usbd` owner であることを確認する。

`logicd` の frame format を変えないため、rollback で keymap や control plane への影響を出さない。

## Test Plan

Unit tests:

- valid frame decode。
- invalid magic / version / size / checksum / reserved / payload length reject。
- endpoint mapping parity。
- keyboard report ID prepend。
- `/dev/hidg2` no Report ID。
- duplicate keyboard report suppression。
- release merge: different key press merges, same key press merges when it restores the same state。
- release merge flush before mouse / consumer。
- mouse motion coalesce。
- mouse button transition immediate flush。
- write retry timeout and endpoint reopen。
- status schema snapshot。

Python parity fixtures:

- `script/test_usbd_hid_report_broker.py`
- `script/test_usbd_validation.py`
- `script/test_logicd_usbd_report_broker_backend.py`

Native implementation uses the existing Python frame encoder in `script/test_hidloom_hidd_tool.py`.
The acceptance condition is byte-for-byte report output parity for the M0 supported cases.

Integration tests without hardware:

- socket bind/unlink/mode。
- send broker frames to a temporary datagram socket and write reports to temporary files/FIFOs。
- live status counter update before process exit。

Real-device smoke:

1. boot with `hidloom-hidd` enabled and Python broker disabled。
2. verify `/tmp/usbd_hid_reports.sock` exists before `logicd` first report。
3. press a normal key, modifier key, consumer key, mouse key, and US sub key。
4. confirm host receives expected reports。
5. unplug/replug USB and confirm endpoint reopen or clear failure status。
6. stop `logicd` while a key is held and confirm no stuck key after service restart。
7. rollback helper で Python `usbd` owner へ戻せることを確認し、restore helper で native owner へ戻す。

2026-06-19 real-device result on `<keyboard-host>`:

- Rust toolchain installed on the device with apt: `rustc 1.85.0`, `cargo 1.85.0`, `rustfmt 1.8.0`.
- `tools/hidloom_hidd/build.sh` built ARM64 `bin/hidloom-hidd`.
- `script/test_hidloom_hidd_tool.py` passed on the device.
- `hidloom-hidd.service` started with Python `usbd.service` stopped, bound `/tmp/usbd_hid_reports.sock`,
  opened `/dev/hidg0` and `/dev/hidg2`, and processed safe null keyboard / US-sub reports with
  `frames_received>=2`, `write_errors=0`.
- At that point, the smoke rolled back to Python `usbd.service`, `logicd.service`, `matrixd.service`, and
  `hidloom-usb-gadget.service`; later promotion changed the normal owner to
  `hidloom-hidd.service` with `usbd.service` inactive.

Remaining real-device observations:

- Boot marker comparison against Python `usbd` baseline.
- Host-visible non-null typing / mouse / consumer smoke across target OSes.
- USB unplug/replug endpoint reopen behavior.
- Held-key crash / restart stuck-key recovery.

## Acceptance Criteria

M0 was accepted for active owner rollout when all conditions pass:

- Existing Python broker writer works without source change.
- Supported report output is byte-for-byte compatible with current `usbd.py`.
- Rollback to Python `usbd` is one service change and does not require keymap migration.
- No endpoint double-owner condition exists during boot.

Promotion to default boot owner additionally requires:

- Boot marker shows broker socket listening earlier than Python `usbd` baseline.
- `/api/status` or equivalent status surface can distinguish `hidloom-hidd` owner from Python `usbd` owner.
- Host-visible non-null typing / mouse / consumer / Raw HID Vial smoke passes on the intended host OS set.
- USB disconnect/reconnect and held-key recovery behavior are documented.

## Known Risks

Endpoint double-owner:

- Risk: Python `usbd` and `hidloom-hidd` both bind the socket or open `/dev/hidg0`.
- Mitigation: explicit service selection, status owner field, startup test.

Release merge mismatch:

- Risk: subtle Japanese input / modifier behavior changes.
- Mitigation: fixture parity and real typing smoke with IME.

Raw HID split:

- Risk: `/dev/hidg1` Raw HID bridge が止まると Vial が device reload で通信失敗する。
- Mitigation: `hidloom-hidd` owns `/dev/hidg1` as well as `/dev/hidg0` / `/dev/hidg2`;
  status explicitly shows `hidg1.open` / `hidg1.connected` and host-side
  `script/test_vial_raw_hid_host.py` sends valid Vial protocol packets through the bridge.

Host descriptor drift:

- Risk: Report ID mapping changes in gadget descriptor but `hidloom-hidd` still uses old mapping.
- Mitigation: descriptor profile constant and tests that compare gadget helper profile with hidd mapping.

Stuck key on crash:

- Risk: process abort before null report.
- Mitigation: systemd restart plus `logicd-core-rs` all-up on reconnect; panic hook can best-effort null but cannot be sole safety.
