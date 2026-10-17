# ADR-0016: private履歴を維持し、監査済みclean exportを別repositoryへ出す

- 状態: 採用済み（既存決定の遡及記録）
- 記録日・最終確認日: 2026-09-07
- 決定日: 不明（参照資料の作成・更新日とは区別する）
- 記録対象: 選択肢・公開境界との関係

## 決定

主開発repositoryはprivateのまま維持し、公開用repositoryへ監査済みsource、再現build、license等をclean exportする。内部履歴・個別実機証跡・credential運用は同期しない。

## 理由

公開に必要な再現性を提供しながら、内部開発の履歴と運用情報を公開範囲から分離するため。

## 代替案・影響

private repositoryのvisibility変更やbinaryだけの公開を採らない。export分類、秘匿情報監査、公開文書の到達性検証が必要になる。

## 現状と再検討条件

公開境界の機械可読契約はpublic-export.json。新しいADRも内容で公開/privateを判定し、ADRという形式だけで公開許可とはしない。

公開対象追加時に分類、再配布条件、link変換後の欠落・孤立を検証する。

## 根拠・関連仕様

- [docs/ops/public-documentation-boundary.md](../../ops/public-documentation-boundary.md)
- [config/public-export.json](../../../config/public-export.json)
- [docs/ops/buildroot-fast-boot-experiment.md](../../ops/buildroot-fast-boot-experiment.md)
