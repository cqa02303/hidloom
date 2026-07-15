# matrixd runtime priority ideal conditions

更新日: 2026-06-02

この文書は [scan-stability-plan.md](scan-stability-plan.md) と
[variable-scan-debounce-note.md](variable-scan-debounce-note.md) の補足です。

`matrixd` の実行優先度引き上げ、可変scan周期、debounce、socket送信、`logicd` との関係について、
実装時に目指す理想条件を固定します。

## 基本方針

- `matrixd` は物理入力を最初に拾う daemon なので、通常daemonより優先する。
- ただし `matrixd` だけを無制限に最優先化して、受け側の `logicd` が動けなくなる状態は避ける。
- scan周期の可変化は負荷軽減のための設計として維持する。
- デバウンス中の高頻度raw確認は許容する。
- press / release の確定は、raw確認回数ではなく実時間の安定継続で判断する。
- フリック入力、touch-panel PointerEvent、Vial layout、LED effect表現そのものには触れない。

## 理想条件

### 1. 優先度階層

理想は、入力経路のdaemonが以下の順に処理できること。

```text
matrixd >= logicd input path > usbd/btd output path > ledd/httpd/その他UI系
```

`matrixd` は高優先度でよいが、`logicd` がイベントを受け取って処理できないほど強くしない。
`matrixd` が `SCHED_FIFO` を使う場合でも、priority 99 固定を前提にしない。

検討候補:

- `matrixd` のRT priorityを少し下げる。
- `logicd` の入力処理だけを適度に優先する。
- `ledd` や `httpd` は入力経路より低優先にする。
- `matrixd` と `logicd` の優先度差をREADMEに明記する。

受け入れ条件:

- `matrixd` が高負荷時にもscanを継続できる。
- `logicd` がsocket受信とHID report生成を極端に遅らせない。
- `ledd` multi splash中でも入力経路が飢餓状態にならない。

### 2. socket送信

`matrixd` から `logicd` へのイベント送信は、入力経路の要所です。
blocking `send()` が長時間止まると、scanそのものが止まる可能性があります。

理想:

- 通常時は4 byte packetを確実に送る。
- 送信先が詰まった場合、`matrixd` が長時間停止しない。
- 送信失敗時に、未送信eventだけが `matrixd` internal state に反映されない。

検討候補:

- state更新を `send()` 成功後に移す。
- socketをnon-blocking化するか、短いtimeout相当の安全処理を入れる。
- 送信失敗時は reconnect し、次の安定scanで再判定できるようにする。
- 必要ならlogicd側で再接続時に全releaseを行う。

受け入れ条件:

- `logicd` 側が一時的に遅れても `matrixd` が無期限に詰まらない。
- press / release の片側だけが内部状態に残らない。
- packet formatは現行4 byteを維持する。

### 3. 可変scan周期とdebounce

可変scan周期は維持する。
`interval_us` / `idle_interval_us` / `deep_idle_interval_us` の切り替えは負荷軽減に必要です。

理想:

- active時は高頻度にrawを確認してよい。
- debounce中は多少負荷が上がってもよい。
- raw確認回数が増えても、`debounce_ms` 未満ではpress / releaseを確定しない。
- idle / deep idleでscan回数が減っても、短い入力を過度に取りこぼさない。

検討候補:

- `debounce_mode=time` を追加する。
- `debounce_ms` を実時間の安定継続時間として扱う。
- raw change後はactive intervalへ戻す既存方針を維持する。
- 必要なら将来 `wake_scan_burst_ms` を追加する。

受け入れ条件:

- scan間隔が短くても長くても、確定条件を `now - raw_since >= debounce_ms` で説明できる。
- 優先度引き上げでraw確認回数が増えても、確定時刻が早まらない。
- idle中の初回入力を取りこぼしにくい設計が残っている。

### 4. GPIO settle

チャーリープレックスではrow切り替え時の残留電荷、pull状態、配線容量の影響を受けやすい。

理想:

- row drive後のsettleを設定できる。
- row release後のsettleも設定できる。
- 既存設定では挙動を変えず、必要な環境だけ調整できる。

検討候補:

- 既存 `settle_us` を維持する。
- `post_row_settle_us` を追加する。
- READMEに `settle_us` と `post_row_settle_us` の調整順を記録する。

受け入れ条件:

- row間干渉を疑う時に、コード変更なしでsettleを調整できる。
- デフォルトは現行互換。
- 設定値の読み込みをstatic testで固定する。

### 5. busy loop保護

高優先度daemonでsleepが0に近い状態になると、他daemonを圧迫する。

理想:

- `SCHED_FIFO` や高nice時でも、設定ミスでbusy loopしない。
- 最低sleepまたは安全な下限を持つ。
- debug用途以外では、完全な無休止scanを避ける。

検討候補:

- `interval_us` / idle interval の最小値を検証する。
- config load時に危険な0や負値をwarningまたは下限丸めする。
- `scan_sleep_us()` にRT時の安全下限を持たせるか検討する。

受け入れ条件:

- 設定ミスでCPUを占有し続けない。
- 入力遅延を増やしすぎない。
- 高優先度設定と負荷軽減設計が両立する。

## 実装順の推奨

1. debounce helper分離とテスト追加。
2. `debounce_mode=time` 追加。
3. `post_row_settle_us` 追加。
4. send成功後にstate更新するように整理。
5. 優先度階層とbusy loop保護の設定・ドキュメント整理。
6. 実機が使えるようになったら、multi splash / Space / 取りこぼし再確認。

## 実機なしでの判定

実機がない間は、以下を完了条件にする。

- 設定の後方互換が保たれている。
- debounceのraw sequence testで、短周期・長周期・混在周期の挙動が説明できる。
- send失敗時に未送信eventがinternal stateだけに残らないことをコード上で確認できる。
- `matrixd` / `logicd` の優先度階層方針がREADMEに記録されている。
