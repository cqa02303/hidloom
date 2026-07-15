#!/usr/bin/env python3
"""Drive the Interaction Conditional Layers editor through Chromium DevTools.

This helper is a real-browser DOM smoke for the Interaction summary editor.  It
does not save settings; it edits the in-page JSON textarea, checks the summary
state, then restores the original textarea content.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import urllib.request

import websockets


async def _cdp_call(ws, counter: list[int], method: str, params: dict | None = None, timeout: float = 10.0) -> dict:
    counter[0] += 1
    msg_id = counter[0]
    await ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
        if msg.get("id") == msg_id:
            return msg


def _js_conditional_editor_probe(rule_name: str, sources: list[int], target: int) -> str:
    return f"""
(async () => {{
  const ruleName = {json.dumps(rule_name)};
  const sourceText = {json.dumps(", ".join(str(layer) for layer in sources))};
  const targetLayer = {int(target)};
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const waitFor = async (predicate, timeoutMs = 6000) => {{
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {{
      const value = predicate();
      if (value) return value;
      await wait(100);
    }}
    return null;
  }};
  const metricValue = (label) => {{
    for (const item of document.querySelectorAll(".interaction-summary-metric")) {{
      const name = item.querySelector("span")?.textContent || "";
      if (name === label) return item.querySelector("code")?.textContent || "";
    }}
    return "";
  }};
  const conditionalSection = () => Array.from(document.querySelectorAll(".interaction-summary-section"))
    .find((section) => (section.querySelector(".interaction-summary-title")?.textContent || "").startsWith("Conditional Layers ("));
  const conditionalRows = () => {{
    const section = conditionalSection();
    return section ? Array.from(section.querySelectorAll(".interaction-summary-row")) : [];
  }};
  const settings = () => {{
    const editor = document.getElementById("interaction-editor");
    return editor ? JSON.parse(editor.value || "{{}}") : {{}};
  }};
  const conditionalCount = () => {{
    const rules = settings().conditional_layers;
    return Array.isArray(rules) ? rules.length : 0;
  }};
  const hasRuleRow = () => conditionalRows().some((row) => (row.textContent || "").includes(ruleName));

  await new Promise((resolve) => {{
    if (document.readyState === "complete") resolve();
    else window.addEventListener("load", resolve, {{ once: true }});
  }});
  if (typeof setActiveTab === "function") setActiveTab("interaction");
  await waitFor(() => document.getElementById("interaction-editor"));
  if (typeof fetchInteractionSettings === "function") {{
    await fetchInteractionSettings();
  }}
  if (typeof refreshInteractionRuntimeSummary === "function") await refreshInteractionRuntimeSummary();
  if (typeof refreshInteractionConditionalInspector === "function") await refreshInteractionConditionalInspector();
  await waitFor(() => document.getElementById("interaction-summary-panel"));

  const editor = document.getElementById("interaction-editor");
  if (!editor) return {{ ok: false, reason: "editor_not_found" }};
  const originalText = editor.value;
  const originalCount = conditionalCount();
  const before = {{
    count: originalCount,
    conditionalMetric: metricValue("Conditional"),
    inspectorMetric: metricValue("Conditional Inspector"),
    inspectorLoaded: Boolean(typeof _interactionConditionalInspector !== "undefined" && _interactionConditionalInspector),
  }};

  try {{
    document.getElementById("interaction-conditional-name").value = ruleName;
    document.getElementById("interaction-conditional-if-all").value = sourceText;
    document.getElementById("interaction-conditional-then").value = String(targetLayer);
    const addButton = Array.from(document.querySelectorAll(".interaction-conditional-editor button"))
      .find((button) => (button.textContent || "").includes("Add Conditional"));
    if (!addButton) return {{ ok: false, reason: "add_button_not_found", before }};
    addButton.click();
    await waitFor(() => conditionalCount() === originalCount + 1 && hasRuleRow());
    const afterAdd = {{
      count: conditionalCount(),
      rowVisible: hasRuleRow(),
      status: document.getElementById("interaction-status")?.textContent || "",
      dirty: document.getElementById("interaction-status")?.dataset.dirty || "",
      validation: document.getElementById("interaction-status")?.dataset.validation || "",
      conditionalMetric: metricValue("Conditional"),
      inspectorMetric: metricValue("Conditional Inspector"),
      inspectorCleared: typeof _interactionConditionalInspector === "undefined" || _interactionConditionalInspector === null,
      editorIncludesRule: editor.value.includes(ruleName),
    }};

    const row = conditionalRows().find((item) => (item.textContent || "").includes(ruleName));
    const removeButton = row
      ? Array.from(row.querySelectorAll("button")).find((button) => (button.textContent || "").includes("削除"))
      : null;
    if (!removeButton) return {{ ok: false, reason: "remove_button_not_found", before, afterAdd }};
    removeButton.click();
    await waitFor(() => conditionalCount() === originalCount && !hasRuleRow());
    const afterRemove = {{
      count: conditionalCount(),
      rowVisible: hasRuleRow(),
      status: document.getElementById("interaction-status")?.textContent || "",
      conditionalMetric: metricValue("Conditional"),
      inspectorMetric: metricValue("Conditional Inspector"),
      inspectorCleared: typeof _interactionConditionalInspector === "undefined" || _interactionConditionalInspector === null,
      restoredCount: conditionalCount() === originalCount,
    }};

    const checks = {{
      addCount: afterAdd.count === originalCount + 1,
      addRow: afterAdd.rowVisible,
      addStatus: afterAdd.status.includes("追加"),
      addDirty: afterAdd.dirty === "1",
      addInspectorCleared: afterAdd.inspectorCleared,
      addMetricPending: afterAdd.conditionalMetric.includes(`rules ${{originalCount + 1}} / active pending-save`),
      addInspectorUnavailable: afterAdd.inspectorMetric === "unavailable",
      removeCount: afterRemove.count === originalCount,
      removeRowGone: !afterRemove.rowVisible,
      removeStatus: afterRemove.status.includes("削除"),
      removeInspectorCleared: afterRemove.inspectorCleared,
    }};
    return {{
      ok: Object.values(checks).every(Boolean),
      checks,
      before,
      afterAdd,
      afterRemove,
    }};
  }} finally {{
    editor.value = originalText;
    if (typeof markInteractionEditorChanged === "function") markInteractionEditorChanged();
    if (typeof renderInteractionSummary === "function") renderInteractionSummary();
    if (typeof refreshInteractionConditionalInspector === "function") await refreshInteractionConditionalInspector();
  }}
}})()
"""


async def _run(args: argparse.Namespace) -> dict:
    with urllib.request.urlopen(f"{args.cdp}/json/list", timeout=5) as resp:
        pages = json.load(resp)
    page = next((p for p in pages if p.get("type") == "page"), None)
    if page is None:
        raise RuntimeError("CDP page target not found")
    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=4_000_000) as ws:
        counter = [0]
        await _cdp_call(ws, counter, "Runtime.enable", timeout=args.cdp_timeout)
        if args.reload:
            await _cdp_call(ws, counter, "Page.enable", timeout=args.cdp_timeout)
            await _cdp_call(ws, counter, "Page.reload", {"ignoreCache": True}, timeout=args.cdp_timeout)
            await asyncio.sleep(args.reload_wait)
        expression = _js_conditional_editor_probe(args.name, args.sources, args.target)
        return await _cdp_call(
            ws,
            counter,
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
            },
            timeout=args.cdp_timeout,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cdp", default="http://127.0.0.1:9222")
    parser.add_argument("--name", default="cdp_probe_conditional")
    parser.add_argument("--sources", type=int, nargs="+", default=[1, 2])
    parser.add_argument("--target", type=int, default=3)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--reload-wait", type=float, default=2.0)
    parser.add_argument("--cdp-timeout", type=float, default=12.0)
    args = parser.parse_args()
    result = asyncio.run(_run(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
