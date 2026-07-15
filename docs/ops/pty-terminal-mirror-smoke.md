# PTY terminal mirror smoke

現行の `KC_SH7` 実機運用、2ms timing、`Ctrl-C` output flush、`usbd` broker 復旧手順は
[kc-sh/sh7-pty-terminal-mirror.md](kc-sh/sh7-pty-terminal-mirror.md) に分離しました。
この文書は `docs/ops/README.md` から辿る上位入口として残し、M0 smoke の履歴と
no-HID / manual socket 手順を保持します。

## 2026-06-15 standard mode update

`KC_SH7` の標準 host profile は `windows_text_editor_us_sub_keyboard` です。
標準モードでは Windows Terminal / WSL 側に `cat` receiver を起動せず、focus 中のテキストエディタへ
PTY output を plain text HID tap plan として入力します。ANSI/terminal 制御列は text editor では解釈されないため、
標準モードでは出力前に strip します。

旧 cat モードは互換用に `windows_terminal_wsl_cat_us_sub_keyboard` として残します。
この profile を使う場合だけ、最初の PTY output 前に
`stty -echo -icanon min 1 time 0; cat; stty sane` の receiver bootstrap を投入し、
停止時に receiver stop plan で `Ctrl-C` / `stty sane` を送ります。

標準 smoke の Windows 側 preflight は、メモ帳、VS Code、その他安全なテキストエディタの入力欄に focus します。
cat 互換 smoke を行う場合だけ、Windows Terminal の WSL shell prompt に focus してください。

作成日: 2026-06-14

この手順は `sessiond` PTY terminal mirror M0 の実装途中 smoke です。
`logicd` から `sessiond` PTY へ入力を route し、PTY output を Windows Terminal + WSL の
echo-off `cat` receiver へ direct ANSI HID tap plan として戻すところまで接続済みです。
実機なしでは socket / PTY / logicd routing の一気通し、実機では Windows Terminal focus 後の
`KC_SH7` / `pwd` / `exit` を確認します。

## Local no-HID smoke

repository root で実行します。

まとめて回す場合:

```bash
python3 script/test_pty_mirror_remote_suite.py
```

内訳を個別に見る場合:

```bash
python3 script/test_sessiond_protocol.py
python3 script/test_sessiond_pty_mirror.py
python3 script/test_sessiond_pty_session.py
python3 script/test_sessiond_socket.py
python3 script/test_sessiond_ctl.py
python3 script/test_logicd_sessiond_client.py
python3 script/test_logicd_pty_mirror_runtime.py
python3 script/test_logicd_sessiond_pty_mirror_integration.py
```

この範囲で確認できるもの:

- `sessiond` protocol / socket / PTY process lifecycle。
- `sessiond_ctl.py` の start / write / key / stop。
- `logicd` から `sessiond` へ key action が route されること。
- `KC_SH7` start / operator escape / output switch / unavailable handling。
- PTY output が receiver bootstrap plan と direct ANSI HID tap plan に変換されること。
- output runner の pacing / cooperative yield / blocked plan handling。
- `pwd`、`echo !`、`sleep 2` + Ctrl-C、`exit` の no-HID 一気通し。

この範囲で確認できないもの:

- Windows Terminal pane の focus / scrollback / wrapping / font / IME 状態。
- US sub keyboard endpoint から Windows Terminal へ実際に HID tap が届くこと。
- host 側 `cat` receiver の echo 復帰を肉眼で確認すること。
- OLED alert / status の見え方。
- 実HID帯域、取りこぼし、体感遅延。

## Manual socket smoke

terminal A:

```bash
PYTHONPATH=daemon:. python3 -m sessiond.sessiond --socket /tmp/sessiond.sock
```

terminal B:

```bash
python3 tools/sessiond_ctl.py --socket /tmp/sessiond.sock start --shell "bash --noprofile --norc" --columns 120 --rows 35
python3 tools/sessiond_ctl.py --socket /tmp/sessiond.sock status
python3 tools/sessiond_ctl.py --socket /tmp/sessiond.sock write pwd --enter
python3 tools/sessiond_ctl.py --socket /tmp/sessiond.sock write "echo !" --enter
python3 tools/sessiond_ctl.py --socket /tmp/sessiond.sock write "sleep 2" --enter
python3 tools/sessiond_ctl.py --socket /tmp/sessiond.sock key KC_C --modifier KC_LCTL
python3 tools/sessiond_ctl.py --socket /tmp/sessiond.sock write "echo ok" --enter
python3 tools/sessiond_ctl.py --socket /tmp/sessiond.sock write "echo k"
python3 tools/sessiond_ctl.py --socket /tmp/sessiond.sock key KC_LEFT
python3 tools/sessiond_ctl.py --socket /tmp/sessiond.sock write "o" --enter
python3 tools/sessiond_ctl.py --socket /tmp/sessiond.sock write "echo okk"
python3 tools/sessiond_ctl.py --socket /tmp/sessiond.sock key KC_LEFT
python3 tools/sessiond_ctl.py --socket /tmp/sessiond.sock key KC_DEL
python3 tools/sessiond_ctl.py --socket /tmp/sessiond.sock key KC_ENTER
python3 tools/sessiond_ctl.py --socket /tmp/sessiond.sock stop --reason manual_smoke
```

期待:

- `start` が `pty_status active=true reason=started` を返す。
- `status` が active session を返す。
- `write pwd --enter` が `pty_text_stream` を返す。
- `write "echo !" --enter` が Shift 記号相当の bash 操作確認として `!` を含む output を返す。
- `key KC_C --modifier KC_LCTL` が `sleep 2` を interrupt し、後続の `echo ok` がすぐ返る。
- `key KC_LEFT` により `echo k` の `k` 手前へ戻り、`o --enter` で `ok` が返る。
- `key KC_DEL` により `echo okk` の末尾手前へ戻って 1 文字削除し、`KC_ENTER` で `ok` が返る。
- `stop` が `pty_status active=false reason=manual_smoke` を返す。

## KC_SH7 smoke

`sessiond` が `/tmp/sessiond.sock` で起動済みの状態で、`KC_SH7` を押します。
Windows 側は Windows Terminal の WSL を使える pane に focus しておきます。

### Preflight

実機側:

```bash
cd /usr/lib/hidloom
systemctl is-active hidloom-logicd-core logicd-companion
rm -f /tmp/sessiond.sock
nohup env PYTHONPATH=daemon:. python3 -m sessiond.sessiond --socket /tmp/sessiond.sock >/tmp/sessiond-pty-mirror.log 2>&1 &
test -S /tmp/sessiond.sock
sudo systemctl restart logicd-companion
test -S /tmp/key_events.sock
```

Windows Terminal 側:

- WSL bash pane に focus する。
- shell prompt が通常入力状態であることを確認する。`>` 継続 prompt が出ている場合は `Ctrl-C` で戻す。
- operator は focus を外したら、先に `KC_SH7` 再押しまたは SSH stop を使い、追加入力を止める。

期待:

- OLED alert に `PTY START` が出る。
- `logicd` が `PtyMirrorRuntime.start(source="KC_SH7")` を呼び、`sessiond` の bash PTY が active になる。
- 最初の PTY output 前に `stty -echo -icanon min 1 time 0; cat; stty sane` が自動入力され、
  Windows Terminal 側の receiver が起動する。
- 以後の PTY output は `Esc` + printable ASCII + Enter などの direct ANSI HID sequence として
  US sub keyboard route に送られる。
- active 中に `KC_SH7` を再度押すと `operator_escape` として mirror mode を停止し、
  `KC_SH7` 自体は PTY input / host HID へ送られない。
- `operator_escape` 時は Windows Terminal 側 receiver に synthetic `Ctrl-C` を送り、
  `cat` を抜けてから defensive restore として `stty sane` も自動入力する。取りこぼしに備え、
  restore では `Ctrl-C` を2回送る。
- 失敗時は OLED alert `PTY ERROR` が出る。

初期操作:

```text
pwd
echo !
exit
```

`exit` で bash が終了し、mirror mode も inactive になります。

緊急停止:

```text
KC_SH7
```

`KC_SH7` 再押しは host へ追加文字を送らずに `PTY EXIT operator_escape` で抜けるため、
focus ずれや receiver 同期ずれを見たら先に使います。

SSH 側で止める場合:

```bash
cd /usr/lib/hidloom
python3 tools/sessiond_ctl.py --socket /tmp/sessiond.sock stop --reason operator_pause || true
sudo systemctl restart logicd-companion
rm -f /tmp/sessiond.sock
```

出力を受け取れているかの確認:

```bash
journalctl -u logicd-companion --since "5 minutes ago" --no-pager \
  | grep "PTY mirror output dispatch result" \
  | tail -20
```

`plans` / `taps` / `events` が増えていれば、Pi側PTY出力は `logicd` まで届き、
HID dispatch も試行されています。

### Next Test Items

1. `KC_SH7` start: OLED `PTY START` と receiver bootstrap command が一度だけ入ること。
2. `pwd`: echo-off receiver の後、余計な `wsl bash -lc ...` wrapper が表示されず、PTY output が描画されること。
3. `KC_SH7` 再押し: `operator_escape` で停止し、`KC_SH7` が host へ文字として流れないこと。
4. `KC_SH7` 停止後: Windows Terminal 側の `cat` が終了し、続けて typed input が echo されること。
5. 再start後 `sleep 2` + `Ctrl-C`: foreground process が interrupt され、続けて `echo ok` が返ること。
6. `exit`: bash終了で mirror inactive、OLED `PTY EXIT` が出ること。

## Notes

- `KC_SH7.sh` は `tools/sessiond_ctl.py` を使う manual fallback として残しています。
  通常の key path では logicd の `KC_SH7` start handler が優先されます。
- `sessiond` は当面 user 権限で手動起動します。root system service 化は M0 の実機 smoke 後に判断します。
- receiver bootstrap command 自体は Windows Terminal の shell prompt 上に一度だけ見える可能性があります。
  その後の PTY output echo は `stty -echo` により抑制します。
- receiver は `-icanon min 1 time 0` で文字単位に出力し、`cat` 終了後に `stty sane` を実行する形です。
  万一 echo が戻らない時は、見えなくても `stty sane` + Enter を手で打つと復帰できます。
- 2026-06-14 の実機切り分けでは、`sessiond_ctl` 経由で `printf READY_FROM_PTY` を実行し、
  `READY_FROM_PTY` と bash prompt が `pty_text_stream` として戻ることを確認しました。
  shell応答が画面に出ない場合は、Pi側PTYではなく `logicd` の HID dispatch、receiver focus、
  または Windows Terminal 側の receiver 状態を優先して確認します。
- receiver bootstrap は安定性優先で `hold=0.006s` / `gap=0.020s`、direct ANSI output は
  速度優先で `hold=0.002s` / `gap=0.004s` を使います。取りこぼしが見える場合は direct output gap を
  `0.008s` 以上へ戻す候補として記録します。
- PTY output は既定 256 文字ごとの HID plan に分割して順次送ります。出力は切り捨てませんが、
  長い出力では 64 文字 window と低速 timing に切り替えます。4文字以上の連続空白は ANSI cursor-forward に圧縮します。
  通常の terminal と同じように出力中の入力は PTY 側で typeahead として扱います。
  長い `cat` / `find` / `ls -R` は
  HID送信に時間がかかるため、まず対象外として扱います。
- Windows Terminal の scrollback / wrapping / focus は通常 terminal app の責任範囲として扱い、
  M0 では完全 terminal emulator を目指しません。
