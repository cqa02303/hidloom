# MCP Write-Capable Tool Design

作成日: 2026-06-13

Keyboard MCP の標準 server は read-only のまま維持する。実キー送信、service restart、設定保存、
実機 checkout 整備のような状態変更は、別 server / 別 allowlist / 明示確認つき tool として扱う。

## 方針

- `keyboard` MCP server は診断専用にする。
- write-capable tool は `keyboard-write` のような別名で登録し、常用の read-only snapshot からは呼ばない。
- network listen はしない。local stdio または SSH stdio だけを対象にする。
- default は dry-run。実行には tool ごとの確認句を要求する。
- payload は allowlist とサイズ制限を持つ。任意 shell、任意 file write、任意 git 操作は入れない。
- 実行前 snapshot、実行後 smoke、rollback / restore 手順を tool output に必ず含める。
- secret、Bluetooth address full value、長い log body、任意 diff hunk は返さない。

## 初期対象

| tool 候補 | 目的 | 初期状態 | 確認句 |
| --- | --- | --- | --- |
| `send_text_smoke_sequence` | `U+3042` / `TEXT(kana_a)` の bounded 実入力 smoke | helper script まで実装。MCP tool 化は未導入 | `SEND_TEXT_SMOKE_TO_FOCUSED_HOST` |
| `send_test_key` | `KC_A` / `KC_ESC` など allowlist された単発 key tap | 後続候補 | `SEND_TEST_KEY_TO_FOCUSED_HOST` |
| `preview_lighting_with_restore` | LED role preview と restore | 後続候補 | `PREVIEW_LIGHTING_AND_RESTORE` |
| `restart_keyboard_service` | allowlist service の restart | 後続候補。post-smoke が固定されるまで入れない | `RESTART_KEYBOARD_SERVICE` |

最初の実装対象は text-send smoke だけでよい。これは既存の
[`script/text_send_smoke_sequence.py`](../../script/text_send_smoke_sequence.py) が dry-run default と
確認句つき `--send` を持つため、write-capable MCP tool 化する場合も同じ guard を使える。

## 禁止すること

- 任意 command 実行。
- 任意 path への write / delete。
- `git reset --hard`、広域 `git clean`、unbounded `rsync`。
- keymap 全体の直接上書き。
- Bluetooth pair / forget の直接実行。
- Wi-Fi off / reboot / shutdown の直接実行。
- focused host が不明なままの実キー送信。

## 実キー送信 tool の条件

実キー送信は host 側アプリへ副作用が出る。MCP tool 化する場合は以下を満たす。

- dry-run で tap sequence、broker kind、socket、gap、blocking reasons を返す。
- 実行時は確認句を完全一致で要求する。
- デフォルト broker kind は Windows JIS / US split の通常文字経路に合わせて `us_sub_keyboard` にする。
- 送信 action は `U+3042` と `TEXT(kana_a)` のような短い smoke 用 allowlist から開始する。
- Enter は IME code conversion の確定目的だけに使い、アプリ送信用 Enter は別 tool にしない。
- host 側で安全な入力欄へ focus していることを operator が確認する。
- 実行後は `/api/status` と `text_send` readiness を read-only で再確認する。

## 実験 checkout との関係

実機で一時修正を試す場合は [../ops/real-device-experiment-workflow.md](../ops/real-device-experiment-workflow.md) を優先する。
実験が終わったら一時変更を戻し、実験結果から repository を更新し、その後に実機を pull する。
write-capable MCP はこの流れを短絡せず、必要な場合だけ bounded action を実行する補助に留める。

## 完了判断

- read-only `keyboard` server の境界が文書上も実装上も維持されている。
- write-capable tool の初期候補、禁止事項、確認句、post-smoke が固定されている。
- 実キー送信の first slice は MCP 本体ではなく guarded helper として dry-run default で確認できる。
- 実機で送る場合は operator が focused host を確認してから明示確認句を渡す。

関連:

- MCP read-only server: [../ops/keyboard-mcp-server.md](../ops/keyboard-mcp-server.md)
- 実機一時実験 workflow: [../ops/real-device-experiment-workflow.md](../ops/real-device-experiment-workflow.md)
- Unicode / Send String safety: [../input/unicode-send-string-safety-design.md](../input/unicode-send-string-safety-design.md)
