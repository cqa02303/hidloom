# Board profiles

更新日: 2026-06-05

CQA02303v5 の基板配線差分を、実機ごとの git 追跡外 marker と repo 内 profile で管理します。
`ver1.0` を標準基板、`ver0.1` を試作基板として扱います。

## Policy

- marker がない実機は `ver1.0` とみなす。fresh install は `ver1.0`
  marker を明示的に書く。
- `ver0.1` は試作基板なので、自動 fallback では選ばない。
- `ver0.1` は fresh install 時、または `--prototype` 付きの明示コマンドでだけ選ぶ。
- 基板 version を変える時は fresh install を基本とし、古い `/mnt/p3/keymap.json` を流用しない。
- repo 内の `config/default/` は選択した board profile から作る。

## Runtime marker

実機ごとの選択は git 追跡外の次のファイルに置きます。

```text
/mnt/p3/board_profile.json
```

`<keyboard-host>` と `<keyboard-host>` は `ver1.0` 標準基板として動かします。
marker がない既存環境も `ver1.0` fallback として読みますが、fresh install や
再セットアップ時は明示 marker を書きます。

```json
{
  "board_version": "ver1.0",
  "device_name": "<keyboard-host>",
  "prototype": false
}
```

```json
{
  "board_version": "ver1.0",
  "device_name": "<keyboard-host>",
  "prototype": false
}
```

## Status visibility

`/api/status.board_profile` は marker を read-only に読み、次を返します。

- `board_version`: marker の `board_version`。marker 欠落時は `ver1.0`。
- `source`: `marker` / `fallback` / `error`。
- `marker_exists`: `/mnt/p3/board_profile.json` が存在するか。
- `prototype`: `ver0.1` 試作基板 marker では `true`。
- `device_name`: marker に記録された実機名。

HTTP System panel では `Board` row として表示します。
`ver0.1` は `prototype` と明示し、通常の `ver1.0` fallback と見分けます。

## Repository layout

```text
config/boards/
  ver0.1/
    board.json
    config/default/
      matrixd.json
      keymap.json
      keyboard-layout.json
      vial.json
      ledd.json
      i2cd.json
  ver1.0/
    board.json
    config/default/
      matrixd.json
      keymap.json
      keyboard-layout.json
      vial.json
      ledd.json
      i2cd.json
```

`ver1.0` の配線差分は `config/boards/ver1.0/conf/` へ先に反映し、必要な実機へ反映します。
2026-05-30 時点では、`<keyboard-host>` で ESC 位置が `[7,0]` として出るため、
ver1.0 keymap では `[7,0]` を `KC_ESC`、`[6,0]` を `KC_BTN2` にしています。
同じ実機で analog stick は物理左右が AIN0、物理上下が AIN1 として観測されたため、
ver1.0 `i2cd.json` では x=`AIN0 invert`、y=`AIN1 invert`、deadzone=`20` にしています。
ver1.0 の LED chain は試作基板の先頭 test LED を持たず、KiCad の配線順に合わせて
`ESC` 行から開始する 81 LED 定義です。行方向は `ESC` 行 `→`、数字行 `←`、Tab 行 `→`、
Caps 行 `←`、Shift 行 `→`、最下段は `↑ ← Shift BS Enter Space Ctrl Shift Del Alt 無変換 変換 Win ↓ →`
の順です。
初期 keymap では、ひらがな/かな側の layer-tap を `LT(2,KC_LANG1)` に固定し、
layer2 の Func 列に `KC_F13`-`KC_F24` を入れています。fresh install や
runtime keymap reset 後も、layer2 overlay color と F13-F24 の確認をすぐ行えるようにするためです。

## Apply commands

現在の marker または fallback を見る:

```sh
python3 script/apply_board_profile.py --status
```

profile 一覧を見る:

```sh
python3 script/apply_board_profile.py --list
```

標準基板 `ver1.0` を repo の `config/default/` へ反映し、runtime keymap をリセットする:

```sh
sudo python3 script/apply_board_profile.py ver1.0 \
  --repo-conf \
  --write-marker \
  --device-name "$(hostname)" \
  --reset-runtime-keymap \
  --restart-services
```

試作基板 `ver0.1` を明示反映する:

```sh
sudo python3 script/apply_board_profile.py ver0.1 \
  --prototype \
  --repo-conf \
  --write-marker \
  --device-name "$(hostname)" \
  --reset-runtime-keymap \
  --restart-services
```

`--reset-runtime-keymap` は `/mnt/p3/keymap.json` を
`/mnt/p3/keymap.json.bak.<timestamp>` へ退避します。
`logicd` は `/mnt/p3/keymap.json` がある場合に `config/default/keymap.json` より優先するため、
matrix 座標や物理対応が変わる board 切替では必ず reset します。

## Fresh install

fresh install の既定は `ver1.0` で、`/mnt/p3/board_profile.json` に marker を書きます。
`ver0.1` 試作基板へ install する場合だけ、install 後に次を実行してから reboot します。

```sh
sudo python3 script/apply_board_profile.py ver0.1 \
  --prototype \
  --repo-conf \
  --write-marker \
  --device-name "$(hostname)" \
  --reset-runtime-keymap
```

## Files included in a profile

- `matrixd.json`: GPIO / row / col scanning
- `keymap.json`: initial keymap and matrix coordinate layout metadata
- `keyboard-layout.json`: HTTP UI physical layout
- `vial.json`: Vial matrix / layout metadata
- `ledd.json`: LED order, matrix coordinate map, semantic role overrides
- `i2cd.json`: OLED / ADS1115 / analog stick wiring

`keycodes.json`、`key_labels.json`、`config.json`、`config/default/script/` は基板配線差分ではないため、
初期 profile には含めません。
