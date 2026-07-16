# docs

HIDloom の詳細ドキュメント置き場です。
トップ README は概要と導入、`docs/` は現在地、仕様、設計、実機確認、調査メモを扱います。

導入方式の選択は [../INSTALL.md](../INSTALL.md) を参照してください。

## まず見る入口

| 目的 | ファイル |
|---|---|
| プロジェクト概要と導入 | [../README.md](../README.md) |
| Raspberry Pi OS package / Buildroot image の選択 | [../INSTALL.md](../INSTALL.md) |
| 実機失敗パターンの検出、復旧、回帰確認 | [ops/failure-patterns.md](ops/failure-patterns.md) |
| release bundle / Debian package の build、deploy、verify、rollback | [ops/release-packaging-runbook.md](ops/release-packaging-runbook.md) |
| daemon ごとの詳細仕様、実装時に守る条件、移植時 checklist | [daemon/specs/README.md](daemon/specs/README.md) |
| Zero / Zero 2 向け runtime profile 方針 | [../config/profiles/README.md](../config/profiles/README.md) |
| テストと helper の棚卸し | [ops/test-script-inventory.md](ops/test-script-inventory.md) |
| Buildroot / fast boot 実験計画 | [ops/buildroot-fast-boot-experiment.md](ops/buildroot-fast-boot-experiment.md) |
| daemon とデータフローの全体像 | [architecture/system-overview.md](architecture/system-overview.md) / [architecture/system-overview.svg](architecture/system-overview.svg) |

完了済みロードマップや古い進捗ログはprivate workspaceのarchiveへ移し、public exportには同期しません。

## root の役割

private workspaceのroot直下に置く`.md`は、次に読む人の入口として常に見える必要がある5文書に限定します。
public exportでは内部進捗4文書を除外し、`README.md`だけを同期します。

| ファイル | 内容 |
|---|---|
| [README.md](README.md) | `docs/` 全体の索引 |

root に残す理由と新規文書の配置ルールは [policy/documentation-policy.md](policy/documentation-policy.md) を参照してください。

## 分類別入口

個別文書の網羅一覧は、各カテゴリの `README.md` に置きます。
`docs/README.md` は入口と分類表に留めます。

| 分類 | 入口 |
|---|---|
| 全体仕様・アーキテクチャ | [architecture/README.md](architecture/README.md) |
| 方針・決定事項 | [policy/README.md](policy/README.md) |
| daemon / IPC | [daemon/README.md](daemon/README.md) |
| Bluetooth / BLE | [bluetooth/README.md](bluetooth/README.md) |
| connectivity / host identity | [connectivity/README.md](connectivity/README.md) |
| feature design | [feature/README.md](feature/README.md) |
| hardware / board / matrix | [hardware/README.md](hardware/README.md) |
| HID extension | [hid/README.md](hid/README.md) |
| input / IME | [input/README.md](input/README.md) |
| interaction UI | [interaction/README.md](interaction/README.md) |
| keycode compatibility | [keycode/README.md](keycode/README.md) |
| lighting / LED / OLED | [lighting/README.md](lighting/README.md) |
| macro | [macro/README.md](macro/README.md) |
| manual pages | [man/README.md](man/README.md) |
| MIDI / audio | [midi/README.md](midi/README.md) |
| Morse | [morse/README.md](morse/README.md) |
| ops / verification | [ops/README.md](ops/README.md) |
| research | [research/README.md](research/README.md) |
| Vial / VIL | [vial/README.md](vial/README.md) |

## 外部 daemon README

daemon 固有の利用説明は各 daemon directory の README に残します。

| daemon | README |
|---|---|
| matrixd | [../daemon/matrixd/README.md](../daemon/matrixd/README.md) |
| logicd | [../daemon/logicd/README.md](../daemon/logicd/README.md) |
| usbd | [../daemon/usbd/README.md](../daemon/usbd/README.md) |
| viald | [../daemon/viald/README.md](../daemon/viald/README.md) |
| httpd | [../daemon/http/README.md](../daemon/http/README.md) |
| i2cd | [../daemon/i2cd/README.md](../daemon/i2cd/README.md) |
| ledd | [../daemon/ledd/README.md](../daemon/ledd/README.md) |
| btd | [../daemon/btd/README.md](../daemon/btd/README.md) |
| spid | [../daemon/spid/README.md](../daemon/spid/README.md) |
| sessiond | [../daemon/sessiond/README.md](../daemon/sessiond/README.md) |
