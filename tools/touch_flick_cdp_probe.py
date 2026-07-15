#!/usr/bin/env python3
"""Drive the touch flick kiosk UI through Chromium DevTools.

This is a real-browser probe for the 4.3 inch kiosk path:
PointerEvent -> browser resolver/preflight -> HTTP dispatch -> logicd.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shlex
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


def _js_pad_probe(key: str, direction: str, submit: bool) -> str:
    direction_offsets = {
        "center": (0, 0),
        "left": (-48, 0),
        "right": (48, 0),
        "up": (0, -48),
        "down": (0, 48),
    }
    dx, dy = direction_offsets[direction]
    submit_js = ""
    if submit:
        submit_js = """
  await dispatchTouchFlickEnvelope({
    dispatch_event: {
      source: "touch_panel_flick",
      kind: "submit_probe",
      key: "ctrl_enter",
      action: "C(KC_ENTER)",
      output: "keycode",
      dispatch: "tap_action",
      enabled: true,
    },
  });
"""
    return f"""
(async () => {{
  await new Promise((resolve) => {{
    if (document.readyState === "complete") resolve();
    else window.addEventListener("load", resolve, {{ once: true }});
  }});
  if (!window._touchFlickMetadata?.available) {{
    await new Promise((resolve) => setTimeout(resolve, 1200));
  }}
  window.setTouchFlickPreviewEnabled(true);
  window.setTouchFlickSendEnabled(true);
  await new Promise((resolve) => setTimeout(resolve, 150));
  const pad = document.querySelector('.touch-flick-pad[data-flick-key="{key}"]');
  if (!pad) {{
    return {{ ok: false, reason: "pad_not_found", key: "{key}", body: document.body.innerText.slice(0, 500) }};
  }}
  const rect = pad.getBoundingClientRect();
  const x = rect.left + rect.width / 2;
  const y = rect.top + rect.height / 2;
  const pointerId = 9000 + Math.floor(Math.random() * 500);
  const common = {{ pointerId, bubbles: true, cancelable: true, pointerType: "touch", isPrimary: true }};
  pad.dispatchEvent(new PointerEvent("pointerdown", {{ ...common, clientX: x, clientY: y }}));
  await new Promise((resolve) => setTimeout(resolve, 80));
  pad.dispatchEvent(new PointerEvent("pointermove", {{ ...common, clientX: x + {dx}, clientY: y + {dy} }}));
  await new Promise((resolve) => setTimeout(resolve, 80));
  pad.dispatchEvent(new PointerEvent("pointerup", {{ ...common, clientX: x + {dx}, clientY: y + {dy} }}));
  await new Promise((resolve) => setTimeout(resolve, 2200));
{submit_js}
  return {{
    ok: true,
    key: "{key}",
    direction: "{direction}",
    status: document.getElementById("touch-flick-status")?.textContent || "",
    preview: document.getElementById("touch-flick-preview")?.textContent || "",
    sendEnabled: window.touchFlickSendEnabled,
    previewEnabled: window.touchFlickPreviewEnabled,
  }};
}})()
"""


def _js_control_probe(control: str) -> str:
    return f"""
(async () => {{
  await new Promise((resolve) => {{
    if (document.readyState === "complete") resolve();
    else window.addEventListener("load", resolve, {{ once: true }});
  }});
  if (!window._touchFlickMetadata?.available) {{
    await new Promise((resolve) => setTimeout(resolve, 1200));
  }}
  window.setTouchFlickPreviewEnabled(true);
  window.setTouchFlickSendEnabled(true);
  await new Promise((resolve) => setTimeout(resolve, 150));
  const btn = document.querySelector('.touch-flick-ime-control[data-ime-control="{control}"]');
  if (!btn) {{
    return {{
      ok: false,
      reason: "control_not_found",
      control: "{control}",
      controls: Array.from(document.querySelectorAll(".touch-flick-ime-control")).map((el) => el.dataset.imeControl || el.textContent),
    }};
  }}
  btn.click();
  await new Promise((resolve) => setTimeout(resolve, 800));
  return {{
    ok: true,
    control: "{control}",
    status: document.getElementById("touch-flick-status")?.textContent || "",
    preview: document.getElementById("touch-flick-preview")?.textContent || "",
    sendEnabled: window.touchFlickSendEnabled,
    previewEnabled: window.touchFlickPreviewEnabled,
  }};
}})()
"""


def _js_batch_probe(steps: list[str], delay_ms: int) -> str:
    items: list[dict[str, str]] = []
    for raw_step in steps:
        if ":" not in raw_step:
            items.append({"type": "control", "control": raw_step})
            continue
        key, direction = raw_step.split(":", 1)
        items.append({"type": "pad", "key": key, "direction": direction})
    return f"""
(async () => {{
  const steps = {json.dumps(items, ensure_ascii=False)};
  const delayMs = {int(delay_ms)};
  const directionOffsets = {{
    center: [0, 0],
    left: [-48, 0],
    right: [48, 0],
    up: [0, -48],
    down: [0, 48],
  }};
  await new Promise((resolve) => {{
    if (document.readyState === "complete") resolve();
    else window.addEventListener("load", resolve, {{ once: true }});
  }});
  if (!window._touchFlickMetadata?.available) {{
    await new Promise((resolve) => setTimeout(resolve, 1200));
  }}
  window.setTouchFlickPreviewEnabled(true);
  window.setTouchFlickSendEnabled(true);
  await new Promise((resolve) => setTimeout(resolve, 150));
  const results = [];
  const dispatchLog = [];
  const originalDispatchTouchFlickEnvelope = dispatchTouchFlickEnvelope;
  dispatchTouchFlickEnvelope = async (envelope) => {{
    const result = await originalDispatchTouchFlickEnvelope(envelope);
    dispatchLog.push({{
      key: envelope?.dispatch_event?.key || "",
      action: envelope?.dispatch_event?.action || "",
      output: envelope?.dispatch_event?.output || "",
      result,
    }});
    return result;
  }};
  let expectedDispatches = 0;
  try {{
  for (const step of steps) {{
    if (step.type === "control") {{
      const btn = document.querySelector(`.touch-flick-ime-control[data-ime-control="${{step.control}}"]`);
      if (!btn) {{
        results.push({{ ...step, ok: false, reason: "control_not_found" }});
        continue;
      }}
      expectedDispatches += 1;
      btn.click();
      await new Promise((resolve) => setTimeout(resolve, delayMs));
      results.push({{
        ...step,
        ok: true,
        status: document.getElementById("touch-flick-status")?.textContent || "",
        preview: document.getElementById("touch-flick-preview")?.textContent || "",
      }});
      continue;
    }}
    const pad = document.querySelector(`.touch-flick-pad[data-flick-key="${{step.key}}"]`);
    const offset = directionOffsets[step.direction] || directionOffsets.center;
    if (!pad) {{
      results.push({{ ...step, ok: false, reason: "pad_not_found" }});
      continue;
    }}
    expectedDispatches += 1;
    const rect = pad.getBoundingClientRect();
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;
    const pointerId = 9400 + Math.floor(Math.random() * 500);
    const common = {{ pointerId, bubbles: true, cancelable: true, pointerType: "touch", isPrimary: true }};
    pad.dispatchEvent(new PointerEvent("pointerdown", {{ ...common, clientX: x, clientY: y }}));
    await new Promise((resolve) => setTimeout(resolve, 80));
    pad.dispatchEvent(new PointerEvent("pointermove", {{ ...common, clientX: x + offset[0], clientY: y + offset[1] }}));
    await new Promise((resolve) => setTimeout(resolve, 80));
    pad.dispatchEvent(new PointerEvent("pointerup", {{ ...common, clientX: x + offset[0], clientY: y + offset[1] }}));
    await new Promise((resolve) => setTimeout(resolve, delayMs));
    results.push({{
      ...step,
      ok: true,
      status: document.getElementById("touch-flick-status")?.textContent || "",
      preview: document.getElementById("touch-flick-preview")?.textContent || "",
    }});
  }}
  }} finally {{
    const startedAt = Date.now();
    while (Date.now() - startedAt < 12000) {{
      const queued = typeof touchFlickTextDispatchQueued === "number" ? touchFlickTextDispatchQueued : 0;
      if (dispatchLog.length >= expectedDispatches && queued === 0) break;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }}
    dispatchTouchFlickEnvelope = originalDispatchTouchFlickEnvelope;
  }}
  const okDispatches = dispatchLog.filter((item) => item.result?.result === "ok").length;
  return {{
    ok: results.every((item) => item.ok)
      && dispatchLog.length === expectedDispatches
      && okDispatches === expectedDispatches,
    total: results.length,
    okCount: okDispatches,
    expectedDispatches,
    dispatchLog,
    queued: typeof touchFlickTextDispatchQueued === "number" ? touchFlickTextDispatchQueued : null,
    results,
  }};
}})()
"""


def _js_setup_probe() -> str:
    return """
(async () => {
  await new Promise((resolve) => {
    if (document.readyState === "complete") resolve();
    else window.addEventListener("load", resolve, { once: true });
  });
  if (!window._touchFlickMetadata?.available) {
    await new Promise((resolve) => setTimeout(resolve, 1200));
  }
  window.setTouchFlickPreviewEnabled(true);
  window.setTouchFlickSendEnabled(true);
  await new Promise((resolve) => setTimeout(resolve, 300));
  return {
    ok: true,
    status: document.getElementById("touch-flick-status")?.textContent || "",
    preview: document.getElementById("touch-flick-preview")?.textContent || "",
    sendButton: document.getElementById("touch-flick-send-toggle")?.textContent || "",
    previewButton: document.getElementById("touch-flick-toggle")?.textContent || "",
  };
})()
"""


def _js_named_preset_probe(key: str, direction: str) -> str:
    direction_offsets = {
        "center": (0, 0),
        "left": (-48, 0),
        "right": (48, 0),
        "up": (0, -48),
        "down": (0, 48),
    }
    dx, dy = direction_offsets[direction]
    return f"""
(async () => {{
  await new Promise((resolve) => {{
    if (document.readyState === "complete") resolve();
    else window.addEventListener("load", resolve, {{ once: true }});
  }});
  if (!window._touchFlickMetadata?.available) {{
    await new Promise((resolve) => setTimeout(resolve, 1200));
  }}
  window.setTouchFlickPreviewEnabled(true);
  window.setTouchFlickSendEnabled(true);
  await new Promise((resolve) => setTimeout(resolve, 150));
  const pad = document.querySelector('.touch-flick-pad[data-flick-key="{key}"]');
  if (!pad) {{
    return {{ ok: false, reason: "pad_not_found", key: "{key}" }};
  }}
  const metadata = typeof _touchFlickMetadata !== "undefined" ? _touchFlickMetadata : window._touchFlickMetadata;
  const metadataEntry = (metadata?.named_text?.entries || [])
    .find((entry) => entry.pad === "{key}" && entry.direction === "{direction}");
  const title = pad.getAttribute("title") || "";
  const before = {{
    label: pad.textContent || "",
    previewOutput: pad.dataset.previewOutput || "",
    title,
    status: document.getElementById("touch-flick-status")?.textContent || "",
    metadataEntry: metadataEntry || null,
  }};
  const rect = pad.getBoundingClientRect();
  const x = rect.left + rect.width / 2;
  const y = rect.top + rect.height / 2;
  const pointerId = 9700 + Math.floor(Math.random() * 500);
  const common = {{ pointerId, bubbles: true, cancelable: true, pointerType: "touch", isPrimary: true }};
  pad.dispatchEvent(new PointerEvent("pointerdown", {{ ...common, clientX: x, clientY: y }}));
  await new Promise((resolve) => setTimeout(resolve, 80));
  pad.dispatchEvent(new PointerEvent("pointermove", {{ ...common, clientX: x + {dx}, clientY: y + {dy} }}));
  await new Promise((resolve) => setTimeout(resolve, 80));
  pad.dispatchEvent(new PointerEvent("pointerup", {{ ...common, clientX: x + {dx}, clientY: y + {dy} }}));
  await new Promise((resolve) => setTimeout(resolve, 2600));
  const preview = document.getElementById("touch-flick-preview")?.textContent || "";
  const checks = {{
    label: before.label === "、。？！定",
    badge: before.previewOutput === "named-text",
    titleAction: title.includes("{direction}: TEXT(kana_a)"),
    titleFamily: title.includes("named_send_string"),
    titlePreflight: title.includes("preflight"),
    statusSummary: before.status.includes("named-text:1"),
    metadataEntry: metadataEntry?.action === "TEXT(kana_a)"
      && metadataEntry?.label === "、。？！定"
      && metadataEntry?.preflight_route === "/api/interaction/text-send-safety/plan",
    previewAction: preview.includes("TEXT(kana_a)"),
    previewCompositionPolicy: preview.includes("composition_mode_requires_unicode_action"),
    previewDispatchBlocked: preview.includes("/ blocked"),
  }};
  return {{
    ok: Object.values(checks).every(Boolean),
    key: "{key}",
    direction: "{direction}",
    checks,
    before,
    preview,
    sendEnabled: window.touchFlickSendEnabled,
    previewEnabled: window.touchFlickPreviewEnabled,
  }};
}})()
"""


def _js_composition_dispatch_boundary_probe(key: str, direction: str) -> str:
    return f"""
(async () => {{
  await new Promise((resolve) => {{
    if (document.readyState === "complete") resolve();
    else window.addEventListener("load", resolve, {{ once: true }});
  }});
  if (!window._touchFlickMetadata?.available) {{
    await new Promise((resolve) => setTimeout(resolve, 1200));
  }}
  window.setTouchFlickPreviewEnabled(true);
  await new Promise((resolve) => setTimeout(resolve, 150));
  const metadata = typeof _touchFlickMetadata !== "undefined" ? _touchFlickMetadata : window._touchFlickMetadata;
  const pad = (metadata?.layout?.pads || []).find((item) => item.key === "{key}");
  if (!pad) {{
    return {{ ok: false, reason: "pad_not_found", key: "{key}" }};
  }}
  const request = {{ kind: "flick_pad", key: "{key}", direction: "{direction}" }};
  const resolved = resolveTouchFlickPreviewAction(pad, "{direction}");
  const envelope = await resolveTouchFlickDispatchEnvelope(request, resolved);
  envelope.composition_plan = await resolveTouchFlickCompositionPlan(request);
  const dispatchPayload = touchFlickDispatchPayload(envelope);
  const payloadKeys = Object.keys(dispatchPayload);
  const checks = {{
    envelopeHasCompositionPlan: Object.prototype.hasOwnProperty.call(envelope, "composition_plan"),
    previewAvailable: envelope.composition_plan?.available === true,
    previewRomaji: (envelope.composition_plan?.tap_sequence || []).length > 0,
    payloadNoComposition: !Object.prototype.hasOwnProperty.call(dispatchPayload, "composition_plan"),
    payloadNoCamelComposition: !Object.prototype.hasOwnProperty.call(dispatchPayload, "compositionPlan"),
    payloadEventOnly: payloadKeys.length === 1 && payloadKeys[0] === "event",
    payloadActionMatches: dispatchPayload.event?.action === envelope.dispatch_event?.action,
  }};
  return {{
    ok: Object.values(checks).every(Boolean),
    key: "{key}",
    direction: "{direction}",
    checks,
    dispatchPayload,
    compositionPlan: envelope.composition_plan,
    preview: document.getElementById("touch-flick-preview")?.textContent || "",
    sendEnabled: window.touchFlickSendEnabled,
    previewEnabled: window.touchFlickPreviewEnabled,
  }};
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
        if args.setup_only:
            expression = _js_setup_probe()
        elif args.composition_dispatch_boundary:
            expression = _js_composition_dispatch_boundary_probe(args.key, args.direction)
        elif args.named_preset:
            expression = _js_named_preset_probe(args.key, args.direction)
        elif args.batch:
            expression = _js_batch_probe(args.batch, args.delay_ms)
        elif args.control:
            expression = _js_control_probe(args.control)
        else:
            expression = _js_pad_probe(args.key, args.direction, args.submit)
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
    parser.add_argument("--key", default="a")
    parser.add_argument("--direction", choices=["center", "left", "right", "up", "down"], default="left")
    parser.add_argument("--control", default="")
    parser.add_argument(
        "--batch",
        nargs="*",
        default=[],
        help="Run pad steps as key:direction and IME controls as plain names, e.g. mark:center convert",
    )
    parser.add_argument("--batch-string", default="", help="Whitespace-separated batch steps; parsed with shell-like quoting.")
    parser.add_argument("--delay-ms", type=int, default=2200)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--setup-only", action="store_true")
    parser.add_argument(
        "--named-preset",
        action="store_true",
        help="Check the osoyoo-4.3 named text preset UI, preflight preview, and dispatch result.",
    )
    parser.add_argument(
        "--composition-dispatch-boundary",
        action="store_true",
        help="Check that composition preview metadata is stripped from the browser dispatch payload.",
    )
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--reload-wait", type=float, default=2.0)
    parser.add_argument("--cdp-timeout", type=float, default=10.0)
    args = parser.parse_args()
    if args.batch_string:
        args.batch.extend(shlex.split(args.batch_string))
    result = asyncio.run(_run(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
