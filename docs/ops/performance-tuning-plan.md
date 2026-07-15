# Performance Tuning Plan

更新日: 2026-05-24

この文書は、ドキュメント棚卸し後に進める速度・メモリ使用量削減の入口です。
方針は「測定してから最適化する」です。体感や推測だけで daemon の構造を変えず、
baseline を残してから小さく変更し、差分と回帰テストで確認します。

## 目的

- 常時起動する daemon の CPU 使用率と RSS を把握する。
- 高頻度 path の余分な allocation、JSON 組み立て、log 出力、socket retry を減らす。
- LED / key event / status polling のような体感に近い経路を、挙動を変えずに軽くする。
- 速度改善と省メモリ化の効果を、次回以降も比較できる形で残す。

## 対象範囲

最初に見る対象:

- `ledd`: effect render loop、direct-frame、VialRGB renderer、animation overlay。
- `logicd`: key event dispatch、macro / script dispatch、output routing、通知 socket。
- `httpd`: `/api/status` polling、layout / lighting JSON、static asset response。
- `btd`: reconnect / pairing 状態確認、report send path。
- `spid`: high-rate motion polling と mouse HID report 変換。

必要になったら見る対象:

- `i2cd`: OLED alert/status rendering、analog stick polling。
- `viald`: Raw HID / VialRGB bridge。
- `matrixd`: scan loop。既存の debounce / timing を壊さない範囲で扱う。

## Baseline

最初の作業は、変更前の状態を保存することにする。

```bash
python3 script/test_validation_suite.py
python3 tools/perf_baseline.py --output /tmp/hidloom-perf-before.md --run-validation
systemctl --failed
systemctl status hidloom-hidd hidloom-uidd hidloom-outputd hidloom-logicd-core logicd-companion ledd httpd viald i2cd btd matrixd --no-pager
journalctl -u hidloom-hidd -u hidloom-outputd -u hidloom-logicd-core -u logicd-companion -u ledd -u httpd -u btd -u spid -n 200 --no-pager
ps -o pid,comm,rss,pcpu,args -C python3 -C hidloom-hidd -C hidloom-uidd -C hidloom-outputd -C hidloom-logicd-core -C ledd -C httpd -C viald -C btd -C spid -C i2cd
```

`pidstat` や `perf` が使える環境では補助的に使ってよいが、新しい package を前提にしない。
実機での長時間確認が必要な場合は、`top` / `ps` / `journalctl` で取れる指標を優先する。
`tools/perf_baseline.py` は command の失敗も report に残して続行するため、実機以外で
事前確認してもよい。

## 優先順

| 優先度 | 項目 | 見るもの | 完了条件 |
|---|---|---|---|
| P1 | baseline 計測入口 | CPU / RSS / failed service / warning log | before/after を比較できるメモまたは helper を残す |
| P1 | `ledd` 高頻度 path | render loop、direct-frame、overlay 復帰、frame buffer reuse | 見た目を変えずに allocation または CPU が下がる |
| P1 | `logicd` key event path | dispatch、output routing、socket reconnect、log | key timing を変えずに hot path の余分な処理を減らす |
| P2 | `httpd` status / JSON | `/api/status`、layout、lighting API、static header | polling 時の処理量を減らし UI 表示を維持する |
| P2 | `btd` / `spid` loop | reconnect/status loop、motion polling | idle 時の無駄な wakeup と log を減らす |

## HID mouse flush tuning candidate

Linux HID gadget の `/dev/hidgX` は、USB host の IN polling token を userspace callback として直接通知する interface ではない。
現実的な候補は、USB poll そのものではなく、HID gadget char device の writable/backpressure を見る方式にすること。

現在の SPID mouse path は `logicd.spid_motion.SpidMotionAccumulator` で dx / dy / wheel を合算し、
`LOGICD_SPID_MOTION_OUTPUT_HZ` の timer で flush している。既定値は 125Hz。
これは report 数削減には効くが、USB host の消費タイミングと完全には同期しない。

次の tuning 候補:

- mouse 専用の `MouseReportScheduler` を作り、SPID / joystick / mouse key の delta を同じ accumulator に集約する。
- 近い TODO として、まず analog stick / joystick 由来の mouse report を SPID mouse sensor と同じ scheduler に合流させる。
  現状の joystick mouse event は発生時に `mouse_write_fn` へ直接 report を書くため、SPID 側の coalesce / rate-limit / stale drop と同じ制御を受けていない。
- gadget 出力では `/dev/hidg0` を `poll()` / `select()` / asyncio writer readiness 相当で監視し、書ける状態になった時点の最新 accumulator を 1 report だけ pop する。
- HID gadget 側へ古い mouse report を複数 queue しすぎない。queue depth は実質 1 に近く扱う。
- writable が来ても accumulator が空なら report を送らない。ただし button release など state transition は必ず送る。
- Bluetooth HID や debug output は USB backpressure と同じ前提にしない。backend ごとに flush policy を分ける。
- fallback として timer flush は残し、`LOGICD_SPID_MOTION_OUTPUT_HZ` は比較用の既定値として維持する。

受け入れ条件:

- 高頻度 SPID motion で stale cursor movement が増えない。
- 現行 timer flush と比較して report 数、cursor latency、drop counter を記録できる。
- keyboard / consumer report と Vial Raw HID bridge に副作用がない。
- `script/test_logicd_spid_motion.py` に accumulator / flush policy の回帰テストを追加する。

## Guardrails

- HID report timing、InteractionEngine の判定時間、default key behavior は測定なしに変更しない。
- daemon を C へ書き換えるような大きな変更は、Python 側の hot spot を測ってから判断する。
- 読みやすさを大きく落とす micro optimization は避ける。
- 最適化で log を消す場合も、異常検知に必要な warning / error は残す。
- 実機依存の改善は、local regression と実機 smoke の両方で確認する。

## 受け入れ条件

- 変更前後の CPU / RSS / log / test 結果が残っている。
- `python3 script/test_validation_suite.py` が通る。
- 対象 daemon の局所 test、またはそれに相当する smoke test が通る。
- `docs/CURRENT_STATUS.md` と `docs/TODO_PRIORITY.md` に、次に見る対象と結果を反映する。

## 次の一手

1. 実機で `tools/perf_baseline.py` を使って baseline を取る。
2. 常時起動かつ高頻度の `ledd` / `logicd` から最初の対象を選ぶ。
3. 小さい差分で 1 件だけ改善し、before/after と回帰テストを残す。

## Fast boot / Buildroot experiment

2026-06-17 時点では、Raspberry Pi OS 側の service 削減と daemon hot path tuning はかなり進んだため、
次の比較対象として Buildroot image を別 microSD で試す価値がある。
ただし現行構成は Python / BlueZ / HTTP / Vial / OLED / LED 依存が多いため、完全移植から始めず、
USB HID gadget と最小 key path だけの phase で `usable keyboard` までの時間を測る。
ここで見るのは OS の total boot time ではなく、`matrixd` -> `logicd` -> HID report の最小 path が
成立するまでの readiness である。GUI、network、HTTP、Vial、Bluetooth、OLED、LED が後から立ち上がっても、
keyboard input path が先に使えるなら fast boot profile として成功扱いにする。

詳細な phase、測定 marker、成功 / 中止基準は
[buildroot-fast-boot-experiment.md](buildroot-fast-boot-experiment.md) に置く。
現行 OS 側の marker 採取には `tools/boot_marker_baseline.py` を使い、
`/tmp/hidloom-boot-rpi-os-baseline.md` のような Markdown report を残す。
Buildroot M1 側は `build/buildroot/hidloom-external/configs/hidloom_m1_defconfig` から
USB HID gadget only image を作り、host 側 enumerate は `tools/usb_enumeration_watch.py` の
`+seconds` timestamp 付き report と突き合わせる。

## 2026-05-24 baseline / first tuning

実機 `<keyboard-host>` で次の report を取得した。

- before: `/tmp/hidloom-perf-before.md`
- after: `/tmp/hidloom-perf-after-output-switch-log.md`

before では `logicd.output_switch` の `USB接続チェック` DEBUG log が 120 行 journal sample 内に
48 件出ていた。最初の tuning として、USB 接続状態、mode、manual lock 状態が変わらない間は
同じ DEBUG log を繰り返さないようにした。

after では再起動後 PID の `USB接続チェック` は起動直後の 1 件だけになり、
`2026-05-24 11:43:00` 以降の追加出力は 0 件だった。`python3 script/test_validation_suite.py` は
実機でも通過した。

次に見る候補:

- `httpd`: RSS が約 33 MiB で、HTTP UI 操作中の `/api/status` polling と JSON 生成を見る。
- `ledd`: effect loop は約 8% 前後。見た目を変えずに frame buffer reuse / sleep 精度を確認する。

## 2026-05-24 matrixd adaptive idle wait trial

`matrixd` に、無操作時だけ scan loop 後の wait を伸ばす adaptive idle wait を追加した。
active 中の `interval_us=1000` は維持し、raw matrix 変化または press / release event を
検出したら即 fast scan へ戻る。

既定値:

- 100ms 無変化後: `idle_interval_us=2000`
- 500ms 無変化後: `deep_idle_interval_us=4000`

目的は、最初の押下遅延を数 ms 程度に抑えながら idle CPU を下げること。
実機では build / restart 後に、`matrixd` CPU、連打、roll、combo、tap-hold の体感を確認する。

実機 `<keyboard-ip>` に反映し、`matrixd` を再ビルド・再起動した。
`systemctl cat matrixd` で service が repo の `config/default/matrixd.json` を直接読んでいることを確認済み。
無操作状態の `ps -C matrixd -o pid,comm,rss,pcpu,args` では、5 秒間隔の 3 samples が
6.1% / 6.1% / 6.0% だった。以前の `/tmp/hidloom-perf-after-matrixd-scan.md` での約 11.6% から、
idle CPU はおおむね半分近くまで下がった。

local と実機の両方で `python3 script/test_validation_suite.py` は通過した。

## 2026-06-02 matrixd time debounce auto smoke

`<keyboard-host>` (`pi@<keyboard-ip>`) に `main` (`9002a3a`) を反映し、
`daemon/matrixd/matrixd` を Pi 上で ARM aarch64 binary として rebuild した。

設定:

- `debounce_mode=time`
- `debounce_ms=5`
- `post_row_settle_us=2`
- `matrixd.service`: `Nice=-20`, `CPUSchedulingPolicy=fifo`, `CPUSchedulingPriority=99`

自動観測:

- Multisplash 低輝度 (`mode=40`, `v=64`) を15秒。
- Multisplash 通常輝度 (`mode=40`, `v=180`) を15秒。
- どちらも `save=false` で一時反映し、元の LED state へ戻した。

結果:

- `matrixd` journal で `デバウンス方式: time (debounce_ms=5)` と `logicd に接続しました` を確認。
- `matrixd` 送信失敗、`logicd` input path warning、`ledd` 異常 log は 0 件。
- process snapshot では `matrixd` CPU 約 4.4%、RSS 約 1.5 MiB。
- 同じ観測中、`logicd` は約 2.8-3.1%、`ledd` は約 3.1-3.5%。
- report は実機の `/tmp/hidloom-smoke/perf-matrixd-time-2026-06-02.md`。

追加比較:

| 条件 | service / log | matrixd CPU / RSS |
|---|---|---|
| `count`, `post_row_settle_us=2`, RT99 | 主要 service active、異常 log 0 件 | 約 5.2% / 1.5 MiB |
| `time`, `post_row_settle_us=5`, RT99 | 主要 service active、異常 log 0 件 | 約 5.0% / 1.5 MiB |
| `time`, `post_row_settle_us=10`, RT99 | 主要 service active、異常 log 0 件 | 約 4.9% / 1.5 MiB |
| `time`, `post_row_settle_us=2`, RT off | 主要 service active、異常 log 0 件 | 約 4.5% / 1.5 MiB |

追加比較 report は実機の `/tmp/hidloom-smoke/matrixd-compare-2026-06-02.txt`。
RT off 比較後は drop-in を削除し、`matrixd` は `Nice=-20`, `CPUSchedulingPolicy=fifo`,
`CPUSchedulingPriority=99` へ戻した。

本命設定 `time`, `debounce_ms=5`, `post_row_settle_us=2`, RT99 で Multisplash 通常輝度を
60 秒流した追加観測でも、主要 service は active、異常 log は 0 件。
report は実機の `/tmp/hidloom-smoke/matrixd-long-idle-2026-06-02.txt`。

同じ本命設定で socket 側の idle ghost も分けて観測した。`/tmp/key_events.sock` の 90 秒監視では
`key_event_count=0`、`/tmp/ledd_events.sock` の 90 秒監視では初期/status message 3 件のみで
`key_message_count=0`。どちらも異常 log は 0 件。report は実機の
`/tmp/hidloom-smoke/key-events-idle-multisplash-2026-06-02.txt` と
`/tmp/hidloom-smoke/ledd-events-idle-multisplash-2026-06-02.txt`。

同じ観測を再実行できるように `tools/matrixd_stability_smoke.py` を追加した。LED effect を
一時適用しながら `key_events.sock` / `ledd_events.sock` / service active state / `matrixd` priority /
process snapshot / daemon journal を Markdown report にまとめ、key event、`t=key` message、warning/error 系 log、
inactive service は既定で失敗扱いにする。

helper 実走では、Multisplash 低輝度 (`v=64`) 20 秒、通常輝度 (`v=180`) 20 秒、
通常輝度 (`v=180`) 60 秒はいずれも pass。通常輝度 60 秒は `key_event_count=0`,
`key_message_count=0`, `interesting_log_count=0` で、report は実機の
`/tmp/hidloom-smoke/matrixd-stability-normal-tool-60s-2026-06-02.md`。追加の通常輝度 180 秒も
`key_event_count=0`, `key_message_count=0`, `interesting_log_count=0` で pass。report は実機の
`/tmp/hidloom-smoke/matrixd-stability-normal-tool-180s-2026-06-02.md`。一方、helper 初回の通常輝度
30 秒 run では `key_event_count=71`, `key_message_count=71` を検出したが、直後の再走と 180 秒 run では再現しなかった。
未再現 transient として、物理 idle 状態の確認で追う。

追加切り分けでは、RT off 60 秒で `key_event_count=24`、RT99 復帰後の通常輝度 (`v=180`) 60 秒で
`key_event_count=74`、同条件の再チェックで `key_event_count=122` を検出した。一方、元 effect
(`speed=32`, `h=183`, `s=163`, `v=180`) 60 秒、`v=64` 60 秒、`v=128` 60 秒、
`v=160` 60 秒、`v=170` 60 秒はいずれも `key_event_count=0`。RT priority 単独よりも、
`mode=40`, `speed=128`, `h=80`, `s=255`, `v=180` 付近の brightness / current 負荷が疑わしい。
`tools/matrixd_stability_smoke.py` の既定 brightness は最終的に `v=160` に下げた。`v=170` 既定値の 60 秒 smoke は
`key_event_count=0`, `key_message_count=0`, `interesting_log_count=0` で pass。report は実機の
`/tmp/hidloom-smoke/matrixd-stability-default-v170-tool-60s-2026-06-02.md`。`v=170` guard 反映後に
`--value 180` を再確認したところ、effective `v=170` でも 60 秒で `key_event_count=36` を検出した。
直後の `v=160` 60 秒は `key_event_count=0` で pass。report は実機の
`/tmp/hidloom-smoke/matrixd-stability-splash-cap-v160-after-restart-60s-2026-06-02.md`。
次は物理 idle 状態の目視確認と、`v=160` を一時的な安全上限にできるかの判断を行う。

通常の VialRGB state 経路には safety guard を入れ、splash 系 mode (`39..42`) の `v` を `160` に丸める。
対象は `logicd` の LED state 正規化と HTTP Lighting update で、direct-frame / 低レベル検証 tool は対象外にする。
`v=160` guard 反映後の `--value 180` request は effective `v=160` となり、60 秒で
`key_event_count=0`, `key_message_count=0`, `interesting_log_count=0`。report は実機の
`/tmp/hidloom-smoke/matrixd-stability-splash-cap-v160-v180-request-60s-2026-06-02.md`。

未判断:

- 物理操作中の Space ghost 非再現。
- 通常入力の取りこぼし非再現。
- `debounce_mode=time` の tap / hold / combo 体感遅延。
- high-brightness `v=180` key burst の物理 idle 再現性。
- `v=160` safety guard の物理操作確認。
- RT priority rollback 時の物理操作差。

## 2026-05-24 httpd status process scan tuning

`/api/status` は daemon 生存確認のために `/proc/*/cmdline` を読んでいる。
従来は daemon ごとの `check_process()` 呼び出しで `/proc` を複数回走査していたため、
`process_statuses()` を 1 回の `/proc` 走査で全 daemon を判定する形へ変更した。

実機で `httpd` を再起動し、`/api/status` の `processes` と `output.display_label` が
従来通り取得できることを確認した。

report:

- after: `/tmp/hidloom-perf-after-httpd-process-scan.md`

結果:

- `httpd` CPU は `/tmp/hidloom-perf-after-matrixd-scan.md` の約 11.0% から、
  `/tmp/hidloom-perf-after-httpd-process-scan.md` では約 8.8% 前後へ下がった。
- RSS は再起動直後や UI 状態で揺れるため、この時点では CPU 側の改善として扱う。
- `python3 script/test_validation_suite.py` は実機でも通過した。

次に見る候補:

- `ledd`: effect loop は約 8% 前後。見た目を変えずに frame buffer reuse / sleep 精度を確認する。
- `httpd`: RSS の長めの観測と、`bluetoothctl` 呼び出し頻度の扱いを必要に応じて見る。

## 2026-05-24 ledd idle splash tuning

既定 Lighting の `Multisplash` (`mode=40`) は、スプラッシュがない待機中でも
60fps で全 LED を描き直していた。待機中のフレームは同じなので、スプラッシュが空の間は
静止フレームを 1 回だけ `show()` し、キー入力でスプラッシュが追加されたら従来通りの描画へ
戻るようにした。

実機で `ledd` を再起動し、`/api/status` で active 状態を確認した。

report:

- after: `/tmp/hidloom-perf-after-ledd-idle-splash.md`

結果:

- `ledd` CPU は `/tmp/hidloom-perf-after-httpd-process-scan.md` の 8.0% から、
  `/tmp/hidloom-perf-after-ledd-idle-splash.md` では 3.4-3.5% へ下がった。
- RSS は約 15 MiB のままで大きな変化なし。
- `python3 script/test_validation_suite.py` は local と実機の report 内 validation で通過した。

次に見る候補:

- `httpd`: RSS の長めの観測と、`bluetoothctl` 呼び出し頻度の扱いを必要に応じて見る。
- `i2cd`: ADS1115 / OLED status loop の CPU が長時間では目立つため、次に測定する候補。

## 2026-05-24 i2cd ADS1115 polling tuning

`i2cd` は ADS1115 analog stick を低レート control event として扱うが、実機 report では
CPU が 18.5% 前後で安定していた。最初に X/Y の ADC 読みで 2 回呼んでいた
`asyncio.to_thread()` を 1 回にまとめ、threadpool 往復を半分にした。
さらに既定 `analog_stick.poll_interval` を 0.02 秒にし、約 50Hz の低レート入力として扱う。

report:

- after thread grouping: `/tmp/hidloom-perf-after-i2cd-adc-thread.md`
- after interval tuning: `/tmp/hidloom-perf-after-i2cd-adc-interval.md`

結果:

- `i2cd` CPU は `/tmp/hidloom-perf-after-ledd-idle-splash.md` の 18.5% から、
  thread grouping 後は 17.1-17.4% へ下がった。
- `poll_interval=0.02` 後は 11.8-12.0% へ下がった。
- RSS は再起動後の状態差が大きいため、この時点では CPU 側の改善として扱う。
- `python3 script/test_validation_suite.py` は local と実機の report 内 validation で通過した。

次に見る候補:

- `httpd`: RSS の長めの観測と、`bluetoothctl` 呼び出し頻度の扱いを必要に応じて見る。
- `btd`: connected / pairing idle loop の wakeup と log を測定してから判断する。

## 2026-05-24 btd status query log tuning

`btd` は `/api/status` などから runtime status を問い合わせられるたびに Unix socket
client の `connected` / `disconnected` を INFO log へ出していた。HTTP UI が開いている状態では
この status query が数秒おきに発生するため、通常運用の接続/切断ログは DEBUG へ下げた。

試したが採用しなかった変更:

- `BTD_ADVERTISING_MONITOR_INTERVAL=3`
  - pairing advertising の `bluetoothctl show` 間隔を伸ばす案。
  - `/tmp/hidloom-perf-after-btd-advertising-monitor.md` では CPU 改善として確認できず、
    fresh setup / 実機 drop-in ともに `1` 秒へ戻した。

report:

- after log tuning: `/tmp/hidloom-perf-after-btd-status-log-interval1.md`

結果:

- `client connected` / `client disconnected` の INFO 連発は、再起動後の新 PID では出なくなった。
- CPU は再起動直後の条件差が大きく、`/tmp/hidloom-perf-after-i2cd-adc-interval.md` の 1.9% より
  after report の方が高く出たため、CPU 改善としては数えない。
- `python3 script/test_btd_suite.py` と `python3 script/test_validation_suite.py` は local と実機で通過した。

次に見る候補:

- `httpd`: RSS の長めの観測と、status polling 中の runtime query 頻度を測る。
- `btd`: 追加で触る場合は、CPU ではなく status query の呼び出し元 (`httpd`) と合わせて見る。

## 2026-05-24 btd disconnected idle backoff

実機確認で、未接続時でも `dbus-daemon` が 5-6% 程度出ることがあった。
常用設定では `btd` が `BTD_ADVERTISING_MONITOR_INTERVAL=1` で `bluetoothctl show`、
`BTD_DISCONNECT_MONITOR_INTERVAL=2` で `bluetoothctl devices Connected` を周期実行しているため、
host 未接続・pairing なしの状態では BlueZ / D-Bus polling が残っていた。

方針:

- 接続中、pairing 中、reconnect advertising 中は従来の短い監視間隔を維持する。
- `logicd` の pairing on/off から btd へ同期通知し、通常の pairing 操作では idle poll を待たない。
- 未接続かつ advertise していない idle 状態では、advertising / disconnect monitor を
  `60` 秒間隔へバックオフする。
- 外部から直接 `bluetoothctl pairable on` した場合は最大で idle interval 分反応が遅れる可能性があるが、
  キー操作 / HTTP API 経由の pairing は即時同期する。

## 2026-05-24 httpd status runtime query cache

`/api/status` は Bluetooth 状態のために `bluetoothctl show`、`bluetoothctl devices`、
device ごとの `bluetoothctl info`、さらに `btd` runtime status の Unix socket query を
毎回実行していた。HTTP UI の status polling では数秒以内に同じ問い合わせが重なるため、
通常の `/api/status` では Bluetooth snapshot と `btd` runtime snapshot を 5 秒だけ再利用する。

操作直後の stale 表示を避けるため、Bluetooth pairing / forget API が成功時に返す
`bluetooth` field は cache を bypass する。

report:

- env cache only: `/tmp/hidloom-perf-after-httpd-env-cache.md`
- after runtime query cache: `/tmp/hidloom-perf-after-httpd-status-cache.md`
- after warm runtime query cache: `/tmp/hidloom-perf-after-httpd-status-cache-warm.md`

結果:

- `bluetoothctl` 群と `btd` socket query の短時間重複を local test で抑制確認した。
- 実機では `/api/status` smoke と `python3 script/test_http_system_status.py` が通過した。
- `httpd` CPU は再起動直後の累積平均で大きく揺れた。warm report では 7.5-7.8% 程度で、
  env cache only の 8.9-9.2% より低いが、古い別条件 report の 5.7% とは直接比較しない。
  この変更は CPU 改善値ではなく、status polling の外部 query 削減として採用する。

次に見る候補:

- `httpd`: RSS の長めの観測、または WebSocket / browser polling 時の CPU を観測する。
- `i2cd` / `matrixd`: 追加で触る場合は入力 latency を変えない小さい差分に限定する。

## 2026-05-24 httpd RSS watch

`httpd` の RSS は再起動直後や UI 状態で揺れていたため、短い after report だけでは
増加傾向か起動条件差かを判断しにくかった。実機で `/api/status` を 30 秒ほど polling
しながら、`tools/perf_baseline.py` の 19 samples / 10 sec interval で約 3 分観測した。

report:

- RSS watch: `/tmp/hidloom-perf-httpd-rss-watch-3min.md`

結果:

- `httpd` RSS は 45,856 KiB から 45,836 KiB の範囲で横ばいだった。
- `httpd` CPU は 5.6-6.2% 程度で推移し、直前の warm runtime query cache report より
  落ち着いた値になった。
- `/api/status` polling だけでは RSS 増加傾向は見えなかったため、現時点で memory leak
  対応の TODO にはしない。
- `spid` は未使用構成のため inactive のまま。ほかの主要 daemon は active。

次に見る候補:

- `httpd`: ブラウザを開いた状態の WebSocket / layout repaint / `/api/layout` 取得頻度を見る。
- `logicd`: key event path の allocation や script dispatch は、実打鍵シナリオを決めてから測る。

## 2026-05-24 httpd browser polling watch

ブラウザを開いた状態で常時動く HTTP polling のうち、Keyboard タブは
`/api/keymap/active` を 250ms 間隔で、内部キーテスター ON 時は `/api/matrix` を
80ms 間隔で取得する。実機でそれぞれ curl による同等頻度 polling を流しながら、
`tools/perf_baseline.py` で観測した。

report:

- active layer polling: `/tmp/hidloom-perf-httpd-active-layer-polling.md`
- matrix tester polling: `/tmp/hidloom-perf-httpd-matrix-tester-polling.md`

結果:

- `/api/keymap/active` 4Hz 相当では `httpd` CPU は 4.4-4.5% 程度だった。
- `/api/matrix` 12.5Hz 相当では `httpd` CPU は 4.6-4.7% 程度だった。
- どちらも warning / error の増加はなく、この範囲の browser polling は現時点で
  追加 tuning 対象にしない。
- `/api/status` には重複 fetch guard を追加し、前回 fetch が遅れている時に次の polling を
  積み上げないようにした。

次に見る候補:

- `logicd`: key event path / output fan-out / script dispatch の測定シナリオを決める。
- `httpd`: 実ブラウザで layout repaint や長時間タブ滞在の違和感が出た時だけ再測定する。

## 2026-05-25 polling log noise tuning

実機で次の短時間 baseline を取り、ブラウザ由来の高頻度 polling が journal に残る状況を確認した。

report:

- before: `/tmp/hidloom-perf-2026-05-25-before-next.md`

結果:

- `httpd` は `/api/keymap/active` 成功 access log を繰り返していた。
- `logicd` は `/api/keymap/active` / `/api/matrix` 由来の Ctrl socket 接続/切断を、
  service の `LOG_LEVEL=DEBUG` 設定下で journal に出していた。
- `_HttpAccessLogger` の抑制対象を `/api/status` だけでなく
  `/api/keymap/active` / `/api/matrix` の 2xx/3xx 成功 response へ広げた。
- Ctrl socket の通常接続/切断ログは `_TRACE_LEVEL=5` へ落とし、DEBUG 運用でも出ないようにした。
- 実機で `httpd` / `logicd` を再起動後、`/api/keymap/active` と `/api/matrix` を連続取得しても
  `api/keymap/active` / `api/matrix` / `Ctrl client` の journal 行が出ないことを確認した。
- ローカルと実機の `python3 script/test_validation_suite.py` は通過した。

この変更は CPU の大幅改善を狙うものではなく、通常表示中の journal 書き込みと調査時ノイズを減らす
低リスク tuning として採用する。4xx/5xx の access log と ctrl command の warning は引き続き残す。

追加確認:

- after restart 後の短時間 baseline: `/tmp/hidloom-perf-2026-05-25-next2-before.md`
- Ctrl socket 接続/切断は消えたが、`logicd.ctrl_keymap` の
  `ctrl G: keymap sent` DEBUG が `/api/keymap/active` polling に合わせて残っていた。
- `ctrl G` / `ctrl K` の正常応答ログを `_TRACE_LEVEL=5` へ落とし、DEBUG 運用でも出ないようにした。
- 実機で `logicd` を再起動後、`/api/keymap/active` と `/api/matrix` を連続取得しても
  `ctrl G` / `ctrl K` / `Ctrl client` の journal 行が出ないことを確認した。
- 同じ観測で `/ws` の CSRF 403 が数秒ごとに出ていた。現行 frontend は
  `csrfWebSocketUrl("/ws")` を使うため、古いタブまたは古い JS を掴んだタブ由来の可能性が高い。
  ここは security warning として残し、再現条件が新規タブでも確認できた場合に別途見る。

追加 tuning:

- `/api/keymap/active` は active layer state だけが必要だが、従来は ctrl `G` で full keymap
  layers も毎回受け取っていた。
- logicd ctrl に `{"t":"ACTIVE"}` を追加し、`/api/keymap/active` は active snapshot だけを
  取得するようにした。`{"t":"G"}` は Vial / layout 用に従来通り full keymap を返す。
- 実機で `logicd` / `httpd` を再起動後、`/api/keymap/active` が
  `{"result":"ok","active":...}` を返し、`/api/layout` は 11 rows / 3 layers / `logicd_active`
  を返すことを確認した。
- `/api/keymap/active` を連続取得しても `ctrl ACTIVE` / `ctrl G` / `Ctrl client` /
  `keymap/active` の journal 行が出ないことを確認した。

## 2026-05-24 logicd event benchmark scenario

`logicd` の次の tuning は、体感に近い key event path を測ってから判断する。
物理キーの手打ちでは再現性が低いため、`tools/logicd_event_benchmark.py` を追加した。
この helper は runtime keymap の 1 キーを一時的に指定 action へ差し替え、
`matrix_events.sock` へ press / release を指定レートで連続注入し、最後に元の action へ戻す。

測定シナリオ:

```bash
sudo python3 tools/logicd_event_benchmark.py KC_A --count 300 --rate-hz 30
sudo python3 tools/logicd_event_benchmark.py KC_CONNAUTO --count 120 --rate-hz 10
sudo python3 tools/logicd_event_benchmark.py KC_SH3 --count 10 --rate-hz 1
```

使い方:

- 別 terminal で `python3 tools/perf_baseline.py --output /tmp/hidloom-perf-logicd-...md`
  を走らせ、同時に上記 benchmark を流す。
- `KC_A` は通常 key event / output fan-out の基準にする。
- `KC_CONNAUTO` は output routing action の軽い制御 path を見る。
- `KC_SH3` は shell script dispatch と script exit notification を見る。
- `KC_SH10` は reboot script なので、測定シナリオには使わない。

実機 smoke:

- `sudo python3 tools/logicd_event_benchmark.py KC_A --count 5 --rate-hz 5 --hold-sec 0.01`
  は `result=ok`、`restore_result=ok` で完了した。
- socket 権限の都合で、実機では通常 `sudo` 付きで実行する。

report:

- normal key: `/tmp/hidloom-perf-logicd-kc-a.md`
- output action: `/tmp/hidloom-perf-logicd-kc-connauto.md`
- script dispatch: `/tmp/hidloom-perf-logicd-kc-sh3.md`
- post script idle: `/tmp/hidloom-perf-logicd-post-script-idle.md`

結果:

- 3 シナリオとも benchmark は `result=ok`、`restore_result=ok` で完了した。
- `KC_A` 300 taps / 30Hz では `logicd` CPU は 4.5% 前後、RSS は 14,032 -> 14,056 KiB 程度。
- `KC_CONNAUTO` 120 taps / 10Hz では `logicd` CPU は 4.5% 前後、RSS は約 14,376 KiB。
- `KC_SH3` 10 taps / 1Hz では `logicd` CPU は 4.5% 前後、RSS は 15,788 -> 15,816 KiB 程度。
- 追加 idle watch では `logicd` RSS は 15,820 KiB で横ばいだった。現時点では増え続ける
  leak ではなく、script dispatch 後に一段上がって安定する挙動として扱う。
- `KC_SH3` の script exit notification は i2cd log に `exit_code=0` として出ていた。

次に見る候補:

- script dispatch の RSS 段差が問題になるほど頻繁に shell script を使う場合だけ深掘りする。
- それ以外は、次の tuning 対象を選ぶ前に実運用で目立つ CPU / RSS / log を再観測する。
- 改善する場合も HID report timing と InteractionEngine 判定時間は変えない。

## 2026-05-24 matrixd scan-loop tuning

after report では `matrixd` が約 13% CPU で安定していたため、次の小さい tuning として
scan loop を確認した。従来は各 row scan 後に `gpio_pullupdown()` を毎回呼び、
pull-up/down を再設定していた。pull は初期化時に設定済みで通常は維持されるため、
既定では row を INPUT に戻すだけに変更した。

互換用に `scan.reapply_pull_each_scan=true` を追加すると旧挙動へ戻せる。
実機で `matrixd` を再ビルド・再起動し、無押下 `/api/matrix` が `pressed: []` のまま
であることを確認した。

report:

- after: `/tmp/hidloom-perf-after-matrixd-scan.md`

結果:

- `matrixd` CPU は `/tmp/hidloom-perf-after-output-switch-log.md` の約 13.1% から、
  `/tmp/hidloom-perf-after-matrixd-scan.md` では約 11.6% へ下がった。
- `python3 script/test_validation_suite.py` は実機でも通過した。

次に見る候補:

- `httpd`: RSS が約 33 MiB で、HTTP UI 操作中の `/api/status` polling と JSON 生成を見る。
- `ledd`: effect loop は約 8% 前後。見た目を変えずに frame buffer reuse / sleep 精度を確認する。

## 2026-05-24 logicd / ledd event-driven idle wait

方針:

- `logicd` は Tap Dance / tap-hold / combo source timeout の次期限だけを event loop に渡し、
  内部 timer がない時は matrix event を完全待機する。固定 10ms tick は使わない。
- `ledd` は VialRGB reactive / splash 系だけ、発光中は従来どおり frame loop で減衰を描画し、
  hit / splash が空になったら静止フレームを 1 回表示して key event 待機に戻る。
- breathing / cycle / rain など、見た目として常時動く effect は従来どおり animation loop を維持する。

実装メモ:

- `InteractionEngine.next_timer_due()` を追加し、`logicd.matrix_pipeline` はその期限まで
  `runtime.queue.get()` を待つ。期限なしなら timeout なしで待機する。
- `ledd.AnimationManager` に VialRGB wake event を追加し、key event / animation stop で renderer を起こす。
- reactive / splash renderer は idle 時に `self._vialrgb_wake.wait()` へ入り、
  アニメーション中だけ 30/60fps の wait loop を使う。

検証:

- `python3 script/test_interaction_engine_tap_hold.py`
- `python3 script/test_vialrgb_ledd.py`
