# Matrix Input Latency Instrumentation Design

作成日: 2026-06-04

`KC_SH8` の後追い診断だけで入力の引っ掛かり原因を切り分けにくい場合に備え、
`matrixd -> logicd -> output backend` の latency 計測境界を固定します。
この文書は設計TODOであり、現時点では protocol や runtime 実装を変更しません。

## Goal

matrix input event が scan、socket、logicd dispatch、HID report send のどこで遅れたかを、
後から `KC_SH8` report や stability smoke で確認できるようにします。

対象にする chain:

```text
matrixd scan/event
  -> /tmp/matrix_events.sock
  -> logicd receive
  -> interaction / action dispatch
  -> USB/BLE/uinput HID send
```

## Protocol

first implementation は mixed-version safety を優先します。

- `matrixd` は既存の short tuple/text event を維持し、拡張 event を送る場合だけ version marker を付ける。
- version marker は `v=2` を第一候補にし、legacy receiver は unknown field を無視できる形にする。
- `logicd` は legacy event に対して `event_id=null`、`matrix_input_monotonic_ns=null` として処理を継続する。
- mixed-version 動作では、latency field が欠けていても key dispatch を止めない。
- protocol mismatch は high-frequency log にせず、diagnostics summary の `latency_instrumentation.available=false` に寄せる。

## Field Names

timestamp は wall clock ではなく monotonic clock 基準にします。単位は nanosecond integer で、表示時だけ millisecond に変換します。

| field | owner | unit | meaning |
| --- | --- | --- | --- |
| `event_id` | `matrixd` | integer | process-local monotonic sequence id |
| `matrix_input_monotonic_ns` | `matrixd` | ns | matrix scan / debounced input event が成立した時刻 |
| `logicd_receive_monotonic_ns` | `logicd` | ns | `logicd` が matrix socket event を受け取った時刻 |
| `hid_send_monotonic_ns` | output backend wrapper | ns | keyboard / mouse / consumer HID report を write した時刻 |
| `output_backend` | output backend wrapper | string | `usb`, `ble`, `uinput`, `debug`, or `unknown` |

Derived values:

- `scan_to_logicd_ms = logicd_receive_monotonic_ns - matrix_input_monotonic_ns`
- `logicd_to_hid_ms = hid_send_monotonic_ns - logicd_receive_monotonic_ns`
- `matrix_to_hid_ms = hid_send_monotonic_ns - matrix_input_monotonic_ns`

## Ownership

- `matrixd` owns `event_id` and `matrix_input_monotonic_ns`.
- `logicd` owns `logicd_receive_monotonic_ns`, validation, aggregation, and diagnostics payload.
- output backend wrappers own `hid_send_monotonic_ns` and `output_backend`.
- `KC_SH8` / `tools/matrixd_diagnostics_snapshot.py` only read summarized diagnostics; they do not parse live socket traffic.
- HTTP UI only shows read-only summary if a later implementation exposes one.

## Logging Policy

Normal operation must not log every matrix event.

- Default mode keeps a ring buffer of recent worst events only.
- Journal detail is emitted only when a threshold is exceeded or diagnostics mode is enabled.
- Initial threshold candidates: `scan_to_logicd_ms >= 20`, `logicd_to_hid_ms >= 20`, `matrix_to_hid_ms >= 50`.
- Ring buffer entries include `event_id`, row/col, press/release, action if already resolved, backend, derived latency, and missing-field reason.
- Missing timestamps are reported as `instrumentation_partial`, not as failure.

## Diagnostics Format

`KC_SH8` and stability smoke should render compact text instead of dumping every event.

Recommended report section:

```text
matrix input latency:
  available: true
  samples: 128
  p50/p95/max matrix_to_hid_ms: 4.2 / 13.7 / 41.9
  worst event: id=1842 key=7,0 P action=KC_ESC backend=usb matrix_to_hid_ms=41.9
  partial samples: 3 (missing hid_send_monotonic_ns)
```

If unavailable:

```text
matrix input latency:
  available: false
  reason: legacy matrix event protocol
```

## Non-goals

- Do not change key dispatch behavior in the design slice.
- Do not make `KC_SH8` execute active probes.
- Do not use wall-clock timestamps for latency math.
- Do not require all output backends to implement the field before legacy input keeps working.
- Do not persist per-event latency records to `/mnt/p3` by default.

