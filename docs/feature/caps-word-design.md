# Caps Word design

作成日: 2026-05-30
更新日: 2026-06-01

QMK / ZMK / KMK 先行機能のうち、実機なしで設計しやすい `Caps Word` を
`logicd` / HTTP UI / OLED / LED overlay に入れる場合の設計です。
2026-05-30 に runtime 初期実装を追加済みです。
2026-06-01 には、実機なしで進められる follow-up として host Caps Lock と混同しない read-only status helper を追加しました。

## Goal

Caps Word は、単語入力中だけ Shift 相当を維持し、単語の区切りで自動解除する入力補助です。
通常の Caps Lock とは違い、host lock LED state や OS 側 Caps Lock を変更しません。

優先する体験:

- `CAPS_WORD` で一度有効化し、英字入力中は Shift を付ける。
- Space / Enter / Escape / Tab / 対象外記号で自動解除する。
- `KC_MINS` / `KC_BSPC` / `KC_DEL` / `KC_UNDS` 相当は単語継続として扱えるようにする。
- OLED / LED overlay / HTTP status へ active state を出せる構成にする。
- status / overlay 名は host Caps Lock と必ず分ける。

## Keycodes

| keycode | 動作 |
| --- | --- |
| `CAPS_WORD` | inactive なら active にする。active 中に押した場合は解除する。 |
| `CAPS_WORD_TOGGLE` | `CAPS_WORD` と同じ toggle alias。将来の UI 表示で説明しやすい名前として残す。 |
| `CW_TOGG` | QMK 互換 alias。Vial / keymap import で見つけた時は `CAPS_WORD` へ正規化する候補。 |

初期実装では hold / one-shot 版を作らない。
`CAPS_WORD_ON` / `CAPS_WORD_OFF` は運用で必要になるまで追加しない。

## Owner / state

| 項目 | 方針 |
| --- | --- |
| runtime owner | `logicd` の `InteractionEngine` |
| config owner | `settings.interaction.caps_word` |
| persistence | active state は永続化しない。daemon restart / config reload / output switch で解除する。 |
| output | `InteractionEngine` が対象 key press に Shift wrapper を合成する。host Caps Lock は送らない。 |
| status | `logicd.caps_word_status` が host Caps Lock と別の read-only status を生成する。 |

`settings.interaction.caps_word` の最小 schema:

```json
{
  "enabled": true,
  "continue_keys": ["KC_MINS", "KC_BSPC", "KC_DEL"],
  "cancel_keys": ["KC_SPACE", "KC_ENTER", "KC_ESC", "KC_TAB"],
  "word_letters": "KC_A..KC_Z"
}
```

`enabled=false` の場合、`CAPS_WORD` keycode は何もせず warning なしで無視する。
初期 config では `enabled=true` を既定候補にするが、UI 表示と一緒に最終判断する。

## Runtime status

`logicd.caps_word_status` は、Caps Word が host Caps Lock ではないことを明示する最小 status を返します。

```json
{
  "enabled": true,
  "active": true,
  "label": "Caps Word",
  "lock_type": "caps_word",
  "host_caps_lock": false
}
```

方針:

- `lock_type` は `caps_word` とし、`caps_lock` にしない。
- `label` は `Caps Word` とし、`Caps Lock` にしない。
- `host_caps_lock` は host LED / OS Caps Lock の read-only 状態を併記するだけで、Caps Word の owner にはしない。
- `enabled=false` の場合は `active=false` に潰して表示する。
- OLED の短縮 label は `CW` / `CW on` / `CW off` とし、`Caps Lock` とは書かない。
- LED overlay 名は `caps_word` とし、host-synced Caps Lock overlay とは分ける。

## Behavior

1. `CAPS_WORD` press/release は HID 出力せず、runtime active state だけを切り替える。
2. active 中に `KC_A`-`KC_Z` が押された場合、Shift wrapper を一時合成して出力する。
3. active 中に continue key が押された場合、その key は通常出力し active を維持する。
4. active 中に cancel key が押された場合、その key は通常出力し、その後 active を解除する。
5. active 中に対象外 action が押された場合、その action を通常出力し、その後 active を解除する。
6. modifier wrapper、tap-hold、tap dance、Morse、combo 由来 action は、最終的な tap action に対して判定する。

解除する event:

- cancel key / 対象外 action
- layer clear / config reload
- output target switch
- daemon shutdown / restart
- emergency release / stuck-key recovery

## UI / feedback

| surface | 方針 |
| --- | --- |
| HTTP remap | `Interaction` または `System` group に `CAPS_WORD` を出す。 |
| HTTP status | first slice は Interaction summary の `Caps Word` metric に設定 enabled / disabled だけを出す。runtime `caps_word.active` は stale 表示を避けるため、`logicd.caps_word_status` を runtime snapshot へ接続する後続まで `/api/status` へ出さない。 |
| OLED | runtime 接続時の label は `CW on` / `CW` / `CW off` とし、host Caps Lock と同時 active の場合も `Caps Lock` より短い別 row / field として扱う。 |
| LED | runtime 接続時の overlay 名は `caps_word` とし、host-synced `caps_lock` / `host_caps_lock` overlay と混ぜない。 |

Caps Lock と同じ overlay 色にすると OS lock と混同するため、LED overlay を入れる場合は
`caps_word` と `caps_lock` を別 state 名にする。
first slice では OLED / LED runtime 接続を入れず、label / overlay name の helper と static test だけで固定する。

## Safety / non-goals

- host Caps Lock を変更しない。
- BLE / USB / uinput output target によって挙動を変えない。
- active state を永続化しない。
- IME の日本語入力状態は検出しない。
- Autocorrect は同時に実装しない。
- Shift を既に押している場合の挙動は、初期実装では「既存 modifier を尊重し、追加 Shift は冪等」とする。
- status や OLED / LED 名で Caps Lock と混同させない。

## Static tests added with implementation

Runtime 初期実装:

- `CAPS_WORD` keycode が validation を通り、通常 HID 出力を発生させない。
- active 中の `KC_A` が Shift 付きで出力される。
- `KC_MINS` / `KC_BSPC` は active を維持する。
- `KC_SPACE` / `KC_ENTER` / 対象外 action は active を解除する。
- config reload / output switch で active state が解除される。
- HTTP remap candidate に `CAPS_WORD` が出る。

Status follow-up:

- status は `label=Caps Word`、`lock_type=caps_word` を返す。
- host Caps Lock の状態は `host_caps_lock` に分けて併記する。
- `enabled=false` では `active=false` として表示する。
- OLED label は `CW` 系にし、`Caps Lock` と書かない。
- LED overlay 名は `caps_word` とし、`caps_lock` / `host_caps_lock` と衝突させない。

## Implementation gate

実装済み:

- `InteractionEngine` の tap action 後段で Shift 合成できることを小さな単体テストで確認できる。
- HTTP remap candidate と Vial import alias の扱いを同じ正規化名へ寄せられる。
- host Caps Lock と混同しない read-only status helper を用意できる。

後続候補:

- HTTP `/api/status` に runtime `caps_word.active` を出す場合は、`InteractionEngine` から同じ request 内で snapshot を取り、config の `settings.interaction.caps_word` と混ぜない。
- OLED / LED feedback を入れる場合も、active state の owner を `logicd` から動かさない。
- output switch / config reload / cancel key / emergency release 後に `active=false` の snapshot が返ることを接続テストで固定する。

実装しない条件:

- 日本語 IME / host layout 依存の補正まで同時に求められる。
- Caps Lock との見分けが UI / LED でつかない。
- Repeat Key / Autocorrect と同時に大きく入れないと成立しない。
