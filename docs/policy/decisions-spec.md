# Decision Specification

更新日: 2026-05-24

このファイルは、実装中に決めた仕様・運用方針を集約する場所です。
詳細な daemon / IPC / API 仕様は [specification.md](../architecture/specification.md) を参照し、
ここでは「なぜこの挙動にするか」「どの状態を正とするか」を残します。

## 使い分け

| ファイル | 役割 |
|---|---|
| [decisions-spec.md](decisions-spec.md) | 決定済みの仕様・運用方針 |
| [specification.md](../architecture/specification.md) | 現在実装されている全体仕様 |

## 2026-05-22 Bluetooth / Output 決定事項

### Pairing と advertising

- BLE HID advertisement は常時出さず、pairing / reconnect を受け入れる必要がある間だけ出す。
- 既定は `BTD_ADVERTISING_MODE=pairing` とする。
- 常時公開が必要な調査時だけ `BTD_ADVERTISING_MODE=always` を明示する。
- 完全に advertisement を止めたい確認では `BTD_ADVERTISING_MODE=off` を使う。
- `BT_PAIRING_ON` は既定で `Pairable=yes` と BLE HID advertisement を有効にする。
- iPhone で同じ keyboard が二重表示されるのを避けるため、adapter `Discoverable` は既定で有効にしない。
- Pi 側に paired device が無い新規 pairing 状態でも、既定では `Discoverable=no` のままにする。検出入口を BLE HID advertisement に一本化し、iPhone 側の二重表示を避けるため。
- discoverable 併用が必要な診断時だけ、`BT_PAIRING_DISCOVERABLE=1` / `BTD_PAIRING_DISCOVERABLE=1` の opt-in とする。

### Pairing off / output 切替時の切断

- BT output を使わない状態へ切り替える時は、iPhone 側のソフトウェアキーボード復帰を優先する。
- `bt` が output target から外れる時は、まず null keyboard report を btd へ送り、その後 connected host を切断する。
- Pairing off は新規 pairing / advertisement を止める操作であり、成立済み接続の扱いは output target の切替方針に従う。

### KC_BT と output target

- `KC_BT` は Bluetooth pairing / power 操作ではなく、OutputRouter の `bt` backend selector とする。
- `BT_*` は Bluetooth control action として扱い、`KC_BT` とは役割を分ける。
- ただし `KC_BT` / `OUTPUT bt` は、BT output に切り替える前提条件として Bluetooth controller が off なら内部で power on してから本来の output target 切替へ進む。
- F10 位置のデフォルト keycode は `KC_BT` とする。
- HTTP のキーコード変更 popup では、`KC_BT` を `System > Bluetooth` の output selector として選べるようにする。
- `System > Output > Output` のような重複表示は避け、表示名は `Bluetooth` / `BT` を使う。

### Pairing / reconnect 後の output

- ペアリングまたは手動接続で BT host と接続できた場合、明示的に `KC_BT` で BT reconnect を開始していた時は output target を `bt` にする。
- output target が `auto` の時に iPhone から接続要求を受けた場合、USB が利用可能なら USB を優先する。
- `auto` で USB が未接続なら BT fallback を許可する。
- BT fallback は既定 off とし、実機常用では `LOGICD_AUTO_BT_FALLBACK=1` を設定した時だけ有効にする。

### Reconnect 復旧

- BlueZ 上で device が `Connected=yes` だが、btd の `host_connected=false` / `StartNotify` なしの状態は stuck reconnect とみなす。
- stuck reconnect 検出時は null report reset 後に GATT application / advertisement を再登録し、host 側の notification 再購読を促す。
- 常用設定では `BTD_STUCK_RECONNECT_POLLS=3` / `BTD_STUCK_RECONNECT_COOLDOWN=30` を使う。
- iPhone OS 再起動後に `KC_BT` で BT output target へ戻した時も、同じ stuck reconnect 復旧経路で `StartNotify` / `host_connected=true` へ戻ることを期待する。

### BLE mouse

- BT output は keyboard report だけでなく mouse report も扱う。
- `logicd -> btd` は keyboard / mouse を区別できる framed protocol を使う。
- BLE mouse は小さい移動をそのまま高頻度送信し続けるのではなく、coalescing で送信数を抑える。
- 大きい移動は短い間隔、小さい移動は少し長い間隔でまとめる。
- 動き終わりのカクつきを避けるため、一定時間は fast mode を維持する。
- 常用値は BLE notify queue の詰まりを避けつつカーソル追従を優先し、`BTD_MOUSE_COALESCE_INTERVAL=0.020` / `BTD_MOUSE_SMALL_COALESCE_INTERVAL=0.040` / `BTD_MOUSE_FAST_HOLD=0.12` を基準にする。
- 再接続直後は host 側の GATT notify 開始を待つため、`BTD_RECONNECT_NOTIFY_GRACE=2.0` の間は stuck reconnect recovery による GATT 再登録を急がない。

### BLE keyboard repeat

- BLE host が保持中 keyboard report だけでキーリピートしない場合に備え、btd 側で通常キーの非 null report を synthetic release / press として一定間隔で再通知する。
- 補助リピートは BT output の BlueZ backend 内だけで扱い、USB gadget / uinput には影響させない。
- release / null report / stuck reconnect recovery / btd stop で補助リピートを停止する。
- BLE notify queue への負荷を抑えるため、常用の repeat interval は `BTD_KEYBOARD_REPEAT_INTERVAL=0.090` を基準にする。

## 2026-05-22 Status / OLED / HTTP UI 決定事項

### Output status 表示

- `auto` は選択中 target、`gadget` / `bt` / `uinput` は実際の runtime output として扱いを分ける。
- 起動時の keyboard output target は `auto` を標準とする。USB接続中は実出力が `gadget` になるが、選択中 target は `auto` のまま扱う。
- HTTP `/api/status` は少なくとも次を返す。
  - `mode`: 実際の output mode
  - `output_target`: 選択中の output target
  - `output.runtime_mode`
  - `output.output_target`
- HTTP status panel は `output_target === "auto"` の時だけ `AUTO gadget` / `AUTO bt` / `AUTO uinput` のように表示する。
- OLED では auto の時、`AUTO` を反転表示し、その後ろに実際の output を表示する。初心者向け表示として、内部名 `gadget` は `USB`、`uinput` は `Pi` に変換する。

### Output status 色

- `bt` の状態マークは青系にする。
- `auto` は緑系にする。
- `uinput` は「接続したい他系統がエラーになった可能性がある」状態として黄色系にする。
- `usb` / `gadget` は通常の有線系統として扱う。

### BT pairing LED / OLED state

- iPhone は自動認証で入力の必要がないため、数字入力モードに入ったまま残らないようにする。
- pairing / passkey 表示は一時 alert として扱い、成功・中断・終了時には通常の LED / OLED effect へ戻す。

## 2026-05-22 HTTP Keycode Remap UI 決定事項

### Remap tab とカテゴリ

- キーコード変更 popup は、現在 keycode のカテゴリに合わせて初期タブを開く。
- `KC_BT` は System / Bluetooth 側にも置き、output selector として見つけやすくする。
- `BT_STATUS` / `BT_POWER_*` / `BT_PAIRING_*` / `BT_DISCONNECT` などは BT control として BT タブに置く。
- Layer タブのグループ名には意味を括弧付きで表示する。
  - `Momentary（押している間だけ対象レイヤー）`
  - `Toggle（対象レイヤーをトグル切り替え）`
  - `To（対象レイヤーへ移動）`
  - `Default（既定レイヤーを変更）`
  - `One Shot（次の1キーだけ対象レイヤー）`

### Remap popup の操作性

- タブ切替でフローティングウィンドウの高さやタブ位置が動かないようにする。
- popup は一定サイズを持ち、内容が多いタブは popup 内部でスクロールする。
- タブ列とヘッダは操作中に位置が安定することを優先する。

## Configuration File Placement

- `config/default/` 直下には実行時に必要な設定ファイルを置く。
- KiCad 解析結果、生成物、確認用レポートなどは `config/default/` 直下へ戻さない。
- 解析・生成で使う中間ファイルや出力は `build/generated/` 側へ移す。
- 利用・生成する script は、新しい配置に合わせて参照先を更新する。

## 2026-05-23 HTTP Settings / Basic Auth 決定事項

- HTTP UI に Settings タブを追加し、Basic 認証 password を変更できるようにする。
- `config/default/config.json` は初期値として読み、HTTP UI から直接更新しない。
- `config/default/config.json` の `settings.http_basic_auth.password` は `__HOSTNAME__` を許可し、
  fresh install の初期 password は node 名 (`hostname` の出力) とする。
  これにより、固定の `admin/admin` を既定にしない。
- password 変更値は専用 override ファイルへ保存する。
  - 実機既定: `/mnt/p3/http_basic_auth.json`
  - 開発環境既定: `config/default/http_basic_auth.local.json`
  - `HTTPD_BASIC_AUTH_FILE` で明示指定できる。
- 保存形式は平文 `password` ではなく、salt 付き PBKDF2-SHA256 の `password_hash` とする。
- 専用 override ファイルは `0600` で作成し、ログには password 本体を出さない。

## 2026-05-24 HTTP security 決定事項

- OS firewall だけに寄せず、まず `httpd` middleware で client address を制限する。
  理由は repo 内で policy と regression test を持て、fresh install で ufw/nftables の有無に依存しないため。
- default では loopback、IPv4 private、IPv4 link-local 以外の client を 403 で拒否する。
- IPv6 は通常運用で使わないため default 許可しない。必要な VPN / 管理 network は
  `HTTPD_ALLOWED_NETS` に CIDR で明示する。
- OS firewall は defense in depth として追加可能だが、primary policy は `httpd` 側に置く。
- 動的 HTTP header 値は専用 sanitizer を通す。`.vil` export の
  `Content-Disposition` filename は ASCII 安全文字へ丸める。
- HTTP から外部 command を呼ぶ箇所は `create_subprocess_exec()` に argv を分けて渡し、
  shell command line の文字列連結を避ける。
- POST / PUT / DELETE と `/ws` は CSRF token を要求する。通常 UI は `hidloom_csrf`
  cookie から `X-HIDLOOM-CSRF` header、または WebSocket query を付与する。
- `/api/scripts/{KC_SHn}/check-run` は command injection ではなく、
  認証済みユーザーが editor content を `httpd` 権限で実行する強い機能として扱う。
  editor UI では実行前の再確認を必須にし、強い操作は `AUDIT http` として journal に残す。

## 2026-05-24 Vial / KiCad 生成決定事項

- `build/generators/mkvial.py` は KiCad PCB 座標を正にして KLE を変形するのではなく、
  `config/default/keyboard-layout.json` の KLE slot を正として先に読み、
  KiCad 解析から得た switch point を KLE slot 順へ割り当てる。
- KiCad から判断できない例外は script 内の個別条件ではなく、
  `config/default/vial-layout-overrides.json` に `exclude_sources` / `slot_overrides` /
  `virtual_slots` として明示する。
- encoder pulse は Vial の通常キー slot から除外し、Vial encoder 表示用の `e` slot は
  `virtual_slots` として扱う。
- HTTP の KLE preview は encoder `e` marker を通常キーラベルで潰さず、
  `encoder_actions` metadata から現在レイヤの encoder action 表示を載せる。
- 生成後は `build/generated/vial_generation_report.txt` の未割当欄を確認する。

## Wishlist へ移したもの

- PAW3805EK / SPI mouse sensor 搭載は当面先のため、実装 TODO ではなく wishlist とする。

## 過去から維持する決定事項

### OutputRouter

- Bluetooth は USB gadget / uinput と同列の output backend として扱う。
- `KC_CONNAUTO` は auto target へ戻す action とする。
- `KC_CONSOLE` は `uinput`、`KC_USB` は `gadget`、`KC_BT` は `bt` を明示選択する action とする。
- output backend の失敗は他 backend や logicd 全体を巻き込まない。

### Script keycode

- shell script 実行は `KC_SH0` から `KC_SH10` の custom keycode として扱う。
- Vial Macro / `SCRIPT(...)` とは別物として扱う。
- runtime script directory は `/mnt/p3/script` を優先し、初期テンプレートは `config/default/script` に置く。

### Runtime keymap

- runtime keymap は `/mnt/p3/keymap.json` を優先する。
- 初期 keymap は `config/default/keymap.json` とする。
- HTTP / Vial からの remap は logicd に集約し、runtime keymap と表示状態を同じ source から更新する。

### Documentation

- 決定済みの仕様・運用方針はこのファイルへ追記する。
