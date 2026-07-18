# ドキュメント分割方針

README 本体はプロジェクトの入口として扱い、詳細な機能説明は `docs/` 配下へ分割する。

## README 方針

- README には概要、全体構成、最短導入方法、主要機能、詳細リンクだけを書く
- 長い手順、プロトコル詳細、デバッグ手順、設計メモは README に直書きしない
- README から詳細ドキュメントへリンクする
- 新機能を追加するときは、必要なら実装と同じ PR で `docs/` を追加・更新する

## 詳細ドキュメント方針

- 新規の詳細文書は、できるだけ `docs/<category>/` または `docs/<component>-<feature>.md` の形にする
- daemon ごとの利用説明は、必要に応じて各ディレクトリの `README.md` に置く
- `docs/README.md` は root 入口とカテゴリ別入口に留め、個別文書の網羅一覧はカテゴリ README に置く
- `docs/<category>/README.md` はカテゴリ入口として維持し、`まず見る文書` と `文書一覧` を置く
- `docs/<category>/` に `.md` を追加・移動した時は、同じ変更でカテゴリ `README.md` の `文書一覧` を実ファイル一覧と一致させる
- `TODO_PRIORITY.md` は現在の作業入口として薄く保ち、日付付きの完了履歴や長い経緯は `CURRENT_STATUS.md` または `docs/archive/` へ移す
- `WISHLIST.md` は未確定案だけを置き、受け入れ条件が書けるものは TODO / 専用設計文書へ移す

## 概要・使い方・設定と詳細仕様の分離

概要、使い方、設定方法は、実装の細かい条件や動作契約とは分けて置く。
読む人が「動かすために読む文書」と「移植・実装で条件を落とさないために読む文書」を迷わない状態を維持する。

| 情報 | 置き場所 | 例 |
|---|---|---|
| daemon の役割、起動方法、簡単な設定例、開発者向け入口 | `daemon/<name>/README.md` | `daemon/logicd/README.md` |
| daemon の詳細動作、互換条件、異常系、field / protocol contract、移植 checklist | `docs/daemon/specs/<name>/` | `docs/daemon/specs/logicd/behavior-contract.md` |
| daemon 横断の設計、段階移行計画、責務分割 | `docs/daemon/` | `docs/daemon/native-fast-input-core-design.md` |
| 実機での操作手順、systemd 操作、検証 runbook、host 観測手順 | `docs/ops/` | `docs/ops/real-device-test-checklist.md` |
| 設定ファイル形式の厳密な意味、JSON field の許容値、互換 fallback | 該当 daemon / feature の詳細仕様 | `docs/daemon/specs/logicd-core-rs/m0-implementation-spec.md` |
| UI / 機能の利用者向けふるまい、feature design | `docs/feature/` などの機能カテゴリ | `docs/feature/sequence-engine-design.md` |

`daemon/<name>/README.md` が長くなった場合は、起動・設定・最短確認だけを残し、条件、例外、protocol、test matrix は `docs/daemon/specs/<name>/` へ移す。
逆に `docs/daemon/specs/<name>/` には「まず何を起動すればよいか」だけの運用手順を重複させず、必要なら `daemon/<name>/README.md` または `docs/ops/` へリンクする。

## root に残す文書

`docs/` root の `.md` は、次に読む人の入口として常に見える必要があるものだけにする。

| 文書 | root に残す理由 |
|---|---|
| `README.md` | `docs/` 全体の索引 |
| `CURRENT_STATUS.md` | 現在地、直近の完了、次に見るもの |
| `TODO_PRIORITY.md` | 実装・検証することが決まっている残作業の入口 |
| `WISHLIST.md` | まだ TODO 昇格前の将来案 |
| `REORG_PROGRESS.md` | docs 整理の移動履歴、完了判定、検査入口 |

設計詳細、仕様、方針、調査、日付付き進捗、実機確認手順は root に置かず、該当カテゴリへ置く。

## 配置カテゴリ

| 配置 | 用途 |
|---|---|
| `docs/` root | `README.md`、`CURRENT_STATUS.md`、`TODO_PRIORITY.md`、`WISHLIST.md`、`REORG_PROGRESS.md` |
| `docs/architecture/` | 全体仕様、system overview、module structure、single source architecture |
| `docs/policy/` | 決定済み方針、docs 運用方針、logging / status 表示方針 |
| `docs/research/` | 調査メモ、仕様・外部挙動の確認結果、TODO 昇格前の判断材料 |
| `docs/review/` | 現行判断へつながる横断レビュー、design gap review |
| `docs/hardware/` | board profile、配線、matrix 座標、touch-panel layout note |
| `docs/bluetooth/` | Bluetooth / BLE HID / Bluetooth host profile 関連 |
| `docs/lighting/` | LED / OLED / VialRGB / Lighting tab / semantic role 関連 |
| `docs/daemon/` | daemon 横断、logicd 出力経路、IPC、分割境界など daemon 実装補助文書 |
| `docs/daemon/specs/` | daemon ごとの詳細動作仕様、互換条件、移植 checklist、test matrix |
| `docs/feature/` | Interaction、host profile、power preset など複数 daemon にまたがる feature design |
| `docs/gallery/` | project-authored hardware、Web UI、touch panelの公開画像とカテゴリ別入口 |
| `docs/macro/` | KML / QMK macro / Vial macro / Dynamic Macro の互換性と runner 設計 |
| `docs/man/` | package に同梱する man page source。詳細仕様は各カテゴリへリンクする |
| `docs/midi/` | MIDI / audio output / sequencer integration 関連 |
| `docs/hid/` | Mouse / System Control / Digitizer など HID report extension 関連 |
| `docs/keycode/` | QMK / Vial keycode completion、alias、translation、runtime suppression 関連 |
| `docs/input/` | Unicode / Send String、Autocorrect、touch-panel flick など host input / IME 関連 |
| `docs/connectivity/` | Wi-Fi / USB host identity / host-facing connectivity profile 関連 |
| `docs/morse/` | Morse runtime behavior、HTTP route、UI progression 関連 |
| `docs/vial/` | Vial protocol / viald architecture / .vil import policy 関連 |
| `docs/ops/` | 作業手順、実機確認、テスト棚卸し、性能測定計画など運用文書 |
| `docs/interaction/` | Interaction tab / builder UX / interaction UI 計画 |
| `docs/archive/` | 古い状態メモ、長い履歴、通常入口から外した文書 |
| `docs/archive/bugs/` | 完了済みの bug record |
| `docs/archive/progress/` | 完了済みの日付付き監査メモ、first slice 横断まとめ、進捗整理 |
| `docs/archive/review/` | 完了済みの横断レビュー、導入レビュー、実装境界レビュー |
| `docs/<daemon>/` | daemon 固有の補助文書を今後増やす場合の候補。既存 daemon README は各 daemon directory に残す |
| `docs/<feature-family>/` | 大きな feature family をさらに分ける場合の候補。既存 `*_DESIGN.md` は段階移動する |

新規文書の prefix 目安:

- `research/<topic>.md`: host OS / upstream / hardware 仕様などの調査
- `archive/progress/<topic>-YYYY-MM-DD.md`: 完了済みの日付付き監査、横断進捗、作業整理
- `archive/review/<topic>-YYYY-MM-DD.md`: 完了済みの横断レビューや境界レビュー
- `review/<topic>-YYYY-MM-DD.md`: 日付付きの横断レビューや境界レビュー
- `<daemon>-<topic>.md`: daemon 固有の設計や IPC
- `<feature>-<topic>.md`: 複数 daemon にまたがる feature
- `<hardware>-<topic>.md`: board、matrix、sensor、配線

## コードコメント方針

実装コードにも、後から読み返して設計意図が分かるコメントを残す。

特に次のような箇所ではコメントを必須に近い扱いにする。

- 複数方式を同じインターフェイスに揃える場所
- 既存互換のために古い経路を残している場所
- 将来差し替える前提の stub / adapter / backend
- Raspberry Pi 実機状態、USB、Bluetooth、GPIO、uinput など外部状態に依存する処理
- 一見すると冗長に見えるが、切り分けや安全性のために必要な処理

コメントには、できるだけ以下を含める。

- なぜその設計にしているか
- 共通インターフェイスは何か
- どこを差し替えれば拡張できるか
- 既存挙動との互換性をどう保っているか

ただし、処理をそのまま日本語に言い換えるだけのコメントは避ける。

## ファイル名の目安

```text
docs/daemon/logicd-output-router.md
docs/daemon/logicd-log-output.md
docs/daemon/logicd-ipc-protocol.md
docs/daemon/logicd-runtime-keymap.md
docs/daemon/specs/matrixd/charlieplex-scan.md
docs/bluetooth/hid.md
```

## カテゴリ README 更新

カテゴリ README は、各フォルダに入った時の短い入口として扱う。

- `まず見る文書`: 代表的な 2-5 件を用途つきで置く
- `文書一覧`: 同じフォルダの `README.md` 以外の `.md` をすべてリンクし、カテゴリ外の文書は混ぜない
- カテゴリ外の関連文書が必要な場合は `関連文書` / `関連進捗` のような別見出しへ分ける
- 詳細な説明は各文書へ残し、カテゴリ README は索引以上に肥大化させない
- `script/test_docs_reorg.py` で root 直下の許可リスト、カテゴリ README の存在、`まず見る文書` のカテゴリ内リンク、`文書一覧` と実ファイル一覧の完全一致を確認する

`docs/README.md` はカテゴリ README への案内役とし、個別文書をすべて列挙しない。
個別文書への導線が必要な test / docs は、該当カテゴリ README を確認対象にする。

## Public export

private repository内の配置規則と、public repositoryへ同期する文書境界は分けて管理する。
日々の進捗、内部review、実機個別証跡、credential運用、private開発host固有手順はprivate側に保持し、
public exportへ含めない。詳細と検証入口は
[Public Documentation Boundary](../ops/public-documentation-boundary.md)を参照する。

次回作業入口、operator workflow、host別handoff、完了済みの日付付きprogress / status / auditは
private-onlyとする。恒久的なarchitecture、仕様、再現runbookへ昇格する場合は、sessionやhostに依存しない
内容とfilenameへ整理してから公開対象へ戻す。

公開対象文書からprivate文書を参照する必要がある場合、export後にbroken linkを残さない。
意図的な除外先はplain textへ変換し、未知の欠落targetは公開blockerにする。
公開root `README.md`を唯一のnavigation rootとし、全`docs/**/*.md`がMarkdown linkを辿って
到達できる状態を維持する。directory linkは配下の`README.md`へ解決し、code fence内の例示linkは
navigationとして数えない。broken linkがなくても孤立文書があれば公開blockerにする。

## 目的

- README の肥大化を防ぐ
- 機能単位で読みやすくする
- 実装、デバッグ、運用の情報を探しやすくする
- Raspberry Pi 実機作業中に必要なページだけ参照できるようにする
- コードの設計意図と拡張ポイントを失わないようにする
