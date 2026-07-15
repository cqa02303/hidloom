# Mod-Morph / Grave Escape design

更新日: 2026-06-01

この文書は Mod-Morph / Grave Escape 系 preset の設計と runtime first slice の状態をまとめます。
2026-06-01 に `logicd.mod_morph` の独立 helper と静的テストを追加し、
2026-06-05 に `InteractionEngine` の dispatch path、`settings.interaction.mod_morphs` validation、
config reload、Interaction inspector の read-only summary / conflict warning へ接続しました。

## 現在の前提

- `InteractionEngine` は currently-held action を使う Key Override を実装済み。
- modifier wrapper (`S(KC_1)` など) は action validation / macro dispatch で扱える。
- `KC_ESC` / `KC_GRV` / `KC_LSFT` など基本 key は対応済み。
- Combo / Tap Dance / Key Override inspector は read-only warning schema を設計済み。
- `logicd.mod_morph` は実装済みで、main dispatch path へ接続済み。

## Feature shape

Mod-Morph は「特定 modifier が held の時だけ別 action を出す」preset として扱います。
初期実装では汎用 editor ではなく、少数の preset / declarative rule に留めます。

実装済み候補:

- `GRAVE_ESCAPE`: built-in preset。通常時は `KC_ESC`、Shift / GUI held 中は `KC_GRV` を返す。
- `MOD_MORPH(name)`: `settings.interaction.mod_morphs[name]` 形式の named rule を参照する候補。

設定候補:

```json
{
  "settings": {
    "interaction": {
      "mod_morphs": {
        "grave_escape": {
          "trigger_mods": ["KC_LSFT", "KC_RSFT", "KC_LGUI", "KC_RGUI"],
          "default_action": "KC_ESC",
          "morphed_action": "KC_GRV",
          "layers": "all"
        }
      }
    }
  }
}
```

## Scope

first slice で扱うもの:

- caller から渡された held action set で modifier held を判定する。
- `default_action` / `morphed_action` は通常 `KC_*` keyboard action または限定的な modifier wrapper にする。
- `layers` は `all` または explicit layer list に限定する。
- `GRAVE_ESCAPE` は built-in preset として `MOD_MORPH(grave_escape)` と同じ rule を使う。
- modifier alias (`KC_LSHIFT` -> `KC_LSFT`、`KC_RWIN` -> `KC_RGUI` など) は canonicalize する。

初期実装で扱わないもの:

- arbitrary boolean expression。
- negative trigger。
- time-based morph。
- host OS / layout detection。
- script / system / connectivity / output switch action。
- mouse movement / wheel / consumer control。
- nested `MOD_MORPH(...)`。

## State owner

Mod-Morph は long-lived runtime state を持ちません。
owner は `logicd` の `InteractionEngine` です。

runtime first slice:

- `logicd.mod_morph.ModMorphConfig` が normalized rule set と validation warning を保持する。
- `resolve_mod_morph_action()` は action、held actions、active layers を受け取り、置換後 action を返す。
- helper は HID device や runtime keymap を直接変更しない。
- `InteractionEngine` は explicit Key Override を先に適用し、その後 Mod-Morph を解決する。
- press 時に解決した action を `KeyState.action` に pin し、release 側でも同じ action を返す。
- HTTP / OLED / LED は active state writer にならない。
- config reload は通常の Interaction settings validation / runtime rebuild 経路で rule を再読込する。
- output switch / emergency release で特別な state clear は不要だが、held modifier の release は既存 zero report / pressed state clear に従う。

## Relation to Key Override

Key Override:

- 汎用設定として trigger / key / replacement を持つ。
- 複数 rule、negative trigger、layer mask などの互換領域を持つ。

Mod-Morph / Grave Escape:

- 日常的に使う small preset として扱う。
- editor を複雑化させない。
- 初期実装では warning / inspector で Key Override と衝突する可能性だけ出す。
- `mod_morph_conflicts_for_key_overrides()` で、default / morphed action が Key Override 対象と重なる候補を列挙する。

優先順位:

1. Combo / Tap Dance の resolved action。
2. explicit Key Override。
3. Mod-Morph preset。
4. normal key action。

## UI policy

HTTP:

- 初期実装では preset の read-only summary と JSON editor の validation だけにする。
- graphical editor は作らない。
- conflict warning は Interaction inspector に寄せる。

OLED:

- Mod-Morph 単体の常時表示はしない。
- warning が必要な場合も config validation / HTTP 側に寄せる。

LED:

- Mod-Morph 専用 overlay は作らない。
- modifier role / key role の既存表示を使う。

## Static tests

実装済み:

- `GRAVE_ESCAPE` が通常時 `KC_ESC` を返す。
- Shift / GUI held 中の `GRAVE_ESCAPE` が `KC_GRV` を返す。
- `MOD_MORPH(grave_escape)` が built-in rule を参照する。
- custom rule の `layers` filter が効く。
- modifier alias を canonicalize する。
- safe output は plain `KC_*` と限定 wrapper に絞る。
- script / system / connectivity / output switch / layer / macro / unicode / mouse / RGB / nested Mod-Morph は reject される。
- invalid rule は skipped with warning とする。
- Key Override と同じ key にかかる conflict candidate を列挙する。

後続候補:

- 実使用で必要になった warning / preset の追加。
- Interaction inspector の duplicate warning 強化。
- Vial custom keycode alias を追加するかの判断。

## Implementation gate

実装済み first slice:

- held modifier の判定を caller-supplied held action set から取れる。
- action validation が `default_action` / `morphed_action` を安全な keyboard action に限定できる。
- Key Override との conflict candidate をテストで固定できる。
- HTTP UI を汎用 rule editor にしない前提で、small preset として扱える。
- `InteractionEngine` が existing pressed action set から held modifier を判定し、dispatch path で `GRAVE_ESCAPE` / `MOD_MORPH(name)` を解決する。
- `settings.interaction.mod_morphs` validation と config reload 経路に接続済み。
- Interaction inspector は read-only `mod_morphs` section と conflict warning を返す。

後続へ進める条件:

- 実使用で built-in 以外の preset が必要になる。
- Key Override との衝突 warning をさらに細かく出す必要がある。
- Vial / key picker 上で alias 表示が必要になる。

実装しない条件:

- host OS detection や JIS/US layout 補正が必須になる。
- arbitrary expression editor が必要になる。
- script / system / connectivity action を morph 対象に含める必要がある。
- Key Override と優先順位を分けられない。
