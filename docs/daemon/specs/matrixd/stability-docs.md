# matrixd stability documentation index

更新日: 2026-06-02

この文書は、`matrixd` scan stability / ghost Space / 入力取りこぼし対策に関する文書の入口です。

## 目的

LED multi splash 中に、触れていない Space bar が短時間 press / release されたように見える事象と、まれな入力取りこぼしへの対策を整理します。

フリック入力、touch-panel PointerEvent、Vial layout、LED effect 表現そのものはこの範囲に含めません。

## 読む順番

| 順 | 文書 | 役割 |
|---|---|---|
| 1 | [stability-docs.md](stability-docs.md) | この索引。どの文書を見ればよいかを示す |
| 3 | [scan-stability-plan.md](scan-stability-plan.md) | 対策全体の計画。実機なしで進める順序、Phase、受け入れ条件 |
| 4 | [variable-scan-debounce-note.md](variable-scan-debounce-note.md) | 可変scan周期を維持したまま実時間debounceへ寄せる方針 |
| 5 | [runtime-priority-ideal.md](runtime-priority-ideal.md) | `matrixd` / `logicd` / `ledd` / `httpd` の優先度階層、socket送信、busy loop保護の理想条件 |
| 7 | [real-device-stability-checklist.md](real-device-stability-checklist.md) | 実機が使える時の確認手順 |
| 8 | [../daemon/matrixd/README.md](../../../../daemon/matrixd/README.md) | `matrixd` の通常README。設定項目、debounce mode、systemd rollback 手順 |
| 9 | [../daemon/logicd/README.md](../../../../daemon/logicd/README.md) | `logicd` の通常README。matrix input priority と飢餓回避方針 |
| 10 | [ops/test-script-inventory.md](../../../ops/test-script-inventory.md) | `script/test_matrixd_*` と `script/test_logicd_matrix_*` の棚卸しとローカル確認セット |

## source of truth

### 現在地サマリ


### 実装方針

- [scan-stability-plan.md](scan-stability-plan.md)
- [variable-scan-debounce-note.md](variable-scan-debounce-note.md)
- [runtime-priority-ideal.md](runtime-priority-ideal.md)

### 実装済み進捗


### follow-up design TODO

- [daemon/logicd-resolved-action-handler-split-design.md](../../logicd-resolved-action-handler-split-design.md)

### 実機確認

- [real-device-stability-checklist.md](real-device-stability-checklist.md)

`ops/real-device-test-checklist.md` は全体の大きな実機確認ログです。
`matrixd` ghost Space / 取りこぼし対策の詳細手順は、重複を避けるため [real-device-stability-checklist.md](real-device-stability-checklist.md) に集約します。
全体チェックリストへは、最終判断や実機確認結果だけを反映します。

### 設定・運用

- [../daemon/matrixd/README.md](../../../../daemon/matrixd/README.md)
- [../daemon/logicd/README.md](../../../../daemon/logicd/README.md)

### テスト

- [ops/test-script-inventory.md](../../../ops/test-script-inventory.md)
- `script/test_matrixd_debounce.py`
- `script/test_matrixd_build.py`
- `script/test_matrixd_scan_optimization.py`
- `script/test_logicd_matrix_input_priority.py`
- `script/test_logicd_matrix_event_processing_boundary.py`
- `script/test_logicd_output_router_boundary.py`
- `script/test_logicd_resolved_action_heavy_boundary.py`

### TODO / 優先度

- `matrixd` stability の詳細な設計・進捗・実機手順はこの索引から辿ります。
- TODO本体には、実機確認後の最終判断や残タスクだけを反映します。

## 現時点の実装済み範囲

2026-06-02 時点で実機なしで実装済み:

- `matrixd/debounce.[ch]` の分離
- `debounce_mode=count/time`
- 実時間debounce
- 高頻度raw確認でも `debounce_ms` 未満では確定しないテスト
- `post_row_settle_us`
- `MIN_INTERVAL_US=50`
- 負値設定の丸め
- busy loop保護
- `send()` 成功後にだけ debounce state を commit
- `matrixd.c + debounce.c` の build regression test
- `matrixd/README.md` の rollback 手順
- `daemon/logicd/README.md` の matrix input priority 方針
- `logicd` の matrix socket intake が軽量な queue 投入に留まることを固定する静的テスト
- `logicd` の `process_matrix_event()` にファイルI/Oや保存処理を直接持ち込まないことを固定する静的テスト
- `OutputRouter` への出力経路が matrix socket intake と直接結合しないことを固定する静的テスト
- BT / Wi-Fi / macro / output preparation など重い可能性がある処理が resolved action 境界に留まることを固定する静的テスト

## 現時点の残り

実機なしで残るもの:

- `BT_*` / `WIFI_*` / macro など、意図的に重い action の境界を README / 設計文書へもう少し詳しく整理する。
- [daemon/logicd-resolved-action-handler-split-design.md](../../logicd-resolved-action-handler-split-design.md) に基づき、必要になったら `handle_resolved_action()` を action family ごとに helper 分割する。

実機が必要なもの:

- multi splash 低輝度 / 通常輝度で Space ghost が再現しないか確認。
- 通常入力の取りこぼしが再現しないか確認。
- `debounce_mode=time` の体感遅延確認。
- `post_row_settle_us` / `settle_us` の調整値確認。
- `matrixd` RT priority rollback 比較。
- `logicd` が matrix input path で飢餓していないか確認。

## ローカル確認セット

実機なしで確認できる主なテスト:

```bash
python3 script/test_matrixd_debounce.py
python3 script/test_matrixd_build.py
python3 script/test_matrixd_scan_optimization.py
python3 script/test_logicd_matrix_input_priority.py
python3 script/test_logicd_matrix_event_processing_boundary.py
python3 script/test_logicd_output_router_boundary.py
python3 script/test_logicd_resolved_action_heavy_boundary.py
```
