# Vial advanced macro compatibility design

作成日: 2026-06-01

この文書は Vial advanced macro / QMK macro 互換を、local macro / KML / Send String と混ぜずに扱うための設計です。
2026-06-01 時点では実装へは進まず、raw Vial macro buffer、展開済み macro、runtime runner、import/export、UI 境界、テスト範囲を固定します。

## Goal

- `.vil` import/export の再現性を維持する。
- `settings.vial_macro_buffer` と local runtime macro を混同しない。
- Vial macro の未対応 command を silent に実行しない。
- KML / QMK macro compatible runner / Send String の設計と責務を分ける。
- macro 互換性を高めても、script / system / connectivity action へ勝手に拡張しない。

## Current baseline

- `.vil` import では `settings.vial_macro_buffer` と展開済み `macros` を両方保持する方針がある。
- `daemon/http/vil_macro_import.py` は Vial macro buffer decode / config update / VIAL macro expansion を扱う。
- `daemon/http/vil_apply.py` は `.vil` import 時の remap / interaction settings / macro buffer 適用を扱う。
- `logicd` の runtime macro runner は key action dispatch へつながる。

## Data owners

| data | owner | 目的 |
| --- | --- | --- |
| `settings.vial_macro_buffer` | `.vil` compatibility layer | raw Vial macro buffer の round-trip / export 再現性 |
| `macros` | local runtime config | project runtime / script 表示で使いやすい展開済み表現 |
| KML files | KML runner | KML syntax の named macro |
| QMK macro compatible files | QMK-compatible runner | text representation の QMK-like macro |
| Send String entries | Send String runner | named text snippet |

方針:

- raw buffer は互換保存用であり、runtime runner の唯一の source of truth にはしない。
- import 時に展開できる Vial macro は local `macros` へ反映する。
- 展開できない command は warning と raw buffer 保持で扱う。

## Supported compatibility layers

初期候補:

| layer | 扱い |
| --- | --- |
| Vial raw macro buffer | 保存 / export 再現性を優先 |
| Vial macro decoded summary | read-only inspector 候補 |
| local expanded macro | runtime runner 用 |
| QMK macro text | 別 runner / 別 storage |
| KML | 別 runner / 別 storage |

## Import policy

`.vil` import 時:

1. raw Vial macro buffer を `settings.vial_macro_buffer` に保持する。
2. decode 可能な macro を local `macros` へ展開する。
3. non-VIAL local macro は保持する。
4. unsupported command は warning にする。
5. raw buffer を破棄しない。

衝突時:

- `VIAL*` macro は buffer 由来で置換する。
- non-VIAL macro は保持する。
- user macro を消す場合は明示 warning を出す候補。

## Export policy

`.vil` export 時:

- raw buffer がある場合は、互換性のため raw buffer を優先する候補。
- local macro から再生成する場合は、対応 command だけに限定する。
- unsupported local macro は Vial macro として export しないか warning にする。
- export 後に import し直しても macro buffer が壊れないことをテスト候補にする。

## Runtime execution policy

- Runtime は expanded local macro を実行する。
- raw Vial macro buffer をそのまま実行しない。
- unsupported command は no-op ではなく validation warning にする。
- shell script / system / connectivity action は Vial advanced macro 互換の初期対象外にする。
- Send String / Unicode を呼ぶ場合は [input/unicode-send-string-safety-design.md](../input/unicode-send-string-safety-design.md) の cancel path に従う。

## UI policy

HTTP:

- Vial macro raw buffer summary を read-only に表示する候補。
- expanded local macro と raw Vial macro buffer の両方が存在することを分かるようにする。
- unsupported command warning を表示する。
- raw buffer を直接編集する UI は初期実装では作らない。

Vial / `.vil`:

- `.vil` round-trip を優先する。
- Vial custom keycode 64 枠とは別問題として扱う。
- unknown user action がある場合は warning を出す。

## Relation to other macro features

| feature | 境界 |
| --- | --- |
| KML / QMK macro keycode | file-based / named runner。Vial raw buffer とは分ける。 |
| Dynamic Macro | runtime memory だけ。Vial macro buffer とは分ける。 |
| Send String | text runner。Vial macro buffer の owner ではない。 |
| Script editor | shell script runner。Vial advanced macro 互換には含めない。 |

## Safety policy

- raw buffer を実行 source にしない。
- unsupported command を silent に無視しない。
- system / connectivity / power action を Vial macro compatibility へ自動変換しない。
- import/export で local non-VIAL macro を意図せず削除しない。
- runtime cancel path は output switch / reload / emergency release とつなげる。

## Static tests to add with implementation

設計 first slice では doc test だけを追加する。
実装へ進む場合は以下を追加する。

- import で `settings.vial_macro_buffer` が保持される。
- decode 可能な Vial macro が local `macros` へ展開される。
- non-VIAL macro が import 後も保持される。
- unsupported command warning が出る。
- export で raw buffer round-trip が壊れない。
- raw Vial macro buffer を runtime runner が直接実行しない。
- system / connectivity / power action を自動変換しない。

## 2026-06-10 boundary groundwork

`daemon/logicd/macro_integration.py` の `vial_macro_boundary()` で、Vial raw macro buffer と
expanded local macro の owner 境界を read-only metadata として固定した。

完了した範囲:

- `settings.vial_macro_buffer` は import/export source。
- runtime source は expanded local macros。
- raw Vial macro buffer は executable ではない。
- system / connectivity / power action へ自動変換しない。
- `KML(name)` / `QMK_MACRO(name)` の lookup / validation / dry-run plan と、Vial raw buffer source を分ける。

未実装のまま残す範囲:

- `.vil` advanced macro command の完全互換。
- 実 Vial macro buffer 互換確認。
- Vial custom keycode 64 枠の再設計。

## Implementation gate

実装へ進める条件:

- raw buffer と expanded macro の source of truth が分けられている。
- unsupported command warning の schema が決まっている。
- `.vil` round-trip のテストが作れる。
- KML / QMK macro / Send String との境界が保てる。

実装しない条件:

- raw Vial macro buffer を唯一の runtime source にする必要がある。
- shell script / system action を Vial macro compatibility に含める必要がある。
- Vial custom keycode 64 枠の再設計と同時でないと成立しない。
