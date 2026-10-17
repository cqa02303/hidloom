# ADR-0001: 通常keyboard入力をnative core、複雑な操作をPython companionへ分担する

- 状態: 採用済み（既存決定の遡及記録）
- 記録日・最終確認日: 2026-09-07
- 決定日: 不明（参照資料の作成・更新日とは区別する）
- 記録対象: 選択肢・他機能との関係

## 決定

通常keyboardの入力処理と押下状態の所有を`logicd-core-rs`へ置き、複雑なactionや管理処理をPython companionへ委譲する。USBなどのdevice ownerは別daemonに置く。

## 理由

Pythonの起動・初期化を通常打鍵の成立条件から外し、既存の高度な機能と互換性を維持するため。

## 代替案・影響

Python全体の軽量化だけに留める案と全機能の一括native移植は採らない。委譲境界のIPCと二重処理防止を保守する必要がある。

## 現状と再検討条件

keyboard profileの現行仕様はnative coreとcompanionの分担。touch profileを含む全構成の一律native化を意味しない。
状態の正本、委譲の順序、sourceごとの解除は[ADR-0024](0024-native-owner-transactions.md)で具体化する。

委譲遅延や互換性が問題になった機能単位で所有者を再検討する。起動短縮はusable keyboardで確認する。

## 根拠・関連仕様

- [docs/daemon/specs/logicd-core-rs/README.md](../../daemon/specs/logicd-core-rs/README.md)
- [docs/daemon/native-fast-input-core-design.md](../../daemon/native-fast-input-core-design.md)
