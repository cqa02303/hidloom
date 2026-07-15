# Daemon Detailed Specs

daemon の機能追加、移植、native 化で落としてはいけない条件を記録する場所です。

ここに置く文書は「実装の説明」だけではなく、実装を差し替えても維持する動作契約、互換性条件、テスト観点を明文化します。特に Python から C / Rust へ移植する場合、既存挙動との差分を `migration-notes.md` または各 daemon の README に残します。

## 使い分け

| 場所 | 役割 |
|---|---|
| `daemon/<name>/README.md` | 開発者向けの入口、起動方法、ファイル構成、簡易利用説明 |
| `docs/daemon/specs/<name>/README.md` | daemon の詳細動作仕様、守る条件、異常系、確認項目 |
| `docs/daemon/specs/<name>/behavior-contract.md` | 実装を変えても維持する細かい動作条件 |
| `docs/daemon/specs/<name>/compatibility-checklist.md` | 移植、機能追加、protocol 変更時の漏れ防止 checklist |
| `docs/daemon/specs/<name>/test-matrix.md` | unit / smoke / 実機 / fault injection の確認表 |
| `docs/daemon/specs/<name>/m0-implementation-spec.md` | native 化や置き換え M0 の実装仕様、promotion 条件、検証履歴 |
| `docs/daemon/*.md` | daemon 横断設計、移行計画、native 化の段階設計 |

## daemon 別入口

| daemon / service | 詳細仕様 |
|---|---|
| `matrixd` | [matrixd/README.md](matrixd/README.md) |
| `logicd` | [logicd/README.md](logicd/README.md) |
| `logicd-core-rs` | [logicd-core-rs/README.md](logicd-core-rs/README.md) |
| `outputd` / `hidloom-outputd` | [outputd/README.md](outputd/README.md) |
| `hidd` / `hidloom-hidd` | [hidd/README.md](hidd/README.md) |
| `uidd` / `hidloom-uidd` | [uidd/README.md](uidd/README.md) |
| `usb-gadget-fast` | [usb-gadget-fast/README.md](usb-gadget-fast/README.md) |
| `usbd` | [usbd/README.md](usbd/README.md) |
| `viald` | [viald/README.md](viald/README.md) |
| `httpd` | [httpd/README.md](httpd/README.md) |
| `i2cd` | [i2cd/README.md](i2cd/README.md) |
| `ledd` | [ledd/README.md](ledd/README.md) |
| `btd` | [btd/README.md](btd/README.md) |
| `spid` | [spid/README.md](spid/README.md) |
| `sessiond` | [sessiond/README.md](sessiond/README.md) |
| boot service helpers | [service-helpers/README.md](service-helpers/README.md) |

## 横断の再発防止メモ

- [implementation-risk-notes.md](implementation-risk-notes.md): 過去の bug record、review、progress log から起こした、移植・機能追加時に落としてはいけない注意点

## 標準章立て

新しい daemon 仕様を追加する時は、[_template.md](_template.md)を複製して章の欠落を防ぎます。

各 daemon の README は、できるだけ次の章を維持します。

- 役割
- 非役割
- 所有するリソース
- 起動順序
- 入力
- 出力
- IPC / API
- 設定
- 状態管理
- ログ / 診断
- 異常系とリトライ
- 終了処理
- 実装時に守る条件
- 移植時に維持する互換性
- テスト観点
- 既知の課題

## 書き方の原則

- 「適切に処理する」ではなく、観測可能な条件として書く。
- press / release / repeat / timeout / reconnect のように、時系列で壊れやすい条件を分けて書く。
- JSON / socket / status など外部 contract は、field 名、許容値、不明 field の扱いを明記する。
- 依存 daemon が未起動、再起動中、古い実装の場合の fallback を明記する。
- 実機でのみ確認できる項目は、作業を止める理由にせず `実機確認待ち` として test-matrix に残す。
