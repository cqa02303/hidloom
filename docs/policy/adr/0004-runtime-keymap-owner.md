# ADR-0004: runtime keymapの更新をlogicdへ集約する

- 状態: 採用済み（既存決定の遡及記録）
- 記録日・最終確認日: 2026-09-07
- 決定日: 不明（参照資料の作成・更新日とは区別する）
- 記録対象: 選択肢・他機能との関係

## 決定

利用者のkeymapは`/mnt/p3/keymap.json`を優先し、`config/default/keymap.json`は初期値とする。HTTP/Vialのremapはlogicdを通し、native coreへはsnapshot/reloadで反映する。

## 理由

保存状態と表示・入力解決が別々の正本を持たないようにするため。

## 代替案・影響

HTTP/Vialがそれぞれruntime状態や初期configを直接管理する形にはしない。永続化とcoreへの反映の整合性を保つ必要がある。

## 現状と再検討条件

runtime fileとcore snapshotの責務は現行仕様。profile installが既存runtime定義を無条件に上書きする権限を与えるものではない。
snapshot/reloadの反映契約は[ADR-0024](0024-native-owner-transactions.md)で具体化し、実行ownerの適用ACKと永続化を区別する。reload通知だけで適用成功とは扱わない。

keymap schemaや保存経路を変える時はHTTP/Vial/native coreとBuildrootの共有データ互換を確認する。

## 根拠・関連仕様

- [docs/policy/decisions-spec.md](../decisions-spec.md)
- [docs/daemon/native-fast-input-core-design.md](../../daemon/native-fast-input-core-design.md)
- [docs/ops/package-profile-split-plan.md](../../ops/package-profile-split-plan.md)
