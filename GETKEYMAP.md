# Runtime Keymap の取得

HIDloom が現在メモリ上で使っている keymap は `logicd-companion` の
`/tmp/ctrl_events.sock` から取得できます。package install 環境では
`hidloom-ctrl` が標準 command です。

## 基本操作

```bash
sudo hidloom-ctrl keymap
```

source checkout には同じ `G` request を Python 3 の Unix socket client で送る
portable wrapper もあります。

```bash
sudo ./getkeymap.sh
sudo ./getkeymap.sh --pretty
```

`--pretty` は `jq` があれば整形し、なければ raw JSON を表示します。取得処理は
keymap、layer、runtime file を変更しません。

## Response

代表的な response:

```json
{
  "t": "keymap",
  "layers": [
    {
      "7,0": "KC_ESC",
      "6,0": "KC_F1"
    }
  ],
  "mode": "jp",
  "output_target": "auto",
  "active": {
    "momentary": [],
    "toggled": [],
    "locked": [],
    "all": [0]
  }
}
```

- `layers`: layer ごとの `row,col` と action
- `mode`: 現在の HID/JIS routing mode
- `output_target`: `auto`、`gadget`、`bt`、`uinput` などの実効出力
- `active`: momentary/toggle/lock を含む active layer state

特定位置だけを見る例:

```bash
sudo hidloom-ctrl keymap | jq '.layers[0]["7,0"]'
```

## Socket を指定する

fixture や isolated daemon を使う場合だけ socket path を変更します。

```bash
./getkeymap.sh --socket /tmp/logicd-test-ctrl.sock --pretty
hidloom-ctrl --socket /tmp/logicd-test-ctrl.sock keymap
```

通常運用の socket は `/tmp/ctrl_events.sock` です。JSON Lines protocol の request は
次の1行です。

```json
{"t":"G"}
```

protocol owner は
[`daemon/logicd/ctrl.py`](daemon/logicd/ctrl.py) と
[`daemon/logicd/ctrl_keymap.py`](daemon/logicd/ctrl_keymap.py) です。

## Troubleshooting

socket がない場合:

```bash
systemctl status hidloom-logicd-core logicd-companion --no-pager
journalctl -u hidloom-logicd-core -u logicd-companion -b -n 200 --no-pager
ls -l /tmp/ctrl_events.sock
```

permission error の場合は、実機では `sudo` を付けます。socket permission を広げる変更で
回避しないでください。

timeout や空 response の場合は companion が起動中でも処理不能な可能性があります。
service restart 前に journal と次の status を保存します。

```bash
cat /run/hidloom/logicd-core-status.json
systemctl --failed --no-pager
```

変更方法と永続化は [SETKEYCODE.md](SETKEYCODE.md) を参照してください。action の一覧と
routing contract は [docs/keycode/README.md](docs/keycode/README.md) が入口です。
