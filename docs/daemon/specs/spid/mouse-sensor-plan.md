# spid: SPI Mouse Sensor Driver Plan

更新日: 2026-07-15

SPI 接続のマウスセンサを追加するための設計メモ。
現在は `PAW3805EK` の Linux spidev polling backend と `logicd.spid_motion` への接続まで実装済みです。
CS0 試験機では Product ID / Revision ID、motion 由来の mouse HID report 生成まで確認済みです。

## 結論

SPI 接続のマウスセンサは、`logicd` へ直接入れず、`spid` として独立 daemon 化する方針です。

```text
SPI mouse sensor
  ↓ SPI
spid
  ↓ Unix socket event: dx / dy / wheel / buttons
logicd
  ↓ mouse HID report
/dev/hidg0 mouse report ID 2 or output backend
```

センサ定義がない構成では `spid` を起動しません。
既定値は以下です。

```text
SPID_ENABLED=false
SPID_BACKEND=none
```

また、誤って `SPID_ENABLED=true` だけを指定しても、`SPID_BACKEND=none` のままなら SPI も Unix socket も開かず終了します。

## 現在の状態

| 項目 | 状態 |
|---|---|
| `spid` daemon skeleton | 実装済み |
| JSON Lines motion protocol | 実装済み |
| `none` backend | 実装済み。daemon 起動なし用途 |
| `mock` backend | 実装済み。実機不要テスト用 |
| `PAW3805EK` backend | 実装済み。CS0 試験機で ID 読みと motion report 生成まで確認済み |
| `logicd.spid_motion` | 実装済み |
| `logicd.spid_direction` | mapper / key tap dispatch 実装済み |
| `script/test_spid_suite.py` | 実装済み |

## 対応センサ

対応センサ:

- `PAW3805EK`

`PAW3805EK` は `cqa02303/hfk/right/paw3805ek.c` の QMK 実装で使っていたレジスタ情報・初期化手順を参考に、`spid` 用に Python で新規実装しました。

## PAW3805EK backend

`PAW3805EK` backend の現在仕様:

- Linux `spidev` 使用
- polling 方式
- SPI mode: `3`
- SPI speed: `2 MHz`
- Product ID: `0x31`
- Revision ID: `0x61`
- software reset 実行
- write protect 解除後に operation mode / CPI 設定
- motion register bit 7 を確認
- X/Y delta は 12-bit two's complement として変換
- `MotionEvent(dx, dy, sensor="PAW3805EK")` を出力

配線:

| SPI0 signal | Raspberry Pi GPIO | Linux device |
|---|---:|---|
| `CS1` | `GPIO07` | `/dev/spidev0.1` |
| `CS0` | `GPIO08` | `/dev/spidev0.0` |
| `RX` / MISO | `GPIO09` | bus `0` |
| `TX` / MOSI | `GPIO10` | bus `0` |
| `SCK` | `GPIO11` | bus `0` |

マウスセンサ試験機は SPI0 `CS0` / `GPIO08` に接続します。`SPID_SPI_DEVICE=0` が対象です。`SPID_SPI_DEVICE=1` は `CS1` / `GPIO07` です。

注意: PAW3805EK は `NCS` / `SCLK` / `SDIO` の 3-wire SPI です。Raspberry Pi の標準 SPI0 で使う場合、センサの `SDIO` が Pi の `MOSI` / `MISO` 双方へ適切に合流している必要があります。4-wire 前提で `MOSI` と `MISO` をセンサ側の別ピンへ分ける配線では Product ID が読めません。

2026-05-22 実機メモ:

- 試験機: `pi@<keyboard-ip>` / `<keyboard-host>`
- GUI は `multi-user.target` + `lightdm` disabled で抑止済み
- I2C / matrix 未接続のため `i2cd.service` / `matrixd.service` は disabled
- `/dev/spidev0.0` / `/dev/spidev0.1` は生成済み
- 配線見直し前は `product_id=0x00 revision_id=0x00` となり未検出
- 配線見直し後、CS0 / SPI mode 3 / 100kHz-2MHz で `product_id=0x31 revision_id=0x61` を確認
- `SPID_ENABLED=true SPID_BACKEND=PAW3805EK SPID_SPI_DEVICE=0` で backend 初期化成功
- `/tmp/spi_events.sock` を `logicd` へ `SPID_CONNECT` し、`logicd.spid_motion` の mouse HID report 生成を確認

環境変数:

| 変数 | 既定値 | 内容 |
|---|---:|---|
| `SPID_SPI_BUS` | `0` | SPI bus |
| `SPID_SPI_DEVICE` | `0` | SPI device / CE |
| `SPID_SPI_SPEED_HZ` | `2000000` | SPI clock |
| `SPID_SPI_MODE` | `3` | SPI mode |
| `SPID_PAW3805EK_CPI` | `200` | 初期 CPI |
| `SPID_PAW3805EK_SCALE` | `1.0` | dx/dy multiplier |

起動例:

```bash
SPID_ENABLED=true SPID_BACKEND=PAW3805EK SPID_SPI_DEVICE=0 PYTHONPATH=daemon python3 -m spid.spid
```

CE1 を使う場合:

```bash
SPID_ENABLED=true SPID_BACKEND=PAW3805EK SPID_SPI_DEVICE=1 PYTHONPATH=daemon python3 -m spid.spid
```

## 理由

### logicd を重くしない

`logicd` は keymap / layer / macro / HID report / output routing の中心なので、SPI の低レベル処理を直接持たせません。

SPI マウスセンサには以下のようなデバイス固有処理が入ります。

- reset sequence
- register read/write
- chip select timing
- polling rate
- CPI / resolution 設定
- axis invert / rotation
- smoothing
- センサ未接続時の retry / fail-safe

これらは `spid` に閉じ込めます。

### 障害分離

SPI センサ未接続、read timeout、初期化失敗があっても keyboard 本体を落としません。

`spid` が落ちても `logicd` / `matrixd` / `btd` / USB HID keyboard は動き続ける設計です。

## spid の責務

`spid` が持つ責務:

- SPI bus open / close
- sensor reset / init
- sensor register read/write
- motion delta polling
- optional IRQ handling
- sensor-specific conversion
- CPI / axis / rotation / smoothing 設定
- motion event の Unix socket 出力
- センサ未接続時の fail-safe

`spid` が持たない責務:

- keymap / layer / macro
- keyboard HID report 生成
- output backend fan-out
- Bluetooth HID 実送信

## logicd の責務

`logicd` は `spid` から受け取った motion event を mouse HID report に変換します。

```json
{"t":"motion","dx":3,"dy":-2,"wheel":0,"buttons":0,"sensor":"PAW3805EK"}
```

```text
spid event
  ↓
logicd.spid_motion
  ↓
mouse HID report
  ↓
OutputRouter
  ├─ /dev/hidg0 mouse report ID 2
  ├─ btd BLE HID mouse
  └─ debug / other output backends
```

OutputRouter / Bluetooth mouse report への統合は実装済みです。PAW3805EK の本体搭載は
先の予定のため、方向 / 感度 / CPI / axis 設定や長期体感確認は Wishlist / TODO で扱います。

## Socket protocol 方針

初期 protocol は JSON Lines です。

理由:

- 実機調整時に `socat` / `nc` / log で見やすい
- センサ固有の debug 情報を追加しやすい
- 初期段階では可読性を優先する

例:

```json
{"t":"motion","dx":3,"dy":-2,"wheel":0,"buttons":0,"sensor":"PAW3805EK"}
{"t":"status","sensor":"PAW3805EK","ok":true,"cpi":800}
{"t":"status","sensor":"PAW3805EK","ok":false,"msg":"sensor read failed"}
```

高速化が必要になったら binary frame を検討します。ただし protocol / packet size を変える場合は実装前に相談します。

## 実装フェーズ

### Phase 0: datasheet / 既存実装確認

状態: `PAW3805EK` の対応範囲について完了。

確認済み:

- PAW3805EK SPI mode
- PAW3805EK clock
- PAW3805EK product id / revision id
- PAW3805EK motion read method
- PAW3805EK CPI register
- PAW3805EK delta 変換方式
- CS0 実機配線と polling 動作
- CE0 / CE1 の設定境界

### Phase 1: spid skeleton

状態: 完了。

- `daemon/spid/` directory
- daemon entrypoint
- systemd unit draft
- Unix socket server/client 境界
- mock backend
- tests

### Phase 2: sensor backend I/F

状態: 完了。

- `MouseSensorBackend` 共通 I/F
- `MockMouseSensorBackend`
- `Paw3805EkBackend`

### Phase 3: mock motion path

状態: 実装済み。実機では mouse HID report 生成まで確認済み。

- mock backend から dx/dy を生成
- `spid` から socket へ motion event を出す
- `logicd.spid_motion` が motion event を扱う
- `/dev/hidg0` mouse report ID 2 へ変換する足場

### Phase 4: PAW3805EK real SPI backend

状態: 実装済み。CS0 試験機で ID 読み、motion delta、`logicd.spid_motion` report 生成まで確認済み。

実装済み:

- Linux spidev backend
- sensor init sequence
- product id / revision id check
- motion read
- CPI 設定
- sensor absent initialization error
- 実機不要 Fake SPI test

残り:

- Raspberry Pi 実機で Product ID / Revision ID が読めることを確認
- 実 motion delta が読めることを確認
- `/dev/hidg0` mouse report ID 2 へ接続確認
- センサ未接続時の fail-safe を実機確認

### Phase 5: 実機 tuning

状態: 未着手。

- CPI
- poll interval
- smoothing
- acceleration の有無
- axis invert
- rotation
- trackball としての体感

## 設定候補

`config/default/config.json` の `settings.spid` 候補:

```json
{
  "settings": {
    "spid": {
      "enabled": false,
      "backend": "none",
      "socket": "/tmp/spi_events.sock",
      "bus": 0,
      "device": 0,
      "speed_hz": 2000000,
      "mode": 3,
      "cpi": 200,
      "scale": 1.0,
      "invert_x": false,
      "invert_y": false,
      "swap_xy": false,
      "rotation": 0,
      "poll_hz": 125
    }
  }
}
```

現時点では主に環境変数で制御します。runtime config 連携は後続作業です。

## 実機確認項目

- [x] SPI が OS で有効になっている
- [x] `/dev/spidev*` が見える
- [x] `python3-spidev` が入っている
- [x] `PAW3805EK` の Product ID `0x31` / Revision ID `0x61` が読める
- [x] motion delta が読める
- [x] logicd が motion event を受け取れる
- [x] `logicd.spid_motion` が mouse HID report を生成する
- [ ] `/dev/hidg0` mouse report ID 2 から host 側 mouse cursor が動く
- [ ] cursor 方向 / 感度 / CPI / axis 設定を体感確認する
- [ ] センサ未接続時に keyboard 本体が落ちない

## 実機不要テスト

```bash
python3 script/test_spid_suite.py
```

開発用一括テストにも `test_spid_suite.py` を含めます。

```bash
python3 script/test_development_suite.py
```

## 注意

- Bluetooth mouse report への統合は keyboard BLE HID が安定してから判断する
- `PAW3805EK` は polling 実装を先に使い、MOTION pin / IRQ は必要になってから検討する
- `spid` が停止しても keyboard 入力は止めない
