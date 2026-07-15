# System Overview Diagram

システム全体像を、人間がさっと確認できる一枚図としてまとめた資料です。

![HIDloom system overview](system-overview.svg)

## 読み方

- 中央の hot path は `matrixd -> logicd-core-rs -> hidloom-outputd -> hidloom-hidd` です。物理キーの基本入力、modifier、US sub keyboard route、HID release safety は native core が持ち、`hidloom-outputd` が出力 target を選びます。USB target では `hidloom-hidd` が `/tmp/usbd_hid_reports.sock` と `/dev/hidg0` / `/dev/hidg1` / `/dev/hidg2` の owner です。
- `logicd-companion` は HTTP / Vial / macro / text send / sessiond / advanced interaction / status merge などの control plane です。companion は `LOGICD_OUTPUTS=debug` で起動し、通常の keyboard report を broker へ直接 fan-out しません。
- `KC_SH7` PTY mirror 中だけ、`logicd-companion` は `logicd-core-rs` control socket の `set_matrix_delegate_all` で全 matrix P/R を delegate socket へ切り替えます。この間の物理キーは `matrixd -> logicd-core-rs -> logicd-companion -> sessiond PTY` へ入り、PTY 応答は `logicd-companion -> logicd-core-rs key_event source=pty_terminal_mirror -> hidloom-outputd usb -> hidloom-hidd -> hidg2` で host text editor へ戻ります。
- `KC_CONSOLE` / `KC_USB` / `KC_BT` / `KC_CONNAUTO` の native owner 復旧は実装済みです。`logicd-companion` は output switch action を `hidloom-outputd` の control socket へ送り、`usb` / `uinput` / `bt` / `auto` target を切り替えます。`logicd-core-rs` には uinput ioctl や Bluetooth transport を入れず、`uinput` target では `hidloom-outputd -> hidloom-uidd -> /dev/uinput`、`bt` target では `hidloom-outputd -> btd -> BLE HID host` へ配送します。
- `logicd-core-rs` は HID 本線で受理した通常 matrix P/R を、best-effort の `/tmp/matrix_tap_events.sock` へ複製します。companion はこの tap を HTTP / Vial Matrix Tester 用の観測 pressed state と LED reactive trigger にだけ使います。delegate / PTY mirror で companion 本線へ渡した event は二重 tap しません。
- 左側は入力源です。物理キーは `matrixd` から core へ入り、`httpd` の HTTP UI/API/WebSocket、analog stick、CLI/helper、KC_SH/sessiond などの低頻度 control-plane action は companion / control socket 側へ入ります。
- マクロ系の実装済み経路は、`KC_SHn` の shell script 実行、Vial Macro `M0`-`M7` から `MACRO:VIALn` への変換、local `MACRO:name` です。KML と QMK macro compatible runner は、`KC_KMLn` / `KC_QMn` の実装前設計TODOとして [macro/compatibility-plan.md](../macro/compatibility-plan.md) で扱います。
- 右上は PC との USB HID 経路です。`hidloom-outputd` の `usb` / `auto` target から `hidloom-hidd` に broker frame が入り、`hidg0` が Keyboard / Mouse / Consumer Control の multi-report、`hidg1` が Raw HID/Vial、`hidg2` が US sub keyboard です。`bt` target では同じ core 由来 frame を `btd1` protocol へ変換して `btd` へ送ります。
- `viald_events.sock` は `hidloom-hidd` と `viald` の間の Raw HID bridge です。Vial GUI からの 32 byte packet は `hidloom-hidd` から `viald` へ入り、応答も同じ経路で PC へ戻ります。
- `httpd` は仮想キー入力、キーマップ変更・`.vil` import・Lighting 操作・Interaction editor 保存などを control plane 経由で companion / core へ渡します。Interaction inspector と summary は `settings.interaction` の validation 結果、Caps Word / Repeat Key / Conditional Layers の設定、`/api/keymap/active` の `active.conditional` / `active.oneshot` / `active.locked` を read-only に表示します。
- `viald` は Vial protocol を処理し、keymap SET や VialRGB 操作を control plane 経由で companion / core へ渡します。Vial Matrix Test は `ctrl_events.sock` の `K` response を読み、native owner 時は tap-observed state も含みます。
- `ledd` と `i2cd` は companion/core からの状態通知を受けて LED / OLED を描画します。`i2cd` は Wi-Fi / service status と CPU/温度などの軽量 system status を描画経路の外で採取し、OLED 更新時はキャッシュを表示します。
- `btd` は companion 側の Bluetooth control plane と連携し、BlueZ D-Bus 経由で BLE HID over GATT keyboard report を host へ送ります。
- `BT_*` action は native core では delegate 対象です。pairing / disconnect / status は companion の Bluetooth control layer へ渡します。
- 下部の設定・永続化領域は、初期設定 `config/default/*`、runtime profile `config/profiles/*`、runtime 保存 `/mnt/p3/*` の関係を示しています。Interaction 設定は `config/default/config.json` の `settings.interaction` に入り、HTTP UI から保存した後に `logicd` reload で反映されます。

## 関連資料

- [specification.md](specification.md)
- [../daemon/specs/viald/architecture.md](../daemon/specs/viald/architecture.md)
- [../keycode/qmk-vial-keycode-support.md](../keycode/qmk-vial-keycode-support.md)
- [module-structure.md](module-structure.md)
- [native-output-routing-uidd-design.md](native-output-routing-uidd-design.md)
- [../macro/compatibility-plan.md](../macro/compatibility-plan.md)
