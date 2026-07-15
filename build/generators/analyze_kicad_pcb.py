#!/usr/bin/env python3
"""
KiCad PCB ファイルを解析し、build/generated/keymap_matrix_analysis.json に含まれる SW / JOY の
PCB座標 (右上原点) を付与した JSON を生成する。
"""

import copy
import json
import os
import re
from typing import Dict, Tuple


SwitchPos = Dict[str, Tuple[float, float]]


# ---------------------------------------------------------------------------
# キーボード物理レイアウト定義
# None = キーなし / 整数 = SW番号 (例: 5 → SW5)
# 14列固定グリッド (3文字/セル: "%2d " or "   ")
# ---------------------------------------------------------------------------
KEYBOARD_LAYOUT: list[list[int | None]] = [
    # row 0: ファンクション行
    [64, 91, 73, 74, 83, 82, 57, 58, 67, 66, 75, 76, 85, 84],
    # row 1: 数字/記号行
    [ 1,  2,  3,  4,  5,  6,  7,  8,  9, 59, 60, 61, 62, 63],
    # row 2: Q行
    [10, 11, 12, 13, 14, 15, 16, 17, 18, 68, 69, 70, 72, 72],
    # row 3: A行
    [19, 20, 21, 22, 23, 24, 25, 26, 27, 77, 78, 79, 80, None],
    # row 4: Z行
    [28, 29, 30, 31, 32, 33, 34, 35, 36, 86, 87, 81, None, None],
    # row 5: スペース/モディファイア行
    [37, 38, 39, 40, None, None, 42, 43, None, 45, None, None, None, None],
    # row 6: エンコーダ/特殊キー行
    [None, None, None, None, None, None, None, None, None, None, None, None, 60, None],
    # row 7: サムクラスター上段 (概略位置)
    [None, None, None, None, 50, 41, None, None, 44, 54, None, None, None, None],
    # row 8: サムクラスター下段 (概略位置)
    [None, None, 48, 49, None, None, 51, 52, None, 53, None, None, None, None],
]


def print_keyboard_layout() -> None:
    """キーボードの物理レイアウト順に SW 番号を表示する。"""
    print("=== キーボードレイアウト (SW番号) ===")
    print()
    for row in KEYBOARD_LAYOUT:
        line = ""
        for cell in row:
            if cell is None:
                line += "   "
            else:
                line += f"{cell:2d} "
        print(line.rstrip())
    print()



def _ref_num(ref: str) -> int:
	m = re.search(r"(\d+)", ref)
	return int(m.group(1)) if m else 0


def _extract_switch_positions_from_pcb(pcb_file: str) -> SwitchPos:
	"""PCBファイルから SW / JOY 参照名とフットプリント座標を抽出する。"""
	with open(pcb_file, "r", encoding="utf-8") as f:
		content = f.read()

	footprint_blocks = re.findall(r"\(footprint\s+\".*?\".*?\n\s*\)\n", content, re.DOTALL)

	switches: SwitchPos = {}
	ref_pattern = re.compile(r"\(property\s+\"Reference\"\s+\"((?:SW|JOY)\d+)\"")
	at_pattern = re.compile(r"\(at\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)(?:\s+-?\d+(?:\.\d+)?)?\)")

	for block in footprint_blocks:
		ref_match = ref_pattern.search(block)
		if not ref_match:
			continue

		at_match = at_pattern.search(block)
		if not at_match:
			continue

		ref = ref_match.group(1)
		x = float(at_match.group(1))
		y = float(at_match.group(2))
		switches[ref] = (x, y)

	return switches


def _to_top_right_origin(switches: SwitchPos) -> Dict[str, Tuple[float, float]]:
	"""
	右上原点座標へ変換する。
	- X: 右端を 0 として左方向に増加 (左右のみ反転)
	- Y: PCBの元座標をそのまま使用
	"""
	if not switches:
		return {}

	max_x = max(pos[0] for pos in switches.values())

	converted: Dict[str, Tuple[float, float]] = {}
	for ref, (x, y) in switches.items():
		converted[ref] = (max_x - x, y)

	return converted


def _load_json(path: str) -> dict:
	with open(path, "r", encoding="utf-8") as f:
		return json.load(f)


def _save_json(path: str, data: dict) -> None:
	with open(path, "w", encoding="utf-8") as f:
		json.dump(data, f, ensure_ascii=False, indent=2)
		f.write("\n")


def _save_text(path: str, text: str) -> None:
	with open(path, "w", encoding="utf-8") as f:
		f.write(text)


def _report_path(path: str) -> str:
	repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
	absolute = os.path.abspath(path)
	relative = os.path.relpath(absolute, repo_root)
	if relative == ".." or relative.startswith(f"..{os.sep}"):
		return path
	return relative.replace(os.sep, "/")


def _generate_pcb_switch_report(data: dict, pcb_file: str, matrix_json_path: str) -> str:
	"""PCB上のSW/JOY座標レポートを生成する。"""
	report = []
	report.append("=== PCB上SW/JOY座標レポート (右上原点 / 左右のみ反転) ===")
	report.append("")
	report.append(f"入力PCB: {_report_path(pcb_file)}")
	report.append(f"入力Matrix JSON: {_report_path(matrix_json_path)}")
	report.append("")

	info = data.get("analysis_info", {})
	report.append(f"付与済み座標数(SW): {info.get('pcb_coordinates_added', 0)}")
	report.append(f"未付与座標数(SW): {info.get('pcb_coordinates_missing', 0)}")
	report.append(f"付与済み座標数(JOY): {info.get('pcb_joy_coordinates_added', 0)}")
	report.append(f"原点定義: {info.get('pcb_origin', 'unknown')}")
	report.append("")

	report.append("SW | Matrix[row,col] | PCB座標(x,y)")
	report.append("-" * 52)

	switches = data.get("switches", {})
	entries = []
	for ref, sw in switches.items():
		matrix_pos = sw.get("estimated_matrix_pos", [None, None])
		pcb_pos = sw.get("pcb_position_top_right")
		if pcb_pos is None:
			y_sort = float("inf")
			x_sort = float("inf")
		else:
			x_sort, y_sort = pcb_pos[0], pcb_pos[1]
		entries.append((y_sort, x_sort, _ref_num(ref), ref, matrix_pos, pcb_pos))

	entries.sort(key=lambda x: (x[0], x[1], x[2]))

	for _, _, _, ref, matrix_pos, pcb_pos in entries:
		if pcb_pos is None:
			pcb_str = "(missing)"
		else:
			pcb_str = f"({pcb_pos[0]:8.4f}, {pcb_pos[1]:8.4f})"
		report.append(f"{ref:4} | [{matrix_pos[0]:2},{matrix_pos[1]:2}]         | {pcb_str}")

	if "pcb_missing_switches" in info:
		report.append("")
		report.append("未付与SW:")
		report.append(", ".join(info["pcb_missing_switches"]))

	joysticks = data.get("joysticks", {})
	if joysticks:
		report.append("")
		report.append("JOY  | PCB座標(x,y)")
		report.append("-" * 36)
		joy_entries = []
		for ref, joy in joysticks.items():
			pcb_pos = joy.get("pcb_position_top_right")
			if pcb_pos is None:
				y_sort = float("inf")
				x_sort = float("inf")
			else:
				x_sort, y_sort = pcb_pos[0], pcb_pos[1]
			joy_entries.append((y_sort, x_sort, _ref_num(ref), ref, pcb_pos))
		joy_entries.sort(key=lambda x: (x[0], x[1], x[2]))
		for _, _, _, ref, pcb_pos in joy_entries:
			if pcb_pos is None:
				pcb_str = "(missing)"
			else:
				pcb_str = f"({pcb_pos[0]:8.4f}, {pcb_pos[1]:8.4f})"
			report.append(f"{ref:5} | {pcb_str}")

	encoders = data.get("encoders", {})
	if encoders:
		report.append("")
		report.append("ENC  | PCB座標(x,y)")
		report.append("-" * 36)
		enc_entries = []
		for ref, enc in encoders.items():
			pcb_pos = enc.get("pcb_position_top_right")
			if pcb_pos is None:
				y_sort = float("inf")
				x_sort = float("inf")
			else:
				x_sort, y_sort = pcb_pos[0], pcb_pos[1]
			enc_entries.append((y_sort, x_sort, _ref_num(ref), ref, pcb_pos))
		enc_entries.sort(key=lambda x: (x[0], x[1], x[2]))
		for _, _, _, ref, pcb_pos in enc_entries:
			if pcb_pos is None:
				pcb_str = "(missing)"
			else:
				pcb_str = f"({pcb_pos[0]:8.4f}, {pcb_pos[1]:8.4f})"
			report.append(f"{ref:5} | {pcb_str}")

	return "\n".join(report) + "\n"


def enrich_matrix_json_with_pcb(matrix_json_path: str, pcb_file: str, output_path: str) -> None:
	matrix_data = _load_json(matrix_json_path)
	switches = matrix_data.get("switches", {})

	pcb_all = _extract_switch_positions_from_pcb(pcb_file)
	pcb_top_right = _to_top_right_origin(pcb_all)

	out = copy.deepcopy(matrix_data)

	matched = 0
	missing_in_pcb = []
	for ref, sw in out.get("switches", {}).items():
		# 仮想スイッチ (例: SW91A/SW91B) は末尾の英字を取り除いた基底参照名で
		# PCB フットプリント (例: SW91) を共有する
		base_ref = re.sub(r'([A-Za-z]+\d+)[A-Za-z]+$', r'\1', ref)
		lookup = ref if ref in pcb_top_right else base_ref
		if lookup in pcb_top_right:
			x, y = pcb_top_right[lookup]
			sw["pcb_position_top_right"] = [round(x, 4), round(y, 4)]
			if lookup != ref:
				sw["pcb_reference"] = lookup
			matched += 1
		else:
			missing_in_pcb.append(ref)

	joysticks_out: Dict[str, dict] = {}
	for ref, (x, y) in pcb_top_right.items():
		if not ref.startswith("JOY"):
			continue
		joysticks_out[ref] = {
			"reference": ref,
			"pcb_position_top_right": [round(x, 4), round(y, 4)],
		}
	if joysticks_out:
		out["joysticks"] = dict(sorted(joysticks_out.items(), key=lambda kv: _ref_num(kv[0])))

	# matrix_data に含まれる仮想スイッチ (例: SW91A/SW91B) から
	# 基底参照 (SW91) をエンコーダとして抽出する
	encoders_out: Dict[str, dict] = {}
	for ref, sw in out.get("switches", {}).items():
		if sw.get("source") != "encoder_pulse":
			continue
		base_ref = re.sub(r'([A-Za-z]+\d+)[A-Za-z]+$', r'\1', ref)
		if base_ref == ref or base_ref in encoders_out:
			continue
		if base_ref in pcb_top_right:
			x, y = pcb_top_right[base_ref]
			encoders_out[base_ref] = {
				"reference": base_ref,
				"pcb_position_top_right": [round(x, 4), round(y, 4)],
			}
	if encoders_out:
		out["encoders"] = dict(sorted(encoders_out.items(), key=lambda kv: _ref_num(kv[0])))

	out.setdefault("analysis_info", {})["pcb_coordinates_added"] = matched
	out["analysis_info"]["pcb_coordinates_missing"] = len(missing_in_pcb)
	out["analysis_info"]["pcb_joy_coordinates_added"] = len(joysticks_out)
	out["analysis_info"]["pcb_encoder_coordinates_added"] = len(encoders_out)
	out["analysis_info"]["pcb_origin"] = "top_right_x_flipped_only"

	if missing_in_pcb:
		out["analysis_info"]["pcb_missing_switches"] = sorted(missing_in_pcb, key=_ref_num)

	_save_json(output_path, out)
	report_path = os.path.join(os.path.dirname(output_path), "pcb_analysis_sw_report.txt")
	report_text = _generate_pcb_switch_report(out, pcb_file, matrix_json_path)
	_save_text(report_path, report_text)

	print(f"input matrix json: {matrix_json_path}")
	print(f"input pcb: {pcb_file}")
	print(f"matched switches: {matched}/{len(switches)}")
	print(f"matched joysticks: {len(joysticks_out)}")
	print(f"matched encoders: {len(encoders_out)}")
	print(f"output: {output_path}")
	print(f"report: {report_path}")


def main() -> None:
	import sys

	script_dir = os.path.dirname(__file__)
	repo_root = os.path.normpath(os.path.join(script_dir, "..", ".."))
	default_matrix_json = os.path.join(repo_root, "build", "generated", "keymap_matrix_analysis.json")
	default_pcb = os.path.join(repo_root, "kicad", "cqa02303v5rpi", "cqa02303v5rpi.kicad_pcb")
	default_output = os.path.join(repo_root, "build", "generated", "pcb_analysis.json")

	# 使い方:
	#   python analyze_kicad_pcb.py
	#   python analyze_kicad_pcb.py <pcb_file>
	#   python analyze_kicad_pcb.py <pcb_file> <matrix_json>
	#   python analyze_kicad_pcb.py <pcb_file> <matrix_json> <output_json>
	argc = len(sys.argv)
	if argc == 1:
		pcb_file = default_pcb
		matrix_json = default_matrix_json
		output_json = default_output
	elif argc == 2:
		pcb_file = sys.argv[1]
		matrix_json = default_matrix_json
		output_json = default_output
	elif argc == 3:
		pcb_file = sys.argv[1]
		matrix_json = sys.argv[2]
		output_json = default_output
	elif argc == 4:
		pcb_file = sys.argv[1]
		matrix_json = sys.argv[2]
		output_json = sys.argv[3]
	else:
		print("Usage: python analyze_kicad_pcb.py [pcb_file] [matrix_json] [output_json]")
		sys.exit(1)

	output_dir = os.path.dirname(output_json)
	if output_dir:
		os.makedirs(output_dir, exist_ok=True)

	print_keyboard_layout()
	enrich_matrix_json_with_pcb(matrix_json, pcb_file, output_json)


if __name__ == "__main__":
	main()
