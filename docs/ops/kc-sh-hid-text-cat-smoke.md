# KC_SH hid_text cat smoke

更新日: 2026-06-02

## 目的

`KC_SHn` の opt-in report 経路で、Raspberry Pi 側の script 出力を keyboard HID report として host PC の terminal に表示できることを確認する。

この確認は `tty cat console mode` そのものではない。`KC_SHn` の report sink として `hid_text` が動くことだけを確認する。

## 前提

- host PC 側で cqa02303v5 が USB keyboard として認識されている。
- `logicd` が起動している。
- `KC_SHn` が実行できる keymap になっている。
- script には明示的に `# @report hid_text` を書く。
- metadata がない `KC_SHn` script は、従来どおり host PC へ文字を送らない。

## host PC 側手順

terminal を開き、入力先を terminal に focus する。

```sh
cat
```

`cat` は標準入力をそのまま表示するだけなので、Raspberry Pi 側から HID keyboard 入力として送られた text がそのまま見える。

終了する時は host PC 側で `Ctrl-C` を押す。

## Raspberry Pi 側 script 例

短い出力から確認する。

```sh
#!/bin/sh
# @label report ip address
# @report hid_text
# @report-max-bytes 2048
# @report-ansi strip
hostname -I
```

ANSI escape の visible 表示を確認する例。

```sh
#!/bin/sh
# @label report ansi visible
# @report hid_text
# @report-ansi visible
printf '\033[31mhello\033[0m\n'
printf 'warn\n' >&2
```

`visible` の場合、ESC は `^[` として可視化され、terminal 制御としては効かない。

## 期待結果

`# @report hid_text` がある script を `KC_SHn` から実行すると、host PC の `cat` に script output が入力される。

例:

```text
<keyboard-ip>
```

stderr がある場合は、stdout の後ろに `[stderr]` section が付く。

```text
hello
[stderr]
warn
```

## 安全確認

以下を確認する。

- `# @report` がない script は host PC へ文字を送らない。
- `# @report-max-bytes` を小さくした場合、長大出力が truncation 表示で止まる。
- `# @report-ansi strip` では ANSI escape が消える。
- `# @report-ansi visible` では ESC が `^[` として見える。
- `# @report-ansi passthrough` は metadata / sanitizer 上は保持できるが、実 terminal 制御として安全に扱うかは後続判断とする。

## 注意

`hid_text` は keyboard HID report として文字を送るため、host PC の focus がある場所へ入力される。terminal / `cat` 以外に focus があると、そのアプリへ文字が入力される。

日本語や IME 依存文字は初期 smoke の対象外。まずは ASCII、改行、短い診断 command で確認する。

## future

この smoke が安定したら、将来の `tty cat console mode` では以下を検討する。

- 疑似 REPL。
- command history。
- `ip` / `temp` / `status` / `log` などの allowlist command。
- ANSI escape を terminal 表示としてどこまで扱うか。
- 双方向化が必要な場合の HID raw / CDC ACM serial / WebUI 併用。
