# チャーリープレックス回路仕様

## 概要
CQA02303v5キーボードは、チャーリープレックス方式を使用した10x10マトリックスキーボードです。

## マトリックス構成

### scan line ピン配置

現在の `matrixd` 設定では、チャーリープレックスの ROW / COL は同じ GPIO 配列を使います。

```
LINE1  - Raspberry Pi GPIO13 (Pin 33)
LINE2  - Raspberry Pi GPIO26 (Pin 37)
LINE3  - Raspberry Pi GPIO6  (Pin 31)
LINE4  - Raspberry Pi GPIO5  (Pin 29)
LINE5  - Raspberry Pi GPIO4  (Pin 7)
LINE6  - Raspberry Pi GPIO25 (Pin 22)
LINE7  - Raspberry Pi GPIO24 (Pin 18)
LINE8  - Raspberry Pi GPIO22 (Pin 15)
LINE9  - Raspberry Pi GPIO23 (Pin 16)
LINE10 - Raspberry Pi GPIO27 (Pin 13)
```

`config/default/matrixd.json`:

```
row_gpios = [13, 26, 6, 5, 4, 25, 24, 22, 23, 27]
col_gpios = [13, 26, 6, 5, 4, 25, 24, 22, 23, 27]
```

SPI0 (`GPIO07`-`GPIO11`) は PAW mouse sensor 用に空けます。matrix scan では使いません。

## チャーリープレックス ダイオード配置

### BAV70 (デュアルダイオード) 使用
- **D1-D30**: キーマトリックス用チャーリープレックス ダイオード
- **各ダイオード**: SOT-23 パッケージ、100V/215mA
- **配置**: 各キースイッチに直列接続

### 接続パターン
```
スイッチ → ダイオード → ROW線
              ↓
            COL線
```

## 特殊機能

### エンコーダー (EC1)
```
EC1A  - エンコーダー A相
EC1B  - エンコーダー B相
EC1SW - エンコーダー プッシュスイッチ
```

### アナログジョイスティック
```
JOY1  - X軸 (ADC入力)
JOY2  - Y軸 (ADC入力)
JOYB  - ボタン (デジタル入力)
```

## スキャン方式

### スキャンアルゴリズム
1. ROW線を順次 HIGH に設定
2. COL線をプルダウン抵抗でLOW に保持
3. 各ROW線がHIGH時に全COL線を順次読み取り
4. ダイオードの順方向特性により、押下されたキーのみ信号が流れる

### デバウンス処理
- ハードウェア: R-Cフィルタ（オプション）
- ソフトウェア: 10-20ms のデバウンス時間

## チャーリープレックス利点
1. **GPIO数削減**: N本のGPIOで N×(N-1) キーを制御可能
2. **配線簡素化**: 従来マトリックスより配線数が削減
3. **NKRO対応**: Nキーロールオーバー実現可能
