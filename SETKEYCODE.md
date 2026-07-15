# Runtime Keycode の変更

`setkeycode.sh` は `logicd-companion` の `/tmp/ctrl_events.sock` へ `M` request を送り、
現在メモリ上の1キーを変更します。変更だけでは永続化されません。実機 keymap を安全に
変更するため、取得、変更、確認、保存を分けて実行します。

## 1. 変更前を確認

```bash
sudo hidloom-ctrl keymap | jq '.layers[0]["7,0"]'
sudo cp --preserve=mode,ownership,timestamps \
  /mnt/p3/keymap.json \
  /mnt/p3/keymap.json.manual-backup
```

runtime keymap がまだ存在しない構成では、backup command は省略します。package default の
`/usr/lib/hidloom/config/default/keymap.json` を runtime state として直接編集しないでください。

## 2. メモリ上の Action を変更

layer 0 の `7,0` を `KC_ESC` に変更:

```bash
sudo /usr/lib/hidloom/setkeycode.sh 7,0 KC_ESC
```

source checkout では repository root から実行できます。

```bash
sudo ./setkeycode.sh 7,0 KC_ESC
```

layer を指定する例:

```bash
sudo ./setkeycode.sh --layer 1 7,0 KC_GRAVE
sudo ./setkeycode.sh --layer 0 4,0 'MO(1)'
sudo ./setkeycode.sh --layer 0 4,1 'LT(1,KC_A)'
```

引数:

- `POSITION`: `row,col` 形式の matrix position
- `ACTION`: `KC_A`、`MO(1)`、`LT(1,KC_A)` などの action
- `--layer N`: 対象 layer。省略時は layer 0
- `--socket PATH`: isolated fixture 用。通常は変更しない

送信される JSON Lines request:

```json
{"t":"M","l":0,"r":7,"c":0,"a":"KC_ESC"}
```

`M` は入力値を検証し、成功時に次を返します。

```json
{"t":"M","result":"ok"}
```

## 3. 変更を確認

```bash
sudo hidloom-ctrl keymap | jq '.layers[0]["7,0"]'
```

この段階では再起動すると変更が失われます。意図した action と物理キー動作を確認してから
保存してください。

## 4. `/mnt/p3` へ保存

```bash
sudo hidloom-ctrl save
```

`S` request は runtime keymap を `/mnt/p3/keymap.json` へ atomic replace し、native core と
LED semantic role を reload します。成功 response の `path` が保存先です。

```json
{"t":"S","result":"ok","path":"/mnt/p3/keymap.json"}
```

保存後:

```bash
sudo python3 -m json.tool /mnt/p3/keymap.json >/dev/null
sudo hidloom-ctrl keymap | jq '.layers[0]["7,0"]'
```

Vial と HTTP keymap API も同じ control path を使って保存します。複数の client から同時に
編集せず、最後に保存した state を正としてください。

## Rollback

手動 backup を戻す場合:

```bash
sudo cp --preserve=mode,ownership,timestamps \
  /mnt/p3/keymap.json.manual-backup \
  /mnt/p3/keymap.json
sudo systemctl restart hidloom-logicd-core logicd-companion
```

device profile の既定値へ戻す場合は、現在の runtime keymap を backup してから profile を
再適用します。

```bash
sudo hidloom-profile keyboard-ver1 --apply --backup --restart
```

profile 再適用は keymap 以外の layout、Vial、matrix、LED、I2C 定義と service policy も
対象にします。1キーだけを戻す用途では、元 action を `setkeycode.sh` で設定して `save` する
方が影響範囲を限定できます。

## Troubleshooting

```bash
systemctl status hidloom-logicd-core logicd-companion --no-pager
journalctl -u hidloom-logicd-core -u logicd-companion -b -n 200 --no-pager
ls -l /tmp/ctrl_events.sock
sudo hidloom-ctrl keymap
```

- `Socket not found`: `logicd-companion` と native core の起動順・journal を確認
- `Permission denied`: 実機では `sudo` を使用し、socket mode を場当たり的に変更しない
- `invalid remap request`: layer、matrix range、action 文字列を確認
- 変更が再起動後に消える: `sudo hidloom-ctrl save` の response と runtime file を確認
- 物理 routing が異なる: JIS/US route、LT、layer state を action routing 文書と照合

action syntax は [docs/keycode/action-patterns.md](docs/keycode/action-patterns.md)、routing は
[docs/keycode/action-routing-matrix.md](docs/keycode/action-routing-matrix.md)、protocol 実装は
[`daemon/logicd/ctrl_keymap.py`](daemon/logicd/ctrl_keymap.py) を参照してください。
