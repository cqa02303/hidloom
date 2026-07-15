# MIDI sequencer / audio integration design

作成日: 2026-06-01

この文書は MIDI / Audio output backend の上に、長い sequence / pattern / song を載せる場合の設計です。
2026-06-01 時点では実装へは進まず、保存形式、再生 state、停止条件、MIDI / Audio backend との境界、UI と実機確認範囲を固定します。

## Goal

- 単発 `MIDI_NOTE(n)` / `AUDIO_TONE(name)` と、長い sequence / song を分けて扱う。
- keyboard scan / HID report の遅延を増やさない。
- 再生中に output switch / reload / emergency release が来ても停止できる。
- MIDI backend / audio backend / buzzer backend を直接 song storage の owner にしない。

## Relation to MIDI / Audio output design

[audio-output-design.md](audio-output-design.md) は output backend と keycode 境界を扱う。
この文書は、その上に乗る sequencer / pattern runner を扱う。

| layer | owner candidate |
| --- | --- |
| note / tone event | audio_midi dispatcher |
| sequence timing / cursor / loop | sequencer state |
| storage | settings or `/mnt/p3/sequences` |
| backend output | USB MIDI / ALSA MIDI / Pi audio / buzzer / debug logger |

## Storage candidates

候補:

```text
/mnt/p3/sequences/midi/<name>.json
/mnt/p3/sequences/audio/<name>.json
config/default/sequences/midi/<name>.json
config/default/sequences/audio/<name>.json
```

最小 JSON 候補:

```json
{
  "version": 1,
  "name": "startup",
  "type": "midi",
  "tempo": 120,
  "events": [
    {"t": 0, "type": "note_on", "note": 60, "velocity": 64, "duration": 120}
  ],
  "loop": false,
  "max_duration_ms": 5000
}
```

方針:

- keymap action に長い sequence を直接埋め込まない。
- named sequence を参照する。
- `/mnt/p3` は user-edited runtime sequence。
- `config/default/` は fallback / sample。
- format は versioned JSON から始める。

## Candidate actions

| action | 意味 |
| --- | --- |
| `SEQ_PLAY(name)` | named sequence を再生する |
| `SEQ_STOP` | 再生中 sequence を止める |
| `SEQ_TOGGLE(name)` | 再生中なら stop、停止中なら play |
| `SEQ_STATUS` | read-only status 候補 |

初期実装では `SEQ_RECORD` は作らない。
録音や live overdub は Dynamic Macro / MIDI sequencer とは別の大きな機能として扱う。

## Runtime state

候補:

```text
idle
loading(name)
playing(name, cursor, started_at)
stopping(name, reason)
failed(name, reason)
```

方針:

- sequence state は永続化しない。
- daemon restart 後に勝手に再生を再開しない。
- `loop=true` は初期実装では無効または duration 上限必須。
- status は name / elapsed / backend / stopped reason を read-only で返す候補。

## Timing policy

- keyboard scan loop と同じ thread / blocking loop で再生しない。
- async task または専用 worker thread を候補にする。
- long sleep 中でも cancel signal を見られる構成にする。
- event timing は best effort でよく、音楽制作用途の高精度 sequencer は初期対象外。
- latency / jitter は debug metrics として記録する候補。

## Stop / cancel policy

stop する event:

- `SEQ_STOP`
- output switch
- config reload
- keymap reload
- emergency release / stuck-key recovery
- daemon shutdown
- backend unavailable
- max duration reached

stop 時:

- MIDI backend なら all notes off / pending note off を送る候補。
- audio backend なら current tone / playback を止める。
- buzzer backend なら PWM duty を 0 にする。
- debug logger backend なら stop reason を記録する。

## Backend boundary

- sequencer は backend-specific descriptor / GPIO / ALSA device を直接触らない。
- output event を audio_midi dispatcher へ渡す。
- backend unavailable は sequencer failure ではなく output warning として扱う候補。
- USB MIDI gadget の有効化 / 無効化は sequencer から行わない。

## Safety policy

- default disabled。
- max duration を必須にする候補。
- loop は初期 disabled または explicit confirmation。
- volume / velocity / duty は backend 上限を超えない。
- system / connectivity / power action は sequence event に入れない。
- external file path や shell command を sequence event に入れない。

## UI policy

HTTP:

- 初期は read-only sequence list / validation / status から始める。
- play button は明示 warning と max duration 表示を必須にする候補。
- editor は JSON preview と validation から始める。

OLED:

- `SEQ startup` / `SEQ stop` の短い alert 候補。
- event list は表示しない。

LED:

- sequencer 専用 overlay は初期不要。

## Static tests to add with implementation

設計 first slice では doc test だけを追加する。
実装へ進む場合は以下を追加する。

- sequence name validation。
- versioned JSON validation。
- max duration required。
- unknown backend no-op + warning。
- output switch / reload / emergency release で stop。
- all notes off / tone stop が stop path で呼ばれる。
- sequence event に system / connectivity / power action を入れない。
- daemon restart で自動再生しない。

## Implementation gate

実装へ進める条件:

- 先に MIDI / Audio output backend の first backend が決まっている。
- stop path と max duration がテストで固定できる。
- sequence storage と keymap action の境界が決まっている。
- backend owner と sequencer owner が分かれている。

実装しない条件:

- 音楽制作用の高精度 timing が必須になる。
- sequence から shell command や system action を実行する必要がある。
- loop 再生を default 有効にする必要がある。
- keyboard scan loop と同じ blocking loop でしか実装できない。
