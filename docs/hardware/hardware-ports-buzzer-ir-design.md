# Hardware ports / buzzer / IR design

作成日: 2026-06-01

この文書は GPIO に追加する buzzer / IR / 汎用 hardware port を扱う前の設計です。
2026-06-01 時点では実装へは進まず、board profile の pin reservation、daemon 起動条件、PWM / carrier の責務境界、MIDI / Audio output との接続、実機確認範囲を固定します。

## Goal

- 未定義の GPIO を勝手に使わない。
- board profile に明示された port だけを有効にする。
- buzzer / IR / 汎用 output を keyboard scan や LED timing と競合させない。
- hardware がない環境では daemon / backend を起動しない。
- MIDI / Audio output design と接続できるが、pin owner は hardware ports 側に置く。

## Scope

初期候補:

| port | 用途 | 初期扱い |
| --- | --- | --- |
| `buzzer_pwm` | short tone / alert / simple audio feedback | board profile で pin がある時だけ候補 |
| `ir_tx` | IR carrier output / remote preset | 実機検証待ち。初期は設計のみ |
| `gpio_out` | simple on/off output | safety validation 後の候補 |
| `gpio_in` | external switch / sensor input | matrixd / i2cd との owner 境界を決めてから |

初期実装では、arbitrary GPIO script や web からの直接 GPIO 操作は作らない。

## Board profile schema candidate

```json
{
  "hardware_ports": {
    "buzzer_pwm": {
      "enabled": true,
      "pin": 18,
      "pwm_channel": 0,
      "max_duty": 0.30,
      "max_duration_ms": 1000
    },
    "ir_tx": {
      "enabled": false,
      "pin": 17,
      "carrier_hz": 38000,
      "max_burst_ms": 500
    }
  }
}
```

方針:

- pin は board profile の明示定義が必須。
- default は disabled。
- pin overlap は validation error。
- matrix / LED / I2C / SPI / analog stick で使う pin と重複させない。
- hardware profile がない時は backend を起動しない。

## Owner / data flow

| layer | owner candidate |
| --- | --- |
| board pin reservation | board profile |
| hardware port validation | config / board profile validator |
| buzzer tone event | audio_midi dispatcher -> buzzer backend |
| IR preset event | future ir backend |
| GPIO direct access | hardware backend only |
| HTTP status | read-only availability / config warning |

`logicd` は action dispatch の coordinator になれるが、GPIO register 操作や PWM detail の owner にはしない。

## Buzzer policy

- PWM backend を候補にする。
- duty / frequency / duration に上限を持つ。
- default volume は低めにする。
- blocking sleep で keyboard scan を止めない。
- output switch / reload / emergency release / daemon shutdown で stop する。
- MIDI / Audio output の `AUDIO_TONE(name)` から呼べる候補にする。

初期 key/action 候補:

| action | 意味 |
| --- | --- |
| `BUZZER_TONE(name)` | named tone を鳴らす |
| `BUZZER_STOP` | tone を止める |
| `BUZZER_STATUS` | read-only status |

## IR policy

- IR TX は carrier frequency と burst duration の上限が必要。
- protocol encoder は backend から分ける。
- preset は named entry にする。
- HTTP から arbitrary raw pulse list を直接送らない。
- 実機 receiver / oscilloscope / logic analyzer がない状態では実装しない。

初期 key/action 候補:

| action | 意味 |
| --- | --- |
| `IR_SEND(name)` | named IR preset を送る |
| `IR_STOP` | 送信中 burst を止める |
| `IR_STATUS` | read-only status |

## Generic GPIO policy

- 汎用 GPIO は危険なので後回し。
- pin mode は board profile で固定し、runtime で arbitrary mode change しない。
- output は duration / fail-safe default を持つ。
- input は matrixd / i2cd / dedicated daemon のどれが owner かを先に決める。

## Safety policy

- default disabled。
- pin reservation 必須。
- pin overlap validation 必須。
- max duration / duty / burst を必須にする。
- stop path を必須にする。
- backend unavailable は no-op + warning。
- hardware がない時は daemon を起動しない。
- HTTP から pin number を直接指定して即時操作しない。

## UI policy

HTTP:

- 初期は read-only availability / validation warning を表示する。
- enable / pin assignment は board profile editor の後続候補。
- direct send button は実機確認が済むまで作らない。

OLED:

- `Buzzer off` / `IR send` の短い alert 候補。
- 常時表示はしない。

LED:

- hardware port 専用 overlay は初期不要。

## Relation to other features

| feature | 境界 |
| --- | --- |
| MIDI / Audio output | buzzer backend は audio_midi dispatcher から呼ぶ候補。pin owner は hardware ports。 |
| Power preset | low power / restore で buzzer / IR を stop する候補。 |
| matrixd scanner abstraction | matrix scan pin と port pin は board profile validation で重複禁止。 |
| spid / analog / i2cd | SPI / I2C / analog pins と重複させない。 |

## Static tests to add with implementation

設計 first slice では doc test だけを追加する。
実装へ進む場合は以下を追加する。

- hardware_ports default disabled。
- pin overlap validation。
- missing board profile では backend 起動しない。
- max duration / max duty / max burst required。
- output switch / reload / emergency release で stop。
- HTTP status は read-only。
- direct arbitrary GPIO action が validation を通らない。

## Implementation gate

実装へ進める条件:

- board profile に pin reservation が入っている。
- stop path と duration upper bound がテストで固定できる。
- buzzer / IR の first hardware が決まっている。
- keyboard scan timing への影響を測定できる。

実装しない条件:

- board profile なしで GPIO を使う必要がある。
- HTTP から任意 pin を直接操作する必要がある。
- blocking sleep で timing を作る必要がある。
- pin overlap を許容しないと成立しない。
