#!/usr/bin/env python3
"""Static checks for HTTP UI assets."""
from __future__ import annotations

from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    index = (ROOT / "daemon/http/static/index.html").read_text(encoding="utf-8")
    static_readme = (ROOT / "daemon/http/static/README.md").read_text(encoding="utf-8")
    extra = (ROOT / "daemon/http/static/extra_key_groups.js").read_text(encoding="utf-8")
    remap = (ROOT / "daemon/http/static/remap_panel.js").read_text(encoding="utf-8")
    remap_quick = (ROOT / "daemon/http/static/remap_quick_keys.js").read_text(encoding="utf-8")
    scripts = (ROOT / "daemon/http/static/script_editor.js").read_text(encoding="utf-8")
    settings = (ROOT / "daemon/http/static/settings_panel.js").read_text(encoding="utf-8")
    interaction = (ROOT / "daemon/http/static/interaction_panel.js").read_text(encoding="utf-8")
    interaction_css = (ROOT / "daemon/http/static/interaction_panel.css").read_text(encoding="utf-8")
    keyboard_css = (ROOT / "daemon/http/static/keyboard.css").read_text(encoding="utf-8")
    remap_quick_css = (ROOT / "daemon/http/static/remap_quick_keys.css").read_text(encoding="utf-8")

    assert "恒久的な見た目は CSS asset に置く" in static_readme
    assert "document.createElement(\"style\")" in static_readme
    assert "status_panel.css" in static_readme
    assert "remap_quick_keys.css" in static_readme
    assert "lighting_panel.css" in static_readme

    assert 'id="settings-stick-validate"' in index
    assert 'id="settings-stick-min-range-volts"' in index
    assert 'id="settings-stick-map"' in index
    assert "calibrateAnalogStick('validate', false)" in index
    assert "function analogStickMapModel" in settings
    assert "function renderAnalogStickMap" in settings
    assert "mergeAnalogStickCalibration(_analogStickCurrent, data)" in settings
    assert 'settingsEl("settings-stick-min-range-volts")' in settings
    assert "Number(data?.min_range_volts)" in settings
    assert "minRangeEl.value = String(minRangeVolts)" in settings
    assert "min_range_volts: minRangeVolts" in settings
    assert 'JSON.stringify({ phase, min_range_volts: minRangeVolts })' in settings
    assert 'setAnalogStickStatus(data.valid ? "保存値は有効です"' in settings
    assert ".settings-stick-map" in keyboard_css
    assert ".settings-stick-map-point" in keyboard_css

    assert 'type="image/svg+xml" href="/static/hidloom-mark.svg"' in index
    assert 'rel="icon" href="/static/favicon.ico"' in index
    assert 'href="/static/favicon-32x32.png"' in index
    assert 'href="/static/apple-touch-icon.png"' in index
    assert 'href="/static/android-chrome-192x192.png"' in index
    assert 'href="/static/android-chrome-512x512.png"' in index
    expected_icons = {
        "favicon-32x32.png": (32, 32),
        "apple-touch-icon.png": (180, 180),
        "android-chrome-192x192.png": (192, 192),
        "android-chrome-512x512.png": (512, 512),
    }
    assert (ROOT / "daemon/http/static/favicon.ico").is_file()
    assert (ROOT / "daemon/http/static/hidloom-mark.svg").is_file()
    for name, size in expected_icons.items():
        with Image.open(ROOT / "daemon/http/static" / name) as icon:
            assert icon.size == size, name

    assert "/static/extra_key_groups.js" in index
    assert "/static/remap_quick_keys.js" in index
    assert index.index("/static/remap_vil.js") < index.index("/static/extra_key_groups.js")
    assert index.index("/static/extra_key_groups.js") < index.index("/static/remap_quick_keys.js")
    assert index.index("/static/remap_quick_keys.js") < index.index("/static/script_editor.js")
    assert '@import url("/static/remap_quick_keys.css")' in interaction_css

    # Remap search / filter.
    assert "function ensureRemapSearchFilter" in remap
    assert "function applyRemapSearchFilter" in remap
    assert "function openRemapChoicePicker" in remap
    assert "window.openRemapChoicePicker = openRemapChoicePicker" in remap
    assert "function applyDirectRemapInput" in remap
    assert "window.applyDirectRemapInput = applyDirectRemapInput" in remap
    assert "normalizeDirectRemapAction" in remap
    assert "[\\s\\u3000]+" in remap
    assert 'const label = _labelsCache[kc] || window.HIDLOOM_EXTRA_KEY_LABELS?.[kc]' in remap
    assert 'id="remap-direct-input"' in index
    assert "LSFT(LGUI(KC_F23))" in index
    assert "_remapChoicePicker" in remap
    assert "if (_remapChoicePicker)" in remap
    assert "keyEl.dataset.keycode = kc" in remap
    assert "keyEl.dataset.group = group.label" in remap
    assert "key.hidden = !match" in remap
    assert ".remap-search-row" in keyboard_css
    assert ".remap-direct-row" in keyboard_css
    assert "_cqaEnsureRemapSearchBox" in extra
    assert 'input.id = "remap-search"' in extra
    assert "_cqaApplyRemapSearchFilter" in extra
    assert "remapSearchNeedle" in remap
    assert "Copilot" in extra
    assert "window.HIDLOOM_EXTRA_KEY_LABELS = EXTRA_KEY_LABELS" in extra
    assert "renderAllRemapTabs.__cqaSearchPatched" in extra
    assert "switchRemapTab.__cqaSearchPatched" in extra

    # Remap quick access / pin / recent / unimplemented docs guide.
    assert "REMAP_PINNED_STORAGE_KEY" in remap_quick
    assert "REMAP_RECENT_STORAGE_KEY" in remap_quick
    assert "window.localStorage" in remap_quick
    assert "toggleRemapPinnedKeycode" in remap_quick
    assert "rememberRemapRecentKeycode" in remap_quick
    assert "remap-quick-access" in remap_quick
    assert "remap-pin-toggle" in remap_quick
    assert "remap-unimplemented-guide" in remap_quick
    assert "keycode/unimplemented-keycodes.md" in remap_quick
    assert "docs/keycode/unimplemented-keycodes.md" in remap_quick
    assert "UNIMPLEMENTED_KEYCODES.md" not in remap_quick
    assert "renderAllRemapTabs.__remapQuickAccessPatched" in remap_quick
    assert "applyRemap.__remapQuickAccessPatched" in remap_quick
    assert "Pinned" in remap_quick
    assert "Recent" in remap_quick
    assert "remap-quick-access-style" not in remap_quick
    assert "document.createElement(\"style\")" not in remap_quick
    assert ".remap-quick-access" in remap_quick_css
    assert ".remap-pin-toggle" in remap_quick_css
    assert ".remap-unimplemented-guide" in remap_quick_css

    # Script label / safety.
    assert "let _remapScriptEntries = new Map()" in remap
    assert 'fetch("/api/scripts")' in remap
    assert "function _decorateRemapScriptKey" in remap
    assert "keyEl.dataset.scriptLabel" in remap
    assert "keyEl.dataset.scriptSafety" in remap
    assert "remap-key-script-danger" in remap
    assert "scriptLabel" in remap
    assert "scriptSafety" in remap
    assert "function analyzeScriptSafetyContent" in scripts
    assert "function updateScriptSafetyPanel" in scripts
    assert "script-safety-panel" in scripts
    assert "SCRIPT_DANGER_PATTERNS" in scripts
    assert "confirmDangerousScriptRun" in scripts
    assert "危険scriptの${actionLabel}をキャンセルしました" in scripts
    assert ".script-safety-panel" in keyboard_css
    assert "KC_SH10: \"Script\\n10 ⚠\"" in extra
    assert "_cqaAnalyzeScriptContent" in extra
    assert "#\\s*@danger" in extra
    assert "#\\s*@confirm" in extra
    assert "systemctl\\s+(?:poweroff|halt|reboot)" in extra
    assert "script-safety-panel" in extra
    assert "checkRunScriptContent.__cqaSafetyPatched" in extra
    assert ".remap-key-script" in keyboard_css
    assert ".remap-key-script-danger" in keyboard_css
    assert ".remap-script-badge" in keyboard_css

    # Interaction summary / remove / reorder.
    assert "function renderInteractionSummary" in interaction
    assert "function ensureInteractionSummary" in interaction
    assert "function moveInteractionItem" in interaction
    assert "interaction-summary-panel" in interaction
    assert "interaction-summary-btn" in interaction
    assert "renderInteractionRuntimeSummary" in interaction
    assert "refreshInteractionRuntimeSummary" in interaction
    assert "refreshInteractionInspector" in interaction
    assert ".interaction-summary-panel" in interaction_css
    assert ".interaction-summary-metrics" in interaction_css
    assert ".interaction-inspector-row" in interaction_css
    assert "_cqaEnsureInteractionSummary" in extra
    assert "interaction-summary-panel" in extra
    assert "_cqaRenderInteractionSection" in extra
    assert "_cqaMoveArrayItem" in extra
    assert "Combo" in extra
    assert "Tap Dance" in extra
    assert "Key Override" in extra
    assert "削除" in extra

    # Keymap matrix coordinate overlay.
    keyboard_js = (ROOT / "daemon/http/static/keyboard.js").read_text(encoding="utf-8")
    assert 'id="matrix-coords-toggle"' in index
    assert "KEYBOARD_MATRIX_COORDS_KEY" in keyboard_js
    assert "TOUCH_FLICK_PREVIEW_KEY" in keyboard_js
    assert 'fetch("/api/touch-panel/flick")' in keyboard_js
    assert "function touchFlickDirection" in keyboard_js
    assert "function resolveTouchFlickPreviewAction" in keyboard_js
    assert "function resolveTouchFlickImePreviewAction" in keyboard_js
    assert "function resolveTouchFlickDispatchEnvelope" in keyboard_js
    assert "function updateTouchFlickDispatchPreview" in keyboard_js
    assert '"/api/touch-panel/flick/resolve"' in keyboard_js
    assert '"/api/touch-panel/flick/dispatch"' in keyboard_js
    assert "csrfFetch(touchFlickResolveRoute()" in keyboard_js
    assert "function touchFlickDispatchRoute" in keyboard_js
    assert "function touchFlickDispatchPolicy" in keyboard_js
    assert "function touchFlickBrowserDispatchEnabled" in keyboard_js
    assert "function touchFlickHostImeWarning" in keyboard_js
    assert "function touchFlickDispatchBlockedReason" in keyboard_js
    assert "local_send_disabled" in keyboard_js
    assert "host-profile-required" in keyboard_js
    assert 'if (!touchFlickCanEnableSend()) return "browser_dispatch_disabled";' in keyboard_js
    assert 'if (blockedReason) return { result: "blocked", reason: blockedReason };' in keyboard_js
    assert "csrfFetch(touchFlickDispatchRoute()" in keyboard_js
    assert 'method: "POST"' in keyboard_js
    assert 'headers: { "Content-Type": "application/json" }' in keyboard_js
    assert "touchFlickLocalDispatchEnvelope" in keyboard_js
    assert "resolve_endpoint_unavailable" in keyboard_js
    assert 'dispatch: "preview_noop"' in keyboard_js
    assert "function cancelTouchFlickPreview" in keyboard_js
    assert 'el.classList.add("active", "pressed", "flicking")' in keyboard_js
    assert 'pointer.el.classList.remove("active", "pressed", "flicking")' in keyboard_js
    assert "function renderTouchFlickImeControls" in keyboard_js
    assert 'id="touch-flick-ime-controls"' in index
    assert "ensureKeyMatrixCoordBadge" in keyboard_js
    assert "updateKeyboardMatrixCoordsOverlay" in keyboard_js
    assert "handleInteractionComboKeyPick(row, col, matrixKey)" in keyboard_js
    assert ".key-matrix-coord" in keyboard_css
    assert ".touch-flick-panel" in keyboard_css
    assert ".touch-flick-pad" in keyboard_css
    assert ".touch-flick-ime-control" in keyboard_css
    assert ".key.flicking" in keyboard_css
    assert "transform: none;" in keyboard_css
    assert "body.keyboard-demo-mode *" in keyboard_css
    assert "cursor: none !important;" in keyboard_css
    assert ".interaction-combo-pick-mode .key[data-matrix-row]" in keyboard_css

    print("ok: HTTP UI assets")


if __name__ == "__main__":
    main()
