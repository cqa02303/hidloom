# sessiond PTY terminal mirror design

作成日: 2026-06-14

この文書は、HDMI 出力がない状態でも Raspberry Pi 側のコンソール操作に近い体験を得るため、
Pi 内部の PTY セッションを Windows 側ターミナルへ HID keyboard 入力として mirror する機能の
責務境界と初期マイルストーンを固定します。

## Goal

- 物理キーボード入力を Pi 側の仮想端末 PTY へ routing する。
- PTY stdout/stderr を terminal screen buffer に反映し、ANSI escape sequence の差分文字列へ変換する。
- 差分文字列は `logicd` の text-send / host profile / safety gate で HID keyboard tap sequence に変換する。
- 最終的な USB HID report 書き込みは `usbd` の broker / endpoint owner に集約する。
- 初期実装は user 権限の shell、US ASCII、最小 control code、`exit` による mode exit に限定する。

## Non-goals

- 初期マイルストーンでは root shell を起動しない。
- 初期マイルストーンでは Windows helper app を必須にしない。
- 初期マイルストーンでは Raw HID companion route、IME 制御、広範な JIS 記号入力、高速全画面描画を要求しない。
- 初期マイルストーンでは Windows 側 terminal focus の自動検出をしない。
- 初期マイルストーンでは Pi 側の既存 login console へ attach しない。新規 user 権限 PTY session を起動する。
- 初期マイルストーンでは新しい mode switch 用 virtual keycode を増やさない。
- `usbd` は PTY セッション状態、terminal diff、host layout policy を持たない。
- `sessiond` は `/dev/hidg*` を直接開かない。

## Decisions

現時点で決めたこと:

- daemon 名は `sessiond` とする。
- HID transport owner は `usbd` のままにする。
- ANSI text stream から HID keyboard tap sequence への変換は `logicd` に戻す。
- PTY session、PTY input byte 変換、screen buffer、ANSI diff 生成は `sessiond` が持つ。
- loop guard は `logicd` が持つ。`source=pty_terminal_mirror` を再度 macro / interaction / text-send 入力として解釈しない。
- M0 の標準出力 route は US sub keyboard endpoint (`kind=us_sub_keyboard` / `/dev/hidg2`) にする。
- M0 は user 権限の shell だけを起動する。
- M0 の入力 scope は US ASCII printable と小さい control code だけにする。
- `exit` / EOF / PTY child exit で mirror mode を抜ける。
- mirror mode 開始は、M0 では既存 `KC_SH7` を logicd start handler として扱い、
  `sessiond` owned socket へ `start_pty_mirror` を送る。
  `KC_SH7.sh` は manual fallback として残す。
- M0 は小さい軽作業用の experimental mode として扱う。full-screen TUI や長時間作業は対象外にする。
- `sessiond` / `logicd` が落ちた場合は、mirror mode 終了として扱う。
- bandwidth / latency は M0 では experimental として扱い、row-level diff から始める。
- helper app / Raw HID companion は初期必須ではなく、将来の性能・信頼性改善オプションにする。

## Working assumptions

実装前提として、次を仮定する。

- Windows Terminal は ANSI escape sequence を解釈する。
- operator は mirror mode 開始前に Windows Terminal の安全な pane/input へ focus できる。
- operator の現在の Windows Terminal 起動サイズは 120x35 であり、M0 の初期 screen size も 120x35 にする。
- US sub keyboard endpoint は Windows 側で US layout として扱われる。認識が完全でない場合でも、
  通常 keyboard として US 記号入力に寄る可能性が高い。
- `[`、`]`、`;`、数字、英字、`ESC`、改行が安定して入力できれば、M0 の row-level ANSI diff は成立する。
- 既存 `text_send_runner` の cancel / timeout / zero-report 方針は terminal mirror の synthetic text stream にも再利用できる。
- PTY child は user 権限で起動し、root への昇格や destructive command は機能の責務外に置ける。
- 実用性は HID typing 帯域に依存するため、M0 は「使えるかを見る」実験機能とする。
- M0 の用途は短い shell 操作、状態確認、`echo` / `cat` / 小さい command 実行程度の軽作業に限定する。

## Design intent

この機能は、Windows 側に terminal session を作る機能ではない。
Windows Terminal は表示器であり、実際の端末 session、入力 routing、shell process は Pi 側にある。

このため、Windows から Pi へ入力を戻す channel は M0 では不要です。
物理キーボード入力はもともと Pi に入っているので、mirror mode 中だけ `logicd -> sessiond` へ routing すればよい。
PTY output だけを Windows Terminal へ HID keyboard 入力として描く。

ただし Windows 側への描画も keyboard input なので、focus 誤爆すると普通の大量入力になる。
これは transport の制約として受け入れ、explicit enable、arming、timeout、cancel で守る。

Windows Terminal は ANSI escape sequence を process output として受けた時に解釈する。
HID keyboard で `ESC [ 2 J` をそのまま入力しても、多くの場合は shell/readline への入力であり、
terminal output として解釈されない。そのため M0 の Windows Terminal smoke は、
WSL が使える前提で `wsl bash -lc "printf %s '<base64>' | base64 -d"` command を typing し、
ANSI text を process output として出す方式にする。

M0 は「HDMI なしで少し触れる」ための fallback であり、SSH や通常の terminal transport の代替ではない。
長時間操作、full-screen TUI、log tail、editor、package install のような大量出力作業は後続で性能と安全性を見てから扱う。

## Alternatives considered

| 案 | 採用判断 | 理由 |
| --- | --- | --- |
| `sessiond -> usbd` に text stream を直接送る | 不採用 | text stream から HID tap への変換は layout / profile / cancel を含むため `logicd` の責務に近い |
| `usbd` が ANSI / layout / text-send を理解する | 不採用 | `usbd` が USB transport owner から入力意味論 owner へ膨らむ |
| Windows helper app を必須にする | M0 では不採用 | 既存 US sub endpoint を使えば US ASCII ANSI の実験は helperless で始められる |
| Raw HID companion を使う | M0 では不採用 | layout 非依存 / 高速化には有効だが、初期確認には重い |
| `logicd` が PTY を直接持つ | 不採用寄り | `logicd` が keymap/action 解決に加えて PTY process / screen buffer まで抱えると肥大化する |
| 既存 login console へ attach する | M0 では不採用 | 権限、session state、復旧時の扱いが重い。まず user 権限の新規 PTY session にする |
| mirror mode 用 virtual keycode を追加する | M0 では不採用 | 後に残る surface を増やすより、既存 `KC_SH7` action から明示起動する方が可逆で軽い |

## Daemon boundary

候補 daemon 名は `sessiond` とする。`hostd` よりも、PTY / uinput / debug などの
出力先セッションを owner にする意味が明確なため。

```text
matrixd
  -> logicd
      keymap / layer / interaction / action 解決
      loop guard / source tag guard
      text stream -> keyboard tap sequence
      host profile / layout / safety gate
      -> sessiond
          mode=pty_terminal
          mode=uinput_policy
          PTY session owner
          terminal screen buffer / ANSI diff owner
      -> usbd
          USB HID endpoint owner
          HID report broker owner
          Raw HID / Vial multiplex owner
```

実際の terminal mirror data path は次の向きにする。

```text
physical key
  -> matrixd
  -> logicd
  -> sessiond mode=pty_terminal
      key event -> PTY byte
      PTY output -> screen buffer
      screen diff -> ANSI text stream
  -> logicd
      text stream -> HID keyboard tap sequence
  -> usbd
      keyboard report
```

`sessiond -> logicd` へ戻す理由は、ANSI 文字列から HID keyboard tap sequence への変換が
transport ではなく入力意味論だからです。`ESC`、`[`、`;`、US/JIS layout、tap gap、
cancel、timeout、host profile gate は `logicd` の既存 text-send 系責務に近い。
`usbd` は最終 report / endpoint / reconnect / broker readiness に集中する。

IPC は、可能なら `sessiond` 側の単一 local socket で往復する案を優先候補にする。
`logicd` はすでに大きいため、M0 では `logicd` 側に新しい待ち受け socket を増やさない方向で考える。
`logicd -> sessiond` の start/input/control と、`sessiond -> logicd` の text stream/status を
同じ sessiond-owned socket 上の request/stream として扱えるなら、その方が単純です。
ただし実装時に双方向 stream が複雑になる場合は、`sessiond` socket は維持したまま
message type を絞り、`logicd` 側は既存 event loop に接続 client として参加する。

## Loop guard

PTY mirror は、`logicd` に loop guard を持たせる。

- `source=pty_terminal_input`: 物理キーを PTY stdin へ routing する入力。
- `source=pty_terminal_mirror`: PTY output を Windows terminal へ描画するための synthetic text stream。
- `source=pty_terminal_mirror` から生成された HID tap sequence は、再度 interaction / macro / text-send source として解釈しない。
- mirror mode 中でも emergency release / mode exit / output switch は通常の安全経路を通す。
- `logicd` restart、`sessiond` disconnect、`usbd` broker unavailable では PTY mirror を停止し、通常 HID mode へ戻せる状態にする。
- `sessiond` process exit / heartbeat timeout は mirror mode 終了として扱う。
- `logicd` restart / shutdown は active PTY session を終了対象にし、再起動後に自動復帰しない。

loop guard で守りたい事故:

- PTY output の echo-back が再度 key action として処理され、PTY input へ戻る。
- terminal mirror 用の ANSI text stream が user macro / dynamic macro / text-send named entry として記録される。
- mirror 描画中の synthetic tap が interaction state machine の physical key として扱われる。
- mirror mode exit 後に stale modifier / stale key press が残る。

初期実装では `source` と `mode` の両方で guard する。
`source=pty_terminal_mirror` は output-only synthetic source とし、
physical matrix event と同じ queue に入る場合でも macro recording / interaction input / PTY input routing の対象外にする。

backpressure は M0 実装後の調整項目にする。
設計時点では、HID 送信待ちが詰まる可能性を認識するだけに留め、drop / merge / block の最終判断は
実際の typed ANSI throughput を見て決める。

M0 の仮決め:

- `sessiond` IPC は sessiond-owned local socket で始める。
- `logicd` はその socket に client として接続し、新しい listening socket を増やさない。
- `sessiond -> logicd` の mirror text stream は length-prefixed JSON line か newline-delimited JSON の小さい protocol で始める。
- message type は `start_pty_mirror`、`stop_pty_mirror`、`pty_key_input`、`pty_text_stream`、`pty_status` に絞る。
- protocol が詰まったら M0 内で見直すが、最初から汎用 RPC にはしない。

## Host layout and helper app position

初期マイルストーンは helper app なしで進める。
既存の JIS main / US sub split keyboard を前提にし、ANSI text stream は通常 typing と同じ
US sub keyboard endpoint を優先して送る。Windows 側で sub keyboard の認識が完全でない場合でも、
US keyboard として扱われる可能性が高いため、初期の ANSI 記号入力はこの endpoint を信じる。

条件:

- Windows Terminal など ANSI escape sequence を解釈する terminal app に operator が focus している。
- host profile は `windows_terminal_wsl_cat_us_sub_keyboard` のような明示 profile を要求する。
- `logicd` / broker route は `kind=us_sub_keyboard` / `/dev/hidg2` を ANSI text stream の標準出力先にする。
- 送信文字は US ASCII printable、`ESC`、`\r`、`\n`、`\t`、Backspace 相当、`^C` / `^D` などの小さい control code に限定する。
- `[`、`;`、数字、英字など ANSI diff に必要な文字が profile 上で入力できる場合だけ real send を許可する。

JIS/US layout 問題は touch flick / text-send と同じ課題です。
helper app を必須にしない解決の目はあるが、範囲を絞る必要がある。

- 標準 HID route: US sub keyboard endpoint / Windows Terminal ANSI / US ASCII に寄せる。
- JIS main route: `KC_ZKHK`、JIS 固有キー、IME control などは既存 `jis_special_us_default` 方針へ残し、ANSI mirror の M0 には混ぜない。
- profile gate: US sub endpoint で安定して出せる文字だけを allowlist にし、JIS 記号や IME state に依存する文字は default blocked にする。
- Raw HID / companion app: 将来の高速化、layout 非依存化、focus 誤爆低減の opt-in route として残す。

つまり helper app は初期必須ではなく、将来の性能・信頼性改善オプションとして扱う。

US sub endpoint を使う時の考え方:

- ANSI mirror の text stream は、通常文字入力と同じ US sub keyboard route を使う。
- Windows Terminal M0 では raw ANSI key tap ではなく WSL `printf | base64 -d` wrapper に包んで実行する。
- `KC_ZKHK`、`KC_RO`、`KC_JYEN`、`KC_HENKAN`、`KC_MUHENKAN` などは JIS main route のままにする。
- ANSI diff に必要な `ESC [ row ; col H` は US ASCII として出せることを期待する。
- Windows 側が sub keyboard を完全に US 101/102 として bind できない場合でも、通常 keyboard default は US 寄りに倒れると考える。
- profile が未設定、US sub endpoint が disabled、broker が `kind=us_sub_keyboard` を受けられない場合は real send しない。

helper app / Raw HID companion が必要になりそうな条件:

- focus 誤爆を Windows 側で検出・拒否したい。
- ANSI diff を keyboard tap ではなく byte stream として高速に送りたい。
- US/JIS layout や IME state の影響を完全に避けたい。
- Windows Terminal 以外の専用 viewer を使いたい。
- bidirectional control や clipboard / paste / resize event を扱いたい。

M0 では operator が Windows Terminal に focus していることを前提にする。
arming phrase や focus marker は後続候補であり、初期は operator 任せにする。

## Initial milestone

初期 milestone は `PTY mirror M0` とする。

受け入れ条件:

- `sessiond` design で PTY / uinput / HID transport owner 境界が明記されている。
- `logicd` loop guard が必要であることが明記されている。
- 初期 input scope は US ASCII printable と小さい control code に限定されている。
- ANSI text stream は US sub keyboard endpoint を標準 route にする。
- 初期 PTY は user 権限で起動する。
- `exit` で PTY session が終了した時、mirror mode を抜ける。
- ANSI diff は行単位差分を基本にし、帯域 / 遅延は experimental として扱う。
- helper app は初期必須ではなく、Raw HID / companion route は将来の opt-in として扱う。
- mode switch 用の新規 virtual keycode は追加せず、既存 `KC_SH7` script から開始する。
- M0 は軽作業用として扱い、full-screen TUI / editor / long-running log watch は対象外にする。

最小 key mapping:

| 入力 | PTY byte |
| --- | --- |
| US ASCII printable | 同じ byte |
| `KC_ENTER` | `\r` |
| `KC_TAB` | `\t` |
| `KC_BSPC` | `0x7f` |
| `KC_ESC` | `0x1b` |
| `C(KC_C)` | `0x03` |
| `C(KC_D)` | `0x04` |

矢印、function key、Alt sequence、IME、Unicode、paste、long text は M0 では対象外にする。

M0 の想定 user flow:

1. operator が Windows Terminal を開き、ANSI sequence を受ける pane に focus する。
2. keyboard 側で割り当て済み `KC_SH7` を押し、script が mirror start command を呼ぶ。
3. `logicd` が host profile、US sub endpoint、`sessiond` readiness、`usbd` broker readiness を確認する。
4. `sessiond` が user 権限 PTY shell として bash を起動する。
5. `sessiond` が初回描画 `ESC[2J ESC[H ...` を生成し、`logicd` が US sub keyboard route で送る。
6. 物理 key は mirror mode 中だけ PTY stdin へ routing する。
7. PTY output は row-level ANSI diff として coalescing 後に送る。
8. user が bash 上で `exit` を入力する。
9. PTY child exit / EOF を検出し、mirror mode を抜け、通常 HID routing に戻る。

M0 completion tests:

- static design test で daemon boundary、US sub route、loop guard、user 権限、`exit` mode exit が文書化されていることを確認する。
- pure helper test で key mapping table 相当の US ASCII / control code 変換を確認する。
- pure helper test で row-level diff renderer が ANSI text stream を生成できることを確認する。
- integration-ish unit test で `source=pty_terminal_mirror` が macro recording / PTY input routing 対象外になることを確認する。
- real-device smoke は Windows Terminal focus と US sub endpoint を使い、最初は短い prompt / `echo ok` / `exit` の範囲に限定する。
- 少し進んだ段階で bash を起動して US ASCII と `^C` / `^D` の小さい操作を確認し、bash `exit` で通常 mode に戻ることを確認する。

M0 implementation defaults:

| 項目 | 仮決め |
| --- | --- |
| protocol | sessiond-owned local socket, newline-delimited JSON first |
| `logicd` role | client only, no new listening socket |
| start trigger | existing `KC_SH7` script |
| shell | user 権限 bash |
| screen size | 120x35 fixed first |
| output route | US sub keyboard endpoint |
| focus | operator responsibility |
| failure | `sessiond` / `logicd` failure exits mirror mode |
| backpressure | merge latest row when possible, tune after smoke |
| logging | payload default off, debug opt-in only |

Recommended M0 initial values:

| 項目 | 初期値 |
| --- | --- |
| PTY columns | 120 |
| PTY rows | 35 |
| flush window | 50 ms |
| max flush rate | 20 fps |
| key tap hold | 6 ms |
| key tap gap | 20 ms for ASCII, 50 ms after ESC sequence chunk |
| startup alert | `PTY START`, 1.5 sec |
| exit alert | `PTY EXIT`, 2.0 sec |
| error alert | `PTY ERROR`, 3.0 sec, warning/inverted |
| idle timeout | none in M0; operator exits with bash `exit` |
| startup full refresh | enabled |
| periodic full refresh | disabled in M0 |
| max queued row updates | 35 rows, latest row wins |
| status refresh | ready screen refresh cadence; no high-rate OLED update |

## ANSI diff rendering

初期は cell-level diff ではなく row-level diff にする。

使用候補:

```text
ESC[2J        clear screen
ESC[H         home
ESC[{r};{c}H  cursor position
ESC[K         erase to end of line
ESC[?25l      hide cursor
ESC[?25h      show cursor
```

M0 は bandwidth / latency を experimental として扱い、rate limit / coalescing は設計だけ固定する。
実装時は 30-100ms 程度の flush window で PTY output をまとめ、同じ行の複数更新は最後の状態だけ送る。

考えている描画方針:

- 初回は `ESC[2J ESC[H` で clear + home し、表示範囲をまとめて送る。
- 通常更新は変更行ごとに `ESC[{row};1H` + line text + `ESC[K` を送る。
- cursor 表示は、最後に PTY cursor 位置へ `ESC[{row};{col}H` を送る。
- cursor のちらつきが大きい場合だけ `ESC[?25l` / `ESC[?25h` を使う。
- 画面サイズは M0 では 120x35 固定値から始める。resize は後続。
- ANSI parser は完全 terminal emulator を目指さない。scroll や wrap は通常の Windows Terminal app の責任範囲に寄せ、
  sessiond は必要最小限の clear / cursor move / line overwrite を送るだけにする。

懸念:

- shell prompt や full-screen app は ANSI の種類が多く、M0 では崩れる可能性がある。
- HID typing が遅いため、`top` や progress bar のような高頻度更新は追従できない可能性が高い。
- Windows Terminal 側の wrap / scrollback / cursor state と Pi 側 screen buffer がずれる可能性がある。
- `ESC[K` や cursor move が途中で欠けると、Windows 側表示が壊れる。
- M0 は lightweight shell work 向けなので、この崩れを完全には追わない。

## uinput policy

`sessiond` は将来、uinput 出力時の加工 owner も兼ねられる。

- `logicd` は action / layer / interaction 解決を維持する。
- `sessiond mode=uinput_policy` は host profile / layout / modifier policy / release safety を扱う。
- USB HID transport は引き続き `usbd`、Linux local injection は uinput backend として分ける。

PTY mirror M0 では uinput 移管は実装しない。責務境界だけ固定する。

考えている将来像:

- `sessiond mode=uinput_policy` は local Linux injection の layout / modifier / release policy を持つ。
- `sessiond mode=pty_terminal` は PTY session / terminal mirror を持つ。
- どちらも「logicd が解決した action を host/session へどう出すか」という隣接領域なので同じ daemon に置ける。
- ただし M0 で uinput 移管まで同時に進めると scope が広がるため、PTY mirror とは別 milestone にする。

## Safety

- mirror mode は explicit enable のみ。
- M0 の focus は operator 任せにする。focus 自動検出や arming phrase は後続候補。
- focus 誤爆対策として timeout と cancel action を持つ。
- output switch / config reload / emergency release で text-send runtime と同じ cancel / zero-report path に入る。
- PTY session exit、`exit` command、EOF、daemon disconnect で mirror mode を抜ける。
- `sessiond` / `logicd` failure は mirror mode exit とする。自動復帰しない。
- root shell、destructive command allowlist、persistent autostart は M0 では扱わない。

安全上の考え方:

- この機能の危険性は shell そのものより、Windows 側 focus 誤爆と synthetic key flood にある。
- M0 は user 権限 shell に限定して権限リスクを下げる。
- real send は host profile、US sub endpoint、`sessiond` readiness、`usbd` broker readiness を満たした時だけ許可する。
- cancel action は physical key からでも HTTP/ctrl からでも通せるようにする。
- cancel / timeout / daemon shutdown 時は `logicd` が release-all / zero-report を通す。
- PTY child は終了時に必ず reap し、mode state を stale にしない。
- PTY payload log は default off にする。デバッグ中だけ明示 opt-in で payload logging を許可する。
- `sessiond` が落ちた時は PTY child cleanup を試みる。cleanup できない場合も `logicd` は通常 mode へ戻る。
- `logicd` が落ちた時は systemd による process lifecycle に委ね、再起動後に mirror mode を inactive として扱う。

## OLED feedback

M0 は OLED を小さな運用 feedback に使う。

- mode start: OLED alert `PTY START` を 1.5 秒表示する。
- mode exit: OLED alert `PTY EXIT` と exit reason を 2.0 秒表示する。
- mode error: OLED warning / inverted alert `PTY ERROR` を 3.0 秒表示する。
- debug status: ready 画面の時計の次の行に `PTY idle` / `PTY active` / `PTY exit:<reason>` などを短く表示する。
- 実機 OLED の縦幅で時計下行が収まらない場合は、FPS 行または時計直上の status 行を差し替える。
- debug status は payload を出さない。active/inactive、last reason、drop count 程度に限定する。
- payload logging と同様、詳細 debug 表示は opt-in にする。

## Open questions and thin areas

検討が薄い箇所:

- `sessiond` IPC: sessiond-owned local socket / newline-delimited JSON を M0 仮決めにする。詳細 schema は未確定。
- backpressure: HID送信待ちが詰まった時の drop / merge / block は、動き出した後の調整項目にする。
- terminal parser: M0 は完全 terminal emulator を目指さない。clear / cursor move / line overwrite の具体 subset は未確定。
- screen size: M0 は 120x35 固定で始める。profile 設定や Windows Terminal 側への合わせ込みは後続。
- focus arming: M0 は operator 任せ。後続で arming phrase / visual marker を足すかは未確定。
- mode switch UX: M0 は既存 `KC_SH7` script から start command を呼ぶ。HTTP UI、MCP/ctrl は後続候補。
- `exit` 検出: shell の文字列として検出するのではなく、PTY child exit / EOF を source of truth にする実装詳細。
- logging: PTY payload log は default off。デバッグ opt-in の設定名と保存先は未確定。
- OLED status layout: 時計下行を優先するが、実機表示で収まらない場合の fallback 行を実装時に確認する。
- uinput 移管: `sessiond` に寄せる場合、既存 `daemon/logicd/uinput.py` との段階的移行順。
- Windows Terminal 前提: cmd / PowerShell / Windows Terminal pane による ANSI 挙動差をどこまでサポートするか。
- real-device test: 小さい `echo ok` / `exit` から始め、次に bash 操作と bash `exit` mode return を確認する。
- lightweight scope: M0 は小さい軽作業用に限定する。どこまでの command を「軽作業」とみなすかは smoke 後に調整する。

## Risks

| リスク | 初期対策 |
| --- | --- |
| Windows 側 focus 誤爆 | operator focus 前提、explicit enable、timeout、cancel、短い M0 smoke に限定 |
| HID 帯域不足 | row-level diff、coalescing、experimental 扱い |
| layout 不一致 | US sub endpoint と explicit host profile に限定 |
| loop / re-entry | `source=pty_terminal_mirror` guard、macro recording 除外 |
| stale key press | cancel / timeout / shutdown で release-all / zero-report |
| shell 権限 | user 権限 PTY のみ、root shell 非対象 |
| terminal state drift | 自前で完全管理しない。clear + home の初回描画、row-level erase、必要時 full refresh |
| secret logging | payload log は default off。debug opt-in 時だけ許可。status は counts / state 中心 |
| daemon failure | `sessiond` / `logicd` failure は mirror mode exit。自動復帰しない |
| scope creep | M0 は軽作業用。full-screen TUI / editor / long-running output は対象外 |
| OLED layout overflow | 時計下行を優先し、収まらない場合は FPS 行または時計直上 status 行へ fallback |
