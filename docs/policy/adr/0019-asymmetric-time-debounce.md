# ADR-0019: 可変scanのtime debounceを非対称にする

- 状態: 採用済み（既存決定の遡及記録）
- 記録日・最終確認日: 2026-09-07
- 決定日: 不明（参照資料の作成・更新日とは区別する）
- 記録対象: 一般的でない決定・実測と他層の関係

## 決定

可変scanを維持しtime debounceを使う。現行標準は通常press 5 ms、release 6 ms、release確定後16 ms以内に始まる同一keyの再pressだけ6 msとする。count互換とhiddの16 ms release mergeは別の機構として維持する。

## 理由

6 ms一律ではrelease反跳を抑える一方、idle pressのraw分割により有効入力を欠落し得る実測があったため。

## 代替案・影響

一律6 msへの延長だけで解決しない。scan回数による判定へ戻さず、release確定時刻と再press開始の関係を保持する。

## 現状と再検討条件

default configとtrace由来fixtureへ反映済み。保存済みchecklistにはpackage反映後の物理closeoutが残り、このADRでは完了へ変更しない。

新board/scan条件では通常tap、overlap両順、modifier、LT、final pressed zeroを確認し、反跳拒否と入力欠落防止を両立する。

## 根拠・関連仕様

- [config/default/matrixd.json](../../../config/default/matrixd.json)
- [script/test_matrixd_debounce.py](../../../script/test_matrixd_debounce.py)
- [docs/daemon/specs/matrixd/variable-scan-debounce-note.md](../../daemon/specs/matrixd/variable-scan-debounce-note.md)
