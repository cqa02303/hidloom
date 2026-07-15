# LED long-run metrics

更新日: 2026-05-26

LED video / direct-frame を長時間動かす時の観測入口です。
実機なしでも、観測項目・手順・記録形式を固定しておき、実機がある時に同じ観点で比較できるようにします。

## 目的

- direct-frame producer が送った frame と `ledd` が適用した frame の差を見る。
- accepted / applied / ignored / rejected の増え方を見る。
- 長時間再生時に dropped frame、thermal、CPU、memory の傾向を見る。
- demo asset、producer、`ledd`、HTTP status の見え方を揃える。

## 観測対象

| 項目 | 意味 |
|---|---|
| `direct_frame_active` | direct-frame 入力が現在 active か |
| `accepted_frames` | socket receiver が受け入れた frame 数 |
| `applied_frames` | renderer 側で実際に適用した frame 数 |
| `ignored_frames` | active 状態や restore などの都合で無視された frame 数 |
| `rejected_frames` | packet format / size / validation で拒否された frame 数 |
| `bytes_received` | direct-frame socket が受けた byte 数 |
| `last_frame_id` / `last_applied_frame_id` | producer / renderer 側の最後の frame id |
| `last_error` | 最後の error 文字列 |

## 手動観測 helper

`tools/demo/led_direct_frame_metrics_watch.py` は、`/tmp/ledd_direct_frame_status.json` を読み、
一定間隔で差分 rate を表示します。
HTTP UI を開かずに観測できるため、長時間再生時の軽量な監視に使います。

例:

```bash
python3 tools/demo/led_direct_frame_metrics_watch.py --interval 1
python3 tools/demo/led_direct_frame_metrics_watch.py --interval 2 --count 30
LEDD_DIRECT_FRAME_STATUS=/tmp/ledd_direct_frame_status.json python3 tools/demo/led_direct_frame_metrics_watch.py
```

出力例:

```text
active=1 source=json_file accepted=240(24.0/s) applied=238(23.8/s) ignored=0 rejected=0 bytes=86400(8640/s) last=239 err=-
```

## 推奨手順

### 1. baseline

```bash
curl -k -u admin:$(hostname) https://127.0.0.1/api/status
python3 tools/demo/led_direct_frame_metrics_watch.py --interval 1 --count 5
```

### 2. short smoke

```bash
python3 tools/demo/play_led_video.py --backend ledd-direct --seconds 10 --fps 24
python3 tools/demo/led_direct_frame_metrics_watch.py --interval 1 --count 15
```

### 3. long-run

```bash
python3 tools/demo/play_led_video.py --backend ledd-direct --seconds 300 --fps 24
python3 tools/demo/led_direct_frame_metrics_watch.py --interval 5 --count 70
```

別 terminal で resource baseline を取る場合:

```bash
python3 tools/perf_baseline.py --output /tmp/hidloom-led-long-run.md --ps-samples 30 --ps-interval 10
```

## 記録すること

- 日付、commit SHA、Raspberry Pi 個体、電源条件、LED 数。
- `play_led_video.py` の `--fps`、`--seconds`、入力動画。
- watch tool の accepted/s、applied/s、rejected、last_error。
- `top` / `ps` で目立つ CPU / RSS。
- 体感上の明るさ、速度、カクつき、欠落 frame の有無。
- restore 後に通常 Lighting effect へ戻るか。

## 受け入れの目安

- 10 秒 smoke で rejected が 0 のまま。
- applied/s が producer fps に近い。
- `last_error` が空または `-` のまま。
- producer 終了後、direct-frame fallback / restore の方針どおり通常表示に戻る。

長時間再生では thermal / CPU 条件で applied/s が落ちる可能性があります。
落ちた場合は failure と決めつけず、fps、LED 数、CPU、温度、電源条件と一緒に記録します。

## 関連

- [../daemon/specs/ledd/direct-frame-socket-plan.md](../daemon/specs/ledd/direct-frame-socket-plan.md)
- [../daemon/specs/ledd/direct-frame-fallback.md](../daemon/specs/ledd/direct-frame-fallback.md)
- [ops/performance-tuning-plan.md](../ops/performance-tuning-plan.md)
- [tools/README.md](../../tools/README.md)

## Pattern editor boundary

The first editor slice is limited to VialRGB-compatible effect parameters and long-run observation presets.
It is not an LED role editor, semantic role override editor, or shared preset marketplace.

Initial editor scope:

- `pattern`: direct-frame demo pattern draft such as `rainbow` / `pulse` / `solid`.
- `splash`: VialRGB splash / reactive mode parameter draft.
- `reactive`: VialRGB reactive mode parameter draft.
- common parameters: brightness, speed, hue, saturation, value, FPS limit, timeout.

Out of scope:

- semantic role override.
- layer overlay color editing.
- host lock LED editing.
- per-key LED role reassignment.
- direct writes to `config/default/ledd.json` from preview.

## Preview / restore policy

Preview must be side-effect-free:

- Save the current effect snapshot before preview.
- Apply preview through the existing Lighting preview / direct-frame path.
- Enforce brightness ceiling: default max `128`, hard max `192` unless explicitly confirmed.
- Enforce preview timeout: default `30s`, hard max `300s`.
- Restore the previous effect on timeout, user restore, disconnect, HTTP error, or daemon reload.
- If a direct-frame producer disconnects during preview, use the documented direct-frame fallback policy and then restore the saved effect.

## Save format

Do not write pattern editor changes directly into `config/default/ledd.json` in the first slice.

Use a draft / user override boundary:

```json
{
  "version": 1,
  "led_pattern_editor": {
    "drafts": {
      "demo-rainbow": {
        "kind": "pattern",
        "pattern": "rainbow",
        "brightness": 96,
        "fps": 24,
        "timeout_sec": 30
      }
    }
  }
}
```

Candidate storage:

```text
/mnt/p3/led_pattern_editor.json
```

Rules:

- `config/default/ledd.json` remains the default effect configuration owner.
- `/mnt/p3/led_pattern_editor.json` stores user drafts / overrides.
- Exported presets are versioned JSON and do not include runtime metrics.
- Import starts preview-only, then save after restore safety passes.

## Long-run record format

Record long-run observations as Markdown or JSON under a caller-selected path, with `/tmp` as the default for throwaway runs.

Minimum fields:

- commit SHA
- board profile
- LED count
- effect / pattern / FPS / brightness
- accepted FPS / applied FPS
- dropped frames
- rejected frames
- CPU percent
- RSS
- thermal reading when available
- memory pressure summary when available
- journal warning / error count
- restore result
- human observation note for speed, brightness, and visible dropped frames

Demo asset notes should include the asset name, duration, FPS, and whether the real LED chain was checked.

## 2026-06-10 pattern / metrics groundwork

`daemon/ledd/led_pattern_metrics.py` を追加し、pattern editor / long-run metrics の no-device
groundwork を固定した。この helper は LED へ frame を送らず、`config/default/ledd.json` も変更しない。

完了した範囲:

- `led_pattern_editor.draft.v1` draft validation。
- editor scope は `pattern` / `splash` / `reactive` に限定し、semantic role override とは分ける。
- `brightness` は default ceiling `128`、hard ceiling `192`。default ceiling 超過は explicit confirm が必要。
- preview plan は current effect snapshot、timeout restore、disconnect restore、HTTP error restore、daemon reload restore を要求する。
- preview は direct-frame preview path または VialRGB preview path の plan だけを返し、実 LED 送信は行わない。
- `led_long_run.metrics.v1` が accepted / applied / ignored / rejected / bytes / dropped frames / FPS / last error / warning を集計する。

未実装のまま残す範囲:

- 実 LED の見え方。
- 長時間発熱・電源余裕確認。
- HTTP UI editor / API route 接続。
- `/mnt/p3/led_pattern_editor.json` への保存。
