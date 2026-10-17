# ADR-0007: BLE内でmouse集約とkeyboard補助repeatを行う

- 状態: 採用済み（既存決定の遡及記録）
- 記録日・最終確認日: 2026-09-07
- 決定日: 2026-05-22（既存の決定事項の節に記載）
- 記録対象: 一般的でない決定・transportとの関係

## 決定

BLE mouseの移動をcoalescingし、通常キーには必要なhost向けのsynthetic release/pressによる補助repeatを持つ。null/release、recovery、停止時に補助repeatを止める。

## 理由

BLE notify queueの負荷を抑えながらmouse追従性を保ち、保持reportだけではrepeatしないhostを扱うため。

## 代替案・影響

mouse移動の全件即時notifyやhost repeatだけへの依存には制約がある。補助repeatをUSB/uinputへ広げず、集約による遅延とnotify負荷を調整する。

## 現状と再検討条件

btdのBlueZ backend内の機能として記録されている。具体的な間隔はbtd設定と仕様を参照する。

hostのrepeat対応やBLE送信特性が変わった時に、二重repeat、停止、追従性を再確認する。

## 根拠・関連仕様

- [docs/policy/decisions-spec.md](../decisions-spec.md)
- [daemon/btd/README.md](../../../daemon/btd/README.md)
