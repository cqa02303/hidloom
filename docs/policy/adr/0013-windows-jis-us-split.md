# ADR-0013: Windows向けにJIS mainとUS subのkeyboard経路を分ける

- 状態: 採用済み（既存決定の遡及記録）
- 記録日・最終確認日: 2026-09-07
- 決定日: 不明（参照資料の作成・更新日とは区別する）
- 記録対象: 一般的でない決定・OSとHIDの関係

## 決定

Windows向けsplit構成では、同一composite内のmainをJIS、subをUSとして扱うcustom INFと`jis_special_us_default` routingを使う。通常キーとJIS固有キーを分け、US配列とIME controlの可否を同一視しない。

## 理由

US配列の通常入力とJIS固有入力を両立し、hostのlayout認識とVial検出条件を保つため。

## 代替案・影響

bCountryCodeだけでWindows配列を強制する案は主手段にしない。INF、interface identity、report routingの対応を保守する必要がある。

## 現状と再検討条件

既存調査は2026-06-13にsplit構成の実機確認を記録している。今回Windowsやdriverを再検証したものではなく、正式USB identityの公開可否とも別である。

USB descriptor、INF、host layout変更時はfresh enumerationとJP/US両入力、Vialを確認する。

## 根拠・関連仕様

- [docs/research/windows-split-keyboard-identity.md](../../research/windows-split-keyboard-identity.md)
- [windows-driver/README.md](../../../windows-driver/README.md)
