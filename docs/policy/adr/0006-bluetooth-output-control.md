# ADR-0006: BT出力選択とpairing操作を分け、離脱時に接続を解放する

- 状態: 採用済み（既存決定の遡及記録）
- 記録日・最終確認日: 2026-09-07
- 決定日: 2026-05-22（既存の決定事項の節に記載）
- 記録対象: 見えにくい制約・hostとの関係

## 決定

`KC_BT`は出力backend選択、`BT_*`はBluetooth controlとする。BT出力に必要ならcontrollerをpower onする。BTを出力先から外す時はnull report後にhostを切断する。autoはUSBを優先し、BT fallbackは明示opt-inとする。

## 理由

出力切替の意味を保ちつつ、BTを使わない時にiPhoneのソフトウェアkeyboardを復帰させるため。

## 代替案・影響

pairing offを出力切替と同義にしない。接続の保持や無条件のBT fallbackは標準挙動にしない。再利用時にはreconnectが必要になる。

## 現状と再検討条件

Bluetooth controlと出力targetの分離は現行仕様。nativeの実出力切替はADR-0002のoutputd経路に従う。

host側keyboard復帰やauto優先順位を変更する場合は、接続状態と選択targetの両方の契約を見直す。

## 根拠・関連仕様

- [docs/policy/decisions-spec.md](../decisions-spec.md)
- [docs/architecture/native-output-routing-uidd-design.md](../../architecture/native-output-routing-uidd-design.md)
