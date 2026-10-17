# ADR-0003: action定義をruntime・HTTP・Vialで共有する

- 状態: 採用済み（既存決定の遡及記録）
- 記録日・最終確認日: 2026-09-07
- 決定日: 不明（参照資料の作成・更新日とは区別する）
- 記録対象: 見えにくい制約・他機能との関係

## 決定

action名・wrapper・layer/custom actionの共通定義を`shared_action_defs.py`へ集約し、runtime parser、HTTP validation、Vial codecの対応を揃える。

## 理由

runtimeで動くactionをHTTPが拒否したり、Vialとの入出力で失ったりする重複定義のずれを防ぐため。

## 代替案・影響

各利用側が独立してaction一覧を持つ構成は共通定義へ寄せる。外部protocolの表現制限や移行中の例外まで対応済みとみなさない。

## 現状と再検討条件

共有定義は実装済み。個々のactionの対応範囲はrouting matrixで確認し、全codecの完全移行をこのADRから推定しない。

新action追加時はruntime、validation、codecの表現可否を併せて確認する。

## 根拠・関連仕様

- [docs/architecture/single-source-architecture.md](../../architecture/single-source-architecture.md)
- [daemon/logicd/shared_action_defs.py](../../../daemon/logicd/shared_action_defs.py)
- [docs/keycode/action-routing-matrix.md](../../keycode/action-routing-matrix.md)
