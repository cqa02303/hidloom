# Key Toggle / Key Lock design

更新日: 2026-06-05

この文書は Key Toggle / Key Lock / Drag Lock 相当の interaction の設計と first slice の状態をまとめます。
2026-06-05 時点では、`logicd.key_lock` helper を `InteractionEngine` main dispatch path へ接続済みです。
stuck-key リスクを避けるため、対象は modifier と mouse button に限定し、runtime status は read-only に留めます。
OLED / LED feedback、generic editor、Vial keycode assignment、実機での drag 体感確認は後続です。

## 現在の前提

- `logicd` は keyboard / mouse / consumer report を出力できる。
- output switch 時は `release_all()` により keyboard / mouse の zero report を送る。
- `InteractionEngine` は tap-hold、combo、tap dance、key override、Morse、key lock などの状態を持つ。
- Sticky status design では将来の key lock / drag lock を `sticky.keys[]` に載せる候補にしている。
- `logicd.key_lock.KeyLockState` は `InteractionEngine.key_locks` の runtime state owner で、active locked modifier は Key Override の held modifier 判定にも参加する。

## Candidate actions

初期候補名:

- `KEY_TOGGLE(kc)`: 対象 key を押下状態にする。すでに locked なら解除する。
- `KEY_LOCK(kc)`: 対象 key を押下状態にする。解除は `KEY_UNLOCK(kc)` または全解除 event。
- `KEY_UNLOCK(kc)`: 対象 key の locked state を解除する。
- `DRAG_LOCK`: `KC_BTN1` の mouse button hold に限定した preset。

first slice では `logicd.key_lock.parse_key_lock_action()` で上記の action 名を parse します。
HTTP remap candidate や Vial custom keycode に出す前に、`config/default/keycodes.json` と `daemon/viald/keycode_codec.py` の名前を最終決定します。

## Scope

初期実装で扱う対象:

- modifier key: `KC_LCTL` / `KC_LSFT` / `KC_LALT` / `KC_LGUI` / right side modifier と互換 alias。
- mouse button: `KC_BTN1`-`KC_BTN5`。
- `DRAG_LOCK` は `KC_BTN1` の preset として扱う。

初期実装で扱わない対象:

- 通常文字 key の hold lock。
- script action。
- system / power / Bluetooth / Wi-Fi / output switch action。
- consumer control。
- mouse movement / wheel。
- macro / Morse / tap dance / combo の複合 action。

通常文字 key は stuck-key 事故の影響が大きく、host の key repeat と衝突しやすいため初期対象外にします。

## State owner

State owner は `logicd.key_lock.KeyLockState` で、runtime owner は `InteractionEngine.key_locks` です。

実装済み:

- state は `{action: "KC_BTN1", kind: "mouse_button", source: "DRAG_LOCK"}` のように正規化して保持する。
- `httpd` は `INTERACTION_STATUS` / `GET /api/interaction/runtime-status` / Interaction summary と `/api/status.interaction.key_lock.active_count` / System panel count の read-only consumer にする。
- `i2cd`、`ledd` は将来 read-only consumer にする。
- active state は永続化しない。
- helper は HID device へ直接触らず、caller が通常 output path に流せる `KeyLockEvent(action, is_press, source="key_lock")` だけを返す。

Status schema は Sticky status design の `keys[]` を使います。

実装済み status 例:

```json
{
  "keys": [
    {
      "action": "KC_BTN1",
      "mode": "locked",
      "source": "DRAG_LOCK",
      "kind": "mouse_button",
      "locked": true,
      "cancel_reason": null
    }
  ]
}
```

## Output policy

Key Lock は synthetic press / release を出す機能として扱います。

- lock 開始時に対象 action の press event を返す。
- unlock 時に対象 action の release event を返す。
- clear 時は active lock の release event を全て返し、state を空にする。
- helper 自体は zero report を送らない。output switch では switch action の前に `clear()` release event を既存 output path へ流し、その後既存 release / zero report 経路へ進む。
- mouse button lock は mouse zero report で必ず解除できるようにする。
- modifier lock は keyboard zero report で必ず解除できるようにする。

同じ対象が物理 press 中の場合:

- 物理 press と synthetic lock を別 source として扱う。
- synthetic unlock だけで物理 press を release しない。
- 物理 release だけで synthetic lock を release しない。

この source 分離が dispatch path で実装できない場合は、Key Lock は main path へ接続しません。

## UI policy

HTTP:

- 初期実装では read-only status 表示だけにする。
- `GET /api/interaction/runtime-status` は `key_lock.keys[]` を返し、Interaction summary は active key を短く表示する。
- `/api/status.interaction` は `key_lock.active_count` だけを返し、System panel は action 名を出さない。
- editor / unlock button は後回しにする。
- 保存 payload に active lock state を混ぜない。

OLED:

- `Drag`、`Hold Sft` のように短く表示する。
- Caps Word / Caps Lock / Layer Lock と違う表示にする。
- first slice では未実装。

LED:

- optional overlay 名は `key_lock` または `drag_lock` とする。
- host lock LED の `HOST_LED` overlay とは混ぜない。
- first slice では未実装。

## Static tests

実装済み:

- `DRAG_LOCK` が `KC_BTN1` synthetic press を生成し、再実行で release を生成する。
- `KEY_TOGGLE(KC_LSFT)` が modifier press / release event を生成する。
- `KEY_LOCK(KC_BTN2)` は重複 lock で no-op、`KEY_UNLOCK(KC_BTN2)` で release を生成する。
- `clear()` が active lock の release event を返し、state を空にする。
- script / system / output switch / connectivity / 通常文字 action は unsupported として reject される。
- Sticky status 互換の `keys[]` が read-only で返る。
- supported target inventory を test で固定する。
- `InteractionEngine` が `KEY_TOGGLE(KC_LSFT)` / `DRAG_LOCK` を synthetic press / release として dispatch する。
- locked modifier が Key Override の held modifier 判定に参加する。
- output switch 前に locked keys を clear し、release event が switch action より先に通常 output path へ流れる。
- reset / config reload / emergency release 相当では、active key lock の release event と held interaction release event を返し、
  後続の物理 release は no-op にする。
- `settings.interaction` validation は modifier / mouse button lock だけを受け入れ、`KEY_LOCK(KC_A)` は warning として拒否する。
- `INTERACTION_STATUS` / `GET /api/interaction/runtime-status` / `/api/status.interaction` / static UI assets の runtime status 境界を固定する。

後続候補:

- OLED / LED feedback。
- generic editor / Vial keycode assignment。
- 実機での drag 体感、stuck-key recovery、mouse zero report の確認。

2026-06-05 follow-up:

- Vial custom keycode は既存 64 件で `USER00`-`USER63` を使い切っているため追加しない。
- `DRAG_LOCK` は HTTP Remap の Interaction tab `Runtime helpers` から割り当てる。
- `KEY_TOGGLE(kc)` / `KEY_LOCK(kc)` / `KEY_UNLOCK(kc)` の汎用 editor は、実使用で必要になってから別途判断する。

Dispatch first slice の固定事項:

- first slice の対象は modifier key と `KC_BTN1`-`KC_BTN5` だけにする。
- `DRAG_LOCK` は `KC_BTN1` の `KEY_TOGGLE` preset として同時に扱う。
- script / system / connectivity / output switch action は unsupported warning として消費し、通常 executor へ落とさない。
- helper の `clear()` は active synthetic lock の release event を返すだけにし、zero report は caller が既存 output path で必ず送る。
- output switch 接続時は、switch action 前に `clear()` release event を通常 output path へ流し、status `keys=[]` になることを integration test で固定する。
- reset / config reload / emergency release 相当では `InteractionEngine.reset()` が release event を返し、state を空にする。
  実際の config reload は既存の `release_all()` / zero report 経路も併用して host 側 stuck-key を避ける。
- physical press と synthetic lock は runtime state source を分ける。synthetic unlock で physical press を release せず、physical release で synthetic lock を解除しない。

## Implementation gate

実装済み first slice:

- keyboard modifier と mouse button の target validation。
- unsupported target の reject。
- synthetic press / release event 生成。
- Sticky status design の `keys[]` と矛盾しない read-only status。
- `InteractionEngine` main dispatch への接続。
- locked modifier の Key Override held modifier 参加。
- output switch 前 clear と通常 output path への release dispatch。
- `INTERACTION_STATUS` / `GET /api/interaction/runtime-status` / Interaction summary。
- `/api/status.interaction.key_lock.active_count` / System panel count。

main dispatch first slice の達成条件:

- keyboard modifier と mouse button の press / release を synthetic source として分離できる。
- output switch で release event と state clear を通せる。
- 対象外 action を validation で拒否できる。
- HTTP / config save payload に active state を混ぜない。

実装しない条件:

- 通常文字 key の hold lock から始める必要がある。
- script / system / connectivity action を lock 対象に含める必要がある。
- physical press と synthetic lock の source 分離ができない。
- active lock state が config / Vial / HTTP save payload に保存される。
