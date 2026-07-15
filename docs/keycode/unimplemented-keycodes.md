# Unsupported and Deferred Keycodes

更新日: 2026-07-15

この文書は、HIDloomが現在送信しないkeycode familyと、追加実装を始める前に必要な境界を示します。
現行の対応表は[qmk-vial-keycode-support.md](qmk-vial-keycode-support.md)を正本とします。

ここに名前があるだけでは、`config/default/keycodes.json`、HTTP remap、Vial codec、runtime dispatchへ
追加してはいけません。descriptor、host互換性、全解除、rollbackの受け入れ条件が揃った項目だけを
個別に実装します。

## 運用ルール

- 既存keyboard / mouse / consumer reportを変える項目は、descriptor差分とhost回帰を先に用意する。
- host配列依存aliasは、物理HID usageと入力文字を混同しない。
- local system actionはhostへHID usageとして送信しない。
- partial implementationを「対応」と表示せず、保存、runtime、出力先ごとの境界を明記する。
- 新規actionはunknown input、release-all、output切替、再起動時のstuck-state testを持つ。

## 非対応・後送り項目

### Host layout aliases

| 項目 | 代表キー | 現在の境界 |
|---|---|---|
| Layout aliases | `JP_*`, `DE_*`, `FR_*` | host layout依存。canonical HID usageまたはhost profile方針が決まるまで追加しない |
| Keypad extras | `KC_KP_COMMA`, `KC_KP_EQUAL_AS400`以外の追加alias | keyboard page usageとWindows/Linux配列差を個別確認する |

### System / programmable HID

| 項目 | 代表キー | 現在の境界 |
|---|---|---|
| System Control | `KC_SYSTEM_POWER`, `KC_SYSTEM_SLEEP`, `KC_SYSTEM_WAKE` | Generic Desktop System Control reportが必要。keyboard reportへ詰めない |
| Programmable Button | `PB_1`など | 専用report descriptorとhost support表が必要 |
| Joystick output | `JS_0`-`JS_31` | analog stick入力とは別機能。USB/BLE/uinputの出力契約が必要 |
| Digitizer / Haptic / Steno | feature固有keycode | 専用subsystemを持たないため非対応 |

### Layer / tap-hold aliases

| 項目 | 代表キー | 現在の境界 |
|---|---|---|
| Persistent default layer | `PDF(layer)` | 永続化と失敗時rollbackの契約が必要 |
| Layer with modifier | `LM(layer, mod)` | layer ownerとmodifier release順序の回帰が必要 |
| One Shot Mod aliases | `OSM(mod)`, `OS_LCTL`, `OS_LSFT` | modifier state、timeout、全解除を同じownerで扱う必要がある |
| Additional Space Cadet aliases | `SC_SENT`など | `MT`/tap-holdとの優先順位を固定してから追加する |

### Mouse / pointing

| 項目 | 代表キー | 現在の境界 |
|---|---|---|
| Mouse buttons 6-8 | `MS_BTN6`-`MS_BTN8` | USB/BLE mouse reportのbutton bit拡張とhost回帰が必要 |
| Extended pointing actions | pan、high-resolution wheel | current 4-byte mouse reportを変更するため後送り |

### Lighting

| 項目 | 代表キー | 現在の境界 |
|---|---|---|
| QMK Backlight | `BL_TOGG`, `BL_UP`, `BL_DOWN` | HIDloomの`ledd` / VialRGB modelと同義ではないため自動aliasしない |
| QMK LED Matrix | `LM_ON`, `LM_TOGG`, `LM_NEXT` | `RM_*`へ暗黙変換せず、明示的な互換表が必要 |

### Macro / text input

| 項目 | 代表キー | 現在の境界 |
|---|---|---|
| Dynamic Macro live control | `DM_REC1`, `DM_REC2`, `DM_PLY1` | buffer primitiveだけでは公開しない。record allowlistとreplay cancelが必要 |
| Leader live control | `QK_LEAD` | pending/timeout modelだけでは公開しない。InteractionEngine接続とstuck-state回帰が必要 |
| QMK Unicode | `UC(c)`, `UM(i)`, `UP(i,j)` | host-specific text runnerとIME ownershipを通す必要がある |
| Unicode mode mutation | `UC_LINX`, `UC_WIN`, `UC_WINC` | unknown hostで永続modeを変更しない方針を維持する |

### Audio / MIDI / firmware actions

| 項目 | 代表キー | 現在の境界 |
|---|---|---|
| QMK Audio / MIDI | `AU_ON`, `MI_ON`, `MI_SUST` | Pi側backendとemergency all-notes-offを設計してから追加する |
| Firmware / EEPROM | `QK_BOOT`, `QK_RBT`, `EE_CLR`, `QK_MAKE` | QMK firmware前提のためHIDloom local actionへ暗黙変換しない |
| Magic translation | `CG_SWAP`, `AG_SWAP`, `NK_TOGG` | host profileとruntime translation ownerを決めるまで追加しない |

## 追加時の同期契約

実装を追加する場合は、必要な層を同じ変更で同期します。

- `config/default/keycodes.json`
- `daemon/logicd/shared_action_defs.py`
- `daemon/http/keymap_actions.py`
- `daemon/viald/keycode_codec.py`
- `config/default/vial.json`
- `config/default/key_labels.json`
- `docs/keycode/qmk-vial-keycode-support.md`
- `script/test_shared_action_defs.py`
- `script/test_http_remap_keycode_coverage.py`
- `script/test_vial_keycode_codec.py`
