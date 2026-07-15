# Auto role inspector / LED role tuning design

更新日: 2026-05-28

この文書は、LED role editor を本格実装する前に、まず自動 role 判定を可視化する read-only inspector を設計するためのメモです。
手動 override editor は UI と保存構造が複雑になりやすいため、現時点では実装しません。

## 結論

- 最初に作るのは read-only の Auto role inspector。
- keymap / keycode から推定された role と、その推定理由を表示する。
- 手動 override editor は作らない。
- 誤判定が見つかったら、まず inference rule を直す。
- override は最後の手段として、実例が複数出てから再検討する。
- `GET /api/lighting/role-inspector` と Lighting tab の read-only 表示は実装済み。
- 実LED preview / restore の肉眼確認は、実機目視確認キューに残す。

## 目的

LED role preview は、role ごとに実LED色分けを表示できます。
しかし、どのキーがどの role として推定されたのか、なぜそう判定されたのかが UI 上で分かりにくいと、誤判定の原因を追いづらくなります。

Auto role inspector の目的:

- keymap上の各キーの inferred role を見る。
- role 判定理由を確認する。
- keycode / layer / position のどこから推定されたかを見える化する。
- 誤判定を manual override ではなく rule 改善につなげる。

## 対象外

この設計TODOでは、まだ以下を実装しません。

- role override editor
- keycode override 保存
- position override 保存
- layer+position override 保存
- LED role を手動で書き換えるUI
- roleごとの色編集UI

## 表示する情報

キーごとに表示する候補:

```json
{
  "row": 0,
  "col": 1,
  "layer": 0,
  "keycode": "KC_LSFT",
  "role": "modifier",
  "source": "keycode_rule",
  "reason": "KC_LSFT is modifier key",
  "confidence": "high"
}
```

最小表示:

- key label
- keycode
- inferred role
- source
- reason

詳細表示:

- layer
- row / col
- normalized action
- role priority
- overlay対象かどうか
- reactive / splash trigger 除外対象かどうか

## role source 候補

- `keycode_rule`
  - keycode prefix / known keycode から判定。
  - 例: `KC_LSFT` -> modifier。
- `action_type`
  - local action type から判定。
  - 例: `BT_POWER_OFF` -> system。
- `script_label`
  - `KC_SHn` と script metadata から判定。
- `semantic_roles_config`
  - `config/default/ledd.json` の `semantic_roles` 上書きから判定。
- `fallback`
  - 判定できない通常 key。

## UI配置案

第一候補:

- Lighting tab の LED role preview summary 周辺に `Inspect roles` を追加する。
- keyboard layout 上のキーをクリックすると、そのキーの role / reason を表示する。
- 最初は read-only table でもよい。

代替案:

- Keymap tab の key detail panel に role 情報を追加する。
- `/api/layout` に role metadata を含める。

実装済み:

- 最初は Lighting tab に read-only inspector を置く。
- keymap編集と混ぜず、LED role preview の補助として扱う。

## API案

実装済み:

```text
GET /api/lighting/role-inspector
```

返却例:

```json
{
  "result": "ok",
  "layers": [
    {
      "layer": 0,
      "keys": [
        {
          "row": 0,
          "col": 1,
          "keycode": "KC_LSFT",
          "role": "modifier",
          "source": "keycode_rule",
          "reason": "KC_LSFT is modifier key",
          "confidence": "high"
        }
      ]
    }
  ],
  "summary": {
    "normal": 66,
    "modifier": 7,
    "layer": 2,
    "lock": 1,
    "script": 8,
    "system": 5
  }
}
```

別案:

- 既存 `/api/layout` に `role` metadata を追加する。

- 既存 layout payload を肥大化させないため、まず専用 API を第一候補にする。
- 将来、keymap editor側で必要になったら `/api/layout` へ要約だけ足す。

## rule改善の流れ

1. inspector で誤判定を見つける。
2. source / reason を確認する。
3. keycode rule または action mapping を修正する。
4. role preview で実LED色分けを確認する。
5. 必要なら docs に誤判定例を記録する。

manual override はこの流れで解決できない場合だけ検討します。

## override再検討条件

手動 override editor は、以下が揃うまで実装しません。

- 自動判定だけでは解決できない実例が複数ある。
- keycode override と layer+position override のどちらが必要か決まる。
- 保存先が決まる。
- UI で誤操作なく説明できる。
- preview / restore が実機で安定している。

## 実装TODOへ進む条件

- [ ] LED role preview の実LED肉眼確認が完了している。
- [x] inspector の表示場所が決まっている。
- [x] 専用 API か `/api/layout` 拡張かが決まっている。
- [x] role source / reason の最小 schema が決まっている。
- [x] manual override editor を作らないことが明記されている。
- [x] 静的テストで inspector API / UI helper の存在を固定できる。

## 実機確認案

実装後に必要な確認:

1. Lighting tab で role inspector を開ける。
2. `Preview roles` の summary と inspector summary が一致する。
3. modifier / layer / lock / script / system の代表キーで reason が読める。
4. role preview の実LED色と inspector の role が一致する。
5. keymap変更後に inspector の role が更新される。
6. manual override editor が無くても誤判定の原因を追える。

## 現時点の判断

Auto role inspector は read-only API / UI helper / 静的テストまで実装済みです。
実LED色と inspector role が一致するかの肉眼確認は、LED role preview の実機確認と一緒に行います。
