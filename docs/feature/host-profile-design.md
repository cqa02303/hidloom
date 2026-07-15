# Host profile / OS detection design

更新日: 2026-06-01

この文書は host profile / OS detection 的な host 別設定の設計です。
2026-06-01 時点では、実機なしで進められる first slice として `logicd.host_profile_status` の read-only status helper と静的テストを追加済みです。
まだ host profile の適用、modifier swap、OS detection、btd writer 連携は実装しません。

## 現在の前提

- HTTP System panel は Bluetooth paired host overview を read-only 表示できる。
- `last_connected_at` / `last_connected_source` は HTTP status merge / System panel detail 表示まで実装済み。
- btd writer は未実装で、paired host がある状態で notify ready を観測してから進める。
- output target は `auto` / `gadget` / `bt` / `uinput` を扱う。
- JIS/US の host layout は自動判定できない。
- `logicd.host_profile_status` は connected host metadata と profile config を合成し、表示用の active metadata だけを返す。

## Initial policy

初期実装は OS detection ではなく、manual host profile として扱います。

- 自動で Windows / macOS / iOS / Linux を推定しない。
- host address / alias / last connected metadata を read-only の候補情報として使う。
- profile 適用は明示設定で行う。
- profile active state は HTTP / OLED で read-only 表示する。
- 未設定 host には profile を適用しない。

## Profile schema candidate

保存先候補:

- `/mnt/p3/host_profiles.json`
- または `settings.host_profiles`。初期実装では `/mnt/p3/host_profiles.json` を第一候補にする。

候補:

```json
{
  "version": 1,
  "hosts": {
    "AA:BB:CC:DD:EE:FF": {
      "label": "iPhone",
      "profile": "ios",
      "layout": "jis",
      "modifier_swap": "command_control",
      "keymap_profile": null,
      "enabled": true,
      "updated_at": "2026-05-30T00:00:00Z"
    }
  },
  "profiles": {
    "ios": {
      "display_name": "iOS",
      "modifier_map": {
        "KC_LGUI": "KC_LCTL",
        "KC_LCTL": "KC_LGUI"
      },
      "layout_fixups": [],
      "keymap_layer": null
    }
  }
}
```

## Owner / data flow

- `btd` owns Bluetooth runtime host events.
- `httpd` can read host metadata and profile config for display / edit.
- `logicd` owns applying profile behavior to key output.
- `logicd.host_profile_status` owns only derived read-only display metadata.
- `i2cd` / `ledd` are read-only consumers.
- host profile config is persistent, but active runtime profile is derived state.
- First slice does not provide an edit UI. When an edit UI is added, `httpd` owns validation and atomic replacement of `/mnt/p3/host_profiles.json`; `logicd` never writes this file.

Flow candidate:

1. `btd` reports connected host address / alias / notify ready.
2. `logicd` receives or reads current output host metadata.
3. `logicd` looks up enabled profile.
4. `logicd` applies modifier map / layout fixup / keymap profile only while that host is active.
5. output switch / disconnect clears active derived profile.

First slice flow:

1. caller passes connected host metadata and profile config to `active_host_profile_status()`.
2. helper returns reasoned read-only status.
3. helper does not mutate host metadata or profile config.
4. helper does not apply modifier / layout / keymap changes.

## Active profile status

`logicd.host_profile_status.active_host_profile_status()` returns:

```json
{
  "active": true,
  "host_address": "AA:BB:CC:DD:EE:FF",
  "host_label": "iPhone",
  "profile": "ios",
  "profile_label": "iOS",
  "layout": "jis",
  "enabled": true,
  "reason": "matched"
}
```

Reason values:

| reason | 意味 |
| --- | --- |
| `matched` | connected host に enabled profile が見つかった。 |
| `no_active_host` | active host metadata がない。 |
| `profile_not_configured` | host address に紐づく profile entry がない。 |
| `profile_disabled` | profile entry はあるが `enabled=false`。 |

`merge_profile_status_into_host()` は host metadata の copy に read-only field を足すだけで、元 object を変更しません。

## Scope

初期実装で扱うもの:

- Bluetooth host address に紐づく manual profile。
- modifier swap preset の schema placeholder。
- read-only active profile status。
- profile enabled / disabled flag。
- HTTP System panel detail への profile label 表示候補。
- OLED 用の短い `Host iOS` label helper。

初期実装で扱わないもの:

- automatic OS detection。
- USB host identity detection。
- JIS/US layout の完全自動補正。
- per-host destructive actions。
- profile ごとの arbitrary script。
- profile ごとの Wi-Fi / BT / power 操作。
- keymap 全体の hot swap。
- first slice での modifier swap 適用。

## Modifier / layout policy

Modifier swap:

- 初期対象は `KC_LGUI` / `KC_LCTL` / `KC_LALT` / right side modifier の direct swap に限定する。
- tap-hold / modifier wrapper / Mod-Morph との適用順を実装前に固定する。
- script / system / connectivity action は変換しない。
- first slice ではまだ変換しない。

Layout fixups:

- 初期実装では read-only candidate に留める。
- JIS/US 記号補正は host OS layout に依存するため、自動判定しない。
- 補正する場合は `S(KC_*)` など既存 wrapper action に展開する。

Keymap profile:

- 初期実装では `keymap_profile` は `null` のまま許可する schema placeholder。
- layer / keymap の完全切替は実装しない。
- 実装する場合は Vial / HTTP / runtime keymap の source of truth と衝突しない設計を先に追加する。

## UI policy

HTTP:

- System panel の Bluetooth host detail に profile name / enabled / layout を read-only 表示する。
- 初期実装では edit UI は作らない。
- destructive forget / rename UI と profile UI を混ぜない。

OLED:

- active profile がある時だけ短い `Host iOS` のような status を表示する候補。
- 常時表示はしない。

LED:

- host profile 専用 overlay は作らない。
- modifier / layer / lock overlay と混ぜない。

## Static tests

実装済み first slice:

- active host metadata がない場合は `no_active_host`。
- unknown host では `profile_not_configured`。
- disabled profile は metadata を表示できるが active にはしない。
- enabled profile は profile / label / layout を read-only status に出す。
- host metadata merge は copy にだけ field を足し、元 object を変更しない。
- OLED label は active profile の時だけ `Host <label>` を返す。

後続実装時に追加するテスト:

- enabled profile の modifier_map が direct modifier action にだけ適用される。
- script / system / connectivity action は変換されない。
- output switch / disconnect で active profile が clear される。
- `/api/status.bluetooth.devices[]` に profile read-only fields が merge される。
- HTTP System panel が profile label を read-only 表示する。

## Implementation gate

実装へ進める条件:

- paired host がある状態で reconnect / HID notify ready / last_connected_at を観測できる。
- host address を profile key にしてよいことを実機で確認できる。
- `logicd` が active host metadata を read-only に受け取れる。
- modifier swap の適用順を InteractionEngine / macro dispatch とテストで固定できる。

実装しない条件:

- automatic OS detection が前提になる。
- USB host identity detection が必要になる。
- keymap 全体 hot swap が必須になる。
- profile が Vial / HTTP keymap save payload と混ざる。
- profile が script / system / connectivity actionを書き換える。
