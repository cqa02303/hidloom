# hidd Behavior Contract

## HID Report Contract

- descriptor の report ID と payload の report ID は一致する。
- report length は descriptor と一致する。
- keyboard / consumer / system / mouse / custom HID の report 種別を混同しない。
- 不正長 payload は host endpoint に書かない。

## Startup Contract

- 起動直後に古い pressed state を host に見せない。
- current split profileではinput frameを読む前に、`hidg0`へReport ID `0x01` + 8 zero bytes、`hidg2`へReport IDなし8 zero bytesを送る。
- broker socketへ先にinputがqueueされても、両endpointのzero reportが成功するまでそのinputを処理しない。
- endpoint が存在しない場合、panic ではなく明示的な error にする。
- endpoint 準備前の report を送るか捨てるかを実装ごとに明示する。

## Runtime Contract

- source 切断時に stuck key を残さない。
- service restart 時に last report を盲目的に再送しない。
- short write は成功扱いにしない。
- EPIPE / ENODEV / permission error は区別して診断可能にする。

## Compatibility Contract

- 既存 host が認識している descriptor を変更する場合、host OS ごとの再認識影響を記録する。
- report ID 追加は既存 report ID の意味を変えない。
- fallback path と native path が同じ report を同時に送らない。
- default 起動で既存 keyboard / mouse / consumer / Vial Raw HID interface を変えない。
- Raw HID / Vial endpoint の report length を descriptor 変更の副作用で変えない。
- Windows IME / custom HID route は diagnostic と通常 keyboard route の成功条件を分ける。
