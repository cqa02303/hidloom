"use strict";

// UI-only wiring for the temporary real-LED role preview route.
// This file is safe to load before the route is connected: HTTP errors are shown
// in the Lighting panel and normal Lighting controls remain usable.

let _lightingRolePreviewRestoreState = null;

function setLightingRolePreviewStatus(text, isError = false) {
  const note = document.getElementById("lighting-role-preview-note");
  if (!note) return;
  note.textContent = text;
  note.classList.toggle("error", isError);
}

function ensureLightingRolePreviewControls() {
  const panel = document.getElementById("lighting-role-preview-panel");
  if (!panel || document.getElementById("lighting-role-preview-actions")) return;
  const actions = document.createElement("div");
  actions.id = "lighting-role-preview-actions";
  actions.className = "lighting-role-preview-actions";

  const preview = document.createElement("button");
  preview.type = "button";
  preview.className = "lighting-btn";
  preview.textContent = "Preview roles";
  preview.addEventListener("click", previewLightingRoles);

  const restore = document.createElement("button");
  restore.type = "button";
  restore.id = "lighting-role-preview-restore";
  restore.className = "lighting-btn";
  restore.textContent = "Restore effect";
  restore.disabled = true;
  restore.addEventListener("click", restoreLightingRolePreview);

  actions.appendChild(preview);
  actions.appendChild(restore);
  panel.appendChild(actions);
}

function setLightingRolePreviewRestoreEnabled(enabled) {
  const restore = document.getElementById("lighting-role-preview-restore");
  if (restore) restore.disabled = !enabled;
}

async function previewLightingRoles() {
  ensureLightingRolePreviewControls();
  setLightingRolePreviewStatus("preview送信中");
  try {
    const brightness = Number(document.getElementById("lighting-brightness")?.value || 96);
    const resp = await csrfFetch("/api/lighting/role-preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "preview", brightness }),
    });
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") {
      setLightingRolePreviewStatus(data.msg || `HTTP ${resp.status}`, true);
      return;
    }
    _lightingRolePreviewRestoreState = data.restore_state || null;
    setLightingRolePreviewRestoreEnabled(Boolean(_lightingRolePreviewRestoreState));
    setLightingRolePreviewStatus(`preview中 (${data.count ?? "?"} LEDs)`);
  } catch (e) {
    setLightingRolePreviewStatus(e.message, true);
  }
}

async function restoreLightingRolePreview() {
  if (!_lightingRolePreviewRestoreState) {
    setLightingRolePreviewStatus("restore state がありません", true);
    return;
  }
  setLightingRolePreviewStatus("restore送信中");
  try {
    const resp = await csrfFetch("/api/lighting/role-preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "restore", state: _lightingRolePreviewRestoreState }),
    });
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") {
      setLightingRolePreviewStatus(data.msg || `HTTP ${resp.status}`, true);
      return;
    }
    _lightingRolePreviewRestoreState = null;
    setLightingRolePreviewRestoreEnabled(false);
    if (typeof updateLightingUI === "function") updateLightingUI(data.state || {});
    setLightingRolePreviewStatus("effect復帰済み");
  } catch (e) {
    setLightingRolePreviewStatus(e.message, true);
  }
}

function initLightingRolePreviewControls() {
  ensureLightingRolePreviewControls();
}

window.previewLightingRoles = previewLightingRoles;
window.restoreLightingRolePreview = restoreLightingRolePreview;
window.initLightingRolePreviewControls = initLightingRolePreviewControls;

document.addEventListener("DOMContentLoaded", initLightingRolePreviewControls);
