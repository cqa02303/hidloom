# logicd Detailed Spec

`logicd` は matrix input を key action に解決し、HID / Bluetooth / LED / status / script / session 系へ出力する中心 daemon です。移植や機能追加で条件漏れが起きやすいため、この directory では「実装を差し替えても維持する動作契約」を細かく記録します。

## 役割

- matrix event を keymap、layer、modifier、macro、feature state に基づいて resolved action へ変換する。
- press / release の対応関係を保持し、release 時に press 時の解決結果を参照する。
- output router を通じて HID、Bluetooth、script、session、LED 通知などへ出力を配送する。
- runtime state、status、diagnostic log を他 daemon / HTTP UI から参照できる形にする。
- keymap reload、runtime control、host profile、feature toggle を受け付ける。

## 非役割

- 物理 matrix scan は `matrixd` の責務。
- USB gadget descriptor の構築は `hidd` / `usbd` / gadget helper の責務。
- Vial protocol の host-facing 互換処理は `viald` の責務。
- BLE advertising / GATT 実体は `btd` の責務。

## 所有するリソース

- Python 実装: `daemon/logicd/`
- native 計画: `docs/daemon/specs/logicd-core-rs/m0-implementation-spec.md`
- 主な入力: matrix event stream、control socket、config / keymap JSON、host LED output、spid motion / direction
- 主な出力: HID report broker、Bluetooth sender、LED notification、status API、script / session output
- 状態: active layer、pressed key resolution、modifier state、macro state、feature state、host profile state

## 起動順序

- `matrixd` からの入力が未接続でも、`logicd` は起動し、再接続可能状態を維持する。
- HID / Bluetooth / LED の出力先が未接続でも、key resolution 本体は停止しない。
- 起動直後は keymap と runtime default を読み、読み込み失敗時は安全側に倒す。安全側とは、未知 action を送出しないこと、押下状態を残さないこと、停止理由をログに残すこと。
- native `logicd-core-rs` を併用する段階では、Python `logicd` と Rust core の責務境界を明示し、同じ入力を二重送出しない。

## 入力

- matrix event は press / release の順序を保持して扱う。
- release が先行した場合、未対応 release として no-op にし、押下状態を捏造しない。
- keymap / config JSON は未知 field の扱いを文書化し、既存 UI / Vial import が出す field を壊さない。
- control request は validation し、失敗時は daemon を落とさず error response / log に残す。

## 出力

- HID 出力は report 種別ごとの route を維持する。
- output route が未接続の場合、既存方針に従って drop / retry / reconnect を区別する。
- press に対応する release は、release 時点の layer ではなく press 時に確定した action を基準にする。
- 同じ physical key の repeat / macro / layer action が混在する場合、状態遷移を `behavior-contract.md` に追記する。

## 関連文書

- [behavior-contract.md](behavior-contract.md)
- [compatibility-checklist.md](compatibility-checklist.md)
- [test-matrix.md](test-matrix.md)
- [../../../daemon/logicd-output-router.md](../../logicd-output-router.md)
- [../logicd-core-rs/m0-implementation-spec.md](../logicd-core-rs/m0-implementation-spec.md)

## 既知の課題

- Rust core 投入後の Python fallback 境界は、段階ごとに `logicd-core-rs` 側の仕様へ反映する。
- 複雑な JSON 定義をどこまで Rust 側で解釈するかは、互換性 checklist と test-matrix を先に埋めてから切る。
