# matrixd variable scan debounce note

更新日: 2026-06-02

この文書は [scan-stability-plan.md](scan-stability-plan.md) の補足です。

## 前提

`matrixd` の scan周期は、負荷軽減のために可変にしている。

- active時は `interval_us`
- idle時は `idle_interval_us`
- deep idle時は `deep_idle_interval_us`

この可変scan周期は設計意図として維持する。
今回の対処は scan周期を固定化することではなく、可変scan周期のままでも debounce と GPIO settle が安全側に働くようにすることです。

## デバウンス中の高頻度チェックの扱い

デバウンス中に多少負荷が上がることは許容する。
実行優先度引き上げや active scan により、一回の debounce 中の raw 確認回数が増えること自体は問題ではない。
むしろ、短時間に多く確認できることは raw の安定性を細かく見られる利点がある。

問題は、確認回数が増えた時に count debounce のままだと、同じ `debounce_count` に到達する実時間が短くなり、短いノイズを press として確定しやすくなる点です。

したがって方針は次の通りです。

- デバウンス中は高頻度に raw を確認してよい。
- 高頻度チェックによる負荷増は、active / debounce 中に限れば許容する。
- ただし press / release の確定条件は「何回見たか」ではなく「同じ raw が何ms続いたか」にする。
- 確認回数は多いほどよいが、確定時刻は `debounce_ms` より早めない。

## 問題意識

count debounce は「何回連続で同じrawを読んだか」で確定する。
しかし scan周期が可変だと、同じ count でも実時間が変わる。

- activeでscanが速い時は、実効debounce時間が短くなり、短いノイズをpressとして拾いやすい。
- idle / deep idleでscanが遅い時は、実効debounce時間が長くなり、短い実入力を取りこぼしやすい。
- 実行優先度変更やLED負荷でloop間隔が揺れると、設定上の `interval_us` だけでは実効debounceを説明できない。

## 方針

- 可変scan周期は維持する。
- active / debounce 中の高頻度チェックは許容する。
- `debounce_mode=time` を追加し、press/release確定は scan回数ではなく stable raw duration で判断する。
- 既存互換のため `debounce_mode=count` は残す。
- 初期導入では既定値を既存互換にし、推奨設定として time mode を記録する。
- idle / deep idle からの初回入力取りこぼしが問題になる場合は、scan周期固定化ではなく active復帰後の短時間 burst scan を別途検討する。

## 実装時の注意

- `debounce_ms` は実時間の安定継続時間として扱う。
- raw が変化した時点で `raw_since_us` を更新する。
- 同じ raw が `debounce_ms` 以上続いた時だけ state を更新して event を送る。
- scan間隔が短くても長くても、確定条件は `now_us - raw_since_us >= debounce_ms` で説明できるようにする。
- raw確認回数が増えても、`debounce_ms` 未満では確定しない。
- idle / deep idle の負荷軽減を壊さない。

## MATRIXD_SCAN_STABILITY_PLAN への反映方針

本計画の Phase 2 は、単なる実時間debounceではなく、可変scan周期とデバウンス中の高頻度チェックを前提とした実時間debounceとして進める。
Phase 1 の test には、短周期、長周期、周期が混在する raw sequence を含める。
また、同じ `debounce_ms` の間に raw確認回数が増えても、確定時刻が早まらないことをテストする。
