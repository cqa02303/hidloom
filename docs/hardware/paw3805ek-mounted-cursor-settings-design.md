# PAW3805EK mounted cursor / settings UI design

作成日: 2026-06-01

この文書は PAW3805EK などの SPI optical sensor を、キーボード筐体へ固定搭載した cursor / scroll / gesture 入力として扱う前の設計です。
2026-06-01 時点では実装へは進まず、`spid`、mouse HID、mounting orientation、HTTP settings、board profile、実機検証の境界を固定します。

## Goal

- optical sensor の物理向きや取り付け位置を board profile と settings で扱えるようにする。
- `spid` は raw motion / health の owner とし、mouse HID 変換は `logicd` 側で扱う方針を維持する。
- 実機なしでは sensor 動作を仮定せず、設定 schema と validation だけを先に固定する。
- trackball / trackpad / mounted cursor の将来拡張と衝突しないようにする。

## Current baseline

- SPI mouse sensor daemon は `spid` として分離候補がある。
- `logicd` は mouse report output path を持つ。
- board profile は基板差分 / pin / layout の source of truth になっている。
- 実機センサーが未定義の時は daemon を起動しない方針がある。

## Device / board profile schema candidate

候補:

```json
{
  "devices": {
    "cursor_sensor": {
      "type": "paw3805ek",
      "enabled": true,
      "owner": "spid",
      "spi_bus": 0,
      "spi_device": 0,
      "cs_pin": 8,
      "motion_pin": null,
      "orientation": "normal",
      "mount": "right_thumb",
      "dpi": 800
    }
  }
}
```

方針:

- board profile に device 定義がない場合、`spid` は起動しない。
- SPI bus / CS / optional motion pin は board profile の pin reservation と重複チェックを受ける。
- `type=paw3805ek` は driver selection に使う。
- `mount` は UI 表示 / default axis tuning の hint として使う。

## Runtime settings candidate

候補:

```json
{
  "settings": {
    "cursor_sensor": {
      "enabled": true,
      "mode": "cursor",
      "axis_swap": false,
      "invert_x": false,
      "invert_y": false,
      "rotation": 0,
      "sensitivity": 1.0,
      "acceleration": "off",
      "scroll_layer": null,
      "scroll_mode": "hold_layer"
    }
  }
}
```

方針:

- runtime settings は挙動調整を扱う。
- board profile は物理配線 / device type / mount を扱う。
- `rotation`、`axis_swap`、`invert_x`、`invert_y` の重複表現は実装前に正規化する。
- 初期実装では `rotation` か `axis_swap + invert` のどちらか一方を source of truth にする。

## Owner / data flow

```text
PAW3805EK sensor
  -> spid raw motion / health
  -> logicd cursor transform
  -> mouse HID report
  -> USB / BLE / uinput output
```

Owner:

| layer | owner |
| --- | --- |
| SPI transaction / sensor health | `spid` |
| device presence / pin mapping | board profile |
| orientation / sensitivity settings | `logicd` settings candidate |
| mouse HID report | `logicd` output path |
| HTTP settings UI | `httpd` as editor / read-only status consumer |

`spid` は host output target を知らない。
`httpd` は sensor を直接 read/write しない。

## Modes

初期候補:

| mode | 内容 |
| --- | --- |
| `cursor` | dx/dy を mouse cursor movement にする |
| `scroll` | dx/dy を wheel / horizontal wheel にする |
| `disabled` | motion を HID へ出さない |

後続候補:

- `layered_cursor_scroll`: layer / modifier で cursor と scroll を切り替える。
- `gesture`: tap / flick / edge gesture。初期対象外。

## Orientation policy

- `normal` / `rot90` / `rot180` / `rot270` のような離散 rotation を第一候補にする。
- `axis_swap` / `invert_x` / `invert_y` は UI 表示や legacy compatibility で使う候補。
- 初期実装では rotation を source of truth にし、UI で invert / swap に展開するかを検討する。
- 実機検証で、物理 mount と指の移動方向に合う default を board profile に残す。

## HTTP UI policy

- 初期は read-only device presence / health / current settings 表示から始める。
- settings editor は sensitivity / rotation / mode の最小 field から始める。
- raw sensor register editor は作らない。
- save 後は `spid` ではなく `logicd` transform config reload を第一候補にする。
- `spid` driver parameter を変える場合は restart が必要かを別途表示する。

## Safety / performance policy

- device 定義がない時は daemon を起動しない。
- sensor read failure は keyboard 入力を止めない。
- motion burst が多い時も output queue を詰まらせない。
- sensitivity 上限を設ける。
- acceleration は初期 `off`。
- output switch / emergency release では mouse zero report を出す。
- sleep / polling interval は keyboard scan と競合しないようにする。

## Real-device checks

- SPI bus / CS / sensor ID read。
- motion dx/dy の符号と向き。
- `rotation` / invert / swap の正しさ。
- cursor mode / scroll mode の出力。
- USB / BLE / uinput での mouse report。
- high motion 時の CPU / queue / dropped motion。
- sensor なし board profile で `spid` が起動しないこと。

## Static tests to add with implementation

設計 first slice では doc test だけを追加する。
実装へ進む場合は以下を追加する。

- board profile に device がない時は `spid` disabled。
- unknown sensor type は validation error。
- orientation / rotation validation。
- sensitivity upper/lower bound。
- HTTP settings save payload が board profile pin mapping を変更しない。
- output switch / emergency release で mouse zero report。
- sensor failure が keyboard output を止めない。

## Implementation gate

実装へ進める条件:

- board profile に PAW3805EK device / SPI pin reservation がある。
- sensor ID / motion の実機確認ができる。
- orientation source of truth が `rotation` か `axis_swap + invert` のどちらかに決まっている。
- `spid` raw motion と `logicd` transform の境界をテストで固定できる。

実装しない条件:

- sensor 定義なしで daemon を起動する必要がある。
- HTTP から raw SPI register を直接編集する必要がある。
- keyboard scan / HID output を止める blocking sensor read が必要になる。
- board profile と runtime settings の owner が分けられない。
