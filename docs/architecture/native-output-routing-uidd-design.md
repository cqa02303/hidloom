# Native Output Routing And uidd Design

作成日: 2026-06-22

更新日: 2026-06-25

## 現在の実装状態

M0 は実装済みです。現行 hot path は
`matrixd -> logicd-core-rs -> hidloom-outputd -> hidloom-hidd` で、`KC_CONSOLE` /
`KC_USB` / `KC_CONNAUTO` は `logicd-companion` から `hidloom-outputd` の
control socket へ送られます。`uinput` target では
`hidloom-outputd -> hidloom-uidd -> /dev/uinput` へ配送し、`bt` target では
`hidloom-outputd -> btd` へ broker frame を `btd1` frame に変換して配送します。

`<keyboard-host>` では `auto` / `usb` / `uinput` target 切り替え、USB target forwarding、
uinput target の `hidloom-uidd` event 生成、target switch / `release_all` regression、
status schema regression まで確認済みです。
BT target は 2026-06-25 に local regression を追加済みで、実機 smoke は次回同期後に確認します。

## 背景

native owner 初期構成では、物理キーの boot-critical path は
`matrixd -> logicd-core-rs -> hidloom-hidd` でした。
`logicd-companion` は `LOGICD_OUTPUTS=debug` で起動し、通常 keyboard report を
USB broker へ直接 fan-out しません。

このため、旧 Python `logicd` owner 時代に有効だった
`KC_CONSOLE` / `KC_USB` / `KC_CONNAUTO` の output switch は、
native owner では companion 内の古い OutputRouter だけを切り替える状態になります。
通常キーの HID report は当時 `logicd-core-rs` から `hidloom-hidd` へ流れていたため、
companion 側だけを `uinput` にしても実出力は切り替わりません。

## 方針

`logicd-core-rs` に `/dev/uinput`、ioctl、Linux input keycode 差分変換を直接持たせず、
`hidloom-hidd` と同格の `uidd` を追加します。

責務境界:

| Process | 責務 |
| --- | --- |
| `logicd-core-rs` | matrix event から action / layer / HID keyboard report を生成する。出力先固有の device owner にはならない |
| `hidloom-outputd` | 現在の output target を保持し、core の broker frame を `hidloom-hidd` / `hidloom-uidd` / 将来 `btd` へ配送する |
| `hidloom-hidd` | USB gadget HID endpoint owner。`/dev/hidg0` / `/dev/hidg1` / `/dev/hidg2` と Raw HID bridge を担当する |
| `hidloom-uidd` | Pi local console 用 uinput device owner。keyboard HID report を Linux input event へ変換して `/dev/uinput` へ書く |
| `logicd-companion` | output switch action の control plane、OLED/LED への mode 表示、BT 準備、advanced action delegation を担当する |

## 現行 runtime flow

```text
matrixd ─► logicd-core-rs ─► hidloom-outputd ─┬─► hidloom-hidd ─► /dev/hidg0 /dev/hidg2
                                           ├─► hidloom-uidd ─► /dev/uinput
                                           └─► btd ─► BLE HID host

logicd-companion ─ ctrl/output target ─► hidloom-outputd
logicd-companion ─ mode notification ─► ledd / i2cd / httpd status
```

現行実装では `btd` が BLE HID transport owner のままです。`logicd-companion` は
`KC_BT` / `hidloom-ctrl output bt` を受けた時に `hidloom-outputd` の target を `bt` へ切り替え、
通常キーの hot path は core 由来 frame を `btd` へ送ります。

## output target semantics

| Action | 目標挙動 |
| --- | --- |
| `KC_USB` | target を `usb` に固定し、keyboard report を `hidloom-hidd` へ送る |
| `KC_CONSOLE` | target を `uinput` に固定し、keyboard report を `uidd` へ送る |
| `KC_CONNAUTO` | USB gadget ready なら `usb`、ready でなければ `uinput` を選ぶ。BT fallback は従来通り明示 opt-in のままにする |
| `KC_BT` | target を `bt` に固定し、keyboard / US-sub keyboard / mouse / consumer frame を `btd` へ送る |

切り替え時は stuck key を避けるため、旧 target と新 target の両方へ null keyboard report
または release-all 相当を送ってから target を変更します。
特に `usb -> uinput` では host 側と Pi local console 側のどちらにも押下状態を残さないことを優先します。

## `hidloom-uidd` first slice

`hidloom-uidd` は Python 版 `daemon/logicd/uinput.py` の責務を native daemon として切り出します。

最小機能:

- `/dev/uinput` を open し、keyboard 用 virtual device を作る
- `config/default/keycodes.json` または runtime keycodes から HID usage -> Linux keycode mapping を読む
- modifier byte と 6-key slots の差分から EV_KEY press/release を発行する
- EV_SYN を各差分の後に送る
- repeat delay / repeat period を `settings.uinput` 互換で設定する
- status JSON に device open、last error、frames received、events written、dropped reports を出す
- systemd unit は `hidloom-uidd.service` とし、`uinput` kernel module と `/dev/uinput` の存在を前提にする

非目標:

- `uidd` は keymap / layer / macro を解釈しない
- `uidd` は matrix event を読まない
- `uidd` は Raw HID / Vial bridge を持たない
- `uidd` は USB endpoint fallback を持たない

## router placement

first slice では、既存 `/tmp/usbd_hid_reports.sock` 互換を壊さないため、
router は `logicd-core-rs` と device owners の間に置く案を優先します。

候補:

1. `hidloom-outputd` を新設し、`logicd-core-rs` は `/tmp/hidloom_output_reports.sock` へ送る。
   `hidloom-outputd` が `/tmp/usbd_hid_reports.sock` の `hidloom-hidd` と `uidd` socket へ配送する。
2. `hidloom-hidd` を broker owner のまま拡張し、USB 書き込みと uidd 転送の router も担当する。

現時点の推奨は 1 です。
`hidloom-hidd` は USB endpoint owner と Raw HID bridge という十分に重い責務を既に持つため、
出力 target 状態と uinput 配送まで混ぜると再分離しづらくなります。

ただし migration の first implementation では、systemd と socket 名の変更範囲を小さくするため、
`hidloom-hidd` 互換 broker frame をそのまま `hidloom-outputd` が受ける形にします。
`hidloom-hidd` は router から届く USB 宛 frame だけを受ける device owner へ移します。

## IPC sketch

Report frame は既存 compatible broker frame を再利用します。

```text
logicd-core-rs -> /tmp/hidloom_output_reports.sock -> hidloom-outputd
hidloom-outputd    -> /tmp/usbd_hid_reports.sock   -> hidloom-hidd
hidloom-outputd    -> /tmp/uidd_reports.sock       -> uidd
hidloom-outputd    -> /tmp/btd_events.sock         -> btd
```

Control は JSON Lines を使います。

```json
{"t":"set_output_target","target":"uinput"}
{"t":"set_output_target","target":"usb"}
{"t":"set_output_target","target":"bt"}
{"t":"set_output_target","target":"auto"}
{"t":"status"}
{"t":"release_all"}
```

M0 では `hidloom-outputd` がこの socket / control schema を実装し、`usb` target では
既存 `hidloom-hidd` socket へ frame をそのまま転送し、`uinput` target では
`/tmp/uidd_reports.sock` へ転送し、`bt` target では `/tmp/btd_events.sock` へ
`btd1` framed keyboard / mouse / consumer report として転送します。
target 変更時は old/new target の両方へ
keyboard / US-sub keyboard の null frame を送って stuck key を避けます。
`<keyboard-host>` の A/B smoke で `logicd-core-rs -> hidloom-outputd -> hidloom-hidd`
の `usb` target forwarding が `write_errors=0` / `dropped_reports=0` で通過したため、
systemd 既定は `/tmp/hidloom_output_reports.sock` へ切り替えます。

`logicd-companion` は `KC_CONSOLE` / `KC_USB` / `KC_CONNAUTO` / `KC_BT` を受けたら、
旧 Python OutputRouter ではなく native output router の control socket へ送ります。
router が unavailable の場合は OLED/HTTP status に warning を出し、
silent success にはしません。

## Migration status

1. 現状明文化:
   native owner 初期構成では output switch action が companion の旧 OutputRouter だけを切り替え、
   実出力切り替えとしては未完了だったことを docs / TODO に記録した。
2. `uidd` M0:
   Python `uinput.py` と同じ HID report 差分変換を native daemon として実装し、
   fixture report から EV_KEY sequence を検証する単体テストを追加済み。
3. router M0:
   `usb` 固定 target で `logicd-core-rs -> hidloom-outputd -> hidloom-hidd` に同じ frame が通ることを確認済み。
4. `uinput` target:
   `KC_CONSOLE` または ctrl command で target を `uinput` にし、USB へ出さず `uidd` へ配送する経路を確認済み。
5. switch safety:
   target 変更時の release-all、旧 target null report、新 target clean start を regression 化済み。
6. `bt` target:
   `hidloom-outputd` が core broker frame を `btd1` protocol へ変換し、keyboard / US-sub keyboard / mouse / consumer を
   `/tmp/btd_events.sock` へ送る local regression を追加済み。
7. auto:
   `hidloom-hidd` readiness を見て `usb` / `uinput` を選ぶ。BT fallback は別 phase。
8. UI/status:
   HTTP / OLED / LED mode 表示を router status 由来へ移す。

## Test plan

local / non-device:

- broker frame encode/decode compatibility
- HID report -> Linux EV_KEY diff conversion
- modifier-only report
- same key held across repeated report
- null report releases all uinput pressed keys
- target switch sends release before route change
- router `usb` target preserves existing hidd frame order
- router `bt` target converts `CQAU` keyboard / US-sub keyboard / mouse / consumer frames to `btd1` stream frames

real device:

- `<keyboard-host>` で `uidd` が `/dev/uinput` virtual keyboard を作れる
- `KC_CONSOLE` 後に safe local console へ文字が入る
- `KC_USB` 後に host 側へ文字が入る
- `KC_CONSOLE` 中は host USB 側へ通常 keyboard report が出ない
- held key 中の target switch で stuck key が残らない
- USB cable replug 後の `auto` が `usb` へ戻る

## Open decisions

- router daemon 名は `hidloom-outputd` とするか、短く `outputd` とするか。
- `uidd` の socket を broker frame 互換にするか、8-byte keyboard report 専用にするか。
  first slice は互換 frame の方が capture / replay helper を流用しやすい。
- Consumer Control と mouse を `uidd` M0 に含めるか。
  console 切り替え復旧の最短 path では keyboard report だけでよい。
- `KC_BT` を native router に入れる時期。
  BLE HID は既に companion / `btd` 経路があるため、first slice では混ぜない。
