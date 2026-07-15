# Action routing matrix

この文書は、keymap / Vial / HTTP / macro から入る action を、
内部処理と出力先ごとの扱いへ落とすための一覧表です。
個別の HID usage / Linux code の正本は [../../config/default/keycodes.json](../../config/default/keycodes.json) とし、
この文書は「分類」「特殊処理」「出力 route」「移植時の確認点」を固定します。

## 目的

機能追加や Rust 移植で取りこぼしやすい条件を、実装前に表で確認できるようにします。

- 送信できる keycode と、内部専用 action を混同しない。
- Keyboard / Consumer / Mouse / local command / text send を同じ HID report として扱わない。
- USB / uinput / BT / auto / console の出力差を明示する。
- `logicd` と `logicd-core-rs` の対応範囲を比較できるようにする。

## 正本と派生表

| 種類 | 正本 | この文書で固定する内容 |
|---|---|---|
| 個別 keycode 名、HID usage、Linux code | `config/default/keycodes.json` | 分類、route、特殊処理の読み方 |
| Vial custom 表示名 | `config/default/vial.json` | local action が Vial へ出る時の注意 |
| keymap action shape | `config/default/keymap.json`、runtime `/mnt/p3/keymap.json` | action 文字列をどの処理クラスへ送るか |
| resolved action runtime | `daemon/logicd/interaction_engine.py` | layer / tap-hold / one-shot などの解決後 event |
| native fast path | `tools/hidloom_logicd_core/src/main.rs` | boot-critical subset と broker frame route |

個別 315 件の keycode 表は JSON を正本にします。
文書へ手で全件を重複転記すると古くなりやすいため、完全表が必要な時は
`tools/keycode_action_inventory.py` で Markdown 表を生成します。

## Action 分類一覧

| 分類 | action 例 | 内部処理 | host へ直接送るか | 注意点 |
|---|---|---|---|---|
| no-op / transparent | `KC_NONE`, `KC_TRNS` | `KC_NONE` は何もしない。`KC_TRNS` は keymap 解決時に下位 layer へ fallthrough | 送らない | `KC_TRNS` を HID usage 0 として送らない |
| Keyboard Page | `KC_A`, `KC_ENTER`, `KC_F1`, `KC_INT1`, `KC_LANG1` | Keyboard HID 8 byte report の modifier / key array へ反映 | 送る | `page` 未指定の `hid <= 255` が基本 |
| Modifier | `KC_LCTL`, `KC_LSFT`, `KC_RALT`, `KC_RGUI` | Keyboard report の modifier bit へ反映 | 送る | key array へ通常 key として入れない |
| Consumer Page | `KC_VOLU`, `KC_MPLY`, `KC_BRIU` | Consumer Control report へ変換 | 送る | `page=consumer`。Keyboard report と別 report |
| Keyboard Page 音量互換 | `KC_KB_MUTE`, `KC_KB_VOLUME_UP`, `KC_KB_VOLUME_DOWN` | 互換 alias として扱う | 送る | host 互換のため Consumer route へ寄せる場合がある |
| Mouse button / motion / wheel | `KC_BTN1`, `KC_MS_U`, `KC_WH_D` | Mouse report state を更新 | 送る | motion は押下中 button bit を merge する |
| Layer control | `MO(1)`, `TG(2)`, `TO(0)`, `DF(1)`, `OSL(2)`, `TT(3)` | layer state を変更し、必要なら synthetic release を出す | 直接は送らない | layer 変更で押下中 action が変わる場合の release を忘れない |
| Tap-hold / mod-tap | `LT(2,KC_A)`, `MT(KC_LSFT,KC_A)` | press/release 時間と interrupt で tap / hold を解決 | 解決後 action を送る | tap 側と hold 側の両方を validation する |
| Modifier wrapper | `S(KC_1)`, `C(KC_ENTER)` | 一時 modifier press + key tap / hold へ展開 | 展開後に送る | wrapper 自体を HID usage として保存しない |
| Script key | `KC_SH0`-`KC_SH10` | local script / shell action を起動 | 送らない | boot-critical path に subprocess を戻さない |
| Output switch | `KC_CONNAUTO`, `KC_CONSOLE`, `KC_USB`, `KC_BT` | output target を変更 | 送らない | 現行 owner は `hidloom-outputd`。切替時は release-all / null report を送る |
| Bluetooth command | `BT_STATUS`, `BT_POWER_ON`, `BT_PAIRING_TOGGLE`, `BT_DISCONNECT` | BT manager / btd 制御 | 送らない | paired list と active host を混同しない |
| Wi-Fi command | `WIFI_STATUS`, `WIFI_POWER_TOGGLE` | local network helper / status | 送らない | input hot path から重い処理を呼ばない |
| System command | `KC_SHUTDOWN` | local system action | 送らない | confirmation / safety gate を別途維持する |
| JIS special local alias | `KC_ZKHK`, `KC_ZENKAKU_HANKAKU` | host profile / split keyboard route で扱う | profile 次第 | native M0 では no-op または route-specific handling |
| RGB / lighting | `RGB_TOG`, `RM_NEXT`, `RM_VALU` | LED / VialRGB state を変更 | 送らない | QMK Backlight / LED Matrix とは別モデル |
| Macro | `MACRO:name`, `M0`, Vial macro | token sequence へ展開 | 展開後に送る | text / tap / down / up / delay の cancel 条件を維持 |
| Text / Unicode | `U+3042`, `SEND_STRING(...)`, touch flick text | host profile の text send plan へ変換 | plan 次第 | helperless route は host layout 依存。preview と real send を混ぜない |
| Dynamic interaction | Repeat Key, Caps Word, Tap Dance, Combo, Key Override | InteractionEngine が resolved action を生成 | 解決後 action を送る | synthetic source と実 key source を区別する |
| 未対応 / preview-only | `UC(c)`, `LM(layer,mod)`, `PDF(layer)` など | validation / preview / blocking reason | 送らない | 保存可能と実行可能を分ける |

## 出力先別扱い

| target | owner | Keyboard Page | Consumer Page | Mouse | local command | text / Unicode | 備考 |
|---|---|---|---|---|---|---|---|
| `usb` | `hidloom-outputd -> hidloom-hidd` | USB HID keyboard report | USB HID consumer report | USB HID mouse report | 送らない | key tap sequence へ変換した場合のみ | boot-critical の標準 route |
| `uinput` / `console` | `hidloom-outputd -> hidloom-uidd` または legacy console route | Linux input code があるものだけ | Linux input code があるものだけ | uinput mouse 対応範囲のみ | 送らない | host 側表示ではなく local input として扱う | `linux=null` の key は fallback 不可 |
| `bt` | `hidloom-outputd -> btd` | BLE HID keyboard report | BLE HID consumer report | BLE HID mouse report | 送らない | key tap sequence へ変換した場合のみ | active host / notify ready を確認する |
| `auto` | `hidloom-outputd` | USB ready なら `usb`、そうでなければ `uinput` | 同左 | 同左 | 送らない | 同左 | BT fallback は暗黙に含めない |
| `none` / preview | caller | 送らない | 送らない | 送らない | 実行しない | preview のみ | UI / validation / dry-run 用 |

local command は出力 target へ流さず、resolved action handler で処理します。
output switch action だけは target を変更するための control action であり、変更先へ key press として送ってはいけません。

## 特殊処理一覧

| 条件 | 処理 | 取りこぼし防止 |
|---|---|---|
| `KC_TRNS` | keymap resolve 中だけ下位 layer へ fallthrough | resolved action として HID route に出さない |
| `KC_NONE` | no-op | press/release state を持たない |
| modifier key | modifier bit set / clear | regular key array の 6 key limit と別管理 |
| Consumer Page | consumer report kind へ分岐 | Keyboard report の usage と混ぜない |
| Mouse button + motion | button state を motion report に merge | drag 中 motion で button release しない |
| layer change | old active action の release を生成 | stuck key と layer ghost を防ぐ |
| output switch | old/new target へ release-all / null report | target 変更時の stuck key を防ぐ |
| `KC_ZKHK` | JIS special profile で扱う。通常 route では host 依存 | US default route へ無条件に混ぜない |
| `KC_LANG1` / `KC_LANG2` | Windows IME helperless の主要候補 | host profile と warning を通す |
| `KC_SH*` | local script route | matrix intake / native hot path へ重い処理を置かない |
| text send | preflight、blocking reason、cancel condition を通す | preview-only と real send を混同しない |
| unknown action | validation error または unsupported counter | no-op 成功扱いにしない |

## logicd-core-rs 投入時の対応範囲

`logicd-core-rs` は boot-critical subset から始めます。
現時点で native fast path の正面対象は、basic keyboard、modifier、`KC_TRNS` fallthrough、
`KC_NONE`、`MO(n)`、一部 JIS special route、`usb_split_keyboard` route です。

| 分類 | native fast path | Python companion / legacy 側 |
|---|---|---|
| basic keyboard / modifiers | 対象 | parity 比較対象 |
| Consumer / Mouse | 段階追加対象 | 現行処理を維持 |
| `KC_SH*` / system / BT / Wi-Fi | 対象外 | companion / control plane |
| text / Unicode / macro | 対象外 | companion / text-send runner |
| output switch | control 経由で扱う | `hidloom-outputd` owner を維持 |

Rust 側で unsupported action を no-op にする場合も、
status counter / preview log に unsupported として残します。
「押しても何も起きない」と「未対応として検出した」を分けます。

## 完全表を生成する時の列

個別 keycode の完全表を生成する場合は、次の列にします。
`MO(n)` / `LT(...)` のような構文 pattern は [action-patterns.md](action-patterns.md) に分けます。

```bash
python3 tools/keycode_action_inventory.py > /tmp/keycode-action-inventory.md
```

| column | 内容 |
|---|---|
| `action` | `KC_A` などの action 名 |
| `canonical` | alias の代表名。未決なら空 |
| `category` | `keyboard`, `modifier`, `consumer`, `mouse`, `local_command`, `layer`, `text`, `unsupported` |
| `hid_page` | `keyboard`, `consumer`, `mouse`, `none` |
| `hid_usage` | HID usage ID |
| `linux_code` | uinput fallback code。不可なら `null` |
| `logicd` | `send`, `internal`, `expand`, `preview`, `unsupported` |
| `logicd_core_rs` | `keyboard_page`, `internal`, `unsupported`, `not_in_m0` |
| `usb` | 出力可否と report kind |
| `uinput` | 出力可否 |
| `bt` | 出力可否と report kind |
| `special_notes` | route / host profile / safety gate |

この列を使えば、QMK keycode 追加、Vial custom keycode 追加、Rust 移植、BT route 追加のレビューで
同じ表を見ながら抜けを確認できます。

## 更新ルール

- `config/default/keycodes.json` に keycode を追加したら、この文書の分類表に該当分類があるか確認する。
- 新しい出力 target を追加したら「出力先別扱い」を更新する。
- 特殊な host profile 依存を追加したら「特殊処理一覧」に入れる。
- `logicd-core-rs` の対応範囲を広げたら「logicd-core-rs 投入時の対応範囲」を更新する。
- 個別 keycode の生成表を追加する場合は、手書きではなく JSON から生成する。
