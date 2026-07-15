#!/usr/bin/env python3
"""
KiCad PCB ファイルを解析し、LED フットプリントの座標を抽出して
config/default/ledd.json の leds フィールドを更新する。

出力形式:
  "leds": {
    "5,9": {"x": 123.45, "y": 67.89},
    "5,8": { ... },
    ...
  }

現在の ledd.json は LED 参照名ではなく matrix 座標を key にする。
このスクリプトは既存 ledd.json の key 順を LED strip 順として使い、PCB で検出した
LED1..LEDn の座標を先頭から対応付ける。PCB にない補助 LED entry は既存値を保持する。

Usage:
  python build/generators/analyze_kicad_pcb_led.py [PCB_FILE] [LEDD_JSON]
  デフォルト:
    PCB_FILE  : kicad/cqa02303v5rpi/cqa02303v5rpi.kicad_pcb
    LEDD_JSON : config/default/ledd.json
"""

import json
import os
import re
import sys
import math
from typing import Dict, Tuple


# ---------------------------------------------------------------------------
# PCB 解析
# ---------------------------------------------------------------------------

def _extract_led_positions(pcb_file: str) -> Dict[str, Tuple[float, float]]:
    """PCB ファイルから LED 参照名とフットプリント座標を抽出する。"""
    with open(pcb_file, "r", encoding="utf-8") as f:
        content = f.read()

    # フットプリントブロックを抽出（括弧の深さを追跡）
    leds: Dict[str, Tuple[float, float]] = {}
    i = 0
    n = len(content)

    while i < n:
        # "(footprint" の開始を探す
        idx = content.find("(footprint", i)
        if idx == -1:
            break

        # ブロック全体を括弧の深さで取得
        depth = 0
        start = idx
        end = idx
        for j in range(idx, n):
            if content[j] == "(":
                depth += 1
            elif content[j] == ")":
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break

        block = content[start:end]
        i = end

        # LED 参照のみ対象
        ref_match = re.search(r'\(property\s+"Reference"\s+"(LED\d+)"', block)
        if not ref_match:
            continue

        ref = ref_match.group(1)

        # フットプリント直下の (at x y [angle]) を取得
        # "(footprint ..." 行直後の最初の (at ...) がフットプリント位置
        at_match = re.search(
            r'\(at\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)(?:\s+-?\d+(?:\.\d+)?)?\)',
            block
        )
        if not at_match:
            continue

        x = float(at_match.group(1))
        y = float(at_match.group(2))
        leds[ref] = (x, y)

    return leds


def _sort_by_led_number(leds: Dict[str, Tuple[float, float]]) -> list[tuple[str, dict]]:
    """LED 番号順にソートし、{"x": ..., "y": ...} 形式に変換する。
    X 座標は PCB の左右を反転して右上原点に揃える (max_x - x)。"""
    def led_num(key: str) -> int:
        m = re.search(r"(\d+)", key)
        return int(m.group(1)) if m else 0

    max_x = max(x for x, _ in leds.values())

    sorted_refs = sorted(leds.keys(), key=led_num)
    result: list[tuple[str, dict]] = []
    for ref in sorted_refs:
        x, y = leds[ref]
        result.append((ref, {"x": round(max_x - x, 4), "y": round(y, 4)}))
    return result


def _merge_led_positions_with_existing_keys(
    existing_leds: Dict[str, dict],
    detected_leds: list[tuple[str, dict]],
) -> Dict[str, dict]:
    """既存の matrix 座標 key を保ったまま、検出 LED 座標を strip 順に流し込む。"""
    if not existing_leds:
        return {ref: pos for ref, pos in detected_leds}

    if detected_leds:
        first_existing = next(iter(existing_leds.values()))
        first_detected = detected_leds[0][1]
        last_detected = detected_leds[-1][1]

        def dist(pos: dict) -> float:
            return math.hypot(
                float(first_existing.get("x", 0.0)) - float(pos["x"]),
                float(first_existing.get("y", 0.0)) - float(pos["y"]),
            )

        if dist(last_detected) < dist(first_detected):
            detected_leds = list(reversed(detected_leds))

    merged: Dict[str, dict] = {}
    existing_items = list(existing_leds.items())
    for idx, (key, current_pos) in enumerate(existing_items):
        if idx < len(detected_leds):
            merged[key] = detected_leds[idx][1]
        else:
            merged[key] = current_pos
    return merged


# ---------------------------------------------------------------------------
# ledd.json 更新
# ---------------------------------------------------------------------------

def _update_ledd_json(ledd_json_path: str, leds_data: Dict[str, dict]) -> None:
    """ledd.json の leds フィールドを更新して上書き保存する。"""
    with open(ledd_json_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    config["leds"] = leds_data

    with open(ledd_json_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main() -> None:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(os.path.dirname(script_dir))

    pcb_file = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        repo_root, "kicad", "cqa02303v5rpi", "cqa02303v5rpi.kicad_pcb"
    )
    ledd_json = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        repo_root, "config", "default", "ledd.json"
    )

    if not os.path.exists(pcb_file):
        print(f"ERROR: PCB ファイルが見つかりません: {pcb_file}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(ledd_json):
        print(f"ERROR: ledd.json が見つかりません: {ledd_json}", file=sys.stderr)
        sys.exit(1)

    print(f"PCB ファイル : {pcb_file}")
    print(f"ledd.json   : {ledd_json}")
    print()

    # 座標抽出
    raw_leds = _extract_led_positions(pcb_file)
    if not raw_leds:
        print("ERROR: LED フットプリントが見つかりませんでした。", file=sys.stderr)
        sys.exit(1)

    detected_leds = _sort_by_led_number(raw_leds)
    with open(ledd_json, "r", encoding="utf-8") as f:
        existing_config = json.load(f)
    leds_data = _merge_led_positions_with_existing_keys(
        existing_config.get("leds", {}),
        detected_leds,
    )

    # 結果表示
    print(f"検出 LED 数: {len(detected_leds)}")
    print(f"ledd entry 数: {len(leds_data)}")
    print()
    print(f"{'参照名':<8}  {'x (mm)':>10}  {'y (mm)':>10}")
    print("-" * 34)
    for idx, (ref, pos) in enumerate(leds_data.items()):
        source = detected_leds[idx][0] if idx < len(detected_leds) else "preserve"
        print(f"{ref:<8}  {pos['x']:>10.4f}  {pos['y']:>10.4f}  {source}")
    print()

    # ledd.json 更新
    _update_ledd_json(ledd_json, leds_data)
    print(f"ledd.json を更新しました: {ledd_json}")


if __name__ == "__main__":
    main()
