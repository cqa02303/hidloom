# Touch panel Vial layout notes

更新日: 2026-06-02

この文書は Raspberry Pi 4 touch panel kiosk / `<keyboard-host>` 用に生成する
`/mnt/p3/vial.json` と、Vial client での表示確認メモを残す場所です。

## 背景

`<keyboard-host>` touch-panel 用 runtime Vial 定義では、`viald` と `/api/layout` が
`/mnt/p3/vial.json` を優先して参照します。
実機では Vial protocol が touch-panel profile 名、UID、Space slot、`KC_SPACE` を返すことを確認済みです。

その後、Vial client 上で Space bar が表示されない事象がありました。
ユーザー確認により、Space bar の layout entry に付いていた KLE / Vial 互換の `a` 属性を削除すると
Vial client で表示されることを確認しました。

## `a` 属性の扱い

`layouts.keymap` 内の `a` は keycode や matrix coordinate ではなく、KLE 系の legend alignment、
つまりキーキャップ上の文字配置を指定する描画用属性です。

本プロジェクトの Vial 定義で matrix mapping に必要なのは、基本的に次の属性です。

- `x` / `y`: 表示位置の相対移動
- `w` / `h`: キーの幅と高さ
- `row,col`: matrix coordinate

Space bar のような横長キーでは、`w` などの geometry だけで Vial client の表示には十分です。
`a` は必須ではなく、touch-panel Vial では client 側の large-key rendering と相性が悪い場合があります。

## 方針

- touch-panel 用 `vial.json` では、横長キーに `a` を付けない。
- Space bar などの large key は `w` / `h` / `x` / `y` と `row,col` だけで表現する。
- `a` は legend alignment 用の任意属性として扱い、matrix mapping や keycode lookup のためには使わない。
- 今後 Vial client 側の別 regression が見つかるまでは、touch-panel Vial 生成で `a` を再導入しない。

推奨例:

```json
[
  { "w": 6.25 },
  "5,2"
]
```

避ける例:

```json
[
  { "a": 7, "w": 6.25 },
  "5,2"
]
```

## 実装メモ

`build/generators/generate_touch_panel_vial.py` にも同じ方針をコメントとして残しています。
`a` は legend alignment hint であり、touch-panel Space bar では Vial client が large key を隠す原因になり得るため、
geometry と matrix coordinate に必要な属性だけを残す運用にします。

2026-06-02 に `script/test_touch_panel_profile.py` へ `layouts.keymap` の `a` 非混入チェックを追加しました。
生成済み `config/default/touch-panel/vial.json` / `config/default/touch-panel/osoyoo-4.3/vial.json` と、
`select_touch_panel_profile.py` が配置する runtime `/mnt/p3/vial.json` 相当の両方を静的に確認します。

## 残確認

- Vial client で runtime `/mnt/p3/vial.json` を読み直し、Space bar が表示されることを実機側でも再確認する。
- Vial client 側の別 regression が出た場合だけ、最小再現 JSON と client version を記録して方針を見直す。
