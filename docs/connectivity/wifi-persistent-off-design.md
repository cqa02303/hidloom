# Persistent Wi-Fi off design

更新日: 2026-06-04

この文書は、再起動後も Wi-Fi off を維持する上級者向け設定を実装する前の設計メモです。
現行の `Wi-Fi recovery-first power control` は、問題発生後に SSH / HTTP UI へ戻れるように reboot 後は Wi-Fi on に戻す安全方針です。
永続 off は管理経路を失う危険があるため、実装より先に failsafe、保存場所、boot 適用順序、解除方法、警告導線を固定します。

## 結論

- 既定では Wi-Fi off を永続化しない。
- 永続 off は明示設定した時だけ有効にする。
- boot 直後に即 Wi-Fi off へしない。
- 少なくとも logicd / key input / USB gadget 管理経路が立つまでは Wi-Fi off を遅延する。
- `WIFI_POWER_ON` は永続 off 設定を解除する。
- HTTP UI / OLED / docs で、SSH / HTTP UI を失う可能性を明示する。
- USB gadget Ethernet、serial、local console、物理キー操作など、Wi-Fi 以外の復旧経路がある前提でのみ使う。

## 対象外

この設計TODOでは、まだ実装しません。

- config schema の実装
- systemd unit / daemon の実装変更
- HTTP UI switch の実装
- OLED warning の実装
- 永続 off の実機検証

実装は、受け入れ条件が埋まってから別 TODO として扱います。

## 保存場所

採用:

```json
{
  "settings": {
    "wifi": {
      "persistent_off": false
    }
  }
}
```

理由:

- `config/default/config.json` は既に runtime / HTTP UI / daemon 設定の集約先として使われている。
- `settings` 配下なら既存構造と相性がよい。
- 将来 `wifi` 配下へ policy や warning acknowledged などを増やしやすい。

代替案:

- `settings.wifi_persistent_off`
  - 単純だが、Wi-Fi 関連設定が増えると散らかる。
- `/mnt/p3` 側の runtime user setting
  - ユーザー永続設定としては自然だが、fresh install / recovery 時の扱いを別途決める必要がある。

- `settings.wifi.persistent_off` を第一候補にする。
- 実装時に既存 config migration が必要なら、未定義時は `false` として扱う。
- 既定値は必ず `false` とし、fresh install / config 欠落時も recovery-first のままにする。

## boot 適用順序

危険な案:

- boot 直後、network service より先に Wi-Fi off を適用する。

この案は、SSH / HTTP UI に戻る前に管理経路を失うため採用しません。

第一候補:

1. system boot
2. USB gadget / local input / logicd が起動
3. HTTP UI または local key path が使える状態になる
4. `settings.wifi.persistent_off == true` を確認
5. warning / status を出す
6. Wi-Fi off を適用

採用:

- power control の source of truth は `daemon/logicd/wifi_manager.py` 側に置く。
- boot 適用も logicd 経由に寄せる。
- readiness 条件は `logicd` が matrix input socket と ctrl socket を用意し、USB gadget が configured / connected として見えることを最低条件にする。
- 固定秒数だけでは判定しない。readiness を満たした後、短い猶予として 10 秒待ってから Wi-Fi off を適用する。
- HTTP UI の起動完了は必須条件にしない。HTTP UI は Wi-Fi 経由のことが多く、待ち条件にすると persistent off が永遠に適用されない構成があり得る。
- i2cd は表示専用のままにする。

## 解除方法

第一候補:

- `WIFI_POWER_ON`
  - Wi-Fi を on にするだけでなく、`settings.wifi.persistent_off=false` へ戻す。
  - これにより、物理キー操作だけで永続 off から復帰できる。

代替案:

- `WIFI_POWER_ON` は一時 on のみで、永続 off 設定は維持する。
  - 次回 reboot で再び off になるため、省電力運用としては一貫する。
  - ただし復旧時に再び閉じ込められる危険がある。

- 安全優先で、`WIFI_POWER_ON` は永続 off を解除する。
- 一時 on が必要になった場合は、将来 `WIFI_TEMP_ON` のような別 action を検討する。

HTTP UI:

- 永続 off が有効な時は、Wi-Fi row に明確な warning を出す。
- Disable persistent off / Turn Wi-Fi on and disable persistent off のような解除導線を置く。
- 有効化 confirmation 文言:
  - `Reboot後もWi-Fiをoffにします。SSH/HTTP UIに戻れない可能性があります。USB gadget Ethernet、local console、または物理キーの復旧経路を確認してから有効化してください。`
- 解除 button 文言:
  - `Turn Wi-Fi on and disable persistent off`

local console:

- `tools/hidloom_send/.build/hidloom-ctrl '{"t":"WIFI","action":"WIFI_POWER_ON"}'` または同等の helper で解除できるようにする。
- config 直接編集による解除は `config/default/config.json` の `settings.wifi.persistent_off=false` に戻し、`logicd` を restart する手順にする。
- docs に最短復旧手順を載せる。

## 警告導線

HTTP UI:

- 設定を有効化する時に confirmation を要求する。
- warning 文言には以下を含める。
  - SSH / HTTP UI を失う可能性がある。
  - USB gadget Ethernet / local console / physical key の復旧経路が必要。
  - reboot 後も Wi-Fi off になる可能性がある。

OLED:

- 永続 off が有効な時は、Wi-Fi icon 非表示だけではなく、boot 適用前に `WiFi P-Off` alert を出す。
- Ready 画面の常時表示はまず増やさない。表示領域を圧迫し、通常の off / unavailable と混同しやすいため、alert と HTTP status で区別する。

Docs:

- `FRESH_INSTALL.md` または運用 docs に、永続 off の解除手順を書く。
- `TODO_PRIORITY.md` には設計完了条件だけを残す。

## failsafe

必須条件:

- Wi-Fi 以外の復旧経路があること。
- `WIFI_POWER_ON` keycode または local console helper で解除できること。
- config 編集で `persistent_off=false` に戻せること。

後続候補:

- boot 後 N 秒以内に特定キーを押すと persistent off を一時スキップする。
- matrixd / logicd が起動していない時は Wi-Fi off を適用しない。
- 前回 boot で Wi-Fi off 適用後に正常終了していない場合は、次回 boot で persistent off をスキップする。

- 初回実装では「logicd readiness + local input available」を最低条件にする。
- crash / failed boot 検出は複雑なので、実装前に必要性を再評価する。
- 初回実装では、readiness を満たせなければ Wi-Fi off を適用せず、journal と HTTP status に deferred reason を残す。

## Implementation readiness boundary

永続 off は、Wi-Fi を使わない設置運用が具体化し、Wi-Fi 以外の復旧経路を実機で再確認できるまで実装しません。

runtime `WIFI_POWER_OFF` だけで足りる場面:

- 省電力や誤接続回避を一時的に行いたい。
- reboot 後に SSH / HTTP UI へ戻れる recovery-first 方針を維持したい。
- Wi-Fi off 後の復旧確認を自動 recovery timer または `WIFI_POWER_ON` に任せたい。

永続 off が必要になる場面:

- 常設 kiosk / USB gadget Ethernet 運用など、reboot 後も Wi-Fi を使わないことが明確。
- local console、USB keyboard、USB gadget Ethernet、または physical key による復旧経路が常に使える。
- HTTP UI / OLED / docs の warning を読んだ上で、管理経路を失う risk を受け入れられる。

初期実装へ進める場合の smoke 手順:

1. `settings.wifi.persistent_off=false` の fresh / existing config で reboot 後 Wi-Fi が on へ戻ることを確認する。
2. `settings.wifi.persistent_off=true` でも logicd readiness と local recovery route が立つまで Wi-Fi off を遅延することを確認する。
3. local console helper または physical key の `WIFI_POWER_ON` で Wi-Fi が on になり、`settings.wifi.persistent_off=false` へ戻ることを確認する。
4. config 直接編集で `persistent_off=false` に戻し、logicd restart 後に永続 off が再適用されないことを確認する。
5. HTTP warning / OLED `WiFi P-Off` / docs recovery 手順が runtime off (`Wi-Fi OFF\nuntil reboot`) と別物として読めることを確認する。

実装しない間は、現行の recovery-first runtime off を代替方針にします。
runtime off は reboot 後に Wi-Fi on へ戻るため、管理経路を失う危険が小さく、現時点の運用要求には十分です。

## 実装TODOへ進める条件

以下が決まるまで、実装へ進めません。

- [x] config key と既定値
- [x] boot 適用担当 daemon
- [x] boot 適用タイミングまたは readiness 条件
- [x] `WIFI_POWER_ON` の永続 off 解除 semantics
- [x] HTTP UI warning / confirmation 文言
- [x] OLED 表示方針
- [x] local console / config 編集による解除手順
- [x] 実機検証手順

## 実機検証案

実装後に必要な確認:

1. 既定値では reboot 後に Wi-Fi が on へ戻る。
2. 永続 off を有効化しても、USB keyboard / local console / USB gadget Ethernet の復旧経路が使える。
3. boot 後、readiness 条件を満たしてから Wi-Fi off が適用される。
4. `WIFI_POWER_ON` で Wi-Fi が on になり、永続 off 設定も解除される。
5. HTTP UI から解除できる。
6. OLED / HTTP status が永続 off と通常 off を区別できる。
7. `rfkill` が無い環境でも、状態表示と解除手順が破綻しない。

## 現時点の判断

設計TODOの受け入れ条件は埋まりましたが、実装はまだ行いません。
Wi-Fi recovery-first の runtime off 表示を肉眼確認し、USB gadget Ethernet / local console / physical key の復旧経路を実機で再確認してから、永続 off の実装へ進むか判断します。
