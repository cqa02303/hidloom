# config/default/ — 設定ファイル一覧

各デーモン・ツールが参照する設定ファイルをまとめたディレクトリです。
ランタイム設定は `/mnt/p3/` (SD カード P3 パーティション) のファイルが最優先されます。
開発・デバッグ時はこのディレクトリのファイルが使用されます。
Raspberry Pi Zero / Zero 2 向けの性能別 runtime profile は標準設定へ混ぜず、
[`config/profiles/`](../profiles/) に分離します。

---

## ファイル一覧

| ファイル | 用途 | 参照デーモン |
|---------|------|------------|
| [`i2cd.json`](#i2cdjson) | OLED 表示設定 | `i2cd` |
| [`ledd.json`](#leddjson) | シリアル LED 設定 | `ledd` |
| [`matrixd.json`](#matrixdjson) | GPIO キーマトリクススキャン設定 | `matrixd` |
| [`keymap.json`](#keymapjson) | レイヤーキーマップ定義 | `logicd` |
| [`keycodes.json`](#keycodesjson) | USB HID キーコード対応表 | `logicd` |
| [`key_labels.json`](#key_labelsjson) | キーキャップ表示ラベル | `httpd`（Web UI）|
| [`keyboard-layout.json`](#keyboard-layoutjson) | キーボード物理レイアウト（KLE 形式）| `httpd`（Web UI）|
| [`vial.json`](#vialjson) | Vial 互換メタデータ | `viald` |

---

## i2cd.json

SH1107 OLED ディスプレイの表示設定。`i2cd` デーモンが起動時に読み込みます。

```json
{
  "version": "1.0",
  "oled": {
    "driver":    "sh1107",
    "i2c_port":  1,
    "address":   "0x3C",
    "width":     64,
    "height":    128,
    "rotate":    0
  },
  "display": {
    "fps":       10,
    "font_size": 11,
    "font_path": null
  },
  "ipc": {
    "i2c_socket": "/tmp/i2c_events.sock",
    "ctrl_socket": "/tmp/ctrl_events.sock"
  }
}
```

| キー | 説明 |
|------|------|
| `oled.address` | I2C アドレス（`"0x3C"` or `"0x3D"`）|
| `oled.rotate` | 表示回転 0〜3（90° 刻み）|
| `display.font_path` | フォントの絶対パス。`null` で自動検索 |
| `ipc.i2c_socket` | logicd から OLED / mode / alert 通知を受信するソケットパス |
| `ipc.ctrl_socket` | i2cd から logicd へ analog stick などを送るソケットパス |
| `analog_stick.min_range_volts` | range 測定 / 保存値検査で両軸に要求する最小 span。未指定時は `0.1` |

---

## ledd.json

シリアル LED（SK6812MINI-E）の制御設定。`ledd` デーモンが使用します。

```json
{
  "version": "1.0",
  "led": {
    "type":        "SK6812MINI-E",
    "gpio_bcm":    12,
    "pin_board":   32,
    "brightness":  64,
    "color_order": "GRB"
  },
  "animation": {
    "fps":          30,
    "default":      "static",
    "idle_timeout": 60
  },
  "startup_effect": {
    "enabled": true,
    "kind": "vialrgb",
    "mode": 6,
    "speed": 48,
    "h": 140,
    "s": 120,
    "v": 32
  },
  "ipc": {
    "socket_path": "/tmp/ledd_events.sock",
    "direct_frame_socket_path": "/tmp/ledd_direct_frame.sock"
  }
}
```

| キー | 説明 |
|------|------|
| `led.gpio_bcm` | GPIO 番号（BCM 番号）|
| `led.pin_board` | 物理ピン番号（参照用、GPIO12 = Pin32）|
| `leds` | LED chain の物理順と実位置座標。標準基板 `ver1.0` は test LED なしの 81 個、試作基板 `ver0.1` は先頭 test LED を含む 89 個 |
| `led.brightness` | 輝度 0〜255 |
| `led.color_order` | SK6812MINI-E は W チャンネルなし。`"GRB"` 固定 |
| `animation.idle_timeout` | 無操作後に消灯するまでの秒数 |
| `startup_effect` | `ledd` が logicd 接続前に単独で出す低輝度の起動中エフェクト。logicd 接続後の初期同期で通常の VialRGB / state 表示へ上書きされる |
| `ipc.socket_path` | logicd から LED / mode / animation 通知を受信するソケットパス |
| `ipc.direct_frame_socket_path` | LED video demo など内部 producer 用の direct-frame socket |
| `ipc.direct_frame_fallback` | direct-frame producer 終了時の復帰動作。動画再生後は通常 effect に戻すため `restore_default` |
| `semantic_roles.reactive.modifier_triggers_effects` | `true` で Shift / Ctrl / Alt / Win など modifier key も reactive / splash effect の発火対象にする |
| `semantic_roles.load_keymap_on_startup` | `false` なら `ledd` 起動時は `ledd.json` だけを読み、keymap layer は `logicd-companion` 接続後の `semantic_keymap` 同期で受け取る |

---

## matrixd.json

C 言語実装の GPIO スキャンデーモン `matrixd` の設定。
チャーリープレックスマトリクス（10×10）のピン配置・スキャン動作を定義します。

```json
{
  "version": "1.0",
  "matrix": {
    "row_gpios":      [13, 26, 6, 5, 4, 25, 24, 22, 23, 27],
    "col_gpios":      [13, 26, 6, 5, 4, 25, 24, 22, 23, 27],
    "skip_same_index": true,
    "gpio_enabled":   true
  },
  "scan": {
    "interval_us": 1000,
    "idle_interval_us": 2000,
    "deep_idle_interval_us": 4000,
    "idle_after_ms": 100,
    "deep_idle_after_ms": 500,
    "debounce_mode": "time",
    "debounce_ms": 5,
    "settle_us": 20,
    "post_row_settle_us": 2
  },
  "ipc": {
    "socket_path": "/tmp/matrix_events.sock"
  }
}
```

| キー | 説明 |
|------|------|
| `matrix.row_gpios` / `col_gpios` | ROW・COL の GPIO 番号リスト（チャーリープレックスは同一）|
| `matrix.skip_same_index` | `true` で row == col をスキップ（チャーリープレックス用）|
| `matrix.gpio_enabled` | `false` にするとハードウェア未接続時の誤入力を防止 |
| `scan.interval_us` | スキャン周期（マイクロ秒）|
| `scan.idle_interval_us` / `deep_idle_interval_us` | 無操作時だけ伸ばす scan wait |
| `scan.debounce_mode` | `time` で実時間 debounce、`count` で scan 回数 debounce |
| `scan.debounce_ms` | チャタリング除去時間（ミリ秒）|
| `scan.settle_us` | ROW ドライブ後のセトリング待ち時間（マイクロ秒）|
| `scan.post_row_settle_us` | ROW release 後の行間待ち時間（マイクロ秒）|

---

## keymap.json

キーボードのレイヤーキーマップ定義。`logicd` の `config_loader` が読み込みます。

- `layers` 配列の各要素が 1 レイヤーに対応
- 各行は `_layout_def` で定義した物理キー順（左→右）と 1:1 対応
- キーコード文字列は `keycodes.json` に定義された `KC_*` を使用

```json
{
  "_schema": "hidloom-keymap/1",
  "_layout_def": [[行, 列], ...],
  "layers": [
    ["KC_ESC", "KC_1", ..., "MO(1)"],
    ["KC_GRAVE", "KC_F1", ..., "KC_TRNS"]
  ]
}
```

変更後は `logicd` の再起動か SIGHUP リロードが必要です。

### `settings.host_led_output`

host から返る Keyboard LED Output Report のうち、どの種類を `ledd` の state overlay に反映するかを設定します。
HID 標準 bit の意味は固定で、設定するのは有効化する種類だけです。

```json
{
  "settings": {
    "host_led_output": {
      "enabled": true,
      "fallback_internal_toggle": false,
      "states": {
        "caps_lock": true,
        "num_lock": true,
        "scroll_lock": true,
        "compose": false,
        "kana": false
      }
    }
  }
}
```

USB の Output Report は `/dev/hidg0` から `logicd` が読み取り、`HOST_LED` と同じ経路で
`ledd` の state overlay に反映します。BLE の Keyboard Output Report `WriteValue` から
同じ経路へ渡す処理は未接続です。

USB host から Caps / Num / Scroll の実状態を受け取るには、keyboard HID descriptor が
LED Output Report (`Usage Page 0x08`, `Output`) を宣言している必要があります。
`setup_usb_gadget.sh` の descriptor を変更した後は、`hidloom-usb-gadget` を再起動して
host 側に USB device を再列挙させてください。

`device.hid_country_code` は USB HID descriptor の country code 候補です。
既定値は `0` (not localized) です。`15` は Japan、`33` は US など、HID 仕様上の値を
0..255 で指定します。現行 Raspberry Pi OS の configfs HID gadget function では
`country_code` / `bCountryCode` 属性が公開されないことがあるため、その場合
`setup_usb_gadget.sh` は warning を出して値を適用しません。country code は host OS の
配列選択を強制するものではないため、US / JP 配列の確実な切替は USB identity profile や
host 側設定と分けて扱います。

`fallback_internal_toggle` は、実 Output Report 経路が未接続な環境で
`KC_CAPS` 押下だけで `caps_lock` overlay を確認するためのデバッグ用 fallback です。
通常は host の実状態だけを表示するため `false` にします。

---

## keycodes.json

USB HID Usage Page 0x07 のキーコード対応表および QMK 互換エイリアス。
`logicd` がアクション文字列（`KC_*`）を HID Usage ID に変換するために参照します。
通常は編集不要です。

---

## key_labels.json

Web UI（`httpd`）でキーキャップに表示するラベル文字列のマッピングです。
`KC_A → "A"` のような表示用テキストを定義します。
JIS 配列のシフト面ラベル（`"!\n1"` など改行区切り）にも対応しています。

---

## keyboard-layout.json

KLE（Keyboard Layout Editor）形式のキーボード物理レイアウト定義。
`httpd` の Web UI がキーボード見取り図を描画するために使用します。
KiCad PCB から `script/kicad_to_vial_layout.py` で生成されます。

---

## vial.json

Vial/QMK 互換のキーボードメタデータ定義。
`viald` デーモンが Vial Raw HID プロトコルで PC 側の Vial アプリと通信する際に参照します。
`uid`・`matrix` サイズ・`lighting` 種別などを含みます。
`build/generators/mkvial.py` で生成されます。

---

解析スクリプトが作る `pcb_analysis.json` や `keymap_matrix_analysis.json` は
実行時設定ではないため、`build/generated/` に置きます。
