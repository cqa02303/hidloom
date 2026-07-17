#!/usr/bin/env python3
"""Exercise OLED pointer release and drag guards in the real browser script."""
from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "daemon/http/static/oled_panel.js"

NODE_TEST = r"""
const fs = require("fs");
const vm = require("vm");

class Element {
  closest(selector) {
    return selector === ".oled-pixel" ? this : null;
  }
}

const context = {
  console,
  Element,
  document: {
    hidden: false,
    addEventListener() {},
    getElementById() { return null; },
  },
  window: { addEventListener() {} },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);
vm.runInContext(`
  let testPaintCount = 0;
  paintOledCell = () => { testPaintCount += 1; };
  _oledEditorState.painting = true;
  _oledEditorState.fillMode = false;
  _oledEditorState.paintValue = "1";
`, context);

const target = new Element();
context.handleOledPointerOver({ buttons: 0, target });
if (vm.runInContext("testPaintCount", context) !== 0) throw new Error("hover painted after release");
if (vm.runInContext("_oledEditorState.painting", context) !== false) throw new Error("stale painting state remained");

vm.runInContext('_oledEditorState.painting = true; _oledEditorState.paintValue = "1";', context);
context.handleOledPointerOver({ buttons: 1, target });
if (vm.runInContext("testPaintCount", context) !== 1) throw new Error("left drag did not paint once");

vm.runInContext('_oledEditorState.painting = true; _oledEditorState.paintValue = "0";', context);
context.handleOledPointerOver({ buttons: 2, target });
if (vm.runInContext("testPaintCount", context) !== 2) throw new Error("right drag did not erase once");

vm.runInContext('_oledEditorState.painting = true; _oledEditorState.paintValue = "0";', context);
context.handleOledPointerOver({ buttons: 1, target });
if (vm.runInContext("testPaintCount", context) !== 2) throw new Error("wrong button continued painting");
if (vm.runInContext("_oledEditorState.painting", context) !== false) throw new Error("wrong button did not stop painting");
"""


def main() -> None:
    subprocess.run(
        ["node", "--check", str(PANEL)],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        ["node", "-e", NODE_TEST, str(PANEL)],
        cwd=ROOT,
        check=True,
    )
    print("ok: OLED pointer release and drag guards")


if __name__ == "__main__":
    main()
