# ADR-0017: source公開・内部RC・正式binary公開を別channelにする

- 状態: 採用済み（既存決定の遡及記録）
- 記録日・最終確認日: 2026-09-07
- 決定日: 不明（参照資料の作成・更新日とは区別する）
- 記録対象: 見えにくい制約・外部割当との関係

## 決定

監査済みsourceはsource-public、実機候補はinternal-rc、正式binaryはstable-publicで扱う。正式VID/PID割当の最新証拠はstable-publicのgateとし、未割当中も他channelの条件を満たす作業は継続する。

## 理由

外部割当の待ち時間で開発とsource同期を止めず、USB identity未確定binaryの正式公開を防ぐため。

## 代替案・影響

全作業をPID待ちで止める案や内部identityのbinary公開は採らない。正式昇格には検証済みRCのexact sourceへidentityを適用して再build/最終smokeが必要になる。

## 現状と再検討条件

release-channels.jsonとrelease readinessがchannelを区別する。このADRは割当の現在の承認状態や公開readyを証明しない。

正式identity適用時は最新割当証拠とWindows fresh enumerationを含む最終gateを確認する。

## 根拠・関連仕様

- [docs/ops/release-channel-policy.md](../../ops/release-channel-policy.md)
- [config/release-channels.json](../../../config/release-channels.json)

## 2026-09-28: 正式identityのM6搭載

割当確認後のM6は明示的な`HIDLOOM_M6_USB_PROFILE=public_formal`選択で、同じguarded contractから
USB gadgetとconfig/Vial seedを生成する。開発互換defaultとM1–M4 templateは保持する。
理由はUSBとVialの部分移行を防ぎ、別microSDの復旧用開発identityを維持するため。
新しいnetwork露出やtarget依存は追加せず、host上の生成とimage内照合に限定する。
採用済みだが、実機移行・公開の受入を意味しない。descriptor構成変更時は生成templateとimage検証を再評価する。
