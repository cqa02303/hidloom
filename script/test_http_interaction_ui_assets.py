#!/usr/bin/env python3
"""Smoke test for Interaction UI asset wiring."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    index_html = (ROOT / "daemon/http/static/index.html").read_text(encoding="utf-8")

    assert 'data-app-tab="interaction"' in index_html
    assert 'data-app-tab="settings"' in index_html
    assert 'href="https://github.com/cqa02303/hidloom"' in index_html
    assert 'class="repo-title-link"' in index_html
    assert 'rel="noopener noreferrer"' in index_html
    assert 'id="interaction-panel"' in index_html
    assert '/static/interaction_panel.js' in index_html
    assert '/static/interaction_panel.css' in index_html
    assert '/static/lighting_panel.css' in index_html
    assert 'id="interaction-editor"' in index_html
    assert 'id="interaction-mode-gui-btn"' in index_html
    assert 'setInteractionEditorMode(\'gui\')' in index_html
    assert 'id="interaction-mode-raw-btn"' in index_html
    assert 'setInteractionEditorMode(\'raw\')' in index_html
    assert 'id="interaction-gui-editors"' in index_html
    assert 'id="interaction-raw-accordion"' in index_html
    assert 'id="interaction-builders-accordion"' in index_html
    assert 'Raw editor' in index_html
    assert 'Combo / Tap Dance / Key Override / Timing' in index_html
    assert 'id="interaction-action-buttons"' in index_html
    assert 'id="interaction-action-datalist"' in index_html
    assert 'id="interaction-keycode-picker"' in index_html
    assert 'insertSelectedInteractionAction()' in index_html
    assert 'id="kle-open-btn"' in index_html
    assert 'openKleForCurrentLayer()' in index_html
    assert 'keyboard-layout-editor.com/favicon.ico' not in index_html
    assert 'class="kle-open-icon" aria-hidden="true">KLE</span>' in index_html
    assert 'id="interaction-combo-row-1"' in index_html
    assert 'class="interaction-combo-key-block"' in index_html
    assert 'pickInteractionComboKey(1)' in index_html
    assert 'appendInteractionCombo()' in index_html
    assert 'id="interaction-tap-dance-name"' in index_html
    assert 'appendInteractionTapDance()' in index_html
    assert 'id="interaction-override-trigger"' in index_html
    assert 'appendInteractionKeyOverride()' in index_html
    assert 'id="interaction-tapping-term"' in index_html
    assert 'id="interaction-combo-term"' in index_html
    assert 'id="interaction-tap-dance-term"' in index_html
    assert 'id="interaction-hold-on-other-key-press"' in index_html
    assert 'applyInteractionTiming()' in index_html
    assert 'id="interaction-warning-count"' in index_html
    assert 'id="interaction-validation-preview"' in index_html
    assert 'id="interaction-reload-result"' in index_html
    assert 'validateInteractionSettings()' in index_html
    assert "insertInteractionSnippet('combo')" in index_html
    assert "insertInteractionSnippet('conditional')" in index_html
    assert 'saveInteractionSettings(true)' in index_html
    assert 'fetchInteractionSettings()' in index_html
    keyboard_js = (ROOT / "daemon/http/static/keyboard.js").read_text(encoding="utf-8")
    assert 'function showShutdownConfirm()' in keyboard_js
    assert 'function hideShutdownConfirm()' in keyboard_js
    assert 'async function shutdownSystemFromOverlay()' in keyboard_js
    assert 'window.PointerEvent' in keyboard_js
    assert 'pointercancel' in keyboard_js
    assert 'function isMouseButtonElement(el)' in keyboard_js
    assert '/^(?:KC|MS)_BTN[1-5]$/' in keyboard_js
    assert 'if (isMouseButtonKey()) return;\n      releasePointer(e);' in keyboard_js
    assert 'if (isMouseButtonKey()) return;\n    releaseKey();' in keyboard_js
    assert 'csrfFetch("/api/system/shutdown", { method: "POST" })' in keyboard_js
    assert 'id="system-status"' in index_html
    assert 'class="sysstat-row"' in index_html
    assert 'data-service="hidd"' in index_html
    assert 'id="stat-hidd"' in index_html
    assert 'data-service="usbd"' not in index_html
    assert 'id="stat-bluetooth"' in index_html
    assert 'id="stat-bt-power"' in index_html
    assert 'id="stat-bt-pairing"' in index_html
    assert 'id="stat-bt-connected"' in index_html
    assert 'id="bt-pair-on-btn"' in index_html
    assert 'id="bt-forget-btn"' in index_html
    assert 'setBluetoothPairing' in index_html
    assert 'forgetBluetoothDevices' in index_html
    assert 'class="bt-step-label">Power' in index_html
    assert 'class="bt-step-label">Pair' in index_html
    assert 'class="bt-step-label">Conn' in index_html
    assert 'id="lighting-mode" type="hidden"' in index_html
    assert 'id="lighting-current-effect"' in index_html
    assert 'id="lighting-effect-groups"' in index_html
    assert 'class="lighting-side-controls"' in index_html
    assert 'id="lighting-brightness-number"' in index_html
    assert 'id="lighting-speed-number"' in index_html
    assert 'id="lighting-hue-number"' in index_html
    assert 'id="lighting-saturation-number"' in index_html
    assert 'id="lighting-color-presets"' in index_html
    assert 'id="keyboard-layer-sel"' in index_html
    assert 'setKeyboardDisplayLayer(this.value)' in index_html
    assert 'id="keyboard-layer-status"' in index_html
    assert 'class="keyboard-layer-legend"' in index_html
    assert 'id="matrix-coords-toggle"' in index_html
    assert 'setKeyboardMatrixCoordsEnabled(!keyboardMatrixCoordsEnabled)' in index_html
    assert 'id="keyboard-fit-toggle"' in index_html
    assert 'setKeyboardFitEnabled(!keyboardFitEnabled)' in index_html
    assert 'id="touch-flick-toggle"' in index_html
    assert 'setTouchFlickPreviewEnabled(!touchFlickPreviewEnabled)' in index_html
    assert 'id="touch-flick-send-toggle"' in index_html
    assert 'setTouchFlickSendEnabled(!touchFlickSendEnabled)' in index_html
    assert 'id="touch-flick-panel"' in index_html
    assert 'data-profile-guard="osoyoo-4.3"' in index_html
    assert 'id="touch-flick-ime-controls"' in index_html
    assert 'id="touch-flick-preview"' in index_html
    assert "resolveTouchFlickPreviewAction" in keyboard_js
    assert "resolveTouchFlickImePreviewAction" in keyboard_js
    assert 'id="overlay-flick-btn"' in index_html
    assert 'id="overlay-flick-send-btn"' in index_html
    assert 'id="overlay-shutdown-btn"' in index_html
    assert 'showShutdownConfirm()' in index_html
    assert 'id="overlay-shutdown-confirm"' in index_html
    assert 'id="overlay-shutdown-confirm-btn"' in index_html
    assert 'Shutdown now' in index_html
    assert 'shutdownSystemFromOverlay()' in index_html
    assert 'onclick="toggleMatrixTester()"' in index_html
    assert 'id="keyboard-stage"' in index_html
    assert 'id="settings-panel"' in index_html
    assert 'saveHttpAuthPassword(event)' in index_html
    assert 'id="settings-current-password"' in index_html
    assert 'id="settings-new-password"' in index_html
    assert 'id="settings-confirm-password"' in index_html
    assert 'saveSendStrings(event)' in index_html
    assert 'id="settings-send-strings-rows"' in index_html
    assert 'addSendStringRow()' in index_html
    assert 'id="settings-send-strings"' in index_html
    assert 'id="settings-send-strings-validation"' in index_html
    assert 'id="settings-send-strings-plan-action"' in index_html
    assert 'previewSendStringPlan()' in index_html
    assert 'id="settings-send-strings-plan-preview"' in index_html
    assert '/static/csrf.js' in index_html
    assert '/static/settings_panel.js' in index_html
    assert index_html.index('/static/csrf.js') < index_html.index('/static/scripts_panel.js')
    assert '/static/remap_key_groups.js' in index_html
    assert index_html.index('/static/remap_key_groups.js') < index_html.index('/static/remap_panel.js')
    assert '/static/remap_kle.js' in index_html
    assert index_html.index('/static/remap_panel.js') < index_html.index('/static/remap_kle.js')
    assert '/static/remap_vil.js' in index_html
    assert index_html.index('/static/remap_panel.js') < index_html.index('/static/remap_vil.js')
    assert '<select id="lighting-mode">' not in index_html

    httpd_py = (ROOT / "daemon/http/httpd.py").read_text(encoding="utf-8")
    assert 'app.router.add_post("/api/system/shutdown", handle_system_shutdown)' in httpd_py
    assert 'app.router.add_post("/api/keymap/layer-lock/clear", handle_keymap_layer_lock_clear)' in httpd_py
    assert 'app.router.add_get("/api/interaction/runtime-status", handle_interaction_runtime_status)' in httpd_py
    assert "HTTPD_SYSTEM_SHUTDOWN_COMMAND" in httpd_py

    keyboard_css = (ROOT / "daemon/http/static/keyboard.css").read_text(encoding="utf-8")
    assert "touch-action: none;" in keyboard_css

    tabs_js = (ROOT / "daemon/http/static/tabs.js").read_text(encoding="utf-8")
    assert '"interaction"' in tabs_js
    assert '"settings"' in tabs_js
    assert 'fetchSettings()' in tabs_js
    assert 'fetchInteractionSettings()' in tabs_js
    assert 'const fetchOnActivate = options.fetch !== false' in tabs_js
    assert 'INTERACTION_TAB_HASHES' in tabs_js
    assert '"interaction-raw"' in tabs_js
    assert '"interaction-morse"' in tabs_js
    assert '"interaction-builders"' in tabs_js
    assert 'function appTabFromHash' in tabs_js
    assert 'window.addEventListener("hashchange"' in tabs_js
    assert 'cancelTouchFlickPreview("tab_switch")' in tabs_js

    interaction_js = (ROOT / "daemon/http/static/interaction_panel.js").read_text(encoding="utf-8")
    assert 'PUT' in interaction_js
    assert '/api/interaction' in interaction_js
    assert 'insertInteractionAction' in interaction_js
    assert 'insertInteractionSnippet' in interaction_js
    assert 'renderInteractionWarnings' in interaction_js
    assert 'renderInteractionReloadResult' in interaction_js
    assert 'validateInteractionSettings' in interaction_js
    assert 'renderInteractionValidationPreview' in interaction_js
    assert '/api/interaction/validate' in interaction_js
    interaction_api = (ROOT / "daemon/http/interaction_api.py").read_text(encoding="utf-8")
    assert "interaction.status_connections.v1" in interaction_api
    assert "save_payload_includes_runtime_state" in interaction_api
    assert "runtime_feedback_or_real_device_touch_flick" in interaction_api
    assert '"/api/interaction/runtime-status"' in interaction_api
    assert '{"t": "INTERACTION_STATUS"}' in interaction_api
    builder_ux = (ROOT / "daemon/http/interaction_builder_ux.py").read_text(encoding="utf-8")
    assert "interaction.builder_ux.polish.v1" in builder_ux
    assert "first_slice_complete" in builder_ux
    assert "runtime_feedback_or_real_device_touch_flick" in builder_ux
    assert 'appendInteractionCombo' in interaction_js
    assert 'collectInteractionComboKeys' in interaction_js
    assert 'settings.combos.push({ keys, action })' in interaction_js
    assert 'pickInteractionComboKey' in interaction_js
    assert 'handleInteractionComboKeyPick' in interaction_js
    assert 'setActiveTab("interaction", { fetch: false })' in interaction_js
    assert 'appendInteractionTapDance' in interaction_js
    assert 'collectInteractionTapDanceActions' in interaction_js
    assert 'settings.tap_dances[name] = actions' in interaction_js
    assert 'appendInteractionKeyOverride' in interaction_js
    assert 'parseOverrideTrigger' in interaction_js
    assert 'settings.key_overrides.push(nextOverride)' in interaction_js
    assert 'interaction-action-buttons' in interaction_js
    assert 'fetchInteractionLayoutActions' in interaction_js
    assert 'interaction-keycode-picker' in interaction_js
    assert 'insertSelectedInteractionAction' in interaction_js
    assert "payload.polish_status" in interaction_js
    assert "scope: ${polish[builderKey].editor_scope}" in interaction_js
    assert "polish?.warning_display?.dedupe_rule" in interaction_js
    assert 'focusedInteractionActionInput' in interaction_js
    assert 'openInteractionActionPicker' in interaction_js
    assert 'window.openRemapChoicePicker' in interaction_js
    assert 'const remapPicker' in interaction_js
    assert 'ensureInteractionActionInputTools' in interaction_js
    assert 'interaction-action-input-tools' in interaction_js
    assert 'interactionActionInputHelp' in interaction_js
    assert 'interaction-action-input-help' in interaction_js
    assert 'Tap Dance stores actions in TD(name)' in interaction_js
    assert 'Trigger accepts one or more action names' in interaction_js
    assert 'Combo sources use row/col blocks' in interaction_js
    assert 'interactionSummaryButton("Edit"' in interaction_js
    assert 'interactionSummaryButton("Copy TD"' in interaction_js
    assert 'copyInteractionActionToClipboard(`TD(${name})`)' in interaction_js
    assert 'window.__interactionCopyTextForTest' in interaction_js
    assert 'window.navigator.clipboard.writeText(text)' in interaction_js
    assert 'loadInteractionComboIntoBuilder' in interaction_js
    assert 'loadInteractionTapDanceIntoBuilder' in interaction_js
    assert 'loadInteractionKeyOverrideIntoBuilder' in interaction_js
    assert 'let _interactionEditingComboIndex = null' in interaction_js
    assert 'let _interactionEditingTapDanceIndex = null' in interaction_js
    assert 'let _interactionEditingOverrideIndex = null' in interaction_js
    assert 'settings.combos[_interactionEditingComboIndex] = { keys, action }' in interaction_js
    assert 'tapDanceEntries[_interactionEditingTapDanceIndex] = [name, actions]' in interaction_js
    assert 'Tap Dance ${name} は既に存在します' in interaction_js
    assert 'settings.key_overrides[_interactionEditingOverrideIndex] = nextOverride' in interaction_js
    assert 'function adjustedInteractionEditIndex' in interaction_js
    assert 'function adjustedInteractionEditIndexAfterRemove' in interaction_js
    assert '_interactionEditingComboIndex = adjustedInteractionEditIndex(_interactionEditingComboIndex, index, delta, combos.length)' in interaction_js
    assert '_interactionEditingTapDanceIndex = adjustedInteractionEditIndex(_interactionEditingTapDanceIndex, index, delta, tapDanceEntries.length)' in interaction_js
    assert '_interactionEditingOverrideIndex = adjustedInteractionEditIndexAfterRemove(_interactionEditingOverrideIndex, index)' in interaction_js
    assert 'focusInteractionBuilder(".interaction-tap-dance-builder", "interaction-tap-dance-name")' in interaction_js
    assert 'override.trigger.join(", ")' in interaction_js
    assert 'previewInteractionTextSendPlanForInput' in interaction_js
    assert 'csrfFetch : fetch' in interaction_js
    assert '"/api/interaction/text-send-safety/plan"' in interaction_js
    assert 'body: JSON.stringify({ action })' in interaction_js
    assert 'window.previewInteractionTextSendPlanForInput' in interaction_js
    assert 'let _interactionRuntimeStatus = null' in interaction_js
    assert 'fetch("/api/interaction/runtime-status")' in interaction_js
    assert 'await refreshInteractionRuntimeStatus()' in interaction_js
    assert 'capsRuntime.active ? "active" : "inactive"' in interaction_js
    assert 'repeatRuntime.history_available ? "ready" : "-"' in interaction_js
    assert 'runtimeStatus && runtimeStatus.key_lock ? runtimeStatus.key_lock : null' in interaction_js
    assert 'appendInteractionSummaryMetric(metrics, "Key Lock"' in interaction_js
    assert 'Action を選択しました' in interaction_js
    assert 'interaction-action-picker-dialog' in interaction_js
    assert 'interactionActionLabel' in interaction_js
    assert 'ensureInteractionGuiLayout' in interaction_js
    assert 'setInteractionEditorMode' in interaction_js
    assert 'hidloom-interaction-editor-mode' in interaction_js
    assert 'hidloom-interaction-accordion-open' in interaction_js
    assert 'interactionHashAccordionId' in interaction_js
    assert '"interaction-raw": "interaction-raw-accordion"' in interaction_js
    assert '"interaction-morse": "interaction-morse-accordion"' in interaction_js
    assert '"interaction-builders": "interaction-builders-accordion"' in interaction_js
    assert 'window.addEventListener("hashchange", applyInteractionAccordionState)' in interaction_js
    assert 'renderInteractionTimingControls' in interaction_js
    assert 'applyInteractionTiming' in interaction_js
    assert 'interaction-hold-on-other-key-press' in interaction_js
    assert 'let _interactionSavedText = ""' in interaction_js
    assert 'let _interactionValidatedText = ""' in interaction_js
    assert 'function interactionEditorIsDirty' in interaction_js
    assert 'function setInteractionSavedTextFromEditor' in interaction_js
    assert 'function setInteractionValidatedTextFromEditor' in interaction_js
    assert 'function interactionValidationIsStale' in interaction_js
    assert 'function markInteractionEditorChanged' in interaction_js
    assert '_interactionInspector = null' in interaction_js
    assert '_interactionConditionalInspector = null' in interaction_js
    assert 'renderInteractionValidationPreview(null)' in interaction_js
    assert 'renderInteractionReloadResult(null)' in interaction_js
    assert 'function warnBeforeLeavingInteractionEditor' in interaction_js
    assert 'window.addEventListener("beforeunload", warnBeforeLeavingInteractionEditor)' in interaction_js
    assert 'interaction-status-dirty' in interaction_js
    assert 'interaction-status-validation-stale' in interaction_js
    assert 'Unsaved' in interaction_js
    assert 'Saved' in interaction_js
    assert 'Needs check' in interaction_js
    assert 'Checked' in interaction_js
    assert 'renderInteractionRuntimeSummary' in interaction_js
    assert 'refreshInteractionRuntimeSummary' in interaction_js
    assert 'fetch("/api/keymap/active")' in interaction_js
    assert 'fetch("/api/interaction/conditional-layers/inspector")' in interaction_js
    assert 'refreshInteractionConditionalInspector' in interaction_js
    assert 'renderInteractionConditionalInspectorRows' in interaction_js
    assert 'Conditional Inspector' in interaction_js
    assert 'interaction-conditional-inspector-rows' in interaction_js
    assert 'const conditionalRuntimeFresh = !interactionEditorIsDirty()' in interaction_js
    assert '"pending-save"' in interaction_js
    assert 'conditional: \'{\\n  "name": "lower_raise_adjust"' in interaction_js
    assert 'function parseConditionalLayerList' in interaction_js
    assert 'function collectInteractionConditionalLayerRule' in interaction_js
    assert 'function addInteractionConditionalLayer' in interaction_js
    assert 'function removeInteractionConditionalLayer' in interaction_js
    assert 'function renderInteractionConditionalLayerEditor' in interaction_js
    assert 'interaction-conditional-editor' in interaction_js
    assert 'interaction-conditional-name' in interaction_js
    assert 'interaction-conditional-if-all' in interaction_js
    assert 'interaction-conditional-then' in interaction_js
    assert 'settings.conditional_layers.push(nextRule)' in interaction_js
    assert 'renderInteractionSummarySection(panel, "Conditional Layers"' in interaction_js
    assert 'remove: (index) => removeInteractionConditionalLayer(settings, index)' in interaction_js
    assert 'markInteractionEditorChanged();' in interaction_js
    assert 'window.addInteractionConditionalLayer = addInteractionConditionalLayer' in interaction_js
    assert 'fetch("/api/interaction/text-send-safety")' in interaction_js
    assert 'refreshInteractionTextSendSafety' in interaction_js
    assert 'renderInteractionTextSendWarning' in interaction_js
    assert 'Text Send preview/no-op' in interaction_js
    assert 'interactionTextSendActionsInSettings' in interaction_js
    assert 'renderInteractionTextSendEditorWarning' in interaction_js
    assert 'Text Send actions present' in interaction_js
    assert 'use Plan preview for warning / blocked reasons' in interaction_js
    assert 'interaction-text-send-editor-warning' in interaction_js
    assert 'renderInteractionTextSendPlan' in interaction_js
    assert 'Text Send plan' in interaction_js
    assert 'dryRun.available === true' in interaction_js
    assert 'taps ${Number(dryRun.sequence_count || 0)}' in interaction_js
    assert 'entry errors:' in interaction_js
    assert 'entry warnings:' in interaction_js
    assert 'appendInteractionSummaryMetric(metrics, "Text Send"' in interaction_js
    assert 'appendInteractionSummaryMetric(metrics, "Host Profile"' in interaction_js
    assert 'appendInteractionSummaryMetric(metrics, "Tap Dry Run"' in interaction_js
    assert "textSendDryRun.supported_modes.join" in interaction_js
    assert 'textSendDryRun.sends_hid_reports === false' in interaction_js
    assert 'activeConditional.join(",")' in interaction_js
    assert 'One Shot Layer' in interaction_js
    assert 'OSL ${activeOneshot.length}' in interaction_js
    assert 'activeOneshot.map((layer) => `OSL(${layer})`).join(",")' in interaction_js
    assert 'Locked Layer' in interaction_js
    assert 'Lock ${activeLocked.length}' in interaction_js
    assert 'activeLocked.map((layer) => `LL(${layer})`).join(",")' in interaction_js
    assert 'renderInteractionLayerLockUnlock(section, activeLocked)' in interaction_js
    assert 'function clearInteractionLayerLock' in interaction_js
    assert '"/api/keymap/layer-lock/clear"' in interaction_js
    assert 'Layer Lock を解除しました' in interaction_js
    assert 'Layer Lock は既に解除済みです' in interaction_js
    assert 'Unlock' in interaction_js
    assert 'fetch("/api/interaction/inspector")' in interaction_js
    assert 'fetch("/api/interaction/builder-ux")' in interaction_js
    assert 'flattenInteractionInspectorWarnings' in interaction_js
    assert 'interaction-inspector-rows' in interaction_js
    assert 'handleInteractionComboKeyPick(row, col, matrixKey)' in keyboard_js

    remap_kle_js = (ROOT / "daemon/http/static/remap_kle.js").read_text(encoding="utf-8")
    assert "openKleForCurrentLayer" in remap_kle_js
    assert "keyboard-layout-editor.com" in remap_kle_js
    assert "_cloneKleLayoutWithCurrentLayerLabels" in remap_kle_js
    assert "_kleLabelForVialEncoderSlot" in remap_kle_js
    assert 'parts[parts.length - 1] = "e"' in remap_kle_js

    remap_key_groups_js = (ROOT / "daemon/http/static/remap_key_groups.js").read_text(encoding="utf-8")
    assert "PC104_MAIN_ROWS" in remap_key_groups_js
    assert "REMAP_TAB_GROUPS" in remap_key_groups_js
    assert "OTHER_KEY_GROUPS" in remap_key_groups_js

    remap_vil_js = (ROOT / "daemon/http/static/remap_vil.js").read_text(encoding="utf-8")
    assert "exportVilLayout" in remap_vil_js
    assert "importVilLayout" in remap_vil_js
    assert "refreshRemapAfterExternalKeymapUpdate" in remap_vil_js

    keyboard_js = (ROOT / "daemon/http/static/keyboard.js").read_text(encoding="utf-8")
    matrix_js = (ROOT / "daemon/http/static/matrix_tester.js").read_text(encoding="utf-8")
    assert "_kleLayoutSource" in keyboard_js
    assert 'KEYBOARD_LAYER_DISPLAY_KEY' in keyboard_js
    assert 'fetch("/api/keymap/active")' in keyboard_js
    assert 'effectiveKeycodeForMatrix' in keyboard_js
    assert 'effectiveKeyInfoForMatrix' in keyboard_js
    assert 'encoderActions' in keyboard_js
    assert 'layer-override' in keyboard_js
    assert 'layer-fallback' in keyboard_js
    assert 'setKeyboardDisplayLayer' in keyboard_js
    assert 'startKeyboardActiveLayerPolling' in keyboard_js
    assert 'KEYBOARD_FIT_KEY' in keyboard_js
    assert 'setKeyboardFitEnabled' in keyboard_js
    assert 'updateKeyboardFitScale' in keyboard_js
    assert 'TOUCH_FLICK_PREVIEW_KEY' in keyboard_js
    assert 'TOUCH_FLICK_SEND_KEY' in keyboard_js
    assert 'touchFlickTextDispatchQueue' in keyboard_js
    assert 'touchFlickTextDispatchQueued' in keyboard_js
    assert 'function enqueueTouchFlickTextDispatch' in keyboard_js
    assert 'touchFlickTextDispatchBusy' not in keyboard_js
    assert 'fetch("/api/touch-panel/flick")' in keyboard_js
    assert 'function touchFlickDirection' in keyboard_js
    assert 'function cancelTouchFlickPreview' in keyboard_js
    assert 'function setTouchFlickPreviewEnabled' in keyboard_js
    assert 'function resolveTouchFlickDispatchEnvelope' in keyboard_js
    assert 'function touchFlickCompositionPlanRoute' in keyboard_js
    assert 'function resolveTouchFlickCompositionPlan' in keyboard_js
    assert 'function updateTouchFlickDispatchPreview' in keyboard_js
    assert '"/api/touch-panel/flick/resolve"' in keyboard_js
    assert '"/api/touch-panel/flick/dispatch"' in keyboard_js
    assert '"/api/touch-panel/flick/composition-plan"' in keyboard_js
    touch_api = (ROOT / "daemon/http/touch_panel_flick_api.py").read_text(encoding="utf-8")
    cdp_probe = (ROOT / "tools/touch_flick_cdp_probe.py").read_text(encoding="utf-8")
    assert 'TOUCH_PANEL_FLICK_COMPOSITION_PLAN_ROUTE = "/api/touch-panel/flick/composition-plan"' in touch_api
    assert "touch_panel_flick_composition_plan_response" in touch_api
    assert "touch_flick_named_text_summary" in touch_api
    assert "touch_panel.flick.named_text_summary.v1" in touch_api
    assert "touch_panel.flick.named_text_assignment.v1" in touch_api
    assert "assign_action_in_flick_json" in touch_api
    assert 'function touchFlickDispatchRoute' in keyboard_js
    assert 'function touchFlickBrowserDispatchEnabled' in keyboard_js
    assert 'function touchFlickCanEnableSend' in keyboard_js
    assert 'function touchFlickTextDispatchPreflight' in keyboard_js
    assert 'function dispatchTouchFlickEnvelopeNow' in keyboard_js
    assert 'function setTouchFlickSendEnabled' in keyboard_js
    assert "function touchFlickStatusText" in keyboard_js
    assert "named-text:${namedTextCount}" in keyboard_js
    assert 'Send flick keycode/text actions' in keyboard_js
    assert 'keycode/text actionを送信します' in keyboard_js
    assert 'panel.hidden = !touchFlickPreviewEnabled || document.body.classList.contains("keyboard-demo-mode")' in keyboard_js
    assert 'function touchFlickHostImeWarning' in keyboard_js
    assert 'local_send_disabled' in keyboard_js
    assert 'text_send_runner_busy' not in keyboard_js
    assert '"composition_plan_unavailable"' in keyboard_js
    assert 'touchFlickTextDispatchPreflight(event, envelope)' in keyboard_js
    assert "composition?.available === true" in keyboard_js
    assert 'host-profile-required' in keyboard_js
    assert 'const blockedReason = touchFlickDispatchBlockedReason(event);' in keyboard_js
    assert '"browser_dispatch_disabled"' in keyboard_js
    assert 'csrfFetch(touchFlickDispatchRoute()' in keyboard_js
    assert 'function touchFlickDispatchPayload' in keyboard_js
    assert 'delete payload.composition_plan' in keyboard_js
    assert 'delete payload.compositionPlan' in keyboard_js
    assert 'JSON.stringify(touchFlickDispatchPayload(envelope))' in keyboard_js
    assert 'csrfFetch(touchFlickCompositionPlanRoute()' in keyboard_js
    assert "composition_plan" in keyboard_js
    assert "romaji:" in keyboard_js
    assert "function touchFlickPadOutputFamily" in keyboard_js
    assert 'return "named-text"' in keyboard_js
    assert "function touchFlickPadActionTitle" in keyboard_js
    assert "action.preflight_route ? \" preflight\"" in keyboard_js
    assert "el.title = touchFlickPadActionTitle(pad)" in keyboard_js
    assert "metadata?.named_text?.entry_count" in keyboard_js
    assert "named-text:" in keyboard_js
    assert "def _js_named_preset_probe" in cdp_probe
    assert "--named-preset" in cdp_probe
    assert 'before.label === "、。？！定"' in cdp_probe
    assert 'before.previewOutput === "named-text"' in cdp_probe
    assert 'typeof _touchFlickMetadata !== "undefined" ? _touchFlickMetadata : window._touchFlickMetadata' in cdp_probe
    assert 'title.includes("named_send_string")' in cdp_probe
    assert 'preview.includes("composition_mode_requires_unicode_action")' in cdp_probe
    assert 'preview.includes("/ blocked")' in cdp_probe
    assert "--composition-dispatch-boundary" in cdp_probe
    assert "def _js_composition_dispatch_boundary_probe" in cdp_probe
    assert "touchFlickDispatchPayload(envelope)" in cdp_probe
    assert "payloadNoComposition" in cdp_probe
    assert 'pointercancel' in keyboard_js
    assert 'visibilitychange' in keyboard_js
    assert 'shutdown_menu' in keyboard_js
    assert 'KEYBOARD_MATRIX_COORDS_KEY' in keyboard_js
    assert 'keyboardMatrixCoordsEnabled' in keyboard_js
    assert 'ensureKeyMatrixCoordBadge' in keyboard_js
    assert 'updateKeyboardMatrixCoordsOverlay' in keyboard_js
    assert 'setKeyboardMatrixCoordsEnabled' in keyboard_js
    assert 'ResizeObserver' in keyboard_js
    assert '全体表示を閉じる' in keyboard_js

    interaction_css = (ROOT / "daemon/http/static/interaction_panel.css").read_text(encoding="utf-8")
    assert '.interaction-grid' in interaction_css
    assert '.interaction-mode-switch' in interaction_css
    assert '.interaction-gui-editors' in interaction_css
    assert '.interaction-mode-gui .interaction-mode-raw' in interaction_css
    assert '.interaction-mode-raw .interaction-gui-editors' in interaction_css
    assert '.interaction-accordion' in interaction_css
    assert '.interaction-accordion-badges' in interaction_css
    assert '.interaction-accordion-badge-alert' in interaction_css
    assert '.interaction-editor' in interaction_css
    assert '.interaction-action-tools' in interaction_css
    assert '.interaction-action-btn' in interaction_css
    assert '.interaction-action-picker-dialog' in interaction_css
    assert '.interaction-action-picker-key' in interaction_css
    assert '.interaction-builder-grid' in interaction_css
    assert '.interaction-builder-has-warning' in interaction_css
    assert '.interaction-builder-inline-warning' in interaction_css
    assert '.interaction-builder-subtitle' in interaction_css
    assert '.interaction-action-input-tools' in interaction_css
    assert '.interaction-action-input-tool' in interaction_css
    assert '.interaction-action-input-help' in interaction_css
    assert '.interaction-combo-grid' in interaction_css
    assert '.interaction-combo-key-block' in interaction_css
    assert '.interaction-combo-key-label' in interaction_css
    assert '.interaction-combo-pick-btn' in interaction_css
    assert '.interaction-picker-row' in interaction_css
    assert '.interaction-check-field' in interaction_css
    assert '.interaction-timing-grid' in interaction_css
    assert '.interaction-warning-count' in interaction_css
    assert '.interaction-warning-row' in interaction_css
    assert '.interaction-status-dirty' in interaction_css
    assert '.interaction-status-validation-stale' in interaction_css
    assert '.interaction-summary-metrics' in interaction_css
    assert '.interaction-summary-metric' in interaction_css
    assert '.interaction-validation-hint' in interaction_css
    assert '.interaction-validation-hint-blocked' in interaction_css
    assert '.interaction-inspector-row' in interaction_css

    interaction_js = (ROOT / "daemon/http/static/interaction_panel.js").read_text(encoding="utf-8")
    assert 'function updateInteractionAccordionHeaders' in interaction_js
    assert 'function interactionValidationSummary' in interaction_js
    assert 'function interactionSaveHintLabel' in interaction_js
    assert 'INTERACTION_BUILDER_WARNING_TARGETS' in interaction_js
    assert 'INTERACTION_BUILDER_UX_TARGETS' in interaction_js
    assert 'function renderInteractionBuilderInlineWarnings' in interaction_js
    assert 'function renderInteractionBuilderUx' in interaction_js
    assert 'metadata.canonical_aliases ? Object.keys(metadata.canonical_aliases)' in interaction_js
    assert 'metadata.canonical_aliases ? Object.values(metadata.canonical_aliases)' in interaction_js
    assert 'interaction-builder-subtitle' in interaction_js
    assert 'interaction-builder-inline-warning' in interaction_js
    assert 'interaction-accordion-badge' in interaction_js
    assert 'JSON error' in interaction_js
    assert 'Caps ${interactionEnabledLabel(caps.enabled)}' in interaction_js
    assert 'Repeat ${interactionListLength(repeat.alternate_pairs)}' in interaction_js
    assert 'Cond ${conditional.length}' in interaction_js
    assert 'interactionSummaryButton("Add Conditional", addInteractionConditionalLayer)' in interaction_js
    assert 'Combo ${combos}' in interaction_js
    assert 'Save ${saveHint}' in interaction_js
    assert 'appendInteractionSummaryMetric(metrics, "Save check", saveHint)' in interaction_js
    assert 'interaction-validation-hint-${saveHint}' in interaction_js
    assert 'Warn ${warnings}' in interaction_js
    assert 'window.updateInteractionAccordionHeaders' in interaction_js

    morse_js = (ROOT / "daemon/http/static/morse_inspector_panel.js").read_text(encoding="utf-8")
    assert 'interaction-morse-accordion' in morse_js
    assert 'window.updateInteractionAccordionHeaders' in morse_js
    assert 'window.bindInteractionAccordionState' in morse_js
    assert 'window.applyInteractionAccordionState' in morse_js

    keyboard_css = (ROOT / "daemon/http/static/keyboard.css").read_text(encoding="utf-8")
    assert ".repo-title-link" in keyboard_css
    assert ".settings-card" in keyboard_css
    assert ".settings-field" in keyboard_css
    assert "#system-status" in keyboard_css
    assert ".sysstat-row" in keyboard_css
    assert "#system-status.simple .status" in keyboard_css
    assert ".bt-indicators" in keyboard_css
    assert ".bt-actions" in keyboard_css
    assert ".bt-action-btn" in keyboard_css
    assert ".bt-forget-btn" in keyboard_css
    assert ".bt-step-label" in keyboard_css
    assert "#system-status.simple .bt-step-label" in keyboard_css
    assert ".bt-step.pairing" in keyboard_css
    assert ".bt-step.connected" in keyboard_css
    assert "#log-panel" in keyboard_css
    assert "#scripts-panel" in keyboard_css
    assert ".script-content" in keyboard_css
    assert "min-height: 560px" in keyboard_css
    assert ".joystick-control::before" in keyboard_css
    assert "clip-path: polygon(50% 0, 100% 50%, 50% 100%, 0 50%)" in keyboard_css
    assert ".joystick-control::after" in keyboard_css
    assert 'content: "✥"' not in keyboard_css
    assert ".encoder-control::before" in keyboard_css
    assert "repeating-conic-gradient" in keyboard_css
    assert ".key.encoder-key.control-label" in keyboard_css
    assert "border-radius: 50%" in keyboard_css
    assert ".kle-open-icon" in keyboard_css
    assert ".touch-flick-panel" in keyboard_css
    assert ".touch-flick-grid" in keyboard_css
    assert ".touch-flick-pad" in keyboard_css
    assert '.touch-flick-pad[data-preview-output="text"]::after' in keyboard_css
    assert '.touch-flick-pad[data-preview-output="named-text"]::after' in keyboard_css
    assert ".touch-flick-ime-controls" in keyboard_css
    assert ".touch-flick-ime-control" in keyboard_css
    assert ".touch-flick-preview" in keyboard_css
    assert "touch-flick-preview-mode" in keyboard_js
    assert "body.keyboard-demo-mode.touch-flick-preview-mode #keyboard-stage" not in keyboard_css
    assert "grid-template-rows: auto minmax(0, 1fr) auto auto" in keyboard_css
    assert "@media (max-width: 820px) and (max-height: 520px)" in keyboard_css
    assert "grid-template-columns: repeat(6, minmax(0, 1fr))" in keyboard_css
    assert "text-overflow: ellipsis" in keyboard_css
    assert "white-space: nowrap" in keyboard_css
    assert "#remap-popup" in keyboard_css
    assert "position: fixed" in keyboard_css
    assert ".remap-popup-content" in keyboard_css
    assert "height: min(560px, calc(100vh - 28px))" in keyboard_css
    assert "overflow: hidden" in keyboard_css
    assert ".remap-tab-pane" in keyboard_css
    assert "overflow: auto" in keyboard_css
    assert ".remap-key-row" in keyboard_css
    assert ".remap-key.current" in keyboard_css
    assert "#remap-toast" in keyboard_css

    status_js = (ROOT / "daemon/http/static/status_panel.js").read_text(encoding="utf-8")
    assert "status-dot connected" in status_js
    assert "status-dot disconnected" in status_js
    assert "updateBluetoothIndicators" in status_js
    assert "stat-bt-power" in status_js
    assert "/api/bluetooth/pairing" in status_js
    assert "/api/bluetooth/forget" in status_js
    assert "/api/bluetooth/hosts/" in status_js
    assert "renameBluetoothHost" in status_js
    assert "display_name_source" in status_js
    assert "setBluetoothPairing" in status_js
    assert "forgetBluetoothDevices" in status_js
    status_css = (ROOT / "daemon/http/static/status_panel.css").read_text(encoding="utf-8")
    assert ".bt-host-rename" in status_css
    assert "closeLogPanelOnOutsidePointer" in status_js
    assert 'document.addEventListener("pointerdown", closeLogPanelOnOutsidePointer)' in status_js
    assert 'panel.contains(event.target)' in status_js

    settings_js = (ROOT / "daemon/http/static/settings_panel.js").read_text(encoding="utf-8")
    assert "/api/settings" in settings_js
    assert "/api/settings/http-auth" in settings_js
    assert "saveHttpAuthPassword" in settings_js
    assert "current_password" in settings_js
    assert "new_password" in settings_js
    assert "confirm_password" in settings_js
    assert 'csrfFetch("/api/settings/http-auth"' in settings_js
    assert "saveSendStrings" in settings_js
    assert "parseSendStringsEditor" in settings_js
    assert "renderSendStringRows" in settings_js
    assert "collectSendStringRows" in settings_js
    assert "syncSendStringRowsToEditor" in settings_js
    assert "normalizedSendStringEntry" in settings_js
    assert "previewSendStringRowPlan" in settings_js
    assert "copySendStringRowAction" in settings_js
    assert "navigator.clipboard.writeText(action)" in settings_js
    assert 'csrfFetch("/api/settings/send-strings"' in settings_js
    assert "renderSendStringsValidation" in settings_js
    assert "previewSendStringPlan" in settings_js
    assert 'csrfFetch("/api/interaction/text-send-safety/plan"' in settings_js
    assert "const plan = data.plan || {}" in settings_js
    assert "const dry = plan.tap_dry_run || {}" in settings_js
    assert "dry.sequence_count" in settings_js
    assert "Plan ready" in settings_js
    assert ".settings-send-string-row" in keyboard_css
    assert ".settings-send-strings-empty" in keyboard_css
    assert ".settings-json-editor" in keyboard_css
    assert ".settings-validation-preview" in keyboard_css

    csrf_js = (ROOT / "daemon/http/static/csrf.js").read_text(encoding="utf-8")
    assert "function csrfToken" in csrf_js
    assert "function csrfFetch" in csrf_js
    assert "X-HIDLOOM-CSRF" in csrf_js
    assert "function csrfWebSocketUrl" in csrf_js

    httpd_py = (ROOT / "daemon/http/httpd.py").read_text(encoding="utf-8")
    assert "handle_keymap_active" in httpd_py
    assert '"/api/keymap/active"' in httpd_py
    assert '"/api/bluetooth/hosts/{address}/rename"' in httpd_py
    assert '"/api/bluetooth/hosts/{address}/forget"' in httpd_py
    assert "bluetooth_host_rename_response" in httpd_py
    assert "bluetooth_host_forget_response" in httpd_py
    assert "handle_settings_http_auth" in httpd_py
    assert '"/api/settings/http-auth"' in httpd_py
    assert "handle_settings_send_strings" in httpd_py
    assert '"/api/settings/send-strings"' in httpd_py
    assert "csrf_middleware" in httpd_py

    lighting_js = (ROOT / "daemon/http/static/lighting_panel.js").read_text(encoding="utf-8")
    lighting_css = (ROOT / "daemon/http/static/lighting_panel.css").read_text(encoding="utf-8")
    assert "_renderLightingEffectButtons" in lighting_js
    assert "lighting-effect-btn" in lighting_js
    assert "effect_categories" in lighting_js
    assert "lighting-current-effect" in lighting_js
    assert "LIGHTING_COLOR_PRESETS" in lighting_js
    assert "_renderLightingColorPresets" in lighting_js
    assert "_setHsFromColor" in lighting_js
    assert "lighting-modifier-trigger-effects" in lighting_js
    assert "saveLightingReactiveSettings" in lighting_js
    assert "modifier_triggers_effects" in lighting_js
    assert "lighting-lock-toolbar" in lighting_js

    assert ".lighting-effect-groups" in keyboard_css
    assert ".lighting-side-controls" in keyboard_css
    assert ".lighting-effect-button-grid" in keyboard_css
    assert ".lighting-effect-btn.active" in keyboard_css
    assert ".lighting-range-row" in keyboard_css
    assert ".lighting-number" in keyboard_css
    assert ".lighting-color-presets" in keyboard_css
    assert ".lighting-color-preset" in keyboard_css
    assert ".lighting-reactive-panel" in lighting_css
    assert ".lighting-lock-toolbar" in lighting_css
    assert ".keyboard-layer-label" in keyboard_css
    assert ".keyboard-layer-status" in keyboard_css
    assert ".keyboard-layer-legend" in keyboard_css
    assert ".key-matrix-coord" in keyboard_css
    assert ".interaction-combo-pick-mode .key[data-matrix-row]" in keyboard_css
    assert "#keyboard-container.show-matrix-coords .key.remap-mode .key-matrix-coord" in keyboard_css
    assert ".key.layer-override" in keyboard_css
    assert ".key.layer-fallback" in keyboard_css
    assert ".layer-swatch-fallback" in keyboard_css
    assert "#keyboard-stage" in keyboard_css
    assert ".keyboard-fit-enabled" in keyboard_css
    assert "body.keyboard-demo-mode #keyboard-tab-toolbar" in keyboard_css
    assert "body.keyboard-demo-mode #keyboard-fit-toggle" not in keyboard_css
    assert 'body.keyboard-demo-mode #keyboard-tab-toolbar > :not(#keyboard-fit-toggle)' not in keyboard_css
    assert "transform-origin: top left" in keyboard_css
    assert "window.isMatrixTesterEnabled" in keyboard_js
    assert "syncMatrixTesterWithKeyboardFit" not in keyboard_js
    assert "_keyboardFitPreviousMatrixTesterEnabled" not in keyboard_js
    assert "window.setMatrixTesterEnabled = setMatrixTesterEnabled" in matrix_js
    assert "window.isMatrixTesterEnabled = isMatrixTesterEnabled" in matrix_js
    assert "window.toggleMatrixTester = toggleMatrixTester" in matrix_js
    assert 'new WebSocket(csrfWebSocketUrl("/ws"))' in matrix_js
    assert 'ws.send(`${type === "keydown" ? "P" : "R"}' in matrix_js
    assert "cache_control_middleware" in httpd_py
    assert 'request.path == "/" or request.path.startswith("/static/")' in httpd_py
    assert '"Cache-Control"] = "no-cache, max-age=0, must-revalidate"' in httpd_py

    mutating_api_expectations = [
        ("daemon/http/static/layer_controls.js", "csrfFetch(url"),
        ("daemon/http/static/interaction_panel.js", 'csrfFetch("/api/interaction/validate"'),
        ("daemon/http/static/interaction_panel.js", 'csrfFetch("/api/interaction"'),
        ("daemon/http/static/status_panel.js", 'csrfFetch("/api/bluetooth/pairing"'),
        ("daemon/http/static/status_panel.js", 'csrfFetch("/api/bluetooth/forget"'),
        ("daemon/http/static/lighting_panel.js", 'csrfFetch("/api/lighting"'),
        ("daemon/http/static/remap_panel.js", 'csrfFetch("/api/keymap"'),
        ("daemon/http/static/remap_panel.js", 'csrfFetch("/api/keymap/reset"'),
        ("daemon/http/static/remap_vil.js", 'csrfFetch("/api/vil/import"'),
        ("daemon/http/static/script_editor.js", "csrfFetch(`/api/scripts/${encodeURIComponent(keycode)}`"),
        ("daemon/http/static/script_editor.js", "csrfFetch(`/api/scripts/${encodeURIComponent(keycode)}/check-run`"),
        ("daemon/http/static/script_editor.js", "csrfFetch(`/api/scripts/${encodeURIComponent(keycode)}/run`"),
        ("daemon/http/static/script_editor.js", "csrfFetch(`/api/scripts/${encodeURIComponent(keycode)}/reset`"),
        ("daemon/http/static/settings_panel.js", 'csrfFetch("/api/settings/http-auth"'),
    ]
    for path, needle in mutating_api_expectations:
        assert needle in (ROOT / path).read_text(encoding="utf-8")

    print("ok: interaction UI assets wired")


if __name__ == "__main__":
    main()
