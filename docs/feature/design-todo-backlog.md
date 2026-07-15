# Design TODO backlog

更新日: 2026-07-15

この文書は、公開ソースで追跡する設計判断と、実装を追加する前に維持すべき安全境界の索引です。
完了履歴やprivate workspaceの進捗記録は含めません。現在、未完了の受け入れchecklistはありません。

新しい機能候補は、対応する個別設計文書、回帰test、実機確認条件が揃ってからここへ追加します。
QMK/Vial互換の対象外・後送り項目は
[keycode/unimplemented-keycodes.md](../keycode/unimplemented-keycodes.md)を参照してください。

## 現在の設計TODO

### Sequence engine / timed interaction unification design

詳細は [feature/sequence-engine-design.md](sequence-engine-design.md) にあります。
外部action名と保存payloadを変えず、Morse、Tap Dance、Tap-Holdの共通安全境界だけを整理します。

受け入れ条件:

- [x] `SequenceEmission`のordering ruleとhost-visible / feedback境界を固定する。
- [x] press / release owner を固定し、press時に選んだactionをreleaseする。
- [x] suppress / restore accounting を固定し、複数featureが同じsource actionを扱えるようにする。
- [x] timer generationとstale timeout防止を共通化する。
- [x] feedback separation を固定し、feedback eventをHID dispatchへ混ぜない。
- [x] compatibility guard を固定し、`MORSE(name)`、`TD(name)`、`LT`、`MT`、`TT`と保存payloadを維持する。

### KML / QMK macro keycode integration design

first slice は `KML(name)` / `QMK_MACRO(name)` の runtime action 名だけにし、
slot mappingが確定するまで`KC_KMLn` / `KC_QMn`は追加しません。
詳細は[macro/compatibility-plan.md](../macro/compatibility-plan.md)と
[macro/kml-qmk-macro-keycode-design.md](../macro/kml-qmk-macro-keycode-design.md)にあります。
parser test、runner test、keycode dispatch test、配置優先順位 testで境界を固定します。

### Morse romaji composition planning design

touch flick composition planと同じread-only `romaji_us_ime`境界で扱い、host IME ownerを
keyboard側へ移しません。`MORSE(name)` の runtime は 1 sequence = 1 actionのまま維持し、
fallback / force_commit / feedbackとVial import-exportの外部挙動を変えません。
実機なしで coverage と blocking reasonを確認し、実送信は touch flick composition と同じく
text-send safety gateが揃ってから扱います。

## 完了済み設計判断

### Persistent Wi-Fi off setting design

radio無効化はrecovery-firstとし、復旧経路を失う変更をkeyboard hot pathから実行しません。

### Bluetooth host last connected timestamp design

接続観測とlocal rename metadata routeを分離し、host表示名を接続判定のidentityに使いません。

### Caps Word feedback / status design

runtime状態、解除条件、OLED/LED feedbackの責務境界を
[caps-word-design.md](caps-word-design.md)へ固定済みです。

### Power management preset implementation readiness

radio、display、serviceの変更は独立した確認対象とし、適用前snapshotと復旧手順を必須にします。

## 公開実装へ追加しない境界

- 設計だけでruntime dispatch、descriptor、Vial codecを追加しない。
- 未実装backendや選択肢だけのCLI/configを追加しない。
- host依存keycodeを互換確認なしでcanonical actionへ追加しない。
- 実機専用機能はdefault disabledとし、rollbackとhealth snapshotを先に定義する。
- public sourceから参照できない内部進捗文書を根拠にしない。
