#!/usr/bin/env python3
"""
KiCad keymap.kicad_sch ファイルを解析して、実装されるキースイッチの物理的配置とROW/COL対応を推定

改良版:
1. dnp(do not populate)のスイッチを除外
2. 座標をグリッドで分析してマトリックス位置を推定
3. global_labelとhierarchical_labelを基にROW/COL対応を推定
"""

import re
import json
import math
import os
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from collections import defaultdict


def _ref_sort_key(ref: str) -> Tuple[int, int, str]:
    """\u53c2\u7167\u540d (SW##/SW##A/JOY##) \u3092\u30bd\u30fc\u30c8\u3059\u308b\u305f\u3081\u306e\u30ad\u30fc\u3002"""
    m = re.match(r'([A-Za-z]+)(\d+)([A-Za-z]*)', ref)
    if not m:
        return (99, 0, ref)
    prefix_order = {"SW": 0, "JOY": 1}.get(m.group(1).upper(), 9)
    return (prefix_order, int(m.group(2)), m.group(3))


@dataclass
class SwitchInfo:
    """スイッチ情報を格納するクラス"""
    reference: str
    x: float
    y: float
    uuid: str
    is_populated: bool = True
    estimated_row: Optional[int] = None
    estimated_col: Optional[int] = None
    source: str = "sw_push"

@dataclass
class LabelInfo:
    """ラベル情報を格納するクラス"""
    name: str
    x: float
    y: float
    label_type: str

class KiCadMatrixAnalyzer:
    def __init__(self, schema_file: str):
        self.schema_file = schema_file
        self.switches: Dict[str, SwitchInfo] = {}
        self.labels: Dict[str, LabelInfo] = {}
        self.grid_tolerance = 15.0  # 座標グリッドの許容誤差

    def parse_schema_file(self):
        """KiCadスキーマファイルを解析"""
        with open(self.schema_file, 'r', encoding='utf-8') as f:
            content = f.read()

        self._extract_switches(content)
        self._extract_labels(content)
        self._extract_joystick_switches(content)
        self._extract_encoder_switches(content)
        self._estimate_matrix_positions()
        self._estimate_row_col_mapping()

    def _extract_switches(self, content: str):
        """スイッチの情報を抽出（dnp設定も含む）"""
        # スイッチのパターンを拡張してdnp設定も抽出
        switch_pattern = re.compile(
            r'\(symbol\s*\n\s*\(lib_id\s+"[^"]*SW_PUSH"\)\s*\n\s*\(at\s+([\d.]+)\s+([\d.]+).*?\n(.*?)'
            r'\(property\s+"Reference"\s+"(SW\d+)".*?\n.*?'
            r'\(uuid\s+"([^"]+)"\)',
            re.MULTILINE | re.DOTALL
        )

        for match in switch_pattern.finditer(content):
            x, y, middle_section, reference, uuid = match.groups()

            # dnp設定をチェック
            is_populated = "(dnp yes)" not in middle_section and "(dnp no)" not in middle_section or "(dnp no)" in middle_section

            if is_populated:  # 実装されるスイッチのみ
                self.switches[reference] = SwitchInfo(
                    reference=reference,
                    x=float(x),
                    y=float(y),
                    uuid=uuid,
                    is_populated=is_populated
                )

    def _extract_labels(self, content: str):
        """グローバル/階層ラベルの情報を抽出"""
        # global_labelのパターン
        global_pattern = re.compile(
            r'\(global_label\s+"([^"]+)"\s*\n.*?\n\s*\(at\s+([\d.]+)\s+([\d.]+)',
            re.MULTILINE | re.DOTALL
        )

        for match in global_pattern.finditer(content):
            name, x, y = match.groups()
            self.labels[name] = LabelInfo(
                name=name,
                x=float(x),
                y=float(y),
                label_type="global_label"
            )

        # hierarchical_labelのパターン
        hier_pattern = re.compile(
            r'\(hierarchical_label\s+"([^"]+)"\s*\n.*?\n\s*\(at\s+([\d.]+)\s+([\d.]+)',
            re.MULTILINE | re.DOTALL
        )

        for match in hier_pattern.finditer(content):
            name, x, y = match.groups()
            if name not in self.labels:  # global_labelを優先
                self.labels[name] = LabelInfo(
                    name=name,
                    x=float(x),
                    y=float(y),
                    label_type="hierarchical_label"
                )

    def _extract_joystick_switches(self, content: str):
        r"""ジョイスティッククリックボタンをマトリクス上のスイッチとして抽出する。

        マトリクス領域内に配置された global_label "JOY\d+" をクリックスイッチとみなし、
        switches に参照名 JOY\d+ として追加する。マトリクス位置は 後段の
        _estimate_matrix_positions で SW と同じグリッドにスナップされる。
        """
        if not self.switches:
            return

        # SW の坐標範囲をマトリクス領域とみなす
        sw_xs = [sw.x for sw in self.switches.values()]
        sw_ys = [sw.y for sw in self.switches.values()]
        x_min, x_max = min(sw_xs) - self.grid_tolerance, max(sw_xs) + self.grid_tolerance
        y_min, y_max = min(sw_ys) - self.grid_tolerance, max(sw_ys) + self.grid_tolerance

        joy_pattern = re.compile(
            r'\(global_label\s+"(JOY\d+)"\s*\n.*?\n\s*\(at\s+([\d.]+)\s+([\d.]+).*?\n.*?\(uuid\s+"([^"]+)"\)',
            re.MULTILINE | re.DOTALL
        )

        for match in joy_pattern.finditer(content):
            name, x_str, y_str, uuid = match.groups()
            x, y = float(x_str), float(y_str)
            # マトリクス領域内のラベルのみ採用
            if not (x_min <= x <= x_max and y_min <= y <= y_max):
                continue
            if name in self.switches:
                continue  # 重複を避ける
            self.switches[name] = SwitchInfo(
                reference=name,
                x=x,
                y=y,
                uuid=uuid,
                is_populated=True,
                source="joystick_click",
            )

    def _extract_encoder_switches(self, content: str):
        """ロータリーエンコーダの A/B パルススイッチをマトリクス上のスイッチとして抽出する。

        - lib_id に RotaryEncoder を含むシンボルをエンコーダとして検出し、
          その Reference (例: SW91) を取得する。Reference 番号順で EC1, EC2 ... に対応させる。
        - マトリクス領域内にある EC<N>A / EC<N>B の global_label を抽出し、
          <encoder_ref>A / <encoder_ref>B という参照名で switches に追加する。
        """
        if not self.switches:
            return

        sw_xs = [sw.x for sw in self.switches.values() if sw.source == "sw_push"]
        sw_ys = [sw.y for sw in self.switches.values() if sw.source == "sw_push"]
        if not sw_xs or not sw_ys:
            return
        x_min, x_max = min(sw_xs) - self.grid_tolerance, max(sw_xs) + self.grid_tolerance
        y_min, y_max = min(sw_ys) - self.grid_tolerance, max(sw_ys) + self.grid_tolerance

        encoder_pattern = re.compile(
            r'\(symbol\s*\n\s*\(lib_id\s+"[^"]*RotaryEncoder[^"]*"\)\s*\n\s*\(at\s+([\d.]+)\s+([\d.]+).*?\n(.*?)'
            r'\(property\s+"Reference"\s+"(SW\d+)"',
            re.MULTILINE | re.DOTALL,
        )
        encoder_refs: List[str] = []
        for match in encoder_pattern.finditer(content):
            ref = match.group(4)
            if ref not in encoder_refs:
                encoder_refs.append(ref)
        encoder_refs.sort(key=lambda r: int(r[2:]))
        if not encoder_refs:
            return

        ec_label_pattern = re.compile(
            r'\(global_label\s+"EC(\d+)([AB])"\s*\n.*?\n\s*\(at\s+([\d.]+)\s+([\d.]+).*?\n.*?\(uuid\s+"([^"]+)"\)',
            re.MULTILINE | re.DOTALL,
        )
        for match in ec_label_pattern.finditer(content):
            idx_str, suffix, x_str, y_str, uuid = match.groups()
            idx = int(idx_str)
            if not (1 <= idx <= len(encoder_refs)):
                continue
            x, y = float(x_str), float(y_str)
            if not (x_min <= x <= x_max and y_min <= y <= y_max):
                continue
            ref = f"{encoder_refs[idx - 1]}{suffix}"
            if ref in self.switches:
                continue
            self.switches[ref] = SwitchInfo(
                reference=ref,
                x=x,
                y=y,
                uuid=uuid,
                is_populated=True,
                source="encoder_pulse",
            )

    def _find_unique_coordinates(self, coords: List[float], tolerance: float) -> List[float]:
        """座標リストから一意なグリッド位置を検出"""
        if not coords:
            return []

        sorted_coords = sorted(coords)
        unique_coords = [sorted_coords[0]]

        for coord in sorted_coords[1:]:
            if coord - unique_coords[-1] > tolerance:
                unique_coords.append(coord)

        return unique_coords

    def _estimate_matrix_positions(self):
        """座標からマトリックス位置を推定"""
        # 全スイッチのX,Y座標を収集
        x_coords = [sw.x for sw in self.switches.values()]
        y_coords = [sw.y for sw in self.switches.values()]

        # 一意なX座標(列)とY座標(行)を検出
        unique_x = self._find_unique_coordinates(x_coords, self.grid_tolerance)
        unique_y = self._find_unique_coordinates(y_coords, self.grid_tolerance)

        print(f"Detected X coordinates (columns): {len(unique_x)} positions")
        print(f"Detected Y coordinates (rows): {len(unique_y)} positions")

        # 各スイッチのマトリックス位置を推定
        for sw in self.switches.values():
            # 最も近いX座標(列)を見つける
            col_idx = min(range(len(unique_x)),
                         key=lambda i: abs(unique_x[i] - sw.x))

            # 最も近いY座標(行)を見つける
            row_idx = min(range(len(unique_y)),
                         key=lambda i: abs(unique_y[i] - sw.y))

            sw.estimated_col = col_idx
            sw.estimated_row = row_idx

    def _estimate_row_col_mapping(self):
        """ROW/COLラベルから実際のマトリックス対応を推定"""
        # ROW/COLラベルの座標を分析
        row_labels = {name: label for name, label in self.labels.items()
                     if re.match(r'ROW\d+', name)}
        col_labels = {name: label for name, label in self.labels.items()
                     if re.match(r'(COL|col)\d+', name)}

        print(f"\nFound ROW labels: {list(row_labels.keys())}")
        print(f"Found COL labels: {list(col_labels.keys())}")

        # ROWラベルのY座標でソート
        sorted_rows = sorted(row_labels.items(),
                           key=lambda x: x[1].y)

        # COLラベルのX座標でソート
        sorted_cols = sorted(col_labels.items(),
                           key=lambda x: x[1].x)

        print(f"\nROW labels by Y coordinate:")
        for i, (name, label) in enumerate(sorted_rows):
            print(f"  {name}: Y={label.y}")

        print(f"\nCOL labels by X coordinate:")
        for i, (name, label) in enumerate(sorted_cols):
            print(f"  {name}: X={label.x}")

    def generate_matrix_report(self) -> str:
        """マトリックス配置レポートを生成"""
        report = []
        report.append("=== キースイッチ マトリックス配置解析結果 ===\n")

        # 実装されるスイッチの数
        populated_count = len([sw for sw in self.switches.values() if sw.is_populated])
        report.append(f"実装されるスイッチ数: {populated_count}")

        # マトリックスサイズ
        max_row = max(sw.estimated_row for sw in self.switches.values() if sw.estimated_row is not None)
        max_col = max(sw.estimated_col for sw in self.switches.values() if sw.estimated_col is not None)
        row_count = max_row + 1
        col_count = max_col + 1
        report.append(f"推定マトリックスサイズ: {row_count} x {col_count}")

        # スイッチリスト
        report.append("\n=== スイッチリスト ===")
        report.append("Reference | 推定位置[行,列]")
        report.append("-" * 30)

        for ref in sorted(self.switches.keys(), key=_ref_sort_key):
            sw = self.switches[ref]
            report.append(f"{ref:8} | [{sw.estimated_row:2},{sw.estimated_col:2}]")

        # マトリックス配置図
        report.append(f"\n=== マトリックス配置図 ({row_count}x{col_count}) ===")

        # マトリックスを初期化
        matrix = [["   " for _ in range(col_count)] for _ in range(row_count)]

        # スイッチを配置
        for sw in self.switches.values():
            if sw.is_populated and sw.estimated_row is not None and sw.estimated_col is not None:
                row_idx = sw.estimated_row
                col_idx = sw.estimated_col
                if sw.reference.startswith("SW"):
                    cell = f"{sw.reference[2:]:>3}"
                elif sw.reference.startswith("JOY"):
                    cell = f" J{sw.reference[3:]}"
                else:
                    cell = f"{sw.reference[:3]:>3}"
                matrix[row_idx][col_idx] = cell

        # マトリックスを表示
        col_header = "    " + "".join(f"{i:4}" for i in range(col_count))
        report.append(col_header)

        for i, row in enumerate(matrix):
            if all(cell.strip() == "" for cell in row):
                continue
            row_str = f"{i:2}: " + "".join(f"{cell}" for cell in row)
            report.append(row_str.rstrip())

        return "\n".join(report)

    def save_detailed_results(self, output_file: str):
        """詳細結果をJSONファイルに保存"""
        results = {
            'analysis_info': {
                'populated_switches': len([sw for sw in self.switches.values() if sw.is_populated]),
                'total_switches_found': len(self.switches),
                'row_labels': len([name for name in self.labels.keys() if 'ROW' in name]),
                'col_labels': len([name for name in self.labels.keys() if 'COL' in name or 'col' in name])
            },
            'switches': {
                ref: {
                    'reference': sw.reference,
                    'sch_position': [sw.x, sw.y],
                    'estimated_matrix_pos': [sw.estimated_row, sw.estimated_col],
                    'is_populated': sw.is_populated,
                    'uuid': sw.uuid,
                    'source': sw.source,
                } for ref, sw in self.switches.items()
            },
            'labels': {
                name: {
                    'name': label.name,
                    'sch_position': [label.x, label.y],
                    'type': label.label_type
                } for name, label in self.labels.items()
            }
        }

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
            f.write("\n")

def main():
    repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    schema_file = os.path.normpath(
        os.path.join(repo_root, "kicad", "cqa02303v5rpi", "keymap.kicad_sch")
    )
    if not os.path.exists(schema_file):
        raise FileNotFoundError(f"KiCad schematic source not found: {schema_file}")

    analyzer = KiCadMatrixAnalyzer(schema_file)
    analyzer.parse_schema_file()

    # レポート生成と表示
    report = analyzer.generate_matrix_report()
    print(report)

    output_dir = os.path.join(repo_root, "build", "generated")
    os.makedirs(output_dir, exist_ok=True)

    base_name = os.path.splitext(os.path.basename(schema_file))[0]
    report_output = os.path.join(output_dir, f"{base_name}_matrix_analysis_final_report.txt")
    with open(report_output, 'w', encoding='utf-8') as f:
        f.write(report + "\n")
    print(f"\nレポートを保存しました: {report_output}")

    # 詳細結果をJSONに保存
    json_output = os.path.join(output_dir, f"{base_name}_matrix_analysis.json")
    analyzer.save_detailed_results(json_output)
    print(f"\n詳細結果を保存しました: {json_output}")

if __name__ == "__main__":
    main()
