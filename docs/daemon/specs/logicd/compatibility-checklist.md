# logicd Compatibility Checklist

機能追加、Rust 移植、JSON schema 変更、output route 変更の前後で確認します。

## Keymap / JSON

- [ ] 既存 keymap JSON を無変換で読み込める。
- [ ] 実機に `/mnt/p3/keymap.json` がある場合、repo default ではなく runtime keymap が優先されることを確認した。
- [ ] 不明 field の扱いが既存と同じ、または version gate つきで変わる。
- [ ] action 名、keycode alias、macro 定義の解釈が既存と一致する。
- [ ] default layer、active layer、conditional layer の初期値が既存と一致する。
- [ ] keymap reload 後に押下中 state を安全に扱う。

## Event Semantics

- [ ] press / release の対応関係を保持する。
- [ ] release 時に press 時の resolved action を参照する。
- [ ] 未定義 key は no-op になる。
- [ ] unknown action は送出しない。
- [ ] debounce や matrix scan 側の重複 event を logicd 側で二重送出しない。

## Output

- [ ] keyboard report の modifier / key slots が既存と一致する。
- [ ] consumer / system / mouse / custom HID の report route を混同しない。
- [ ] mouse motion report で押下中 button bit を `buttons=0` に戻していない。
- [ ] USB route 未接続時も Bluetooth route の動作を壊さない。
- [ ] Bluetooth route 未接続時も USB route の動作を壊さない。
- [ ] stuck key を避けるため、route 切替時の release / clear 方針が決まっている。
- [ ] `KC_USB` / `KC_CONSOLE` / `KC_BT` / `KC_CONNAUTO` が native owner 時に `hidloom-outputd` target を変更する。

## Runtime Control / Status

- [ ] 既存 control command が同じ request / response で動く。
- [ ] status field 名を壊していない。
- [ ] error response が UI / script 側で解釈可能な形になっている。
- [ ] log output の確認手順が残っている。
- [ ] unknown active host では host profile transform が no-op / warning になる。
- [ ] text send、physical usage alias、host profile transform の責務が混ざっていない。

## Rust Core 投入時

- [ ] Python `logicd` と Rust `logicd-core-rs` が同じ physical event を二重処理しない。
- [ ] Rust 側に移した state と Python 側に残る state の owner が一意に決まっている。
- [ ] fallback 時に route / state を二重初期化しない。
- [ ] 実機 A/B で native path と Python path の output report を比較する。
- [ ] legacy `LOGICD_USBD_HID_REPORT_BROKER` を通常運用へ戻していない。
