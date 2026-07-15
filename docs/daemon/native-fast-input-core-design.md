# Native Fast Input Core Design

作成日: 2026-06-19

この文書は、起動直後の usable keyboard time を短縮するために、
`matrixd` / `logicd` / `usbd` の boot-critical path を native core へ寄せる案と実装済み移行状態を固定する。
2026-06-21 時点では、`<keyboard-host>` の既定 owner は `matrixd -> logicd-core-rs -> hidloom-hidd` で、
Python `logicd` は `logicd-companion.service` として control plane を担当し、legacy `usbd.service` は通常 inactive。

## 背景

`<keyboard-host>` の現行 Raspberry Pi OS 構成では、初回 boot の marker は概ね次の通りだった。

| marker | boot からの時刻 |
| --- | ---: |
| `hidloom-usb-gadget.service` start | 13.390s |
| `logicd.service` start | 13.413s |
| `logicd.service` systemd active | 13.852s |
| `matrixd.service` systemd active | 14.121s |
| `matrixd` GPIO init done | 14.288s |
| native USB gadget configured | 14.764s |
| `usbd` HID report broker socket listening | 15.628s |
| `logicd` sockets listening | 16.761s |
| `matrixd` connected to `logicd` | 16.798s |
| analog stick runtime center calibrated | 19.277s |
| `ledd` / `btd` / `viald` / `httpd` late group ready | 46-50s |

`hidloom-late-services.timer` により Bluetooth / Vial / HTTP は 45 秒後へ遅延済みで、
LED は `ledd.service` が早期起動して低輝度の startup effect を表示し、`logicd-companion` 起動後の初期同期で通常状態へ戻る。
boot-critical input path は USB gadget、HID broker、`logicd`、`matrixd` に絞られている。
次の大きな短縮候補は Python daemon 起動と import / runtime init を避けることである。

## 目的

- 電源投入から `input-to-HID ready` までの時間を短縮する。
- Python control plane が起動途中でも、物理キー入力だけは host へ届くようにする。
- `logicd` の複雑な runtime 機能を失わず、boot-critical hot path だけを native 化する。
- USB endpoint owner を明確にし、`logicd` が `/dev/hidg*` の細部を直接持たない方針を維持する。

## 非目的

- `logicd` の全機能を一度に Rust / C へ移植しない。
- HTTP UI、Vial import/export、macro、text send、Morse、touch flick、sessiond PTY mirror を
  初期 native core へ入れない。
- `usbd` / HID transport owner に keymap semantics や text layout policy を持たせない。
- 既存 Python daemon をすぐ削除しない。
- Buildroot 化を前提条件にしない。Raspberry Pi OS 上でも効果を測れる形にする。

## 提案構成

初期の推奨構成は、USB gadget setup、HID broker、keymap hot path、control plane を分ける。

```text
hidloom-usb-gadget-fast
        |
        v
      hidd-rs  <----- logicd-core-rs <----- matrixd
        ^                 |
        |                 v
        |          logicd-control.py
        |
      host USB HID
```

各コンポーネントの役割:

| component | 役割 |
| --- | --- |
| `hidloom-usb-gadget-fast` | configfs で通常 USB composite HID gadget を作る。原則 oneshot。 |
| `hidd-rs` | `/dev/hidg0` / `/dev/hidg1` / `/dev/hidg2` の endpoint owner。HID report broker socket を早期に開く。 |
| `logicd-core-rs` | matrix event 受信、最小 keymap / layer / output routing、keyboard report 生成。 |
| `logicd-control.py` | HTTP / Vial / macro / interaction / text send などの複雑で変更頻度が高い control plane。 |
| `matrixd` | 既存 C scanner。row/col event を core へ送る。 |

## 責務境界

native 化で一番危険なのは、処理速度ではなく owner が曖昧になることである。
次の owner 表を initial contract とする。

| state / function | owner | reader / client | 備考 |
| --- | --- | --- | --- |
| USB gadget configfs tree | `hidloom-usb-gadget-fast` | `hidd-rs`, diagnostics | 作成後は原則不変。再作成は setup service の責務 |
| `/dev/hidg*` fd | `hidd-rs` | none | 二重 open を避ける。endpoint owner は 1 process |
| HID report broker socket | `hidd-rs` | `logicd-core-rs`, fallback Python `logicd` | M0 は既存 frame 互換 |
| Raw HID / Vial packet bridge | `hidloom-hidd` | `viald` | `/dev/hidg1` と `viald_events.sock` の bridge も native owner |
| pressed key state | `logicd-core-rs` | `logicd-control.py`, status | Python sidecar は直接 mutation しない |
| active layer state | `logicd-core-rs` | `logicd-control.py`, HTTP status | advanced layer 機能は phase ごとに追加 |
| desired keymap/config | Python control plane / runtime files | `logicd-core-rs` | core は snapshot を読み、reload command で更新 |
| output target state | `logicd-core-rs` | `logicd-control.py`, OLED/status | M0 は USB early path に限定 |
| macro/text/sessiond state | Python control plane | `logicd-core-rs` only via explicit command | implicit side effect を禁止 |
| service health/status | each daemon | HTTP/MCP/status tools | status merge は read-only |

この表から外れる機能を追加する時は、その機能が hot path なのか control plane なのかを先に決める。

## hidd-rs 方針

`hidd-rs` は、既存 `usbd.py` の boot-critical HID report broker 部分を native daemon として置き換える候補である。
`hidloom-usb-gadget-fast` に吸収する案もあるが、初期段階では分離を推奨する。

2026-06-19 時点で M0 は `tools/hidloom_hidd/` の `hidloom-hidd` として実装済み。
`<keyboard-host>` で ARM64 build、既存 Python frame encoder を使った temp endpoint parity、
systemd service 経由の `/dev/hidg0` / `/dev/hidg2` null-report smoke、validation suite 通過まで確認した。
2026-06-20 以降は既定 owner を `hidloom-hidd.service` へ昇格し、Raw HID / Vial bridge も
`hidloom-hidd` 側で持つ。legacy `usbd.service` は rollback / A/B 診断用として残す。
昇格後の確認履歴は [specs/hidd/m0-implementation-spec.md](specs/hidd/m0-implementation-spec.md) と
private workspace reference *(omitted from public export)* に残す。

### 分離を推奨する理由

- gadget setup は固定手順の oneshot、HID broker は常駐 daemon で性質が違う。
- endpoint reopen、socket accept、frame validation、shutdown null report は long-running state machine になる。
- `usbd.py` との A/B 切り替えや rollback がしやすい。
- 後で `logicd-core-rs` と型 / frame 定義を共有しやすい。
- `hidloom-usb-gadget-fast` を肥大化させず、shell fallback の位置づけを保てる。

### M0 対象

- `/tmp/usbd_hid_reports.sock` 互換の local socket を listen する。
- 既存 broker frame と同じ `kind=keyboard/mouse/consumer/us_sub_keyboard` を受ける。
- `keyboard` / `mouse` / `consumer` を `/dev/hidg0` へ書く。
- `us_sub_keyboard` を `/dev/hidg2` へ書く。
- mouse motion accumulator、button transition immediate write の既存境界を維持する。
- endpoint close / reopen を扱う。
- shutdown 時に keyboard / mouse null report を送れる。
- `/api/status.usbd` 相当が読めるよう、status file か small status socket を出す。

### M0 では扱わないもの

- Vial Raw HID protocol の解釈。Raw HID packet bridge 自体は `hidloom-hidd` が持つ。
- Windows IME Raw HID experimental socket。
- keymap semantics。
- text stream / ANSI / host layout。
- Bluetooth HID。

### hidd-rs M0 protocol details

M0 は既存 `usbd` broker frame 互換を優先し、wire compatibility を壊さない。
既存 frame の仕様がコード上に散っている場合は、先に fixture と protocol note を追加する。

既存 writer は Unix datagram socket で broker frame を送る。M0 `hidd-rs` は互換 mode では
`SOCK_DGRAM` を維持する。stream socket へ変える場合は、writer 側の reconnect、
partial frame、backpressure 処理まで同じ phase で設計する。

M0 で受ける logical kind:

| kind | output endpoint | payload | timing |
| --- | --- | --- | --- |
| `keyboard` | `/dev/hidg0` | 8 byte keyboard report, hidd が Report ID を付与または既存互換で処理 | immediate |
| `us_sub_keyboard` | `/dev/hidg2` | 8 byte keyboard report | immediate |
| `consumer` | `/dev/hidg0` | consumer control report | immediate |
| `mouse` | `/dev/hidg0` | button / dx / dy / wheel | motion coalesce, button immediate |

既存 `usbd` broker には mouse accumulator だけでなく、keyboard report pacing、
duplicate suppression、release merge window、HID write retry がある。`hidd-rs` M0 は
これらを parity 対象に含める。

| behavior | current owner | M0 requirement |
| --- | --- | --- |
| mouse motion coalesce | `usbd.MouseReportScheduler` | parity required |
| mouse button immediate flush | `usbd.MouseReportScheduler` | parity required |
| keyboard report pacing | `usbd.KeyboardReportPacer` | parity required or explicitly disabled measurement |
| duplicate keyboard report suppression | `usbd.KeyboardReportPacer` | parity required |
| release merge window | `usbd` broker loop | parity required |
| HID write retry timeout / interval | `usbd` writer | parity required |

M0 status fields:

```json
{
  "schema": "hidd.status.v1",
  "process": true,
  "protocol": "usbd-hid-report-broker.v1",
  "socket": {"path": "/tmp/usbd_hid_reports.sock", "listening": true},
  "endpoints": {
    "hidg0": {"path": "/dev/hidg0", "open": true, "last_error": ""},
    "hidg1": {"path": "/dev/hidg1", "open": false, "owner": "python-usbd"},
    "hidg2": {"path": "/dev/hidg2", "open": true, "last_error": ""}
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

Status は HTTP が直接 hidd を制御しないための read-only surface であり、write command を混ぜない。

### hidd-rs failure behavior

| failure | expected behavior | reason |
| --- | --- | --- |
| `/dev/hidg0` missing at start | short retry, status `open=false`, socket may still listen | gadget setup と起動順が前後しても core を詰まらせない |
| endpoint write `ENODEV` / `ESHUTDOWN` | endpoint close, reopen retry, null report on reopen | USB re-enumeration / cable抜き差しに耐える |
| invalid frame | reject, increment counter, keep socket alive | malformed client で daemon を落とさない |
| client disconnect while key down | hidd cannot know pressed semantics; optional null report only for that client class | pressed state owner は core |
| hidd shutdown | send null keyboard/mouse/consumer reports best-effort | stuck key / stuck consumer risk を下げる |
| status file write fail | log only | HID path を止めない |

`hidd-rs` は key semantics を持たないため、client disconnect 時の release は完全には判断できない。
本命の stuck-key prevention は `logicd-core-rs` 側で行う。

## logicd-core-rs 方針

`logicd-core-rs` は、起動直後に必要な key input hot path だけを持つ。
Python `logicd` の全機能移植ではなく、Python control plane の前段に置く native runtime として始める。

### M0 対象

- `matrixd` 互換の matrix event socket を listen する。
- `config/default/keymap.json` または `/mnt/p3/keymap.json` から、最小 layer map を読む。
- `KC_*` basic keyboard key、modifier、`KC_TRNS`、`KC_NONE` を処理する。
- 必要最小限の `MO(n)` または `LT(n,kc)` は M0 から外してもよい。M1 以降で互換性を増やす。
- 8 byte keyboard report を生成し、`hidd-rs` へ送る。
- emergency release / all keys up を持つ。
- `status` / `reload` / `stop` 程度の control socket を持つ。

### logicd-core-rs M0 key semantics

M0 は対応範囲を狭くし、未対応 action を明示的に扱う。

| action | M0 behavior | notes |
| --- | --- | --- |
| `KC_A` など basic keyboard | supported | `hid_report.KEYCODE` と parity が必要 |
| modifier key | supported | modifier bit parity が必要 |
| `KC_TRNS` | supported | lower layer fallback。ただし M0 layer scope に依存 |
| `KC_NONE` | supported | no-op |
| `MO(n)` | optional M1 | M0 で入れる場合は layer state test 必須 |
| `LT(n,kc)` | M1+ | timing/interaction が絡むため M0 外 |
| mouse key / consumer | M1+ | hidd は transport 可能だが semantics は core phase 次第 |
| macro / text / script | Python control plane | M0 は unsupported counter |
| `OUTPUT_*` / BT action | Python control plane or M2+ | early USB path とは分ける |

未対応 action を押した場合の M0 policy:

- HID report は変えない。
- `unsupported_action_count` を増やす。
- 初回または rate-limited warning を journal/status に出す。
- key release では何もしない。

これにより、M0 core で未対応 key を押しても stuck key にならない。

### logicd-core-rs config snapshot

M0 core が読む JSON は最小 subset にする。

| file | required fields | optional fields |
| --- | --- | --- |
| `/mnt/p3/keymap.json` or `config/default/keymap.json` | `_layout_def`, `layers` | `encoders`, `joysticks` ignored in M0 |
| `config/default/config.json` | none for M0 if defaults are enough | `settings.usb_split_keyboard`, `settings.outputs` |

M0 loader rule:

1. runtime keymap `/mnt/p3/keymap.json` を優先する。
2. parse できない場合は default keymap へ fallback する。
3. both invalid の場合は core を degraded mode で起動し、matrix socket は開くが all key no-op にする。
4. degraded mode は status に明示する。

起動に失敗して process が落ちるより、SSH/HTTP から診断できる degraded mode を優先する。

### logicd-core-rs control surface

control socket は low-rate JSON line で始める。

```json
{"command":"status"}
{"command":"reload_keymap"}
{"command":"set_output_target","target":"usb"}
{"command":"all_keys_up","reason":"operator"}
{"command":"shadow_mode","enabled":true}
```

M0 response:

```json
{"result":"ok","schema":"logicd-core.status.v1","pressed":0,"layers":[0],"mode":"active_basic"}
```

禁止:

- arbitrary file write。
- service restart。
- shell command execution。
- advanced action eval。

Python control plane が必要な場合は、core に command を送るのではなく既存 Python daemon 側の責務として残す。

### Auxiliary input sources

現行 `logicd` は matrix event 以外の入力も受ける。native core が pressed state owner になる場合、
これらの入口を phase ごとに整理する必要がある。

| source | current path | early core policy |
| --- | --- | --- |
| physical matrix | `matrixd -> /tmp/matrix_events.sock -> logicd-core-rs`; core accepted-edge observation copy to `/tmp/matrix_tap_events.sock` | M0/M3 core owner。tap は HID decision へ使わない |
| HTTP virtual key | `httpd -> /tmp/matrix_events.sock -> current input owner` | native owner では core へ仮想 matrix injection。観測ではなく入力注入 |
| HTTP / Vial matrix tester | `logicd-core-rs -> /tmp/matrix_tap_events.sock -> logicd-companion -> /tmp/ctrl_events.sock K` | tap-observed state を表示。取りこぼし不可の入力処理には使わない |
| CLI sendkey / tools | `sendkey.py` / tools -> key event or ctrl socket | M0 は Python path、M4 で bridge |
| analog stick | `i2cd -> ctrl_events.sock -> logicd` | M0 core では対象外。early usable keyboard の合格条件に含めない |
| matrix-backed encoder | matrix event -> `logicd` binding | M0 では対象外または basic only |
| SPID motion | `spid -> logicd` | M0 では対象外 |
| touch flick | HTTP/touch -> `logicd` text/action dispatch | Python control plane |

M0 active basic の成功条件は、物理 key matrix から USB keyboard report までに限定する。
analog stick、SPID、sendkey CLI は M4 以降の bridge / parity 対象にする。
HTTP / Vial matrix tester は入力処理ではなく観測 UI なので、native owner では tap-observed state を companion の `ctrl K` に合流させる。

### Existing ctrl socket compatibility

HTTP UI、Vial、i2cd、tools は既存 `ctrl_events.sock` API を前提にしている。
native core が同じ path を奪うと Python control plane と競合する。

初期方針:

- M0/M3 では `ctrl_events.sock` は Python `logicd-control.py` または既存 Python `logicd` が持つ。
- `logicd-core-rs` の control socket は別名にする。例: `/tmp/logicd_core_ctrl.sock`。
- Python sidecar が必要な low-rate command だけ core control socket へ転送する。
- 既存 tools を一斉に core 対応へ変えない。

将来 `ctrl_events.sock` owner を core に移す場合は、既存 ctrl API の full compatibility test が必要になる。

### Python control plane に残すもの

- HTTP UI / settings / keymap editor。
- Vial protocol と `.vil` import/export。
- advanced macro、dynamic macro、Leader、Repeat Key、Caps Word、Morse、touch flick。
- text send、Windows IME helper、sessiond PTY mirror。
- Bluetooth host metadata、pairing UI、rename / forget。
- LED / OLED の高級 status 表示。
- docs / diagnostic / MCP 連携。

## IPC 方針

hot path と control plane の IPC は分ける。

| path | 推奨形式 | 理由 |
| --- | --- | --- |
| `matrixd -> logicd-core-rs` | 既存 matrix event format 互換から開始 | `matrixd` を最初に変えないため |
| `logicd-core-rs -> hidd-rs` | 既存 broker frame 互換、後で binary frame 検討 | `usbd.py` と A/B しやすい |
| `logicd-control.py -> logicd-core-rs` | JSON line control socket | 低頻度で human/debug friendly |
| `logicd-core-rs -> logicd-control.py` | event JSON line または status polling | 起動後の同期で十分 |

hot path の JSON は将来的に binary frame 化してよいが、初期は既存互換を優先する。
JSON を使う場合も、Rust 側は `serde` で strict deserialize し、unknown field と型不一致を明示 error にする。

## State synchronization

core と Python sidecar の同期は eventual consistency とする。
起動直後は core が単独で basic keyboard として動き、sidecar が後から詳細状態を読み取る。

### 起動時

1. core が keymap snapshot を読む。
2. core が matrix socket と hidd client を準備する。
3. matrixd が core に接続する。
4. Python sidecar が core status を読み、必要なら runtime config reload を要求する。
5. HTTP / Vial は sidecar 経由で core に desired keymap reload を反映する。

### keymap reload

reload は stuck key を避けるため、次の順序に固定する。

1. sidecar が新 keymap を runtime file へ atomic write する。
2. sidecar が core に `reload_keymap` を送る。
3. core は pressed state が空なら即 reload。
4. pressed state が非空なら、policy に従う。
   - safe mode: all keys up を送って reload。
   - strict mode: release を待って reload。
5. core は reload result と keymap revision を返す。

M0 は safe mode を推奨する。HTTP / Vial 編集は低頻度であり、stuck key 回避を優先する。

### Runtime file ownership

runtime JSON の書き込み owner は変えない。

| file | write owner | native core behavior |
| --- | --- | --- |
| `/mnt/p3/keymap.json` | Python control plane / Vial / HTTP | read snapshot only |
| `/mnt/p3/led_state.json` | Python `logicd` / `ledd` path | no write |
| `/mnt/p3/bluetooth_hosts.json` | `btd` / HTTP rename path | no read in core |
| `/mnt/p3/config.json` | operator / setup / future UI | read subset only |

core が degraded mode で起動しても runtime files を修復・上書きしない。
修復は Python control plane または operator の明示操作に寄せる。

### shadow mode

M2 では core が report を送らず、Python `logicd` と同じ matrix event を観測して preview report だけを出す。
shadow diff は次のような NDJSON で十分。

```json
{"t":"shadow_report","event":{"row":1,"col":2,"pressed":true},"core":"0200040000000000","python":"0200040000000000","match":true}
```

実機で差分がある action は、M3 active basic へ進む前に unsupported list へ分類する。

## 起動順序

目標の起動順序:

```text
local-fs / modules
  -> hidloom-usb-gadget-fast
  -> hidd-rs
  -> logicd-core-rs
  -> matrixd
  -> logicd-control.py
  -> ledd.service early startup effect
  -> late-services: btd / viald / httpd
```

`hidd-rs` は `/dev/hidg*` が無い場合に短く retry する。
`logicd-core-rs` は `hidd-rs` 未接続時でも matrix socket を先に開き、HID 接続後に null report から始める。
`matrixd` は core socket へ短い retry で接続する。

### systemd sketch

初期の unit は opt-in にし、fallback を残す。

```text
hidloom-usb-gadget.service
  Before=hidloom-hidd.service

hidloom-hidd.service
  After=hidloom-usb-gadget.service
  Before=logicd-core.service

logicd-core.service
  After=hidloom-hidd.service
  Before=matrixd.service

matrixd.service
  After=logicd-core.service
```

既存 Python `logicd.service` を完全に置き換える前は、次のどちらかにする。

| mode | units | 用途 |
| --- | --- | --- |
| shadow | Python `logicd.service` active, `logicd-core.service` preview-only | parity 測定 |
| active-basic | `logicd-core.service` active path, Python sidecar low-rate control | M3 以降 |

同じ `/tmp/matrix_events.sock` を二つの process が listen しないよう、shadow mode では socket path を分けるか、
matrixd の tee helper を使う。

### stale sockets and drop-ins

実機には過去の実験 drop-in が残ることがある。
native core rollout では、unit source だけでなく `/etc/systemd/system/*.d/` の effective config を確認する。

確認対象:

- `logicd.service.d/*`
- `usbd.service.d/*`
- `hidloom-usb-gadget.service.d/*`
- stale `/tmp/*.sock`
- stale hidd/core status files

`systemctl cat` と drop-in snapshot を rollout checklist に含める。

## 現在の bottleneck と方針

2026-06-20 の `<keyboard-host>` reboot sample では、boot-critical key path は次の状態だった。

| marker | boot からの時刻 |
| --- | ---: |
| USB HID gadget configured | 15.037s |
| `hidloom-hidd` active | 15.189s |
| Python `logicd.service` active | 15.325s |
| `matrixd.service` active | 15.342s |
| Python `logicd` logging ready | 17.059s |
| output router enabled | 17.150s |
| Python `logicd` sockets listening | 17.166s |
| `matrixd` connected to logicd | 17.166s |

`logicd` 内部の config load / runtime apply は 0.1s 前後に収まっているため、残る大きな待ちは
Python process startup / top-level import と boot-time CPU / I/O contention である。
したがって次の主方針は、Python `logicd` を単に軽くするのではなく、入力経路の ready owner を
native `logicd-core-rs` に移し、Python 側を遅延 companion として systemd 管理に分けることにする。

目標は、`hidloom-hidd` active 後すぐに `logicd-core-rs` が `/tmp/matrix_events.sock` を listen し、
`matrixd` が Python import を待たずに接続できる状態にすることである。
短期目標値は `logicd-core sockets listening` / `matrixd connected` を 16.0s 未満へ寄せること、
中期目標値は USB gadget configured 後 0.5s-0.8s 以内に `input-to-HID ready` marker を出すこと。

## systemd 分割後の完了までの作業予定

### 目標構成

`logicd.service` を boot-critical owner として使い続けず、次の 2 unit に分ける。

| unit | 役割 | boot-critical | failure policy |
| --- | --- | --- | --- |
| `hidloom-logicd-core.service` | matrix event listen、pressed state、basic keymap/layer、HID broker output、release safety | yes | `Restart=always`。Python companion 不在でも最低限の USB key path を維持する |
| `logicd-companion.service` または移行期の `logicd.service` | HTTP/Vial/macro/sessiond/text/advanced interaction/status merge | no | `Restart=always`。落ちても core は degraded mode で入力を維持する |

`systemd` は core と companion の再起動を別々に扱う。
core は入力 ready の source of truth、companion は desired config / advanced action / UI integration の client とする。
native core が Python process を直接 fork/restart する責務は持たせず、再起動自体は systemd に任せる。

### QMK action delegation

`logicd-core-rs` は QMK 由来の時間依存 / layer 意味論を持たない。
`LT(...)`、`MT(...)`、`MO(...)`、tap-hold、tap dance、combo、macro、mouse、text、script 系は
`/tmp/logicd_delegate_events.sock` へ matrix event をそのまま転送し、`logicd-companion.service` の既存
`InteractionEngine` に処理させる。

keyboard HID report の最終合成 owner は core に固定する。companion は QMK 文法や未知文法を
単純な key press/release へ分解する責務だけを持ち、分解後の keyboard action は
`/tmp/logicd_core_ctrl.sock` の `key_event` command で core へ戻す。core は物理 hot path と
helper 由来 key event を同じ pressed state に重ねて 8 byte keyboard report を作る。
これにより、core が先行キーを保持している最中に companion が別 keyboard report を直接 broker へ送り、
先行キーが host から release/press されたように見える split-brain を避ける。
mouse / consumer / system side effect など core が keyboard report として合成しないものは、
引き続き companion 側の専用 runtime が処理する。

delegate action が押下中の間は、その後に押された通常キーも companion へ転送する。
これは `LT` / `MO` の layer context を core が部分的に解釈して壊さないための境界である。
companion が落ちている場合は該当 action だけ degraded / no-op になり、core が処理できる通常 `KC_*` hot path は維持する。

### 予定フェーズ

| phase | 内容 | 完了条件 |
| --- | --- | --- |
| M3a active-owner dry run | `hidloom-logicd-core.service` を active socket owner 候補として起動できる unit / rollback / preflight を固定する | reboot 前 preflight が `ok=true`、`logicd-core` が `/tmp/matrix_events.sock` と broker socket の owner 競合を起こさないことを read-only で判定できる |
| M3b active-basic A/B | Python `logicd` を止め、`logicd-core-rs -> hidloom-hidd` だけで basic key / modifier / US-sub split を実送信する | safe focused editor で basic key、modifier、US-sub key が届き、`hidd` counters に write error / dropped report が出ない |
| M3c boot owner rehearsal | core を boot-critical owner、Python `logicd` を disabled または delayed companion として 1 回 reboot 測定する | `logicd-core sockets listening`、`matrixd connected`、`input-to-HID ready` marker を取得し、Python owner baseline より明確に早い |
| M3d rollback proof | rollback helper で Python `logicd` owner へ戻し、restore helper で native owner へ戻す | 完了。`<keyboard-host>` で rollback は `logicd-core=inactive/disabled`、Python `logicd` / `matrixd` / `hidloom-hidd` active、restore は core / matrixd / companion active に戻ることを確認 |
| M4a companion split | Python control plane を `logicd-companion.service` として core 後に起動する | companion が落ちても core は入力維持。companion restart 後に status / reload / advanced action の最低限が復帰する |
| M4b control bridge | keymap reload、release_all、output target、status merge を core ctrl socket 経由に寄せる | HTTP / MCP / OLED status が core owner を表示し、basic remap reload が all-up safety 付きで反映される |
| M5 feature migration | deterministic layer action、tap-hold / tap dance / combo / macro / analog / BT などを feature 単位で core or companion owner に分類する | native core が `MO` / `TG` / `TO` / `DF` / `OSL` を持ち、timed / composite action は companion 委譲として明示される。既存 development suite を feature ごとに移せる |
| M6 promotion | `logicd-core-rs` を default boot owner として維持する | 複数 reboot sample、native live smoke、service restart stuck-key recovery、USB gadget restart、rollback path が通過する。物理 USB cable replug と focused host text visual soak は operator-only evidence として残す |

2026-06-20 の `<keyboard-host>` reboot で M3a/M3b/M3c と M4a の first slice は通過した。
`hidloom-logicd-core.service` / `matrixd.service` / `logicd-companion.service` が active、
旧 `logicd.service` は inactive / disabled、failed units は 0。
`matrixd connected to /tmp/matrix_events.sock` は `14.951s` で、直前の Python owner baseline `16.872s` から約 `1.92s` 早い。
2026-06-21 に M5 の deterministic layer action first slice として `MO` / `TG` / `TO` / `DF` / `OSL` を native core へ追加し、default keymap parity suite `65/65 matched` と実機 active binary status の layer state 出力を確認した。
同日に M3d rollback proof も通過し、Python owner rollback と native owner restore の両方で `ok=true` を確認した。
さらに native owner の 3 回 reboot sample では、core active `14.478s`-`15.153s`、matrixd connected `14.782s`-`15.484s`、failed units 0 を確認した。
同日の native owner live smoke では、active `/tmp/matrix_events.sock` へ `KC_LSFT` と overlapping `KC_A` / `KC_B` を注入し、core と hidd counters が進み、final pressed state が zero、`write_errors=0` / `dropped_reports=0` のまま戻ることを確認した。
`hidloom-usb-gadget.service` restart 後にも同じ live smoke が通過し、endpoint reopen の remote-safe proxy として記録した。
さらに action classification helper により default keymap は `native=100` / `delegated=29` /
`transparent=141` / `unsupported=0` として分類し、timed / composite action は companion 委譲へ固定した。
人間入力なしで進められる M6 材料は完了し、物理 USB cable replug も実施済み。残りは operator-only の focused host text visual soak と、再発時に `matrixd` / `logicd-core` / `hidloom-hidd` の三層 capture を取り `tools/hid_release_roll_analyzer.py` で hidd release roll 境界を確認する観測に限定する。
2026-06-21 の `<keyboard-host>` 追加実験では `hidloom-usb-gadget.service` を
`After=tmp.mount systemd-remount-fs.service systemd-modules-load.service` へ変更した。
`systemd-remount-fs.service` だけに寄せると `/tmp` tmpfs mount 前に broker socket が作られて隠れるため不可。
`tmp.mount` 待ち版は reboot sample で `usb-gadget finished=13.745s`、`hidd active=13.755s`、
`matrixd connected=15.183s`。synthetic `P02/R02` は `broker_frames_sent +2` / `hidd.frames_received +2`。

### 依存関係と unit sketch

active-basic 以降の boot-critical chain は次を目標にする。

```text
hidloom-usb-gadget.service
  -> hidloom-hidd.service
  -> hidloom-logicd-core.service
  -> matrixd.service
  -> hidloom-input-ready.target

early visual feedback:
  ledd.service (not input-critical)

delayed:
  logicd-companion.service
  hidloom-late-services.timer
```

unit ordering の意図:

- `hidloom-hidd.service` は gadget 後に起動し、broker socket と `/dev/hidg*` を持つ。
- `hidloom-logicd-core.service` は hidd 後に起動し、hidd が遅い場合も matrix socket を先に開いて broker reconnect する。
- `matrixd.service` は core の後に起動し、Python `logicd` を待たない。
- `hidloom-input-ready.target` は core が socket listen 済み、matrixd 接続済み、broker output 可能、という marker を journal/status に出せた時点の運用 target として扱う。
- companion は `After=hidloom-input-ready.target` または timer / path activation に寄せ、boot-critical path から外す。

### 実装時の守る線

- `/tmp/matrix_events.sock` の listener は常に 1 process だけにする。
- pressed state と HID report state は core owner にする。
- companion は core ctrl socket へ command を送るだけで、pressed state を直接 mutation しない。
- QMK 由来でも `MO` / `TG` / `TO` / `DF` / `OSL` のような deterministic layer action は core が持つ。
- `LT` / `MT` / `TT` / Tap Dance / macro / mouse / text / script action は core に再実装せず、delegate socket で companion へ渡す。
- keymap reload / companion restart / core stop では all-up safety を先に実行する。
- unsupported action は no-op + counter + status で見えるようにし、silent behavior drift を避ける。
- companion 不在時でも英数字、modifier、Enter、Backspace、US-sub route、emergency release は維持する。
- rollback は Python `logicd` owner に戻す helper、restore は native owner に戻す helper で 1 コマンド化し、実機 checklist に毎回結果を残す。

### 計測と合格ライン

各 active-owner rehearsal では `tools/boot_marker_baseline.py` と journal marker で次を記録する。

| marker | 合格ライン |
| --- | --- |
| USB HID gadget configured | 現状同等、15s 前後 |
| `hidloom-hidd` active / socket listening | 現状同等、15.2s 前後 |
| `logicd-core sockets listening` | Python `logicd` sockets `17.166s` より 1s 以上早いことを目標 |
| `matrixd connected` | core socket listen 直後に接続すること |
| `input-to-HID ready` | broker output 可能で null report / safe key report が通ること |
| companion ready | boot-critical 合否から外す。遅延しても USB key path を壊さないこと |

`<keyboard-host>` first reboot sample:

| marker | result |
| --- | --- |
| `hidloom-hidd` active | `14.494s` |
| `logicd-core` active | `14.708s` |
| `matrixd` active | `14.737s` |
| `matrixd connected` | `14.951s` |
| Python companion sockets ready | `17.253s` |

大きな regressions:

- core 起動後にキー入力が host へ届かない。
- core / hidd restart 後に stuck key が残る。
- companion crash が core 入力 path を巻き込む。
- rollback helper で Python owner へ戻せない。
- Vial / Raw HID bridge が `hidloom-hidd` owner と競合する。

## 段階移行

| phase | 内容 | 合格条件 |
| --- | --- | --- |
| M0-hidd | `hidloom-hidd` が既存 `usbd` broker frame を受けて `/dev/hidg0` / `/dev/hidg2` へ書く | 実装済み。temp endpoint parity と `<keyboard-host>` null-report smoke は通過。default owner promotion 前に boot marker / host-visible non-null smoke / USB replug / stuck-key recovery を確認する |
| M1-core-fixture | `logicd-core-rs` が keymap fixture から basic key report を生成 | 実装済み。`tools/hidloom_logicd_core/` の replay path と `script/test_logicd_core_rs_tool.py` で Python `HidState` / broker frame parity を確認する |
| M2-core-device-shadow | 実機で Python `logicd` と並走し、core は report preview だけ出す | 完了扱い。shadow service unit、recorded replay helper、broker capture helper、kind-aware preview/capture compare helper、isolated Python replay helper、default keymap parity suite、ctrl socket、`ExecStop` release guard、`jis_special_us_default` split route first slice を追加済み。`<keyboard-host>` で ARM64 build、shadow service synthetic replay、isolated Python replay comparison、latest 65 sequence parity suite (`matched=65`)、control smoke、service stop/restart stuck-key recovery が通過。unsupported action は 29 件として active owner 条件から除外する |
| M3-core-active-basic | basic key path だけ `logicd-core-rs -> hidloom-hidd` を active にし、Python `logicd` を delayed companion 化する | 実キー押下が host へ届き、emergency release が効く。`input-to-HID ready` が Python owner より早い |
| M4-control-bridge | Python companion が keymap reload / advanced action / status merge を core ctrl socket 経由で反映する | HTTP / Vial から basic remap が反映され、companion restart が入力 path を壊さない |
| M5-feature-parity | layer / interaction / output switch の互換範囲を増やす | 現行 development suite の対象を段階的に移す |
| M6-default-owner | `logicd-core-rs` を default boot owner に昇格する | 複数 reboot、native live smoke、USB gadget restart、stuck-key recovery、rollback が通過。物理 USB cable replug と focused host text visual soak は operator-only evidence |

## Decision matrix

各候補の比較:

| option | startup benefit | implementation risk | rollback | long-term fit | judgment |
| --- | --- | --- | --- | --- | --- |
| Extend `hidloom-usb-gadget-fast` into hidd | highest for USB path | high: oneshot + daemon mixed | medium | medium | later only |
| Separate `hidd-rs` | high | medium | good | high | first choice |
| Rewrite full `logicd` in Rust | high if complete | very high | poor | uncertain | avoid initially |
| Add `logicd-core-rs` with Python sidecar | high for key path | medium-high | good in shadow | high | second step |
| Optimize Python imports only | low-medium | low | good | medium | useful but not sufficient |
| Buildroot only | broad boot gain | high ops cost | good with separate SD | experimental | parallel ops experiment |

短期の推奨順:

1. `hidd-rs` separated daemon。
2. Python import profiling / obvious lazy import。
3. `logicd-core-rs` shadow mode。
4. active basic key path。
5. Buildroot M3 比較。

2026-06-20 時点では 1-3 は完了扱いであり、次の作業入口は M3 active-basic / systemd split である。

## 主な課題

### 1. owner 分裂

`logicd` を core と control に分けると、keymap、layer state、pressed state、output target の source of truth が割れやすい。

対策:

- pressed state と HID report state は `logicd-core-rs` の owner にする。
- Python control plane は desired config を送るだけにし、pressed state を直接変更しない。
- reload 時は core が clear/reconcile を行い、必要なら all keys up を送る。

### 2. 互換性の境界

現行 `logicd` は QMK/Vial 互換 keycode、wrapper action、interaction、macro を多く持つ。
M0 native core が中途半端に解釈すると、Python 版と違う挙動になる。

対策:

- M0 は basic key only と明記し、unsupported action は no-op + warning counter にする。
- `KC_TRNS` / `KC_NONE` / modifier / basic HID から始める。
- advanced action は Python control plane へ委譲する設計を別 phase にする。

### 3. JSON schema の固定

`keymap.json` は `_layout_def` と group 配列を持ち、HTTP / Vial / build generator と共有している。
Rust core が独自解釈を始めると schema drift が起きる。

対策:

- Rust 側に `serde` struct と strict validation を置く。
- Python `config_loader.keymap_json_to_layers()` と同じ fixture を使う cross-language tests を追加する。
- unknown top-level field は許容しても、core が読む field の型違いは起動失敗ではなく fallback/no-op を選ぶ。

### 4. IPC protocol の二重管理

既存 broker frame と将来 binary frame が混在すると、調査が難しくなる。

対策:

- M0 は既存 frame 互換に固定する。
- binary frame を入れる場合は version byte と magic を持つ。
- `hidd-rs` は protocol version を status に出す。

### 5. shutdown / restart safety

Python daemon 分割後、どの process が all keys up を送るか曖昧になると stuck key が起きる。

対策:

- `hidd-rs` は endpoint owner として shutdown 時に null report を送る。
- `logicd-core-rs` は pressed state owner として stop/reload 前に release sequence を送る。
- Python control plane restart では core pressed state を触らない。

### 6. Vial / Raw HID bridge

Raw HID / Vial bridge は 2026-06-20 に `hidloom-hidd` 側へ移した。
HID broker と Raw HID bridge の endpoint owner は同じ process になり、legacy `usbd.py` は通常 inactive。

現行の確認点:

- `/dev/hidg1` を `hidloom-hidd` が open し、`viald_events.sock` へ固定長 packet を中継する。
- `/dev/hidg1` を legacy `usbd` と二重 open しない。
- Vial protocol の解釈は引き続き `viald` が担当する。

### 7. Bluetooth / uinput output

現行 `logicd` は USB、BT、uinput、debug の output routing を持つ。
native core が USB だけ扱うと、output switch の意味が変わる。

対策:

- M0 は early USB keyboard path として扱い、BT / uinput は Python control plane 起動後に有効化する。
- output target state は core が持つが、BT sender は Python sidecar 経由にする案を別途検討する。
- `auto` mode の遷移は explicit event として status に出す。

### 8. 実機 rollback

native core が失敗するとキーボード入力そのものが失われる。

対策:

- systemd unit は `Environment=HIDLOOM_FAST_INPUT_CORE=1` の opt-in から始める。
- Python `logicd` / `usbd` fallback unit を残す。
- `tools/logicd_core_owner_recovery.py --apply --sudo` で Python `logicd` owner へ戻す。
- physical key または SSH から fallback へ戻す手順を docs に置く。
- 初期 smoke は SSH 到達可能な `<keyboard-host>` でだけ行う。

### 9. Build / install complexity

Rust toolchain を Pi 上で持つか、cross build するかを決める必要がある。

対策:

- repo には source と Makefile / cargo wrapper を置く。
- 実機 install は prebuilt binary を使うか、Pi 上 build を許可するかを profile で分ける。
- `README` の rsync 注意と同じく、x86_64 binary を Pi へ送らない guard を追加する。

### 10. 測定の誤認

systemd active と実際の socket/listen/usable keyboard は一致しない。

対策:

- `journalctl -b -o short-monotonic` の marker を主指標にする。
- `tools/boot_marker_baseline.py` は boot-critical socket snapshot と
  `hidd-status.json` / `logicd-core-status.json` も含める。
- `systemd-analyze` は背景情報に留める。
- `input-to-HID ready` と `usable keyboard` を合格条件にする。

### 11. matrix event duplication

shadow mode で Python `logicd` と Rust core の両方へ matrix event を流す必要がある。
`matrixd` が一つの Unix socket にしか送れない場合、実機での同時比較が難しい。

対策:

- M2 では matrixd を変更せず、`tools/logicd_core_shadow_replay.py` による recorded event replay から始める。
- 実機 shadow が必要になった時点で、tee helper または matrixd multi-client output を追加する。
- multi-client 化する場合も scan loop を遅延させないよう non-blocking queue にする。

### 12. timing-dependent actions

Tap-hold、tap dance、oneshot、combo、Morse などは timing と cancellation が重要で、
core と Python に分割すると境界が難しい。

対策:

- M0/M3 active basic では timing-dependent action を unsupported にする。
- M5 で移す場合は feature 単位で owner を決める。
- 一つの physical key sequence を core と Python が同時に解釈しない。

### 13. host LED output report

現行 `logicd` は `/dev/hidg0` の host LED output report を読み、Caps/Kana などを ledd へ反映する。
endpoint owner を `hidd-rs` に移すと、この read path も owner を決め直す必要がある。

対策:

- `/dev/hidg0` fd owner を `hidd-rs` に寄せるなら、host LED output report read も `hidd-rs` が受ける。
- `hidd-rs` は LED state event を core/control へ publish する。
- Python sidecar は LED state を read-only event として表示・通知に使う。

この event は Kana LED bit の Windows JIS main smoke と関係するため、`hidd-rs` parity test に
host LED output report decode を含める。

### 14. permissions and privilege

`/dev/hidg*`、uinput、real-time scheduling、GPIO は root 権限を要求しがちである。
native daemon を増やすと privilege surface が増える。

対策:

- `hidd-rs` は root または `input` group で `/dev/hidg*` だけを持つ。
- `logicd-core-rs` は matrix socket と hidd socket だけなら root 不要を目指す。
- `matrixd` の realtime / GPIO privilege は既存通り分離する。
- systemd hardening は M1 以降で `NoNewPrivileges`, `ProtectSystem`, `PrivateTmp` を段階適用する。

### 15. observability loss

Python は debug print や JSON dump が容易だが、native daemon は内部状態が見えにくくなりやすい。

対策:

- M0 から status socket/file と counters を必須にする。
- journal marker を明示する。
- `tools/matrixd_diagnostics_snapshot.py` か MCP read-only tools に native core summary を追加する。
- panic/backtrace 前提ではなく structured error counter を置く。

### 16. release compatibility

既存 docs、install script、systemd unit、real-device smoke が `logicd` / `usbd` 名を前提にしている。
daemon 名を変えると運用文書と検査が割れる。

対策:

- `hidloom-hidd.service` を既定 owner とし、`usbd.service` は rollback / A/B 診断用に残す。
- HTTP status / hidd status file で `hidloom-hidd` owner、endpoint open、write error を確認する。
- README / architecture docs は `logicd-core-rs -> hidloom-hidd` を現行の boot-critical path として扱う。

### 17. Socket permissions and client identity

既存 broker socket は `/tmp/usbd_hid_reports.sock` を mode `0666` にしている。
native daemon でも同じにすると移行は楽だが、任意 local process が HID report を送れる。

対策:

- M0 parity では既存 mode を維持して挙動差を減らす。
- M1 以降で group owner / mode `0660` / peer credential check を検討する。
- status に socket mode / uid / gid を出す。
- security hardening は functional parity 後に別 phase とする。

### 18. Report descriptor profile drift

`hidd-rs` が endpoint / Report ID を固定で仮定すると、USB descriptor profile 変更に弱くなる。
現在は `/dev/hidg0` multi-report、`/dev/hidg2` US sub keyboard が前提だが、Windows IME custom HID や
keyboard-only test profile では変わり得る。

対策:

- M0 は current default profile only と明記する。
- `hidd-rs` status に assumed profile を出す。
- profile 変更時は shell/Python fallback へ戻す。
- descriptor parser を native に入れるのは M0 では避ける。

### 19. Panic / crash behavior

Rust daemon でも panic や fatal error はあり得る。
systemd restart だけに頼ると、押下中の key が残る可能性がある。

対策:

- panic 時に top-level cleanup ができるか検討する。
- signal handler は最小限にし、shutdown flag + best-effort null report に寄せる。
- systemd `Restart=on-failure` 時も start 前に hidd/core が null report を送る。
- watchdog は初期無効。安定後に watchdog readiness を検討する。

## Open questions

| question | decision needed before |
| --- | --- |
| `hidd-rs` が `/dev/hidg1` Raw HID も持つか | 完了。2026-06-20 に `hidloom-hidd` Raw HID bridge を追加 |
| existing broker frame を永続 contract にするか、M1 で binary frame へ移るか | M0-hidd 完了後 |
| M0 core で `MO(n)` を入れるか basic only にするか | M1-core-fixture 前 |
| shadow mode の event source を replay にするか実機 tee にするか | M2-core-device-shadow 前 |
| output target `auto` を core owner にするか Python owner にするか | M3-core-active-basic 前 |
| host LED output report を hidd event として publish する形式 | hidd が `/dev/hidg0` read owner になる前 |
| Rust build を Pi native にするか cross build にするか | install script 追加前 |
| `ctrl_events.sock` owner をいつ core に移すか | M4-control-bridge 前 |
| broker socket permission を parity 優先にするか hardening 優先にするか | M0-hidd unit 追加前 |
| descriptor profile を fixed default として割り切る期間 | M0-hidd 実機 smoke 前 |
| analog stick / SPID / sendkey を core へ bridge する順序 | M4-control-bridge 前 |

## M0-hidd implementation checklist

- `daemon/hidd-rs/` or `daemon/hidd/` の置き場を決める。
- [x] broker protocol fixture を Python `usbd` encoder から再利用する。
- [x] Rust frame decoder を実装する。
- [x] endpoint writer abstraction を temp file test で確認する。
- [x] `/tmp/usbd_hid_reports.sock` listen を実装する。
- [x] mouse accumulator parity test を追加する。
- [x] keyboard pacer / dedup / release merge parity test を追加する。
- [x] HID write retry timeout を実装する。
- [x] status JSON を出す。
- [x] systemd unit は disabled/opt-in で追加する。
- [x] `<keyboard-host>` で manual start、broker ready、safe null-report smoke を取る。
- [x] boot marker helper に `hidloom-logicd-core.service`、boot-critical socket snapshot、
  `hidd-status.json` / `logicd-core-status.json` snapshot を追加する。
- [x] Python `logicd` owner へ戻す rollback helper を追加し、`<keyboard-host>` で
  `--apply --sudo` smoke を取る。
- [x] host LED output report read/decode parity test を追加する。`script/test_logicd_host_led_reader.py`
  は Report ID 付き / なし payload の decode を固定し、`script/test_logicd_host_led_output.py`
  は `HOST_LED` ctrl message と overlay state mapping を固定する。2026-06-21 に
  `<keyboard-host>` でも両方通過。
- [x] `USBD_HID_REPORT_SOCKET_ENABLED=1` 相当を hidd owner に切り替える drop-in または service profile を用意する。
  `system/systemd/hidloom-hidd.service` は `/tmp/usbd_hid_reports.sock` を
  `USBD_HID_REPORT_SOCKET` として持ち、`Conflicts=usbd.service` で Python owner と同時 bind しない。
  2026-06-21 の `<keyboard-host>` でも socket listening、`hidg0` / `hidg1` / `hidg2` open、
  `write_errors=0` / `dropped_reports=0` を確認済み。
- [ ] focused host text visual soak、keyboard / mouse / consumer の operator-visible smoke を取る。physical USB cable replug は実施済みで、今後は関連変更時の regression として扱う。
- [x] reboot marker を取り、`usbd` Python 比で socket ready が短くなるか確認する。2026-06-21 の
  native owner 3 回 reboot sample で core active `14.478s`-`15.153s`、
  matrixd connected `14.782s`-`15.484s`、failed units 0 を確認済み。

## M1/M2 logicd-core implementation checklist

- [x] Python `config_loader.keymap_json_to_layers()` と同じ keymap JSON flattening を Rust に実装する。
- [x] Rust keymap loader の fixture / replay parity test を追加する。
- [x] basic HID keycode table の source of truth は `config/default/keycodes.json` にする。
- [x] matrix event parser を実装する。
- [x] report state machine を実装する。
- [x] unsupported action counter を実装する。
- auxiliary input source は M0 対象外であることを status に出す。
- [x] preview-only shadow output を実装する。
- [x] recorded matrix event replay test を追加する。
- real-device shadow は tee が必要になるまで保留する。

## 検証入口

初期実装時に追加すべき検証:

- `hidd-rs` frame codec fixture test。
- Python `usbd` broker と `hidd-rs` の output byte parity test。
- `logicd-core-rs` keymap loader と Python `config_loader.keymap_json_to_layers()` の parity test。
- stuck key prevention test: reload / stop / endpoint disappear で null report が送られる。
- unsupported action policy test。
- real-device reboot marker:
  - `hidg ready`
  - `hidd socket listening`
  - `logicd-core socket listening`
  - `matrixd connected`
  - `input-to-HID ready`
  - `usable keyboard`

## 判断

現時点の既定構成は、`hidloom-hidd` が既存 `usbd` broker の boot-critical 部分と Raw HID bridge を置き換え、
`logicd-core-rs` が matrix hot path の active owner になる構成である。

`hidloom-usb-gadget-fast` を hidd に拡張して完全一体化する案は最速候補だが、
oneshot setup と常駐 endpoint owner の責務が混ざるため、初期実装では採用しない。
将来、`hidd-rs` が安定し、さらに数百 ms を詰める必要が出た場合に、
`hidd-rs` が gadget setup fallback を呼ぶ、または一体型 profile を追加する形で再検討する。
