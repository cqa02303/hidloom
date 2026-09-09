# ADR-0020: matrix診断を上限付きRAM traceへ分離する

- 状態: 採用済み（既存決定の遡及記録）
- 記録日・最終確認日: 2026-09-07
- 決定日: 不明（参照資料の作成・更新日とは区別する）
- 記録対象: 選択肢・入力性能と保存媒体の関係

## 決定

matrix構造eventだけをnonblocking経路で別writerへ渡し、RAM上で各4 MiB・2世代、0600のtraceを循環保存する。trace障害はcounterへ残し、入力を止めない。永続snapshotは明示採取にする。

## 理由

低頻度障害の直前を残しつつ、scan時のI/O負荷、microSDへの常時書込み、入力内容の記録を抑えるため。

## 代替案・影響

通常scanからの同期file writeや自動永続snapshotをしない。再起動で履歴を失い、queue drop時は証跡が不完全になる。

## 現状と再検討条件

traceとsnapshot helperはsourceへ実装済み。mapped keycode、文字列、HID payload、script、credentialは対象外。今回実機の権限・retention確認はしていない。

診断項目や保存先を増やす時は入力遅延、容量、秘匿情報、欠落検出を再評価する。

## 根拠・関連仕様

- [docs/ops/matrixd-incident-snapshot.md](../../ops/matrixd-incident-snapshot.md)
- [script/test_matrixd_trace.py](../../../script/test_matrixd_trace.py)
