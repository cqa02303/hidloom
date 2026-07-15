# Power management preset design

更新日: 2026-06-01

OLED off、LED off、BT off、Wi-Fi off、low power mode をまとめて扱うための設計です。
2026-06-01 時点では、実機なしで進められる first slice として `logicd.power_preset_status` の read-only metadata helper と静的テストを追加済みです。
まだ preset action の実行、Wi-Fi / BT / OLED / LED への dispatch、restore 実装は行いません。

## 目的

- 省電力操作を個別 action の寄せ集めではなく、意図が分かる preset として扱う。
- 既存の `WIFI_POWER_OFF` / `BT_POWER_OFF` / LED / OLED の制御境界を崩さない。
- Wi-Fi を落として SSH / HTTP へ戻れない、BT を落として入力が戻らない、という失敗を preset 側で増やさない。
- 実装前に「保存される低電力状態」と「一時的な runtime 低電力状態」を分ける。
- UI では preset の risk / confirmation / recovery route を先に表示できるようにする。

## 既存前提

- `WIFI_POWER_OFF` は recovery-first の runtime off として扱い、通常 reboot 後は Wi-Fi on に戻す。
- 永続 Wi-Fi off は [connectivity/wifi-persistent-off-design.md](../connectivity/wifi-persistent-off-design.md) に分離済みで、初期 power preset には混ぜない。
- `BT_POWER_OFF` は `btd` / socket を止められるが、paired host の reconnect / HID notify 復帰は実機確認が残っている。
- OLED off / LED off は radio off より復旧リスクが低いが、状態が見えなくなるので HTTP / local recovery の導線が必要。
- USB / local key / reboot のいずれかを recovery route として残す。
- `logicd.power_preset_status` は preset を実行せず、read-only safety metadata だけを返す。

## Candidate actions

初期候補:

- `POWER_PRESET_STATUS`
  - 現在の preset / applied runtime state / recovery route を read-only で返す。
- `POWER_PRESET_LOW`
  - LED を off または低輝度、OLED を dim または短時間表示へ寄せる。
  - 初期状態では Wi-Fi / BT は変更しない。
- `POWER_PRESET_DISPLAY_OFF`
  - OLED と LED だけを消す。
  - radio は触らない。
- `POWER_PRESET_RADIOS_OFF`
  - `BT_POWER_OFF` と `WIFI_POWER_OFF` 相当をまとめる危険 preset。
  - HTTP / OLED / local key で確認が取れる時だけ有効にする。
- `POWER_PRESET_RESTORE`
  - preset が runtime で変更した OLED / LED / BT / Wi-Fi 状態を戻す。
  - reboot をまたいだ復元は初期対象外にする。

将来候補:

- `LOW_POWER_TOGGLE`
  - UI alias としては便利だが、初期実装では明示 preset 名を優先する。

## Settings shape

保存するのは preset 定義だけで、active state は保存しない。
初期値は `persist=false` とし、boot 後に勝手に低電力へ戻らない。

```json
{
  "settings": {
    "power_presets": {
      "low": {
        "oled": "dim",
        "led": "off",
        "bt": "unchanged",
        "wifi": "unchanged",
        "persist": false,
        "requires_confirmation": false
      },
      "display_off": {
        "oled": "off",
        "led": "off",
        "bt": "unchanged",
        "wifi": "unchanged",
        "persist": false,
        "requires_confirmation": false
      },
      "radios_off": {
        "oled": "status",
        "led": "off",
        "bt": "off",
        "wifi": "runtime_off",
        "persist": false,
        "requires_confirmation": true
      }
    }
  }
}
```

## Read-only status metadata

`logicd.power_preset_status.power_preset_status_payload()` returns:

```json
{
  "schema": "power_preset.status.v1",
  "read_only": true,
  "current_preset": null,
  "restore_available": false,
  "active_state_persistent": false,
  "default_safe_preset": "low",
  "recovery_routes": [
    "USB keyboard / gadget path",
    "local physical key",
    "power cycle / reboot"
  ],
  "presets": {
    "low": {
      "risk": "low",
      "requires_confirmation": false,
      "touches_radios": false
    },
    "radios_off": {
      "risk": "high",
      "requires_confirmation": true,
      "touches_radios": true
    }
  }
}
```

Risk policy:

| risk | 条件 |
| --- | --- |
| `low` | radio に触らず、display-only でもない軽い preset。 |
| `medium` | OLED / LED を消すなど、状態が見えにくくなる preset。 |
| `high` | Wi-Fi / BT など radio を変更する preset。 |
| `blocked` | `persist=true` など初期実装で扱わない永続 active state を含む preset。 |
| `unknown` | preset が定義されていない。 |

`requires_confirmation` は、preset 側の指定に加え、radio 変更または persistent state を含む場合に true になります。

## Owner / data flow

- `logicd`
  - preset action の coordinator。
  - active runtime state と `POWER_PRESET_STATUS` の source of truth。
  - Wi-Fi / BT / OLED / LED へ直接保存 payload を書かず、既存 helper / socket 経路へ委譲する。
- `logicd.power_preset_status`
  - preset 実行は行わず、risk / confirmation / recovery route の read-only metadata だけを作る。
- `wifi_manager`
  - Wi-Fi runtime power の owner。
  - preset からの Wi-Fi off も `WIFI_POWER_OFF` と同じ recovery-first 経路を使う。
- `btd` / BlueZ
  - Bluetooth HID runtime の owner。
  - preset から直接 BlueZ state を保存しない。
- `i2cd`
  - OLED 表示 / dim / off / alert の owner。
  - `Power Low`、`Display Off`、`Radios Off` の短い alert を出す。
- `ledd`
  - LED effect / off / restore の owner。
  - preset 適用前の runtime effect を可能なら memory に保持する。
- `httpd`
  - status 表示と confirmation UI を担当する。
  - radio off や persistent off の直接 owner にはしない。

## Initial policy

- 初期実装は transient preset だけにする。
- `POWER_PRESET_LOW` は Wi-Fi / BT を落とさない。
- `POWER_PRESET_LOW` の最小対象は LED low/off と OLED dim に限定する。
- `POWER_PRESET_DISPLAY_OFF` の最小対象は LED off と OLED off に限定する。
- `POWER_PRESET_RADIOS_OFF` は explicit confirmation がない限り実行しない。
- `POWER_PRESET_RADIOS_OFF` は confirmation UI、recovery-first Wi-Fi path、paired host reconnect 確認が揃うまで実行対象外にする。
- preset active state は config に保存しない。
- `POWER_PRESET_RESTORE` は、同一 daemon runtime 内で preset が変更した値だけを戻す。
- first slice の read-only payload では、未適用状態を `current_preset=null`、`restore_available=false` として System panel / OLED へ出せる形にする。
- reboot 後は通常の boot policy に従い、Wi-Fi は recovery-first で on に戻す。
- persistent Wi-Fi off を有効にする UI / keycode は、この preset とは別の上級設定として扱う。

Restore 対象:

| subsystem | restore する runtime state | restore しない state |
| --- | --- | --- |
| LED | preset が変更した brightness / effect / off state | 保存済み `config/default/ledd.json`、user preset、direct-frame producer の所有状態 |
| OLED | preset が変更した dim / off / alert state | boot policy、display orientation、永続設定 |
| Wi-Fi | preset が runtime off を実行した同一 daemon runtime 内の on 復帰 | `settings.wifi.persistent_off`、NetworkManager connection profile |
| BT | preset が runtime off を実行した同一 daemon runtime 内の on 復帰 | BlueZ bond、paired host metadata、rename / forget metadata |

## No-go

初期実装では行わない:

- boot 時に自動で low power preset を再適用する。
- `POWER_PRESET_LOW` で Wi-Fi / BT を暗黙に off へする。
- `settings.wifi.persistent_off=true` を preset から保存する。
- OLED / LED / Wi-Fi / BT / input をすべて同時に無効化し、復旧導線を消す。
- script / system command を preset に埋め込む。
- HTTP だけを唯一の restore route にする。
- first slice で実際の radio / OLED / LED 状態を変更する。

## UI / feedback

HTTP:

- System panel に current preset、radio state、restore action、recovery route を表示する。
- `POWER_PRESET_RADIOS_OFF` は confirmation modal を出す。
- warning には「Wi-Fi off 後は HTTP / SSH が切れる」「reboot で Wi-Fi は戻る」「local key / USB / power cycle が復旧経路」と明記する。

OLED:

- `POWER_PRESET_LOW`: `Power Low`
- `POWER_PRESET_DISPLAY_OFF`: `Display Off`
- `POWER_PRESET_RADIOS_OFF`: `Radios Off`
- restore 時は `Power Restore` を短く表示する。

LED:

- `low` は消灯または低輝度へ寄せる。
- `display_off` は消灯する。
- `restore` は preset 適用前の runtime effect へ戻す。
- LED off 中も critical alert を出すかは、実機の見え方を確認してから決める。

## Static tests

実装済み first slice:

- `low` は Wi-Fi / BT off を含まず `risk=low`、confirmation 不要。
- `display_off` は radio に触らず `risk=medium`。
- `radios_off` は `risk=high`、confirmation 必須、recovery warning を含む。
- `persist=true` の preset は `risk=blocked`。
- unsupported Wi-Fi / BT action は warning に出る。
- payload は read-only で `current_preset=null`、`restore_available=false`、`active_state_persistent=false`。
- OLED label は `Power Low` / `Display Off` / `Radios Off` / `Power Restore` を返す。

後続実装時に追加するテスト:

- `POWER_PRESET_LOW` が Wi-Fi / BT off を呼ばない。
- `POWER_PRESET_RADIOS_OFF` は confirmation なしでは実行されない。
- preset から `settings.wifi.persistent_off=true` を保存しない。
- `WIFI_POWER_OFF` は既存 recovery-first 経路を使う。
- `POWER_PRESET_RESTORE` は daemon runtime 内の変更だけを戻し、config に active preset を保存しない。
- HTTP warning に recovery route が含まれる。
- OLED / LED owner は `logicd` ではなく `i2cd` / `ledd` のまま維持される。

## Implementation gate

実装へ進める条件:

- Wi-Fi runtime off / reboot 復帰 / OLED runtime off 表示の実機確認が終わっている。
- `BT_POWER_OFF` 後、paired host がある状態で `BT_POWER_ON` / reconnect / HID notify 復帰を確認できている。
- LED role preview / restore と LED off / restore の境界が実機で確認できている。
- HTTP confirmation と local recovery route の文言を static test で固定できる。

実装しない条件:

- `radios_off` が HTTP / SSH の唯一の管理経路を失わせる。
- restore が保存済み config を破壊する。
- preset active state を永続化しないと実装できない。
- BT reconnect の復旧経路が paired host で確認できていない状態で、BT off を含む preset を default にする必要がある。
