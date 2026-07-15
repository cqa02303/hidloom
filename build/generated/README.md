# build/generated/

解析スクリプトが作る中間成果物とレポートを置くディレクトリです。

実行時設定は `config/default/` に置き、KiCad / matrix 解析から再生成できるファイルはここに置きます。

| ファイル | 生成元 |
| --- | --- |
| `keymap_matrix_analysis.json` | `build/generators/analyze_kicad_matrix.py` |
| `keymap_matrix_analysis_final_report.txt` | `build/generators/analyze_kicad_matrix.py` |
| `pcb_analysis.json` | `build/generators/analyze_kicad_pcb.py` |
| `pcb_analysis_sw_report.txt` | `build/generators/analyze_kicad_pcb.py` |
| `vial_generation_report.txt` | `build/generators/mkvial.py` |

## keymap_matrix_analysis.json

KiCad 回路図から key switch と row/column label の位置関係を解析した中間成果物です。

- 座標キーは `position` ではなく `sch_position` を使用します。
- `sch_position` は回路図 (SCH) 上の座標です。
- マトリクス座標 `estimated_matrix_pos` は 0 始まりです。

switch entry の例:

```json
"SW36": {
  "reference": "SW36",
  "sch_position": [299.72, 114.3],
  "estimated_matrix_pos": [3, 9],
  "is_populated": true,
  "uuid": "..."
}
```

label entry の例:

```json
"ROW3": {
  "name": "ROW3",
  "sch_position": [50.8, 101.6],
  "type": "global_label"
}
```

## pcb_analysis.json

KiCad PCB から switch footprint や物理座標を解析した中間成果物です。
基板座標は keyboard 裏面から見た向きを基準にするため、他の表示座標と比較する時は
左右反転の扱いに注意します。

## Vial 生成時の注意

`build/generators/mkvial.py` は、まず [../../config/default/keyboard-layout.json](../../config/default/keyboard-layout.json)
の KLE slot を正とし、KiCad 解析から得た switch point を KLE slot 順へ割り当てます。
KiCad から判断できない例外は [../../config/default/vial-layout-overrides.json](../../config/default/vial-layout-overrides.json)
に明示します。

- `exclude_sources`: KiCad 解析結果には出るが Vial の通常キーにしない source。
  例: encoder A/B pulse。
- `slot_overrides`: `row:<row>,order:<order>` の KLE slot に matrix 座標を明示する。
- `virtual_slots`: 実 switch point を消費せず、Vial 表示用 label としてそのまま出す。

生成後は `build/generated/vial_generation_report.txt` を確認します。
`Unassigned Slots` や `Unassigned Switch Points` が数件だけなら、
`config/default/vial-layout-overrides.json` に追記して再生成します。

## 鮮度確認

canonical inputは`kicad/cqa02303v5rpi/keymap.kicad_sch`と
`kicad/cqa02303v5rpi/cqa02303v5rpi.kicad_pcb`です。
`make generated-artifact-check`は一時treeで依存generatorをすべて実行し、上表の生成物と
`config/default/vial.json`がtracked内容へbyte一致することを確認します。canonical inputが存在しない場合は、
既存JSONを再利用せず失敗します。
