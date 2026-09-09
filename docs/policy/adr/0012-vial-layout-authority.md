# ADR-0012: Vial生成のslot順をKLEに合わせ、基板由来の例外をdataで表す

- 状態: 採用済み（既存決定の遡及記録）
- 記録日・最終確認日: 2026-09-07
- 決定日: 2026-05-24（既存の決定事項の節に記載）
- 記録対象: 選択肢・hardwareとUIの関係

## 決定

Vial生成ではKLE slotを先に読み、KiCad switch pointをその順へ割り当てる。除外・補正・virtual slotはvial-layout-overrides.jsonで明示する。encoder pulseは通常slotから除き、表示用e slotはvirtualとして扱う。

## 理由

KLE表示と物理switchの対応、および基板だけでは決まらないencoder等の例外を明示して保つため。

## 代替案・影響

KiCad座標を正にKLEを変形する方式や、生成script内の個別条件追加を採らない。overrideと未割当reportの保守が必要になる。

## 現状と再検討条件

mkvial.pyとoverride設定を根拠にする。生成後は未割当欄を確認する。

新boardやencoder配置変更時にslot対応とHTTP previewを再検証する。

## 根拠・関連仕様

- [docs/policy/decisions-spec.md](../decisions-spec.md)
- [build/generators/mkvial.py](../../../build/generators/mkvial.py)
- [config/default/vial-layout-overrides.json](../../../config/default/vial-layout-overrides.json)
