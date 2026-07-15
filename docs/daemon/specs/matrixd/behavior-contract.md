# matrixd Behavior Contract

## Scan Contract

- stable state が変化したときだけ event を出す。
- raw read が揺れている間は stable transition として確定しない。
- 同一 key の press を release なしに二重発行しない。
- 同一 key の release を press なしに二重発行しない。
- scan interval を変更しても、event ordering は保持する。

## Coordinate Contract

- physical row / column は documented matrix map と一致する。
- logical coordinate への変換を変更する場合、keymap 互換性への影響を記録する。
- board profile 追加時は、未定義 pin を暗黙の有効 pin として扱わない。

## Debounce Contract

- debounce threshold 未満の揺れは event にしない。
- threshold 到達後、確定 event は 1 回だけ出す。
- event delivery が失敗した transition を stable committed state として扱わない。
- threshold や sampling rate を変更する場合、実機で missed input と false input の両方を見る。
- scan 高速化では busy loop guard と row settle time を両方確認する。

## Load / Noise Contract

- LED high-brightness effect の負荷で ghost input が再発しないことを確認する。
- RT priority 変更は matrixd 単体 CPU だけで判断せず、key event count、ledd key message、daemon log を合わせて見る。

## Diagnostics

- scan start、hardware init failure、profile mismatch はログに残す。
- latency instrumentation を追加する場合、通常 scan path の timing を壊さない。
- diagnostic 出力が上位 input event と混ざらないようにする。
