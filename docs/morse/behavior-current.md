# MORSE behavior current reference

更新日: 2026-07-15

`MORSE(name)` は Tap Dance とは別の、押下時間で dot / dash を判定する timed tap behavior です。
現時点の仕様確認はこの文書を入口にします。

- [behavior-plan.md](behavior-plan.md): 検討経緯と段階計画

## 現行仕様

### Action

```text
MORSE(main)
MORSE(nav)
MORSE(symbols)
```

- `MORSE(name)` の `name` は Web UI で扱いやすいように文字列名にする。
- 使用できる名前は `A-Z a-z 0-9 _ . -` の 1〜64 文字。
- 複数の `morse_behaviors` を作り、別々のキーへ割り当てられる。

### Behavior config

`settings.interaction.morse_behaviors` に定義する。

```json
{
  "morse_behaviors": {
    "main": {
      "dot_threshold": 0.18,
      "sequence_timeout": 0.70,
      "max_depth": 4,
      "fallback_action": "KC_ESC",
      "force_commit": [".-"],
      "map": {
        ".": "KC_E",
        "-": "KC_T",
        ".-": "KC_A",
        ".-.": "KC_R"
      }
    }
  }
}
```

### 判定ルール

- press 時刻を保存する。
- release 時刻との差分が `dot_threshold` 以下なら `.`。
- `dot_threshold` より長ければ `-`。
- `sequence` が `max_depth` を超えたら cancel。
- `sequence` が action を持ち、`force_commit` に含まれていれば即 commit。
- `sequence` が action を持ち、より長い prefix がなければ自動 leaf として即 commit。
- `sequence` が action を持ち、より長い prefix があれば `sequence_timeout` まで待つ。
- timeout 時に action があれば commit、なければ cancel。
- action が `KC_NO` / `KC_NONE` / 空扱いなら cancel。
- `fallback_action` が設定されている場合、unmapped / timeout_unmapped / max_depth などの cancel で fallback を tap 発行する。
- `fallback_action` が未指定、空、`KC_NO`、`KC_NONE` の場合は従来どおり無発行 cancel。

### force_commit

`force_commit` は「枝があってもここで打ち切って確定する」指定。

例:

```json
{
  "force_commit": [".-"],
  "map": {
    ".-": "KC_A",
    ".-.": "KC_R"
  }
}
```

この場合、`.-` に到着した時点で `KC_A` を発行し、`.-.` には進まない。
`terminal` / `terminal_sequences` は互換 alias として読み取れるが、新規設定では `force_commit` を使う。

### fallback_action

`fallback_action` は「不発時に何も出さない代わりに指定 action を発行する」指定。

例:

```json
{
  "fallback_action": "KC_ESC",
  "map": {
    ".": "KC_E"
  }
}
```

この場合、`-` は未定義なので `KC_ESC` を tap 発行する。

## 実装済み

### Core / validation

- `logicd.morse_behavior`
- `MORSE(name)` parser
- dot / dash 判定
- prefix wait
- leaf commit
- force_commit
- fallback_action
- cancel
- 可変 `max_depth`
- `settings.interaction.morse_behaviors` validation
- `terminal` / `terminal_sequences` 互換 alias

### InteractionEngine

- `InteractionEngine.__init__` に `morse_behaviors` を追加。
- `MORSE(name)` press / release を runtime へ渡す。
- committed action を `_tap_events(..., source="morse")` で発行。
- timeout 用に `InteractionTimer(kind="morse")` を使う。
- reset / config reload 時に pending sequence を破棄する。
- press / pending / commit / cancel / fallback / reset の feedback event を buffer へ蓄積する。
- transport 側は `drain_morse_feedback()` で feedback event を取得できる。
- `logicd.config_runtime` が validated `morse_behaviors` を `InteractionEngine` へ渡す。
- pending / commit / cancel / fallback は OLED alert と LED の短時間キー flash として表示する。
- OLED alert は `alert` / `warning` 共通の `immediate` フラグを使って即時表示する。
  Morse 専用の queue 破棄や message 内容判定はしない。

### Ctrl feedback transport

- ctrl socket で `{"t":"MORSE_FEEDBACK"}` を送ると、蓄積済み Morse feedback を返して drain する。
- `CtrlContext.drain_morse_feedback` を `logicd.py` から `_runtime.interactions.drain_morse_feedback` へ配線済み。
- 戻り値は `{"t":"MORSE_FEEDBACK", "result":"ok", "events":[...], "count":N}`。
- feedback が利用できない context では error を返す。

### HTTP / Web UI

- `GET /api/interaction/morse-inspector` を登録済み。
- `daemon/http/morse_inspector.py` が read-only inspector payload を返す。
- `GET /api/interaction/morse-feedback` を登録済み。
- `daemon/http/morse_feedback_api.py` が ctrl socket `MORSE_FEEDBACK` を read-only HTTP drain endpoint として公開する。
- Interaction tab で `/static/morse_inspector_panel.js` を lazy load。
- JSON editor の `morse_behaviors` から read-only Morse Tree を描画。
- leaf / prefix / force_commit / cancel を表示。
- Morse snippet button を追加。
- Morse behavior builder を追加。新規定義は `.` / `-` の `KC_NO` だけを持つ空 tree 相当で開始する。
- Morse editor の `Morseを保存してreload` は、表示中の tree 入力を `settings.interaction.morse_behaviors`
  へ反映し、既存 `PUT /api/interaction` 経路で保存して `logicd` reload まで行う。
  上部 toolbar の `保存してreload` でも、保存直前に表示中の Morse editor 入力を自動反映する。
- builder から `morse_behaviors[name]` を追加・更新できる。
- builder から `MORSE(name)` action を action 入力欄へ挿入できる。
- builder から `fallback_action` を設定できる。
- Morse Feedback panel を追加し、HTTP drain endpoint を短い間隔で polling して最新 event を表示する。

### Feedback helper

- `logicd.morse_feedback` を追加。
- transport-neutral な `MorseFeedbackEvent` を定義。
- press / pending / commit / cancel / fallback / reset の payload 形を固定。
- `InteractionEngine` の `drain_morse_feedback()` から同じ payload を取り出せる。
- ctrl socket の `MORSE_FEEDBACK` command で同じ payload を取り出せる。
- WebSocket へ直接送る処理はまだ接続しない。
- Web UI は HTTP drain endpoint 経由でこの payload を表示する。
- OLED へは `MORSE main` / `. CANCEL` のような短時間 alert として接続済み。
- OLED への Morse alert は `immediate: true` 付きで送るため、素早い `...` 入力でも
  前の `.` / `..` alert の表示時間を待たず、release ごとの最新 sequence 表示に置き換わる。
- LED へは `morse_feedback` message として `ledd` へ流し、対象キーだけ短時間 overlay flash する。

## Feedback payload

例:

```json
{
  "type": "morse",
  "name": "main",
  "phase": "fallback",
  "sequence": "-",
  "stroke": "-",
  "action": "KC_ESC",
  "pending_action": null,
  "reason": "fallback_unmapped",
  "canceled": true,
  "fallback": true,
  "needs_timeout": false,
  "row": 0,
  "col": 0
}
```

`phase` 候補:

- `press`
- `pending`
- `commit`
- `cancel`
- `fallback`
- `reset`
- `idle`

## 関連テスト

- `script/test_morse_behavior.py`
- `script/test_morse_interaction_config.py`
- `script/test_interaction_engine_morse.py`
- `script/test_morse_inspector.py`
- `script/test_morse_feedback.py`
- `script/test_morse_feedback_api.py`
- `script/test_morse_ctrl_feedback.py`
- `script/test_morse_oled_alert.py`
- `script/test_i2cd_immediate_alert.py`
- `script/test_morse_led_feedback.py`
- `script/test_morse_documentation.py`
- `script/test_morse_browser_smoke_tool.py`
- `script/test_morse_browser_dom.py`

## 残り

### R1: feedback transport 接続

土台は `logicd.morse_feedback`、`InteractionEngine.drain_morse_feedback()`、ctrl socket `MORSE_FEEDBACK` で完了。
Web UI feedback は `/api/interaction/morse-feedback` と Interaction tab の Morse Feedback panel で接続済み。
OLED feedback は短時間 alert として接続済みで、実機 `i2cd` log でも `MORSE smoke` alert 受信を確認済み。
LED feedback は通常の lighting 表示を止めず、対象キーだけ pending=橙、commit=緑、cancel/fallback=赤で短時間 flash する。
実機 `ledd` log で `MORSE feedback LED flash: phase=pending key=0,0 idx=82` と `phase=cancel` を確認済み。
実機では一時 `MORSE(smoke)` 設定で press / cancel feedback が HTTP drain endpoint から返ることを確認済み。
2026-05-30 に一時 `MORSE(smoke)` を runtime keymap へ割り当て、matrix event 注入から
`i2cd` の `MORSE smoke` alert と `ledd` の `MORSE feedback LED flash: phase=cancel key=6,0 idx=81`
まで再確認した。splash 系の着火位置として使うダミー定義
`0,0` / `1,1` / `2,2` / `3,3` / `6,1` / `7,0` / `7,1` ではなく、
実LEDが見える `6,0` で赤 cancel flash を肉眼確認済み。
確認後、実機 config と runtime keymap は元に戻した。

### R2: 実機 / ブラウザ確認

実環境で確認済み:

1. `GET /api/interaction/morse-inspector` が JSON を返す。
2. `GET /api/interaction/morse-feedback` が JSON を返す。
3. `schema.route` / `schema.editor` が inspector schema として返る。
4. `MORSE(smoke)` を一時設定し、`KC_NO` map で HID 出力なしの press / cancel feedback が返る。

ブラウザで確認済み:

1. Interaction tab で Morse builder が表示される。
2. Morse Feedback panel が表示され、standby 表示になる。
3. 実ブラウザ相当の実機 headless Chromium で screenshot を取得済み。
4. Chromium を使わない Node DOM smoke で `Morseを保存してreload` 前段の editor 反映、Morse Tree の leaf / prefix / force_commit / cancel row、`Copy MORSE(name)` 相当の `MORSE(ui_smoke)` コピーを確認済み。
5. workstation 側の Google Chrome から実機 HTTP UI に接続し、`tools/morse_browser_smoke.py` で同じ builder 操作、Morse Tree row、`MORSE(ui_smoke)` コピー動線を確認済み。

ブラウザで未確認:

1. `MORSE(main)` をキーへ割り当て、短押し / 長押し / timeout / fallback が期待通り HID 出力されること。

`tools/morse_browser_smoke.py` は、workstation などメモリに余裕がある環境の headless Chromium から
実機 HTTP UI を開き、Morse Tree の leaf / prefix / force / cancel row を自動確認するための helper。
512MB Raspberry Pi 実機上では Chromium を起動しない。

`httpd` log では browser から `/api/interaction/morse-feedback` への polling が 200 で到達している。

## 手元検証

2026-05-29 にローカルと実機で Morse 系テストを実行済み。
確認コマンド:

```sh
python3 script/test_morse_behavior.py
python3 script/test_morse_interaction_config.py
python3 script/test_interaction_engine_morse.py
python3 script/test_morse_inspector.py
python3 script/test_morse_feedback.py
python3 script/test_morse_feedback_api.py
python3 script/test_morse_ctrl_feedback.py
python3 script/test_morse_oled_alert.py
python3 script/test_morse_led_feedback.py
python3 script/test_morse_browser_smoke_tool.py
python3 script/test_morse_documentation.py
python3 script/test_validation_suite.py
git diff --check
```
