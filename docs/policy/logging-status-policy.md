# Logging And Status Policy

更新日: 2026-05-22

この文書は、daemon log、HTTP `/api/status`、OLED alert / status の役割分担を整理する。
運用中の切り分けで見る場所を迷わないようにし、UI には内部実装名をそのまま出しすぎない。

## 方針

| 出力先 | 役割 |
|---|---|
| journal log | 開発・障害調査向け。内部名、socket path、systemd env、BlueZ 状態などを残す |
| HTTP status | 運用・診断向け。通常見る簡潔な状態と、必要時に開ける詳細状態を同じ API で返す |
| OLED status | 手元確認向け。短く、入力中でも読める名称にする |
| OLED alert | 一時的な操作結果・エラー通知。pairing / output 切替 / script 終了などを短時間表示する |

## 表示名

内部名とユーザー向け表示名は分ける。

| 内部名 | UI/OLED 表示 |
|---|---|
| `gadget` | `USB` |
| `bt` | `BT` |
| `uinput` | `Pi` |
| `auto + gadget` | `AUTO USB` |
| `auto + bt` | `AUTO BT` |
| `auto + uinput` | `AUTO Pi` |

HTTP status の詳細や journal log では、内部名も残してよい。
画面上の一次表示では `USB` / `BT` / `Pi` へ変換する。

## daemon ごとの重要ログ

### logicd

残すべきログ:

- 起動時の output router 構成
- keymap reload / save / reset
- output target 変更 (`auto`, `gadget`, `bt`, `uinput`)
- BT output が外れた時の null report / host disconnect hook
- InteractionEngine の validation warning
- matrix の duplicate press / stray release は debug

避けるログ:

- 通常打鍵ごとの info ログ
- HID report の常時 info 出力。必要時は `LOGICD_OUTPUTS=debug` を使う

### btd

残すべきログ:

- GATT application / advertisement registration
- `StartNotify` / `StopNotify`
- host connected / disconnected
- stuck reconnect 検出と recovery
- pairing mode on/off
- null report reset

避けるログ:

- report payload の常時 info 出力。必要時は trace / debug 設定で見る

### httpd

残すべきログ:

- keymap set / reset / layer add / clear
- `.vil` import/export の適用件数と warning 件数
- Bluetooth pairing / forget API の結果
- status 取得に必要な外部コマンドの timeout / error

避けるログ:

- `/api/status` の定期取得成功ログ
- `/api/keymap/active` / `/api/matrix` の定期取得成功ログ
- WebSocket の通常 key event

HTTP access log は `_HttpAccessLogger` で高頻度 polling endpoint の成功ログを抑制し、
操作 API や異常調査に必要な request は残す。

### viald

残すべきログ:

- Vial keymap SET / buffer SET の accepted / rejected
- unsupported command / out-of-range access
- `.vil` / Vial dynamic data の変換 warning

避けるログ:

- 通常 GET packet の常時 info ログ

### ledd / i2cd / spid

残すべきログ:

- 起動時 backend / device 構成
- device open failure
- direct-frame producer disconnect / invalid frame
- OLED alert / status の描画不能エラー
- spid sensor identification / backend disabled

`i2cd` の OLED alert / warning は通常 queue 表示にする。
入力中の feedback など古い表示を待つと意味が薄れる通知は、message 内容による特例ではなく
`immediate: true` を付けて即時表示へ切り替える。

## HTTP `/api/status`

`/api/status` は、通常表示用と診断用の両方を返す。

通常表示で使う項目:

- HID gadget connected
- output mode / output target
- process running state
- Bluetooth powered / pairing / connected count

診断表示で使う項目:

- `output.logicd_outputs_env`
- `output.runtime_mode`
- `output.output_target`
- `output.display_label`
- `output.runtime_mode_label`
- `output.output_target_label`
- `btd.runtime.host_connected`
- `btd.runtime.service_registered`
- `btd.runtime.advertising_registered`
- `btd.runtime.stuck_reconnect_recoveries`
- `ledd_direct_frame.accepted_frames`
- `ledd_direct_frame.applied_frames`
- `ledd_direct_frame.ignored_frames`
- `ledd_direct_frame.direct_frame_active`
- `ledd_direct_frame.rejected_frames`
- `ledd_direct_frame.producer_connects`
- `ledd_direct_frame.producer_disconnects`
- daemon socket existence / path / mode

`/api/status` は原則 side-effect free とする。
例外は、btd runtime status の read-only control frame のように、状態取得専用で副作用がないものに限定する。

## 実機確認ポイント

- auto 選択中に HTTP status が `AUTO USB` / `AUTO BT` / `AUTO Pi` と表示される。
- HTTP `/api/status` の `output.display_label` も同じ表示名を返し、UI はこれを優先する。
- OLED も同じく `AUTO` + `USB` / `BT` / `Pi` の組み合わせで表示される。
- Pair on/off、Forget、output切替時に OLED alert が短時間表示され、通常 effect が戻る。
- `journalctl -u hidloom-logicd-core -u logicd-companion -u btd -u httpd --since -5min` で、通常操作時に過剰な info ログが出ない。
- `python3 script/test_i2cd_output_mode_label.py` で OLED の `AUTO USB` / `AUTO BT` / `AUTO Pi`
  表示が崩れていないことを確認する。

## 関連ファイル

- `daemon/http/static/status_panel.js`
- `daemon/http/system_api.py`
- `daemon/logicd/output_router.py`
- `daemon/logicd/output_switch.py`
- `daemon/logicd/notifications.py`
- `daemon/i2cd/i2cd.py`
- `daemon/btd/btd.py`
- `docs/TODO_PRIORITY.md`
