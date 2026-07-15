# C helper command policy

このフォルダは、KC_SH や shell script から軽く呼べる C 言語系補助コマンドの置き場です。

## 目的

- Python 起動待ちが目立つ用途で、短時間に起動して終了する小さなコマンドを提供する。
- `logicd` / `i2cd` の既存 UNIX socket protocol を直接使い、新しい daemon を増やさない。
- 実行時に `config/default/*.json` や大きな定義ファイルを読まない。
- 実機操作でホストが取りこぼしにくいよう、key tap には既定の hold / gap を持たせる。

## 境界

- `/tmp/key_events.sock`
  - 4 byte packet を送る。
  - packet は `event_type`, `hid_keycode`, `modifier`, `0x00`。
  - `event_type` は press `0x50` / release `0x52`。
  - ここへ送る keycode は 8bit HID usage ID とする。`KC_SH2` などの内部 custom keycode は送らない。
- `/tmp/i2c_events.sock`
  - JSON Lines を送る。
  - OLED alert は `{"t":"alert","msg":"...","sec":2.0}`。
  - OLED warning は `{"t":"warning","msg":"...","sec":2.0}`。
  - `hidloom-notify` は同じ OLED message を送り、あわせて syslog / journal にも記録する。
- `/tmp/ctrl_events.sock`
  - JSON Lines を送る。
  - `logicd` control protocol の汎用入口として扱う。
  - よく使う操作は `hidloom-ctrl layer ...` / `output ...` / `bt ...` / `led ...` などの短いサブコマンドで包み、未対応の操作は `hidloom-ctrl json ...` で直接送る。

## 実行時の方針

- runtime は socket path、文字列、数値 option だけを見る。
- keycode 名や layout 変換が必要な場合は、実行時 JSON parse ではなくビルド時生成ヘッダを追加する。
- 失敗時は stderr に短い理由を出し、非 0 で終了する。
- 送信は `connect -> write all -> close` を基本とし、常駐しない。
- 依存は libc / POSIX socket の範囲に留める。

## key tap timing

既定値は `daemon/logicd/macro.py` と同じ考え方で、press 後 30ms、release 後 20ms 待つ。
これは高速化しすぎると USB host / OS 側で短い press-release を取りこぼすことがあるため。

必要に応じて `--hold-us` / `--gap-us` で短縮できるが、KC_SH から使う標準値は保守的にする。

## KML / macro との関係

このフォルダのコマンドは macro language ではなく、低レベル送信部品です。
KML / QMK 互換 runner を作る場合は、parse / 展開は別層に置き、最終送信だけここで使う関数や protocol に寄せます。

## 今後の拡張候補

- `config/default/keycodes.json` などから C header を生成する build helper。
- keycode 名指定の `hidloom-key tap KC_A`。
- modifier chord や複数キー同時押しの軽量 command。
- OLED alert / warning 以外の status / progress message。
- `hidloom-ctrl` の追加 short command は、実運用でよく使う操作が見えてから増やす。
