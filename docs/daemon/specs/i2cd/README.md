# i2cd Detailed Spec

`i2cd` は OLED / I2C peripheral と connectivity icon 表示を扱う daemon です。表示更新が入力経路を阻害しないこと、I2C failure を隔離することを重視します。

## 役割

- I2C device を初期化し、OLED / sensor / icon 表示を更新する。
- connectivity state を表示用 bitmap / icon に反映する。
- I2C error を診断可能にする。

## 非役割

- connectivity state の owner にはならない。
- key event / HID report には関与しない。

## 所有するリソース

- 実装: `daemon/i2cd/`
- 入力: connectivity state、display update request
- 出力: I2C device update、diagnostic log

## 実装時に守る条件

- I2C device missing 時に入力 daemon を巻き込まない。
- 表示 update の失敗を状態 owner の失敗として扱わない。
- icon bitmap の座標 / bit order を変更する場合は visual 確認を残す。
- update loop が CPU を占有しない。
- OLED / I2C refresh は入力 path より低優先として扱う。
- idle loop の wake interval を短くする場合は、実機 CPU 使用率と `/api/status` latency への影響を見る。

## テスト観点

- device missing。
- icon render snapshot。
- repeated update。
- service restart。
- idle CPU / refresh interval。
