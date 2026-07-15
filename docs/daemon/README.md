# Daemon Docs

daemon 横断、logicd 出力経路、IPC、分割境界など daemon 実装補助文書を置きます。

daemon ごとの詳細動作仕様、実装時に守る条件、移植時の互換性 checklist は [specs/README.md](specs/README.md) を入口にします。

まず見る文書:

- [logicd-output-router.md](logicd-output-router.md): keyboard output backend と fan-out 方針
- [logicd-log-output.md](logicd-log-output.md): debug output / HID report log 確認
- [logicd-resolved-action-handler-split-design.md](logicd-resolved-action-handler-split-design.md): resolved action handler の分割境界
- [kc-sh-report-output-route-design.md](kc-sh-report-output-route-design.md): `KC_SHn` report / output route
- [native-fast-input-core-design.md](native-fast-input-core-design.md): `hidd-rs` / `logicd-core-rs` による boot-critical input path native 化案

文書一覧:

- [kc-sh-report-output-route-design.md](kc-sh-report-output-route-design.md)
- [logicd-log-output.md](logicd-log-output.md)
- [logicd-output-router.md](logicd-output-router.md)
- [logicd-resolved-action-handler-split-design.md](logicd-resolved-action-handler-split-design.md)
- [native-fast-input-core-design.md](native-fast-input-core-design.md)

関連入口:

- [specs/README.md](specs/README.md): daemon ごとの詳細仕様、動作契約、互換性 checklist、test matrix
- [specs/implementation-risk-notes.md](specs/implementation-risk-notes.md): 過去の bug / review / progress log から起こした再発防止メモ
- `hidd-rs` M0 実装仕様: [specs/hidd/m0-implementation-spec.md](specs/hidd/m0-implementation-spec.md)
- `logicd-core-rs` M0 実装仕様: [specs/logicd-core-rs/m0-implementation-spec.md](specs/logicd-core-rs/m0-implementation-spec.md)
