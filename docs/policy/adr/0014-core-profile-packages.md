# ADR-0014: coreとdevice profileを別Debian packageにする

- 状態: 採用済み（既存決定の遡及記録）
- 記録日・最終確認日: 2026-09-07
- 決定日: 不明（参照資料の作成・更新日とは区別する）
- 記録対象: 選択肢・複数deviceとの関係

## 決定

標準配布をhidloom-coreとdevice profileのsplit Debian packageとする。同versionを同APT transactionでinstallし、profile applyでbackup後にruntime定義とservice policyを反映する。

## 理由

共通runtimeの更新と、keyboard/touchごとに異なる入力定義・service構成の選択を分けるため。

## 代替案・影響

single packageのruntime apply案は置換済み。checkout rsyncなどはlegacy/recovery用途。exact version依存のためcoreだけの独立更新はしない。

## 現状と再検討条件

split packageが現行標準。installだけで利用者のruntime定義を無条件上書きしない。

core/profile互換性をversion範囲で保証できるようになった時に依存方式を再検討する。

## 根拠・関連仕様

- [docs/ops/package-profile-split-plan.md](../../ops/package-profile-split-plan.md)
- [tools/package/README.md](../../../tools/package/README.md)
- [docs/ops/release-packaging-runbook.md](../../ops/release-packaging-runbook.md)
