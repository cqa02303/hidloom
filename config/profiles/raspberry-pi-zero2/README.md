# Raspberry Pi Zero 2 runtime profile

Raspberry Pi Zero 2 W 向けに、Zero 1 系より少し表示応答を上げる runtime profile です。

この profile は board wiring profile ではありません。`config/boards/` は物理配線差分を扱い、
この directory は daemon parameter と service state だけを記録します。
runtime profile 全体の方針は [`../README.md`](../README.md) を参照します。

## Apply policy

- `overrides/*.json` は `config/default/*.json` へ deep-merge する想定の差分です。
- `services.json` は systemd / rfkill の推奨状態を記録するだけです。
- 標準の `config/default/` へは直接混ぜません。

## Notes

- OLED は Zero 1 profile より短い定期再描画間隔と高い event FPS を使います。
- Bluetooth HID を使う可能性があるため、Bluetooth 系 daemon は標準状態のまま active 寄りにします。
- Analog stick polling は標準設定を維持します。

## Direction

- Zero 1 profile のような徹底した service 停止より、通常機能を保ったまま軽くする方針です。
- OLED は `display.refresh_interval_sec=3.0` と `display.fps=4` を基準にし、CPU 余裕を見ながら 3-5 秒 / 3-5 FPS の範囲で調整します。
- CPU 使用率 / 温度のような軽量 system status は 1 秒間隔で裏取りし、OLED 描画時はキャッシュを表示します。
- Wi-Fi / service status poll は標準より控えめにしつつ、Zero 1 profile ほど長くはしません。
- Bluetooth と analog stick は、実機で明確に入力遅延へ効くと分かるまで止めません。
