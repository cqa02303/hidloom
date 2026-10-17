# ADR-0015: Raspberry Pi OSを主系とし、Buildrootを並行applianceにする

- 状態: 採用済み（既存決定の遡及記録）
- 記録日・最終確認日: 2026-09-07
- 決定日: 不明（参照資料の作成・更新日とは区別する）
- 記録対象: 選択肢・機能と運用の関係

## 決定

通常開発・機能追加はRaspberry Pi OSを主系として続け、Buildrootは別microSDのoffline keyboard applianceとする。追加機能は価値、依存、起動、容量、保守性、network露出から搭載可否を判断する。

## 理由

通常運用の機能と復旧経路を残しながら、keyboardが使えるまでの時間を短縮する構成を検証するため。

## 代替案・影響

Raspberry Pi OSの全面置換や全機能の無条件移植をしない。二構成の再現buildと共有keymap schema互換を保つ負担がある。

## 現状と再検討条件

M6の再現build assetsが存在する。M1/M3の最小構成をM6の全搭載仕様として読まず、各milestoneと現行差分表を参照する。

usable keyboard/input-to-HIDで優位性と維持費を評価する。systemd-analyze totalだけで採否を決めない。

## 根拠・関連仕様

- [docs/ops/buildroot-fast-boot-experiment.md](../../ops/buildroot-fast-boot-experiment.md)
- [build/buildroot/README.md](../../../build/buildroot/README.md)
- [INSTALL.md](../../../INSTALL.md)
