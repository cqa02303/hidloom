# ADR-0011: HTTPの接続元制限をmiddlewareで保証する

- 状態: 採用済み（既存決定の遡及記録）
- 記録日・最終確認日: 2026-09-07
- 決定日: 2026-05-24（既存の決定事項の節に記載）
- 記録対象: 選択肢・環境依存の制約

## 決定

HTTPのprimaryな接続元policyをhttpd middlewareへ置く。既定ではloopback、IPv4 private/link-localを許可し、IPv6や追加の管理networkは明示CIDR設定にする。OS firewallは追加防御として扱う。

## 理由

fresh installで特定firewallの有無に依存せず、repo内でpolicyとregressionを保持できるため。

## 代替案・影響

OS firewallだけに依存する案は採用しない。middlewareの許可範囲が運用networkに適合するか管理する必要がある。

## 現状と再検討条件

httpdの許可network設定とmiddlewareに実装されている。認証・CSRFなど他の境界を置き換えない。

IPv6/VPN/proxy対応時は実際のclient addressと許可範囲を明確にして見直す。

## 根拠・関連仕様

- [docs/policy/decisions-spec.md](../decisions-spec.md)
- [daemon/http/httpd.py](../../../daemon/http/httpd.py)
