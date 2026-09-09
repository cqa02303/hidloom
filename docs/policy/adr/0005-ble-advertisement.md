# ADR-0005: BLEの検出入口をadvertisementへ絞る

- 状態: 採用済み（既存決定の遡及記録）
- 記録日・最終確認日: 2026-09-07
- 決定日: 2026-05-22（既存の決定事項の節に記載）
- 記録対象: 一般的でない決定・hostとの関係

## 決定

BLE HID advertisementはpairing/reconnectを受け入れる必要がある間に出す。標準のpairingでは`Pairable=yes`、adapterの`Discoverable=no`とし、新規pairingでもDiscoverableを自動で有効にしない。

## 理由

iPhoneで同じkeyboardが二重表示されるのを避けるため。

## 代替案・影響

常時advertiseやDiscoverable併用は診断用opt-inとして残す。すべてのhost向けに発見方法を一律追加する変更はしない。

## 現状と再検討条件

設定によるpairing/always/offとDiscoverable opt-inが仕様化されている。

新しいhostで検出できない場合はhost別の観測を取り、二重表示との両方を検証する。

## 根拠・関連仕様

- [docs/policy/decisions-spec.md](../decisions-spec.md)
- [daemon/btd/README.md](../../../daemon/btd/README.md)
