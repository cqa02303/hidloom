# HIDloom Software Specification

この文書は、現在の実装に合わせた HIDloom のソフトウェア仕様です。
fresh install と運用手順の詳細は `../FRESH_INSTALL.md`、リリース前確認は
`../RELEASE_CHECKLIST.md` を参照してください。

## 1. Overview

HIDloom は Raspberry Pi Zero 2 W を USB HID 複合デバイスかつ BLE HID keyboard として動かす
キーボード制御ソフトウェアです。現行の既定構成では、物理キーの boot-critical path を
`matrixd -> logicd-core-rs -> hidloom-outputd -> hidloom-hidd` に寄せ、HTTP UI、Vial GUI、
Bluetooth pairing、macro、text send、sessiond などの control plane は `logicd-companion` が扱います。

主な機能:

- GPIO matrix scan
- USB Keyboard / Raw HID / Mouse / Consumer Control gadget
- BLE HID over GATT keyboard (`btd`)
- Vial dynamic keymap GET / SET
- VialRGB / HTTP Lighting control
- HTTP UI による keymap 編集、内部 Key Tester、script viewer、Bluetooth pairing
- runtime keymap の `/mnt/p3/keymap.json` 永続化
- KC_SH0 から KC_SH10 による shell script 実行

## 2. Process Responsibilities

| Process | 役割 |
|---|---|
| `matrixd` | GPIO matrix をスキャンし、押下/離放を本線 `/tmp/matrix_events.sock` へ送る |
| `logicd-core-rs` | 物理キー hot path の matrix socket owner。基本 keymap / layer、stable HID slot、release safety、output broker frame 生成、観測用 matrix tap を担当 |
| `logicd-companion` | HTTP / Vial / macro / text send / sessiond / advanced interaction / status merge などの control plane。通常 HID fan-out は無効 |
| `hidloom-outputd` | native output router。`usb` / `uinput` / `bt` / `auto` target を保持し、core 由来 report を `hidloom-hidd` / `hidloom-uidd` / `btd` へ配送する |
| `hidloom-hidd` | `/tmp/usbd_hid_reports.sock` と `/dev/hidg0` / `/dev/hidg1` / `/dev/hidg2` の owner。USB HID report broker と Raw HID/Vial bridge を担当 |
| `hidloom-uidd` | Pi local console 用 `/dev/uinput` owner。native output router から受けた keyboard report を Linux input event へ変換する |
| `btd` | BlueZ D-Bus へ BLE HID over GATT service を登録し、keyboard report を notify |
| `usbd` | legacy Python USB HID broker。現行既定では通常 inactive で、rollback / A/B 診断用に残す |
| `viald` | Vial Raw HID protocol、VialRGB packet、keymap GET/SET を処理 |
| `httpd` | HTTP UI、keymap editor、Lighting 操作、script viewer、内部 Key Tester |
| `ledd` | SK6812MINI-E LED、VialRGB effect、direct control、key reactive effect |
| `i2cd` | SH1107 OLED 表示、service 状態表示、alert、script exit 表示 |
| `spid` | SPI slave 入力を `/tmp/spi_events.sock` へ送り、logicd の pointing input へ接続 |

## 3. Runtime Flow

```text
matrixd ─ reliable /tmp/matrix_events.sock ─► logicd-core-rs
                                      │
                                      ├─ /tmp/hidloom_output_reports.sock ─► hidloom-outputd ─ usb/auto ─► hidloom-hidd ─► /dev/hidg0 Keyboard/Mouse/Consumer
                                      │                                                │                         └───► /dev/hidg2 US sub keyboard
                                      │                                                └─ uinput ─► hidloom-uidd ─► /dev/uinput
                                      └─ /tmp/logicd_delegate_events.sock ─► logicd-companion

logicd-core-rs ─ best-effort /tmp/matrix_tap_events.sock ─► logicd-companion ─► ledd reactive trigger
                                                        └─ observed pressed matrix state for HTTP/Vial testers

httpd / viald / helpers / sessiond ─► logicd-companion ─► core ctrl / runtime files / status merge
logicd-companion ─► /tmp/btd_events.sock ─► btd ─► BLE HID host
logicd-companion ─► /tmp/ledd_events.sock ─► ledd
logicd-companion ─► /tmp/i2c_events.sock  ─► i2cd

PC / Vial GUI ─ /dev/hidg1 Raw HID ─ hidloom-hidd ─ /tmp/viald_events.sock ─ viald
```

`KC_CONSOLE` / `KC_USB` / `KC_CONNAUTO` の native owner 復旧は `hidloom-outputd`
control socket 経由で実装済みです。router は `usb` / `auto` target で `hidloom-hidd`、
`uinput` target で `hidloom-uidd` へ report を配送し、`logicd-core-rs` は出力先固有 device owner にはなりません。
設計詳細は [native-output-routing-uidd-design.md](native-output-routing-uidd-design.md) を参照してください。

## 4. USB HID Interfaces

| Device | Interface | 用途 |
|---|---:|---|
| `/dev/hidg0` | 0 | Keyboard / Mouse / Consumer Control multi-report HID |
| `/dev/hidg1` | 1 | Raw HID / Vial |
| `/dev/hidg2` | 2 | US sub keyboard endpoint |

`hidloom-usb-gadget.service` が ConfigFS 経由で gadget を作成します。
boot 設定と module-load 設定は `setup_fresh_rpi.sh` が行います。
runtime では `hidloom-hidd` が各 `/dev/hidg*` endpoint を open し、legacy `usbd.service` は通常 inactive です。

Vial GUI の検出には USB serial string がmagic `vial:f64c2b3c`を含む必要があります。
現行compatibility profileはmagicだけ、割当後のpublic formal profileはsuffix付きの確定値を使います。
表示名は HID descriptor の `manufacturer_string` と `product_string` から
作られるため、`setup_usb_gadget.sh` は `__HOSTNAME__` を `uname -n` に展開し、
node 名を USB manufacturer / product string に設定します。
これにより複数台接続時は `<keyboard-host> HID Interface` のように見分けます。

## 5. IPC Protocols

### `matrix_events.sock`

matrix 座標の押下/離放を input owner へ送ります。固定 4 byte packet です。
現行既定では `logicd-core-rs` がこの socket の single listener です。

| Byte | 内容 | 値 |
|---:|---|---|
| 0 | event | `P` または `R` |
| 1 | row | 16 進 1 文字 |
| 2 | col | 16 進 1 文字 |
| 3 | newline | `\n` |

### `matrix_tap_events.sock`

`logicd-core-rs` が同じ 4 byte P/R packet を複製して送る best-effort tap socket です。
core が通常 matrix event として受理した edge だけを送信し、tap 側の connect / send failure は HID 出力に影響しません。
delegate / PTY mirror capture に回した event は companion 本線で扱うため、ここには二重送信しません。
`logicd-companion` は press / release を観測用 pressed matrix state に反映し、LED reactive effect には press だけを `ledd` へ転送します。
HTTP / Vial の Matrix Tester は `ctrl_events.sock` の `K` response からこの観測状態を読みます。
tap stream は best-effort なので、取りこぼしを許さない HID hot path や debounced key decision には使いません。

### `key_events.sock`

確定済み keycode と modifier を logicd へ送ります。sendkey / KML などの補助ツールが使います。

| Byte | 内容 | 値 |
|---:|---|---|
| 0 | event | `P` または `R` |
| 1 | keycode | USB HID keycode |
| 2 | modifier | HID modifier bit |
| 3 | reserved | `0x00` |

### `btd_events.sock`

`logicd` から `btd` へ BLE keyboard report を送ります。payload は USB keyboard boot report と同じ 8 byte です。

| Byte | 内容 |
|---:|---|
| 0 | modifier |
| 1 | reserved |
| 2-7 | keycode slots |

### `spi_events.sock`

`spid` から `logicd` へ SPI slave 入力を送ります。analog stick / pointing input の補助経路です。

### `ctrl_events.sock`

JSON line protocol です。Vial / HTTP / analog stick / USB LED OUT から logicd へ制御要求を送ります。

代表的な message:

| `t` | 用途 |
|---|---|
| `M` | keymap remap |
| `G` | current keymap GET |
| `K` | pressed matrix state GET。native owner では delegated Python pipeline の状態と tap-observed state の union を返す |
| `S` | runtime keymap save |
| `RESET_KEYMAP` | `/mnt/p3/keymap.json` を削除し初期 keymap を再読込 |
| `LED` | VialRGB / Lighting 操作 |
| `BT_PAIRING` | Bluetooth pairing 受付状態の変更 |
| `BT_STATUS` | Bluetooth / btd 状態取得 |
| `A` | analog stick 入力 |

### `ledd_events.sock` / `i2c_events.sock`

logicd から ledd / i2cd へ JSON line で状態を通知します。

代表的な message:

- `{"t":"layer","layer":0,"active":[0]}`
- `{"t":"key","kind":"P","row":7,"col":0}`
- `{"t":"mode","mode":"gadget"}`
- `{"t":"vialrgb","mode":2,"speed":128,"h":0,"s":255,"v":128}`
- `{"t":"script_exit","name":"KC_SH0","code":0}`
- `{"t":"alert","msg":"...","sec":5}`
- `{"t":"warning","msg":"...","sec":3,"immediate":true}`

`i2cd` の `alert` / `warning` は通常 queue 表示です。
`immediate: true` を付けると、現在表示中の alert / warning を待たずに即時表示へ切り替えます。
このフラグは通知種別共通で、message 内容に依存した特例は作りません。

## 6. Configuration And Persistence

主な設定ファイル:

| File | 用途 |
|---|---|
| `config/default/config.json` | daemon 共通設定、socket path、HID path、HTTP basic auth 初期値 |
| `config/default/keymap.json` | 初期 keymap、layout metadata、encoder / joystick 定義 |
| `config/default/vial.json` | Vial keyboard definition |
| `config/default/keyboard-layout.json` | HTTP UI の物理レイアウト |
| `config/default/keycodes.json` | internal keycode table |
| `config/default/i2cd.json` | OLED / i2cd 設定 |
| `config/default/ledd.json` | LED / ledd 設定 |

HTTP Basic 認証の変更値は `config/default/config.json` へ直接書き戻さず、専用 override に保存します。
`config/default/config.json` の初期 password は `__HOSTNAME__` を指定でき、その場合は
起動時の node 名 (`hostname` の出力) として扱います。
実機では `/mnt/p3/http_basic_auth.json`、開発環境では `config/default/http_basic_auth.local.json` を使い、
password は平文ではなく `password_hash` として保存します。

runtime keymap の優先順位:

1. `/mnt/p3/keymap.json`
2. `config/default/keymap.json`

script directory の優先順位:

1. `settings.script_dir`
2. `/mnt/p3/script`
3. `config/default/script`

`setup_fresh_rpi.sh` は `config/default/script` を `/mnt/p3/script` へ初期コピーします。
KC_SHn script の実行時は、`logicd` が repository 直下の `bin/` を `PATH` の先頭に追加します。
fresh install では `tools/hidloom_send/build.sh` により `bin/hidloom-keytext` / `bin/hidloom-key` /
`bin/hidloom-oled` / `bin/hidloom-notify` / `bin/hidloom-ctrl` を生成します。

## 7. Keymap And Actions

`logicd` は matrix 座標と現在 layer から action 文字列を解決します。

代表的な action:

| Action | 用途 |
|---|---|
| `KC_*` | keyboard / mouse / consumer / custom keycode |
| `MO(N)` | layer N を押下中だけ有効化 |
| `TG(N)` | layer N を toggle |
| `TO(N)` | layer N へ移動し、他の toggle / momentary / one-shot layer を解除 |
| `DF(N)` | runtime 中の default layer を N に変更（再起動後は初期状態へ戻る） |
| `LT(N,KC_*)` | 短押しで `KC_*`、押している間だけ layer N を有効化 |
| `MT(MOD,KC_*)` | 短押しで `KC_*`、押している間だけ modifier を押下 |
| `TT(N)` | tap で layer N を toggle、hold で momentary |
| `MACRO:name` | local config の named macro |
| `IME_ON` / `IME_OFF` | IME 制御 |
| `U+XXXX` | Windows Unicode input sequence |
| `KC_SH0` ... `KC_SH10` | 対応する shell script を実行 |
| `KC_CONNAUTO` | 旧 Python owner では `gadget` -> `uinput` の順で利用可能な単一出力を選ぶ auto へ戻す。native owner では `hidloom-outputd` の `auto` target へ戻し、USB ready なら `usb`、そうでなければ `uinput` を選ぶ |
| `KC_CONSOLE` / `KC_USB` / `KC_BT` | 旧 Python owner では auto を止め、`uinput` / `gadget` / `bt` の単一出力に限定する。native owner では `hidloom-outputd` により `uinput` / `usb` / `bt` target 切り替えとして復旧済み |
| `KC_BT` | 旧 Python owner では `bt` の単一出力に限定する。native owner first slice では companion / `btd` の既存 Bluetooth output 経路を維持し、router 統合は別 phase |
| `BT_*` | Bluetooth pairing / output 操作 |

Vial GUI では任意名 `SCRIPT(...)` ではなく、`KC_SH0` から `KC_SH10` の
custom keycode として script を割り当てます。
Vial Tap Dance は標準APIの `On tap` / `On hold` / `On double tap` /
`On tap + hold` / `Tapping term` を `settings.interaction.tap_dances` へ橋渡しします。
Vial Combo は layer 0 の keycode を matrix 座標へ逆引きし、
`settings.interaction.combos` へ橋渡しします。
Vial Key Override は required modifier + negative modifier + trigger key +
replacement key + layer mask + option flags を `settings.interaction.key_overrides`
へ橋渡しします。suppressed modifier は保存・復元し、runtime suppression first slice では
trigger action を replacement press 前に一時 release し、replacement release 後に必要なら restore します。
Vial QMK Settings は Combo Term / Tapping Term / Hold On Other Key Press を
`settings.interaction` へ橋渡しします。
Vial Macro は raw buffer を `settings.vial_macro_buffer` に保存し、`M0`-`M7`
を `MACRO:VIAL0`-`MACRO:VIAL7` として実行します。text / tap / down / up / delay は
logicd macro token へ変換します。

HTTP のキーコード変更 UI では、`LT(N,KC_*)` を2段階で設定します。`Layer` タブで
現在編集中のレイヤー以外の `LT(N)` を選び、次に `PC104` などからタップキーを選ぶと、
`LT(N,KC_X)` のような action として保存します。HTTP API 側は `LT(0-31,KC_*)` を
受け付けますが、タップキーは当面 `KC_NONE` / `KC_TRNS` を除く通常 `KC_*` に限定します。

KML (`macro/kml.py`) は `/tmp/key_events.sock` へ key event を送る手動実行用プロトタイプです。
KML / QMK macro keycode integration は実装前設計を固定済みです。
first slice では `KC_KMLn` / `KC_QMn` を追加せず、
`KML(name)` / `QMK_MACRO(name)` の runtime action、`/mnt/p3/macros/<kind>/` -> `config/default/macros/<kind>/`
lookup、read-only file picker + validation / dry-run、`logicd` 経由 events、
Vial custom keycode 非追加で始めます。

## 8. Vial / VialRGB

Vial GUI は `/dev/hidg1` Raw HID 経由で接続します。

対応済み:

- keyboard definition 返却
- dynamic keymap GET / SET
- keymap persistence
- unlock combo
- matrix state for Vial Matrix Test
- VialRGB supported effect query
- VialRGB mode / HSV / speed / direct control

VialRGB effect の実装状態は [lighting/vialrgb-protocol.md](../lighting/vialrgb-protocol.md) を参照してください。

## 9. HTTP UI

`httpd` は Basic 認証付きの HTTPS UI を提供します。初期値は user `admin`、password は node 名（`hostname` コマンドの出力）です。
LAN 内で Basic 認証値を平文送信しないよう、systemd unit では `HTTPD_PORT=443` と
`/mnt/p3/httpd.crt` / `/mnt/p3/httpd.key` を使い、HTTP 80 は待ち受けません。
証明書が存在しない場合は `script/ensure_httpd_tls_cert.sh` が自己署名証明書を生成します。
既定では `HTTPD_PRIVATE_ONLY=1` により、loopback、IPv4 private、IPv4 link-local 以外の
client は 403 で拒否します。IPv6 は通常運用で使わない前提のため既定では許可しません。
追加の管理 network が必要な場合は `HTTPD_ALLOWED_NETS` に CIDR で明示します。

主な機能:

- キーボード表示
- keymap 表示・変更
- `.vil` keymap 書き出し・読み込み
- 内部 Key Tester
- Lighting / VialRGB 操作
- script 一覧・本文編集・保存・初期化
- Bluetooth pairing 受付開始/停止
- daemon status / log 表示 (`logicd` / `btd` / `spid` を含む)
- Settings タブでの Basic 認証 password 変更

Settings タブで password を変更すると、現在 password を確認したうえで専用 override
ファイルへ hash を保存します。既存の `config/default/config.json` は初期値としてのみ扱い、HTTP UI
からは書き換えません。

## 10. Installation

fresh Raspberry Pi OS では、リポジトリ直下で次を実行します。

```bash
sudo ./setup_fresh_rpi.sh
```

再起動を手動にしたい場合:

```bash
sudo ./setup_fresh_rpi.sh --no-reboot
sudo reboot
```

詳細は `../FRESH_INSTALL.md` を参照してください。

## 11. Verification

代表的な確認コマンド:

```bash
systemctl status hidloom-usb-gadget hidloom-hidd hidloom-logicd-core logicd-companion matrixd ledd httpd viald btd i2cd --no-pager
systemctl is-active usbd || true
ls -l /dev/hidg0 /dev/hidg1 /dev/hidg2
curl -k -u admin:$(hostname) https://127.0.0.1/api/status
curl -k -u admin:$(hostname) https://127.0.0.1/api/scripts
python3 script/test_validation_suite.py
python3 script/test_development_suite.py
```

リリース前のチェック項目は `../RELEASE_CHECKLIST.md` にまとめています。
