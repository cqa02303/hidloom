# httpd Detailed Spec

`httpd` は local web UI / API の入口です。複数 daemon の状態や設定を扱うため、API response contract、validation、partial failure の扱いを明確にします。

## 役割

- keymap、lighting、Bluetooth、system status、scripts、Morse などの HTTP API を提供する。
- daemon 状態を UI が扱いやすい JSON に整形する。
- 設定変更 request を validation し、担当 daemon / store へ渡す。

## 非役割

- matrix scan、HID report 送出、BLE GATT 実体は担当 daemon に委譲する。
- UI convenience のために runtime state を勝手に捏造しない。

## 所有するリソース

- 実装: `daemon/http/`
- 入力: HTTP request、static UI access
- 出力: JSON response、daemon control request

## 実装時に守る条件

- response field 名を不用意に変えない。
- daemon 未起動時は UI 全体を落とさず、該当機能だけ degraded response にする。
- 設定変更は validation error と apply error を区別する。
- shell / script 実行 API は安全境界を文書化する。
- `/api/status` は systemd / Bluetooth / daemon status の重い問い合わせを毎 request で連打しない。cache / TTL を維持する。
- paired host 数が増えた場合、Bluetooth detail の N 件問い合わせが status latency を悪化させないよう監視する。
- service shutdown 時は WebSocket / aiohttp handler を長く待たず、restart が timeout failed にならないようにする。
- virtual keyboard の mouse button は pointer が key 領域外へ出ただけで release しない。
- board profile / layout API は runtime keymap と repo default の優先順位を UI が誤解しない形で返す。

## テスト観点

- API schema smoke。
- daemon unavailable。
- invalid request。
- static UI asset serving。
- shutdown / restart with open WebSocket。
- mouse button drag on virtual keyboard。
