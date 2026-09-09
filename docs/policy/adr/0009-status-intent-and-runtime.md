# ADR-0009: 選択targetと実出力を分け、表示先ごとに情報量を変える

- 状態: 採用済み（既存決定の遡及記録）
- 記録日・最終確認日: 2026-09-07
- 決定日: 2026-05-22（既存の決定事項の節に記載）
- 記録対象: 見えにくい制約・UIとの関係

## 決定

選択targetの`auto`と実出力のUSB/BT/Piを別の状態として保持・表示する。journalは調査詳細、HTTPは状態と詳細、OLEDは短い状態と一時alertを担当する。

## 理由

USB接続時も選択はautoのままであり、表示の簡略化によって利用者の選択や障害調査情報を失わないため。

## 代替案・影響

autoを実backend名で上書きしない。OLEDへ内部名や全診断情報を並べず、詳細参照先を残す。

## 現状と再検討条件

APIはoutput_targetとruntime modeを分ける。通常表示ではgadgetをUSB、uinputをPiと表記する。

backendやUI追加時は、選択値と観測値を混同しない契約を確認する。

## 根拠・関連仕様

- [docs/policy/decisions-spec.md](../decisions-spec.md)
- [docs/policy/logging-status-policy.md](../logging-status-policy.md)
