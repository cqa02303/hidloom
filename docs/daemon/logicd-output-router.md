# logicd: OutputRouter fan-out 設計

## 目的

keyboard outputを`gadget` / `uinput` / `bt` / `debug`のどれか1つとして選ぶのではなく、
同じbackend interfaceを実装する接続先として扱う。

これにより、同じ HID keyboard report を複数 backend へ同時に送れる。

例:

```bash
LOGICD_OUTPUTS=gadget,uinput,debug PYTHONPATH=daemon python3 -m logicd.logicd
```

## 設計意図

従来の `gadget <-> uinput` は USB 接続状態に応じた排他的な切り替えだった。
現在は以下のように扱う。

- `gadget`: USB HID gadget へ出力する接続
- `uinput`: Linux input subsystem へ出力する接続
- `bt`: Bluetooth HID へ出力する接続
- `debug`: ログへ出力する接続
- `auto`: `gadget` -> `uinput` の順で利用可能な出力を 1 つだけ選ぶ自動切替 backend

`auto` は単一出力です。明示的に fan-out したい場合は `LOGICD_OUTPUTS=gadget,uinput,debug,bt` のように指定する。
`debug` は必要な時だけ `LOGICD_OUTPUTS` へ追加します。
Bluetooth を `auto` の fallback に含めたい確認時だけ `LOGICD_AUTO_BT_FALLBACK=1` を指定します。

## 共通 I/F

各 backend は以下の I/F を持つ。

```python
name: str
enabled: bool
write(report: bytes) -> None
check() -> None
set_enabled(enabled: bool) -> None
```

`report` は 8-byte keyboard HID report。

## エラー分離

ある backend の失敗で他 backend への出力を止めない。
例えば USB gadget が一時的に write 失敗しても、`debug` や `uinput` には同じ report を送る。

## Bluetooth について

Bluetooth HID transport 本体は `btd` 側の責務にする。
`logicd` の `bt` backend は `BtdReportSender` を使って、`/tmp/btd_events.sock` へ 8-byte keyboard HID report を送るだけにする。

これにより、`logicd` は Bluetooth / BlueZ の詳細を知らず、次の境界を保てる。

```text
logicd OutputRouter
  ↓ 8-byte keyboard HID report
BtdReportSender
  ↓ Unix socket: /tmp/btd_events.sock
btd
  ↓
LoggingBackend / BlueZBackend (BLE HID over GATT)
```

`btd` が停止中、または socket が存在しない場合、`BtdReportSender` は report を drop する。他の backend (`gadget`, `uinput`, `debug`) への出力は止めない。

## 設定

優先順:

1. `LOGICD_OUTPUTS`
2. `settings.outputs`
3. default: `auto`

例:

```bash
LOGICD_OUTPUTS=debug PYTHONPATH=daemon python3 -m logicd.logicd
LOGICD_OUTPUTS=gadget,uinput,debug PYTHONPATH=daemon python3 -m logicd.logicd
LOGICD_OUTPUTS=gadget,uinput,bt,debug PYTHONPATH=daemon python3 -m logicd.logicd
LOGICD_OUTPUTS=auto LOGICD_AUTO_BT_FALLBACK=1 PYTHONPATH=daemon python3 -m logicd.logicd
```

出力選択キー:

```text
KC_CONNAUTO -> auto
KC_USB      -> gadget のみ
KC_CONSOLE  -> uinput のみ
KC_BT       -> bt のみ
```

`KC_BT` から `KC_USB` / `KC_CONSOLE` / `KC_CONNAUTO` へ戻るなど、出力対象から `bt`
が外れる時は null keyboard report を送ってから connected host を切断します。
この挙動は `LOGICD_BT_DISCONNECT_ON_OUTPUT_DISABLE=0` で無効化できます。

btd socket path は既定で `/tmp/btd_events.sock`。開発時は環境変数で変更できる。

```bash
BTD_EVENTS_SOCK=/tmp/test_btd.sock LOGICD_OUTPUTS=bt PYTHONPATH=daemon python3 -m logicd.logicd
```

config 例:

```json
{
  "settings": {
    "outputs": ["gadget", "uinput", "debug", "bt"],
    "btd_events_sock": "/tmp/btd_events.sock"
  }
}
```

## テスト

```bash
python3 -m unittest tests.test_output_router
python3 -m unittest tests.test_btd_sender
```
