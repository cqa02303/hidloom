# matrixd Detailed Spec

`matrixd` は物理 key matrix を scan し、debounce 済みの key state change を上位へ渡す daemon です。上位の `logicd` が正しくても、scan ordering、debounce、座標対応が崩れると入力全体が壊れるため、移植時の条件をここに固定します。

## 役割

- board profile / matrix 配線に従って row / column を scan する。
- chattering を debounce し、安定した press / release event のみを出す。
- physical position と logical key position の対応を維持する。
- scan latency / missed scan / unstable key の診断材料を残す。

## 非役割

- keymap、layer、macro、HID report 変換は `logicd` の責務。
- host への HID 送信は `hidd` / `usbd` / output route の責務。
- LED 表示や OLED 表示の意味付けは `ledd` / `i2cd` の責務。

## 所有するリソース

- 実装: `daemon/matrixd/`
- 主な関連文書: [stability-docs.md](stability-docs.md)
- 入力: GPIO / board profile / scan configuration
- 出力: matrix event stream、scan diagnostic
- 状態: current stable key state、debounce candidate、scan timing

## 起動順序

- hardware 初期化失敗時は、壊れた event を出さずに失敗理由をログへ残す。
- `logicd` が未接続でも scan 本体は開始できるか、少なくとも再接続可能な待機状態を維持する。
- 起動直後の全 key state は安全側に初期化する。押下中 key を検出する場合は、初回 event の扱いを明記する。

## 入力

- GPIO read の一時的な揺れは debounce window 内で確定しない。
- board profile の row / column / diode direction を取り違えない。
- scan interval を変更する場合、debounce time と latency の関係を test-matrix に記録する。

## 出力

- 同じ physical transition から press / release を重複生成しない。
- press と release の順序を逆転させない。
- coordinate は keymap 側が期待する logical coordinate と一致させる。
- 異常 scan を検知した場合、上位へ不正 event を渡すより diagnostic に残す。

## 関連文書

- [behavior-contract.md](behavior-contract.md)
- [compatibility-checklist.md](compatibility-checklist.md)
- [test-matrix.md](test-matrix.md)
- [real-device-stability-checklist.md](real-device-stability-checklist.md)
- [../../../hardware/keyswitch-matrix-map.md](../../../hardware/keyswitch-matrix-map.md)

追加仕様 / 履歴:

- [stability-docs.md](stability-docs.md): matrixd stability cluster の索引。
- [scan-stability-plan.md](scan-stability-plan.md): scan debounce / settle / reconnect 安定化計画。
- [runtime-priority-ideal.md](runtime-priority-ideal.md): matrixd / logicd runtime priority。
- [input-latency-instrumentation-design.md](input-latency-instrumentation-design.md): matrix input latency instrumentation。
- [scanner-abstraction-design.md](scanner-abstraction-design.md): scanner abstraction / row-column design。

## 既知の課題

- scan 高速化や C / Rust 化の際、latency 改善と debounce 安定性の両方を測る必要がある。
- 実機ごとの差は board profile / hardware docs とリンクして残す。
