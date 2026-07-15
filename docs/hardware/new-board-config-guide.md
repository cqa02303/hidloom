# New board config guide

更新日: 2026-06-15

この文書は、新しいキーボード基板を HIDloom の board profile として追加するための作業手順です。
実機がない状態でも、配線資料、KLE、KiCad、既存 profile を使って repo 内の config をそろえられる範囲を扱います。
実機でしか判断できない入力方向、debounce 体感、LED の見え方、host OS の認識は最後の checklist へ分離します。

## 完了条件

実機なしの段階では、次の状態を完了条件にします。

- `config/boards/<board-version>/board.json` と `conf/` 6 ファイルがそろっている。
- `matrixd.json`、`keymap.json`、`keyboard-layout.json`、`vial.json`、`ledd.json`、`i2cd.json` の座標体系が同じ matrix row / col を参照している。
- `script/apply_board_profile.py --list` と `script/test_board_profiles.py` が、新しい profile の存在と必須ファイルを検査できる。
- docs から、新しい profile の目的、適用条件、実機待ち項目へ辿れる。

実機なしの段階では、次を完了条件にしません。

- 実 switch の押下、rotary encoder の方向、analog stick の range 測定。
- LED chain の実発光順、眩しさ、電源余裕。
- Windows / Linux / macOS host での HID device 表示。
- Vial desktop / Vial web からの実接続。
- `/mnt/p3/board_profile.json` の書き込みや service restart。

## 作業全体の流れ

1. 新しい board version 名を決める。
2. 既存 profile を複製し、`board.json` を先に更新する。
3. matrix 座標を固定し、`matrixd.json` と `keymap.json` の row / col を合わせる。
4. HTTP UI 用の `keyboard-layout.json` と Vial 用の `vial.json` を同じ座標で作る。
5. LED がある場合は `ledd.json` の chain と semantic role を座標に合わせる。
6. OLED、ADS1115、analog stick、touch panel などが違う場合だけ `i2cd.json` を更新する。
7. 実機なしの静的レビューを通し、実機待ち項目を checklist に分離する。

## 1. Board version を決める

board version は `config/boards/` 直下の directory 名になります。
既存の `ver1.0` は標準基板、`ver0.1` は試作基板です。
新しい基板は、配線や物理配置が既存 profile と区別できる名前にします。

例:

```text
config/boards/ver1.1/
config/boards/proto-trackball-2026-06/
```

安定版として常用する基板は `ver1.1` のような短い version 名にし、一時的な試作や分岐検証は
`proto-...` のように明示します。
`board.json` の `board_version` は directory 名と一致させます。

新しい profile を default にするかは、実機確認が終わるまで保留します。
marker がない実機は現在 `ver1.0` に fallback するため、新 profile を追加しただけでは既存実機の挙動は変わりません。

## 2. Profile directory を作る

まず既存 profile を土台にして、必須ファイルを欠かさずそろえます。

```text
config/boards/<board-version>/
  board.json
  conf/
    matrixd.json
    keymap.json
    keyboard-layout.json
    vial.json
    ledd.json
    i2cd.json
```

最初に複製元を決めます。

- 配線が標準基板に近いなら `config/boards/ver1.0/` を複製する。
- 試作基板の配線に近いなら `config/boards/ver0.1/` を複製する。
- matrix 方式が大きく違う場合でも、6 ファイルを欠かさないために近い profile から始める。

`board.json` には、少なくとも次を入れます。

```json
{
  "board_version": "ver1.1",
  "title": "CQA02303v5 revised wiring",
  "prototype": false,
  "default": false,
  "notes": [
    "Derived from ver1.0.",
    "Do not select as fallback until real-device smoke is complete."
  ]
}
```

`prototype=true` の profile は、`script/apply_board_profile.py` で `--prototype` を付けないと選べません。
危険な試作配線や未確定配線を通常 fallback に混ぜないためです。

## 3. Matrix 座標を固定する

この project では、matrix 座標の文字列表現は基本的に `"row,col"` です。
同じ座標が複数ファイルに出るため、最初に座標表を固定します。

主に見るファイル:

- `conf/matrixd.json`: scan する row / col 数、GPIO、scan mode。
- `conf/keymap.json`: 各 layer の action が乗る matrix 座標。
- `conf/keyboard-layout.json`: HTTP UI での物理配置。
- `conf/vial.json`: Vial が見る matrix と layout。
- `conf/ledd.json`: LED と key matrix 座標の対応。

まず、物理キーごとに次を表にします。

| 物理位置 | matrix | 初期 action | 備考 |
| --- | --- | --- | --- |
| Esc | `7,0` | `KC_ESC` | 例 |
| A | `2,1` | `KC_A` | 例 |

この表は必ずしも repo に追加する必要はありませんが、迷う場合は `docs/hardware/` に補助表として残します。
配線資料が KiCad 由来なら、既存の [complete-matrix-coordinates.md](complete-matrix-coordinates.md) や
[keyswitch-matrix-map.md](keyswitch-matrix-map.md) と同じ粒度にそろえます。

## 4. `matrixd.json` を更新する

`matrixd.json` は scan daemon が読む配線定義です。
row / col GPIO、scan interval、debounce を扱います。

確認すること:

- `matrix.rows` / `matrix.cols` が座標表の最大 row / col を含む。
- `row_gpios` / `col_gpios` の順序が row / col 番号と一致する。
- charlieplex や row / col scan のような方式差分が `matrix_type` や既存 schema で表せる。
- `skip_same_index`、`row_drive`、`col_pull`、`key_active` が配線方式と矛盾しない。
- debounce は実機なしでは攻めず、既存 profile と同じ保守的な値から始める。

実機なしでは、debounce の最適値は決めません。
初期値は既存 profile に合わせ、実機で取りこぼしやチャタリングが見えた時だけ変更します。

## 5. `keymap.json` を更新する

`keymap.json` は初期 layer と runtime keymap reset 後の基準です。
`/mnt/p3/keymap.json` がある実機では runtime 側が優先されるため、board 切替時は reset が必要です。

作る時の方針:

- layer 0 は、実機が壊れていないか確認しやすい基本キーを優先する。
- 文字入力や Enter / Backspace / Esc など、smoke に使うキーは最初から入れる。
- layer 1 / layer 2 は、既存 profile と同じ検証用 action を残せるなら残す。
- `KC_SH*`、Wi-Fi、Bluetooth、shutdown など副作用のある action は、誤操作しにくい layer に置く。
- matrix 座標が変わった場合は、古い runtime keymap を流用しない。

`ver1.0` では、layer2 の `KC_F13`-`KC_F24` や `LT(2,KC_LANG1)` のように、確認しやすい既定 action を残しています。
新 profile でも、実機 smoke で使う固定 action を意図して置くと後の確認が楽になります。

## 6. `keyboard-layout.json` と `vial.json` をそろえる

HTTP UI と Vial は、どちらも matrix 座標と物理配置を扱います。
見た目だけを合わせるのではなく、同じ `"row,col"` が同じ物理キーを指すようにします。

確認すること:

- `keyboard-layout.json` に置いた座標が、`keymap.json` の座標と一致する。
- `vial.json` の `matrix.rows` / `matrix.cols` が `matrixd.json` と一致する。
- `vial.json.layouts.keymap` に、存在しない座標や重複座標が紛れない。
- Vial unlock key は、実際に押せる安全な 2 点を選ぶ。
- `customKeycodes` は board 固有ではなく project 全体の Vial custom action として扱う。

新しい基板で物理配列だけが違い、action や matrix scan が同じ場合でも、`keyboard-layout.json` と `vial.json` は
profile 側に分けます。
見た目の違いを runtime keymap や UI 側の特別扱いに逃がさないほうが、後で reset しやすくなります。

## 7. `ledd.json` を更新する

LED がある基板では、`ledd.json` が LED chain、matrix 座標、semantic role の橋渡しになります。
LED がない、または未配線の基板でも、既存 daemon が読める最小定義を残します。

確認すること:

- LED 数と chain 順が配線資料と一致する。
- 各 LED が対応する matrix 座標を持つ場合、`keymap.json` と同じ座標を使う。
- layer overlay、modifier overlay、host LED overlay の対象座標が存在する。
- 試作基板だけの test LED を標準基板へ混ぜない。
- 発光順や眩しさの判断は実機待ちへ残す。

実機なしでは、LED の物理的な向きや明るさは確定しません。
静的段階では、chain 数、座標参照、既存 semantic role との矛盾がないことを確認します。

## 8. `i2cd.json` を更新する

`i2cd.json` は OLED、ADS1115、analog stick、connectivity 表示などを扱います。
基板差分がないなら既存 profile をそのまま使います。

更新が必要な例:

- OLED の有無や I2C address が違う。
- ADS1115 の channel 割り当てが変わる。
- analog stick の x / y 軸、invert、deadzone が変わる。
- Zero / Zero 2 向けの描画負荷設定を基板ごとに変える必要がある。

実機なしでは、analog stick の center / range は決めません。
初期値は安全な既存値を置き、実機で `center` と `range` を測ってから runtime config 側へ反映します。

## 9. Apply 方針を決める

repo 内に profile を追加するだけなら、実機操作は不要です。
実機へ適用する段階では、[board-profiles.md](board-profiles.md) の方針に従います。

標準的な適用は次の形です。

```sh
sudo python3 script/apply_board_profile.py <board-version> \
  --repo-conf \
  --write-marker \
  --device-name "$(hostname)" \
  --reset-runtime-keymap \
  --restart-services
```

試作 profile では `--prototype` を追加します。

```sh
sudo python3 script/apply_board_profile.py <board-version> \
  --prototype \
  --repo-conf \
  --write-marker \
  --device-name "$(hostname)" \
  --reset-runtime-keymap \
  --restart-services
```

実機なし作業では、上の command を実行せず、手順として残すだけにします。
`--reset-runtime-keymap` は実機の `/mnt/p3/keymap.json` を退避する操作なので、実機確認時の明示作業です。

## 10. 実機なしでのレビュー

実機なしで見るべき観点は、ファイル間の一貫性です。

静的レビュー:

- `board.json` の `board_version` と directory 名が一致する。
- `conf/` に必須 6 ファイルがある。
- `matrixd.json` の row / col 数が、各 layout の座標を含む。
- `keymap.json` の各 layer が、存在する座標だけを参照する。
- `keyboard-layout.json` と `vial.json` の座標集合が、意図した物理キー集合と一致する。
- `ledd.json` の matrix 参照が存在しない座標を指していない。
- `i2cd.json` の channel / invert / deadzone は、実機未測定値と測定済み値を混同していない。

実行する確認:

```sh
python3 script/apply_board_profile.py --list
python3 script/test_board_profiles.py
python3 script/test_docs_links.py
```

新しい static test を追加する場合は、`script/test_board_profiles.py` へ profile の必須ファイル、manifest、
代表 keymap action を足します。
profile ごとの詳細な座標検査が増える場合は、別 test に分けても構いません。

## 11. 実機待ち checklist

実機でしか判断できないことは、profile の完成を止める理由にしません。
次のように private workspace reference *(omitted from public export)* へ残します。

- `matrixd` が全キーの press / release を取りこぼさない。
- row / col が逆、左右反転、上下反転していない。
- rotary encoder の左右方向、click、速回しの取りこぼしが許容範囲にある。
- LED chain が期待順に点灯し、role overlay が物理位置と一致する。
- OLED / analog stick / ADS1115 の値が実配線と一致する。
- Vial desktop / Vial web で layout と unlock key が使える。
- Windows / Linux / macOS host で keyboard / mouse / consumer route が期待通り認識される。

実機確認で profile の誤りが見つかった場合は、まず repo の `config/boards/<board-version>/conf/` を直し、
必要なら `config/default/` へ再適用します。
runtime keymap だけを手で直して解決した扱いにすると、fresh install や reset 後に同じ問題が戻ります。

## 12. よくある失敗

### 古い runtime keymap を流用してしまう

`/mnt/p3/keymap.json` は `config/default/keymap.json` より優先されます。
matrix 座標が変わる board profile では、runtime keymap を reset しないと古い座標の action が残ります。

### UI layout だけ直して scan 定義を直していない

HTTP UI や Vial の見た目が正しくても、`matrixd.json` の row / col / GPIO が違えば実入力は合いません。
見た目、scan、初期 keymap は同じ座標表から更新します。

### LED の試作差分を標準 profile に混ぜる

試作基板だけの test LED や仮配線を標準 profile に入れると、LED count や overlay の前提が壊れます。
試作差分は `prototype=true` の profile に閉じ込めます。

### 実機測定値と設計初期値を混同する

analog stick の center / range、OLED の見え方、debounce の体感値は実機で決める値です。
実機なしの config には「安全な初期値」を置き、測定後の runtime 値とは区別します。
