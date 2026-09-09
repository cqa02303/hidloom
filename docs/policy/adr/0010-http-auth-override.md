# ADR-0010: HTTP認証の変更を専用のhash保存先へ分離する

- 状態: 採用済み（既存決定の遡及記録）
- 記録日・最終確認日: 2026-09-07
- 決定日: 2026-05-23（既存の決定事項の節に記載）
- 記録対象: 選択肢・設定更新との関係

## 決定

HTTP UIから初期configを直接更新せず、password変更は専用overrideへsalt付きPBKDF2-SHA256 hashで保存する。overrideは0600とする。fresh installの初期値にはhostname置換を許容する。

## 理由

初期configと変更値を分け、共通のadmin/admin既定や平文passwordの保存を避けるため。

## 代替案・影響

初期configへの直接書戻しと平文overrideは採用しない。hostname由来初期値を秘密性の高い認証情報とみなす決定ではない。

## 現状と再検討条件

専用overrideとhash形式は実装済みの方針。実際の認証情報はADRへ記載しない。

初期認証・更新方式を変える際はfresh install、既存override互換、file権限を確認する。

## 根拠・関連仕様

- [docs/policy/decisions-spec.md](../decisions-spec.md)
- [daemon/http/auth_tls.py](../../../daemon/http/auth_tls.py)
