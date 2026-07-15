# OLED connectivity icon row

更新日: 2026-05-28

OLED の接続状態行を、文字列中心ではなく小さな 1bit icon で一括俯瞰するための実装メモです。

## 目的

Ready 表示の出力モード行を、`USB / BT / Wi-Fi / Pi / auto` の接続状態 icon 行として表示します。

表示方針:

- 接続中・現在有効なものは反転表示で目立たせる。
- 接続の電源 on / 利用可能だが非アクティブなものは通常表示で並べる。
- daemon status は ready を反転表示、down / unknown を通常表示にする。
- Ready 表示では daemon status row、接続状態 row、layer row の順に並べる。
- off / unavailable は非表示にする。
- off の枠表示有無は、実機 OLED で見てから判断する。

## 実装済み

### Icon素材

`daemon/i2cd/connectivity_icon_bitmaps.txt` に、肉眼で編集しやすい 0/1 bitmap を置きます。
接続状態 icon と daemon status icon は同じ形式・同じ hot reload 経路で扱います。
各 icon は `# bt: Bluetooth output / Bluetooth status icon` のようなコメントと、`bt:` のような名前付き section を持ちます。
0/1 の 8行だけを編集すれば、Python code を触らず icon を調整できます。高さは 8px 固定、幅は各行の長さから自動決定します。

daemon status icon は現在 `mtx` / `lgc` / `led` / `btd` / `http` / `usbd` / `vial` を定義しています。
Booting 画面と Ready 画面の両方で同じ daemon icon row を使います。
bitmap file の形式は 8行固定ですが、daemon status row の描画では上下の空行を切り詰めます。
このため、下2行を `00000` にした縦6px icon は反転背景も含めて詰めて表示できます。

`daemon/i2cd/icons.py` は上記 bitmap file を読み、以下の Python API として公開します。

- `BT_ICON_8X8`
- `WIFI_LEVEL_0_8X8`
- `WIFI_LEVEL_3_8X8`
- `USB_ICON_8X8`
- `PI_ICON_8X8`
- `AUTO_ICON_8X8`
- `CONNECTIVITY_ICONS`
- `icon_bitmap()`
- `draw_icon_pixels()`

### Wi-Fi snapshot helper

`daemon/i2cd/connectivity.py` を追加済みです。

- `rfkill list wifi` と `nmcli device status` を read-only に読む。
- `powered=False` または blocked の Wi-Fi は非表示にする。
- powered だが未接続の Wi-Fi は `wifi0` を通常表示にする。
- connected の Wi-Fi は `wifi3` を反転表示にする。
- `wifi` / `wifi1` / `wifi2` は未使用のため bitmap 定義から削除済みです。

### 出力モード行

`daemon/i2cd/i2cd.py` の `_draw_output_mode()` を icon row 表示に変更済みです。

現在 i2cd が持っている `current_mode` と Wi-Fi snapshot から分かる範囲で表示します。

| state | 表示 |
| --- | --- |
| `gadget` | USB icon 反転 |
| `bt` | BT icon 反転 |
| `uinput` | Pi icon 反転 |
| `auto:gadget` | auto icon 反転 + USB icon 反転 |
| `auto:bt` | auto icon 反転 + BT icon 反転 |
| `auto:uinput` | auto icon 反転 + Pi icon 反転 |
| Wi-Fi powered, not connected | `wifi0` icon 通常表示 |
| Wi-Fi connected | `wifi3` icon 反転 |
| Wi-Fi off / unavailable | 非表示 |
| unknown output mode | 文字 fallback |

### Tests

以下を更新済みです。

- `script/test_i2cd_oled_icons.py`
  - `daemon/i2cd/connectivity_icon_bitmaps.txt` に接続 / daemon 各 icon のコメント付き 0/1 bitmap があること、8x8、非空、`icon_bitmap()` / hot reload 対応を確認する。
- `script/test_i2cd_connectivity.py`
  - output mode と Wi-Fi snapshot から icon row を決定する helper を確認する。
  - Wi-Fi off / unavailable は非表示、powered 未接続は `wifi0` 通常、connected は `wifi3` 反転を固定する。
- `script/test_i2cd_output_mode_label.py`
  - 出力モード行が文字ではなく icon row を描くことを確認する。
  - active icon は反転描画されることを確認する。
  - daemon status は ready icon が反転描画されることを確認する。
  - daemon status icon の上下空行を詰めて描くことを確認する。
  - unknown mode は文字 fallback になることを確認する。
- `script/test_i2cd_direct_frame_fps.py`
  - Booting 画面でも daemon icon row を使い、旧 `matrix …` / `logicd …` text に戻らないことを確認する。

## 未実装 / 残り

- Wi-Fi RSSI / quality を読んで段階表示を増やす処理は未実装です。
- BT / USB / Pi の「利用可能だが非アクティブ」状態を並べるには、i2cd 側へ richer status snapshot を渡す必要があります。
- 実機 OLED で視認性を確認して、枠表示、間隔、反転時の見え方を調整します。

## 実機確認項目

- USB icon / BT icon / Pi icon / auto icon / Wi-Fi icon が小さすぎず識別できる。
- active の反転表示が目立つ。
- daemon ready の反転表示が目立ち、down / unknown の通常表示と区別できる。
- off / unavailable 非表示で見落としが起きない。
- auto icon と実際の出力先 icon が並んでも分かりやすい。
- Wi-Fi powered 未接続の `wifi0` 通常表示と、connected の `wifi3` 反転表示が直感的に見える。

## 次の候補

1. 実機で現行 icon row の視認性を確認する。
2. RSSI / quality を取得して Wi-Fi 段階表示を増やす。
3. 利用可能だが非アクティブな USB / BT / Pi を通常表示で並べるための status payload を決める。
