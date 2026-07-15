# MIDI / Audio output design

作成日: 2026-06-01

この文書は QMK MIDI / Audio 相当の機能を Raspberry Pi 実装に入れる前の設計です。
2026-06-01 時点では実装へは進まず、USB MIDI gadget、ALSA MIDI、Pi audio、buzzer の責務境界、keycode 範囲、latency、安全な volume、host 互換性、テスト範囲を固定します。

## Goal

- Keyboard input と音声 / MIDI 出力を混ぜず、専用 output backend として扱う。
- USB HID gadget / BLE HID / uinput の入力経路を壊さない。
- 音量・連打・長時間鳴動で不快または危険な挙動にならないようにする。
- 実機に接続する buzzer / audio device が未確定でも、設計上の責務境界を決めておく。

## Output backend candidates

| backend | 用途 | 初期扱い |
| --- | --- | --- |
| USB MIDI gadget | host へ MIDI device として Note / CC を送る | 設計候補。USB composite descriptor への影響が大きいので後続 |
| ALSA MIDI | Pi 上の MIDI sequencer / soft synth へ送る | 開発 / local debug 候補 |
| Pi audio | WAV / simple tone を Pi audio から出す | 実機 audio output が未確定のため後続 |
| PWM buzzer | GPIO buzzer で tone を鳴らす | hardware ports / buzzer design と合わせて後続 |
| debug logger | note / tone event を log へ出す | first implementation 候補 |

## Candidate keycodes

初期候補:

| keycode | 意味 |
| --- | --- |
| `MIDI_NOTE(n)` | note on/off pair を出す候補 |
| `MIDI_CC(n,v)` | Control Change を出す候補 |
| `MIDI_CH(n)` | channel 選択候補 |
| `AUDIO_TONE(name)` | named tone / alert を鳴らす候補 |
| `AUDIO_STOP` | 現在の tone / sequence を止める候補 |

初期実装では keymap に任意波形や長い sequence を直接埋め込まない。
Named preset / file / config entry に分ける。

## Owner / data flow

候補:

```text
InteractionEngine / keymap action
  -> logicd audio_midi dispatcher
  -> midi backend / audio backend / buzzer backend
```

Owner:

| layer | owner |
| --- | --- |
| key action parse / validation | `logicd` / shared action defs |
| runtime routing | `logicd` audio_midi dispatcher candidate |
| USB MIDI descriptor | `usbd` / gadget setup |
| ALSA MIDI output | future `midid` or `logicd` backend |
| PWM buzzer | future hardware port / buzzer backend |
| UI status | HTTP System / Interaction status candidate |

`ledd` / `i2cd` は音声出力 owner にはしない。
ただし OLED alert に現在の audio mode を短く表示することは候補。

## Safety policy

- default disabled。
- volume は明示上限を持つ。
- continuous tone / sequence は timeout を持つ。
- output switch / config reload / emergency release で stop event を出す。
- key repeat による過剰 note on を抑制する。
- backend unavailable 時は no-op + warning にする。
- buzzer / speaker の hardware profile がない時は daemon を起動しない。

## USB MIDI gadget boundary

USB MIDI gadget は USB descriptor を変えるため、HID keyboard / mouse / raw HID / consumer control へ影響する可能性がある。

方針:

- default では有効にしない。
- `USB_MIDI=1` のような opt-in 候補。
- Vial Raw HID と endpoint が衝突しないことを確認する。
- host OS ごとの device enumeration を実機で確認する。
- rollback は USB MIDI なしの gadget setup へ戻せること。

## ALSA MIDI boundary

- USB descriptor を変えずに local debug できる候補。
- headless Pi 上で音が出るとは限らない。
- ALSA sequencer device がない場合は no-op + warning。
- first implementation では debug logger backend の方が安全。

## Buzzer / audio boundary

- PWM buzzer は hardware ports design と合わせる。
- board profile に pin reservation が必要。
- volume / duty / frequency range を制限する。
- boot / shutdown / error alert と keyboard performance を競合させない。
- keyboard scan timing を阻害しないよう、blocking sleep は使わない。

## UI policy

HTTP:

- 初期は read-only backend availability / config validation から始める。
- enable / volume / backend selection は明示 warning を出す。
- USB MIDI は systemd / gadget setup 再構成を伴うため、HTTP から即時変更しない。

OLED:

- `MIDI on` / `Audio off` / `Tone stop` の短い alert 候補。
- 常時表示はしない。

LED:

- audio state overlay は初期不要。

## Relation to other features

| feature | 境界 |
| --- | --- |
| MIDI sequencer | 長い sequence / song は別設計。ここでは output backend と keycode 境界だけ扱う。 |
| buzzer / hardware ports | GPIO pin reservation / PWM backend は別設計で扱う。 |
| Script / KML macro | macro から MIDI / audio action を呼ぶ場合も、backend owner は audio_midi dispatcher。 |
| Power preset | display / radio power とは別。audio stop は power preset restore/low と連携候補。 |

## Static tests to add with implementation

設計 first slice では doc test だけを追加する。
実装へ進む場合は以下を追加する。

- default disabled。
- unknown backend は validation error。
- backend unavailable では no-op + warning。
- volume / duration upper bound。
- output switch / reload / emergency release で stop。
- USB MIDI opt-in flag が default off。
- HID / Vial Raw HID endpoint を壊さない gadget descriptor test。

## Implementation gate

実装へ進める条件:

- 最初の backend を debug logger / ALSA MIDI / USB MIDI / buzzer のどれにするか決まっている。
- USB MIDI を入れる場合は gadget descriptor 影響をテストできる。
- buzzer を入れる場合は board profile pin reservation がある。
- volume / timeout / stop path を先にテストで固定できる。

実装しない条件:

- USB MIDI を default 有効にする必要がある。
- keyboard scan timing を阻害する blocking audio 実装が必要になる。
- hardware pin reservation なしで buzzer を有効化する必要がある。
- volume / duration の上限が決まらない。
