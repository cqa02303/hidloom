# KC_SH report output route design

更新日: 2026-06-02

## 目的

`KC_SHn` を単なる shell 実行 keycode ではなく、必要な script だけが実行結果を安全な report 経路へ流せる keycode family として整理する。

将来の `tty cat` 風コンソール体験は、いきなり独立 mode として作らず、まずは `KC_SHn` から明示 opt-in された stdout / stderr だけを共通の text report sink へ流す first slice から始める。

## 方針

- 直近の実装対象は `KC_SHn` の report 経路。
- `tty cat` 風の擬似 console mode は future wishlist として分離する。
- `KC_SHn` の出力先は固定で HID に直結せず、report sink として抽象化する。
- 既定動作は `no report` とし、通常利用の補助 script が host PC へ勝手に文字を送らないようにする。
- report 出力は script metadata または将来の helper command による明示指示だけで有効にする。
- 初期 slice は `hid_text` を主対象にするが、`log` / `debug` / `OLED` / `WebUI` へ広げられる形にする。
- 実 tty を直接つなぐのではなく、allowlist された command runner の結果を流す。

## 想定データフロー

```text
KC_SH1 / KC_SH2 / KC_SH3 ...
        ↓
script / shell command runner
        ↓
script metadata check
        ↓
stdout / stderr / exit code capture
        ↓
text report formatter
        ↓
report callback / sink
        ↓
hid_text sender / log / debug / WebUI / OLED
```

`hid_text` sink を使う場合、host PC 側では terminal に focus し、`cat` など入力をそのまま表示する command を起動しておくことで、Raspberry Pi 側の実行結果を HID keyboard 入力として確認できる。

## opt-in metadata

初期実装は script コメントによる opt-in を優先する。

```sh
#!/bin/sh
# @label show ip address
# @report hid_text
# @report-max-bytes 2048
# @report-ansi strip
hostname -I
```

metadata がない script は、従来どおり実行、exit code 通知、log 記録だけを行い、host PC へ出力しない。

## 将来 helper command

script 内部の任意タイミングで report を出したい場合は、後続で helper command を追加する。

```sh
#!/bin/sh
ip=$(hostname -I)
hidloom-report --sink hid_text --title KC_SH1 "$ip"
```

この方式なら stdout 全体ではなく、script が選んだ text だけを report できる。初期 slice では helper command は作らず、metadata opt-in で境界を固定する。

## report sink 候補

| sink | 意味 | 初期対象 |
| --- | --- | --- |
| `none` | 実行だけ行い結果は捨てる | 既定 |
| `log` | daemon log に残す | 既存 log |
| `debug` | HID report debug と同様の確認経路へ流す | 候補 |
| `hid_text` | keyboard HID text として host へ送る | 実装済み |
| `webui` | HTTP UI の実行結果 panel へ返す | 後続 |
| `oled` | 短い結果だけ OLED alert/status に出す | 後続 |

## ANSI / escape sequence policy

エスケープシーケンスは将来の `tty cat` 体験で重要になるため、初期から policy を持つ。

| policy | 意味 | 初期用途 |
| --- | --- | --- |
| `strip` | ANSI escape sequence を除去する | default / 安全優先 |
| `visible` | ESC を `^[` として可視化し、制御としては効かせない | debug / 確認用 |
| `passthrough` | ESC 文字を保持する | 将来の terminal-oriented sink 用 |

初期の `hid_text` 実装では、host layout と terminal 状態への副作用を避けるため、`strip` または `visible` を優先する。
`passthrough` は metadata と sanitizing helper では扱えるようにしておき、実際に ESC key sequence として HID 送信するかは後続実装で判断する。

## 安全境界

`KC_SHn` は任意 command 実行に近いので、HID へ送る前に以下を固定する。

- report は default off。
- metadata opt-in がある場合だけ report sink へ流す。
- timeout。
- 最大出力 size。
- stdout / stderr を分けるか、結合するか。
- exit code を表示する format。
- ANSI escape の `strip` / `visible` / `passthrough` policy。
- control character 除去または可視化。
- 改行変換。
- host layout 差を避けるための初期 ASCII 限定。
- 送信間隔 / rate limit。
- 中断 key / emergency release。
- long output 時の truncation 表示。

## 実装済み first slice

- [x] `daemon/logicd/script_report.py` に `# @report` / `# @report-max-bytes` / `# @report-ansi` parser を追加。
- [x] report は default off として扱う。
- [x] ANSI policy `strip` / `visible` / `passthrough` を metadata と sanitizing helper で扱う。
- [x] `script/test_script_report_metadata.py` で opt-in / max bytes / ANSI sanitizing を固定。
- [x] `MacroExecutor._run_shell_script()` で metadata を読み、opt-in された script だけ `script_report_notify(name, sink, text, exit_code)` へ渡す。
- [x] `hid_text` sink は `MacroExecutor._type_string()` を使い、sanitize 済み text を keyboard HID report として送る。
- [x] `script/test_script_directory_resolution.py` で `# @report` なしは callback / HID report なし、`# @report hid_text` ありは stdout / stderr が sanitize され、callback と keyboard report が発生することを固定。
- [x] 初期実装では tty 双方向化を入れないことを明記する。

## 残り first slice

- [ ] stdout / stderr / exit code の最小 format を詰める。現時点は stdout に続けて `[stderr]` section を付ける。
- [ ] host PC 側 `cat` smoke 手順を docs に書く。
- [ ] 長大出力、timeout、command failure、sink unavailable のテスト範囲を追加する。
- [ ] `hid_text` を `MacroExecutor` から独立した sink dispatcher へ分ける必要があるか、実機 smoke 後に判断する。

## first slice 手順

1. metadata parser と sanitizer を追加する。
2. `KC_SHn` の結果を、metadata opt-in がある場合だけ内部 text queue / report callback へ入れる。
3. `hid_text` 送信 helper は ASCII / 改行 / backspace 非使用に限定する。
4. `hostname -I` や `vcgencmd measure_temp` 程度の短い command で smoke する。
5. `cat` 側で読めることを確認する。
6. 実機確認後、`WebUI` / `OLED` / `debug` sink を増やすか判断する。

## future wishlist: tty cat console mode

最終形として、host PC の terminal で `cat` などを起動し、Raspberry Pi 側の擬似 console 出力を HID keyboard 入力として表示する `tty cat` 風体験を残す。

ただし、この項目は `KC_SHn` report route の後続であり、初期実装では扱わない。

将来検討する内容:

- `KC_SHn` を連続実行できる疑似 REPL。
- prompt / command history / help 表示。
- `ip` / `temp` / `status` / `log` などの診断 command set。
- ANSI / escape sequence を terminal 表示としてどこまで再現するか。
- 双方向化が必要な場合の HID raw / CDC ACM serial / WebUI 併用。
- host layout / IME / non-ASCII text の安全な扱い。
- tty そのものではなく、allowlist command の擬似 console として提供する境界。
