# Implementation Risk Notes From Past Work

過去の bug record、review、progress log から、機能追加や移植時にこぼしやすい条件を起こしたものです。

この文書は横断の注意点索引です。daemon 固有の再発防止条件は各 daemon の `behavior-contract.md` / `compatibility-checklist.md` / `test-matrix.md` へも反映します。

## 1. Runtime keymap は repo default より優先される

出典: private workspace reference *(omitted from public export)*

- `/mnt/p3/keymap.json` が存在すると `conf/keymap.json` より優先される。
- board profile や default keymap を変更しただけでは、実機 runtime keymap が残っている環境の表示や挙動は変わらない。
- default 配列の確認では、runtime keymap の有無、marker source、HTTP `/api/status` の board_version を同時に見る。
- runtime keymap を退避する場合は backup を作り、daemon restart 後の layout / keymap / Vial 表示を確認する。

反映先:

- `viald`: keymap import / export、Vial 表示互換。
- `httpd`: `/api/layout`、board profile 表示。
- `logicd`: runtime keymap reload、JSON 互換。

## 2. Mouse motion report は押下中 button bit を保持する

出典: private workspace reference *(omitted from public export)*

- matrix 経路で `KC_BTN1` press を保持していても、stick / spid motion が `buttons=0` の Mouse HID report を送ると host では release に見える。
- mouse motion report を生成する経路は、現在押下中の mouse button bit を merge する。
- HTTP virtual keyboard は pointer が key 領域外へ出ただけで mouse button を release しない。`pointerup` / `pointercancel` / `mouseup` / `touchend` まで保持する。

反映先:

- `logicd`: mouse button state と motion merge。
- `spid`: motion event と button state の境界。
- `httpd`: virtual keyboard pointer lifecycle。
- `hidd` / `usbd`: Mouse HID report の button bit 互換。

## 3. Raw matrix intake に重い処理を戻さない

出典: private workspace reference *(omitted from public export)*, private workspace reference *(omitted from public export)*

- `/tmp/matrix_events.sock` の intake は 4 byte packet parse、range check、queue put に留める。
- HID 生成、LED 通知、BT / Wi-Fi / macro、file I/O、subprocess、status lookup は raw intake に置かない。
- 重い可能性がある処理は resolved action 境界に置く。
- `process_matrix_event()` は pressed state、LED key event 通知、InteractionEngine dispatch までに留める。
- input path の優先度は `matrixd >= logicd matrix input path > usbd/btd output path > ledd/httpd/UI` を目安にする。

反映先:

- `logicd`: input pipeline、resolved action handler split。
- `matrixd`: scan loop と event delivery。

## 4. Debounce state は event delivery と分けて考える

出典: private workspace reference *(omitted from public export)*

- raw state が debounce threshold 未満で揺れている間は stable event にしない。
- `sock_send_event()` 成功後にだけ debounce state を commit する方針を維持する。
- scan 高速化では `MIN_INTERVAL_US` のような busy loop guard と、`post_row_settle_us` のような hardware settle を両方見る。
- RT priority や LED 負荷の調整は、matrixd 単体の CPU だけでなく key event count / ledd key message / daemon log を合わせて見る。

反映先:

- `matrixd`: debounce contract、test matrix。

## 5. LED high-brightness 負荷は ghost input の再発条件になり得る

出典: private workspace reference *(omitted from public export)*

- multi splash 高輝度付近で、物理 idle 中に key event burst が観測された経緯がある。
- splash 系 mode は brightness guard の意図を維持し、見た目だけで解除しない。
- LED effect や brightness を変更した時は、入力 path の stability smoke も対象にする。

反映先:

- `ledd`: effect / brightness guard。
- `matrixd`: idle ghost input smoke。
- `logicd`: input path warning / event count。

## 6. Bluetooth active host は paired list だけで判断しない

出典: private workspace reference *(omitted from public export)*

- BlueZ paired device existence や reconnect event だけで active host と判断すると、実際には HID report を送れない host を connected と誤表示する可能性がある。
- `last_connected_at` は履歴、active host は現在状態として分ける。
- source は `hid_notify_ready` / `report_delivered` / `unknown` のように明示する。
- btd restart、unpair、forget 後は active host を `unknown` に戻す。

反映先:

- `btd`: host metadata。
- `logicd`: host profile 適用。
- `httpd`: status 表示。

## 7. Host profile は unknown host へ自動適用しない

出典: private workspace reference *(omitted from public export)*

- automatic OS detection に寄せると、USB / Bluetooth で同じ host の挙動がずれる。
- active host が unknown の時は safe default に戻し、modifier swap や layout transform を適用しない。
- JIS/US symbol correction、keymap hot swap、text send path を混ぜない。

反映先:

- `logicd`: host profile / text send / keymap transform。
- `btd`: active host source。
- `httpd`: warning 表示。

## 8. Descriptor 変更は default で行わない

出典: private workspace reference *(omitted from public export)*, private workspace reference *(omitted from public export)*, [Windows IME real-device runbook](../../ops/windows-ime-custom-hid-real-device-runbook.md)

- USB HID descriptor や BLE report map の変更は host 再認識、再 pairing、Vial Raw HID へ影響する。
- 追加 HID interface / custom HID は opt-in とし、既存 keyboard / mouse / consumer / Vial Raw HID を default で変えない。
- Windows IME helperless route は host layout / device identity 依存が強い。標準 keyboard HID、Raw HID 診断、helper route を混ぜて成功扱いにしない。
- `/dev/hidg1` Raw HID / Vial の report length を変えない。

反映先:

- `hidd` / `usbd` / `uidd`: descriptor / report contract。
- `viald`: Raw HID 互換。
- `logicd`: Windows IME route。

## 9. Legacy USB broker flag は現行 owner と混ぜない

出典: private workspace reference *(omitted from public export)*

- historical `LOGICD_USBD_HID_REPORT_BROKER` は native `logicd-core-rs -> hidloom-hidd` active owner path に superseded。
- rollback / A/B 診断以外で legacy flag を再有効化しない。
- 有効化する場合は target host、baseline readiness、unit/drop-in、restart order、rollback command、expected readiness を先に記録する。
- Python path と native path で同じ report を二重送出しない。

反映先:

- `hidd`, `logicd-core-rs`, `usbd`, `logicd`。

## 10. Native output target は hidloom-outputd が owner

出典: [Native Output Routing And uidd Design](../../architecture/native-output-routing-uidd-design.md), private workspace reference *(omitted from public export)*

- 現行 hot path は `matrixd -> logicd-core-rs -> hidloom-outputd -> hidloom-hidd`。
- `KC_CONSOLE` / `KC_USB` / `KC_BT` / `KC_CONNAUTO` は companion 内の旧 Python `OutputRouter` だけを切り替える状態へ戻してはいけない。
- target 切替時は旧 target と新 target の両方へ release-all / null report を送り、stuck key を避ける。
- `auto` は USB ready なら `usb`、そうでなければ `uinput`。BT fallback は暗黙に含めない。
- `bt` target は broker frame を `btd1` frame へ変換する。local regression 済みでも、実機 BLE host smoke は別に記録する。

反映先:

- `outputd`, `logicd-core-rs`, `logicd`, `hidd`, `uidd`, `btd`。

## 11. Boot helper service は hot path を待たせない

出典: private workspace reference *(omitted from public export)*, `script/test_power_shed_boot.py`

- USB gadget / hidd / outputd / logicd-core-rs / matrixd を早期 hot path とし、network / Bluetooth / HTTP / Vial は late service 側へ逃がす。
- `logicd-companion` は matrix socket owner ではなく delegation / control plane として扱う。
- `late-services` は `viald` / `httpd` / optional Bluetooth を `--no-block` で起動し、boot-critical key input を待たせない。
- touch panel profile は `logicd` / `httpd` / `viald` より前に runtime keymap / layout を決める。
- `power-shed` は boot peak 緩和であり、input daemon の依存先にしない。

反映先:

- `service-helpers`, `logicd-core-rs`, `matrixd`, `httpd`, `viald`。

## 12. httpd shutdown は長く待たない

出典: private workspace reference *(omitted from public export)*

- HTTP UI / WebSocket の通信中接続は、service stop 時に終了優先で閉じる。
- WebSocket close timeout、aiohttp shutdown timeout、systemd `TimeoutStopSec` の意図を維持する。
- shutdown path で daemon restart が timeout / failed になる変更を入れない。

反映先:

- `httpd`: WebSocket lifecycle、shutdown test。

## 13. status polling は cache と degraded response を維持する

出典: private workspace reference *(omitted from public export)*

- `/api/status` は systemd env、Bluetooth、btd runtime などに cache を持ち、毎 request で重い問い合わせを連打しない。
- Bluetooth device detail は paired host 数に比例して重くなり得るため、host 数が増えたら TTL / 上限 / detail 範囲を見直す。
- daemon 未起動時は UI 全体を落とさず、該当機能だけ degraded response にする。

反映先:

- `httpd`: status API。
- `btd`: status source。
- `i2cd` / `spid`: polling / broadcast。

## 14. 実機 checkout と build artifact を混同しない

出典: private workspace reference *(omitted from public export)*, [real device experiment workflow](../../ops/real-device-experiment-workflow.md)

- 実機上の一時修正は観測手段であり、そのまま repository へ丸ごと移植しない。
- `daemon/matrixd/matrixd` は ARM aarch64 実機 binary を保持する。x86_64 local build artifact で上書きしない。
- 実機 checkout は clean state に戻し、正式変更は repository で実装、test、commit、push する。

反映先:

- `matrixd`: binary / build artifact。
- ops runbook。
