#!/usr/bin/env python3
"""Smoke-test analog stick calibration map helpers in Settings UI."""
from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSET = ROOT / "daemon" / "http" / "static" / "settings_panel.js"


def main() -> None:
    node = shutil.which("node")
    if node is None:
        print("skip: Node is unavailable; analog stick map helpers not run")
        return

    runner = textwrap.dedent(
        f"""
        const fs = require("fs");
        const vm = require("vm");
        const source = fs.readFileSync({str(ASSET)!r}, "utf8");
        const context = {{
          console,
          document: {{ getElementById: () => null }},
          Number,
          Math,
          Set,
          Array,
          Boolean,
          String,
        }};
        vm.createContext(context);
        vm.runInContext(source, context);
        const sample = {{
          valid: true,
          deadzone: 20,
          x: {{ low: 0.1, center: 1.5, high: 2.9, invert: false }},
          y: {{ low: 0.2, center: 1.6, high: 3.0, invert: true }},
        }};
        const model = context.analogStickMapModel(sample);
        if (!model) throw new Error("map model is null");
        const near = (a, b) => Math.abs(a - b) < 0.000001;
        if (!near(model.center.x, 50) || !near(model.center.y, 50)) throw new Error(`unexpected center ${{JSON.stringify(model.center)}}`);
        if (model.point.normalized_x !== 0 || model.point.normalized_y !== 0) throw new Error("center point should normalize to zero");
        if (model.deadzone_radius !== 10) throw new Error("deadzone radius should be half of normalized deadzone");
        const merged = context.mergeAnalogStickCalibration(sample, {{ current: {{ x: 2.9, y: 0.2 }} }});
        const moved = context.analogStickMapModel(merged);
        if (moved.point.normalized_x !== 100 || moved.point.normalized_y !== 100) {{
          throw new Error(`unexpected moved point ${{JSON.stringify(moved.point)}}`);
        }}
        if (context.analogStickMapModel({{ x: {{ low: 1, center: 1, high: 1 }}, y: sample.y }}) !== null) {{
          throw new Error("invalid axis should not render a map model");
        }}
        """
    )
    subprocess.run([node, "-e", runner], check=True)
    print("ok: HTTP Settings analog stick map model")


if __name__ == "__main__":
    main()
