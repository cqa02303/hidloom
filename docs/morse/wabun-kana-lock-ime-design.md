# Wabun Morse kana lock IME design

更新日: 2026-06-15

和文モールス入力は、当面は host IME のかな入力モードに頼る案を優先検討します。
この文書は、`KC_KANA`、Kana LED Output Report、Windows / Microsoft IME のかな入力状態をどう扱うかの
検討結果と、実機確認待ちの判断項目を残します。

## 結論

かなロック LED は、Windows host から返る `Kana` lock state の補助信号として使えます。
2026-06-15 の実機観測では、`Alt + KC_KANA` / `Alt + KC_HENKAN` で IME かな入力を
toggle でき、かな入力 ON 後の次の 1 key 入力で Kana bit と Host lock LEDs 表示が反応しました。
IME の内部状態そのものを即時に保証する信号ではないため、和文モールスの実送信では
hard dependency ではなく delayed safety gate / advisory state として扱います。

現時点の仮方針:

```text
和文モールス実送信の前提候補:
  IME is ON
  Kana LED state is ON after a normal-key refresh
  Host profile is Windows Microsoft IME + JIS main Kana LED capable

使うガード:
  Alt+KC_KANA or Alt+KC_HENKAN でかな入力へ寄せる
  その後に safe refresh key / 実入力 key 後の Kana LED を確認する
  Kana LED が unknown の時は warning / preview-only / 明示続行にする
```

和文モールスは、かな入力 profile を本線として設計してよい段階です。
ただし実送信は host profile opt-in と Kana LED guard を通し、状態が不明な場合は preview-only
または明示 warning に落とします。

## 背景

既存の Windows JIS main + US sub split では、通常入力は US sub keyboard、JIS 固有キーは JIS main keyboard へ
送る方針です。
`KC_KANA` は JIS main route に寄せ、JIS main 側で host Kana LED bit を受信できることを確認済みです。

確認済みの LED Output Report:

```text
bit1 / 0x02 = Caps Lock
bit4 / 0x10 = Kana
0x12        = Caps Lock + Kana
```

このため、`kana=true` は keyboard 側で観測できます。
一方で、LED report は IME toggle 直後に即時返るとは限りません。
かな入力 ON 後、次の通常キー入力で Kana bit が反応する観測があるため、
keyboard 側では Kana LED を遅延しうる advisory state として扱います。

関連:

- [../research/windows-jis-keyboard-vid-pid.md](../research/windows-jis-keyboard-vid-pid.md)
- [../input/windows-us-custom-hid-ime-routing-design.md](../input/windows-us-custom-hid-ime-routing-design.md)
- [behavior-current.md](behavior-current.md)

## 状態モデル

和文モールス側では、Kana LED を次の状態として扱います。

```text
host_kana_state:
  on      = Kana LED bit 0x10 を受信済み
  off     = Kana LED bit が clear 済み
  unknown = LED report 未受信 / host profile 不一致 / JIS main でない
```

IME の ON/OFF は `host_kana_state` と分けます。
IME ON/OFF は `KC_LANG1` / `KC_LANG2` による ImeOn / ImeOff route を優先し、
Kana LED はかな入力 mode の推定だけに使います。

実送信 gate の候補:

| 条件 | 扱い |
| --- | --- |
| IME ON + `host_kana_state=on` + host profile 明示済み | 実送信候補 |
| IME ON + かな入力へ寄せた直後 + refresh 前 | 1 key 後の Kana LED 更新待ち、または warning |
| IME ON + `host_kana_state=unknown` | preview-only または明示 warning |
| IME OFF | 実送信しない。ImeOn 操作または warning |
| host profile 不一致 | 実送信しない。profile warning |

## かな入力 guard で決めること

実機が使える時に、次の 4 点を確認します。

1. `Alt + KC_KANA` / `Alt + KC_HENKAN` で IME かな入力へ寄せられるか。
2. かな入力 ON 後、次の通常キー入力で Kana LED bit `0x10` が立つか。
3. `KC_LANG1` / `KC_LANG2` の IME ON/OFF と Kana Lock が独立しているか。
4. Kana Lock OFF 後に、同じキーがローマ字 / 英字側へ戻るか。

確認後の採用判断:

| 観測結果 | 判断 |
| --- | --- |
| Alt sequence でかな入力へ寄せられ、次キー入力後に LED と入力結果が一致する | 和文モールスはかな入力 profile + Kana LED guard を採用可能 |
| LED は立つが IME 入力が期待通りでない | LED は表示専用。実送信 gate には使わない |
| IME はかな入力になるが LED が返らない | host profile 明示 + manual mode 前提。自動判定はしない |
| host / IME 設定で挙動が変わる | default は preview-only。実送信は host profile opt-in |

## 和文モールスへの意味

かな入力 mode に頼れる場合、和文モールスの出力は「かな文字に対応する物理 key action」を送る形にできます。
この方式では、濁点、半濁点、拗音、促音、長音を host IME のかな入力規則に寄せられる可能性があります。

ただし、次の点はまだ未決です。

- 和文符号そのものを入力単位にするか、かな文字を入力単位にするか。
- 濁点 / 半濁点を独立 stroke として扱うか、合成済みかなの preview にするか。
- 拗音 / 促音 / 長音の fallback をどう表示するか。
- Morse editor で和文符号、かな出力、host IME 操作をどう見せるか。
- Kana Lock が使えない host で、romaji composition へ fallback するか。

最初の設計 TODO へ進める場合は、かな入力 profile を本線にしつつ、まず代表語 preview と
guard 表示から始めます。

代表語候補:

```text
いろは
にほん
にほんご
きょう
がっこう
ぱそこん
ちゅう
おーい
かな
もーるす
```

各語について、和文符号、かな列、必要な IME state、fallback reason を preview できることを受け入れ条件にします。

## 実機確認待ち

この検討は、実機なしでは完了判断しません。
実機が使える時に private workspace reference *(omitted from public export)* へ結果を記録します。

最小確認手順の意図:

```text
1. Alt+KC_KANA または Alt+KC_HENKAN でかな入力へ寄せる。
2. Kana LED bit 0x10 の即時変化を見る。
3. 即時変化しない場合、safe な 1 key 入力後に Kana LED bit が立つかを見る。
4. 入力欄に期待するかなが出るかを見る。
5. Alt sequence または host UI で Kana Lock を戻し、同じ key の挙動が戻るかを見る。
```

安全方針:

- host profile opt-in なしに、和文モールスの実送信 route を有効化しない。
- `host_kana_state=unknown` を実送信 OK とみなさない。
- Kana LED は「IME かな入力 mode の即時確定情報」ではなく「host lock state の遅延観測情報」として扱う。
- host profile 明示なしに Alt+KANA / Alt+HENKAN 自動切替を行わない。
