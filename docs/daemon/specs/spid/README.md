# spid Detailed Spec

`spid` は SPI 接続 sensor、特に motion / direction 系 input を扱う daemon です。pointer / gesture 系の入力は key event と異なるため、sampling、scale、zero state、disconnect を明確にします。

## 役割

- SPI sensor を初期化し、motion / direction event を生成する。
- logicd が扱える形へ sensor output を整形する。
- sensor error / calibration state を診断可能にする。

## 非役割

- keymap action 解決は `logicd` の責務。
- HID mouse report の最終送出は output route 側の責務。

## 所有するリソース

- 実装: `daemon/spid/`
- sensor plan: [mouse-sensor-plan.md](mouse-sensor-plan.md)
- 入力: SPI sensor read
- 出力: motion / direction event、diagnostic log

## 実装時に守る条件

- sensor missing 時に daemon が無限 crash loop しない。
- zero motion と disconnect を区別する。
- scale / axis inversion を変更する場合、host-visible cursor movement の互換性を記録する。
- high-rate sampling が CPU を占有しない。
- slow client が broadcast を詰まらせないよう、client 数や writer buffer を監視できるようにする。
- mouse motion を logicd / HID report へ流す時は、押下中 button bit を `buttons=0` で消さない。

## テスト観点

- sensor missing。
- zero motion。
- axis direction。
- high-rate movement。
- mouse button drag with motion。
- slow client / multiple clients。

## 関連文書

- [mouse-sensor-plan.md](mouse-sensor-plan.md): PAW3805EK、環境変数、socket event、実機確認履歴。
- [../../../hardware/paw3805ek-mounted-cursor-settings-design.md](../../../hardware/paw3805ek-mounted-cursor-settings-design.md): mounted cursor / settings UI 側の設計。
