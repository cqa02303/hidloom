# Autocorrect safety design

作成日: 2026-06-01

この文書は QMK Autocorrect 相当の安全設計です。
2026-06-08 に default-off の `daemon/logicd/autocorrect.py` runtime first slice を追加し、
辞書形式、trigger / replacement owner、host IME / layout 依存、Send String との境界、キャンセル条件を固定しました。
live HID dispatch と Send String runner への接続はまだ行いません。

## Goal

- 誤入力補正を、IME や host layout を壊さない範囲で扱う。
- replacement 実行を中断可能にする。
- Unicode / Send String runner と責務を分ける。
- Caps Word / Repeat Key / Mod-Morph など既存 interaction と衝突しない境界を固定する。

## Current baseline

- Caps Word は runtime 初期実装済みで、英字入力中の Shift 合成を扱う。
- Repeat Key は直前 action 履歴を持つが、入力文字列全体の履歴 owner ではない。
- Unicode / Send String は [unicode-send-string-safety-design.md](unicode-send-string-safety-design.md) で、host mode / runner cancel / storage 境界を設計済み。
- host IME state と host layout は自動検出しない。
- Autocorrect runtime first slice は `AutocorrectRuntime` と `validate_autocorrect_settings()` として実装済み。

## Scope

初期対象候補:

- ASCII lower-case word correction。
- word boundary が明確な英単語だけ。
- correction dictionary は user-editable だが、小さく始める。
- replacement は `backspace N + send string` 方式を候補にする。

初期対象外:

- 日本語 IME 変換中の補正。
- host layout 自動判定。
- Unicode replacement。
- context-aware grammar correction。
- application-specific behavior。

## Dictionary shape

候補:

```json
{
  "settings": {
    "autocorrect": {
      "enabled": false,
      "mode": "ascii_words",
      "max_word_length": 32,
      "entries": {
        "teh": "the",
        "adn": "and"
      }
    }
  }
}
```

方針:

- default は `enabled=false`。
- trigger / replacement は短い ASCII word から始める。
- trigger は lower-case 正規化候補。
- replacement は keymap action ではなく text として扱う。
- 大文字小文字維持、Unicode、記号混在は後続。
- dictionary import/export は最初から version field を持たせる候補。

## Runtime owner

候補 owner は `InteractionEngine` または専用 `AutocorrectEngine`。
first slice は専用 helper の `AutocorrectRuntime` に閉じ、live dispatch adapter は未接続にする。

方針:

- key output の最終 tap action から word buffer を構築する。
- raw matrix position ではなく resolved action を見る。
- modifier wrapper / Caps Word / Key Override 後の最終 action を対象にする。
- Repeat Key の履歴 owner とは分ける。
- buffer は永続化しない。

## Correction flow

1. repeatable / printable ASCII action が出力されたら word buffer に追加する。
2. boundary key が出たら、word buffer を dictionary で照合する。
3. hit したら、入力済み文字数分の `KC_BSPC` を送る。
4. replacement text を Send String runner または tap sequence で送る。
5. boundary key を通常通り送るか、先に送った boundary を戻さない設計にするかを固定する。

初期案:

- boundary key は correction 判定後に送る。
- correction 中は新しい matrix event を queue するか、キャンセルするかを実装前に固定する。
- replacement は Send String runner の cancel path を使う。

## Boundary keys

候補:

- space
- enter
- tab
- punctuation
- layer switch / output switch / reload は buffer clear

Backspace / Delete:

- word buffer から 1 文字消す候補。
- host 側の実入力とずれる可能性があるため、初期は simple delete だけに限定する。

## Safety policy

キャンセル / clear 条件:

- output switch
- config reload
- keymap reload
- emergency release / stuck-key recovery
- daemon shutdown
- layer reset
- non-printable action
- mouse / consumer / system / connectivity / power action

制限:

- default disabled。
- max word length を設ける。
- replacement length 上限を設ける。
- control character / newline replacement は初期禁止。
- Unicode replacement は初期禁止。
- IME 変換中かどうかは検出できないため、日本語入力中の利用は非推奨。

## UI policy

HTTP:

- 初期は read-only validation / dictionary preview から始める。
- enable toggle は明示 warning を出す。
- dictionary editor は too long / non-ASCII warning を出す。
- import/export は versioned JSON とする。

OLED:

- 常時表示はしない。
- correction applied / canceled を短い alert にする候補。

LED:

- 専用 overlay は作らない。

## Relation to other features

| feature | 境界 |
| --- | --- |
| Caps Word | Caps Word は Shift 合成。Autocorrect は word buffer / replacement。owner を混ぜない。 |
| Repeat Key | Repeat history には correction の internal Backspace sequence を残さない。 |
| Send String | replacement 実行に使う候補。storage / dictionary owner は Autocorrect 側。 |
| KML / QMK macro | macro から Autocorrect dictionary を直接編集しない。 |
| Host profile | Autocorrect enable / dictionary は host profile に将来紐づける候補。ただし自動 OS detection はしない。 |

## Static tests with implementation

`script/test_autocorrect_runtime.py` で runtime first slice を固定する。

- [x] dictionary validation: ASCII、length、empty replacement 相当の lower-case word 制約。
- [x] default disabled。
- [x] printable ASCII action だけが word buffer に入る。
- [x] system / connectivity / mouse / consumer action で buffer clear。
- [x] boundary key で correction 判定する。
- [x] replacement は internal `KC_BSPC` + ASCII tap sequence + boundary tap として作る。
- [x] Send String storage と Autocorrect dictionary を混ぜない。
- [ ] replacement 中の output switch / reload / emergency release で cancel。
- [ ] Repeat Key history に internal Backspace sequence を保存しない。

## Implementation gate

runtime first slice で満たした条件:

- ASCII-only dictionary validation が固定できる。
- correction flow と boundary key の順序をテストで固定できる。
- IME / host layout 非対応を UI warning として出せる。

live dispatch へ進める条件:

- Send String runner の cancel path が設計済みである。
- output switch / config reload / emergency release と queue cancel の接続を固定できる。
- Repeat Key / Dynamic Macro history に internal Backspace sequence を残さない adapter test を置ける。

実装しない条件:

- 日本語 IME 変換中の補正が必須になる。
- host layout 自動判定が必須になる。
- Unicode replacement を初期要件に入れる必要がある。
