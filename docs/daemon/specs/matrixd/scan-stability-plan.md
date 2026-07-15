# matrixd scan stability mitigation plan

更新日: 2026-06-02

この文書は、`matrixd` の実行優先度引き上げ後に観測された、触れていない時の短時間 Space press / release と、まれな入力取りこぼしへの本格対処計画です。

関連文書の入口は [stability-docs.md](stability-docs.md) に集約します。
実装済み内容は private workspace reference *(omitted from public export)*、実機確認手順は [real-device-stability-checklist.md](real-device-stability-checklist.md) を参照します。

フリック入力や touch-panel の入力方式には触れません。対象は `matrixd` のチャーリープレックス scan、debounce、GPIO settle、event送出の安定化です。

## 前提

実機は当面使えないため、実機観測を待たずに進めます。

そのため、最初から症状を再現して確認するのではなく、ソース上で明らかに scan周期変動へ弱い箇所を安全側に直し、静的テスト / side-effect-free test で仕様を固定します。実機確認は最後に残します。

## 観測された症状

- LED effect は multi splash。
- キーボードに触れていない時、唐突に Space bar が押され、少しして離されたように見えることがある。
- ごくまれに通常入力を取りこぼす。
- 症状が出始める前に `matrixd` の実行優先度を引き上げた。

## 現時点の有力仮説

### 1. debounce が scan count ベースで、実時間に追従していない

現在の `matrixd` は `debounce_count > 0` ならその scan 数を使い、そうでなければ `debounce_ms * 1000 / interval_us` で debounce scan 数を決める。

このため、実行優先度を上げて実 scan loop が設定上の `interval_us` より速く回ると、実効 debounce 時間が短くなる。短いノイズや settle不足が press として確定しやすくなる。

### 2. LED multi splash 中の電流変動 / CPU負荷 / GPIO settle不足

multi splash は LED 更新と合成が比較的重く、LED電流変動も大きくなりやすい。その間に GPIO level、GND、3.3V、または scan timing が揺れると、Space の GPIO pair だけが短時間 active に見える可能性がある。

### 3. row release 後の settle が固定で短い

row drive 後の `settle_us` は設定化されているが、row を input に戻した後の待ちは固定 `usleep(2)`。チャーリープレックスでは row 切り替え直後の残留電荷や pull 状態の落ち着きが効く可能性があるため、post-row settle も設定化する。

### 4. event送信失敗時の状態ずれ

送信失敗時は `cnt` と `prev_raw` はリセットするが、`state` は更新済みのまま残る。今回の短時間 Space press / release の主因ではなさそうだが、logicd再接続時の堅牢性として整理する。

## 実機なしで進める方針

観測ログから始めず、以下の順で安全側に進める。

1. `matrixd` の debounce 判定を side-effect-free helper へ切り出し、テスト可能にする。
2. 実時間 debounce mode を追加する。
3. `post_row_settle_us` を設定化する。
4. socket送信失敗時に state を先に更新しない、または失敗時に rollback する。
5. `matrixd/README.md` と TODO に、実機確認は後続として残す。

## 実装計画

### Phase 1: debounce helper の分離

目的:

- GPIO実機なしでも debounce の挙動をテストできるようにする。
- 既存の count debounce と新しい time debounce の仕様差分を固定する。

実装候補:

- `matrixd` 内に小さな pure helper を作る。
- 可能なら `matrixd/debounce.h` / `matrixd/debounce.c` に分離する。
- test binary または Python static test から、raw sequence と時刻を与えて press / release 確定を確認する。

受け入れ条件:

- 既存 count debounce の振る舞いをテストで固定できる。
- raw が短時間だけ active になっても、time debounce では `debounce_ms` 未満なら press にならない。
- release も同じく `debounce_ms` 以上安定してから確定する。

### Phase 2: 実時間 debounce mode の追加

目的:

- 実行優先度や scan周期の変動により、debounce の実時間が短くなる問題を避ける。

実装候補:

- config に `debounce_mode` を追加する。
  - `count`: 既存方式。
  - `time`: 実時間方式。
- 各 key に raw 値が変化した時刻を保持する。
- raw が変化したら `raw_since_us` を更新する。
- 同じ raw が `debounce_ms` 以上続いた時だけ、state と違えば event を確定する。
- 初期導入では既定を `count` にして互換性を守る。
- 推奨設定として `debounce_mode=time` を docs に記録し、実機確認後に既定変更を判断する。

受け入れ条件:

- scan loop が速くなっても `debounce_ms` の実時間が短くならない。
- 既存の `debounce_count` 指定環境を壊さない。
- `debounce_mode=count` では既存方式を維持する。
- `debounce_mode=time` では scan間隔のばらつきに対して stable raw duration で判定する。

### Phase 3: post-row settle 設定化

目的:

- rowをinputへ戻した直後の固定 `2us` を調整可能にし、チャーリープレックスの行間干渉を抑える。

実装候補:

- config に `post_row_settle_us` を追加する。
- 既定値は既存互換の `2`。
- `settle_us` と合わせて `matrixd/README.md` に調整順を記録する。

受け入れ条件:

- 既存設定では挙動が変わらない。
- configで post-row settle を増やせる。
- static test で `post_row_settle_us` の config 読み込みが固定される。

### Phase 4: socket送信失敗時の state 更新順序見直し

目的:

- event送信失敗やlogicd再接続で、`matrixd` internal state と logicd 側 state がずれる可能性を減らす。

実装候補:

- `state[r][c] = new_raw` を `sock_send_event()` 成功後に移す。
- 送信失敗時は state を変更せず、次回 scan で再判定可能にする。
- reconnect 後の扱いは、既存protocolを壊さず、必要なら全release安全化を別TODOに分ける。

受け入れ条件:

- send失敗で未送信の press / release が internal state だけに反映されない。
- 次の安定scanで再送または安全側に解消できる。
- 既存 packet format は変更しない。

### Phase 5: 将来の観測ログ

実機が使えるようになったら、必要に応じて debug log を追加する。

ただし、当面は実機なしで進めるため、debug log は最初の必須実装にしない。
実時間 debounce と post-row settle 設定化を先に入れる。

## 実機確認が可能になった時の確認条件

1. LED OFF。
2. 単色固定。
3. multi splash 低輝度。
4. multi splash 通常輝度。
5. matrixd優先度 通常。
6. matrixd優先度 引き上げ。

観測項目:

- Space ghost press / release の発生有無。
- 入力取りこぼしの有無。
- scan loop min / avg / max。
- debounce確定までの実時間。
- CPU / RSS / journal warning。
- LED effect の見た目劣化や入力遅延。

## 当面の安全な暫定設定候補

本格修正前の切り分けとして、実機では以下を一時的に試す価値がある。

```json
{
  "debounce_count": 20,
  "settle_us": 50
}
```

ただし、これは根本対処ではない。
実時間 debounce と post-row settle 設定化を入れるまでの切り分け用とする。

## 触らない範囲

- touch-panel flick / swipe / フリック入力。
- kiosk touch input の PointerEvent 処理。
- Vial GUI / touch-panel Vial layout。
- LED effect の表現そのもの。

今回の範囲は、LED負荷中でも `matrixd` が誤入力しないようにする scan安定化に限定する。
