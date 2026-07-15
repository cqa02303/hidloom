# matrixd Test Matrix

## Unit / Host

| 項目 | 期待結果 |
|---|---|
| debounce state machine | threshold 未満の揺れを event にしない |
| duplicate press | release なしの二重 press を出さない |
| duplicate release | press なしの二重 release を出さない |
| coordinate map | profile の logical coordinate と一致する |

## Integration

| 項目 | 期待結果 |
|---|---|
| logicd 未起動 | matrixd が壊れた event を出さず待機または再接続する |
| logicd 再起動 | event stream が復帰する |
| profile mismatch | 原因がログに残る |
| high load | scan loop が実用範囲で維持される |
| LED high-brightness effect | idle key event が増えない |

## Real Device

| 項目 | 期待結果 |
|---|---|
| 全 key 単押し | 期待 coordinate の press / release が 1 回ずつ出る |
| 隣接 key 同時押し | ghost / missing がない |
| 長押し | repeat ではなく stable press state として維持される |
| 高速打鍵 | missed press / release がない |
| service restart | stuck state なしで復帰する |
| artifact check | 実機 ARM binary を local x86_64 artifact で置換していない |
