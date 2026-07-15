# Bluetooth host last connected timestamp design

更新日: 2026-06-10

この文書は、Bluetooth paired host overview に `last connected` を追加する前の設計メモです。
read-only host overview は実装済みですが、どの時点を「接続」とみなすか、どこへ保存するか、host rename / forget とどう整合させるかを先に固定します。

## 結論

- まず read-only 表示の拡張として扱う。
- host rename / host 単位 forget とは分けて進める。
- `last_connected_at` は「BLE HID notify path が使える状態になった時刻」にする。
- BlueZ の paired / bonded / trusted だけでは接続成功扱いにしない。
- 保存先は `/mnt/p3/bluetooth_hosts.json` にする。
- config schema や Vial / keymap とは混ぜない。
- event source は btd とし、HTTP status は保存済み metadata を read-only で merge する。

## 対象外

この設計TODOでは、次を対象外にします。

- host rename / host forget の実装
- Bluetooth reconnect policy の変更
- BlueZ device 管理 UI の変更

## 目的

現在の read-only host overview は、paired / bonded / trusted / connected などの状態を表示できます。
しかし運用上は、どの host が最近使われたかを知りたい場面があります。

目的:

- 複数 host がある時に、最近使った host を見分ける。
- stale な bonded device を判断しやすくする。
- rename / forget UI を将来作る前の安全な観測情報にする。

## last connected の定義候補

### 候補 A: BlueZ `Connected=true` を見た時刻

利点:

- BlueZ 側の状態として自然。
- device overview と対応しやすい。

欠点:

- Connected でも HID notify がまだ使えない可能性がある。
- 一瞬の接続も記録してしまう可能性がある。

### 候補 B: GATT notify / HID report path が使える状態になった時刻

利点:

- 実際に keyboard / mouse として使える状態に近い。
- ユーザー視点の「接続した」に近い。

欠点:

- btd 側で event を取る必要がある。
- keyboard / mouse / consumer など、どの report path を接続成功扱いにするか決める必要がある。

### 候補 C: 初回 HID report 送信成功時刻

利点:

- 実際の入力到達に近い。

欠点:

- 接続しただけで何も打たない host は記録されない。
- last connected ではなく last used に近い。

採用:

- `last_connected_at`: 候補 B。HID notify path が使える状態になった時刻。
- `last_used_at`: 将来候補。初回 report 送信成功または最後の report 送信時刻。
- 具体的には BlueZ GATT の keyboard Input Report または Boot Keyboard Input Report が `StartNotify` され、`BlueZGattAdapter.status().notifying == true` として見える状態を `btd_notify_ready` と呼ぶ。
- mouse / consumer notify だけでは `last_connected_at` を更新しない。keyboard notify を基準にすることで、キーボードとして使える状態を優先する。

## 保存先候補

採用:

```text
/mnt/p3/bluetooth_hosts.json
```

例:

```json
{
  "version": 1,
  "hosts": {
    "AA:BB:CC:DD:EE:FF": {
      "last_connected_at": "2026-05-28T12:34:56+09:00",
      "last_seen_name": "iPhone",
      "last_connected_source": "btd_notify_ready"
    }
  }
}
```

理由:

- host metadata はユーザー運用データであり、`config/default/config.json` より runtime persistent data に近い。
- rename / notes / host preference などを将来追加しやすい。
- keymap / Vial / layout と混ぜない方が安全。

不採用:

- `config/default/config.json` の `settings.bluetooth.hosts`
  - 設定としては読みやすいが、host runtime metadata が config に混ざる。
- BlueZ device metadata のみに依存
  - 実装は軽いが、UI向けの任意メタデータを持ちにくい。

## event source 候補

### btd

最有力です。

理由:

- BLE HID notify / connection state に近い。
- host ごとの BLE event を把握しやすい。
- `last_connected_at` の定義を HID path ready に寄せやすい。

懸念:

- btd が落ちた時の保存 flush。
- device address と display name の取得タイミング。

### logicd

候補です。

理由:

- output routing の観点では、実際に BT backend を使ったタイミングを知りやすい。

懸念:

- host address / display name を logicd が直接持つべきか悩ましい。
- btd 固有情報を logicd に寄せすぎる可能性がある。

### httpd / status_api

採用しません。

理由:

- HTTP status は表示の入口であって、接続 event の source of truth ではない。
- polling のたびに last connected を書き換える事故を避けたい。

採用:

- event source は btd。
- HTTP status は保存済み metadata を read-only で表示するだけ。
- logicd には host metadata を渡さない。
- btd は notify ready を検出した時に `/mnt/p3/bluetooth_hosts.json` を atomic write で更新する。
- btd が device address / name を取れない場合は、その更新をスキップし、次の connected devices monitor で再試行する。

## UI 表示案

System panel の read-only Bluetooth host overview に追加する候補:

- `Last connected: 2026-05-28 12:34`
- `Last connected: 3h ago`
- unknown の場合は `Last connected: —`

採用:

- simple view では非表示のままでもよい。
- detail view で表示する。
- timestamp は local timezone 表示にする。
- raw ISO timestamp は API payload に残す。
- unknown の表示は `Last connected: -` にする。
- row title には raw `last_connected_at` と `last_connected_source` を含める。

## API payload 案

`/api/status.bluetooth.devices[]` に追加する候補:

```json
{
  "mac": "AA:BB:CC:DD:EE:FF",
  "name": "iPhone",
  "paired": true,
  "bonded": true,
  "trusted": true,
  "connected": false,
  "last_connected_at": "2026-05-28T12:34:56+09:00",
  "last_connected_source": "btd_notify_ready"
}
```

未記録時:

```json
{
  "last_connected_at": null,
  "last_connected_source": null
}
```

採用 field:

- `last_connected_at`
- `last_connected_source`

HTTP status merge:

- `/api/status.bluetooth.devices[]` を組み立てる時に、device MAC で `/mnt/p3/bluetooth_hosts.json` の `hosts` を引く。
- metadata file が無い、壊れている、対象 MAC が無い場合は `last_connected_at=null`, `last_connected_source=null` を返す。
- HTTP status polling は metadata file を更新しない。
- HTTP status merge と System panel detail 表示は実装済み。
- btd writer は実装済み。keyboard notify ready と connected device snapshot を同時に見た時だけ observation metadata を更新する。

## Writer readiness boundary

btd writer を追加する時は、metadata file を host operation state と混ぜません。

- Writer が更新する field は `last_connected_at`、`last_connected_source`、`last_seen_name` に限定する。
- `display_name` は rename UI の owner field として扱い、notify ready writer は変更しない。
- per-host forget / unpair / forget all の destructive operation は、writer とは別の operation path と audit に分ける。
- active host 表示は live Bluetooth status を source とし、保存済み `last_connected_at` だけで active 扱いにしない。
- `btd` restart 後は保存済み timestamp を last connected metadata として表示してよいが、connected / notify ready は live status が再観測されるまで false / unknown にする。
- `/mnt/p3/bluetooth_hosts.json` が missing の場合は empty metadata として扱い、HTTP status は `last_connected_at=null` を返す。
- corrupt JSON の場合は書き換えず、HTTP status は empty metadata fallback として扱う。
- writer 実装時は temp file + fsync + atomic replace の順で保存し、partial write を visible state にしない。

2026-06-10に`<keyboard-host>`とWindows test hostでpairing / keyboard notify ready /
ChatGPT 入力欄への実入力を確認した。`btd` restart 後、writer が
`last_connected_source=btd_notify_ready`、`last_seen_name=WINDOWS-TEST-HOST`、`last_connected_at`を
`/mnt/p3/bluetooth_hosts.json` へ保存し、`/api/status.bluetooth.devices[]` に merge されることも確認済み。
HTTP status polling や System panel 表示から metadata は作らない方針を維持する。

## host rename / forget との関係

この設計は rename / forget より先に進めてもよいです。

- last connected は read-only metadata。
- rename は user editable metadata。
- forget は destructive operation。

誤操作リスクが低い順:

1. last connected timestamp
2. user note / display alias
3. host rename
4. host forget

したがって、last connected は rename / forget より先に実装候補にできます。

## 受け入れ条件

実装TODOへ進む前に、以下を決めます。

- [x] `last_connected_at` の定義を HID notify ready にするか、BlueZ Connected にするか。
- [x] 保存先 path と JSON schema を決める。
- [x] btd が event source でよいか確認する。
- [x] `/api/status.bluetooth.devices[]` の追加 field 名を決める。
- [x] UI 表示位置と unknown 表示を決める。
- [x] 実機確認手順を決める。

## 実機確認案

実装後に必要な確認:

1. 既存 bonded host が connected になり keyboard notify ready になった時、`last_connected_at` が更新される。
2. pairing 直後に keyboard notify ready へ進めば `last_connected_at` が記録される。
3. btd restart 後も保存値が残る。
4. disconnected host は timestamp を維持し、connected=false と区別できる。
5. `/api/status` に raw timestamp が出る。
6. System panel detail view に human readable timestamp が出る。
7. unknown host / timestampなしでも UI が壊れない。

## 現時点の判断

設計TODOの受け入れ条件は埋まり、HTTP status merge / System panel detail 表示までは実装済みです。
2026-06-10 時点で btd writer と実機 smoke は完了済みです。後続は host profile active metadata、
mouse notify、BLE Keyboard Output Report `WriteValue`、per-host forget の実操作確認へ分けます。
