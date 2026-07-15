# viald Detailed Spec

`viald` は Vial / VIL 互換 protocol と keymap 操作を扱う daemon です。外部 tool から見える protocol 互換性を壊さないことを最重要条件にします。

## 役割

- Vial / VIL protocol request を解釈する。
- keymap、dynamic keycode、lighting protocol などの互換処理を提供する。
- logicd / config store へ安全に反映できる request に変換する。

## 非役割

- matrix scan や HID report 送出は行わない。
- UI 表示そのものは `httpd` の責務。

## 所有するリソース

- 実装: `daemon/viald/`
- architecture: [architecture.md](architecture.md)
- 入力: Vial / VIL request
- 出力: response、keymap update、logicd control

## 実装時に守る条件

- upstream Vial が期待する command ID / payload length / response を壊さない。
- unsupported command は誤成功にしない。
- keymap 更新は validation 後に適用する。
- logicd 反映に失敗した場合、永続 store と runtime state の不一致を診断できるようにする。
- `conf/vial.json` / board profile layout / HTTP layout の物理配置をずらさない。
- `/mnt/p3/keymap.json` が repo default より優先される実機では、Vial 表示の判断に runtime keymap の有無を含める。
- Raw HID endpoint の report length / interface identity を descriptor 変更の副作用で壊さない。

## テスト観点

- known command response。
- unsupported command。
- VIL import / export。
- keymap update 後の logicd reload。
- board profile layout と HTTP layout の一致。
- runtime keymap present / absent の表示差。

## 関連文書

- [architecture.md](architecture.md): `hidloom-hidd` / `viald` / `logicd` / `ledd` の責務分離、Raw HID endpoint、VialRGB 統合方針。
- [../../../vial/implementation-plan.md](../../../vial/implementation-plan.md): Vial 対応の実装計画。
- [../../../vial/vil-import-policy.md](../../../vial/vil-import-policy.md): `.vil` import policy。
