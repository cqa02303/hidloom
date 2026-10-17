# ADR-0002: 出力先の選択をoutputd、デバイス操作をhidd・uidd・btdへ分離する

- 状態: 採用済み（既存決定の遡及記録）
- 記録日・最終確認日: 2026-09-07
- 決定日: 不明（参照資料の作成・更新日とは区別する）
- 記録対象: 選択肢・他機能との関係

## 決定

`hidloom-outputd`がoutput targetと配送を所有する。coreはbroker frameを渡し、USB endpointはhidd、Piのuinputはuidd、BLE transportはbtdが所有する。

## 理由

companion内だけのtarget変更ではnative入力の実出力が切り替わらず、USB ownerにroutingまで集めると責務を再分離しづらいため。

## 代替案・影響

coreへuinput/ioctlを直接追加する案、hiddへrouterを吸収する案を採らない。既存broker frame互換を維持する代わりにdaemon間の障害処理が必要になる。

## 現状と再検討条件

outputdを挟む経路が現行仕様。切替時は旧・新targetの押下状態をreleaseし、control失敗を表示上だけ成功にしない。

新backend追加時もtarget ownerとdevice ownerを先に決める。socketやframe変更時は既存client互換を確認する。

## 根拠・関連仕様

- [docs/architecture/native-output-routing-uidd-design.md](../../architecture/native-output-routing-uidd-design.md)
- [docs/daemon/specs/outputd/README.md](../../daemon/specs/outputd/README.md)
- [docs/daemon/specs/uidd/README.md](../../daemon/specs/uidd/README.md)
