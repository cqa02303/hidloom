# BLE Host LED Output Report design

更新日: 2026-05-30

BLE host から来る Keyboard LED Output Report を、既存の USB host lock LED と同じ
`HOST_LED` 経路へ流すための実装前設計です。

この設計では、まだ wiring 実装はしません。実機で BLE host の `WriteValue` 発火を
再確認してから実装します。

## 現状

実装済み:

- BLE HID GATT には Keyboard Output Report characteristic と Boot Keyboard Output Report
  characteristic がある。
- iOS から Keyboard Output Report へ `WriteValue value=0100` が来ることは確認済み。
- USB `/dev/hidg0` OUT report は `daemon/logicd/host_led_reader.py` で読み、
  `HOST_LED` ctrl message と同じ処理へ渡している。
- `logicd` は `{"t":"HOST_LED","report":2}` を受けると、設定済みの
  `caps_lock` / `num_lock` / `scroll_lock` / `compose` / `kana` を
  `ledd` の state overlay へ反映できる。

未接続:

- `btd.gatt_adapter` の `WriteValue` は value を保持して log するだけで、
  `logicd` へ `HOST_LED` を送らない。

## 方針

BLE の Output Report は新しい意味を作らず、USB と同じ 1-byte keyboard LED bitfield として扱う。

```json
{"t":"HOST_LED","report":2}
```

bit の意味は `daemon/logicd/host_led_output.py` の定義に合わせる。

| bit | state |
| --- | --- |
| 0 | `num_lock` |
| 1 | `caps_lock` |
| 2 | `scroll_lock` |
| 3 | `compose` |
| 4 | `kana` |

## daemon 責務

`btd`:

- BlueZ / GATT の `WriteValue` を受ける。
- Keyboard Output Report / Boot Keyboard Output Report の value だけを対象にする。
- payload の先頭 byte を keyboard LED bitfield として抽出する。
- `logicd` の ctrl socket へ `HOST_LED` JSON line を best-effort で送る。
- 送信に失敗しても BLE HID 入力 path と `btd` daemon を落とさない。

`logicd`:

- `HOST_LED` message の validation と state 変換を続けて担当する。
- `settings.host_led_output.states` と `lock_indicators` を source of truth にする。
- `led_overlay_state` 通知を通じて `ledd` へ状態を渡す。

`ledd`:

- 既存の state overlay と lock indicator 表示だけを担当する。
- BLE / USB の入力元は区別しない。

## payload handling

受け入れる payload:

- `b"\x00"` から `b"\x1f"` までを含む 1 byte 以上の value。
- 2 byte 以上の場合は HID Output Report の先頭 byte だけを使う。

無視する payload:

- empty value。
- Keyboard Output Report / Boot Keyboard Output Report 以外の characteristic / descriptor write。

drop 方針:

- ctrl socket が無い、接続できない、write に失敗する場合は DEBUG または rate-limited WARNING にする。
- retry queue は持たない。次の `WriteValue` で再送する。
- `btd` 停止時に追加の all-off `HOST_LED` は送らない。host state の source of truth は host 側であり、
  stale 表示が問題になる場合は `logicd` 側の host disconnect policy と一緒に扱う。

## 実装候補

最小実装:

1. `btd` に `logicd` ctrl socket へ JSON line を送る small helper を追加する。
2. GATT characteristic に optional `on_keyboard_output_report` callback を渡す。
3. Keyboard Output Report / Boot Keyboard Output Report の `WriteValue` だけ callback を呼ぶ。
4. callback は `{"t":"HOST_LED","report": <first byte>}` を送る。
5. unit test では `WriteValue([2])` が callback に `2` を渡すこと、empty value を無視することを固定する。

## 実装TODOへ進める条件

- BLE host で Keyboard Output Report または Boot Keyboard Output Report の `WriteValue` が再観測できる。
- その host で Caps / Num / Scroll の OS 側 state がどの bit に出るか確認できる。
- USB host lock LED 表示と同じ `HOST_LED` 経路へ渡しても表示 semantics が破綻しない。

2026-06-07 に `<keyboard-host>` で BT power cycle と `btd` / GATT service 復帰は確認済みです。
ただし paired host が 0 件だったため、BLE host からの `WriteValue` 再観測は未実施です。
実装 gate はこの条件が満たされるまで維持します。

## 実装しない条件

- BLE host が Output Report を送らない。
- host ごとに bit semantics が標準から外れる。
- `WriteValue` の発火が pairing / reconnect 時だけで、lock state 表示として安定しない。

## 関連

- [ble-gatt-hid-spec.md](ble-gatt-hid-spec.md)
- [lighting/led-semantic-roles.md](../lighting/led-semantic-roles.md)
- [../daemon/specs/btd/socket-protocol.md](../daemon/specs/btd/socket-protocol.md)
- `daemon/btd/gatt_adapter.py`
- `daemon/logicd/host_led_output.py`
- `daemon/logicd/host_led_reader.py`
- `daemon/logicd/ctrl.py`
- `script/test_logicd_host_led_output.py`
- `script/test_logicd_host_led_reader.py`
