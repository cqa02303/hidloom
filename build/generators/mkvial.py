#!/usr/bin/env python3
"""Generate Vial layout JSON from build/generated/pcb_analysis.json and config/default/keyboard-layout.json.

Dependencies:
  - build/generators/analyze_kicad_matrix.py: KiCad スキーマティック解析（自動実行）
  - build/generators/analyze_kicad_pcb.py: PCB座標抽出（自動実行）

This script automatically executes the above dependencies to ensure up-to-date
analysis files, then converts PCB coordinates to 1u coordinates with 19.05 mm pitch,
matches each populated switch to a key slot from keyboard-layout.json,
and writes config/default/vial.json.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


PITCH_MM = 19.05


@dataclass
class KeySlot:
	row_index: int
	order_index: int
	label: str
	x: float
	y: float
	w: float
	h: float
	# ラベルから明示的に付与されたマトリクス位置 (row, col)
	explicit_matrix: Optional[Tuple[int, int]] = None
	# ラベルから明示的に指定されたスイッチ参照名 (例: SW91A)
	explicit_ref: Optional[str] = None


@dataclass
class SwitchPoint:
	reference: str
	matrix_row: int
	matrix_col: int
	x_u: float
	y_u: float
	output_label: Optional[str] = None


@dataclass
class VialLayoutOverrides:
	exclude_sources: set[str]
	slot_overrides: dict[str, str]
	virtual_slots: dict[str, str]


def _project_root() -> str:
	return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _run_dependency(script_name: str) -> None:
	"""依存スクリプトを実行して必要な定義ファイルを生成する"""
	script_path = os.path.join(_project_root(), "build", "generators", script_name)
	if not os.path.exists(script_path):
		raise FileNotFoundError(f"generator dependency not found: {script_path}")

	print(f"実行中: {script_name}...")
	subprocess.run(
		[sys.executable, script_path],
		cwd=_project_root(),
		capture_output=False,
		check=True,
	)


def _load_json(path: str) -> Any:
	with open(path, "r", encoding="utf-8") as f:
		return json.load(f)


def _load_overrides(path: str) -> VialLayoutOverrides:
	if not os.path.exists(path):
		return VialLayoutOverrides(exclude_sources=set(), slot_overrides={}, virtual_slots={})
	data = _load_json(path)
	return VialLayoutOverrides(
		exclude_sources=set(data.get("exclude_sources", [])),
		slot_overrides=dict(data.get("slot_overrides", {})),
		virtual_slots=dict(data.get("virtual_slots", {})),
	)


_MATRIX_LABEL_RE = re.compile(r'^\s*(\d+)\s*,\s*(\d+)\s*$')
_REF_LABEL_RE = re.compile(r'^\s*(\d+[A-Za-z]+)\s*$')


def _classify_label(label: str) -> Tuple[Optional[Tuple[int, int]], Optional[str]]:
	"""ラベルの先頭トークンを見て、明示的なマトリクス指定/スイッチ参照名を返す。

	- ``"0,0"`` のような `数字,数字` → (row, col) のタプルを返す。
	- ``"91A"`` のように数字+英字 → 参照名 (例: ``SW91A``) を返す。
	  (ここでは SW プレフィックスを補う)
	"""
	head = label.split("\n", 1)[0]
	m = _MATRIX_LABEL_RE.match(head)
	if m:
		return (int(m.group(1)), int(m.group(2))), None
	m = _REF_LABEL_RE.match(head)
	if m:
		token = m.group(1)
		ref = token if token.upper().startswith(("SW", "JOY")) else f"SW{token}"
		return None, ref
	return None, None


def _parse_kle_slots(layout_data: List[List[Any]]) -> List[KeySlot]:
	slots: List[KeySlot] = []
	y = 0.0

	for row_idx, row in enumerate(layout_data):
		x = 0.0
		w = 1.0
		h = 1.0
		key_order = 0

		for item in row:
			if isinstance(item, dict):
				y += float(item.get("y", 0.0))
				x += float(item.get("x", 0.0))
				if "w" in item:
					w = float(item["w"])
				if "h" in item:
					h = float(item["h"])
				continue

			label = str(item)
			explicit_matrix, explicit_ref = _classify_label(label)
			# ジョイスティック表記の要素はスイッチ1個に対応しないため除外するが、
			# ラベルに明示的なマトリクス座標/参照名がある場合は採用する。
			is_stick = "stick" in label.lower()
			if (not is_stick) or explicit_matrix is not None or explicit_ref is not None:
				slots.append(
					KeySlot(
						row_index=row_idx,
						order_index=key_order,
						label=label,
						x=x,
						y=y,
						w=w,
						h=h,
						explicit_matrix=explicit_matrix,
						explicit_ref=explicit_ref,
					)
				)
				key_order += 1

			x += w
			w = 1.0
			h = 1.0

		y += 1.0

	return slots


def _slot_key(slot: KeySlot) -> str:
	return f"row:{slot.row_index},order:{slot.order_index}"


def _parse_matrix_label(value: str) -> Tuple[int, int]:
	m = _MATRIX_LABEL_RE.match(value)
	if not m:
		raise ValueError(f"invalid matrix override: {value!r}")
	return int(m.group(1)), int(m.group(2))


def _parse_switch_points(
	pcb_analysis: Dict[str, Any],
	exclude_sources: Optional[set[str]] = None,
) -> List[SwitchPoint]:
	exclude_sources = exclude_sources or set()
	switches = pcb_analysis.get("switches", {})
	if not switches:
		return []

	min_y = min(sw["pcb_position_top_right"][1] for sw in switches.values())
	points: List[SwitchPoint] = []

	for sw in switches.values():
		if sw.get("source") in exclude_sources:
			continue
		row, col = sw["estimated_matrix_pos"]
		x_mm, y_mm = sw["pcb_position_top_right"]
		points.append(
			SwitchPoint(
				reference=sw["reference"],
				matrix_row=int(row),
				matrix_col=int(col),
				x_u=float(x_mm) / PITCH_MM,
				y_u=(float(y_mm) - float(min_y)) / PITCH_MM,
			)
		)

	# KLEの並びに合わせやすいよう、上から左へ順に並べる
	points.sort(key=lambda p: (p.y_u, p.x_u, p.reference))
	return points


def _distance(slot: KeySlot, sw: SwitchPoint) -> float:
	return math.hypot(slot.x - sw.x_u, slot.y - sw.y_u)


def _assign_switches_to_slots(
	slots: List[KeySlot],
	points: List[SwitchPoint],
	overrides: Optional[VialLayoutOverrides] = None,
) -> Dict[int, SwitchPoint]:
	overrides = overrides or VialLayoutOverrides(exclude_sources=set(), slot_overrides={}, virtual_slots={})
	unassigned_slots = set(range(len(slots)))
	unassigned_points = list(points)
	assignment: Dict[int, SwitchPoint] = {}

	# 1) override file で virtual slot / matrix slot を明示しているスロット。
	for slot_idx in list(unassigned_slots):
		slot = slots[slot_idx]
		key = _slot_key(slot)
		if key in overrides.virtual_slots:
			row, col = _parse_matrix_label(overrides.virtual_slots[key].split("\n", 1)[0])
			assignment[slot_idx] = SwitchPoint(
				reference=f"virtual:{key}",
				matrix_row=row,
				matrix_col=col,
				x_u=slot.x,
				y_u=slot.y,
				output_label=overrides.virtual_slots[key],
			)
			unassigned_slots.remove(slot_idx)
			continue
		if key in overrides.slot_overrides:
			row, col = _parse_matrix_label(overrides.slot_overrides[key])
			assignment[slot_idx] = SwitchPoint(
				reference=f"override:{key}",
				matrix_row=row,
				matrix_col=col,
				x_u=slot.x,
				y_u=slot.y,
			)
			unassigned_slots.remove(slot_idx)

	# 2) ラベルが「数字,数字」でマトリクス位置を明示しているスロットは
	#    そのままその座標を採用する (実 SwitchPoint が無くても合成して割り当てる)
	points_by_matrix: Dict[Tuple[int, int], SwitchPoint] = {
		(p.matrix_row, p.matrix_col): p for p in unassigned_points
	}
	for slot_idx in list(unassigned_slots):
		slot = slots[slot_idx]
		if slot.explicit_matrix is None:
			continue
		row, col = slot.explicit_matrix
		sw = points_by_matrix.get((row, col))
		if sw is not None and sw in unassigned_points:
			assignment[slot_idx] = sw
			unassigned_points.remove(sw)
		else:
			# 対応する SwitchPoint が無い場合はラベルをそのまま採用するための合成エントリを作る
			assignment[slot_idx] = SwitchPoint(
				reference=f"slot:{row},{col}",
				matrix_row=row,
				matrix_col=col,
				x_u=slot.x,
				y_u=slot.y,
				output_label=f"{row},{col}",
			)
		unassigned_slots.remove(slot_idx)

	# 3) ラベルがスイッチ参照名 (例: SW91A) を明示しているスロット
	points_by_ref: Dict[str, SwitchPoint] = {p.reference: p for p in unassigned_points}
	for slot_idx in list(unassigned_slots):
		slot = slots[slot_idx]
		if slot.explicit_ref is None:
			continue
		sw = points_by_ref.get(slot.explicit_ref)
		if sw is None or sw not in unassigned_points:
			continue
		assignment[slot_idx] = sw
		unassigned_slots.remove(slot_idx)
		unassigned_points.remove(sw)

	# 4) 残りは KLE のスロット順と PCB の上から左への順を対応させる。
	remaining_slots = sorted(unassigned_slots)
	skipped: List[SwitchPoint] = unassigned_points[len(remaining_slots):]
	for slot_idx, sw in zip(remaining_slots, unassigned_points):
		assignment[slot_idx] = sw
		unassigned_slots.remove(slot_idx)

	if skipped:
		print(
			"警告: 以下のスイッチに割り当てるキースロットが不足しているためスキップしました: "
			+ ", ".join(sw.reference for sw in skipped),
			file=sys.stderr,
		)

	return assignment


def _assignment_report(
	slots: List[KeySlot],
	points: List[SwitchPoint],
	assignment: Dict[int, SwitchPoint],
	overrides: VialLayoutOverrides,
) -> str:
	assigned_point_refs = {
		sw.reference
		for sw in assignment.values()
		if not sw.reference.startswith(("virtual:", "override:", "slot:"))
	}
	unassigned_points = [p.reference for p in points if p.reference not in assigned_point_refs]
	unassigned_slots = [idx for idx in range(len(slots)) if idx not in assignment]

	lines = [
		"# Vial generation report",
		"",
		f"slots: {len(slots)}",
		f"switch_points: {len(points)}",
		f"assigned_slots: {len(assignment)}",
		f"virtual_slots: {len(overrides.virtual_slots)}",
		f"slot_overrides: {len(overrides.slot_overrides)}",
		f"exclude_sources: {', '.join(sorted(overrides.exclude_sources)) or '(none)'}",
		"",
		"## Virtual Slots",
	]
	for key, label in sorted(overrides.virtual_slots.items()):
		lines.append(f"- {key}: {label.splitlines()[0]}")
	lines.append("")
	lines.append("## Slot Overrides")
	if overrides.slot_overrides:
		for key, matrix in sorted(overrides.slot_overrides.items()):
			lines.append(f"- {key}: {matrix}")
	else:
		lines.append("- (none)")
	lines.append("")
	lines.append("## Unassigned Slots")
	if unassigned_slots:
		for idx in unassigned_slots:
			slot = slots[idx]
			lines.append(f"- {idx} {_slot_key(slot)} label={slot.label!r}")
	else:
		lines.append("- (none)")
	lines.append("")
	lines.append("## Unassigned Switch Points")
	if unassigned_points:
		for ref in unassigned_points:
			lines.append(f"- {ref}")
	else:
		lines.append("- (none)")
	return "\n".join(lines) + "\n"


def _build_vial_keymap(slots: List[KeySlot], assignment: Dict[int, SwitchPoint]) -> List[List[Any]]:
	rows: Dict[int, List[Tuple[KeySlot, SwitchPoint]]] = {}
	for slot_index, sw in assignment.items():
		slot = slots[slot_index]
		rows.setdefault(slot.row_index, []).append((slot, sw))

	keymap: List[List[Any]] = []
	prev_row_y = 0.0
	for row_index in sorted(rows.keys()):
		row_items = sorted(rows[row_index], key=lambda pair: pair[0].x)
		row: List[Any] = []
		cursor_x = 0.0
		row_base_y = row_items[0][0].y
		is_first_in_row = True

		for slot, sw in row_items:
			pos: Dict[str, float] = {}

			if is_first_in_row:
				if abs(slot.x) > 1e-9:
					pos["x"] = round(slot.x, 4)
				y_offset = row_base_y - prev_row_y
				# KLE/Vialは行が変わるごとに暗黙で+1されるため、明示yは追加分のみ
				explicit_y = y_offset if not keymap else (y_offset - 1.0)
				if abs(explicit_y) > 1e-9:
					pos["y"] = round(explicit_y, 4)
				is_first_in_row = False
			else:
				x_offset = slot.x - cursor_x
				if abs(x_offset) > 1e-9:
					pos["x"] = round(x_offset, 4)

			if abs(slot.w - 1.0) > 1e-9:
				pos["w"] = round(slot.w, 4)
			if abs(slot.h - 1.0) > 1e-9:
				pos["h"] = round(slot.h, 4)

			if pos:
				row.append(pos)
			row.append(sw.output_label or f"{sw.matrix_row},{sw.matrix_col}")

			cursor_x = slot.x + slot.w

		keymap.append(row)
		prev_row_y = row_base_y

	return keymap


def _build_vial_json(
	keymap: List[List[Any]],
	points: List[SwitchPoint],
	template: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
	max_row = max(p.matrix_row for p in points)
	max_col = max(p.matrix_col for p in points)

	out = copy.deepcopy(template) if template else {}
	out.setdefault("name", "CQA02303v5 Keyboard")
	out.setdefault("version", 1)
	out.setdefault("uid", 4850729948911185980)
	out.setdefault("lighting", "vialrgb")
	out["matrix"] = {
		"rows": max_row + 1,
		"cols": max_col + 1,
	}
	out["layouts"] = {
		"keymap": keymap,
	}
	return out


def main() -> None:
	root = _project_root()

	# 前提ファイルを最新化するために依存スクリプトを実行
	print("=== 前提ファイルの更新 ===")
	_run_dependency("analyze_kicad_matrix.py")
	_run_dependency("analyze_kicad_pcb.py")
	print()

	pcb_path = os.path.join(root, "build", "generated", "pcb_analysis.json")
	kle_path = os.path.join(root, "config", "default", "keyboard-layout.json")
	override_path = os.path.join(root, "config", "default", "vial-layout-overrides.json")
	out_path = os.path.join(root, "config", "default", "vial.json")
	report_path = os.path.join(root, "build", "generated", "vial_generation_report.txt")

	if not os.path.exists(pcb_path):
		raise FileNotFoundError(f"入力ファイルが見つかりません: {pcb_path}")
	if not os.path.exists(kle_path):
		raise FileNotFoundError(f"入力ファイルが見つかりません: {kle_path}")

	pcb_analysis = _load_json(pcb_path)
	keyboard_layout = _load_json(kle_path)
	template = _load_json(out_path) if os.path.exists(out_path) else None
	overrides = _load_overrides(override_path)

	slots = _parse_kle_slots(keyboard_layout)
	points = _parse_switch_points(pcb_analysis, overrides.exclude_sources)

	if not points:
		raise ValueError("pcb_analysis.json にスイッチ情報がありません。")

	assignment = _assign_switches_to_slots(slots, points, overrides)
	keymap = _build_vial_keymap(slots, assignment)
	vial_json = _build_vial_json(keymap, points, template)

	os.makedirs(os.path.dirname(out_path), exist_ok=True)
	with open(out_path, "w", encoding="utf-8") as f:
		json.dump(vial_json, f, ensure_ascii=False, indent=2)
		f.write("\n")

	with open(report_path, "w", encoding="utf-8") as f:
		f.write(_assignment_report(slots, points, assignment, overrides))

	print(f"Generated: {out_path}")
	print(f"Report: {report_path}")
	print(f"Assigned switches: {len(assignment)}")
	print(f"Matrix size: {vial_json['matrix']['rows']}x{vial_json['matrix']['cols']}")


if __name__ == "__main__":
	main()
