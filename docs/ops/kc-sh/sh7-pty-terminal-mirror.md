# KC_SH7 PTY Terminal Mirror

更新日: 2026-06-23

## 目的

`KC_SH7` は、Raspberry Pi 側の user 権限 shell を `sessiond` の PTY 上で起動し、
物理キーボード入力を PTY へ送り、PTY output を host PC のテキストエディタへ HID keyboard tap として戻す実験的な terminal mirror です。

標準 host profile は `windows_text_editor_us_sub_keyboard` です。
Windows Terminal / WSL の `cat` receiver は使わず、安全なテキストエディタやメモアプリへ plain text として出力します。

## 起動と終了

- `KC_SH7` press: mirror を開始します。
- mirror active 中の `KC_SH7` press: operator escape として mirror を停止します。
- PTY shell で `exit`: shell 終了により mirror も inactive になります。
- output switch action (`KC_USB` など): mirror を停止して出力先切替を優先します。

`sessiond` は `KC_SH7` 実行時だけ `logicd` から user 権限で自動起動します。
常駐 user service は現時点では不要です。

## 入力と出力

通常時の入力経路:

```text
physical key -> matrixd -> logicd-core-rs -> hidloom-outputd -> hidloom-hidd / hidloom-uidd
```

mirror active 中の入力経路:

```text
physical key -> matrixd -> logicd-core-rs matrix_delegate_all -> logicd-companion -> sessiond PTY
```

mirror active 中の PTY 応答出力経路:

```text
sessiond PTY text -> logicd-companion text plan -> logicd-core-rs key_event source=pty_terminal_mirror -> hidloom-outputd usb -> hidloom-hidd -> /dev/hidg2 -> host app
```

標準 profile では、PTY output から ANSI / terminal control sequence を strip します。
host PC 側は terminal emulator としてではなく、テキストを受けるアプリとして扱います。

`KC_SH7` で mirror が active になると、`logicd-companion` は `logicd-core-rs` control socket へ
`set_matrix_delegate_all=true` を送り、core 側の pressed state を release してから全 matrix P/R を
delegate socket へ渡します。これにより mirror 中の通常キーは USB へ直接出ず、PTY input として
`sessiond` へ入ります。mirror 停止、`exit`、operator escape、output switch、または PTY output dispatch
失敗時は `set_matrix_delegate_all=false` に戻します。

mirror 開始時は `hidloom-outputd` target も `usb` へ準備します。`KC_CONSOLE` などで Pi local console にしていた後でも、
PTY 応答は host 側の text editor へ戻す前提です。

## Timing

2026-06-15 時点の採用値:

| Parameter | Value |
| --- | ---: |
| output tap hold | 2ms |
| output tap gap | 2ms |
| chunk post gap | 2ms |
| `usbd` keyboard pacing | 500Hz |
| release merge window | 16ms |

確認結果:

- 1ms / 1000Hz は host 側で詰まりが出ました。
- 2ms / 500Hz は `ls` と `ls -alF` で良好でした。
- 4ms hold / 6ms gap / 200Hz は余裕があり、重いアプリでの fallback 候補です。
- 6ms hold / 12ms gap / 125Hz は直近の安全側 fallback 候補です。

host app の入力処理速度で結果が変わります。
重い editor で崩れ、軽いメモアプリで通る場合は、host app 側の入力 queue が律速です。

## Ctrl-C

mirror active 中に `Ctrl-C` を入力すると、次を行います。

1. `logicd` が `Ctrl-C` を判定した瞬間に、送信中の PTY output task と pending queue を cancel します。
2. その後 `sessiond` の PTY へ `0x03` を送ります。
3. `sessiond` は PTY 側の古い output を discard します。
4. 最後に shell prompt 候補だけが見えた場合は、その prompt tail だけを `pty_text_stream` として返します。

狙いは、`ls -alF` や `ps` などの長い応答中に止めた時、古い出力を最後まで host へ打ち続けず、
prompt 付近へ素早く戻すことです。

限界:

- すでに host PC へ HID report として送られた文字は取り消せません。
- host app 側の入力 queue に積まれた文字は、アプリ側で処理されるまで残る場合があります。
- prompt tail は `$` または `#` で終わる最後の行だけを保守的に返します。

## HID Broker

現行の既定構成では、boot-critical keyboard path は
`logicd-core-rs -> hidloom-outputd -> hidloom-hidd` へ流れます。
KC_SH7 / sessiond 側の複雑な control-plane input は `logicd-core-rs` の
`matrix_delegate_all` mode で `logicd-companion` へ委譲します。
PTY 応答の synthetic HID output は `logicd-companion` から `logicd-core-rs` の
`key_event` control path へ戻し、`source=pty_terminal_mirror` として US sub keyboard route に固定します。
`hidloom-outputd` は `usb` target で `hidloom-hidd` へ配送し、`hidloom-hidd` は
`/tmp/usbd_hid_reports.sock` と `/dev/hidg*` endpoint の owner です。

broker の役割:

- mouse motion を合算します。
- keyboard report は press/release の順序を守って pacing します。
- 別キー連続 tap では、safe な範囲で release を coalesce します。
- 同一キー連打、modifier-only 連打、mouse / consumer との混在では release を残します。

重要:

- `/tmp/usbd_hid_reports.sock` が消えると、`logicd` は broker へ送れず host へキーが届きません。
- 2026-06-15 に、flush due 時の `recv()` `EAGAIN` を fatal 扱いして socket を unlink する問題を修正しました。
- 2026-06-20 以降の既定 owner は `hidloom-hidd` です。legacy `usbd.service` は通常 inactive です。

## Troubleshooting

サービス状態:

```bash
systemctl is-active hidloom-logicd-core matrixd hidloom-hidd logicd-companion hidloom-usb-gadget viald
ls -l /tmp/usbd_hid_reports.sock /dev/hidg0 /dev/hidg2
```

PTY mirror capture / output dispatch が動いているか:

```bash
journalctl -u logicd-companion -u hidloom-logicd-core --since "5 min ago" --no-pager \
  | egrep -i "PTY mirror|matrix capture|matrix_delegate_all|key_event|outputd|gadget|warning|error"
```

core status で capture mode を見る:

```bash
cat /run/hidloom/logicd-core-status.json \
  | python3 -m json.tool \
  | egrep -i "matrix_delegate_all|force_delegate_all|pressed_keys|delegated_actions"
```

`hidloom-hidd` broker が動いているか:

```bash
journalctl -u hidloom-hidd --since "5 min ago" --no-pager \
  | egrep -i "HID report|socket|failed|error"
```

broker へ手動で 1 key 送る:

```bash
cd /home/USERNAME/hidloom
python3 script/send_standard_keyboard_report.py KC_A \
  --socket /tmp/usbd_hid_reports.sock \
  --transport socket \
  --broker-kind keyboard \
  --hold-sec 0.01
```

`/tmp/usbd_hid_reports.sock` がない場合:

```bash
sudo systemctl restart hidloom-hidd logicd-companion
ls -l /tmp/usbd_hid_reports.sock
```

`sessiond` を止めて次回自動起動からやり直す:

```bash
pkill -f "python3 -m sessiond.sessiond" || true
rm -f /tmp/sessiond.sock /tmp/hidloom-sessiond.sock
sudo systemctl restart logicd-companion
```

## Tests

local /実機で使う主な確認:

```bash
python3 script/test_logicd_pty_terminal_text.py
python3 script/test_logicd_pty_mirror_runtime.py
python3 script/test_logicd_core_rs_tool.py
python3 script/test_sessiond_socket.py
python3 script/test_sessiond_ctl.py
python3 script/test_usbd_validation.py
python3 script/test_pty_mirror_remote_suite.py
```

`Ctrl-C` 周辺の要点:

- `script/test_logicd_pty_mirror_runtime.py` は route 前 cancel を確認します。
- `script/test_logicd_core_rs_tool.py` は `set_matrix_delegate_all` 中に通常 matrix P/R が
  companion delegate socket へ流れ、broker へ直接出ないことを確認します。
- `script/test_sessiond_ctl.py` は `sleep 2` + `Ctrl-C` の status を確認します。
- `script/test_sessiond_socket.py` は prompt tail 抽出 helper を確認します。

## 関連文書

- [../pty-terminal-mirror-smoke.md](../pty-terminal-mirror-smoke.md): M0 smoke の履歴と手順。
- [../../daemon/specs/sessiond/pty-terminal-mirror-design.md](../../daemon/specs/sessiond/pty-terminal-mirror-design.md): 設計メモ。
- [../../daemon/specs/sessiond/pty-terminal-mirror-implementation-notes.md](../../daemon/specs/sessiond/pty-terminal-mirror-implementation-notes.md): 実装メモ。
- [../../../daemon/sessiond/README.md](../../../daemon/sessiond/README.md): `sessiond` daemon の概要。
