# QMK/Vial Keycode Support Status

作成日: 2026-05-17

この資料は、QMK/Vial で定義・利用される代表的なキーコード群に対して、
HIDloom がどこまで対応しているかを整理したものです。

参照元:

- QMK Basic Keycodes: https://docs.qmk.fm/keycodes_basic
- QMK Keycodes Overview: https://docs.qmk.fm/keycodes
- QMK Quantum Keycodes: https://docs.qmk.fm/quantum_keycodes
- QMK One Shot Keys: https://docs.qmk.fm/one_shot_keys
- QMK Magic Keycodes: https://docs.qmk.fm/keycodes_magic
- QMK MIDI: https://docs.qmk.fm/features/midi
- QMK Unicode: https://docs.qmk.fm/features/unicode
- QMK Audio: https://docs.qmk.fm/features/audio
- Vial Custom Keycode: https://get.vial.today/docs/custom_keycode.html

## 判定基準

| 状態 | 意味 |
| --- | --- |
| 対応済み | HTTP/Vial/API から割り当て可能で、logicd が期待する出力または内部動作を実行できる |
| 一部対応 | 内部実装はあるが、QMK/Vial 名・UI表示・全alias・全variantまでは揃っていない |
| 未対応 | action として保存できても logicd/viald が QMK と同等の意味で処理できない、または保存時点で想定していない |
| 対象外寄り | QMKファームウェア内機能に強く依存し、このRaspberry Pi実装では直接の対応価値が低い |

## 現在の対応入口

| 入口 | 対応内容 |
| --- | --- |
| `config/default/keycodes.json` | 通常HID Keyboard Page、Consumer Control、マウス、独自 `KC_SHn` などの action 定義 |
| `daemon/logicd/macro.py` | `KC_*` 実行、Consumer Control、Mouse HID、スクリプトキー、出力先切替 |
| `daemon/logicd/keymap.py` | レイヤ解決、`MO(n)`、`TG(n)`、`TO(n)`、`DF(n)` |
| `daemon/viald/keycode_codec.py` | Vial keycode と内部 action 文字列の変換 |
| `daemon/http/static/keyboard.js` | HTTPキーコード変更UIの候補表示 |
| `config/default/vial.json` | Vial GUI 用 custom keycode 表示 |

## 対応済み・一部対応

| グループ | 状態 | 主な対応済みキー | 備考 |
| --- | --- | --- | --- |
| 基本英数字 | 対応済み | `KC_A`-`KC_Z`, `KC_1`-`KC_0` | USB HID Keyboard Page として `/dev/hidg0` または uinput へ出力 |
| 基本記号・制御 | 一部対応 | `KC_ENTER`, `KC_ESC`, `KC_BSPC`, `KC_TAB`, `KC_SPACE`, `KC_MINUS`, `KC_EQUAL`, `KC_LBRC`, `KC_RBRC`, `KC_BSLS`, `KC_SCLN`, `KC_QUOT`, `KC_GRV`, `KC_COMM`, `KC_DOT`, `KC_SLSH` | QMKの全alias名までは未網羅。例: `KC_LEFT_BRACKET` は未定義で `KC_LBRACKET` を使用 |
| Fキー | 対応済み | `KC_F1`-`KC_F24` | HTTP UI では `F13-F24` も候補表示 |
| 修飾キー | 対応済み | `KC_LCTL`, `KC_LSFT`, `KC_LALT`, `KC_LGUI`, `KC_RCTL`, `KC_RSFT`, `KC_RALT`, `KC_RGUI` | 基本modifierとして対応 |
| Navigation / Editing | 一部対応 | `KC_PSCR`, `KC_PAUS`, `KC_INS`, `KC_HOME`, `KC_PGUP`, `KC_DEL`, `KC_END`, `KC_PGDN`, `KC_LEFT`, `KC_DOWN`, `KC_UP`, `KC_RGHT`, `KC_UNDO`, `KC_CUT`, `KC_COPY`, `KC_PASTE`, `KC_FIND`, `KC_EXECUTE`, `KC_HELP`, `KC_MENU`, `KC_SELECT`, `KC_STOP`, `KC_AGAIN`, `KC_SYSTEM_REQUEST`, `KC_CANCEL`, `KC_CLEAR`, `KC_CRSEL`, `KC_EXSEL` | `KC_SYSTEM_REQUEST` は単独 Keyboard Page usage として対応済み。host 入力欄では単独押下が可視文字を出さないことを確認済み。host OS の SysRq modifier 組み合わせ動作は実機確認待ち |
| テンキー | 一部対応 | `KC_KP_SLASH`, `KC_KP_ASTERISK`, `KC_KP_MINUS`, `KC_KP_PLUS`, `KC_KP_ENTER`, `KC_KP_0`-`KC_KP_9`, `KC_KP_DOT`, `KC_KP_EQUAL`, `KC_KP_COMMA`, `KC_KP_EQUAL_AS400` | その他 keypad extras は必要時に個別棚卸し |
| International / Language | 一部対応 | `KC_INT1`-`KC_INT9`, `KC_LANG1`-`KC_LANG9`, `KC_LANGUAGE_6`-`KC_LANGUAGE_9`, `KC_RO`, `KC_KANA`, `KC_JYEN`, `KC_HENKAN`, `KC_MUHENKAN` | USB gadget と BLE GATT の keyboard report descriptor は 8-bit Keyboard/Keypad usage (`0x00`-`0xFF`) を許可し、International / Language 系も report 上は送れる。Windows helperless 通常 UX は `KC_LANG1` / `KC_LANG2` の ImeOn/ImeOff に固定し、dedicated `KC_HENKAN` / `KC_MUHENKAN` は通常採用しない。US sub keyboard interface / `0x87`-`0x98` route は別 OS 確認用に残す。Raw HID / custom HID receiver は診断用に限定する。`KC_LANG6`-`KC_LANG9` は 2026-06-07 second slice で USB HID usage として追加済み。Linux fallback は `linux=null` |
| Consumer / Media | 対応済み | `KC_MUTE`, `KC_VOLU`, `KC_VOLD`, `KC_MNXT`, `KC_MPRV`, `KC_MSTP`, `KC_MPLY`, `KC_MSEL`, `KC_EJCT`, `KC_MAIL`, `KC_CALC`, `KC_MYCM`, `KC_WSCH`, `KC_WHOM`, `KC_WBAK`, `KC_WFWD`, `KC_WSTP`, `KC_WREF`, `KC_WFAV`, `KC_MFFD`, `KC_MRWD`, `KC_BRIU`, `KC_BRID` | `/dev/hidg0` Consumer Control report ID 3 へ出力。HTTP UI は主要 media / brightness 候補を表示 |
| Keyboard Page の音量キー | 互換対応 | `KC_KB_MUTE`, `KC_KB_VOLUME_UP`, `KC_KB_VOLUME_DOWN` | PCで有効だった Consumer Control へ内部alias変換する互換キー |
| Mouse Keys | 一部対応 | `KC_MS_U`, `KC_MS_D`, `KC_MS_L`, `KC_MS_R`, `MS_UP`, `MS_DOWN`, `MS_LEFT`, `MS_RGHT`, `KC_BTN1`-`KC_BTN5`, `MS_BTN1`-`MS_BTN5`, `KC_WH_U`, `KC_WH_D`, `KC_WH_L`, `KC_WH_R`, `MS_WHLU`, `MS_WHLD`, `MS_WHLL`, `MS_WHLR`, `MS_ACL0`-`MS_ACL2` | QMK alias は既存 `KC_MS_*` / `KC_WH_*` / `KC_BTN*` へ変換する。加速度キーは key-driven cursor / wheel profile として対応済み。Button 6-8 は未対応 |
| Layer Switching | 一部対応 | `MO(layer)`, `TG(layer)`, `TO(layer)`, `DF(layer)`, `OSL(layer)`, `TT(layer)`, `LT(layer,kc)`, `KC_TRNS`, `KC_NONE` | `MO/TG/DF/OSL/TT/LT` は 0-31、`TO` は Vial codec 上 0-15 を扱える。HTTP UI の `LT` は現在編集中のレイヤー以外の `LT(n)` を先に選び、次に `KC_*` タップキーを選ぶ。`DF` は runtime 中のみで永続化しない |
| Modifier / Tap-Hold | 一部対応 | `MT(mod,kc)`, `SC_LSPO`, `SC_RSPC`, modifier wrapper (`S(KC_1)` など) | InteractionEngine で tap/hold を処理する。wrapper は validation と macro/keymap action として扱えるが、全QMK alias名の網羅は未対応 |
| RGB / VialRGB | 一部対応 | `RGB_TOG`, `RGB_MOD`, `RGB_RMOD`, `RGB_HUI`, `RGB_HUD`, `RGB_SAI`, `RGB_SAD`, `RGB_VAI`, `RGB_VAD`, `RGB_SPI`, `RGB_SPD`, `RM_ON`, `RM_OFF`, `RM_TOGG`, `RM_NEXT`, `RM_PREV`, `RM_HUEU`, `RM_HUED`, `RM_SATU`, `RM_SATD`, `RM_VALU`, `RM_VALD`, `RM_SPDU`, `RM_SPDD` | VialRGB状態変更として実装。QMKのBacklight/LED Matrix全体とは別物 |
| 独自スクリプトキー | 対応済み | `KC_SH0`-`KC_SH10` | Vial custom keycode と HTTP UI のスクリプトタブで扱う |
| 独自システムキー | 対応済み | `KC_CONNAUTO`, `KC_CONSOLE`, `KC_USB`, `KC_BT`, `KC_SHUTDOWN` | 出力先切替、シャットダウンなどローカル独自動作 |
| ローカルMacro/Unicode | 一部対応 | `MACRO:name`, `U+XXXX`, KML | QMK `UC(c)` / `UM(i)` / Vial Macro とは別実装 |

## 未対応キーコード群

### 1. Basic Keycodes の未対応

| グループ | 代表キー | 現状 | 実装メモ |
| --- | --- | --- | --- |
| Locking keys | `KC_LOCKING_CAPS_LOCK`, `KC_LOCKING_NUM_LOCK`, `KC_LOCKING_SCROLL_LOCK` | 対応済み | 2026-06-07 third slice で USB HID usage / Vial codec / HTTP picker へ追加済み。通常 Caps / Num / Scroll とは別 key として扱う |
| Command keys | `KC_EXECUTE`, `KC_HELP`, `KC_MENU`, `KC_SELECT`, `KC_STOP`, `KC_AGAIN`, `KC_ALTERNATE_ERASE`, `KC_SYSTEM_REQUEST`, `KC_CANCEL`, `KC_CLEAR`, `KC_PRIOR`, `KC_SEPARATOR`, `KC_OUT`, `KC_OPER`, `KC_CLEAR_AGAIN`, `KC_CRSEL`, `KC_EXSEL` | 一部対応済み | 2026-06-07 first/fourth slice で USB HID usage / Vial codec / HTTP picker へ追加済み。Linux uinput fallback は keycode が曖昧なため `linux=null`。`KC_SYSTEM_REQUEST` 単独押下は host 入力欄で可視文字を出さないことを確認済み。host OS SysRq modifier 組み合わせ動作は実機確認待ち。`KC_RETURN` は canonical alias で `KC_ENTER` に寄せる |
| Language 6-9 | `KC_LANGUAGE_6`-`KC_LANGUAGE_9` | 対応済み | 2026-06-07 second slice で USB HID usage / Vial codec / HTTP picker へ追加済み。Linux uinput fallback は `linux=null` |
| System control | `KC_SYSTEM_POWER`, `KC_SYSTEM_SLEEP`, `KC_SYSTEM_WAKE` | 設計TODOへ昇格 | Generic Desktop Page の別reportが必要。System control / programmable HID report design で扱う |
| QMK shifted aliases | `KC_EXLM`, `KC_AT`, `KC_HASH`, `KC_DLR`, `KC_PLUS`, `KC_PIPE`, `KC_COLN`, `KC_DQUO`, `KC_LT`, `KC_GT`, `KC_QUES` など | 方針整理済み | 個別 alias の網羅ではなく、内部action表現 `S(KC_1)` などの modifier wrapper を正とする。必要なalias追加はwishlist扱い |
| Layout extras | `JP_*`, `DE_*`, `FR_*` など | 設計TODOへ昇格 | QMKの言語別alias群。Basic HID keycode completion design と host profile design で扱う |

### 2. Layer Switching の未対応

| キー | 状態 | 実装メモ |
| --- | --- | --- |
| `PDF(layer)` | 設計TODOへ昇格 | 永続保存先の設計が必要。Layer / one-shot completion design で扱う |
| `TT(layer)` | 対応済み | tap は toggle、hold は momentary として InteractionEngine で処理する |
| `OSL(layer)` | 対応済み | Vial/QMK の one-shot layer keycode として decode / encode する |
| `LM(layer, mod)` | 設計TODOへ昇格 | layer + modifierの同時押下状態管理が必要。Layer / one-shot completion design で扱う |
| `LT(layer, kc)` | 対応済み | tap/hold判定は InteractionEngine で処理する。HTTP UI は `LT(n)` -> tap key の2段階選択で `LT(n,KC_*)` を保存する |
| `QK_LAYER_LOCK` / `QK_LLCK` | 設計TODOへ昇格 | [feature/layer-lock-design.md](../feature/layer-lock-design.md) で state owner と解除条件を設計済み。Layer / one-shot completion design で実装入口を固定する |

残る layer 系の主な未対応は `PDF(layer)`、`LM(layer, mod)`、`QK_LAYER_LOCK` / `QK_LLCK` です。

### 3. Modifier / Mod-Tap / Tap-Hold 系

| グループ | 代表キー | 状態 | 実装メモ |
| --- | --- | --- | --- |
| Modifier wrapper | `LCTL(kc)`, `LSFT(kc)`, `LALT(kc)`, `LGUI(kc)`, `RCTL(kc)`, `HYPR(kc)`, `MEH(kc)` | 設計TODOへ昇格 | `S(KC_1)` など wrapper action は validation で扱う。alias 網羅は QMK alias completion design で扱う |
| Mod-Tap | `MT(mod,kc)`, `LCTL_T(kc)`, `LSFT_T(kc)`, `LALT_T(kc)`, `LGUI_T(kc)` など | 設計TODOへ昇格 | `MT(mod,kc)` 基本形を InteractionEngine で処理する。QMK alias completion design で alias 方針を固定する |
| Space Cadet | `SC_LSPO`, `SC_RSPC`, `SC_SENT` など | 設計TODOへ昇格 | `SC_LSPO` / `SC_RSPC` は対応済み。その他は QMK alias completion design で扱う |
| One Shot Modifiers | `OSM(mod)`, `OS_LCTL`, `OS_LSFT`, `OS_LALT`, `OS_LGUI` など | 設計TODOへ昇格 | sticky 状態表示は [feature/sticky-state-status-design.md](../feature/sticky-state-status-design.md) で設計済み。modifier 実装は Layer / one-shot completion design で扱う |

### 4. Mouse Keys の未対応

| キー | 状態 | 実装メモ |
| --- | --- | --- |
| `MS_BTN1`-`MS_BTN5` | 対応済み | 2026-06-07 に既存 `KC_BTN1`-`KC_BTN5` と同じ 5-button Mouse HID report usage へ alias 接続済み |
| `MS_BTN6`-`MS_BTN8` | 設計TODOへ昇格 | Mouse HID report のbutton bit拡張が必要。Mouse HID extension design で扱う |
| `MS_ACL0`-`MS_ACL2` | 対応済み first slice | 2026-06-07 に logicd key-driven cursor / wheel profile、Vial v5 `253`-`255`、HTTP keycode payload へ追加済み |

### 5. Backlight / LED Matrix / RGB Matrix

| グループ | 代表キー | 状態 | 実装メモ |
| --- | --- | --- | --- |
| Backlight | `BL_TOGG`, `BL_UP`, `BL_DOWN`, `BL_STEP`, `BL_ON`, `BL_OFF` | 設計TODOへ昇格 | 現在のLEDは `ledd` / VialRGB 管理で、QMK Backlightとは別モデル。Lighting key alias compatibility design で扱う |
| LED Matrix | `LM_ON`, `LM_OFF`, `LM_TOGG`, `LM_NEXT`, `LM_PREV`, `LM_BRIU`, `LM_BRID`, `LM_SPDU`, `LM_SPDD`, `LM_FLGN`, `LM_FLGP` | 設計TODOへ昇格 | `RM_*` とは別名。Lighting key alias compatibility design で alias 方針を固定する |
| RGB Matrix / RGB Light追加alias | `RGB_MODE_*`, `RGB_TOGGLE`, `RM_TOG`, など一部長名 | 設計TODOへ昇格 | logicd側は一部aliasあり。HTTP/Vial UI候補は Lighting key alias compatibility design で整理する |

### 6. Audio / MIDI

| グループ | 代表キー | 状態 | 実装メモ |
| --- | --- | --- | --- |
| QMK Audio | `AU_ON`, `AU_OFF`, `AU_TOGG`, `CK_TOGG`, `CK_ON`, `CK_OFF`, `CK_UP`, `CK_DOWN`, `MU_ON`, `MU_OFF`, `MU_TOGG`, `MU_NEXT`, `MU_PREV` | 設計TODOへ昇格 | QMKの基板上ブザー/スピーカー機能。Raspberry Pi側で音を出すなら MIDI / Audio output design と hardware ports design で扱う |
| MIDI | `MI_ON`, `MI_OFF`, `MI_TOGG`, `MI_C`, `MI_Cs`, `MI_OCTU`, `MI_OCTD`, `MI_CHNU`, `MI_CHND`, `MI_AOFF`, `MI_SUST`, `MI_MOD`, `MI_BNDU` など | 設計TODOへ昇格 | USB MIDI gadgetやALSA MIDI出力を追加するなら MIDI / Audio output design で扱う |

### 7. Magic / Boot / Debug / EEPROM

| グループ | 代表キー | 状態 | 実装メモ |
| --- | --- | --- | --- |
| Boot/Debug | `QK_BOOT`, `QK_RBT`, `DB_TOGG`, `EE_CLR`, `QK_MAKE` | 設計TODOへ昇格 | QMK firmwareのビルド/ブートローダ/EEPROM前提。Pi実装では意味が異なるため action mapping design で扱う |
| Magic | `CL_SWAP`, `CL_NORM`, `EC_SWAP`, `CG_SWAP`, `AG_SWAP`, `NK_ON`, `NK_OFF`, `NK_TOGG`, `EH_LEFT`, `EH_RGHT` | 設計TODOへ昇格 | runtime key translation layerを持てば一部可能。Boot / Debug / EEPROM action mapping design と host profile design で扱う |

### 8. Macro / Dynamic Macro / Leader / Tap Dance / Combo / Key Override

| グループ | 代表キー | 状態 | 実装メモ |
| --- | --- | --- | --- |
| QMK Macro | `QK_MACRO_*` 系 | 一部対応 | Vial Macro buffer を `settings.vial_macro_buffer` に保持し、`M0`-`M7` を `MACRO:VIAL0`-`MACRO:VIAL7` として実行する。text / tap / down / up / delay は実行用 token へ変換する |
| Dynamic Macro | `DM_REC1`, `DM_REC2`, `DM_RSTP`, `DM_PLY1`, `DM_PLY2` | runtime-only groundwork 完了 | `daemon/logicd/dynamic_macro_leader.py` が 2 slot buffer、record filter、playback re-entry guard、cancel boundary を固定済み。実 HID 送信と実キー体感確認は未実装 |
| Key Toggle / Key Lock | `KEY_TOGGLE(kc)`, `KEY_LOCK(kc)`, `DRAG_LOCK` | 設計TODOへ昇格 | QMK 互換名ではなく local interaction 候補。[feature/key-toggle-lock-design.md](../feature/key-toggle-lock-design.md) で synthetic source 分離と全解除を設計済み |
| Mod-Morph / Grave Escape | `GRAVE_ESCAPE`, `MOD_MORPH(name)` | 設計TODOへ昇格 | local interaction preset 候補。[feature/mod-morph-grave-escape-design.md](../feature/mod-morph-grave-escape-design.md) で Key Override との境界を設計済み |
| Leader | `QK_LEAD` | runtime-only groundwork 完了 | Leader settings validation、default disabled、pending / match / timeout / cancel を固定済み。live InteractionEngine 接続は未実装 |
| Tap Dance | `TD(n)` | 一部対応 | Vial標準 `TD(0)`-`TD(255)` を `TD(TD0)` 形式へdecode/encodeする。Vial Tap Danceタブの `On tap` / `On hold` / `On double tap` / `On tap + hold` / term は `settings.interaction.tap_dances` に保存する。QMKの関数型Tap Danceまでは未対応 |
| Combo | compile-time combo定義 | 一部対応 | Vial Comboタブの keycode 組み合わせを layer 0 の matrix 座標へ逆引きし、`settings.interaction.combos` に保存する。layer 0 に存在しない keycode や layer依存のQMK互換までは未対応 |
| Key Override | `ko_*` 設定で発火 | 対応済み first slice | Vial Key Overridesタブの required modifier + negative modifier + trigger key + replacement key + layer mask + option flags を `settings.interaction.key_overrides` に保存する。2026-06-05 に runtime suppression first slice を追加し、trigger action を replacement press 前に一時 release、replacement release 後に必要なら restore する |
| QMK Settings | runtime settings | 一部対応 | Vial QMK Settingsタブの Combo Term / Tapping Term / Hold On Other Key Press を `settings.interaction` に保存する |
| Repeat Key | `QK_REPEAT_KEY`, `QK_ALT_REPEAT_KEY` | 初期対応 | [feature/repeat-key-design.md](../feature/repeat-key-design.md) に沿って runtime history と対象外 action allowlist を実装済み。追加 pair / UI 表示は follow-up |
| Caps Word / Autocorrect | `CW_TOGG` 等 | 一部対応 | Caps Word は [feature/caps-word-design.md](../feature/caps-word-design.md) に沿って初期実装済み。Autocorrect は safety design へ昇格済み |

### 9. Unicode

| グループ | 代表キー | 状態 | 実装メモ |
| --- | --- | --- | --- |
| QMK Unicode | `UC(c)`, `UM(i)`, `UP(i,j)` | read-only groundwork 完了 | `daemon/logicd/qmk_unicode.py` が unicode map validation と action plan preview を固定済み。実 HID 送信は real runner と host profile gate が安定してから扱う |
| Unicode mode | `UC_NEXT`, `UC_PREV`, `UC_MAC`, `UC_LINX`, `UC_WIN`, `UC_WINC`, `UC_EMAC` | read-only groundwork 完了 | `UC_LINX` / `UC_WIN` / `UC_WINC` は preview-only、unsupported / cycle action は blocking reason を返す。永続 mode mutation は未実装 |
| ローカル `U+XXXX` | 一部対応 | `daemon/logicd/macro.py` の独自action | QMK互換ではなく、Windows Unicode入力寄りのローカル機能 |

### 10. Joystick / Programmable Button / Hardware固有

| グループ | 代表キー | 状態 | 実装メモ |
| --- | --- | --- | --- |
| Joystick buttons | `JS_0`-`JS_31` | 設計TODOへ昇格 | 本プロジェクトにはanalog joystick入力はあるが、QMK Joystick HID出力キーコードではない。System control / programmable HID report design で扱う |
| Programmable Button | `PB_1` など | 設計TODOへ昇格 | HID report descriptor追加が必要。System control / programmable HID report design で扱う |
| Digitizer / Haptic / Sequencer / Steno | 各feature固有キー | 設計TODOへ昇格 | 専用HIDや専用サブシステムが必要。feature design で対象候補 / 対象外を固定する |

## Vial固有の扱い

VialはQMK keycodeをGUIで選ぶための層であり、独自キーは `vial.json` の
`customKeycodes` によって名前を付けて表示できます。

現在対応済み:

- `KC_SH0`-`KC_SH10`
- `KC_CONNAUTO`
- `KC_CONSOLE`
- `KC_USB`
- `KC_BT`
- `BT_STATUS`, `BT_POWER_*`, `BT_PAIRING_*`, `BT_DISCONNECT`, `BT_FORGET_DEVICE`
- `OSL(0)`-`OSL(31)`
- `LT(2,KC_A)`, `MT(KC_LSFT,KC_A)`, `TT(2)`, `TD(TD0)`
- `KC_SHUTDOWN`

注意点:

- Vial GUI は `USER00`-`USER63` までの custom keycode を解決するため、`customKeycodes` は64件以内に保つ。
- `KC_CONNAUTO` / `KC_USB` / `KC_BT` と `OSL(0)`-`OSL(31)` は標準値も decode するが、現在の Vial GUI では raw 表示になりやすいため custom USER 表示を優先する。
- `LT(2,KC_A)`, `MT(KC_LSFT,KC_A)`, `TT(2)`, `TD(TD0)` は実機確認用の固定 custom 候補として扱う。
- `RGB_*` / `RM_*` は USER custom 枠ではなく Vial/QMK の lighting keycode として扱う。
- Vial GUIに表示できても、`logicd` が処理しなければ動作しません。
- 逆にHTTPで動く独自actionでも、Vial keycode codecに登録しなければVialからは扱えません。
- QMK/Vialの標準外IDを追加する場合は、Vial GUIでの表示を期待せず、HTTP/独自仕様として管理する方針が現実的です。

## 実装優先度案

| 優先度 | 対象 | 理由 |
| --- | --- | --- |
| 高 | `OSL(layer)` | レイヤ運用で自然に欲しくなり、既存 `LayerManager` に近いが解除タイミングの仕様決めが必要 |
| 中 | `LT(layer,kc)`, `MT(mod,kc)`, `TT(layer)` | QMKらしい操作性だがtap-hold基盤が必要 |
| 中 | shifted aliases (`KC_EXLM`, `KC_PLUS` 等) | QMK keymap移植性が上がる。modifier wrapper設計とセット |
| 中 | Mouse buttons 6-8 | report bit / descriptor 拡張が必要。Mouse HID extension design で扱う |
| 低 | Magic, Boot, EEPROM, QK_MAKE | QMK firmware前提でPi実装との意味が薄い |
| 低 | Joystick HID | 別HID gadget/descriptor設計が必要。MIDI / Audio は設計TODOへ昇格済み |

## 直近TODO候補

未実装 keycode の運用リストは [unimplemented-keycodes.md](unimplemented-keycodes.md) に集約します。
直近の実装TODOは private workspace reference *(omitted from public export)* に置き、ここに残る未対応群は
設計TODOへ紐付け済みの棚卸しとして扱います。
