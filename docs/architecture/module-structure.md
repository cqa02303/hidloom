# Module Structure

作成日: 2026-05-18
更新日: 2026-06-25

主要 daemon のファイル分割と責務をまとめます。基本方針は、daemon の入口ファイルには起動配線を残し、protocol / state / rendering / UI panel などの意味単位を小さな module に分けることです。

2026-06-25 時点の既定 owner 境界:

- boot-critical physical key path は `matrixd -> logicd-core-rs -> hidloom-outputd -> hidloom-hidd`。
- 観測・表示向けの best-effort path は `logicd-core-rs -> /tmp/matrix_tap_events.sock -> logicd-companion`。core が受理した通常 matrix edge だけを tap stream に出し、press / release を `observed_pressed_matrix` に反映する。現行 `ledd` consumer は press だけを reactive trigger として使う。
- Python `logicd` は `logicd-companion.service` として control plane / status merge / advanced action delegation を担当する。
- `logicd-companion` は `LOGICD_OUTPUTS=debug` と broker 無効化で動き、通常 keyboard report を output broker へ直接 fan-out しない。
- `KC_CONSOLE` / `KC_USB` / `KC_CONNAUTO` の native owner 復旧は、`logicd-core-rs` を uinput device owner にせず、`hidloom-outputd` と `hidloom-uidd` で実装済み。詳細は [native-output-routing-uidd-design.md](native-output-routing-uidd-design.md)。
- legacy Python `usbd.service` は通常 inactive。rollback / A/B 診断用として残す。

## logicd-core-rs

`tools/hidloom_logicd_core/` は現行既定の matrix socket owner です。基本 keymap/layer、stable HID key slot、release safety、USB split route、delegation boundary、broker frame generation を担当します。

| 領域 | 責務 |
| --- | --- |
| matrix input | `/tmp/matrix_events.sock` を listen し、`matrixd` からの `P/R row col` を処理する |
| matrix tap | core が受理した通常 matrix edge を `/tmp/matrix_tap_events.sock` へ best-effort で複製する。delegate / PTY mirror で companion 本線へ渡した event は二重 tap しない |
| HID state | 6-key slot を stable に保持し、意図しない release/repress を避ける |
| broker output | `hidloom-outputd` の `/tmp/hidloom_output_reports.sock` へ keyboard / US-sub keyboard frame を送る。USB / uinput の device owner 選択は core 外へ出す |
| delegation | `BT_*`、mouse、system/session、timed/composite など core 外 action を companion へ渡す |
| status | runtime state と counters を status / smoke helper で読める形にする |

## hidloom-hidd

`tools/hidloom_hidd/` は USB HID endpoint owner です。Python `usbd.hid_report_broker` と互換の 64-byte frame を受け、`/dev/hidg0` / `/dev/hidg1` / `/dev/hidg2` へ書きます。

| 領域 | 責務 |
| --- | --- |
| broker socket | `/tmp/usbd_hid_reports.sock` を bind し、keyboard / mouse / consumer / US-sub keyboard frame を受ける |
| endpoint owner | `/dev/hidg0` / `/dev/hidg1` / `/dev/hidg2` を open し、write error / reopen を管理する |
| Raw HID bridge | `/dev/hidg1` と `/tmp/viald_events.sock` の Vial packet を中継する |
| status | `/run/hidloom/hidd-status.json` に socket、endpoint、counter、error 状態を書き出す |

## hidloom-uidd / hidloom-outputd

`hidloom-uidd` は Pi local console 用 uinput device owner です。`logicd-core-rs` には Linux uinput ioctl や HID usage -> Linux keycode 差分変換を持たせず、USB endpoint owner の `hidloom-hidd` と同格の出力 daemon として分離します。`hidloom-outputd` は native output router として、core 由来 broker frame を target に応じて `hidloom-hidd`、`hidloom-uidd`、または `btd` へ配送します。

| 領域 | 責務 |
| --- | --- |
| `hidloom-uidd` device owner | `/dev/uinput` を open し、virtual keyboard を作成する |
| `hidloom-uidd` report conversion | keyboard HID report の modifier / 6-key slots 差分を EV_KEY press/release と EV_SYN へ変換する |
| `hidloom-outputd` router | `usb` / `uinput` / `bt` / `auto` の target 状態を保持し、core 由来 broker frame を `hidloom-hidd`、`hidloom-uidd`、または `btd` へ配送する |
| switch safety | target 変更時に旧 target / 新 target へ release-all 相当を送り、stuck key を避ける |
| status | router target、uidd device open、counter、last error を HTTP / OLED から読める形にする |

## logicd / logicd-companion

`daemon/logicd/logicd.py` は現在 `logicd-companion.service` から起動され、control plane の起動オーケストレーションを担当します。config 読み込み、socket server 起動、signal handler、task 起動、終了処理を束ねます。

分割済みの主な責務:

| ファイル | 責務 |
| --- | --- |
| `daemon/logicd/config_runtime.py` | HID device 初期化、Layer / Encoder / Joystick / Macro の runtime 再構築 |
| `daemon/logicd/connections.py` | peer Unix socket への再接続 loop |
| `daemon/logicd/runtime_notifications.py` | `ledd` / `i2cd` / `key_events` への通知 fan-out |
| `daemon/logicd/matrix_pipeline.py` | legacy/Python-owner 時の `matrix_events.sock` 受信と matrix event queue 処理 |
| `daemon/logicd/logicd.py` `_handle_matrix_tap_client` | native-owner 時の `/tmp/matrix_tap_events.sock` 受信。HID hot path には戻さず、`observed_pressed_matrix` と LED などの観測系へだけ使う |
| `daemon/logicd/state.py` `observed_pressed_matrix` | native-owner 時の HTTP / Vial Matrix Tester 用 pressed state。delegated Python pipeline の `pressed_matrix` と分け、advanced action の duplicate 判定へ混ぜない |
| `daemon/logicd/key_event_pipeline.py` | `key_events.sock` 受信と HID/uinput 出力 queue 処理 |
| `daemon/logicd/input_events.py` | matrix / encoder / joystick event dispatch |
| `daemon/logicd/key_lock.py` | Key Toggle / Key Lock / Drag Lock の transient synthetic lock state と validation helper |
| `daemon/logicd/mod_morph.py` | Mod-Morph / Grave Escape の rule 正規化、安全な action validation、held modifier 解決 helper |
| `daemon/logicd/repeat_key_status.py` | Repeat Key の privacy-safe status と alternate pair metadata helper |
| `daemon/logicd/ctrl.py` | ctrl JSON Lines protocol の入口 |
| `daemon/logicd/ctrl_keymap.py` | keymap / matrix / layer ctrl command |
| `daemon/logicd/ctrl_led.py` | LED / VialRGB ctrl command |
| `daemon/logicd/ctrl_runtime.py` | SPID / Bluetooth / output target ctrl command |
| `daemon/logicd/ctrl_common.py` | ctrl 入力検証と共通 helper |
| `daemon/logicd/lighting.py` | VialRGB state、Lighting key action、LED state 永続化 |
| `daemon/logicd/bt_manager.py` | Bluetooth pairing / discoverable / pairable 制御の facade |
| `daemon/logicd/bt_passkey.py` | pairing code 入力待機と数字キー report 生成 |
| `daemon/logicd/btd_sender.py` | BLE HID keyboard report を `/tmp/btd_events.sock` へ送信 |
| `daemon/logicd/sockets.py` | Unix socket client handler 群 |
| `daemon/logicd/output.py` | key event output queue の処理入口 |
| `daemon/logicd/output_switch.py` | USB HID / BLE HID / uinput の動的切り替え |
| `daemon/logicd/uinput.py` | uinput keyboard / Consumer Control fallback |
| `daemon/logicd/notifications.py` | JSON broadcast payload helper |
| `daemon/logicd/protocol.py` | 4-byte packet encode/decode |
| `daemon/logicd/state.py` | `LogicdRuntime` mutable runtime state |
| `daemon/logicd/keymap_store.py` | runtime keymap 保存 / 初期化 |
| `daemon/logicd/text_send_safety.py` | Unicode / Send String action の read-only safety classification |

現時点で `daemon/logicd/logicd.py` に残すもの:

- daemon 起動順序が分かる配線
- SIGHUP / SIGTERM の処理
- 既存テストと内部 callback のための薄い adapter

さらに分ける場合は、`LogicdRuntime` を method 化するか、daemon 起動時の callback 配線を小さくするのが候補です。

## httpd

`daemon/http/httpd.py` は Web server の app assembly、route wiring、薄い adapter を担当します。systemd では `daemon/http/httpd.py` を直接起動するため、repo root を `sys.path` に追加して、`vil_layout.py` など repo root の共通 module を参照できるようにしています。

低頻度・複雑処理は `httpd.py` に戻さず、意味単位の module へ置きます。

分割済みの主な責務:

| ファイル | 責務 |
| --- | --- |
| `daemon/http/layout_api.py` | `/api/layout` payload 組み立て、runtime layer 取得 |
| `daemon/http/layout_controls.py` | `_layout_def` から joystick / encoder / click metadata を生成 |
| `daemon/http/keymap_api.py` | keymap active / remap / layer add-clear の HTTP handler 本体 |
| `daemon/http/lighting_api.py` | Lighting / matrix tester HTTP handler 本体 |
| `daemon/http/lighting_role_preview_api.py` | `POST /api/lighting/role-preview` の一時実LED preview / restore route と route registration |
| `daemon/http/oled_api.py` | OLED customization schema適用、runtime file保存/reset、i2cd reload通知 |
| `daemon/http/settings_api.py` | Settings API の HTTP Basic auth 更新 handler 本体 |
| `daemon/http/scripts_api.py` | Script editor API の request validation、audit logging、HTTP response 組み立て |
| `daemon/http/script_store.py` | `KC_SHn.sh` の探索、label、runtime script 書き込み・削除、path 設定 helper |
| `daemon/http/script_runner.py` | script subprocess 実行、check-run 一時 script 作成、timeout、実行環境、stdout / stderr trim |
| `daemon/http/security_api.py` | 互換 facade。既存 import を保つため `auth_tls.py` / `security_middleware.py` を再エクスポートする |
| `daemon/http/auth_tls.py` | HTTP Basic auth、password hash / verify、auth override file、TLS cert/key path、SSL context |
| `daemon/http/security_middleware.py` | private-network allowlist、CSRF token / cookie、audit log helper |
| `daemon/http/socket_bridge.py` | Unix socket bridge、logicd query、WebSocket message handling |
| `daemon/http/status_api.py` | status / logs / Bluetooth pairing HTTP handler 本体 |
| `daemon/http/vil_api.py` | `.vil` import/export の HTTP handler 本体 |
| `daemon/http/vil_apply.py` | `.vil` import 時の remap / interaction settings / macro buffer 適用 helper |
| `daemon/http/vil_macro_import.py` | `.vil` import 時の Vial macro buffer decode / config update / VIAL macro expansion |
| `daemon/http/vil_response.py` | `.vil` export response の安全な filename / Content-Disposition helper |
| `daemon/http/system_api.py` | output / Bluetooth / btd runtime / systemd environment status |
| `daemon/http/text_send_safety_api.py` | Unicode / Send String safety policy の read-only HTTP route |
| `daemon/http/touch_panel_flick_api.py` | 4.3 inch touch-panel flick preview metadata の read-only HTTP route |
| `daemon/http/system_process.py` | process / HID gadget / Unix socket status |
| `daemon/http/system_peripherals.py` | spid / ledd direct-frame status |
| `daemon/http/system_logs.py` | journald log response |
| `daemon/http/bluetooth_api.py` | Bluetooth pairing API の状態取得と on/off 制御 |
| `daemon/http/keymap_actions.py` | keymap action 入力検証 |
| `daemon/http/lighting.py` | HTTP Lighting API の入力検証と metadata |
| `daemon/http/matrix_state.py` | matrix tester 用 pressed state 正規化 |

### HTTP data retention notes

`.vil` import では、`settings.vial_macro_buffer` と展開済み `macros` を両方保持します。

- `settings.vial_macro_buffer` は `.vil` round-trip / Vial 互換のための raw buffer として保持します。
- `macros` は project runtime / script 表示で使いやすい展開済み表現として保持します。
- import 時は `VIAL*` macro を buffer 由来で置換し、non-VIAL macro は保持します。
- raw buffer を保持しない構成は、Vial 互換や export 再現性に影響する可能性があるため、現時点では採用しません。

HTTP script editor の runtime script は `/mnt/p3/script` を優先するユーザー編集データとして扱います。

- fallback script は `config/default/script` に置きます。
- runtime script は `script_store.py` が書き込み、現状は実行権限 `0755` を付与します。
- 保存サイズ上限、危険 script の保存可否、権限を `0755` のままにするかは後続検討対象です。
- 危険操作の検出・表示は script safety metadata 側で扱います。

フロントエンド JS:

| ファイル | 責務 |
| --- | --- |
| `daemon/http/static/keyboard.js` | layout 描画、virtual key 操作、4.3 inch flick preview、初期化 |
| `daemon/http/static/remap_panel.js` | keymap remap UI、popup 描画 |
| `daemon/http/static/remap_key_groups.js` | keymap remap popup の PC104 / category 定義 |
| `daemon/http/static/remap_kle.js` | keyboard-layout-editor.com preview |
| `daemon/http/static/remap_vil.js` | `.vil` import/export |
| `daemon/http/static/key_passthrough.js` | ブラウザ物理キー入力の転送 |
| `daemon/http/static/matrix_tester.js` | 内部 matrix tester |
| `daemon/http/static/lighting_panel.js` | Lighting / VialRGB UI |
| `daemon/http/static/lighting_role_preview_controls.js` | Lighting tab の `Preview roles` / `Restore effect` UI helper |
| `daemon/http/static/status_panel.js` | daemon status / log panel |
| `daemon/http/static/scripts_panel.js` | script viewer |
| `daemon/http/static/tabs.js` | tab 切り替え |
| `daemon/http/static/layer_controls.js` | layer selector 周辺 |
| `daemon/http/static/script_editor.js` | script editor 入口 |
| `daemon/http/static/extra_key_groups.js` | 追加キー候補 |

## btd

`daemon/btd/btd.py` は BLE HID keyboard daemon の入口です。BlueZ D-Bus へ HID over GATT service と advertisement を登録し、`logicd` から受け取った 8 byte keyboard report を notify します。

| ファイル | 責務 |
| --- | --- |
| `daemon/btd/btd.py` | daemon 起動、backend 選択、socket server、終了処理 |
| `daemon/btd/bluez_backend.py` | BlueZ backend の統合入口 |
| `daemon/btd/gatt_hid.py` | HID Service、Report Map、Input/Output Report、HID Information、Protocol Mode |
| `daemon/btd/gatt_app.py` | D-Bus GATT application / service / characteristic / descriptor 基底 |
| `daemon/btd/gatt_adapter.py` | `org.bluez.GattManager1.RegisterApplication` 呼び出し |
| `daemon/btd/advertising.py` | BLE advertisement 登録 |
| `daemon/btd/pairing.py` | pairing agent、trusted device、pairable/discoverable 制御 |
| `daemon/btd/protocol.py` | `/tmp/btd_events.sock` の report framing |

## i2cd

`daemon/i2cd/i2cd.py` は OLED 表示 daemon の入口です。表示・alert・analog stick polling を扱います。

| ファイル | 責務 |
| --- | --- |
| `daemon/i2cd/i2cd.py` | OLED 初期化、Ready / Boot / alert 描画、i2c_events socket、analog stick task 起動 |
| `daemon/i2cd/icons.py` | OLED 8x8 1bit icon 定義と pixel draw helper |
| `daemon/i2cd/oled_customization.py` | package既定値と`/mnt/p3` overrideのschema、validation、cache、atomic persistence |
| `daemon/i2cd/connectivity.py` | OLED connectivity icon row 用の read-only status snapshot helper。Wi-Fi power control は行わない |
| `daemon/i2cd/ads1115.py` | ADS1115 analog stick polling helper |

`daemon/i2cd/connectivity.py` は現状、表示のために `rfkill` / `nmcli` を read-only に読みます。runtime power control は `daemon/logicd/wifi_manager.py` 側に残します。将来は logicd または status provider がまとめた runtime snapshot を i2cd へ通知する構成に一本化する候補があります。

## ledd

`daemon/ledd/ledd.py` は daemon 起動と animation manager の入口です。

| ファイル | 責務 |
| --- | --- |
| `daemon/ledd/strip.py` | `rpi_ws281x` / stub の抽象化、strip 初期化、全消灯 |
| `daemon/ledd/logicd_client.py` | `logicd` からの JSON message 処理と reconnect loop |
| `daemon/ledd/direct_frame.py` | `LDF1` direct-frame packet encode / decode |
| `daemon/ledd/direct_frame_socket.py` | `ledd` direct-frame socket receiver と counters |
| `daemon/ledd/vialrgb_runtime.py` | VialRGB state 適用、direct frame、render thread 管理 |
| `daemon/ledd/vialrgb_renderers.py` | VialRGB effect render loop 群 |
| `daemon/ledd/vialrgb_hue_renderers.py` | VialRGB hue-focused effect render loop 群 |
| `daemon/ledd/vialrgb_position_renderers.py` | VialRGB position-based effect render loop 群 |
| `daemon/ledd/vialrgb_rain_renderers.py` | VialRGB rain / pixel-noise effect render loop 群 |
| `daemon/ledd/vialrgb_reactive_renderers.py` | VialRGB reactive effect render loop 群 |
| `daemon/ledd/vialrgb_splash_renderers.py` | VialRGB splash effect render loop 群 |
| `daemon/ledd/shutdown.py` | shutdown 時の LED 処理 |

## viald

`daemon/viald/protocol.py` は Vial / VIA command dispatch の入口です。

| ファイル | 責務 |
| --- | --- |
| `daemon/viald/protocol_defs.py` | command ID、default path、report size などの定義 |
| `daemon/viald/keymap_protocol.py` | keymap / encoder get-set、buffer 操作 |
| `daemon/viald/lighting_protocol.py` | VialRGB mode / direct frame / LED info |
| `daemon/viald/unlock_protocol.py` | Vial unlock status / start / poll |
| `daemon/viald/keycode_codec.py` | QMK/Vial keycode と local action の変換 |
| `daemon/viald/viald.py` | Raw HID socket daemon 入口 |

## 検証

分割後の基本確認:

```bash
python3 -m py_compile http/*.py daemon/ledd/*.py daemon/logicd/*.py script/*.py daemon/viald/*.py daemon/btd/*.py daemon/spid/*.py vialrgb_effects.py
node --check daemon/http/static/keyboard.js
node --check daemon/http/static/remap_key_groups.js
node --check daemon/http/static/remap_panel.js
node --check daemon/http/static/remap_kle.js
node --check daemon/http/static/remap_vil.js
node --check daemon/http/static/matrix_tester.js
python3 script/test_validation_suite.py
python3 script/test_development_suite.py
```

実機では `node` が入っていない環境があるため、JS 構文チェックは開発環境側で実行します。実機反映後は `systemctl is-active hidloom-logicd-core logicd-companion hidloom-hidd httpd ledd viald matrixd i2cd btd --no-pager`、`systemctl is-active usbd || true`、`curl -k -u admin:$(hostname) https://127.0.0.1/api/status`、`/api/layout` を確認します。
