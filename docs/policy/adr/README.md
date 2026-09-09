# ADR: 現在の決定と判断の理由

最終確認日: 2026-09-07

この索引から、現在有効な決定を読む。記録基準・更新方法の正本は
[ドキュメント方針](../documentation-policy.md#adrの記録と更新)。
記録は[template.md](template.md)を使い、決定を先に、理由を短く書く。

まず見る文書:

- [template.md](template.md): 新規・遡及記録のひな形
- [0001-native-input-core.md](0001-native-input-core.md): 入力処理の責務分担
- [0014-core-profile-packages.md](0014-core-profile-packages.md): 標準配布とprofileの関係

## 現在の決定

| ADR | 決定 | 状態 |
|---|---|---|
| [ADR-0001](0001-native-input-core.md) | 通常keyboard入力をnative core、複雑な操作をPython companionへ分担する | 採用済み |
| [ADR-0002](0002-output-device-owners.md) | 出力先の選択をoutputd、デバイス操作をhidd・uidd・btdへ分離する | 採用済み |
| [ADR-0003](0003-shared-action-definitions.md) | action定義をruntime・HTTP・Vialで共有する | 採用済み |
| [ADR-0004](0004-runtime-keymap-owner.md) | runtime keymapの更新をlogicdへ集約する | 採用済み |
| [ADR-0005](0005-ble-advertisement.md) | BLEの検出入口をadvertisementへ絞る | 採用済み |
| [ADR-0006](0006-bluetooth-output-control.md) | BT出力選択とpairing操作を分け、離脱時に接続を解放する | 採用済み |
| [ADR-0007](0007-ble-report-pacing.md) | BLE内でmouse集約とkeyboard補助repeatを行う | 採用済み |
| [ADR-0008](0008-ble-reconnect-readiness.md) | BLE再接続の成立をConnectedだけで判定しない | 採用済み |
| [ADR-0009](0009-status-intent-and-runtime.md) | 選択targetと実出力を分け、表示先ごとに情報量を変える | 採用済み |
| [ADR-0010](0010-http-auth-override.md) | HTTP認証の変更を専用のhash保存先へ分離する | 採用済み |
| [ADR-0011](0011-http-network-boundary.md) | HTTPの接続元制限をmiddlewareで保証する | 採用済み |
| [ADR-0012](0012-vial-layout-authority.md) | Vial生成のslot順をKLEに合わせ、基板由来の例外をdataで表す | 採用済み |
| [ADR-0013](0013-windows-jis-us-split.md) | Windows向けにJIS mainとUS subのkeyboard経路を分ける | 採用済み |
| [ADR-0014](0014-core-profile-packages.md) | coreとdevice profileを別Debian packageにする | 採用済み |
| [ADR-0015](0015-buildroot-appliance-boundary.md) | Raspberry Pi OSを主系とし、Buildrootを並行applianceにする | 採用済み |
| [ADR-0016](0016-clean-public-export.md) | private履歴を維持し、監査済みclean exportを別repositoryへ出す | 採用済み |
| [ADR-0017](0017-release-channels.md) | source公開・内部RC・正式binary公開を別channelにする | 採用済み |
| [ADR-0018](0018-separate-write-mcp.md) | 診断MCPと限定write MCPを別serverにする | 採用済み |
| [ADR-0019](0019-asymmetric-time-debounce.md) | 可変scanのtime debounceを非対称にする | 採用済み |
| [ADR-0020](0020-bounded-ram-input-trace.md) | matrix診断を上限付きRAM traceへ分離する | 採用済み |
| [ADR-0021](0021-package-memory-admission.md) | package更新をstrictまたはsteady-state headroomで判定する | 採用済み |
| [ADR-0024](0024-native-owner-transactions.md) | 入力の順序・状態確認・解除を実行ownerのtransactionへ集約する | 採用済み |

採用済みは設計判断の状態であり、全profileへの実装・配布・実機検証完了を意味しない。
0022/0023は既に理由・代替案・再検討条件を持つため、既存pathを正本として登録した。
内部運用に属する両文書は既存のpublic export除外を維持する。

## 遡及整理の範囲と証拠

2026-09-07に、保存済みcheckoutの
仕様方針、architecture、daemon契約、package/Buildroot/release方針、既存運用判断、
最近のmatrix診断・debounce・memory gateの記録を照合した。
根拠は各ADR末尾へリンクし、決定当日の議事録や理由がない場合は作り足さない。
代替案欄は参照資料から分かる不採用方針・比較上の差を整理したもので、当時の全候補や議論順を復元したものではない。
後から整理した影響・再検討条件は、当時の発言や実測結果として扱わない。

未確定のWishlist（和文Morse、VIA入口、新sensor、device-side agent拡張など）は採用済みに昇格しない。
単純なUI配置・色・命名や仕様値の転記は単独ADRにせず、既存仕様に残した。
この一覧はrepository全履歴の網羅証明ではない。以後の作業で条件に該当する既存決定を見つけた時も追加する。
既存設計文書の初期案や過去時点の実機記録は、現在の採用状態とは分けて読む。

文書一覧:

- [0001-native-input-core.md](0001-native-input-core.md)
- [0002-output-device-owners.md](0002-output-device-owners.md)
- [0003-shared-action-definitions.md](0003-shared-action-definitions.md)
- [0004-runtime-keymap-owner.md](0004-runtime-keymap-owner.md)
- [0005-ble-advertisement.md](0005-ble-advertisement.md)
- [0006-bluetooth-output-control.md](0006-bluetooth-output-control.md)
- [0007-ble-report-pacing.md](0007-ble-report-pacing.md)
- [0008-ble-reconnect-readiness.md](0008-ble-reconnect-readiness.md)
- [0009-status-intent-and-runtime.md](0009-status-intent-and-runtime.md)
- [0010-http-auth-override.md](0010-http-auth-override.md)
- [0011-http-network-boundary.md](0011-http-network-boundary.md)
- [0012-vial-layout-authority.md](0012-vial-layout-authority.md)
- [0013-windows-jis-us-split.md](0013-windows-jis-us-split.md)
- [0014-core-profile-packages.md](0014-core-profile-packages.md)
- [0015-buildroot-appliance-boundary.md](0015-buildroot-appliance-boundary.md)
- [0016-clean-public-export.md](0016-clean-public-export.md)
- [0017-release-channels.md](0017-release-channels.md)
- [0018-separate-write-mcp.md](0018-separate-write-mcp.md)
- [0019-asymmetric-time-debounce.md](0019-asymmetric-time-debounce.md)
- [0020-bounded-ram-input-trace.md](0020-bounded-ram-input-trace.md)
- [0021-package-memory-admission.md](0021-package-memory-admission.md)
- [0024-native-owner-transactions.md](0024-native-owner-transactions.md)
- [template.md](template.md)
