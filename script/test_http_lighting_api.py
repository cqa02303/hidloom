#!/usr/bin/env python3
"""Local smoke test for HTTP Lighting API validation helpers."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon" / "http"))
sys.path.insert(0, str(ROOT))

import lighting  # noqa: E402
from lighting_api import lighting_reset_response  # noqa: E402

LIGHTING_JS = ROOT / "daemon" / "http" / "static" / "lighting_panel.js"
LIGHTING_ROLE_PREVIEW_JS = ROOT / "daemon" / "http" / "static" / "lighting_role_preview_controls.js"
LIGHTING_CSS = ROOT / "daemon" / "http" / "static" / "lighting_panel.css"
INTERACTION_CSS = ROOT / "daemon" / "http" / "static" / "interaction_panel.css"
INDEX_HTML = ROOT / "daemon" / "http" / "static" / "index.html"


def main() -> None:
    current = {"mode": 2, "speed": 128, "h": 0, "s": 0, "v": 128}

    partial = lighting.build_lighting_update({"mode": 40, "v": 200}, current)
    assert partial == {"mode": 40, "speed": 128, "h": 0, "s": 0, "v": 160}

    non_splash = lighting.build_lighting_update({"mode": 2, "v": 200}, current)
    assert non_splash == {"mode": 2, "speed": 128, "h": 0, "s": 0, "v": 200}

    full = lighting.build_lighting_update(
        {"mode": "43", "speed": "255", "h": "12", "s": "34", "v": "56"},
        current,
    )
    assert full == {"mode": 43, "speed": 255, "h": 12, "s": 34, "v": 56}

    for body in (
        {"mode": 45},
        {"mode": 40, "speed": 256},
        {"mode": 40, "h": -1},
        ["not", "object"],
    ):
        try:
            lighting.build_lighting_update(body, current)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid lighting body accepted: {body!r}")

    metadata = lighting.lighting_metadata()
    effect_ids = {effect["id"] for effect in metadata["effects"]}
    assert set(range(45)).issubset(effect_ids)
    assert 1000 in effect_ids
    categories = metadata["effect_categories"]
    category_ids = [category["id"] for category in categories]
    assert category_ids[:4] == ["control", "solid", "gradient", "band"]
    assert "reactive" in category_ids
    assert "rain" in category_ids
    grouped_ids = {effect_id for category in categories for effect_id in category["effects"]}
    assert effect_ids == grouped_ids
    assert any(category["label"] == "Reactive / Splash" for category in categories)

    lighting_js = LIGHTING_JS.read_text(encoding="utf-8")
    role_preview_js = LIGHTING_ROLE_PREVIEW_JS.read_text(encoding="utf-8")
    lighting_css = LIGHTING_CSS.read_text(encoding="utf-8")
    interaction_css = INTERACTION_CSS.read_text(encoding="utf-8")
    index_html = INDEX_HTML.read_text(encoding="utf-8")
    assert "function ensureLightingMetricsPanel()" in lighting_js
    assert "lighting-metrics-panel" in lighting_js
    assert "Direct-frame metrics" in lighting_js
    assert "lighting-metric-state" in lighting_js
    assert "lighting-metric-accepted" in lighting_js
    assert "lighting-metric-applied" in lighting_js
    assert "lighting-metric-ignored" in lighting_js
    assert "lighting-metric-rejected" in lighting_js
    assert "function updateLightingMetricsPanel(status)" in lighting_js
    assert "status?.ledd_direct_frame" in lighting_js
    assert "metrics.accepted_frames" in lighting_js
    assert "metrics.applied_frames" in lighting_js
    assert "metrics.ignored_frames" in lighting_js
    assert "metrics.rejected_frames" in lighting_js
    assert 'metrics.metrics_source === "missing" ? "missing" : "idle"' in lighting_js
    assert "metrics.metrics_error || metrics.last_error" in lighting_js
    assert "function fetchLightingMetrics()" in lighting_js
    assert 'fetch("/api/status")' in lighting_js
    assert "fetchLightingMetrics();" in lighting_js
    assert 'csrfFetch("/api/lighting/reset"' in lighting_js
    assert "function resetSavedLighting()" in lighting_js
    assert "反映済み / 保存待ち" in lighting_js
    assert "applyLighting();" in lighting_js

    assert "LIGHTING_ROLE_ORDER" in lighting_js
    assert "function inferLightingRoleFromKeycode(keycode)" in lighting_js
    assert "lighting-role-preview-panel" in lighting_js
    assert "LED role preview" in lighting_js
    assert "function ensureLightingRolePreviewPanel()" in lighting_js
    assert "function updateLightingRolePreviewPanel(layoutPayload)" in lighting_js
    assert "layoutPayload?.layer0" in lighting_js
    assert "lighting-role-chip" in lighting_js
    assert "function fetchLightingRolePreview()" in lighting_js
    assert 'fetch("/api/lighting/role-inspector")' in lighting_js
    assert "updateLightingRoleInspectorPanel" in lighting_js
    assert "fetchLightingRolePreview();" in lighting_js
    assert "function ensureLightingLayerPanel()" in lighting_js
    assert "Layer overlay colors" in lighting_js
    assert 'fetch("/api/lighting/layer-overlays")' in lighting_js
    assert 'csrfFetch("/api/lighting/layer-overlays"' in lighting_js
    assert "function saveLightingLayerOverlays()" in lighting_js
    assert ".lighting-layer-panel" in lighting_css
    assert ".lighting-layer-row" in lighting_css
    assert "document.createElement(\"style\")" not in lighting_js
    assert '@import url("/static/lighting_panel.css")' in interaction_css
    assert ".lighting-metrics-panel" in lighting_css
    assert ".lighting-role-preview-panel" in lighting_css
    assert ".lighting-role-chip" in lighting_css

    assert 'src="/static/lighting_role_preview_controls.js"' in index_html
    assert index_html.index("/static/lighting_panel.js") < index_html.index("/static/lighting_role_preview_controls.js")
    assert 'onclick="resetSavedLighting()"' in index_html
    assert "Preview roles" in role_preview_js
    assert "Restore effect" in role_preview_js
    assert "function ensureLightingRolePreviewControls()" in role_preview_js
    assert "function previewLightingRoles()" in role_preview_js
    assert "function restoreLightingRolePreview()" in role_preview_js
    assert 'csrfFetch("/api/lighting/role-preview"' in role_preview_js
    assert "_lightingRolePreviewRestoreState" in role_preview_js
    assert "vialrgb_save" not in role_preview_js
    assert "conf/ledd.json" not in role_preview_js
    resets: list[dict] = []

    async def send_ctrl(cmd: dict) -> dict:
        resets.append(cmd)
        return {"t": "LED", "result": "ok", "mode": 40, "speed": 128, "h": 175, "s": 77, "v": 160}

    reset_resp = asyncio.run(lighting_reset_response(send_ctrl))
    assert resets == [{"t": "LED", "op": "vialrgb_reset"}]
    assert '"mode": 40' in reset_resp.text
    print("ok: HTTP Lighting API validation is coherent")


if __name__ == "__main__":
    main()
