# logicd Test Matrix

## Unit

| 項目 | 期待結果 |
|---|---|
| keymap JSON load | 既存 config が読み込める |
| unknown field | 方針通りに許容または拒否される |
| press / release pairing | release が press 時 resolved action を参照する |
| undefined key | no-op になる |
| output router selection | report 種別ごとの route が分かれる |
| mouse button + motion | 押下中 button bit が motion report に merge される |
| unknown host profile | transform が no-op / warning になる |

## Integration

| 項目 | 期待結果 |
|---|---|
| matrixd 未接続で起動 | logicd が起動し reconnect 待ちになる |
| HID route 未接続 | key resolution が停止しない |
| Bluetooth route 未接続 | USB route が動く |
| keymap reload | 古い押下 state が stuck key を作らない |
| control API invalid request | daemon crash にならない |
| runtime keymap present | `/mnt/p3/keymap.json` 優先の挙動を誤判定しない |

## Real Device

| 項目 | 期待結果 |
|---|---|
| 通常 key press / release | host に 1 press / 1 release として見える |
| layer hold 中の key | hold layer の key として出力される |
| layer release 後の key release | press 時 action の release になる |
| output route 切替 | stuck key が残らない |
| service restart | 安全な初期 state で復帰する |
| Windows IME standard route | Raw HID 診断結果と混同せず keyboard report bytes を確認する |

## Fault Injection

| 項目 | 期待結果 |
|---|---|
| malformed matrix event | no crash、diagnostic に残る |
| control socket 切断 | reconnect / retry 方針に従う |
| output broker 停止 | route 単位で degraded になる |
| config 破損 | unsafe output を送らず停止理由を残す |
