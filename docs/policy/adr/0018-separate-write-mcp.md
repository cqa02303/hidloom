# ADR-0018: 診断MCPと限定write MCPを別serverにする

- 状態: 採用済み（既存決定の遡及記録）
- 記録日・最終確認日: 2026-09-07
- 決定日: 不明（参照資料の作成・更新日とは区別する）
- 記録対象: 選択肢・権限と実入力の関係

## 決定

keyboard MCPをread-onlyに保ち、writeは別keyboard-write stdio serverへ置く。writeのplan/確認句、keymap digest、allowlist、範囲制限、readbackと復旧手順を要求する。

## 理由

日常の診断から意図せず実入力や設定変更へ進まない境界を作るため。

## 代替案・影響

同じ診断serverへの任意shell・任意file write追加やnetwork listenを採らない。別profileと操作ごとのguardを維持する負担がある。

## 現状と再検討条件

別serverにstatus、tap plan/tap、1位置keymap plan/applyを実装済み。設計文書のrestart等の候補は実装済みtoolではない。
復旧は[ADR-0024](0024-native-owner-transactions.md)の条件付き変更で行い、古い値への無条件rollbackは行わない。

新write toolには操作範囲、実行前後の確認、失敗時復旧を定義する。実装済みであることは実機操作の包括承認を意味しない。

## 根拠・関連仕様

- [docs/policy/mcp-write-capable-tool-design.md](../mcp-write-capable-tool-design.md)
- [dev/mcp/keyboard_write/README.md](../../../dev/mcp/keyboard_write/README.md)
- [dev/mcp/keyboard/README.md](../../../dev/mcp/keyboard/README.md)
