# Raspberry Pi Zero runtime profile

Raspberry Pi Zero W / Zero 1 系で、キー入力遅延を避けるために使う低負荷 runtime profile です。

この profile は board wiring profile ではありません。`config/boards/` は物理配線差分を扱い、
この directory は CPU 1 core / 低メモリ環境向けの daemon parameter と service state だけを記録します。
runtime profile 全体の方針は [`../README.md`](../README.md) を参照します。

2026-06-13 に Raspberry Pi Zero W Rev 1.1 / Raspbian trixie armhf で確認した値を元にしています。

## Apply policy

- `overrides/*.json` は `config/default/*.json` へ deep-merge する想定の差分です。
- `services.json` は systemd / rfkill の推奨状態を記録するだけです。
- 標準の `config/default/` へは直接混ぜません。

## Direction

- 入力遅延と key release の取りこぼし回避を最優先します。
- OLED はイベント更新を 2 FPS へ間引き、定期再描画は標準の 5 秒相当に留めます。
- CPU 使用率 / 温度のような軽量 system status は 1 秒間隔で裏取りし、OLED 描画時はキャッシュを表示します。
- Wi-Fi / service status は描画経路から外し、低頻度の非同期取得にします。
- LED は animation FPS と `show()` 頻度を抑え、キー入力と LED 転送が重なる時間を減らします。
- Bluetooth HID を使わない USB-only 検証では Bluetooth 系 daemon を止めます。
- ADS1115 analog stick polling は Zero 1 系では負荷要因になりやすいため、この profile では無効にします。

## Observed service state

- Keep active: `hidloom-usb-gadget`, `matrixd`, `logicd`, `i2cd`, `ledd`, `httpd`, `viald`, `hidloom-hidd`
- Stop/disable for Zero W low-latency profile: `btd`, `bluetooth`, `hidloom-bluetooth-unblock`
- Mask serial console login: `serial-getty@ttyS0`
- Block Bluetooth rfkill when Bluetooth HID is not used

## Notes

- `ledd` may be manually active while disabled; `logicd.service` can still want/start it when restarted.
- OLED CPU display is smoothed in code, so short 100% spikes should not appear as a long stuck value.
- `matrixd` scan interval is intentionally slower than the default to leave CPU for `logicd` and `ledd`.
