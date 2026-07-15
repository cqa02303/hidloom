# Runtime profiles

`config/profiles/` は、同じ配線・同じ daemon 構成のまま、実機性能や運用目的に応じて変える runtime profile を記録します。

`config/boards/` は物理配線、LED 位置、board 固有 keymap などの hardware profile を扱います。
一方で runtime profile は、CPU 余裕、メモリ、I2C/OLED 負荷、Bluetooth を使うかどうか、service を止めるかどうかを扱います。

## Policy

- 標準の `config/default/` は Zero / Zero 2 専用値で直接上書きしません。
- `overrides/*.json` は、同名の `config/default/*.json` へ deep-merge する差分として扱います。
- `services.json` は systemd / rfkill の推奨状態を記録します。設定ファイルへ deep-merge するものではありません。
- 実機で一時的に試した値は、安定して再現したものだけ profile に残します。
- 低負荷 profile は入力遅延を優先し、OLED/LED/Bluetooth/analog polling を必要に応じて抑えます。
- Zero 2 など余裕のある profile は、入力遅延を悪化させない範囲で OLED の応答性を戻します。

## Profiles

| profile | target | direction |
|---|---|---|
| [`raspberry-pi-zero`](raspberry-pi-zero/) | Raspberry Pi Zero W / Zero 1 系 | 入力遅延を避ける低負荷設定。Bluetooth と serial console login を止め、OLED/LED/matrix scan を控えめにする |
| [`raspberry-pi-zero2`](raspberry-pi-zero2/) | Raspberry Pi Zero 2 W | Zero 1 より OLED 更新を少し短くし、Bluetooth と analog stick は標準寄りに維持する |

## Apply model

現時点では自動適用 helper はありません。適用する場合は次の考え方で手動反映します。

1. 対象 profile の `overrides/*.json` を、対応する runtime config へ deep-merge します。
2. `/mnt/p3/` に runtime config がある実機では、`config/default/` より `/mnt/p3/` 側を優先して更新します。
3. `services.json` の systemd / rfkill 状態を手動で適用します。
4. 関連 daemon を restart し、キー入力遅延、OLED 表示、LED effect、CPU 負荷を確認します。

profile を変えても `config/boards/` の wiring profile は変わりません。配線や LED index が違う場合は、runtime profile ではなく board profile 側で扱います。
