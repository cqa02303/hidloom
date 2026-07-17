# hidd Test Matrix

## Unit / Host

| 項目 | 期待結果 |
|---|---|
| valid keyboard report | descriptor と一致する長さで受理される |
| invalid length | endpoint に書かず error になる |
| unknown report ID | 方針通り拒否または隔離される |
| short write simulation | success 扱いにしない |
| descriptor default | 既存 interface / report length が変わらない |
| startup release shape | mainはReport ID `0x01` + 8 zero bytes、US subはReport IDなし8 zero bytesになる |

## Integration

| 項目 | 期待結果 |
|---|---|
| endpoint missing | 明示的 error になる |
| source disconnect | stuck key を残さない |
| restart | zero / clear state で復帰する |
| first input after startup | endpoint別zero reportより前にnon-zero keyboard reportを送らない |
| input queued before endpoints | queued inputより先に両endpointへzero reportを書き、write errorなしで後続inputを処理する |
| native + Python coexistence | 二重送出しない |
| legacy broker disabled | 通常運用で legacy broker flag が有効化されていない |

## Real Device / Host

| 項目 | 期待結果 |
|---|---|
| Linux host enumeration | keyboard device として認識される |
| Linux key input | press / release が 1 回ずつ届く |
| Windows host enumeration | keyboard device として認識される |
| Windows key input | stuck key / duplicate key がない |
| unplug / replug | endpoint と source が復帰する |
| cold boot / first enumeration | Ctrlを含むmodifierが入力なしでactiveにならない |
| Vial Raw HID | descriptor 変更後も Vial Raw HID が見える |
