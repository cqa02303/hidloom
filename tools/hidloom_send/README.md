# hidloom_send

KC_SH や手動確認から軽く呼ぶ C helper command 群です。方針は [POLICY.md](POLICY.md) を参照してください。

## Build

```bash
tools/hidloom_send/build.sh
```

中間生成物は `tools/hidloom_send/.build/`、実行用 command はリポジトリ直下の `bin/` に置かれます。

## Commands

### hidloom-keytext

US 配列相当の ASCII 文字列を `/tmp/key_events.sock` へ HID tap として送ります。

```bash
bin/hidloom-keytext "ABCabc\n"
bin/hidloom-keytext --hold-us 30000 --gap-us 20000 "OK\n"
```

### hidloom-key

HID usage ID と modifier bit を数値で直接送ります。`tap` は各引数を `0xMMKK` として扱います。
`MM` は modifier、`KK` は HID usage ID です。modifier なしは `0xKK` だけでも指定できます。

```bash
bin/hidloom-key tap 0x04
bin/hidloom-key tap 0x0204
bin/hidloom-key tap 0x0204 0x05
bin/hidloom-key press 0x0204
bin/hidloom-key press 0x04
bin/hidloom-key release 0x04
```

### hidloom-oled

OLED alert / warning を `/tmp/i2c_events.sock` へ送ります。

```bash
bin/hidloom-oled alert "Saved" 2
bin/hidloom-oled warning "Script failed" 3
```

### hidloom-notify

OLED alert / warning を送り、同じ内容を syslog / journal にも残します。

```bash
bin/hidloom-notify alert "Saved" 2
bin/hidloom-notify warning "Script failed" 3
```

### hidloom-ctrl

`logicd` control socket (`/tmp/ctrl_events.sock`) へ JSON line request を送り、response を stdout に出します。
汎用の `json` のほか、よく使う layer / keymap / runtime 操作だけ短いサブコマンドを用意しています。

```bash
bin/hidloom-ctrl json '{"t":"G"}'
bin/hidloom-ctrl keymap
bin/hidloom-ctrl matrix
bin/hidloom-ctrl save
bin/hidloom-ctrl layer get
bin/hidloom-ctrl layer add
bin/hidloom-ctrl layer clear 2
bin/hidloom-ctrl output bt
bin/hidloom-ctrl output usb
bin/hidloom-ctrl bt pairing-toggle
bin/hidloom-ctrl led get
bin/hidloom-ctrl led effect 40 128 175 77 160
```
