# ADR-0021: package更新をstrictまたはsteady-state headroomで判定する

- 状態: 採用済み（既存決定の遡及記録）
- 記録日・最終確認日: 2026-09-07
- 決定日: 不明（参照資料の作成・更新日とは区別する）
- 記録対象: 一般的でない決定・長時間稼働との関係

## 決定

Pi Zero 2 WのAPT actual直前にstrictまたはsteady-state条件とaudit/process/lock cleanを要求する。steady-stateでもメモリ・swap絶対量、空き率、合計headroomを満たす。simulationは1回とし、75%未満だけでrebootを必須にしない。

## 理由

長時間稼働ではsimulation後の固定75%判定が十分な絶対headroomでも停止し、過去OOM値と区別する必要があったため。

## 代替案・影響

strictの空き率だけの一律判定や単純な閾値撤廃を採らない。複合条件の保守が必要だが、過去OOM・swapなし・極小swapは拒否し続ける。

## 現状と再検討条件

現行helperはstrict 128/256 MiB/75%、steady-state 96/256 MiB/60%/combined 384 MiB。数値の実行上の正本はhelperとfixture。実機導入済みとは推定しない。

APT依存、RAM/swap構成、package負荷が変わった時に実測する。両条件不合格ならactualを始めずsimulationを反復しない。

## 根拠・関連仕様

- [tools/package/low_memory_install_preflight.py](../../../tools/package/low_memory_install_preflight.py)
- [script/test_low_memory_install_preflight_tool.py](../../../script/test_low_memory_install_preflight_tool.py)
- [docs/ops/failure-patterns.md](../../ops/failure-patterns.md)
