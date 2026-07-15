# macro

キーボード入力を自動化するための CLI macro tool を置くディレクトリです。
Vial GUI の macro 機能とは別系統で、`/tmp/key_events.sock` を通して `logicd` へキーイベントを送ります。

## ツール一覧

### sendkey.py / send_key.sh

低レベルのキーイベント送信ツール。単一のキーを押す/離す/タップする。

```bash
# キーをタップ（press → release）
./sendkey.py tap 0x04           # 'A' キー
./sendkey.py tap 0x04 0x02      # Shift+'A' (大文字A)

# キーを押す/離す
./sendkey.py press 0xe0         # 左Ctrlを押す
./sendkey.py release 0xe0       # 左Ctrlを離す
```

### kml.py / kml.sh

KML (Keyboard Macro Language) interpreter です。テキストベースのマクロ言語で複雑な入力シーケンスを記述・実行できます。

- タイミング制御（BPM、音符長）
- 同時押し・修飾キー制御
- 特殊キー（Enter, Tab, F1など）のサポート
- シェルエスケープシーケンス（`\n`, `\t`, `\s`）

```bash
# KMLファイルを実行
./kml.py examples/copy_paste.kml
./kml.sh examples/copy_paste.kml

# 文字列を直接実行（シングルクォート推奨）
./kml.py -c '\T180 \[Ctrl c\] \R8 [End] \n \[Ctrl v\]'
./kml.sh -c '\T180 Hello\sWorld\n'

# デバッグモード（ソケット送信せず、標準出力に表示）
./kml.py --debug examples/copy_paste.kml
./kml.py -c --debug 'Test'
```

KML 構文の例:

| 記述 | 意味 |
|------|------|
| `Hello` | "Hello" と入力 |
| `\s` | スペースを入力 |
| `\n` | Enterキーを押す |
| `\t` | Tabキーを押す |
| `[Enter]` | Enterキー（特殊キー形式） |
| `[F1]` | F1キーを押す |
| `\[Ctrl c\]` | Ctrl+C（範囲制御） |
| `\[Shift hello\]` | Shiftを押しながら "hello" |
| `\T180` | テンポを180 BPMに設定 |
| `\L4` | デフォルトキー長を4分音符に |
| `\R8` | 8分音符分の待機 |
| `A4` | Aを4分音符の長さで入力 |

サンプルファイル:

- `examples/copy_paste.kml` - コピー&ペーストマクロ
- `examples/password.kml` - パスワード入力デモ
- `examples/timing_demo.kml` - タイミング制御デモ

詳細仕様は [`KML.md`](KML.md) を参照してください。

## 前提条件

- Python 3.x
- logicd が実行中であること（`/tmp/key_events.sock` が必要）

## IPC 通信

すべてのツールは `/tmp/key_events.sock` (Unixドメインソケット) を通じて logicd にキーイベントを送信します。

protocol:

```
[event_type][keycode][modifier][0x00]
```
- `event_type`: 0x50 (Press) または 0x52 (Release)
- `keycode`: USB HIDキーコード (0x00-0xFF)
- `modifier`: モディファイアビット (bit0=LCtrl, bit1=LShift, ...)
- 最終バイト: 常に 0x00 (予約)
