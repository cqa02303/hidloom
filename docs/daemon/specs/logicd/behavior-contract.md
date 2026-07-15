# logicd Behavior Contract

## Key Event Resolution

- matrix press は、その時点の keymap、layer、modifier、feature state で action に解決する。
- matrix release は、press 時に保存した resolved action を基準に release 処理する。
- release 時点で layer が変わっていても、別 action の release として扱わない。
- 未定義 key は fallback で別 key にしない。no-op とし、必要なら diagnostic に残す。
- 未知 action は送出しない。config validation で検出できる場合は読み込み時に報告する。

## Matrix Input Boundary

- matrix socket intake は packet parse、range check、queue put に留める。
- raw matrix intake に HID 生成、LED 通知、BT / Wi-Fi / macro、file I/O、subprocess、status lookup を置かない。
- 重い処理は resolved action 境界に置く。
- `process_matrix_event()` は pressed state、LED key event 通知、InteractionEngine dispatch までに留める。

## Layer State

- momentary layer は押下中のみ有効にする。
- one-shot / sticky / lock 系 state は、通常 key、modifier key、cancel 条件ごとに状態遷移を明示する。
- layer 解決の優先順位を変更する場合は、既存 keymap の observable output が変わるため test-matrix に追加する。
- conditional layer は、条件成立と解除の両方を記録し、解除漏れで stuck layer を作らない。

## Modifier And Feature State

- modifier press / release は HID report の bit state と内部 state が一致する。
- Caps Word、Repeat Key、Key Toggle Lock、Layer Lock、Mod Morph などは feature ごとに enable / disable / cancel 条件を持つ。
- feature が disabled の場合、その feature 固有 state は次の key event に影響しない。
- runtime reload 後、古い feature state が新しい keymap へ漏れない。

## Output Routing

- keyboard、consumer、system、mouse、custom HID は report 種別を混同しない。
- Bluetooth route と USB route を切り替える場合、押下中 key の release を失わない。
- route 未接続時に daemon を停止しない。
- route 再接続時、古い押下 report を再送して stuck key を作らない。
- mouse motion report を生成する時は、現在押下中の mouse button bit を `buttons=0` で上書きしない。
- Python path、legacy `usbd` broker path、native `logicd-core-rs -> hidloom-hidd` path を併用する時は、同じ report の owner を一意にする。
- 現行 native owner では output target 切替を `hidloom-outputd` control socket へ送る。companion 内の旧 Python `OutputRouter` だけを切り替えて成功扱いにしない。

## JSON / Runtime Contract

- 既存 JSON の field 名を変更しない。
- 新しい field は既存 loader が無視できる形、または明示的な version gate を持つ。
- 不明 field を許容するか拒否するかは loader ごとに明記する。
- default 値を追加する場合、古い config で起動できることを確認する。
- `/mnt/p3/keymap.json` が存在する実機では repo default keymap より runtime keymap が優先されるため、default keymap 変更の確認時は runtime keymap の有無も見る。

## Host Profile / Text Path

- active host が unknown の時は host profile transform を適用しない。
- automatic OS detection を根拠に modifier swap、JIS/US correction、keymap hot swap を行わない。
- physical HID usage alias、text send action、host profile transform を混ぜない。
- Windows IME route は standard keyboard HID、Raw HID diagnostic、helper route を分けて成功条件を記録する。

## Error Handling

- malformed control request は daemon crash にしない。
- 入力 source の切断は reconnect 可能状態にする。
- 出力先の切断は route 単位で扱い、key resolution 全体を停止しない。
- fatal と non-fatal の境界を変更した場合は README と test-matrix を更新する。
