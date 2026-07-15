# viald / VialRGB 設計メモ

## 目的

この文書は、HIDloom に Vial 対応を追加する際の責務分離と、
VialRGB を既存の `ledd` アニメーション基盤へ統合する方針を残すための設計メモである。

## 設計の中心線

- `hidloom-hidd` は USB デバイスファイルと内部ソケットの橋渡しだけを担当する。
- legacy Python `usbd` は rollback / A/B 診断用に残すが、現行既定では通常 inactive。
- `viald` は Vial Raw HID プロトコルを解釈し、内部 API に翻訳する。
- `logicd` はランタイム状態の正本を持つ。
- `keymap.json` は永続キーマップの正本を持つ。
- `vial.json` は Vial GUI に見せる物理定義を持つ。
- `ledd` は LED の描画実体とアニメーション実装を持つ。

```text
PC / Vial GUI
   │
   │ USB Raw HID
   ▼
/dev/hidg1
   │
   ▼
hidloom-hidd
   │  /tmp/viald_events.sock
   ▼
viald
   │
   ├─ config/default/vial.json を返す
   ├─ Vial keycode ↔ internal action を変換
   └─ /tmp/ctrl_events.sock
          ▼
        logicd
          ├─ キーマップ状態の正本
          └─ /tmp/ledd_events.sock
                 ▼
               ledd
```

## USB interface の理想構成

既存 USB gadget 構成は、Vial 対応を正として次の順に組み直す。

| Function | Device | 役割 |
|---|---:|---|
| `hid.usb0` | `/dev/hidg0` | Keyboard / Mouse / Consumer Control multi-report |
| `hid.usb1` | `/dev/hidg1` | Raw HID / Vial |

Vial GUI の通常検出は、上流 `vial-gui` の `util.py` にある
`VIAL_SERIAL_NUMBER_MAGIC = "vial:f64c2b3c"` と Raw HID
`usage_page=0xFF60`, `usage=0x61` に依存する。serialはmagicのsubstring包含で判定されるため、
development profileは固定値、public formal profileは`vial:f64c2b3c:hidloom`を使う。いずれも
node名へ置換せず、`config/public-usb-identity.json`のcontractで検査する。

一方、Vial GUI の device list 表示は `vial_device.py` の `title()` で
`manufacturer_string` と `product_string` を連結して作られる。複数台接続時に
見分けられるよう、`setup_usb_gadget.sh` は `config/default/config.json` の
`__HOSTNAME__` を `uname -n` に展開し、USB manufacturer / product string に
node 名を入れる。Linux HID gadget の Raw HID interface は個別の
function-level string を持てないため、Vial 上では
`<keyboard-host> HID Interface` のように OS/hidapi 由来の `HID Interface`
suffix が付くことがある。

この順にする理由:

1. README の設計図と一致する。
2. `hidg0 = 入力本体`, `hidg1 = 管理チャネル` という意味が明快になる。
3. `hidloom-hidd` が扱う USB 由来イベントを自然に整理できる。

## デーモン責務

## 入力検証とログ基準

今後の機能追加でも、入力境界では同じログ粒度を維持する。

- 外部入力は信頼しない。対象は USB Raw HID packet、Unix socket JSON、設定ファイル、環境変数。
- 範囲外・未対応・壊れた payload・処理不能な状態は `warning` にする。
- 復旧可能な丸めも `warning` にし、元値と採用値を同じログに残す。
- 正常な高頻度イベントは `debug` に留める。
- ctrl socket のように応答できる経路では、失敗時に `{ "result": "error", "msg": "..." }` を返す。
- Vial GUI 操作が反映されない場合は、まず次で原因を追える状態を維持する。

```bash
journalctl -u viald -u logicd-companion -u hidloom-logicd-core -u ledd -u hidloom-hidd -n 200 --no-pager
```

hardware なしで回せる入力検証の回帰テストは次でまとめて実行する。

```bash
python3 script/test_validation_suite.py
```

### `hidloom-hidd`

Phase 1:

```text
/dev/hidg1 <-> /tmp/viald_events.sock
```

Phase 2:

```text
/dev/hidg0 OUT report -> /tmp/ctrl_events.sock
```

`hidloom-hidd` は Vial コマンドを解釈しない。固定長 Raw HID パケットを透過的に中継する。

### `viald`

担当:

- Vial handshake
- keyboard definition 応答
- dynamic keymap GET / SET
- VialRGB コマンドの内部表現への変換

担当しない:

- `/dev/hidg*` の open
- キーマップ状態の保持
- LED の直接描画

### `logicd`

担当:

- ランタイムキーマップの正本
- `ctrl_events.sock` の受け口
- キーマップ保存 API
- LED 状態変更を `ledd_events.sock` へ中継

既存 API:

```json
{"t":"G"}
{"t":"M","l":1,"r":3,"c":5,"a":"KC_A"}
```

追加予定 API:

```json
{"t":"S"}
{"t":"LED","op":"select","vial_effect":1}
{"t":"LED","op":"param","name":"brightness","value":128}
{"t":"LED","op":"param","name":"speed","value":96}
{"t":"LED","op":"param","name":"color","value":{"r":255,"g":0,"b":64}}
{"t":"LED","op":"direct","frame":[[255,0,0],[0,0,0],...]}
```

### `ledd`

担当:

- アニメーション実装
- VialRGB 互換パラメータの反映
- direct frame 描画の実行

既存の `ANIM(N)` は残しつつ、将来は Vial/VialRGB が使う識別子体系を正として
パラメータ付き制御を受けられるようにする。

## LED 制御の流れ

VialRGB を `ledd` のアニメーション基盤へ統合する場合も、経路は直結させない。

```text
Vial GUI
  -> viald
  -> ctrl_events.sock
  -> logicd
  -> ledd_events.sock
  -> ledd
```

この形にする理由:

1. Vial / Web UI / キー操作の LED 状態を 1 箇所で整合させられる。
2. 将来 OLED など別出力へ同じ状態を通知しやすい。
3. `ledd` を Vial 専用実装にしなくて済む。

## `ledd_events.sock` の拡張案

既存:

```json
{"t":"anim","id":1}
```

拡張:

```json
{"t":"anim","id":1,"source":"keymap"}
{"t":"anim","vial_effect":3,"source":"vialrgb","params":{"brightness":128,"speed":96}}
{"t":"anim_param","name":"brightness","value":128}
{"t":"anim_param","name":"speed","value":96}
{"t":"anim_param","name":"color","value":{"r":255,"g":0,"b":64}}
{"t":"frame","source":"vialrgb","pixels":[[255,0,0],[0,0,0],...]}
```

方針:

- `anim` は「どのアニメーションを使うか」
- `anim_param` は「現在アニメーションへ渡すパラメータ」
- `frame` は「VialRGB direct mode のような直接描画」

として役割を分ける。

## `ledd` 側の設計拡張

### `AnimationBase` 追加候補

```python
def on_param(self, name: str, value: object) -> None:
    ...
```

### `AnimationManager` 追加候補

```python
def set_param(self, name: str, value: object) -> None:
    ...

def render_frame(self, pixels: list[list[int]]) -> None:
    ...
```

これにより:

- 既存の `bounce` / `ripple`
- 将来の VialRGB エフェクト
- VialRGB direct frame

を同じ `ledd` の中で共存させられる。

## VialRGB について

`config/default/vial.json` の `"lighting": "vialrgb"` は維持する。

理由:

1. 最終目標が VialRGB 対応である。
2. `ledd` 側を VialRGB の受け皿として拡張する方針が決まっている。
3. 一時的に `"none"` へ落とすより、設計の到達点をファイル上にも残したほうがよい。

ただし、effect 識別子の型は upstream 調査後に確定する。
調査項目は [../../../research/vialrgb-upstream.md](../../../research/vialrgb-upstream.md) に分離する。

実装順は段階化する。

1. Vial detect
2. keymap GET / SET
3. Vial-native LED effect select
4. brightness / speed / color
5. direct frame

## キーマップ永続化

ランタイムキーマップの保存責務は `logicd` に置く。

追加予定:

```json
{"t":"S"}
```

保存先:

```text
/mnt/p3/keymap.json
```

推奨:

- atomic write
- `.tmp` へ書いて rename
- 必要なら backup 生成

## 実装順

### Stage 0: USB gadget 再編

- `hidg0 = keyboard / mouse / consumer control multi-report`
- `hidg1 = raw hid / vial`

### Stage 1: Raw HID transport

- `usbd`
- `/tmp/viald_events.sock`

### Stage 2: Vial detect

- `viald`
- handshake
- keyboard definition

### Stage 3: Dynamic keymap GET

- `viald -> logicd(G)`

### Stage 4: Dynamic keymap SET

- `viald -> logicd(M)`

### Stage 5: Persistence

- `logicd(S)`

### Stage 6: VialRGB

- `viald -> logicd(LED) -> ledd`
- effect / brightness / speed / color / direct frame

## 決定事項

- 新しい `doc/` は作らず、既存の `docs/` を使う。
- `viald` はキーマップの正本を持たない。
- `viald` は `ledd` に直結しない。
- `lighting` は `"vialrgb"` を維持する。
- Vial/VialRGB が effect を番号管理するなら番号を、名前管理するなら名前を内部 API の正本として採用する。
- 独自アニメーションは Vial が使っていない識別子空間へ追加する。
- `ledd` は既存アニメーション方式を残しつつ、Vial-native な識別子、パラメータ付き制御、direct frame を受けられるように拡張する。
