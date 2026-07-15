# VialRGB upstream 調査メモ

## 目的

VialRGB の内部実装を始める前に、upstream の識別子仕様を確定する。

## 確認済み

- `vial.json` で `"lighting": "vialrgb"` を指定すると、Vial GUI は RGB Matrix の effect、color、brightness、speed を扱う。
- VialRGB は QMK RGB Matrix を土台にしている。
- VialRGB には direct control mode がある。

## 確定したこと

1. effect 識別子は Raw HID プロトコル上で 16-bit の番号。
2. GUI 側の effect 一覧は `vial-gui/src/main/python/editor/rgb_configurator.py`
   の `VIALRGB_EFFECTS` に定義される。
3. `SET_MODE` は `mode_le16, speed, h, s, v` をまとめて送る。

## まだ未確定

1. 独自 effect を追加する場合の安全な未使用識別子空間

## 調査対象

### `vial-qmk`

確認対象:

- VialRGB protocol handler
- RGB Matrix mode 定義
- direct mode 実装

検索語:

```text
vialrgb
VIALRGB
rgb_matrix_mode
rgb_matrix_get_mode
direct
```

### `vial-gui`

確認対象:

- RGB effect 一覧の生成
- GUI 選択値から Raw HID packet への変換

検索語:

```text
vialrgb
rgb_matrix
brightness
speed
effect
```

## 設計ルール

upstream 確認までは、内部 API の effect 識別子を仮に `vial_effect` と呼ぶ。

- upstream が番号管理なら番号を採用する。
- upstream が名前管理なら名前を採用する。
- 独自 effect は Vial が使っていない識別子空間へ追加する。
- 独自の二重管理レイヤーは作らない。

## 次に確定する項目

upstream 調査後、次を更新する。

1. [lighting/vialrgb-protocol.md](../lighting/vialrgb-protocol.md)
2. [daemon/specs/viald/architecture.md](../daemon/specs/viald/architecture.md)
3. `logicd` の LED state schema
4. `ledd` の animation registry key

## 参考一次資料

- Vial 公式 lighting docs
- `vial-kb/vial-qmk`
- `vial-kb/vial-gui`
