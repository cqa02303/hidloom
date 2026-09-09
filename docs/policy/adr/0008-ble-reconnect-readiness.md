# ADR-0008: BLE再接続の成立をConnectedだけで判定しない

- 状態: 採用済み（既存決定の遡及記録）
- 記録日・最終確認日: 2026-09-07
- 決定日: 2026-05-22（既存の決定事項の節に記載）
- 記録対象: 見えにくい制約・外部stackとの関係

## 決定

BlueZのConnectedだけでHID接続成功としない。host_connected/StartNotifyが戻らないstuck reconnectではnull reset後にGATT application/advertisementを再登録する。再接続直後のgraceとrecovery cooldownを設ける。

## 理由

接続表示があってもnotification購読が成立せず、キーが届かない状態があるため。

## 代替案・影響

Connectedのみの成功判定や即時の再登録反復を避ける。recoveryがhostの再購読と競合しない待機が必要になる。

## 現状と再検討条件

btdのstuck reconnect recoveryとして仕様化されている。判定回数・grace・cooldownは現行設定を参照する。

BlueZ/host更新時は、接続成功とnotify準備完了の両方、recoveryの反復有無を確認する。

## 根拠・関連仕様

- [docs/policy/decisions-spec.md](../decisions-spec.md)
- [daemon/btd/README.md](../../../daemon/btd/README.md)
