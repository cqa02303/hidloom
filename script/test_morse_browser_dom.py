#!/usr/bin/env python3
"""Run Morse browser builder logic in a lightweight Node DOM shim."""
from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSET = ROOT / "daemon" / "http" / "static" / "morse_inspector_panel.js"


def main() -> None:
    node = shutil.which("node")
    if node is None:
        print("skip: Node is unavailable; Morse browser DOM builder logic not run")
        return
    try:
        subprocess.run([node, "--version"], check=True, text=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"skip: Node is unavailable; Morse browser DOM builder logic not run: {exc}")
        return

    runner = textwrap.dedent(
        f"""
        const fs = require("fs");
        const vm = require("vm");

        class Element {{
          constructor(tag) {{
            this.tagName = tag.toUpperCase();
            this.id = "";
            this.className = "";
            this.value = "";
            this.textContent = "";
            this._innerHTML = "";
            this.children = [];
            this.parentElement = null;
            this.style = {{}};
            this.listeners = {{}};
            this.classList = {{
              add: (...names) => {{
                const set = new Set(String(this.className || "").split(/\\s+/).filter(Boolean));
                names.forEach((name) => set.add(name));
                this.className = Array.from(set).join(" ");
              }},
              remove: (...names) => {{
                const remove = new Set(names);
                this.className = String(this.className || "").split(/\\s+/).filter((name) => !remove.has(name)).join(" ");
              }},
              toggle: (name, force) => {{
                const set = new Set(String(this.className || "").split(/\\s+/).filter(Boolean));
                const enabled = force === undefined ? !set.has(name) : Boolean(force);
                if (enabled) set.add(name);
                else set.delete(name);
                this.className = Array.from(set).join(" ");
                return enabled;
              }},
            }};
            Object.defineProperty(this, "innerHTML", {{
              get: () => this._innerHTML,
              set: (html) => {{
                this._innerHTML = String(html || "");
                const tagRe = /<([a-z0-9-]+)\\b([^>]*)>/gi;
                let match;
                while ((match = tagRe.exec(this._innerHTML))) {{
                  const child = new Element(match[1]);
                  const attrs = match[2] || "";
                  const id = attrs.match(/\\bid=["']([^"']+)["']/);
                  const cls = attrs.match(/\\bclass=["']([^"']+)["']/);
                  const value = attrs.match(/\\bvalue=["']([^"']*)["']/);
                  if (id) child.id = id[1];
                  if (cls) child.className = cls[1];
                  if (value) child.value = value[1];
                  register(child);
                  this.appendChild(child);
                }}
              }},
            }});
          }}
          appendChild(child) {{
            child.parentElement = this;
            this.children.push(child);
            return child;
          }}
          append(...items) {{ items.forEach((item) => this.appendChild(item)); }}
          before(...items) {{
            if (!this.parentElement) return;
            const siblings = this.parentElement.children;
            const index = siblings.indexOf(this);
            items.forEach((item, offset) => {{
              item.parentElement = this.parentElement;
              siblings.splice(index + offset, 0, item);
            }});
          }}
          after(...items) {{
            if (!this.parentElement) return;
            const siblings = this.parentElement.children;
            const index = siblings.indexOf(this);
            items.forEach((item, offset) => {{
              item.parentElement = this.parentElement;
              siblings.splice(index + 1 + offset, 0, item);
            }});
          }}
          replaceChildren(...items) {{
            this.children = [];
            this.textContent = "";
            this.append(...items);
          }}
          addEventListener(name, fn) {{ this.listeners[name] = fn; }}
          setAttribute(name, value) {{
            this[name] = String(value);
          }}
          dispatchEvent(_event) {{}}
          focus() {{}}
        }}

        const elementsById = new Map();
        const roots = [];
        function register(el) {{
          if (el.id) elementsById.set(el.id, el);
          return el;
        }}
        function classes(el) {{
          return new Set(String(el.className || "").split(/\\s+/).filter(Boolean));
        }}
        function matches(el, selector) {{
          if (!selector.startsWith(".")) return false;
          const want = selector.slice(1).split(".");
          const have = classes(el);
          return want.every((name) => have.has(name));
        }}
        function walk(el, out) {{
          out.push(el);
          for (const child of el.children) walk(child, out);
        }}
        function allElements() {{
          const out = [];
          for (const root of roots) walk(root, out);
          return out;
        }}

        global.window = global;
        global.Event = class Event {{ constructor(type, _opts) {{ this.type = type; }} }};
        global.fetch = async () => ({{ ok: true, json: async () => ({{ result: "ok", events: [] }}) }});
        global.setInterval = () => 1;
        global.document = {{
          readyState: "complete",
          createElement: (tag) => register(new Element(tag)),
          createDocumentFragment: () => new Element("fragment"),
          getElementById: (id) => elementsById.get(id) || null,
          querySelector: (selector) => allElements().find((el) => matches(el, selector)) || null,
          querySelectorAll: (selector) => allElements().filter((el) => matches(el, selector)),
          addEventListener: () => {{}},
        }};

        function make(id, tag = "input", className = "") {{
          const el = document.createElement(tag);
          el.id = id;
          el.className = className;
          register(el);
          roots.push(el);
          return el;
        }}
        const wrap = make("interaction-editor-wrap", "div", "interaction-editor-wrap");
        const editor = document.createElement("textarea");
        editor.id = "interaction-editor";
        editor.value = JSON.stringify({{
          morse_behaviors: {{
            main: {{
              dot_threshold: 0.2,
              sequence_timeout: 0.8,
              max_depth: 3,
              force_commit: [".-"],
              map: {{ ".": "KC_E", "-": "KC_T", ".-": "KC_A" }},
            }},
            aux: {{
              map: {{ ".": "KC_1", "-": "KC_2" }},
            }},
          }},
        }});
        register(editor);
        wrap.appendChild(editor);
        const timing = document.createElement("div");
        timing.className = "interaction-builder interaction-timing-builder";
        wrap.appendChild(timing);
        const help = make("interaction-help-root", "div", "interaction-help");
        make("interaction-status", "div");
        let copiedAction = "";

        global.updateInteractionEditor = (settings) => {{
          editor.value = JSON.stringify(settings, null, 2);
        }};
        global.__morseCopyTextForTest = (text) => {{ copiedAction = text; }};

        vm.runInThisContext(fs.readFileSync({json.dumps(str(ASSET))}, "utf8"), {{ filename: "morse_inspector_panel.js" }});

        if (!document.getElementById("interaction-morse-name")) {{
          throw new Error("Morse builder was not initialized after late script load");
        }}
        const initialName = document.getElementById("interaction-morse-name").value;
        const initialMap = document.getElementById("interaction-morse-map").value;
        const initialExisting = document.getElementById("interaction-morse-existing").value;
        document.getElementById("interaction-morse-name").value = "stale_hidden_name";
        document.getElementById("interaction-morse-dot").value = "0.180";
        document.getElementById("interaction-morse-timeout").value = "0.330";
        document.getElementById("interaction-morse-fallback").value = "KC_ESC";
        document.getElementById("interaction-morse-force").value = ".-";
        document.getElementById("interaction-morse-map").value = ".=KC_E\\n-=KC_T\\n.-=KC_A";
        window.renderMorseTreeEditorFromBuilder();
        document.getElementById("interaction-morse-map").value = "-=KC_T";
        window.renderMorseTreeEditorFromBuilder();
        const visibleRootMissingDot = (() => document.getElementById("interaction-morse-tree-editor").children
          .filter((row) => classes(row).has("interaction-morse-tree-row") && !classes(row).has("interaction-morse-tree-head"))
          .map((row) => row.children[0] && row.children[0].children[1] && row.children[0].children[1].textContent)
          .filter(Boolean)
          .join("|"))();
        document.getElementById("interaction-morse-map").value = ".=KC_E\\n-=KC_T\\n.-=KC_A";
        window.renderMorseTreeEditorFromBuilder();
        window.expandMorseTreeSequence(".");
        window.expandMorseTreeSequence(".-");
        window.updateMorseTreeAction("..", "KC_I");
        window.updateMorseTreeForce("..", true);
        const visibleTreeSequences = () => document.getElementById("interaction-morse-tree-editor").children
          .filter((row) => classes(row).has("interaction-morse-tree-row") && !classes(row).has("interaction-morse-tree-head"))
          .map((row) => row.children[0] && row.children[0].children[1] && row.children[0].children[1].textContent)
          .filter(Boolean)
          .join("|");
        const branchToggleFor = (sequence) => {{
          const rows = document.getElementById("interaction-morse-tree-editor").children;
          for (const row of rows) {{
            if (!classes(row).has("interaction-morse-tree-row") || classes(row).has("interaction-morse-tree-head")) continue;
            const code = row.children[0] && row.children[0].children[1];
            if (code && code.textContent === sequence) return row.children[0].children[0].textContent;
          }}
          return "";
        }};
        const actionInputFor = (sequence) => {{
          const rows = document.getElementById("interaction-morse-tree-editor").children;
          for (const row of rows) {{
            if (!classes(row).has("interaction-morse-tree-row") || classes(row).has("interaction-morse-tree-head")) continue;
            const code = row.children[0] && row.children[0].children[1];
            if (code && code.textContent === sequence) return row.children[1] && row.children[1].children[0];
          }}
          return null;
        }};
        const visibleSequencesForced = visibleTreeSequences();
        window.updateMorseTreeForce(".-", false);
        const dotDashToggleAfterForceOff = branchToggleFor(".-");
        const visibleSequencesForceOff = visibleTreeSequences();
        window.updateMorseTreeForce(".-", true);
        window.applyMorseBehaviorBuilder();
        window.copyMorseActionForBuilder();
        window.loadMorseBehaviorByName("aux", {{ setStatus: true }});
        window.deleteMorseBehaviorBuilder();
        global.prompt = () => "popup_new";
        const selector = document.getElementById("interaction-morse-existing");
        selector.value = "__add_morse__";
        selector.listeners.change();
        selector.value = "popup_new";
        actionInputFor(".").value = "KC_Z";
        window.syncMorseTreeInputsToMap();
        const hiddenMapAfterTypedInput = document.getElementById("interaction-morse-map").value;

        const settings = JSON.parse(editor.value);
        const def = settings.morse_behaviors && settings.morse_behaviors.main;
        const promptDef = settings.morse_behaviors && settings.morse_behaviors.popup_new;
        const count = (selector) => document.querySelectorAll(selector).length;
        const result = {{
          hasDefinition: !!def,
          mapDot: def && def.map["."],
          mapDash: def && def.map["-"],
          mapA: def && def.map[".-"],
          mapI: def && def.map[".."],
          mapDotDashDot: def && def.map[".-."],
          mapDotDashDash: def && def.map[".--"],
          maxDepth: def && def.max_depth,
          force: def && def.force_commit && def.force_commit.join(","),
          fallback: def && def.fallback_action,
          copiedAction,
          initialName,
          initialExisting,
          initialMapHasMain: initialMap.includes(".=KC_E") && initialMap.includes(".-=KC_A"),
          deletedGone: !(settings.morse_behaviors && settings.morse_behaviors.aux),
          addedByPrompt: !!promptDef,
          selectedAfterPrompt: document.getElementById("interaction-morse-existing").value,
          promptMapDot: promptDef && promptDef.map["."],
          promptMapDash: promptDef && promptDef.map["-"],
          hiddenMapAfterTypedInput,
          promptFallback: promptDef && promptDef.fallback_action,
          promptForce: promptDef && promptDef.force_commit,
          hasTreeEditor: !!document.getElementById("interaction-morse-tree-editor"),
          visibleSequencesForced,
          visibleSequencesForceOff,
          visibleRootMissingDot,
          dotDashToggleAfterForceOff,
          accordionCount: count(".interaction-morse-accordion"),
          rowCount: count(".interaction-morse-row"),
          editableRows: count(".interaction-morse-tree-row"),
          prefixRows: count(".interaction-morse-row.morse-prefix"),
          leafRows: count(".interaction-morse-row.morse-leaf"),
          forceRows: count(".interaction-morse-row.morse-force_commit"),
          cancelRows: count(".interaction-morse-row.morse-cancel"),
        }};
        console.log(JSON.stringify(result));
        """
    )
    completed = subprocess.run(
        [node, "-e", runner],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr or completed.stdout)
    result = json.loads(completed.stdout)
    expected = {
        "hasDefinition": True,
        "mapDot": "KC_E",
        "mapDash": "KC_T",
        "mapA": "KC_A",
        "mapI": "KC_I",
        "mapDotDashDot": "KC_NO",
        "mapDotDashDash": "KC_NO",
        "maxDepth": 3,
        "force": "..,.-",
        "fallback": "KC_ESC",
        "copiedAction": "MORSE(main)",
        "initialName": "main",
        "initialExisting": "main",
        "initialMapHasMain": True,
        "deletedGone": True,
        "addedByPrompt": True,
        "selectedAfterPrompt": "popup_new",
        "promptMapDot": "KC_NO",
        "promptMapDash": "KC_NO",
        "hiddenMapAfterTypedInput": ".=KC_Z\n-=KC_NO",
        "promptFallback": None,
        "promptForce": None,
        "hasTreeEditor": True,
        "visibleSequencesForced": ".|..|.-|-",
        "visibleSequencesForceOff": ".|..|.-|-",
        "visibleRootMissingDot": ".|-",
        "dotDashToggleAfterForceOff": ">",
    }
    failures = {key: (result.get(key), value) for key, value in expected.items() if result.get(key) != value}
    for key in ("rowCount", "prefixRows", "leafRows", "forceRows", "cancelRows"):
        if int(result.get(key) or 0) <= 0:
            failures[key] = (result.get(key), "> 0")
    if int(result.get("editableRows") or 0) <= 1:
        failures["editableRows"] = (result.get("editableRows"), "> 1")
    if int(result.get("accordionCount") or 0) <= 0:
        failures["accordionCount"] = (result.get("accordionCount"), "> 0")
    assert not failures, failures
    print("ok: Morse browser DOM builder logic")


if __name__ == "__main__":
    main()
