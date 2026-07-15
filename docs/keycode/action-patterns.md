# Action pattern inventory

この文書は、`config/default/keycodes.json` に全件列挙されない action 文字列の構文一覧です。
固定 keycode 名の完全表は [action-inventory.md](action-inventory.md)、
分類・出力 route の読み方は [action-routing-matrix.md](action-routing-matrix.md) を参照します。

## Pattern 一覧

| pattern | 例 | 分類 | logicd 処理 | logicd-core-rs | host へ直接送るか | 出力先扱い | 注意点 |
|---|---|---|---|---|---|---|---|
| `MO(n)` | `MO(1)` | layer control | press で momentary layer on、release で off | M0 対象 | 送らない | local state | `n` は通常 0-31。押下中 key の release 整合を保つ |
| `TG(n)` | `TG(2)` | layer control | tap で layer toggle | M0 対象 | 送らない | local state | toggle 後の active layer と stuck key を確認する |
| `TO(n)` | `TO(0)` | layer control | default を含む active layer を切替 | M0 対象 | 送らない | local state | Vial codec は 0-15、HTTP validation は 0-31 を扱う箇所があるため境界を確認する |
| `DF(n)` | `DF(1)` | layer control | runtime default layer を変更 | M0 対象 | 送らない | local state | 永続 default ではなく runtime state として扱う |
| `OSL(n)` | `OSL(2)` | layer control | one-shot layer を arm し、次の non-layer action で消費 | M0 対象 | 送らない | local state | `KC_NONE` / layer action では消費しない |
| `TT(n)` | `TT(2)` | tap-hold / layer | tap は `TG(n)`、hold は `MO(n)` | delegated | 解決後 action を送る | local state | timeout / interrupt 条件を `LT` と混同しない |
| `LT(n,kc)` | `LT(2,KC_A)` | tap-hold / layer | tap は `kc`、hold は `MO(n)` | delegated | 解決後 action を送る | tap 側は各 output route | tap 側に `KC_NONE` / `KC_TRNS` / script 系を入れない |
| `MT(mod,kc)` | `MT(KC_LSFT,KC_A)` | tap-hold / modifier | tap は `kc`、hold は modifier | delegated | 解決後 action を送る | tap / hold とも keyboard route | `mod` alias 正規化と release 順序を維持する |
| modifier wrapper | `S(KC_1)`, `C(KC_ENTER)`, `LCTL(KC_A)` | expand | modifier press + inner action へ展開 | delegated | 展開後 action を送る | inner action の route | wrapper 自体を HID usage として扱わない |
| nested modifier wrapper | `LCTL(S(KC_A))` | expand | outer から順に modifier を押し、inner を処理 | delegated | 展開後 action を送る | inner action の route | release 順序を逆順に保つ |
| `TD(name)` | `TD(TD0)` | tap dance | runtime definition から tap / hold / double tap を解決 | delegated | 解決後 action を送る | resolved action の route | unknown name は no-op ではなく未解決として扱う |
| `MORSE(name)` | `MORSE(main)` | sequence | Morse runtime が sequence を action へ解決 | delegated | 解決後 action を送る | resolved action の route | feedback emission と host-visible emission を分ける |
| `MACRO:name` | `MACRO:VIAL0`, `MACRO:hello` | macro | macro token sequence へ展開 | delegated | 展開後 action を送る | token ごとの route | Vial macro ID と local macro 名の codec 境界を保つ |
| `TEXT(name)` | `TEXT(kana_a)` | text send | named text entry を text-send plan へ変換 | delegated | plan 次第 | active output keyboard | preview / preflight / real send を分ける |
| `SEND_STRING(...)` | `SEND_STRING("ABC")` | text send / macro | QMK macro compatible runner が text token として扱う | delegated | plan 次第 | active output keyboard | host layout 依存。直接 HID string ではない |
| `U+XXXX` | `U+3042` | unicode text | local Unicode action / text-send plan | delegated | plan 次第 | active output keyboard | real send は host profile gate を通す |
| `UC(...)` | `UC(3042)` | QMK Unicode | preview / blocking reason | delegated | 送らない | preview | QMK Unicode mode の real runner が安定するまで preview-only |
| `UM(i)` / `UP(i,j)` | `UM(0)` | QMK Unicode map | unicode map から preview plan | delegated | 送らない | preview | map validation と mode gate を維持する |
| `M0`-`M31` | `M0` | Vial macro shorthand | Vial macro action へ変換 | delegated | 展開後 action を送る | token ごとの route | codec では `MACRO:VIALn` と対応する |
| `KEY_TOGGLE(kc)` | `KEY_TOGGLE(KC_A)` | local interaction | key toggle / lock runtime 候補 | delegated | 解決後 action を送る | resolved action の route | synthetic source と physical source を分ける |
| `KEY_LOCK(kc)` | `KEY_LOCK(KC_A)` | local interaction | key lock state を変更 | delegated | 解決後 action を送る | resolved action の route | release-all / reload / output switch で解除する |
| `MOD_MORPH(name)` | `MOD_MORPH(grave_escape)` | local interaction | active modifier / layer 条件で置換 | delegated | 置換後 action を送る | replacement route | replacement は safe action に限定する |

## Validation 境界

| 境界 | 期待 |
|---|---|
| HTTP keymap save | safe pattern だけ保存可能。危険な system / script / raw text pattern は reject または専用 route へ分離 |
| Vial codec | Vial keycode と対応できる pattern だけ encode / decode し、対応外は `VIAL_KC_NO` |
| InteractionEngine | tap-hold / tap dance / Morse / combo / key override を resolved action へ変換 |
| Macro runner | text / tap / down / up / delay token を順に実行し、cancel 条件を維持 |
| logicd-core-rs | deterministic layer subset 以外は unsupported / delegated として観測可能にする |

## 更新ルール

- 新しい action 構文を validation へ追加したら、この文書へ pattern を追加する。
- pattern が fixed keycode 名として `config/default/keycodes.json` に入った場合は、[action-inventory.md](action-inventory.md) 側も確認する。
- host-visible output を発生させる pattern は、出力先 `usb` / `uinput` / `bt` / `auto` の扱いを [action-routing-matrix.md](action-routing-matrix.md) に反映する。
- preview-only から real send へ昇格する時は、blocking reason、host profile gate、cancel condition のテストを同時に更新する。
