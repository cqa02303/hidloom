#!/usr/bin/env python3
"""
KiCad解析結果から完全なマトリックス対応表を生成
"""

import json
import re


def _ref_sort_key(ref):
    m = re.match(r'([A-Za-z]+)(\d+)', ref)
    if not m:
        return (99, 0)
    prefix_order = {"SW": 0, "JOY": 1}.get(m.group(1).upper(), 9)
    return (prefix_order, int(m.group(2)))


def load_analysis_results(json_file):
    """解析結果JSONを読み込み"""
    with open(json_file, 'r', encoding='utf-8') as f:
        return json.load(f)

def generate_final_report(data):
    """最終的なマトリックス対応表レポートを生成"""
    report = []

    report.append("=" * 80)
    report.append("KiCad回路図 keymap.kicad_sch - キースイッチマトリックス解析結果")
    report.append("=" * 80)
    report.append("")

    # サマリー情報
    analysis_info = data['analysis_info']
    report.append("## 解析サマリー")
    report.append(f"・実装スイッチ数: {analysis_info['populated_switches']}個")
    report.append(f"・マトリックスサイズ: 10 x 10 (チャーリープレックス対応)")
    report.append(f"・ROWライン: {analysis_info['row_labels']}本 (ROW1-ROW10)")
    report.append(f"・COLライン: {analysis_info['col_labels']}本 (COL1-COL10, col1-col10)")
    report.append("")

    # スイッチ-ROW/COL対応表
    report.append("## 各スイッチのROW/COL接続対応表")
    report.append("SW番号 | ROW番号 | COL番号 | 物理座標(X,Y) | ネット名")
    report.append("-" * 70)

    switches = data['switches']

    # SW 番号 → JOY 番号 の順でソート
    sorted_switches = sorted(switches.items(), key=lambda x: _ref_sort_key(x[0]))

    for ref, switch_data in sorted_switches:
        matrix_pos = switch_data['estimated_matrix_pos']
        row_num = matrix_pos[0]
        col_num = matrix_pos[1]
        if 'sch_position' in switch_data:
            x, y = switch_data['sch_position']
        else:
            x, y = switch_data['position']

        # 物理ネット名は回路図ラベルに合わせて1始まり
        net_name = f"ROW{row_num + 1}, COL{col_num + 1}"
        source = switch_data.get('source', 'sw_push')
        note = " (joystick click)" if source == 'joystick_click' else ""

        report.append(f"{ref:6} | ROW{row_num:2} | COL{col_num:2}  | ({x:6.1f},{y:6.1f}) | {net_name}{note}")

    report.append("")

    # チャーリープレックスマトリックス位置表
    report.append("## チャーリープレックス 10x10 マトリックス配置")
    report.append("マトリックス位置 [ROW, COL] でのスイッチ配置図:")
    report.append("")

    # マトリックスを初期化
    matrix = [["   " for _ in range(10)] for _ in range(10)]

    # スイッチを配置
    for ref, switch_data in switches.items():
        matrix_pos = switch_data['estimated_matrix_pos']
        row_idx = matrix_pos[0]
        col_idx = matrix_pos[1]
        if ref.startswith("SW"):
            cell = f"{ref[2:]:>3}"
        elif ref.startswith("JOY"):
            cell = f" J{ref[3:]}"
        else:
            cell = f"{ref[:3]:>3}"
        matrix[row_idx][col_idx] = cell

    # ヘッダー
    col_header = "ROW\\COL " + "".join(f"{i:4}" for i in range(10))
    report.append(col_header)
    report.append("-" * 50)

    # マトリックス表示
    for i, row in enumerate(matrix):
        row_str = f"ROW{i:2}: " + "".join(f"{cell:>4}" for cell in row)
        report.append(row_str)

    report.append("")

    # ROW/COLライン物理座標情報
    report.append("## ROW/COLライン物理座標情報")

    if 'labels' in data:
        labels = data['labels']

        # ROWラベル
        row_labels = {name: info for name, info in labels.items()
                     if re.match(r'ROW\d+', name)}
        report.append("\n### ROWライン座標:")
        for row_num in range(1, 11):
            row_name = f"ROW{row_num}"
            if row_name in row_labels:
                if 'sch_position' in row_labels[row_name]:
                    x, y = row_labels[row_name]['sch_position']
                else:
                    x, y = row_labels[row_name]['position']
                report.append(f"  {row_name}: X={x:7.2f}, Y={y:7.2f}")

        # COLラベル
        col_labels = {name: info for name, info in labels.items()
                     if re.match(r'(COL|col)\d+', name)}
        report.append("\n### COLライン座標:")
        for col_num in range(1, 11):
            col_name_upper = f"COL{col_num}"
            col_name_lower = f"col{col_num}"

            if col_name_upper in col_labels:
                if 'sch_position' in col_labels[col_name_upper]:
                    x, y = col_labels[col_name_upper]['sch_position']
                else:
                    x, y = col_labels[col_name_upper]['position']
                report.append(f"  {col_name_upper}: X={x:7.2f}, Y={y:7.2f}")
            elif col_name_lower in col_labels:
                if 'sch_position' in col_labels[col_name_lower]:
                    x, y = col_labels[col_name_lower]['sch_position']
                else:
                    x, y = col_labels[col_name_lower]['position']
                report.append(f"  {col_name_lower}: X={x:7.2f}, Y={y:7.2f}")

    report.append("")

    # BAVダイオード情報（チャーリープレックス用）
    report.append("## チャーリープレックス回路の特徴")
    report.append("・各キースイッチはBAV70/BAV99ダイオードと組み合わせてチャーリープレックス回路を構成")
    report.append("・10本のROWライン × 10本のCOLラインで最大100キー対応")
    report.append("・実際には86キー相当のキーレイアウトに対応（83キー実装）")
    report.append("・双方向接続により、ROW→COL および COL→ROW の両方向スキャンが可能")
    report.append("")

    # 欠番スイッチの確認 (JOY/エンコーダで代用される SW は除外)
    all_sw_nums = set(range(1, 91))  # SW1-SW90想定
    actual_sw_nums = set()
    for ref in switches.keys():
        if not ref.startswith("SW"):
            continue
        m = re.match(r'SW(\d+)', ref)
        if not m:
            continue
        # 末尾に英字が付く (例: SW91A) ものは「物理スイッチ番号」ではないので除外
        if not re.fullmatch(r'SW\d+', ref):
            continue
        actual_sw_nums.add(int(m.group(1)))

    def _predicted_sw_at(r, c):
        """SW 番号体系 (行順・対角スキップ) から [r,c] に対応する SW 番号を推定。"""
        n = 0
        for rr in range(10):
            for cc in range(10):
                if rr == cc:
                    continue
                n += 1
                if rr == r and cc == c:
                    return n
        return None

    occupied = []  # (sw_num, virtual_ref, kind)
    for ref, sw in switches.items():
        source = sw.get('source', 'sw_push')
        if source not in ('joystick_click', 'encoder_pulse'):
            continue
        r, c = sw['estimated_matrix_pos']
        predicted = _predicted_sw_at(r, c)
        if predicted is not None and predicted in (all_sw_nums - actual_sw_nums):
            occupied.append((predicted, ref, source))

    occupied_nums = {n for n, _, _ in occupied}
    missing_sw_nums = sorted((all_sw_nums - actual_sw_nums) - occupied_nums)

    if occupied:
        report.append("## 仮想スイッチで代用されている SW 番号")
        kind_label = {
            'joystick_click': 'ジョイスティッククリック',
            'encoder_pulse': 'ロータリーエンコーダパルス',
        }
        for sw_num, virt_ref, kind in sorted(occupied):
            report.append(f"  SW{sw_num} ← {virt_ref} ({kind_label.get(kind, kind)})")
        report.append("")

    if missing_sw_nums:
        report.append("## 欠番/未実装スイッチ")
        report.append(f"以下のスイッチ番号は回路図に存在しません:")
        for i, sw_num in enumerate(missing_sw_nums):
            if i % 10 == 0:
                report.append("")
            report.append(f"SW{sw_num:2} ")
        report.append("")

    return "\n".join(line.rstrip() for line in report)

def main():
    import sys
    if len(sys.argv) != 2:
        print("Usage: python generate_final_matrix_report.py <matrix_analysis.json>")
        sys.exit(1)

    json_file = sys.argv[1]
    data = load_analysis_results(json_file)

    report = generate_final_report(data)
    print(report)

    # テキストファイルにも保存
    output_file = json_file.replace('.json', '_final_report.txt')
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(report + "\n")

    print(f"\n最終レポートを保存しました: {output_file}")

if __name__ == "__main__":
    main()
