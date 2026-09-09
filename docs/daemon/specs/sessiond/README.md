# sessiond Detailed Spec

`sessiond` は PTY terminal mirror / session bridge を扱う daemon です。keyboard input path と terminal output path が交差するため、control sequence、session ownership、disconnect の扱いを明確にします。

## 役割

- PTY session を作成し、logicd / UI から参照できる terminal mirror を提供する。
- text output / command session の lifecycle を管理する。
- session status を diagnostic 可能にする。

## 非役割

- key action の解決は `logicd` の責務。
- web UI rendering は `httpd` / frontend の責務。

## 所有するリソース

- 実装: `daemon/sessiond/`
- 詳細設計: [pty-terminal-mirror-design.md](pty-terminal-mirror-design.md)
- 実装メモ: [pty-terminal-mirror-implementation-notes.md](pty-terminal-mirror-implementation-notes.md)
- 入力: session control、PTY output
- 出力: mirrored terminal stream、status

## 実装時に守る条件

- session owner を一意にする。
- PTY close / process exit を UI が区別できる形で伝える。
- `active` はprocess実行中だけでなくPTY出力のdrain中もtrueとする。補助field `process_active` と `draining` で状態を区別し、PTY EOFとUTF-8 decoderの末尾処理が終わるまで完了を通知しない。
- 自然終了時は最後のtextをinactiveより先に配送し、logicd側の送信queueもdrainする。明示的なstop・escape・interruptでは従来どおり残りの送信をcancelする。
- control sequence を壊さない。
- runaway output で input daemon を阻害しない。
- high-volume PTY output は HID / text send 経路を詰まらせないよう chunking / cancellation 方針を維持する。
- receiver focus や Windows Terminal 側状態の問題を Pi 側 PTY failure と混同しない。

## テスト観点

- session create / close。
- process exit。
- high-volume output。
- 大量出力直後のprocess終了、UTF-8境界をまたぐ末尾、自然終了後のclient queue drain (`script/test_sessiond_output_drain.py`)。
- logicd client reconnect。
- HID text transport focus / receiver unavailable。

## 関連文書

- [pty-terminal-mirror-design.md](pty-terminal-mirror-design.md): PTY terminal mirror の責務境界、IPC、loop guard、host layout 条件。
- [pty-terminal-mirror-implementation-notes.md](pty-terminal-mirror-implementation-notes.md): 実装 slice ごとの仮決めと確認履歴。
- [../../../ops/pty-terminal-mirror-smoke.md](../../../ops/pty-terminal-mirror-smoke.md): no-HID / manual socket / 実機 smoke 手順。
