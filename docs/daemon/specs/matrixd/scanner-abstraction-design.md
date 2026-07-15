# matrixd scanner abstraction / row-column design

作成日: 2026-06-01

この文書は、現在の charlieplex scanner と将来の row-column scanner を `matrixd` 内で分けるための設計です。
2026-06-01 時点では C 実装へは進まず、scanner interface、GPIO pin mapping、debounce / timing、board profile 連携、互換テスト範囲を固定します。

## Goal

- 現行 charlieplex scanner を壊さず、row-column matrix 版を追加できる構造にする。
- `logicd` / HTTP / Vial / keymap は matrix event `(row, col, press/release)` を受けるだけにし、物理配線方式を知らない構成にする。
- board profile で scanner type と pin map を選べるようにする。
- C 実装時に `matrixd.c` が巨大化しないよう、scanner ごとに module を分ける。

## Current baseline

- `matrixd` は C 実装。
- 現行の標準基板は charlieplex scan を使う。
- `logicd` との IPC は `/tmp/matrix_events.sock` の matrix event を前提にしている。
- board profile は `ver1.0` / `ver0.1` のような基板差分を扱う source of truth になっている。

## Proposed module split

候補:

```text
matrixd/
  matrixd.c              # daemon entry / socket / option wiring
  scanner.h              # common scanner interface
  scanner_charlieplex.c  # current charlieplex implementation
  scanner_rowcol.c       # future row-column implementation
  debounce.c             # shared debounce helper candidate
  board_profile.c        # scanner config load candidate
```

`matrixd.c` に残すもの:

- daemon startup / shutdown
- socket output
- signal handling
- scanner selection wiring
- common logging

scanner module に移すもの:

- GPIO direction / drive / read pattern
- scan loop internal state
- electrical topology specific handling
- row / col -> physical pin mapping

## Common scanner interface

候補:

```c
typedef struct matrix_event {
    int row;
    int col;
    bool pressed;
    uint64_t timestamp_us;
} matrix_event_t;

typedef struct scanner scanner_t;

typedef int (*scanner_init_fn)(scanner_t *scanner, const scanner_config_t *config);
typedef int (*scanner_poll_fn)(scanner_t *scanner, matrix_event_t *events, size_t max_events);
typedef void (*scanner_close_fn)(scanner_t *scanner);
```

方針:

- scanner は matrix event だけを返す。
- socket protocol は scanner 固有にしない。
- row/col の意味は keymap / Vial / HTTP の座標と一致させる。
- timestamp は debugging / debounce tuning 用で、初期 IPC へ必ず載せるとは限らない。

## Scanner type config

board profile 側の候補:

```json
{
  "matrix_scanner": {
    "type": "charlieplex",
    "pins": [5, 6, 13, 19],
    "rows": 9,
    "cols": 9,
    "debounce_ms": 5,
    "scan_interval_us": 1000
  }
}
```

row-column 候補:

```json
{
  "matrix_scanner": {
    "type": "row_column",
    "row_pins": [5, 6, 13, 19],
    "col_pins": [12, 16, 20, 21],
    "rows": 4,
    "cols": 4,
    "diode_direction": "row_to_col",
    "debounce_ms": 5,
    "scan_interval_us": 1000
  }
}
```

## Row-column policy

- row-column scanner は charlieplex の特殊 tri-state pattern を使わない。
- row drive / col read または col drive / row read を `diode_direction` で固定する。
- ghosting 対策は diode あり前提から始める。
- diode なし NKRO ghost detection は初期対象外。
- pull-up / pull-down の選択は board profile に入れる候補。

## Charlieplex policy

- 現行挙動を source of truth とする。
- row-column 抽象化のために座標や event format を変えない。
- charlieplex scanner の timing / settle delay は既存実機確認値を維持する。
- 現行 scanner を無理に generic row-column model へ押し込まない。

## Debounce / timing

共有化候補:

- per-key stable state
- last transition timestamp
- debounce threshold
- event coalescing

方針:

- electrical scan と debounce を完全に混ぜない。
- scanner module が raw state を出し、shared debounce が event 化する構成を候補にする。
- ただし現行 charlieplex の安定性を優先し、移行は段階的に行う。

## HTTP / logicd / Vial boundary

- `logicd` は scanner type を知らない。
- HTTP layout は board profile / Vial layout から row/col を見る。
- Vial keymap protocol は scanner type に依存しない。
- scanner type は System panel の read-only board detail に出す候補。
- matrix tester は event だけを見るため、scanner type に依存しない。

## Migration plan

1. `scanner.h` の interface を設計し、現行 charlieplex scanner を wrapper 化する。
2. `matrixd.c` から scanner 固有 GPIO code を切り出す。
3. board profile に `matrix_scanner.type=charlieplex` を追加する。
4. row-column scanner を stub として追加し、実機なしで config validation と compile を通す。
5. row-column 実機ができた時に GPIO / diode direction / ghosting を確認する。

## Static tests to add with implementation

設計 first slice では doc test だけを追加する。
実装へ進む場合は以下を追加する。

- board profile に scanner type がない場合は `charlieplex` default。
- unknown scanner type は起動前 validation error。
- row-column config は `row_pins` / `col_pins` / `diode_direction` を要求する。
- charlieplex config は既存 pin list を受ける。
- scanner type を変えても `logicd` event format が変わらない。
- `matrixd.c` に scanner 固有の pin drive logic が戻らないことを guard する。

## Implementation gate

実装へ進める条件:

- 現行 charlieplex の実機挙動を維持できる。
- scanner interface が row/col event を変えない。
- board profile の scanner type default が決まっている。
- C module split 後の compile / systemd 起動確認ができる。

実装しない条件:

- row-column 対応のために現行 charlieplex 座標を変える必要がある。
- `logicd` / Vial / HTTP keymap に scanner type 依存を持ち込む必要がある。
- diode なし matrix の ghosting 対応を初期要件に入れる必要がある。
