# matrixd real device stability checklist

更新日: 2026-06-02

この文書は、`matrixd` scan stability work の実機確認用チェックリストです。

背景:

- LED effect が multi splash の時、触れていないのに Space bar が短時間 press / release されたように見えることがあった。
- ごくまれに入力取りこぼしもあった。
- 症状が出始める前に `matrixd` の実行優先度を引き上げていた。

実機なしで実装済み:

- `debounce_mode=count/time`
- 実時間 debounce helper
- `post_row_settle_us`
- `MIN_INTERVAL_US` による busy loop 保護
- 負値設定の丸め
- `send()` 成功後にだけ debounce state を commit
- `script/test_matrixd_debounce.py`
- `script/test_matrixd_build.py`
- `script/test_matrixd_scan_optimization.py`

## 2026-06-02 自動実機 smoke

`<keyboard-host>` (`pi@<keyboard-ip>`) に `main` (`9002a3a`) を同期し、`daemon/matrixd/matrixd`
を Pi 上で ARM aarch64 binary として rebuild した。

確認済み:

- `daemon/matrixd/matrixd`: `ELF 64-bit LSB pie executable, ARM aarch64`
- `matrixd` / `logicd` / `ledd` / `httpd` / `viald` / `usbd` / `btd` / `i2cd` は active。
- `/tmp/matrix_events.sock` / `/tmp/ctrl_events.sock` / `/tmp/ledd_events.sock` / `/tmp/viald_events.sock` が存在。
- `systemctl show matrixd` は `Nice=-20`, `CPUSchedulingPolicy=fifo`, `CPUSchedulingPriority=99`。
- Pi 上で `script/test_matrixd_debounce.py`, `script/test_matrixd_build.py`, `script/test_matrixd_scan_optimization.py`,
  `script/test_logicd_matrix_input_priority.py`, `script/test_logicd_matrix_event_processing_boundary.py`,
  `script/test_logicd_output_router_boundary.py`, `script/test_logicd_resolved_action_heavy_boundary.py` が通過。
- `config/default/matrixd.json` に `debounce_mode=time`, `debounce_ms=5`, `post_row_settle_us=2` を設定し、
  `matrixd` journal で `デバウンス方式: time (debounce_ms=5)` と `logicd に接続しました` を確認。
- Multisplash 低輝度 (`mode=40`, `v=64`) と通常輝度 (`mode=40`, `v=180`) を `save=false` で各 15 秒流し、
  `matrixd` 送信失敗、`logicd` input path warning、`ledd` 異常 log は 0 件。
- 観測時の process snapshot では `matrixd` CPU は約 4.4%、RSS は約 1.5 MiB。
  `logicd` は約 2.8-3.1%、`ledd` は約 3.1-3.5%。
- performance baseline report は実機の `/tmp/hidloom-smoke/perf-matrixd-time-2026-06-02.md` に保存。
- 追加比較として、Multisplash 通常輝度を各 12 秒流し、`count` / RT99、`time` + `post_row_settle_us=5` / RT99、
  `time` + `post_row_settle_us=10` / RT99、`time` + `post_row_settle_us=2` / RT off を確認した。
  4 条件すべて主要 service は active、`matrixd` 送信失敗、`logicd` input path warning、`ledd` 異常 log は 0 件。
  report は実機の `/tmp/hidloom-smoke/matrixd-compare-2026-06-02.txt` に保存。
- 本命設定 `time`, `debounce_ms=5`, `post_row_settle_us=2`, RT99 で Multisplash 通常輝度を 60 秒流した追加観測でも、
  主要 service は active、異常 log は 0 件。`matrixd` CPU は約 4.4%、RSS は約 1.5 MiB。
  report は実機の `/tmp/hidloom-smoke/matrixd-long-idle-2026-06-02.txt` に保存。
- 同じ本命設定で `/tmp/key_events.sock` を 90 秒監視し、`key_event_count=0`、異常 log 0 件。
  report は実機の `/tmp/hidloom-smoke/key-events-idle-multisplash-2026-06-02.txt` に保存。
- 同じ本命設定で `/tmp/ledd_events.sock` を 90 秒監視し、初期/status message は 3 件、
  `key_message_count=0`、異常 log 0 件。report は実機の
  `/tmp/hidloom-smoke/ledd-events-idle-multisplash-2026-06-02.txt` に保存。
- この観測を再実行する helper として `tools/matrixd_stability_smoke.py` を追加した。
- helper 実走では、Multisplash 低輝度 (`v=64`) 20 秒、通常輝度 (`v=180`) 20 秒、
  通常輝度 (`v=180`) 60 秒はいずれも pass。`key_event_count=0`, `key_message_count=0`,
  `interesting_log_count=0`。通常輝度 60 秒 report は実機の
  `/tmp/hidloom-smoke/matrixd-stability-normal-tool-60s-2026-06-02.md` に保存。
- 追加で通常輝度 (`v=180`) 180 秒を helper で流し、`key_event_count=0`, `key_message_count=0`,
  `interesting_log_count=0` で pass。主要 service は active、`matrixd` は RT99 のまま。
  report は実機の `/tmp/hidloom-smoke/matrixd-stability-normal-tool-180s-2026-06-02.md` に保存。
- helper 初回の通常輝度 30 秒 run では `key_event_count=71`, `key_message_count=71` を検出したが、
  直後の元 effect 20 秒、低輝度 20 秒、通常輝度 20 秒、通常輝度 60 秒、通常輝度 180 秒では再現しなかった。
  このため、現時点では未再現 transient として物理 idle 確認で追う。
- その後の追加切り分けでは、RT off 60 秒で `key_event_count=24`、
  RT99 復帰後の通常輝度 (`v=180`) 60 秒で `key_event_count=74`、再チェックで `key_event_count=122` を検出。
  一方、元 effect (`speed=32`, `h=183`, `s=163`, `v=180`) 60 秒、`v=64` 60 秒、
  `v=128` 60 秒、`v=160` 60 秒、`v=170` 60 秒はいずれも `key_event_count=0`。
  `mode=40`, `speed=128`, `h=80`, `s=255`, `v=180` 付近の brightness / current 負荷が疑わしい。
- `tools/matrixd_stability_smoke.py` の既定 brightness は最終的に `v=160` に下げた。`v=170` 既定値の 60 秒 smoke は
  `key_event_count=0`, `key_message_count=0`, `interesting_log_count=0` で pass。
  report は実機の `/tmp/hidloom-smoke/matrixd-stability-default-v170-tool-60s-2026-06-02.md` に保存。
- `v=170` guard 反映後に `--value 180` を再確認したところ、effective `v=170` でも 60 秒で
  `key_event_count=36` を検出した。直後の `v=160` 60 秒は `key_event_count=0` で pass。
  report は実機の `/tmp/hidloom-smoke/matrixd-stability-splash-cap-v160-after-restart-60s-2026-06-02.md` に保存。
- `logicd` / HTTP Lighting の通常 VialRGB state 経路では、splash 系 mode (`39..42`) の `v` を
  `160` に丸める safety guard を追加した。`v=180` の再現確認が必要な場合は、guard の対象外にした
  低レベル経路または一時変更で明示的に行う。
- `v=160` guard 反映後に `--value 180` request を再実行し、effective LED state は `v=160`、
  `key_event_count=0`, `key_message_count=0`, `interesting_log_count=0` で pass。
  report は実機の `/tmp/hidloom-smoke/matrixd-stability-splash-cap-v160-v180-request-60s-2026-06-02.md` に保存。

## 2026-06-03 非目視実機確認

`<keyboard-host>` (`pi@<keyboard-ip>`) に SSH 接続できることを確認し、目視や物理操作が不要な範囲を実施した。

確認済み:

- `hidloom-usb-gadget` / `i2cd` / `logicd` / `matrixd` / `ledd` / `httpd` / `viald` / `usbd` / `btd` は active。
- `/dev/hidg0` / `/dev/hidg1` と `/tmp/matrix_events.sock` / `/tmp/ctrl_events.sock` /
  `/tmp/ledd_events.sock` / `/tmp/key_events.sock` / `/tmp/btd_events.sock` が存在。
- `/api/status` は `hid.connected=true`, `wifi.connected=true`, `output.display_label=AUTO USB`。
- Pi 上で `script/test_matrixd_debounce.py`, `script/test_matrixd_build.py`,
  `script/test_matrixd_scan_optimization.py`, `script/test_logicd_matrix_input_priority.py`,
  `script/test_logicd_matrix_event_processing_boundary.py`, `script/test_logicd_output_router_boundary.py`,
  `script/test_logicd_resolved_action_heavy_boundary.py` が通過。
- Pi 上で `script/test_i2cd_oled_icons.py`, `script/test_i2cd_connectivity.py`,
  `script/test_i2cd_output_mode_label.py` が通過。
- `tools/matrixd_stability_smoke.py --duration 60 --value 180 --output /tmp/hidloom-smoke/matrixd-nonvisual-v180-request-2026-06-03.md`
  は fail。
  - request は `v=180` だが、effective LED state は `mode=40`, `speed=128`, `h=80`, `s=255`, `v=160`。
  - `key_event_count=53`
  - `ledd_key_message_count=53`
  - `interesting_log_count=0`
  - 主要 service active、matrixd は RT99 のまま。
- `tools/matrixd_stability_smoke.py --duration 60 --value 160 --output /tmp/hidloom-smoke/matrixd-nonvisual-v160-request-2026-06-03.md`
  も fail。
  - effective LED state は `mode=40`, `speed=128`, `h=80`, `s=255`, `v=160`。
  - `key_event_count=42`
  - `ledd_key_message_count=42`
  - `interesting_log_count=0`
- 現在の通常 effect と同じ `speed=32`, `h=183`, `s=163`, `v=160` は
  `tools/matrixd_stability_smoke.py --duration 60 --speed 32 --hue 183 --saturation 163 --value 160 --output /tmp/hidloom-smoke/matrixd-nonvisual-current-effect-2026-06-03.md`
  で pass。
  - `key_event_count=0`
  - `ledd_key_message_count=0`
  - `interesting_log_count=0`
- 追加の 30 秒 sweep:
  - `speed=128`, `h=183`, `s=163`, `v=160`: fail, `key_event_count=18`
  - `speed=32`, `h=80`, `s=255`, `v=160`: fail, `key_event_count=48`
  - `speed=128`, `h=80`, `s=163`, `v=160`: fail, `key_event_count=4`
  - `speed=32`, `h=80`, `s=163`, `v=160`: pass, `key_event_count=0`
  - `speed=32`, `h=183`, `s=255`, `v=160`: pass, `key_event_count=0`
  - `speed=64`, `h=183`, `s=163`, `v=160`: fail, `key_event_count=4`
  - `speed=64`, `h=80`, `s=255`, `v=160`: fail, `key_event_count=1`

判断:

- 通常運用 effect は 60 秒の非目視 smoke では安定。
- high-speed / high-saturation Multisplash (`speed=128`, `h=80`, `s=255`) は `v=160` guard 後も key burst が再現する。
- `speed>=64` は通常色でも少量再現し、`speed=32` でも `h=80` と `s=255` の組み合わせで強く再現する。
  `h=80` 単体、`s=255` 単体は 30 秒では pass。
- 次の切り分けでは splash 系 mode の speed cap と、high saturation + 特定 hue family の組み合わせ guard を検討する。

未判断:

- 物理キー操作中の Space ghost 非再現。
- 通常入力の取りこぼし非再現。
- `debounce_mode=time` の tap / hold / combo 体感遅延。
- RT priority rollback 時の物理操作差。
- `v=180` の high-brightness Multisplash で出る key burst の物理 idle 再確認。
- `v=160` safety guard の見た目と負荷を物理操作で確認。

## 2026-06-14 extra input scan smoke

`<keyboard-host>` (`operator@<keyboard-ip>`) で、通常の `matrixd.service` を止めずに、
追加 input scan type 実装を `/tmp/matrixd-extra-test` へ一時配置して確認した。

目的:

- charlieplex 以外の row / col 分離 matrix 定義を読めること。
- 1 GPIO 1 switch の `direct_switches[]` 定義を読めること。
- 2 GPIO rotary encoder の `rotary_encoders[]` 定義を読めること。
- 既存 protocol を変えず、追加入力も `P/R row col` に正規化できる前提を確認すること。
- 未使用 GPIO を pull-up / active-low で読むだけの idle 状態で、浮き event と高負荷が出ないこと。

一時 config:

```json
{
  "matrix": {
    "matrix_type": "row_col",
    "rows": 4,
    "cols": 4,
    "row_gpios": [7, 8, 11, 16],
    "col_gpios": [17, 18, 19, 20],
    "row_drive": "output_low",
    "col_pull": "pull_up",
    "key_active": "low",
    "gpio_enabled": true
  },
  "direct_switches": [
    {"row": 0, "col": 2, "gpio": 21, "pull": "up", "active": "low"}
  ],
  "rotary_encoders": [
    {"gpio_a": 14, "gpio_b": 15, "a": [3, 0], "b": [3, 1], "pull": "up", "active": "low"}
  ],
  "ipc": {
    "socket_path": "/tmp/matrixd-extra-test/matrixd-extra-test.sock"
  }
}
```

確認済み:

- Pi 上で一時配置した `daemon/matrixd` source は `make clean all` に成功。
- 一時 socket server に接続し、5 秒間の event 受信を確認。
- `event_bytes=0`。未接続 switch / encoder GPIO の浮きによる press / release は出なかった。
- 追加 instance の CPU samples は `[0.0, 0.0, 0.9, 0.6, 0.9, 0.7, 0.9, 0.7, 0.6, 0.8]`。
- CPU 最大は `0.9%`、終了コードは `0`。
- 通常の `matrixd` / `logicd` は active のまま。

注意:

- GPIO0/1 は HAT EEPROM 系と衝突しやすいため、今回の一時確認では使わなかった。
- GPIO14/15 は UART と共有されるため、本採用時は serial console / UART 利用状況を確認する。
- 今回は未接続 GPIO の idle smoke であり、実際の switch / encoder 回転方向 / debounce 体感は未確認。

## 触らない範囲

この確認では以下を触らない。

- touch-panel flick / swipe / フリック入力
- kiosk touch input の PointerEvent 処理
- Vial GUI / touch-panel Vial layout
- LED effect の表現そのもの

## 事前確認

```bash
systemctl status matrixd hidloom-logicd-core logicd-companion hidloom-hidd ledd --no-pager
journalctl -u matrixd -u hidloom-logicd-core -u logicd-companion -u hidloom-hidd -u ledd -n 100 --no-pager
```

確認すること:

- `matrixd` が active。
- `logicd` が active。
- `/tmp/matrix_events.sock` が存在する。
- `matrixd` log に `logicd に接続しました` が出る。
- `matrixd` log に送信失敗が繰り返し出ていない。
- `logicd` log に matrix event 受信後の異常 warning がない。

## 1. 実機上の静的テスト

Pi 上で実行する。

```bash
python3 script/test_matrixd_debounce.py
python3 script/test_matrixd_build.py
python3 script/test_matrixd_scan_optimization.py
```

期待:

- 3本とも通る。
- `test_matrixd_build.py` は Pi 上で ARM 向けに C build できることを確認する。
- build 後に x86_64 binary を rsync で上書きしない。

## 2. baseline 条件

まず LED 負荷を低くして確認する。

条件:

- LED off または単色固定。
- `debounce_mode=count` の既存互換設定。
- `matrixd` の現在の systemd 優先度設定。

確認:

- 通常入力が取りこぼされない。
- Space が触っていないのに押されない。
- press / release が遅れて見えない。

## 3. time debounce 条件

`config/default/matrixd.json` または runtime config に以下を設定して確認する。

```json
{
  "scan": {
    "debounce_mode": "time",
    "debounce_ms": 5
  }
}
```

確認:

- 通常入力が取りこぼされない。
- Space ghost が出ない、または count mode より改善する。
- tap / hold / combo の体感遅延が許容範囲。
- `matrixd` log に debounce mode が `time` と出る。

## 4. multi splash 条件

LED effect を multi splash にして確認する。

条件:

- multi splash 低輝度。
- multi splash 通常輝度。
- それぞれ `debounce_mode=time` で確認。

まず keyboard に触れない非接触 stress を実行する。

```bash
sudo python3 tools/matrixd_led_stress_sweep.py --quick --duration 30 --output /tmp/hidloom-smoke/matrixd-led-stress-quick.md
sudo python3 tools/matrixd_led_stress_sweep.py --duration 60 --output /tmp/hidloom-smoke/matrixd-led-stress-full.md
```

非接触 stress では `matrix_events.sock` へ入力を注入しない。dummy splash は `ctrl_events.sock` の
diagnostic `LED key_event` から `ledd` へだけ送るため、`key_event_count=0` を ghost input の合格条件にする。
`ledd_key_message_count` は dummy splash では増えるので fail 条件にしない。

2026-06-05 `<keyboard-host>` メモ:

- `--quick --duration 10` は pass。LED off、現行 Multisplash、risky Multisplash、
  dummy splash 30Hz の全 scenario で `key_event_count=0`。dummy 30Hz は
  `ledd_key_message_count=614` / `dummy_sent=614`。
- `--duration 15` の full sweep は途中で実機の電源不足により停止したため、matrixd stability 判定には使わない。
  長時間 / 60Hz dummy splash stress は、十分な電源または powered hub を使って再実行する。

確認:

- 触れていない時に Space press / release が出ない。
- 非接触 stress で `key_event_count=0`。
- 実機が電源不足で落ちた run は fail/pass ではなく `power interrupted` として記録し、再実行する。
- 通常入力が取りこぼされない。
- `matrixd` が送信失敗を出さない。
- `logicd` が matrix event 処理遅延らしい warning を出さない。
- `ledd` の負荷で input path が飢餓していない。

## 5. settle 調整

`debounce_mode=time` でも Space ghost が残る場合にだけ、settle を調整する。

順序:

1. `post_row_settle_us` を少し増やす。
2. それでも残る場合に `settle_us` を少し増やす。
3. 入力遅延やCPU負荷が悪化しない範囲を探る。

例:

```json
{
  "scan": {
    "debounce_mode": "time",
    "debounce_ms": 5,
    "settle_us": 20,
    "post_row_settle_us": 5
  }
}
```

比較候補:

- `post_row_settle_us=2`
- `post_row_settle_us=5`
- `post_row_settle_us=10`
- `settle_us=20`
- `settle_us=50`

確認:

- Space ghost が減るか。
- 入力取りこぼしが増えないか。
- scan体感遅延が許容範囲か。

## 6. RT priority rollback 比較

`debounce_mode=time` と settle 調整後も症状が残る場合、`matrixd` の RT 優先度を一時的に外して比較する。

```bash
sudo systemctl edit matrixd
```

一時drop-in例:

```ini
[Service]
CPUSchedulingPolicy=other
IOSchedulingClass=best-effort
Nice=0
```

`CPUSchedulingPriority=` や `IOSchedulingPriority=` を空で書くと systemd が warning を出す場合があります。
一時比較では policy / class / Nice だけを上書きします。

反映:

```bash
sudo systemctl daemon-reload
sudo systemctl restart matrixd
systemctl show matrixd -p Nice -p CPUSchedulingPolicy -p CPUSchedulingPriority -p IOSchedulingClass -p IOSchedulingPriority
```

比較:

- RT priority あり / なしで Space ghost 発生率が変わるか。
- 入力取りこぼしが変わるか。
- `logicd` 側の受信遅延が変わるか。
- `ledd` multi splash の見た目やFPSが変わるか。

確認後、必要なら drop-in を削除する。

```bash
sudo systemctl revert matrixd
sudo systemctl daemon-reload
sudo systemctl restart matrixd
```

## 7. logicd input path 確認

`matrixd` だけを強くしすぎて `hidloom-logicd-core` または `logicd-companion` が飢餓していないか見る。

確認:

```bash
journalctl -u matrixd -f
journalctl -u hidloom-logicd-core -u logicd-companion -f
```

見ること:

- `matrixd` に送信失敗がない。
- `hidloom-logicd-core` が matrix event を処理できている。
- HID report release が遅れて押しっぱなしに見えない。
- `hidloom-logicd-core` / `logicd-companion` 側で重い処理や例外が出ていない。

理想の優先度階層:

```text
matrixd >= logicd-core / logicd-companion matrix input path > hidloom-hidd/btd output path > ledd/httpd/UI系
```

実機なしでは `hidloom-logicd-core.service` / `logicd-companion.service` の RT 優先度は変更しない。
実機確認で core / companion の受信や HID report 生成が詰まる場合だけ、最小限の優先度調整を検討する。

## 完了判断

完了扱いにできる条件:

- multi splash 通常輝度で Space ghost が再現しない。
- 通常入力の取りこぼしが再現しない。
- `matrixd` に送信失敗が出ない。
- `logicd` に input path 詰まりの warning が出ない。
- rollback 条件を試しても、RT priority が主因ではない、または安全な優先度設定が見つかる。

TODO側には詳細ログではなく、最終判断だけ反映する。
