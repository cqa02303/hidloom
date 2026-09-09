# ADR-0024: 入力の順序・状態確認・解除を実行ownerのtransactionへ集約する

- 状態: 採用済み（実装・自動実行範囲の検証済み。手動・物理確認は別途）
- 記録日: 2026-09-07。最終確認日: 2026-09-08
- 決定日: 不明（今回の課題修正作業で採用。単一の決定日時は未記録）
- 記録対象: 選択肢・daemon間の状態所有・切断時の互換性
- 関連する決定: [ADR-0001](0001-native-input-core.md)、[ADR-0004](0004-runtime-keymap-owner.md)、[ADR-0018](0018-separate-write-mcp.md)の役割分担・更新入口・server分離を維持し、その整合性契約を具体化する。

## 決定

keyboard profileではnative coreをlayer・押下時actionの正本とする。Python companionのinteractionイベントとtimerをdelegate v2の順序付きtransactionで扱い、世代とrevisionを検証してlayer操作を反映する。未解決pressはACKを待つが、既に解決したnative keyのreleaseと制御処理は継続する。

Web入力はownerが発行する接続単位のsource sessionを使い、切断・lease切れ・設定再読込でそのsourceだけを解除する。nativeを使わないPython構成も通常のsource入力を保持し、既存の短命matrix接続の寿命は変更しない。

HTTP/Vial等のkeymap変更はlogicd coordinatorで直列化し、実行ownerの適用ACKとファイル保存を分けて返す。MCPの単一位置変更は条件付きCAS、tapは同じowner処理内で条件を再確認して専用sourceの解除を予約する。応答不明時は同一operationを照会し、無条件の再送・旧keymapへのrollbackをしない。再実行と再照会を区別できる確認句を使う。

## 理由

別々に更新・観測したkeymap、layer、押下状態だけでは、確認したactionと実際に実行するactionの一致や、timer後の解決順序を保証できない。解除責務をclientの生存や座標だけに結び付けると、切断時の押し残しや同座標の別入力の誤解除が生じるため、実行ownerで確認・順序・source寿命を扱う。

## 代替案・影響

以下は今回の計画・実装に基づく比較であり、既存ADRの決定当時の議論を復元したものではない。

- 全入力を常時Pythonへ委譲すれば正本は一つになるが、ADR-0001の通常入力経路をPythonの応答に依存させる。全機能のnative移植もこの修正の条件にしない。
- layerの定期snapshot転送やMCPでの事前status確認だけでは、転送間の更新・timer・別client操作との競合を閉じられない。世代付きの適用順序とowner内の再確認を採る。
- client側のP/R送信と終了時の全解除は実装が小さいが、client消失時の解除予約と他sourceの保持を同時に満たさない。接続別の所有とownerの解除期限を保守する。

IPCの世代・待機queue・ACK・source cleanupの実装と異常系テストが増える。待機とbufferを有限にし、通信失敗を成功や無入力へ読み替えない。ownerの受付・解除済みはhost applicationの受信証明ではなく、MCPもfocusや実機到達を保証しない。

## 現状と再検討条件

native/Python、MCP、HTTPの実socket結合と、timer・競合・ACK損失・source切断・backpressureの対象回帰を実装・検証した。ARMでの隔離実行、標準package適用後の稼働状態、guarded通常キーのowner解除とhost受信も確認した。物理入力品質・各hostのIME/BLE動作・再接続・boot性能は別の確認であり、この採用状態や通常キー1回の受信から推定しない。詳細契約は[core仕様](../../daemon/specs/logicd-core-rs/README.md)、操作と条件付き復旧は[write MCP手順](../../ops/keyboard-write-mcp-server.md)を正本とする。

delegate待機やbuffer上限が通常打鍵・timer精度を損なう実測が得られた場合、またはprofileのowner構成やkeymap互換性を変える場合に境界を再検討する。単なる遅延回避のために有効なkeymapを拒否したり、guardを迂回したりしない。

## 根拠・関連仕様

- [native delegate実装](../../../tools/hidloom_logicd_core/src/delegate.rs)・[owner操作](../../../tools/hidloom_logicd_core/src/owner_protocol.rs)・[Python delegate](../../../daemon/logicd/delegate_protocol.py)
- [keymap coordinator](../../../daemon/logicd/keymap_coordinator.py)・[source sessionと再読込時の解除](../../../daemon/logicd/input_session.py)・[MCP実装](../../../dev/mcp/keyboard_write/server.py)
- [native owner結合回帰](../../../script/test_native_owner_protocol.py)・[ACK異常回帰](../../../script/test_keymap_coordinator.py)・[MCP CAS/tap結合回帰](../../../script/test_mcp_native_owner.py)
- [Webからnativeへの結合回帰](../../../script/test_http_native_input_session.py)・[Python source寿命回帰](../../../script/test_control_owner_sessions.py)
