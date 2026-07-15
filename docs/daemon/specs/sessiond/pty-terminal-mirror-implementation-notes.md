# sessiond PTY terminal mirror implementation notes

## 2026-06-15 KC_SH7 standard text editor profile

採用した判断:

- `KC_SH7` の標準 host profile は `windows_text_editor_us_sub_keyboard` とする。
- 標準モードでは host 側の Windows Terminal / WSL shell に `cat` receiver を起動しない。
- PTY output は focus 中のテキストエディタへ direct HID tap として入力する。
- text editor は ANSI/terminal 制御列を解釈しないため、標準モードでは OSC / CSI / simple ESC sequence を strip する。
- `operator_escape` / `output_switch` 時、標準モードでは host 側に receiver stop plan を送らない。
- 旧 cat receiver 方式は `windows_terminal_wsl_cat_us_sub_keyboard` profile として残し、
  明示設定時だけ receiver bootstrap と receiver stop を使う。
- 標準モードの最初の PTY output 前に `KC_LANG2` を US sub keyboard route へ送って、Windows IME を direct input
  相当に戻す。すでに direct input の場合でも無害な起動時整流として扱う。
- mirror active 中に `Ctrl-C` (`KC_C` + Ctrl modifier) を PTY へ送った場合、`sessiond` は直後の PTY output を読み捨て、
  `clear_output_queue=true` を返す。`logicd` はこれを受けて未送信の PTY text output queue を cancel し、
  誤って長い出力コマンドを実行した時の停止スイッチとして使う。
- `KC_SH7.sh` は `/tmp/sessiond.sock` が無い場合に `sessiond` を必要時起動する。root から呼ばれた場合でも
  repository owner、通常は `pi`、として `sessiond` を起動し、user 権限 shell を維持する。
- `KC_SH7.sh` から起動した `sessiond` は既定で 10 秒 idle が続くと終了し、socket を削除する。
- logicd 内蔵 `KC_SH7` start handler も、`sessiond` socket が無い場合は repository owner user で
  `sessiond` を必要時起動してから start request を再試行する。
  これにより SH7 未使用時は Python daemon を常駐させない。

理由:

- 実運用の標準を「安全な入力欄に出力を貼る」形に寄せると、host 側 shell の状態、`cat` の echo 復旧、
  focus ずれによるコマンド残りのリスクを減らせる。
- cat receiver は ANSI を表示できる利点がある一方で、停止時の `Ctrl-C` / `stty sane` と host shell 状態への依存があるため、
  標準ではなく互換・診断用 profile として扱う。

作成日: 2026-06-14

このメモは [pty-terminal-mirror-design.md](pty-terminal-mirror-design.md)
の実装中に採用した仮決めを残します。後で判断を戻しやすいよう、実装 slice ごとに短く追記します。

## 2026-06-14 M0 pure helper slice

採用した初期値:

| 項目 | 値 | 理由 |
| --- | --- | --- |
| protocol | newline-delimited JSON | 既存 ctrl / i2cd と同じく読みやすく、M0 の message 量では十分 |
| socket owner | `sessiond` | `logicd` 側に新しい待ち受けを増やさない |
| default command | `bash` | user 権限の軽作業用 shell として最小 |
| start source | `KC_SH7` | 新しい virtual keycode を増やさず、既存 script key を使う |
| columns / rows | `120x35` | operator の現在の Windows Terminal 起動サイズに合わせる |
| flush window | `50 ms` | 20fps 相当で、軽作業用の反応と HID 帯域の折衷 |
| key tap hold | `6 ms` | 既存 text-send runner の初期値に合わせる |
| ASCII tap gap | `20 ms` | 文字入力の最初の推奨値。実機 smoke 後に調整 |
| ESC chunk gap | `50 ms` | ANSI sequence 境界で Windows Terminal 側の取りこぼしを避ける仮値 |

実装範囲:

- `daemon/sessiond/protocol.py` に JSON-line message helper と M0 default constants を追加。
- `daemon/sessiond/pty_mirror.py` に US ASCII / control code の PTY byte 変換、120x35 前提でも使える row-level diff helper を追加。
- この slice は socket を開かず、PTY process も起動しない。

未実装:

- `sessiond` daemon skeleton。
- `logicd` client / loop guard。
- `KC_SH7.sh`。
- OLED status line。
- 実機 smoke。

## 2026-06-14 local PTY session slice

採用した判断:

- PTY wrapper は `pty.openpty()` + `subprocess.Popen()` を使い、`TERM=xterm-256color`、
  `COLUMNS=120`、`LINES=35` を環境に渡す。
- shell process は process group を分け、停止時は process group へ `SIGTERM`、
  残る場合だけ `SIGKILL` を送る。
- `exit` 判定は文字列ではなく process exit code / PTY EOF を見る。
- この slice は local PTY smoke だけで、`logicd` routing や HID 送信はまだ行わない。

追加した確認:

- `/bin/sh` を PTY で起動し、`printf PTY_OK` を入力して出力を読めること。
- `exit` を key action 経由で入力し、process が exit code 0 で終了すること。

## 2026-06-14 sessiond socket skeleton slice

採用した判断:

- `sessiond` が Unix domain socket を listen し、`logicd` は将来 client として接続する。
- M0 の socket server は newline-delimited JSON だけを扱い、汎用 RPC framework にはしない。
- `start_pty_mirror` は active session がある場合 `already_active` status を返す。
- `pty_key_input` は M0 のテスト用に `bytes_hex` も受ける。実際の key routing では action/modifier 経路を優先する。
- `sessiond` server close 時は active PTY を terminate する。

追加した確認:

- temporary socket 上で `/bin/sh` PTY を起動できること。
- socket 経由で `printf SOCK_OK` を送り、`pty_text_stream` を受け取れること。
- socket 経由で `exit` を送り、`pty_status active=false reason=exit:0` を受け取れること。

## 2026-06-14 KC_SH7 / control CLI slice

採用した判断:

- `tools/sessiond_ctl.py` を追加し、`start` / `stop` / `status` だけを扱う。
- CLI は sessiond socket に 1 request を送り、最初の `pty_status` を受け取って終了する。
- `KC_SH7.sh` は `tools/sessiond_ctl.py start --shell bash --columns 120 --rows 35 --source KC_SH7` を呼ぶ。
- `KC_SH7.sh` は開始前に OLED alert `PTY START` を出し、CLI 失敗時だけ `PTY ERROR` warning を出す。
- `sessiond.service` はまだ追加しない。user 権限の扱いを崩さないため、実 service 化は次 slice で詰める。

追加した確認:

- temporary sessiond socket に対して CLI から start / status / stop が通ること。
- `KC_SH7.sh` は repo default script として追加し、本番では `/mnt/p3/script/KC_SH7.sh` が優先される既存方針に従う。

## 2026-06-14 WSL output wrapper plan slice

気づいた点:

- Windows Terminal は ANSI escape sequence を process output として受けた時に解釈する。
- HID keyboard で `ESC [ 2 J` をそのまま打つと、多くの場合は shell/readline への入力になり、
  terminal output として解釈されない。

採用した判断:

- M0 の Windows Terminal smoke は WSL 利用可を前提に寄せる。
- `pty_text_stream` は直接 ANSI key taps にせず、
  `wsl bash -lc "printf %s '<base64>' | base64 -d"` に包む。
- command 文字列は US ASCII だけで構成し、US sub keyboard endpoint から tap sequence として送れるようにする。
- source guard は `source=pty_terminal_mirror` を要求し、macro recording / interaction input / PTY input routing には戻さない。
- PowerShell `Console.Write` wrapper も成立するが、M0 では WSL 経由の方が短く、責務も明確なため採用しない。

追加した確認:

- ANSI text が Base64 で WSL command に包まれ、decode すると元 text に戻ること。
- WSL command が US ASCII tap sequence に展開できること。
- invalid source は plan blocked になること。

## 2026-06-14 logicd sessiond client slice

採用した判断:

- `logicd` 側には listening socket を増やさず、`SessiondPtyMirrorClient` が
  `sessiond` owned socket へ client 接続する。
- client は `pty_text_stream` response を受け取った時点で WSL text plan を作る。
- この slice ではまだ matrix event routing や HID dispatch へは接続しない。
- `source=pty_terminal_mirror` loop guard は text plan metadata に残し、実 dispatch 接続時に使う。

追加した確認:

- temporary `sessiond` socket に対して logicd client helper から start できること。
- key action 経由で `pwd` を PTY に入力し、戻ってきた PTY text から WSL text plan を作れること。
- key action 経由の `exit` で inactive status を受け取れること。

## 2026-06-14 logicd mirror runtime routing slice

採用した判断:

- `LogicdRuntime` に `pty_mirror` runtime state を追加する。
- mirror active 中は `handle_resolved_action()` の先頭で key action を `sessiond` へ route し、
  通常 macro/HID 出力へは流さない。
- release event は PTY byte を出さないが consumed として扱い、通常 HID release へ戻さない。
- `sessiond` から inactive status が返ったら mirror mode を終了する。
- この slice ではまだ `sessiond` から戻った WSL text plan を実 HID dispatch しない。

追加した確認:

- mirror inactive 中は通常 macro dispatch が動くこと。
- mirror active 中は press action が `sessiond` client に送られ、macro dispatch へ流れないこと。
- release event は consumed されること。
- inactive status (`exit:0`) で mirror runtime が inactive になること。

## 2026-06-14 logicd output dispatch / KC_SH7 start slice

採用した判断:

- `dispatch_action_event()` / `handle_resolved_action()` に任意の `source` metadata を渡せるようにする。
- PTY text plan 由来の合成 tap は `source=pty_terminal_mirror` として dispatch し、
  active mirror 中でも PTY input routing に戻さない。
- PTY text plan の dispatch は `daemon/logicd/pty_mirror_output_runner.py` に分ける。
  `sessiond_client` は plan 作成、`PtyMirrorRuntime` は状態、output runner は HID tap dispatch という責務にする。
- output runner の初期値は `tap_hold_sec=0.006`, `tap_gap_sec=0.020`。
  既存 text-send runner より速いが、M0 は WSL command wrapper が長くなるため初期実験値として採用する。
- `KC_SH7` press は logicd 側で捕まえて `PtyMirrorRuntime.start(source="KC_SH7")` を呼ぶ。
  これにより `sessiond` 起動後すぐ logicd runtime が active を知り、その後のキー入力を PTY へ route できる。
- `KC_SH7.sh` は CLI/manual fallback として残す。通常の key path では logicd start handler が優先される。
- active 中に `KC_SH7` が再度来た場合は restart せず、通常キーと同じく PTY input として扱う。

追加した確認:

- `KC_SH7` press で `sessiond` client start が呼ばれ、source/columns/rows が M0 初期値になること。
- start 直後の PTY text plan が synthetic source guard 付きで macro/HID dispatch 経路へ流れること。
- mirror active 中の物理 key action は PTY client へ送られ、同じイベントは通常 macro/HID dispatch へ漏れないこと。
- PTY text plan がない key action では直前の text plan を再送しないこと。

実機確認待ち:

- Windows Terminal + WSL focus 状態で、`KC_SH7` から bash prompt 表示まで進むこと。
- `ls` / `pwd` / `exit` の軽操作で、入力 route、WSL command wrapper、bash exit による mode 終了がつながること。
- `tap_gap_sec=0.020` が実機 HID で取りこぼさないか。取りこぼす場合は `0.040` か `0.060` へ上げる。

## 2026-06-14 no-HID integration smoke slice

採用した判断:

- 実機 HID なしでも、`logicd -> sessiond socket -> bash PTY -> pty_text_stream -> WSL text plan -> synthetic HID tap dispatch`
  までは自動テストで確認する。
- Windows Terminal focus / 実際の `/dev/hidg2` 送信だけを実機確認待ちに残す。
- `sessiond` は当面 user 権限で手動起動する。root system service 化は user 権限方針と矛盾するため、M0 実機 smoke 後に判断する。

追加した確認:

- temporary `sessiond` socket で `KC_SH7` start handler が bash PTY を開始できること。
- `pwd` を key action として PTY に送り、PTY output が synthetic HID tap dispatch へ戻ること。
- `exit` を key action として送り、`exit:0` で mirror runtime が inactive になること。

## 2026-06-14 OLED alert feedback slice

採用した判断:

- `KC_SH7` start 成功時は `PTY START`、start 失敗時は `PTY ERROR` を logicd から出す。
- active mirror 中の route 結果で `active=false` になった時は、`PTY EXIT\n<reason>` を出す。
- `sessiond_unavailable` / client missing 系は exit ではなく `PTY ERROR` として扱う。
- 時計の次の行を使う debug status は未実装のまま残し、初期 smoke では alert だけを使う。

追加した確認:

- runtime test で `KC_SH7` start alert と `exit:0` exit alert を固定した。

## 2026-06-14 bash usability / stability slice

つぶした懸念:

- `S(KC_1)` などの wrapper が `KC_LSFT` press -> `KC_1` press に展開された後、
  PTY input へ modifier state が渡らず `!` が `1` になる懸念。
- QMK 短縮 alias (`KC_MINS`, `KC_SCLN`, `KC_LBRC` など) が PTY byte 変換で拾えない懸念。
- PTY output だけ返り status がない正常応答を `ok=false` と見なしてしまう懸念。
- 大量出力を無制限に WSL command wrapper / HID tap sequence 化してしまう懸念。

採用した判断:

- `PtyMirrorRuntime` が active modifier set を持ち、non-modifier key を `sessiond` へ送る時に
  `modifiers` として渡す。
- modifier press/release 自体は PTY byte を出さず consumed とする。
- M0 の PTY text plan は既定 `max_text_chars=256` を1 planあたりの chunk size とし、
  超過時は複数 plan に分割して順次 HID 送信する。
- `SessiondPtyMirrorClient` は `pty_text_stream` だけの response も正常応答として扱う。
- `sessiond` の PTY drain は 8192 bytes を上限にして、単一 read cycle で無制限に貯めない。

追加した確認:

- runtime test で active modifier state が `sessiond` client に渡ること。
- sessiond client test で `echo !` が Shift modifier 経由で shell に届くこと。
- text plan test で長い出力が複数 plan に分割され、出力 text が保持されること。

## 2026-06-14 sessiond_ctl write smoke slice

採用した判断:

- HID / logicd を通す前に bash PTY 操作を確認できるよう、`tools/sessiond_ctl.py write TEXT --enter`
  を追加する。
- `write` は M0 の手動 smoke 用で、`pty_key_input bytes_hex` を使って sessiond の active PTY に文字列を送る。
- `start` / `status` / `stop` は従来通り status response で早く終了し、
  `write` は `pty_text_stream` も正常応答として扱う。

追加した確認:

- `sessiond_ctl` test で `write pwd --enter` が `pty_text_stream` を返すこと。
- `write "echo !" --enter` が `!` を含む output を返すこと。

## 2026-06-14 socket path / ASCII guard slice

つぶした懸念:

- `sessiond` 起動時に `/tmp/sessiond.sock` 相当の path が既存 regular file だった場合、
  無条件 unlink してしまう懸念。
- `close()` 側でも start 失敗後に非socket path を消してしまう懸念。
- `sessiond_ctl write` から M0 scope 外の非ASCII文字列を直接 PTY に流せてしまう懸念。

採用した判断:

- `sessiond` は既存 path が socket の時だけ stale socket として unlink する。
- 既存 path が socket 以外なら起動を失敗させ、ファイルは残す。
- `sessiond_ctl write` は ASCII only とし、非ASCIIは送信前に `ok=false` で拒否する。

追加した確認:

- `script/test_sessiond_socket.py` で non-socket path を削除しないこと。
- `script/test_sessiond_ctl.py` で `write あ --enter` が拒否されること。

## 2026-06-14 output switch bypass slice

つぶした懸念:

- mirror active 中に `KC_USB` / `KC_BT` / `KC_CONSOLE` / `KC_CONNAUTO` が PTY input として consumed され、
  通常の output switch safety path へ届かない懸念。

採用した判断:

- mirror active 中でも output switch action の press は PTY へ送らない。
- output switch action の press を受けたら `PtyMirrorRuntime.stop(reason="output_switch")` を呼び、
  `PTY EXIT\noutput_switch` alert を出してから通常の `handle_resolved_action()` flow に戻す。
- output switch action の release は mirror が inactive になった後の通常 release として扱う。

追加した確認:

- runtime test で active 中の `KC_USB` が sessiond client へ送られず、mirror stop 後に通常 macro/output 経路へ流れること。

## 2026-06-14 status reap / observability slice

つぶした懸念:

- PTY child が `exit` 入力以外で終了した時、次の key input まで `sessiond.session` が stale に残る懸念。
- `status` が常に default `120x35` を返し、実際の session rows/columns や pid を観測できない懸念。

採用した判断:

- `process_message()` の先頭で終了済み session を reap する。
- `status_message()` helper を追加し、active session の rows / columns / pid を返す。
- status request でも終了済み child を `exit:<code>` として確定させる。

追加した確認:

- socket test で start status に `rows=35`, `columns=120`, `pid` が含まれること。
- `/bin/sh -c 'exit 7'` の終了を status request で `exit:7` として reap できること。

## 2026-06-14 synthetic tap release guard slice

つぶした懸念:

- PTY output の WSL command wrapper を synthetic HID tap として送っている途中で例外が起きた場合、
  modifier や key release が送られず host 側に stuck key が残る懸念。

採用した判断:

- `pty_mirror_output_runner._dispatch_tap()` は press 済み action を記録し、
  例外時も `finally` で key / modifier release を逆順に試みる。
- release 中に例外が起きても、可能な限り残り release を続け、最初の例外を呼び元へ戻す。

追加した確認:

- runtime test で `KC_A` press が失敗しても `KC_A` release と `KC_LSHIFT` release が dispatch されること。

## 2026-06-14 controlling terminal / Ctrl-C slice

つぶした懸念:

- PTY child が controlling terminal を持たない状態だと、logicd から `Ctrl-C` 相当の入力を送っても
  foreground process に interrupt signal として届かない懸念。
- その場合、`sleep 2` のようなコマンド中に `Ctrl-C` を送っても shell が戻らず、後続入力が
  process 終了まで滞留する。

採用した判断:

- `PtyMirrorSession.start()` の child setup で `setsid()` 後に slave fd を `TIOCSCTTY` で
  controlling terminal として設定する。
- これにより、当初マイルストーンの `^C` を「文字として送る」だけでなく、通常の PTY 操作に近い
  terminal signal として扱える状態にする。
- この変更は `sessiond` 内の PTY child 起動処理に閉じ、logicd の key mapping や usbd 側の
  HID 処理責務は増やさない。

追加した確認:

- logicd client test で `/bin/sh` を起動し、`sleep 2` 入力後に `KC_LCTL + KC_C` を送る。
- 直後に `echo ok` を入力し、`sleep` 終了待ちなしで `ok` が返ることを確認する。

## 2026-06-14 sessiond_ctl key smoke slice

つぶした懸念:

- 実機 HID path に入る前の no-HID smoke では `write` が ASCII text 専用のため、
  `Ctrl-C` など key action + modifier の確認がしづらい懸念。

採用した判断:

- `tools/sessiond_ctl.py key ACTION --modifier MOD` を追加し、`pty_key_input` の action path を
  manual smoke から直接叩けるようにする。
- `write` は引き続き ASCII text 専用のままにして、M0 の文字列入力 scope を広げすぎない。

追加した確認:

- `sessiond_ctl` test で `sleep 2` 後に `key KC_C --modifier KC_LCTL` を送り、
  後続の `write "echo ok" --enter` がすぐ返ること。
- ops smoke に同じ manual command を追加した。

## 2026-06-14 invalid bytes_hex recovery slice

つぶした懸念:

- 壊れた `bytes_hex` を受けた時に socket client へは error status が返るものの、
  エラー内容が `Odd-length string` のような実装詳細になり、原因が分かりにくい懸念。
- error response 後も既存 PTY session が継続できることがテストで固定されていない懸念。

採用した判断:

- `bytes_hex` の decode 失敗は `invalid bytes_hex payload` として明示する。
- M0 では壊れた client 入力だけで active PTY session は止めない。

追加した確認:

- socket test で `bytes_hex=not-hex` に `active=true reason=error` が返ること。
- その後、同じ session に `printf STILL_OK` を送り、通常 output が返ること。

## 2026-06-14 modifier alias slice

つぶした懸念:

- repo 内の keycode 定義では `KC_LCTL` / `KC_LCTRL`、`KC_LSFT` / `KC_LSHIFT` のような
  alias が同じ modifier として扱われるが、PTY 入力変換側が片方だけを見ると実機経路や
  manual smoke の入力元によって Ctrl / Shift が効かない懸念。

採用した判断:

- PTY input helper の modifier 判定に `KC_LCTRL`, `KC_RCTRL`, `KC_LSHIFT`, `KC_RSHIFT` と
  shortened alias を追加する。
- canonicalization を大きく持ち込むのではなく、M0 の対象 modifier だけを局所的に受ける。

追加した確認:

- pure helper test で `KC_LSHIFT + KC_A` が `A` になり、`KC_LCTRL + KC_C` が `\x03` になること。
- 上位の logicd client / sessiond_ctl smoke が引き続き通ること。

## 2026-06-14 logicd modifier alias tracking slice

つぶした懸念:

- `sessiond` 側の PTY input helper は `KC_LCTRL` / `KC_LSHIFT` alias を受けるが、
  `logicd` の active modifier tracking が canonical 名だけを見ると、実機 keymap や alias 入力から
  modifier state が sessiond へ渡らない懸念。

採用した判断:

- `PtyMirrorRuntime` の tracked modifier に `KC_LCTRL`, `KC_RCTRL`, `KC_LSHIFT`, `KC_RSHIFT` を追加する。
- PTY mirror M0 では global canonicalizer を増やさず、active modifier state に必要な alias だけを受ける。

追加した確認:

- runtime test で mirror active 中に `KC_LCTRL` press、`KC_C` press、`KC_LCTRL` release を送り、
  client 側へ `("KC_C", True, ("KC_LCTRL",))` として渡ること。

## 2026-06-14 PTY start failure fd cleanup slice

つぶした懸念:

- `PtyMirrorSession.start()` で command path が存在しないなど `Popen` が失敗した場合、
  slave fd は閉じるが master fd が local 変数のまま残り、起動失敗を繰り返すと fd leak になる懸念。

採用した判断:

- `Popen` 失敗時は master fd も閉じてから例外を再送出する。
- 起動失敗自体は `sessiond.process_line()` の error status path に任せ、ここでは resource cleanup に限定する。

追加した確認:

- PTY session wrapper test で存在しない shell 起動を複数回試し、`/proc/self/fd` の fd 数が増えないこと。
- 通常の `/bin/sh` 起動、入力、`exit` smoke が引き続き通ること。

## 2026-06-14 sessiond start failure recovery slice

つぶした懸念:

- `start_pty_mirror` の command が存在しない場合に error response 後の service state が曖昧になり、
  次の正常 start ができるかテストで固定されていない懸念。

採用した判断:

- 起動失敗は `process_line()` の既存 error status path で `active=false reason=error` として返す。
- `start_session()` は session object を成功後にだけ保持するため、起動失敗後も次の start を受け付ける。

追加した確認:

- socket test で存在しない shell の start が `active=false reason=error` を返すこと。
- 同じ socket connection で続けて `/bin/sh` を start でき、`reason=started` になること。

## 2026-06-14 sessiond oversized message guard slice

つぶした懸念:

- local socket client が誤って巨大な JSON-line を送った時に、`sessiond` が必要以上に大きな payload を
  decode しようとして memory / latency の不安定要因になる懸念。

採用した判断:

- M0 protocol の single message 上限を 64KiB とし、超過時は `active=<current> reason=error` と
  `sessiond message too large` を返す。
- stream reader の limit は上限より少し大きい 128KiB にし、自前の error status を返せる範囲を確保する。

追加した確認:

- socket test で 70KiB 級の `pty_status` request が `reason=error` / `too large` を返すこと。
- 同じ connection で続けて通常 `status` request を送り、`reason=idle` が返ること。

## 2026-06-14 stop reason normalization slice

つぶした懸念:

- external client が長い stop reason や改行入り reason を送ると、status payload や OLED alert に
  読みにくい文字列が残る懸念。

採用した判断:

- `stop_pty_mirror.reason` は sessiond 境界で CR/LF を空白へ置換し、空文字は `stop`、
  長さは 80 文字に丸める。
- error detail は別 field の `error` に残すため、通常 reason は短い状態表示として扱う。

追加した確認:

- socket test で改行と 120 文字超の reason を送っても、返る `reason` が単一行 80 文字になること。

## 2026-06-14 arrow key / bash line edit slice

つぶした懸念:

- M0 は軽作業用でも、shell の履歴移動や入力行の修正に矢印キーが使えないと bash 操作の体感が大きく落ちる懸念。
- `/bin/sh` では矢印による行編集が効かない環境があるため、line edit smoke の前提 shell が曖昧になる懸念。

採用した判断:

- `KC_LEFT` / `KC_RGHT` / `KC_RIGHT` / `KC_UP` / `KC_DOWN` を ANSI cursor sequence に変換する。
- line edit smoke は M0 既定に近い `bash --noprofile --norc` で確認する。
- `/bin/sh` は basic command smoke に使えるが、行編集の期待値にはしない。

追加した確認:

- pure helper test で矢印 keycode が `ESC[D` / `ESC[C` / `ESC[A` / `ESC[B` になること。
- `sessiond_ctl` test で bash 起動後、`echo k`、`KC_LEFT`、`o --enter` により `ok` が返ること。

## 2026-06-14 sessiond_ctl write size guard slice

つぶした懸念:

- manual smoke 用の `sessiond_ctl write` が長い ASCII 文字列をそのまま socket へ送り、
  sessiond protocol の oversized guard に頼る形になる懸念。

採用した判断:

- `sessiond_ctl write` は M0 の手操作補助として最大 4096 bytes に制限する。
- 長い出力や bulk paste は初期 scope では対象外にし、必要になった時に chunking / pacing を別途設計する。

追加した確認:

- `sessiond_ctl` test で 4097 bytes の ASCII write が送信前に `ok=false` で拒否されること。

## 2026-06-14 logicd sessiond client malformed response slice

つぶした懸念:

- `logicd` の sessiond client が壊れた JSON-line や途中で壊れた socket 応答を受けると、
  decode 例外が mirror runtime 側へ漏れる懸念。

採用した判断:

- `SessiondPtyMirrorClient.request()` は request 中の例外を `ok=false` / `error` / partial responses に畳む。
- close 中の `OSError` は既に response が作れる段階なら握りつぶし、mirror runtime が通常の
  `sessiond_unavailable` 系処理に進めるようにする。

追加した確認:

- fake socket server が `not-json` を返す test を追加し、`client.status()` が例外ではなく
  `ok=false`, `responses=[]`, `text_plans=[]` を返すこと。

## 2026-06-14 delete/home/end line edit slice

つぶした懸念:

- 矢印キーだけでは、bash の入力行から余分な 1 文字を消すような軽い修正がしづらい懸念。

採用した判断:

- M0 の追加行編集キーとして `KC_DEL` / `KC_DELETE`、`KC_HOME`、`KC_END` を PTY escape sequence に変換する。
- まず automated smoke では `KC_DEL` の line edit だけを確認し、Home/End は pure mapping で固定する。

追加した確認:

- pure helper test で Delete/Home/End の PTY bytes を確認。
- `sessiond_ctl` test で bash 起動後、`echo okk`、`KC_LEFT`、`KC_DEL`、`KC_ENTER` により `ok` が返ること。

## 2026-06-14 sessiond_ctl key token guard slice

つぶした懸念:

- manual smoke 用の `sessiond_ctl key` が巨大な action / modifier 名や非ASCII token を socket へ送り、
  protocol guard へ頼る形になる懸念。

採用した判断:

- `sessiond_ctl key` は action / modifier token を ASCII かつ 1-64 bytes に制限する。
- modifier は最大 8 個までとし、M0 の Ctrl/Shift smoke を超える大量 modifier 入力は対象外にする。

追加した確認:

- `sessiond_ctl` test で非ASCII action、64 bytes 超 action、9 個の modifier が送信前に拒否されること。

## 2026-06-14 malformed command parse fd cleanup slice

つぶした懸念:

- `PtyMirrorSession.start()` が PTY fd を開いた後に `shlex.split()` していると、
  malformed quote など command parse 失敗時に master/slave fd が残る懸念。

採用した判断:

- command parsing は `pty.openpty()` より前に実行し、parse failure では PTY fd をまだ作らない。
- `Popen` 失敗時の master fd cleanup は引き続き維持する。

追加した確認:

- PTY session wrapper test で `bash 'unterminated` の起動失敗を複数回試し、`/proc/self/fd` の fd 数が増えないこと。
- 通常起動、存在しない shell 起動失敗 cleanup、socket / CLI smoke が引き続き通ること。

## 2026-06-14 logicd runtime client exception guard slice

つぶした懸念:

- `SessiondPtyMirrorClient` 以外の client 実装や予期しない socket failure が `start` / `stop` /
  `send_key_action` で例外を投げた場合、mirror runtime の外へ例外が漏れて入力処理を壊す懸念。

採用した判断:

- `PtyMirrorRuntime.start()` は client 例外を `active=false`, `last_reason=start_failed` に畳む。
- `route_action()` は client 例外を `sessiond_unavailable` として mode 終了し、modifier state を clear する。
- `stop()` は client stop 例外があっても local runtime は inactive に戻し、error detail を `last_error` に残す。

追加した確認:

- runtime test で start / stop / send が例外を投げる fake client を使い、例外が漏れず state が整理されること。

## 2026-06-14 PTY output unavailable plan observability slice

つぶした懸念:

- PTY output text plan がすべて unavailable の時、output runner が `result=ok` のままになり、
  実機 smoke で「何も送られなかった」理由が追いにくい懸念。

採用した判断:

- 入力 plans があるのに available plan が 0 件の場合、`no_available_pty_text_plan` を blocking reason とする。
- available plan でも taps が空の場合は従来通り `pty_text_plan_taps_unavailable` として扱う。

追加した確認:

- runtime/output runner test で unavailable plan only が `result=blocked`, `events=0`, `taps=0` になること。
- available だが taps 空の plan が `pty_text_plan_taps_unavailable` を返すこと。

## 2026-06-14 stop stale error cleanup slice

つぶした懸念:

- 過去の client error が `last_error` に残ったまま、後続の正常 stop / output switch stop 後も
  status 上は古い error が残って見える懸念。

採用した判断:

- `PtyMirrorRuntime.stop()` は client stop が成功した場合 `last_error=None` に戻す。
- client stop が例外を投げた場合のみ、local runtime は inactive に戻しつつ `last_error` に詳細を残す。

追加した確認:

- runtime test で output switch による正常 stop 後の `last_error is None` を確認。
- client stop 例外時は inactive に戻り、`last_error` に例外内容が残ること。

## 2026-06-14 stale text plan cleanup slice

つぶした懸念:

- `PtyMirrorRuntime.last_text_plans` に直前の PTY output plan が残ったまま、plan なし入力や stop 後も
  stale な出力情報として見えてしまう懸念。

採用した判断:

- `_record_text_plans()` は今回の result に plan がない場合、`last_text_plans` を clear する。
- `stop()` でも mode 終了状態に合わせて `last_text_plans` を clear する。

追加した確認:

- runtime test で text plan あり入力後に plan なし入力を送ると `last_text_plans == []` になること。
- output switch stop 後も `last_text_plans == []` になること。

## 2026-06-14 available text plan accounting slice

つぶした懸念:

- unavailable な PTY output plan まで `text_plan_count` / `last_text_plans` に入ると、
  実際に dispatch 可能な出力数より状態カウンタが大きく見える懸念。

採用した判断:

- `PtyMirrorRuntime._record_text_plans()` は `available=true` の plan だけを記録・カウントする。
- unavailable plan の理由は output runner の `blocking_reasons` 側で観測する。

追加した確認:

- runtime test で unavailable plan を返す key action が `text_plan_count` を増やさず、
  `last_text_plans` も空のままになること。

## 2026-06-14 per-session counter reset slice

つぶした懸念:

- `sent_key_actions` / `text_plan_count` が PTY session をまたいで累積すると、
  OLED / status / debug で現在 session の状態なのか過去分なのか分かりにくい懸念。

採用した判断:

- `PtyMirrorRuntime.start()` のたびに送信数、text plan 数、last text plans を reset する。
- start 直後に prompt 等の text plan が返った場合は、その session の count として記録する。

追加した確認:

- runtime test で一度 exit した同じ runtime を再 start し、`sent_key_actions=0`、
  `text_plan_count=1` から始まること。

## 2026-06-14 output dispatch failure guard slice

つぶした懸念:

- `sessiond` から返った PTY output text plan を synthetic HID tap として流す途中で例外が起きると、
  `logicd` の入力処理へ例外が漏れて PTY mode の状態が曖昧になる懸念。
- start 直後の prompt 描画と、active 中の差分描画で失敗時の扱いが分かれる懸念。

採用した判断:

- `logicd.input_events` 側で text plan dispatch を小さな helper にまとめ、例外を捕捉する。
- dispatch 失敗時は `PtyMirrorRuntime.stop(reason="output_dispatch_failed")` を試み、local runtime も
  `active=false`, `last_reason=output_dispatch_failed`, `last_error=<例外文字列>` に揃える。
- OLED には `PTY ERROR` だけを出し、`PTY START` や通常の `PTY EXIT` alert と二重表示しない。
- 出力 dispatch の失敗は sessiond socket failure とは分け、実機調査時に HID/text-plan 側の問題として追えるようにする。

追加した確認:

- runtime test で start 直後の `KC_C` synthetic tap 失敗が例外として漏れず、sessiond stop と
  `last_reason=output_dispatch_failed` に整理されること。
- runtime test で active 中の `KC_A` route 後に返った `KC_B` synthetic tap 失敗も同じ扱いになること。

## 2026-06-14 invalid text tap key observability slice

つぶした懸念:

- PTY output plan の tap が dict でも `key` が空や文字列でない場合、`events=0` のまま成功に見えて、
  実機 smoke で「何も出ない」原因が追いにくい懸念。

採用した判断:

- output runner は tap dispatch 前に `key` を検査し、空 / 非文字列 key は `invalid_pty_text_tap_key`
  として blocking reason に出す。
- invalid key tap は `taps` count に入れず、実際に送れた synthetic tap 数とずれないようにする。

追加した確認:

- runtime/output runner test で空 key tap が `result=blocked`, `events=0`, `taps=0`,
  `blocking_reasons=["invalid_pty_text_tap_key"]` になること。

## 2026-06-14 invalid text tap modifier guard slice

つぶした懸念:

- PTY output plan の `modifiers` が誤って文字列で来た場合、文字列を iterable として 1 文字ずつ
  modifier 扱いし、host へ意味のない synthetic key events を出す懸念。
- 空文字 modifier を silently drop すると、実際に送れた modifier と plan の不整合が見えにくい懸念。

採用した判断:

- output runner は tap dispatch 前に `modifiers` を検査し、`None` または list だけを受ける。
- list 内の modifier は非空文字列だけを許可し、不正な modifier があれば tap 全体を
  `invalid_pty_text_tap_modifier` として blocked にする。
- `_dispatch_tap()` 側も防御的に list 以外の modifiers を空扱いし、直接呼び出しでも文字列を
  1 文字ずつ dispatch しない。

追加した確認:

- runtime/output runner test で `modifiers="KC_LSHIFT"` と `modifiers=[""]` がどちらも
  `result=blocked`, `events=0`, `taps=0`,
  `blocking_reasons=["invalid_pty_text_tap_modifier"]` になること。

## 2026-06-14 echo-off receiver bootstrap / direct ANSI HID slice

つぶした懸念:

- Windows Terminal + WSL + `cat` の実機 smoke では、入力 echo と `cat` stdout の両方が見えた。
  `abc^[[3DX` と `Xbc` が二重に出るため、ユーザーが毎回 `stty -echo` を意識する必要がある懸念。
- `wsl bash -lc "printf %s '<base64>' | base64 -d"` wrapper は focus が外れた時に長いコマンド断片を
  shell へ残し、復旧を難しくする懸念。
- receiver 起動直後にPTY outputを送ると、WSL shellが `cat` に入る前に出力が混ざる懸念。

採用した判断:

- 通常のPTY output plan は `direct_hid_ansi` に切り替え、`Esc` は `KC_ESC`、printable ASCII は
  US sub keyboard tap、CR/LF は `KC_ENTER` として送る。
- 最初のPTY text stream前に一度だけ receiver bootstrap plan を差し込む。
  receiver command は `trap 'stty echo' EXIT INT TERM; stty -echo; cat` とし、終了時にechoを戻しやすくする。
- receiver bootstrap plan には `post_gap_sec=0.250` を持たせ、`cat` 起動前に後続のPTY出力が入る
  可能性を下げる。
- OSC/title sequence (`ESC ] ... BEL` / `ESC ] ... ESC \`) はM0では送らず、未終端のterminal制御列を
  hostへ残さない。
- 旧 `wsl_cat_base64` helper は互換/比較用に残すが、通常の `SessiondPtyMirrorClient` 経路では使わない。

追加した確認:

- text plan test で receiver bootstrap plan が `wsl_cat_echo_off_receiver`、`post_gap_sec>=0.2`、
  最後のtapが `KC_ENTER` になること。
- text plan test で `ESC[31mRED ESC[0m` が `KC_ESC` + printable ASCII + `KC_ENTER` の直接HID planになること。
- text plan test で OSC title sequence が strip され、`osc_sequence_stripped` が記録されること。
- sessiond client test で最初のPTY text plan群に receiver plan が一度だけ入り、以後は
  `direct_hid_ansi` planでPTY textを送ること。

## 2026-06-14 KC_SH7 operator escape slice

つぶした懸念:

- focus ずれや receiver 同期ずれが起きた時に、host へ追加 HID を送り続けず keyboard 側だけで
  PTY mirror を止める緊急脱出操作が必要。
- active 中の `KC_SH7` を通常 PTY 入力へ流すと、脱出操作として使えず、復旧に SSH 操作が必要になる懸念。

採用した判断:

- M0 では `KC_SH7` を start key 兼 operator escape key とする。
- mirror inactive 中の `KC_SH7` press は従来通り start。
- mirror active 中の `KC_SH7` press は `PtyMirrorRuntime.stop(reason="operator_escape")` を呼び、
  `PTY EXIT\noperator_escape` を OLED alert に出す。
- active 中の `KC_SH7` release も消費し、PTY 入力や通常 HID 出力へ流さない。

追加した確認:

- runtime test で active 中の `KC_SH7` press/release が sessiond key input へ送られず、
  client stop reason が `operator_escape` になること。

## 2026-06-14 direct ANSI HID timing slice

つぶした懸念:

- 実機 smoke でPTY outputの反応が数秒単位に見えた。OLED上のCPU負荷は高くなく、HID tapの
  送信待機が支配的になっている懸念。
- 旧既定の `hold=0.006s`, `gap=0.020s` を direct ANSI output にも使うと、100 tapで約2.6秒、
  256 tapでは6秒級になる。
- PTY outputのCRLFを `KC_ENTER` 2回として送ると、遅延と余分な改行の両方が増える懸念。

採用した判断:

- receiver bootstrap command は shell 入力の安定性を優先し、`hold=0.006s`, `gap=0.020s` を維持する。
- direct ANSI output plan は `tap_hold_sec=0.002`, `tap_gap_sec=0.004` を持たせ、通常出力を高速化する。
- output runner は plan ごとの `tap_hold_sec` / `tap_gap_sec` / `post_gap_sec` を読む。
- CRLF (`\r\n`) は1つの `KC_ENTER` tapへ畳み、CR単独 / LF単独は従来通り `KC_ENTER` とする。

追加した確認:

- text plan test で receiver plan と direct output plan の timing metadata を固定。
- text plan test で `a\r\nb` が `KC_A`, `KC_ENTER`, `KC_B` になることを確認。
- runtime/output runner test で plan ごとの hold/gap/post_gap が sleep順序へ反映されること。

## 2026-06-14 receiver echo restore / dispatch observability slice

つぶした懸念:

- 実機 smoke で `Ctrl-C` により Windows Terminal 側の `cat` receiver を抜けても、terminal echo が
  off のまま戻らないことがあった。
- `trap 'stty echo' EXIT INT TERM; stty -echo; cat` では、`Ctrl-C` が foreground の `cat` にだけ届くと
  shell 側の trap が走らない場合がある。
- shell応答が画面に出ない時、Pi側PTY出力を受信しているのか、HID dispatchで落ちているのかが
  journalから分かりにくい。

採用した判断:

- receiver command は `stty -echo; cat; stty echo` に変更する。`cat` が `Ctrl-C` で終了した後、
  shell が次の `stty echo` を実行しやすい形にする。
- `logicd.input_events` は PTY output dispatch の `result` / `plans` / `taps` / `events` /
  `blocking_reasons` を info log に残す。

追加した確認:

- text plan test で receiver command が `; stty echo` で終わることを確認。

## 2026-06-14 receiver cleanup on operator escape slice

つぶした懸念:

- `KC_SH7` で PTY mirror mode を止めても、Windows Terminal 側の echo-off `cat` receiver が残る。
- operator が手動 `Ctrl-C` で `cat` を抜けた時に echo restore が安定しない場合、以後の入力が見えず
  復旧操作が分かりにくい。
- `KC_SH7` release が mode 停止後に通常 HID へ落ちると、緊急脱出キーとしての責任範囲が曖昧になる。

採用した判断:

- `logicd` は `operator_escape` と `output_switch` の停止時に receiver stop plan を dispatch する。
- receiver stop plan は synthetic HID の `Ctrl-C` (`KC_LCTRL` + `KC_C`) だけを host へ送り、
  `source=pty_terminal_mirror` の loop guard により Pi側PTY入力へ戻さない。
- receiver command は `stty -echo; cat; stty echo` なので、`Ctrl-C` で `cat` が終了した後に
  `stty echo` が実行されることを期待する。
- `KC_SH7` press で `operator_escape` した後の release も消費し、host HID や PTY input へ流さない。

追加した確認:

- text plan test で receiver stop plan が `wsl_cat_echo_off_receiver_stop`、
  `KC_LCTRL` + `KC_C` の1tapになることを確認。
- runtime test で `operator_escape` 停止時に receiver stop plan の synthetic events が出ることと、
  `KC_SH7` press/release が sessiond key input へ送られないことを確認。
- 実機 `<keyboard-host>` で `sessiond_ctl` から `printf READY_FROM_PTY` を実行し、
  `READY_FROM_PTY` と bash prompt が `pty_text_stream` として戻ることを確認。
  この結果から、shell応答未表示時の第一容疑は Pi側PTYではなく、`logicd` output dispatch、
  HID route、receiver focus、または Windows Terminal 側 receiver 状態とする。

## 2026-06-14 receiver canonical-mode follow-up

つぶした懸念:

- 実機 smoke で receiver command は見え、`logicd` の dispatch log も `result=ok` / `taps>0` だったが、
  Windows Terminal 上に shell応答が見えなかった。
- `stty -echo` だけでは terminal が canonical mode のままで、`cat` が Enter まで入力を受け取らず、
  PTY output を1文字ずつ HID送信しても画面に即時反映されない。
- `Ctrl-C` で `cat` は抜けても echo が戻らない場合があり、手動復旧が必要になる。

採用した判断:

- receiver bootstrap command を `stty -echo -icanon min 1 time 0; cat; stty sane` に変更する。
- `-icanon min 1 time 0` により、direct ANSI HID output を1文字単位で `cat` stdout へ通す。
- receiver stop plan は `Ctrl-C` を2回送り、Enterを挟んでから `stty sane` + Enter を送る。
  各段に `post_gap_sec=0.350` を持たせ、host側の取りこぼし時にも復帰しやすくする。
- output runner は tap ごとの `post_gap_sec` を読み、`Ctrl-C` 後だけ待機を長くできるようにする。

追加した確認:

- text plan test で receiver bootstrap command が `-icanon min 1 time 0` と `stty sane` を持つことを確認。
- runtime test で receiver stop plan が二重 `Ctrl-C` の後に `stty sane` + Enter を出すことを確認。
- output runner timing test で tap-level `post_gap_sec` が plan gap より優先されることを確認。

## 2026-06-14 PTY key alias follow-up

つぶした懸念:

- 実機 keymap の Enter は `KC_ENT` だが、sessiond の M0 PTY変換表は `KC_ENTER` のみ対応していた。
- そのため `ls` / `pwd` などの文字キーは bash PTY へ入り、echo が `lspwdls` として mirror される一方、
  Enter が空入力になりコマンドが確定しなかった。

採用した判断:

- `KC_ENT` と `KC_RETURN` を `KC_ENTER` と同じ `\r` に対応させる。
- Backspace も実機 keycode alias に合わせ、`KC_BSPACE` / `KC_BACKSPACE` を `KC_BSPC` と同じ
  DEL (`0x7f`) に対応させる。

追加した確認:

- `script/test_sessiond_pty_mirror.py` で Enter / Backspace alias が PTY bytes へ変換されることを確認。

## 2026-06-14 space / readline backspace echo follow-up

つぶした懸念:

- 実機からの Space は `KC_SPC` として届いていたが、sessiond PTY入力変換表は `KC_SPACE` のみ対応していた。
  そのため `ls -alF` の space が消え、`ls-alF` として bash へ渡っていた。
- Backspace は `KC_BSPC` -> DEL (`0x7f`) として PTY へ届き、bash/readline 側の入力削除は動いていた。
  一方、readline の表示 echo は `BS SPACE BS` (`\x08 \x20 \x08`) のような制御文字列で返るため、
  direct ANSI HID text plan が unsupported control char として plan 化できず、Windows Terminal 側の
  見た目だけ戻らなかった。

採用した判断:

- `KC_SPC` を `KC_SPACE` と同じ ASCII space (`0x20`) に対応させる。
- PTY出力側の `\x08` は receiver terminal へ `Ctrl-H` として送る。`BS SPACE BS` は
  `Ctrl-H`, Space, `Ctrl-H` になり、通常の terminal と同じ削除 echo として扱う。
- 入力削除は引き続き PTY へ DEL を送り、画面更新は PTY/bash/readline から戻った echo を反映する。
  logicd 側で独自に行編集状態を持たない。

追加した確認:

- `script/test_sessiond_pty_mirror.py` で `KC_SPC` が space byte へ変換されることを確認。
- `script/test_logicd_pty_terminal_text.py` で `\x08 \x08` が `Ctrl-H`, Space, `Ctrl-H` の HID tap に
  変換されることを確認。

## 2026-06-14 chunked output backpressure follow-up

つぶした懸念:

- `ls` のような長い出力が M0 の text safety limit に当たると、truncate では shell output や
  prompt を失い、端末としての信頼性が下がる。
- prompt-preserving truncate も応急処置にはなるが、出力を捨てる点は同じなので運用上よくない。
- HID送信速度より PTY出力が速い場合、logicd 側で送信可能な単位へ分割し、送信が終わるまで
  次の入力処理を急がない backpressure が必要。

採用した判断:

- PTY output は切り捨てず、既定 256 文字ごとの direct ANSI plan に分割する。
- `SessiondPtyMirrorClient` は1つの `pty_text_stream` から複数の text plan を返す。
- `dispatch_pty_mirror_text_plans()` は複数 plan を順に HID 送信するため、送信中は
  `handle_resolved_action()` が戻らず、M0 の入力処理に自然な backpressure がかかる。
- さらに大きい出力で詰まる場合は、sessiond 側の drain/read window と logicd 側の送信完了通知を使う
  明示的な flow control を次の候補にする。

追加した確認:

- text plan test で長い出力が複数 chunk になり、`truncated=False` のまま末尾 prompt を含む text が
  保持されることを確認。

## 2026-06-14 chunked HID pacing / typeahead follow-up

つぶした懸念:

- 実機 smoke では `ls` 出力について `logicd` log が `plans=5 taps=1270 result=ok` を記録した一方、
  Windows Terminal 表示は転送途中で止まった。Pi/logicd側は送信完了扱いでも、host側が
  長い HID burst を途中で取りこぼす懸念。
- 出力表示中の operator 入力を消費する guard は通常の terminal と異なり、typeahead を壊す。
  出力中入力は PTY 側へ流し、bash/readline に任せる方が自然。

採用した判断:

- 複数 chunk に分割された長い出力だけ、direct output timing を `hold=0.003s` / `gap=0.020s` /
  `post_gap=0.500s` に落とす。短い応答は従来の高速設定を維持する。
- 長い出力は 64 文字単位の短い送信 window に分割し、host側が一定量の keyboard tap burst で
  止まる症状を避ける。
- `ls` などの列表示に多い4文字以上の連続空白は、space連打ではなく ANSI cursor-forward
  (`ESC [ n C`) に圧縮し、hostへ送る HID tap 数を減らす。
- 出力中入力を guard / queue / drop しない。通常の terminal と同じように sessiond PTY へ流し、
  bash/readline の typeahead と echo に任せる。

追加した確認:

- text plan test で chunked output の timing metadata が低速側になることを確認。
- text plan test で連続空白が `ESC[nC` に圧縮されることを確認。
- runtime test では output-busy input guard を置かず、通常の route が維持されることを前提にする。

## 2026-06-14 chunk boundary / pacing follow-up

つぶした懸念:

- 実機 `ls -aalF` smoke では 4036 文字の PTY output が `plans=63 taps=3915` になり、
  HID送信完了まで約2分かかった。Windows Terminal 側では途中で止まったように見えたが、
  logicd log では送信継続中だった。
- 文字数固定の chunk 分割は `\r\n` の間を割る可能性があり、CR と LF を別々の Enter 相当として
  送って余計な空行を作る懸念がある。

採用した判断:

- chunk 分割は CRLF をまたがない。必要なら最大長を1文字だけ超えて `\r\n` を同じ chunk に残す。
- 長い出力の chunk window は 96 文字へ広げる。
- chunked output timing は `hold=0.002s` / `gap=0.006s` / `post_gap=0.040s` に調整する。
  初期の `post_gap=0.500s` は host 側 burst 回避には安全寄りだったが、軽作業用途としては待ちが長すぎる。

追加した確認:

- text plan test で CRLF 境界が chunk 間で割れず、単一の Enter tap として残ることを確認。
- text plan test で chunked output の timing metadata が新しい推奨値になることを確認。

## 2026-06-14 faster chunked output follow-up

つぶした懸念:

- CRLF-safe chunking と `post_gap=0.040s` で空行と長い停止感は改善したが、軽作業用 terminal としては
  まだ出力待ちが長い。
- 前回設定で余計な空行、長い停止感、SH7復帰が改善したため、host 側の取りこぼし余裕を見ながら
  もう一段速い pacing を試せる。

採用した判断:

- chunk window を 128 文字へ広げる。
- chunked output timing は `hold=0.001s` / `gap=0.003s` / `post_gap=0.020s` にする。
- 取りこぼしや表示欠けが再発した場合、この fast pacing commit だけを戻す候補にする。

追加した確認:

- text plan test で chunked output の timing metadata が fast pacing 値になることを確認。

## 2026-06-14 delayed prompt drain / faster output follow-up

つぶした懸念:

- `sudo -s` 実行後、次の入力をするまで root prompt が表示されなかった。PTY 側では command commit 後に
  少し遅れて prompt が出るが、sessiond が key input 後 0.2 秒だけ読んで応答を閉じるため、遅延出力が
  次回入力まで拾われない。
- fast pacing 後も軽作業用途としてはまだ出力が少し遅い。

採用した判断:

- `KC_ENTER` / `KC_ENT` / `KC_RETURN`、または `bytes_hex` が CR/LF で終わる command commit 入力だけ、
  まず 0.2 秒 drain し、`$` / `#` prompt で終わっていない時だけ追加で 0.65 秒追い読みする。
- 通常文字入力や Backspace の echo は従来通り 0.2 秒 drain のままにし、1文字入力の反応を重くしない。
- chunk window を 160 文字へ広げ、chunked output timing を
  `hold=0.0005s` / `gap=0.0015s` / `post_gap=0.010s` にする。
  取りこぼしが再発する場合はこの速度調整を戻す。

追加した確認:

- socket test で `sleep 0.35; printf ...` の遅延出力が同じ key input 応答内で拾われることを確認。
- text plan test で chunked output の timing metadata が新しい高速値になることを確認。

## 2026-06-14 turbo chunked output follow-up

つぶした懸念:

- 実機貼付ログを確認したところ、`ls -alF` は実機の現在出力 55 行と一致し、`env` block も壊れた行や
  置換文字がなかった。現行 faster pacing では文字欠けは確認できない。
- まだ体感として少し遅いため、長い出力だけさらに大胆に詰める余地がある。

採用した判断:

- chunk window を 240 文字へ広げる。
- chunked output timing は `hold=0.0s` / `gap=0.0s` / `post_gap=0.002s` にする。
- 短い direct output timing は据え置き、通常の echo / small response で無理に挙動を変えない。
- 表示欠けや取りこぼしが出た場合は、この turbo pacing commit を戻すか、直前の
  `hold=0.0005s` / `gap=0.0015s` / `post_gap=0.010s` に戻す。

追加した確認:

- 添付ログの `ls -alF` block が実機の `ls -alF` と行数・内容とも一致することを確認。
- 添付ログの `env` block に `=` を含まない壊れた行がなく、長い `LS_COLORS` と末尾 `_=` が残ることを確認。
- text plan test で chunked output の timing metadata が turbo 値になることを確認。

## 2026-06-14 async output queue follow-up

つぶした懸念:

- `ls` などの長い出力後、人間の感覚で次のコマンドを打っても、数秒待ってから入力がまとめて処理された。
- これは `sessiond` 側の遅延 prompt 問題とは逆で、`logicd` が PTY output の HID描画を
  `handle_resolved_action()` 内で最後まで `await` していたため、物理キー入力イベント自体が後ろに並んでいた。
- turbo pacing で sleep はほぼなくなったが、数千 tap の `dispatch_action_event()` は依然として
  event loop 上で直列に走るため、入力処理を塞ぐ。

採用した判断:

- start / receiver bootstrap、operator escape、output switch、receiver stop は安全のため同期 dispatch のままにする。
- 通常の PTY output text plan だけ、`InputEventContext` 上の `pty_mirror_output_queue` へ積み、
  1本の background worker が直列に HID 送信する。
- これにより HID 出力同士は混ざらず、物理キー入力は出力描画完了を待たずに PTY へ届く。
- SH7 operator escape や output switch 時は、残っている output queue / worker を cancel してから
  receiver stop を送る。

追加した確認:

- runtime test で通常 PTY output が handler return 後に queue drain されることを確認。
- runtime test で background output dispatch failure が従来通り `output_dispatch_failed` で mode stop することを確認。

## 2026-06-14 cooperative turbo output follow-up

つぶした懸念:

- turbo pacing は `hold=0` / `gap=0` のため、background output queue 化後も worker が数千 tap を
  ほぼ休まず回し、同じ asyncio event loop 上の物理入力処理へ制御を返しにくい。
- 画面上の出力が完了したように見えても、内部的な tap/release dispatch が残っている間、
  typeahead が遅れる可能性がある。

採用した判断:

- PTY output runner は 16 tap ごとに `asyncio.sleep(0)` で協調 yield する。
- 実時間の待機は増やさず、event loop に入力処理や sessiond routing を挟む機会だけを作る。
- `hold/gap/post_gap` の turbo 値は維持する。

追加した確認:

- runtime test で 16 tap の turbo plan が `sleep(0)` を1回呼ぶことを確認。

## 2026-06-14 typeahead display interleave decision

実機テスト結果:

- `ls -alF` 完了後に `pwd` / `uname -a` / `env` を続けて入力しても、以前のように数秒待ってから
  まとめて処理される挙動は解消した。
- 2回目の `env` 出力中に次のコマンドを入力したところ、入力は反応した。
- その一方で、`env` の長い `LS_COLORS` 行や後続の prompt 表示には、typeahead の文字が混ざって
  `LS_COuLORS`、`COLUMS`、`USER=fujik0awa`、`_=/usr/` 改行 `bin/env...` のような表示崩れが見えた。

採用した判断:

- 出力中の typeahead が表示へ混ざることは通常の terminal でも起こり得るため、M0では許容する。
- 入力を output 完了まで buffer して表示を綺麗に保つ案は採用しない。軽作業用 terminal としては、
  表示の完全性より、入力が待たされず PTY へ届くことを優先する。
- 問題として扱うのは、入力が数秒待たされる、文字が欠ける、コマンドが PTY へ届かない、
  SH7 / receiver stop で復帰できない、の4つとする。
- 表示混在が気になる場合の運用回避は、長い出力中は待ってから入力する、または `less` / `head` /
  `grep` などで出力量を抑えることにする。

残す懸念:

- 将来 M1 以降で表示品質を上げるなら、logicd で typeahead を buffer するのではなく、
  terminal helper / host app 側で PTY stream と user input echo をより自然に扱う方向がよい。
- HID keyboard transport だけで完全な端末描画と即時 typeahead を両立するには限界がある。

## 2026-06-14 current state and next work

現在の状態:

- M0 は「HDMIなし軽作業用の experimental terminal mirror」として成立し始めている。
- operator は Windows Terminal の WSL shell に focus し、`KC_SH7` で receiver bootstrap
  (`stty -echo -icanon min 1 time 0; cat; stty sane`) と Pi 側 bash PTY を開始する。
- PTY output は ANSI / ASCII HID tap として Windows Terminal の receiver へ送る。
- 通常の PTY output は logicd の background queue で直列送信し、物理キー入力は output 描画完了を
  待たずに sessiond PTY へ届く。
- long output は CRLF-safe chunking、space run の `ESC[nC` 圧縮、turbo pacing
  (`hold=0.0s` / `gap=0.0s` / `post_gap=0.002s`) を使う。
- turbo output runner は 16 tap ごとに `asyncio.sleep(0)` で event loop へ協調 yield する。
- command commit (`KC_ENTER` / `KC_ENT` / `KC_RETURN`、または CR/LF 終端 write) では、
  prompt がすぐ出ない場合だけ追加 drain し、`sudo -s` のような遅延 prompt を次入力待ちに回しにくくする。
- `KC_SH7` operator escape、output switch、receiver stop は同期 dispatch のまま残し、
  残り output queue を cancel してから receiver stop を送る。
- 現時点では sessiond は user 権限の手動起動扱いで、root system service 化は M0 smoke 後に判断する。

固定した判断:

- typeahead は通常端末相当として即 PTY へ流す。
- 長い出力中に入力 echo が表示へ混ざることは M0 では許容する。
- logicd で typeahead を buffer して表示を綺麗に保つ案は採用しない。
- 問題扱いするのは、入力が数秒待たされる、文字が欠ける、コマンドが PTY へ届かない、
  SH7 / receiver stop で復帰できない、の4つ。
- 表示混在が気になる運用では、長い出力を待つか、`less` / `head` / `grep` などで出力量を抑える。
- host helper / dedicated terminal app は M0 では作らない。必要性が出たら M1 以降で再検討する。

実機で確認済み:

- `ls -alF` は実機現行出力 55 行と一致し、文字欠けは見えない。
- `env` の長い `LS_COLORS` を含む出力は、入力を重ねない場合は壊れた行や置換文字なし。
- `ls -alF` 後に `pwd` / `uname -a` / `env` を続けて入力しても、以前のように数秒待って
  まとめて処理される挙動は解消した。
- 2回目の `env` 出力中 typeahead では表示 interleave が見えたが、入力自体は反応した。
- `sudo -s` 後の root prompt は、command commit 後の追加 drain で次入力待ちに回りにくくなった。
- SH7 operator escape 後、receiver `cat` と host echo は戻る。

次の作業予定:

1. 実機 smoke をもう少し増やす:
   `ls -alF`、`env`、`pwd`、`uname -a`、`sudo -s` / `exit`、`sleep 2` + `Ctrl-C`、Backspace line edit、
   SH7 start/stop を同じ receiver session で繰り返す。
2. failure criteria に該当する事象だけを優先して潰す:
   入力待ち、文字欠け、PTY未達、SH7復帰不能、receiver echo 復帰失敗。
3. 文字欠けが再発した場合は、turbo pacing だけを戻す:
   まず `hold=0.0005s` / `gap=0.0015s` / `post_gap=0.010s` へ戻し、
   それでも不安定なら chunk window を 160 または 128 へ戻す。
4. 入力待ちが再発した場合は、output runner の cooperative yield 間隔を 16 tap から 8 tap へ詰める。
   それでも残る場合は output dispatch と input routing の event loop 分離を検討する。
5. receiver / echo 復帰失敗が再発した場合は、receiver stop plan と `stty sane` 復帰手順を優先して見直す。
6. M0 smoke が安定したら、sessiond の user service 化、ログレベル整理、OLED status の文言、
   runbook / checklist への転記を行う。
7. M1 候補として、host helper / dedicated terminal app、非HID transport、screen diff の高精度化を
   別設計として切り出す。

## 2026-06-14 stderr / OSC stripping follow-up

つぶした懸念:

- `ls-alF` のような誤入力では bash の stderr が返るはずだが、画面にエラーが出なかった。
- no-HID smoke では `bash: ls-alF: command not found` が `pty_text_stream` に戻っていたため、
  stderr 自体は PTY で stdout と同じ stream に入っている。
- 問題は `ESC ] ... BEL` の OSC title sequence を strip した時に `osc_sequence_stripped` を
  blocking reason として扱い、本文を含む plan 全体を `available=False` にしていたこと。

採用した判断:

- OSC title sequence は引き続き host へ送らず strip する。
- ただし strip は非致命の `stripped_reasons` として記録し、本文や stderr は送信する。

追加した確認:

- text plan test で OSC title を含む `bash: ... command not found` が `available=True` のまま
  tap plan 化されることを確認。

## 2026-06-14 remote / real-device split

採用した切り分け:

- リモートで進める範囲は、`sessiond` protocol、PTY wrapper、socket lifecycle、CLI、
  `logicd` client、runtime routing、output plan 生成、output runner の pacing / yield、
  stop / unavailable / blocked plan handling までとする。
- 実機が必要な範囲は、Windows Terminal focus、US sub keyboard endpoint の実HID到達、
  receiver `cat` の肉眼表示と echo 復帰、OLED alert / status の見え方、体感速度、
  host layout / terminal app 固有挙動に限定する。
- 文字欠けや入力待ちの疑いが出た時は、先にリモート suite で PTY 入出力と plan 生成が壊れていないかを確認し、
  そこが通る場合だけ実HID / Windows / focus の問題として切り分ける。
- 実機側でしか見えない問題でも、再発条件を `sessiond_ctl` や no-HID integration に落とせる場合は
  先にリモート regression へ固定する。

追加した準備:

- `script/test_pty_mirror_remote_suite.py` を追加し、PTY mirror の実機なし確認セットを
  1コマンドで回せるようにした。
- [../../../ops/pty-terminal-mirror-smoke.md](../../../ops/pty-terminal-mirror-smoke.md) に、リモートで確認できる項目と
  実機待ちに残す項目を分けて記録した。

次にリモートで進める候補:

1. 添付された実機ログと同じ文字列を `build_pty_terminal_text_plans()` に通し、tap plan から復元した文字列が
   欠けないことを regression 化する。
2. 長い `env` / `ls -alF` 相当の plan で、chunk boundary、CRLF、space-run 圧縮、OSC strip の境界を増やす。
3. output queue cancel 後に stale plan / stale error が残らないことを、より大きな queue で確認する。
4. 実機 smoke のログ採取コマンドを `tools/` helper 化し、Windows 目視結果と Pi 側 journal を突き合わせやすくする。
