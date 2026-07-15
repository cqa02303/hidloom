# logicd: デバッグ用 DebugOutput

`debug` output は、確定済み keyboard HID report をログへ出すためのデバッグ用 backend です。

## 目的

チャーリープレックス配線、matrix scan、keymap 変換、press/release イベント、HID 出力前のイベント列を安全に切り分けて確認する。

確認したいこと:

- matrix → keymap 変換後の keycode が期待通りか
- press/release が正しく出ているか
- チャタリングやゴースト由来の異常イベントが見えるか
- HID 出力前段までの問題か、HID/uinput/BT 出力側の問題かを切り分けられるか

## 使い方: debug のみ

```bash
cd /path/to/hidloom
sudo LOG_LEVEL=INFO LOGICD_OUTPUTS=debug PYTHONPATH=daemon python3 -m logicd.logicd
```

## 使い方: fan-out の一部として debug も有効化

`debug` は通常 backend の 1 つなので、実出力しながら同じ report をログにも出せる。

```bash
sudo LOG_LEVEL=INFO LOGICD_OUTPUTS=gadget,uinput,debug PYTHONPATH=daemon python3 -m logicd.logicd
```

## ログ例

```text
DebugOutput: report=0000040000000000
DebugOutput: report=0000000000000000
```

`report=` は、そのイベントを反映したあとの 8-byte keyboard HID report です。

## 旧制御について

以前の `LOGICD_OUTPUT_BACKEND=log` は削除し、`LOGICD_OUTPUTS=debug` に統一する。
出力選択を 1 つの仕組みに寄せることで、debug-only と fan-out の両方を同じ OutputRouter で扱う。

## テスト

```bash
python3 -m unittest tests.test_log_output
python3 -m unittest tests.test_output_router
```

## 関連 Issue

- #6 TODO: デバッグ用 LogOutput を追加する
