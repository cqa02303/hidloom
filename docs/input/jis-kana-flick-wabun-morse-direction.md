# JIS kana direction for touch flick and Wabun Morse

更新日: 2026-06-15

Touch flick と和文 Morse の次ステップは、いったん JIS 配列のかな入力に限定する。

## 方針

- Touch flick のかな出力は JIS 配列かな入力 profile を主対象にする。
- 和文 Morse も JIS 配列かな入力へ変換する profile として扱う。
- `romaji_us_ime` は fallback / 別 profile として残す。
- 汎用 host / 汎用 IME 対応を先に広げない。
- 実装後の試験対象を JIS layout + かな入力 mode に絞る。
- Windows / Microsoft IME では、該当設定を ON にすると `Alt + KC_KANA` と
  `Alt + KC_HENKAN` でかな入力 / ローマ字入力を helper なしで切り替えられることを確認済み。
- host LED output の `Kana` bit は、かな入力 ON 直後ではなく次の 1 key 入力後に反応する場合がある。
  Touch flick / 和文 Morse では、これを即時 source of truth ではなく、遅延ありの
  safety guard / advisory signal として使う。
- Windows のハードウェアキーボードレイアウトを JIS / Japanese 側へ切り替えると、
  `KC_HENKAN` / `KC_MUHENKAN` は変換 / 無変換として有効になった。

## 理由

- Touch flick は画面上のかなと出力かなを対応させるほうが分かりやすい。
- 和文 Morse は和文符号からかなへ対応付けるほうが自然。
- JIS 配列かな入力に限定すると、mapping、host profile、試験条件を狭くできる。
- `Alt + KC_KANA` / `Alt + KC_HENKAN` が使えるため、keyboard 側から host IME をかな入力へ寄せる導線を作れる。
- `Kana` LED output が取得できれば、状態不明のまま文字を送るリスクを下げられる。
  ただし 1 key 分遅延する場合があるため、guard は「refresh 後に確認」または warning として扱う。
- JIS/Japanese keyboard identity が成立した時に Kana LED と `KC_HENKAN` / `KC_MUHENKAN` の挙動が揃うため、
  フリック / 和文 Morse の host profile をかな入力本線に単純化できる。

## 実装前に決めること

- JIS かな入力で使う key action table。
- 濁点、半濁点、拗音、促音、長音の扱い。
- Touch flick の direction label と JIS かな key action の対応。
- 和文 Morse の sequence table と fallback action。
- かな入力へ寄せる時に `Alt + KC_KANA` と `Alt + KC_HENKAN` のどちらを profile default にするか。
- `host_led_output.states.kana` を有効化した時に、かな入力 ON 後の refresh key をどこで入れるか。
- JIS profile ではない host での warning / no-op policy。

## 採用判定

`adopt-with-guard`。

次段は JIS 配列かな入力に限定してよい。ただし、JIS host profile、かな入力 mode guard、
Kana LED unknown 時の warning、disabled default が揃うまで、実送信 path は広げない。
