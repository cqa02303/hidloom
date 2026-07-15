# LED role inspector / auto role tuning

更新日: 2026-05-27

この文書は、LED role editor beyond preview について検討した結果を残すメモです。
結論として、現時点では本格的な role editor を TODO に上げず、Wishlist 側へ下げます。

## 結論

今は **手動 role editor** ではなく、次の方針が安全です。

- 基本は keymap の keycode から自動 role 判定する。
- UI はまず「今このキーが何 role 扱いか」を見える化する inspector に寄せる。
- 誤判定が見つかったら、まず inference rule 側を直す。
- 手動 override editor は最後の手段にする。

## 既にあるもの

- Lighting tab の read-only LED role summary
- `daemon/http/led_role_preview.py` の side-effect-free frame builder
- `POST /api/lighting/role-preview`
- `Preview roles` / `Restore effect` UI helper
- `httpd.py` route wiring
- 非保存方針の静的テスト

## 検討した案

### 1. 全キー手動 role editor

各キーをクリックして role を変更する案です。

問題:

- レイヤーごとに keycode が変わるため、単純な position override では意図とズレる。
- keycode override、position override、layer+position override、LED index override のどれを使うかで UI が複雑になる。
- 永続保存の置き場所が難しい。
- 使い所は、自動判定が外れた特殊キーや物理的に見えにくい位置の例外に限られそう。

### 2. keycode override

特定 keycode の role を変更する案です。

例:

```json
{
  "role_overrides_by_keycode": {
    "KC_SH3": "normal",
    "KC_WIFI_OFF": "system"
  }
}
```

特徴:

- キー位置を移動しても keycode に追従する。
- script / BT / Wi-Fi / reboot など、意味がはっきりした keycode には向いている。
- ただし UI 上で「このキー」ではなく「この keycode 全体」を変える説明が必要になる。

### 3. position override

物理位置ごとに role を変更する案です。

例:

```json
{
  "role_overrides_by_position": {
    "2,5": "layer"
  }
}
```

特徴:

- 物理的に見えにくい LED や親指キーなどの見た目調整には向いている。
- ただしレイヤー変更で keycode が変わる場合、同じ物理位置が常に同じ role になり、自動判定の良さを潰す可能性がある。

### 4. layer+position override

レイヤーと物理位置を組み合わせる案です。

例:

```json
{
  "role_overrides_by_layer_position": {
    "0:2,5": "normal",
    "1:2,5": "function",
    "2:2,5": "system"
  }
}
```

特徴:

- レイヤーごとの keycode 差を壊しにくい。
- ただし UI と保存構造が一気に複雑になる。

## 推奨する当面の方針

当面は以下で十分です。

1. active layer / 表示 layer の keycode から auto role を判定する。
2. 画面では effective role を色で表示する。
3. key をクリックしたら、row/col、keycode、auto role を表示する。
4. 誤判定が見つかったら、手動 override ではなく inference rule を直す。
5. 実LED preview は既存の role preview route を使う。

この段階は editor ではなく、**role inspector / auto role tuning** と呼ぶ方が分かりやすいです。

## override editor を作る場合の条件

以下が揃ったら再検討します。

- 自動判定だけでは解決できない実例が複数出る。
- keycode override と layer+position override のどちらが必要か決まる。
- 保存先が決まる。
- UI で誤操作なく説明できる。
- 実機 preview と restore が安定している。

## 最小 UI にする場合

override なしの inspector なら、UI はシンプルにできます。

表示例:

```text
Layer: active
Key: row 2 col 5
Keycode: KC_SH3
Auto role: script
Effective role: script
```

ボタン:

- `Preview roles`
- `Restore effect`

この程度なら、複雑さを増やさずに自動判定の確認に使えます。

## Wishlist に残す内容

Wishlist には、次のように残します。

- Auto role inspector / tuning
- 自動判定ルールの改善
- 手動 override editor は、実例が出るまで後回し
- override を作る場合は、keycode / position / layer+position のどれに追従させるかを先に決める

## 現時点の扱い

- TODO には上げない。
- Wishlist に下げる。
- 実装優先度は `httpd.py` 分割、実機確認、LED role preview 安定化より下に置く。
