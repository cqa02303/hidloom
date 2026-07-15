# uidd / hidloom-uidd Detailed Spec

`uidd` / `hidloom-uidd` は native output routing の一部として、host input device への送出を軽量化する component です。`hidd` と同様、report contract と source ownership を崩さないことを最優先にします。

## 役割

- 上位から受け取った report / input event を低遅延で送出する。
- Python output path の代替または補助として動作する。
- endpoint / device write の error を診断可能にする。
- `hidloom-outputd` の `uinput` target から届く broker frame を Linux input event へ変換する。

## 非役割

- keymap / layer / macro 解決は行わない。
- matrix scan は行わない。
- report descriptor の意味を勝手に変更しない。

## 所有するリソース

- 実装: `tools/hidloom_uidd/`
- systemd: `system/systemd/hidloom-uidd.service`
- 関連仕様: [../../../architecture/native-output-routing-uidd-design.md](../../../architecture/native-output-routing-uidd-design.md)
- 入力: `/tmp/uidd_reports.sock`
- 出力: `/dev/uinput`

## 実装時に守る条件

- source が複数ある場合、同一 report の二重送出を避ける。
- malformed payload を device へ書かない。
- short write を success として扱わない。
- restart 時に古い report を再送しない。
- keymap / layer / macro は解釈せず、HID report 差分から EV_KEY press/release を生成する。
- target switch 時の release-all / null report を正しく反映し、local console に stuck key を残さない。

## テスト観点

- valid / invalid payload。
- endpoint missing / permission error / disconnect。
- Python route との A/B。
- 実機 host 側で duplicate / stuck input がないこと。
- `hidloom-outputd` `uinput` target からの frame forwarding。
