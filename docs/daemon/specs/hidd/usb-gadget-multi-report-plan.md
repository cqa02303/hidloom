# USB gadget multi-report endpoint consolidation plan

作成日: 2026-06-11

この文書は、Raspberry Pi Zero 2 W の USB gadget endpoint 数制約を避けつつ、
Windows で JIS main keyboard と US sub keyboard を同時に扱うための段階計画です。

## Goal

- Vial Raw HID bridge を壊さずに endpoint を空ける。
- 既存の US keyboard / mouse / consumer control を 1 つの HID function にまとめる。
- 空いた HID function に sub keyboard を追加し、通常キーと JIS 固有キーの route を分ける。
- Windows host で JIS main keyboard と US sub keyboard を別 device instance として扱えるか確認する。
- USB report の endpoint / Report ID / descriptor profile 差分を compatible broker owner
  (`hidloom-hidd` current owner、legacy `usbd` rollback owner) に集約し、
  `logicd` や手動 smoke helper が `/dev/hidg*` の実 report 形状を直接知る範囲を減らす。

## Current layout

現行の `setup_usb_gadget.sh` は 4 つの HID gadget function を作るが、
通常 keyboard / mouse / consumer control は `/dev/hidg0` の multi-report HID function に集約する。

| device | role | report |
| --- | --- | --- |
| `/dev/hidg0` | keyboard / mouse / consumer control multi-report | Report ID 1/2/3 |
| `/dev/hidg1` | Raw HID / Vial | 32-byte Raw HID report |
| `/dev/hidg2` | US sub keyboard endpoint | 8-byte boot keyboard report |
| `/dev/hidg3` | unused / reserved | - |

`/dev/hidg1` は Vial Raw HID / `hidloom-hidd` bridge の安定性に直結するため、統合対象にしない。

## Target phase 1

Status: implemented in `setup_usb_gadget.sh`, `daemon/logicd/config_runtime.py`, and default `config/default/config.json`.

まず keyboard / mouse / consumer control を `/dev/hidg0` の multi-report HID function へ統合する。
この段階では US sub keyboard はまだ追加せず、既存機能の互換性だけを確認する。

| device | role |
| --- | --- |
| `/dev/hidg0` | US keyboard + mouse + consumer control multi-report |
| `/dev/hidg1` | Raw HID / Vial |
| `/dev/hidg2` | US sub keyboard endpoint |
| `/dev/hidg3` | unused / reserved |

Report ID 案:

| Report ID | direction | payload | role |
| ---: | --- | --- | --- |
| 1 | IN | 8 bytes | keyboard |
| 1 | OUT | 1 byte LED bits | keyboard LED Output Report |
| 2 | IN | 4 bytes | relative mouse |
| 3 | IN | 2 bytes | consumer control |

実装時の影響:

- keyboard writer は `8 bytes` ではなく `0x01 + 8 bytes` を `/dev/hidg0` へ書く。
- mouse writer は `0x02 + 4 bytes` を `/dev/hidg0` へ書く。
- consumer writer は `0x03 + 2 bytes` を `/dev/hidg0` へ書く。
- host LED reader は従来の `led_byte` と `0x01, led_byte` の両方を扱えるようにする。
- Vial Raw HID path `/dev/hidg1` は変更しない。

2026-06-11 の Windows 実機確認で、multi-report 化後に旧 8-byte keyboard payload を
`/dev/hidg0` へ直接書く手動 helper が残っていると、host 側で異常な key input として見えることが分かった。
これは個別の helper だけの問題ではなく、USB report の整形責務が `logicd`、helper、descriptor 文書へ
散っていることが原因。

そのため Phase 1.5 として、USB report broker を legacy `usbd` に追加した。
2026-06-20 以降の既定運用では、同じ broker frame 互換を `hidloom-hidd` が引き継ぐ。

## Target phase 1.5: compatible USB report broker

Status: implemented. The historical local pre-device slice introduced the broker socket in Python
`usbd`; current live output uses `logicd-core-rs -> hidloom-outputd -> hidloom-hidd` for the boot-critical USB path.

`logicd-core-rs` / `logicd-companion` は USB descriptor の実 report 形状を知らず、canonical payload だけを broker socket に送る。
`hidloom-hidd` / legacy `usbd` は現在の USB gadget profile を知り、Report ID 付与、endpoint 選択、write retry、
送信 packet logging を一箇所で扱う。

```text
logicd-core-rs / logicd-companion
  keyboard payload 8 bytes
  mouse payload 4 bytes
  consumer payload 2 bytes
        |
        v
compatible broker socket
        |
        v
USB profile adapter
  current phase 1: /dev/hidg0 report ID 1/2/3
  current phase 2: /dev/hidg0 JIS main + /dev/hidg2 US sub keyboard
```

責務分離:

| module | 持つ責務 | 持たない責務 |
| --- | --- | --- |
| `logicd-core-rs` / `logicd-companion` | keymap / macro / layer / canonical HID payload 生成 | Report ID、USB endpoint、descriptor profile 判定 |
| `hidloom-hidd` / legacy `usbd` | `/dev/hidg*` owner、Report ID 付与、profile adapter、USB report log | keymap / macro / IME 意味解釈 |
| helper scripts | broker socket へ smoke request を送る | `/dev/hidg0` direct write を標準手順にしない |

初期 local socket は datagram とし、1 datagram = 1 USB report request にする。

採用した first-slice frame:

```text
byte 0..3   magic: CQAU
byte 4      version: 0x01
byte 5      kind: 0x01 keyboard, 0x02 mouse, 0x03 consumer, 0x04 us_sub_keyboard
byte 6      payload length
byte 7      flags/reserved
byte 8..31  payload
byte 32..62 reserved zero
byte 63     xor checksum over byte 0..62
```

canonical payload:

| kind | payload length | payload |
| ---: | ---: | --- |
| `0x01` keyboard | 8 | modifier/reserved/key1..key6 |
| `0x02` mouse | 4 | buttons/x/y/wheel |
| `0x03` consumer | 2 | little-endian Consumer usage |
| `0x04` us_sub_keyboard | 8 | US sub keyboard payload |

Current broker state:

1. `hidloom-hidd` が native HID gadget owner として `/tmp/usbd_hid_reports.sock` 互換 frame を受け取り、
   USB report request encode/decode と current multi-report profile adapter を持つ。
2. current multi-report profile adapter は `kind=keyboard` を `0x01 + payload`、
   `kind=mouse` を `0x02 + payload`、`kind=consumer` を `0x03 + payload`、
   `kind=us_sub_keyboard` を `/dev/hidg2` の 8-byte payload に変換する。
3. `logicd-core-rs -> hidloom-outputd -> hidloom-hidd` が既定 live USB path。`uinput` target では `hidloom-outputd -> hidloom-uidd` へ配送する。legacy Python `usbd` broker は rollback 互換として扱う。
4. `script/send_standard_keyboard_report.py` は `--transport auto|socket|direct` を持ち、broker socket が
   ある場合は canonical payload を送る。診断用 direct path は `--transport direct --device /dev/hidg0`
   として残す。
5. `hidloom-hidd` / `logicd-core-rs` の packet trace は native owner の診断ログで取得する。legacy
   `USBD_HID_REPORT_*` / `LOGICD_USBD_*` opt-in 手順は通常運用から外す。

Acceptance:

- direct writer と broker adapter の最終 USB bytes が test で一致する。
- helper と native live path が旧 8-byte payload を `/dev/hidg0` へ direct write しない。
- `hidloom-hidd` / `logicd-core-rs` log で、送った report の size / hex が追跡できる。
- live USB 経路は `logicd-core-rs -> hidloom-outputd -> hidloom-hidd` に統一し、legacy `usbd` は rollback 時だけ使う。

## Target phase 1.6: mouse report scheduler at transport outlet

Status: first USB outlet slice and local regression coverage are implemented.
When the broker backend is enabled, analog joystick motion, mouse key repeat,
and SPID mouse mode now reach the active broker owner as `kind=mouse` canonical reports.
Broker-disabled direct writer and non-USB routing policy is also fixed in tests:
direct USB keeps immediate Report ID-prefixed writes, auto BT forwards mouse
reports to `btd`, and auto uinput drops mouse reports because no uinput mouse
backend exists yet. Remaining checks are real-device cursor latency, drag /
release timing, drop behavior, and a future `btd` scheduler if Bluetooth mouse
coalescing becomes necessary.

Mouse motion can arrive faster than USB host polling or gadget writes can drain.
This should not create an unbounded queue in `logicd`, nor should `logicd` need
USB endpoint backpressure knowledge.  The transport daemon closest to the output
owns coalescing.

USB policy:

- `logicd-core-rs` / `logicd-companion` send canonical mouse reports through the HID report broker.
- the active broker owner coalesces only `kind=mouse`.
- keyboard, consumer, and US sub keyboard reports bypass coalescing and remain immediate.
- button transitions flush pending motion first and then send the new button state
  immediately, so drag / release latency is not hidden behind motion batching.
- dx / dy / wheel are accumulated and emitted at `USBD_MOUSE_REPORT_HZ` cadence.
  Values beyond signed HID byte range are emitted over later flushes instead of
  growing an output queue.

Future BT policy:

- Bluetooth should follow the same boundary in `btd` or an equivalent BT HID
  transport daemon.
- `logicd` remains responsible for canonical input semantics only.
- USB-specific scheduling in `usbd` must not become the shared keyboard runtime
  queue for BT / uinput.
- Until a uinput mouse backend exists, auto fallback to uinput intentionally
  drops mouse reports instead of leaking them back to USB gadget output.

## Target phase 2

Phase 1 の Windows / Linux / Vial / mouse / media key / host LED smoke が通ってから、
空いた HID function に JP thin keyboard を追加する。

| device | role |
| --- | --- |
| `/dev/hidg0` | JIS main keyboard + mouse + consumer control multi-report |
| `/dev/hidg1` | Raw HID / Vial |
| `/dev/hidg2` | US sub keyboard |
| `/dev/hidg3` | unused / reserved |

2026-06-13 の結論では、Windows custom INF で main `/dev/hidg0` 側を
JIS 106/109、sub `/dev/hidg2` 側を US 101/102 として bind する。
`logicd` route `jis_special_us_default` は、通常キーを US sub へ、JIS 固有キーと
変換 / 無変換を JIS main へ送る。`KC_ZKHK` は `KC_GRV` と同じ usage `0x35`
を送るが、内部 routing action として JIS main 側へ明示的に送る。

- `KC_ZKHK` / `KC_ZENKAKU_HANKAKU`
- `KC_RO`
- `KC_JYEN`
- `KC_HENKAN` / `KC_MUHENKAN`
- `KC_INT6`-`KC_INT9`

`KC_KANA` は Kana Lock / Kana LED との対応を優先して JIS main に送る。
`KC_LANG1` / `KC_LANG2` は ImeOn/ImeOff として US sub に残す。

2026-06-15 update: `jis_special_us_default` では、modifier を押しながら JIS main 側の
`KC_RO` / `KC_JYEN` / `KC_KANA` / `KC_HENKAN` / `KC_MUHENKAN` などを操作した時に、
JIS main 側へも modifier-only release report を送る。Windows は main keyboard と US sub
keyboard を別 device instance として扱うため、JIS key press だけを main に送り、その後の
modifier-only report を US sub に戻すと、main 側の JIS key release が遅れて repeat / stuck
key 状態に見えることがある。通常キーは引き続き US sub にだけ流す。

## Why not multi-report US/JP in one interface

Report ID は同一 HID interface 内の report 種別を分ける仕組みであり、
host OS に別々の物理 keyboard として layout override を持たせる仕組みではない。
Windows で US / JP layout override を分けたい場合は、別 HID keyboard interface として見せる方が本命。

そのため、JIS main keyboard と US sub keyboard は同じ `/dev/hidg0` multi-report には入れず、
Phase 2 で別 HID function / interface として追加する。

## Acceptance gates

Phase 1:

- Windows / Linux で `/dev/hidg0` が keyboard / mouse / consumer control として認識される。
- keyboard press/release と host LED Output Report が動く。
- mouse movement / button / wheel が動く。
- consumer media key が動く。
- Vial desktop / Vial web / Raw HID bridge が `/dev/hidg1` のまま動く。
- unplug / replug、logicd restart、emergency release で stuck key / stuck button が残らない。

Phase 2:

- Windows が main keyboard と sub keyboard を別 device instance として扱えることを確認済み。
- Custom INF で main `MI_00&Col01` は JIS 106/109、sub `MI_02` は US 101/102 として bind 済み。
- main へ送った記号 usage は JIS として、sub へ送った同じ usage は US として解釈されることを実入力で確認済み。
- `jis_special_us_default` route により、通常 typing は US sub、JIS 固有キーと変換 / 無変換は JIS main へ分離済み。
- `KC_GRV` と同じ usage `0x35` を使う全角 / 半角は、`KC_ZKHK` 内部 action で JIS main へ送れる。
- Vial Raw HID bridge と通常入力に副作用がない。

## Next task order

1. Phase 1.5 USB report broker first slice を入れる。
   - `usbd` に canonical report request encode/decode と current multi-report adapter を追加する。
   - `script/send_standard_keyboard_report.py` の direct `/dev/hidg0` 書き込みを診断 path へ降格する。
   - `logicd` gadget backend の live 切替は、broker adapter と logging test が揃うまで行わない。
2. Phase 1 real-device smoke を消化する。
   - Windows / Linux で `/dev/hidg0` の keyboard / mouse / consumer control が認識されることを確認する。
   - keyboard press / release、host LED Output Report、mouse movement / button / wheel、consumer media key を確認する。
   - Vial desktop / Vial web / Raw HID bridge が `/dev/hidg1` のまま動くことを確認する。
   - unplug / replug、`logicd` restart、emergency release で stuck key / stuck button が残らないことを確認する。
3. `/dev/hidg2` に sub keyboard を opt-in で追加する。完了済み。
   - default gadget は Phase 1 の安定構成から変えない。
   - 有効化は config または environment variable の gate を通す。
   - Windows custom INF 構成では US sub keyboard として使う。
4. sub keyboard の descriptor と static regression を追加する。完了済み。
   - `setup_usb_gadget.sh` が default では `hid.usb2` を作らないことを固定する。
   - opt-in 時だけ `hid.usb2` keyboard を作り、`hid.usb0` / `hid.usb1` を壊さないことを固定する。
   - `script/test_usb_gadget_descriptor.py` に sub interface の report descriptor / symlink / config string の検査を追加する。
5. Windows per-interface recognition を実機で確認する。完了済み。
   - Device Manager で main keyboard と sub keyboard が別 device instance / `MI_xx` として見えるか確認する。
   - Custom INF で main を JIS、sub を US として bind できることを確認する。
   - US sub layout と Vial Raw HID bridge に副作用がないことを確認する。
6. Windows runbook を整備する。完了済み。
   - Device Manager で見る場所、custom INF の入れ方、戻し方、確認キー、失敗時の切り分けを記録する。
   - 手動 registry override は失敗履歴として残し、custom INF route を本命にする。
7. `logicd` の JIS main / US sub 出力経路を追加する。完了済み。
   - 通常 typing は `kind=us_sub_keyboard` として US sub `/dev/hidg2` へ送る。
   - `KC_RO` / `KC_JYEN` / `KC_HENKAN` / `KC_MUHENKAN` / `KC_INT6`-`KC_INT9`
     は main keyboard `kind=keyboard` として JIS main `/dev/hidg0` へ送る。
   - `KC_ZKHK` は usage 53 のまま JIS main `/dev/hidg0` へ送る内部 routing action として扱う。
   - `KC_KANA` は JIS main `/dev/hidg0` へ送る。`KC_LANG1` / `KC_LANG2` は layout 判定ではなく
     US sub で扱える ImeOn/ImeOff control として維持する。
8. BLE 側の扱いは別途決める。
   - BLE GATT の `LANG1` / `LANG2` は維持する。
   - BLE で JP physical layout override 相当を追うかは、USB custom INF route とは別件として判断する。

## Implementation guard

- Raw HID / Vial endpoint は統合しない。
- Phase 1 と Phase 2 を同時に実装しない。
- sub keyboard の role は config route で明示し、Windows INF binding と逆向きにしない。
- USB report profile 変換を `logicd` と helper scripts へ増やさない。
- `/dev/hidg0` direct write helper は診断用として明示し、通常 smoke は `usbd` broker 経由にする。
- Windows custom INF の実機確認なしに、US / JP 同居を完了扱いしない。
- host OS の keyboard layout を gadget 側から強制変更する前提にしない。
