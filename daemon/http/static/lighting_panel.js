"use strict";

let _lightingState = { mode: 2, speed: 128, h: 0, s: 0, v: 128 };
let _lightingEffectsLoaded = false;
let _lightingEffects = [];
let _lightingEffectCategories = [];
let _lightingLockIndicators = null;
let _lightingLayerOverlays = null;
let _lightingLockKeyTarget = null;
let _lightingLockLedTarget = null;
let _lightingLockColorPopoverBound = false;
const LIGHTING_COLOR_PRESETS = [
  "#ffffff", "#bbbbff", "#ffb3c7", "#ff4d4d", "#ff9500", "#ffe45c",
  "#8ee000", "#00d46a", "#00c8ff", "#2b6fff", "#8f5cff", "#ff5cff",
  "#101820", "#7f8c8d", "#c0c7d1", "#6d3bff", "#00fff0", "#ff2e88",
];
const LIGHTING_ROLE_ORDER = ["normal", "modifier", "function", "layer", "lock", "script", "system"];
const LIGHTING_LOCK_STATES = [
  ["caps_lock", "Caps"],
  ["num_lock", "Num"],
  ["scroll_lock", "Scroll"],
  ["compose", "Compose"],
  ["kana", "Kana"],
];
const LIGHTING_LAYER_RANGE = [1, 2, 3, 4, 5, 6, 7];
const LIGHTING_LAYER_BLEND_MODES = ["replace", "max", "add", "alpha"];

function _lightingEl(id) {
  return document.getElementById(id);
}

function setLightingStatus(text, isError = false) {
  const el = _lightingEl("lighting-status");
  if (!el) return;
  el.textContent = text;
  el.classList.toggle("error", isError);
}

function hsvToRgb(h, s, v) {
  const hf = (Number(h) || 0) / 255 * 360;
  const sf = (Number(s) || 0) / 255;
  const vf = (Number(v) || 0) / 255;
  const c = vf * sf;
  const x = c * (1 - Math.abs((hf / 60) % 2 - 1));
  const m = vf - c;
  let r = 0, g = 0, b = 0;
  if (hf < 60) [r, g, b] = [c, x, 0];
  else if (hf < 120) [r, g, b] = [x, c, 0];
  else if (hf < 180) [r, g, b] = [0, c, x];
  else if (hf < 240) [r, g, b] = [0, x, c];
  else if (hf < 300) [r, g, b] = [x, 0, c];
  else [r, g, b] = [c, 0, x];
  return [
    Math.round((r + m) * 255),
    Math.round((g + m) * 255),
    Math.round((b + m) * 255),
  ];
}

function rgbToHsv(r, g, b) {
  const rf = r / 255, gf = g / 255, bf = b / 255;
  const max = Math.max(rf, gf, bf);
  const min = Math.min(rf, gf, bf);
  const d = max - min;
  let h = 0;
  if (d !== 0) {
    if (max === rf) h = 60 * (((gf - bf) / d) % 6);
    else if (max === gf) h = 60 * (((bf - rf) / d) + 2);
    else h = 60 * (((rf - gf) / d) + 4);
  }
  if (h < 0) h += 360;
  const s = max === 0 ? 0 : d / max;
  return [Math.round(h / 360 * 255), Math.round(s * 255), Math.round(max * 255)];
}

function _clampU8(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 0;
  return Math.max(0, Math.min(255, Math.round(numeric)));
}

function _setRangeValue(id, value) {
  const normalized = _clampU8(value);
  const input = _lightingEl(id);
  const number = _lightingEl(`${id}-number`);
  const label = _lightingEl(`${id}-value`);
  if (input) input.value = String(normalized);
  if (number) number.value = String(normalized);
  if (label) label.textContent = String(normalized);
}

function _setColorFromCurrentHs() {
  const colorEl = _lightingEl("lighting-color");
  if (!colorEl) return;
  const [r, g, b] = hsvToRgb(
    _lightingEl("lighting-hue")?.value ?? 0,
    _lightingEl("lighting-saturation")?.value ?? 0,
    255,
  );
  colorEl.value = `#${[r, g, b].map(v => v.toString(16).padStart(2, "0")).join("")}`;
}

function _setHsFromColor(hex) {
  const clean = String(hex || "").replace("#", "");
  if (!/^[0-9a-fA-F]{6}$/.test(clean)) return;
  const r = parseInt(clean.slice(0, 2), 16);
  const g = parseInt(clean.slice(2, 4), 16);
  const b = parseInt(clean.slice(4, 6), 16);
  const [h, s] = rgbToHsv(r, g, b);
  _setRangeValue("lighting-hue", h);
  _setRangeValue("lighting-saturation", s);
}

function rgbArrayToHex(color) {
  const rgb = Array.isArray(color) ? color.slice(0, 3) : [0, 0, 0];
  return `#${rgb.map(v => _clampU8(v).toString(16).padStart(2, "0")).join("")}`;
}

function hexToRgbArray(hex) {
  const clean = String(hex || "").replace("#", "");
  if (!/^[0-9a-fA-F]{6}$/.test(clean)) return [0, 0, 0];
  return [0, 2, 4].map(i => parseInt(clean.slice(i, i + 2), 16));
}

function _renderLightingColorPresets() {
  const presetsEl = _lightingEl("lighting-color-presets");
  if (!presetsEl || presetsEl.dataset.loaded === "1") return;
  for (const color of LIGHTING_COLOR_PRESETS) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "lighting-color-preset";
    btn.style.backgroundColor = color;
    btn.title = color;
    btn.setAttribute("aria-label", `Color ${color}`);
    btn.addEventListener("click", () => {
      const colorEl = _lightingEl("lighting-color");
      if (colorEl) colorEl.value = color;
      _setHsFromColor(color);
    });
    presetsEl.appendChild(btn);
  }
  presetsEl.dataset.loaded = "1";
}

function _lightingEffectName(mode) {
  const effect = _lightingEffects.find((item) => Number(item.id) === Number(mode));
  return effect ? effect.name : `Effect ${mode}`;
}

function ensureLightingMetricsPanel() {
  let panel = _lightingEl("lighting-metrics-panel");
  if (panel) return panel;
  const sideControls = document.querySelector(".lighting-side-controls");
  if (!sideControls) return null;
  panel = document.createElement("div");
  panel.id = "lighting-metrics-panel";
  panel.className = "lighting-metrics-panel";
  panel.innerHTML = [
    '<div class="lighting-metrics-title">Direct-frame metrics</div>',
    '<div class="lighting-metrics-grid">',
    '<span>State</span><strong id="lighting-metric-state">–</strong>',
    '<span>Accepted</span><strong id="lighting-metric-accepted">–</strong>',
    '<span>Applied</span><strong id="lighting-metric-applied">–</strong>',
    '<span>Ignored</span><strong id="lighting-metric-ignored">–</strong>',
    '<span>Rejected</span><strong id="lighting-metric-rejected">–</strong>',
    '<span>Last frame</span><strong id="lighting-metric-last-frame">–</strong>',
    '</div>',
    '<div id="lighting-metric-error" class="lighting-metric-error"></div>',
  ].join("");
  sideControls.appendChild(panel);
  return panel;
}

function formatMetricValue(value) {
  return value === null || value === undefined || value === "" ? "–" : String(value);
}

function updateLightingMetricsPanel(status) {
  const panel = ensureLightingMetricsPanel();
  if (!panel) return;
  const metrics = status?.ledd_direct_frame || status?.led_direct_frame || {};
  const stateEl = _lightingEl("lighting-metric-state");
  const acceptedEl = _lightingEl("lighting-metric-accepted");
  const appliedEl = _lightingEl("lighting-metric-applied");
  const ignoredEl = _lightingEl("lighting-metric-ignored");
  const rejectedEl = _lightingEl("lighting-metric-rejected");
  const lastFrameEl = _lightingEl("lighting-metric-last-frame");
  const errorEl = _lightingEl("lighting-metric-error");
  const active = Boolean(metrics.direct_frame_active);
  if (stateEl) {
    stateEl.textContent = active ? "active" : (metrics.metrics_source === "missing" ? "missing" : "idle");
    stateEl.className = active ? "metric-active" : "";
  }
  if (acceptedEl) acceptedEl.textContent = formatMetricValue(metrics.accepted_frames);
  if (appliedEl) appliedEl.textContent = formatMetricValue(metrics.applied_frames);
  if (ignoredEl) ignoredEl.textContent = formatMetricValue(metrics.ignored_frames);
  if (rejectedEl) rejectedEl.textContent = formatMetricValue(metrics.rejected_frames);
  if (lastFrameEl) lastFrameEl.textContent = formatMetricValue(metrics.last_applied_frame_id ?? metrics.last_frame_id);
  if (errorEl) {
    const error = metrics.metrics_error || metrics.last_error || "";
    errorEl.textContent = error ? `error: ${error}` : "";
    errorEl.hidden = !error;
  }
}

async function fetchLightingMetrics() {
  try {
    const resp = await fetch("/api/status");
    if (!resp.ok) return;
    updateLightingMetricsPanel(await resp.json());
  } catch (_e) {
    // metrics are diagnostics only; lighting controls should still work
  }
}

function inferLightingRoleFromKeycode(keycode) {
  const kc = String(keycode || "").trim();
  if (!kc || kc === "KC_TRNS") return "normal";
  if (/^(KC_)?[LR]?(CTL|CTRL|SFT|SHIFT|ALT|GUI|CMD|WIN|OPT)$/.test(kc)) return "modifier";
  if (/^KC_F\d{1,2}$/.test(kc)) return "function";
  if (/^(MO|TG|TO|DF|OSL|LT|TT)\(/.test(kc)) return "layer";
  if (/^(KC_)?(CAPS|NUM|SCROLL|LOCK)/.test(kc)) return "lock";
  if (/^KC_SH\d+$/.test(kc) || /^SCRIPT\(/.test(kc)) return "script";
  if (/^(BT_|WIFI_|KC_CONNAUTO|KC_USB|KC_SHUTDOWN)/.test(kc) || kc === "KC_BT") return "system";
  return "normal";
}

function ensureLightingRolePreviewPanel() {
  let panel = _lightingEl("lighting-role-preview-panel");
  if (panel) return panel;
  const sideControls = document.querySelector(".lighting-side-controls");
  if (!sideControls) return null;
  panel = document.createElement("div");
  panel.id = "lighting-role-preview-panel";
  panel.className = "lighting-role-preview-panel";
  panel.innerHTML = [
    '<div class="lighting-role-preview-title">LED role preview</div>',
    '<div id="lighting-role-preview-summary" class="lighting-role-preview-summary">読み込み中…</div>',
    '<div id="lighting-role-inspector-list" class="lighting-role-inspector-list"></div>',
    '<div id="lighting-role-preview-note" class="lighting-role-preview-note">read-only: 実LED preview / 保存は後続</div>',
  ].join("");
  sideControls.appendChild(panel);
  return panel;
}

function ensureLightingReactivePanel() {
  let panel = _lightingEl("lighting-reactive-panel");
  if (panel) return panel;
  const sideControls = document.querySelector(".lighting-side-controls");
  if (!sideControls) return null;
  panel = document.createElement("div");
  panel.id = "lighting-reactive-panel";
  panel.className = "lighting-reactive-panel";
  panel.innerHTML = [
    '<label class="lighting-reactive-check">',
    '<input id="lighting-modifier-trigger-effects" type="checkbox" onchange="saveLightingReactiveSettings()">',
    '<span>Modifier keys trigger effects</span>',
    '</label>',
    '<span id="lighting-reactive-status" class="lighting-reactive-status">–</span>',
  ].join("");
  sideControls.insertBefore(panel, sideControls.firstElementChild);
  return panel;
}

function updateLightingReactivePanel(data) {
  ensureLightingReactivePanel();
  const input = _lightingEl("lighting-modifier-trigger-effects");
  if (!input) return;
  input.checked = Boolean(data?.reactive?.modifier_triggers_effects);
}

function updateLightingRolePreviewPanel(layoutPayload) {
  const panel = ensureLightingRolePreviewPanel();
  const summary = _lightingEl("lighting-role-preview-summary");
  if (!panel || !summary) return;
  const layer0 = layoutPayload?.layer0 || {};
  const counts = Object.fromEntries(LIGHTING_ROLE_ORDER.map(role => [role, 0]));
  for (const keycode of Object.values(layer0)) {
    const role = inferLightingRoleFromKeycode(keycode);
    counts[role] = (counts[role] || 0) + 1;
  }
  summary.innerHTML = "";
  for (const role of LIGHTING_ROLE_ORDER) {
    const chip = document.createElement("span");
    chip.className = `lighting-role-chip lighting-role-${role}`;
    chip.textContent = `${role}: ${counts[role] || 0}`;
    summary.appendChild(chip);
  }
}

function updateLightingRoleInspectorPanel(payload) {
  const panel = ensureLightingRolePreviewPanel();
  const summary = _lightingEl("lighting-role-preview-summary");
  const list = _lightingEl("lighting-role-inspector-list");
  if (!panel || !summary || !list || payload?.result !== "ok") return;
  const counts = payload.summary || {};
  summary.innerHTML = "";
  for (const role of LIGHTING_ROLE_ORDER) {
    const chip = document.createElement("span");
    chip.className = `lighting-role-chip lighting-role-${role}`;
    chip.textContent = `${role}: ${counts[role] || 0}`;
    summary.appendChild(chip);
  }
  const keys = Array.isArray(payload.layers?.[0]?.keys) ? payload.layers[0].keys : [];
  list.innerHTML = "";
  for (const item of keys.filter(k => k.role !== "normal").slice(0, 18)) {
    const row = document.createElement("div");
    row.className = "lighting-role-inspector-row";
    row.title = item.reason || "";
    row.innerHTML = [
      `<span>${item.row},${item.col}</span>`,
      `<strong>${item.keycode}</strong>`,
      `<em class="lighting-role-${item.role}">${item.role}</em>`,
    ].join("");
    list.appendChild(row);
  }
}

async function fetchLightingRolePreview() {
  try {
    const resp = await fetch("/api/lighting/role-inspector");
    if (!resp.ok) return;
    updateLightingRoleInspectorPanel(await resp.json());
  } catch (_e) {
    // role preview is diagnostics only
  }
}

function ensureLightingSection(id, label, open = true) {
  let section = _lightingEl(id);
  if (section) return section;
  const controls = document.querySelector(".lighting-controls");
  if (!controls) return null;
  section = document.createElement("details");
  section.id = id;
  section.className = "lighting-section";
  if (open) section.open = true;
  section.innerHTML = [
    `<summary class="lighting-section-summary">${label}</summary>`,
    '<div class="lighting-section-body"></div>',
  ].join("");
  controls.appendChild(section);
  return section;
}

function ensureLightingSections() {
  const controls = document.querySelector(".lighting-controls");
  if (!controls) return;
  const lockSection = ensureLightingSection("lighting-lock-section", "Host lock LEDs", true);
  const layerSection = ensureLightingSection("lighting-layer-section", "Layer overlay colors", false);
  const effectSection = ensureLightingSection("lighting-effect-section", "LED Effect", true);
  const effectBody = effectSection?.querySelector(".lighting-section-body");
  if (effectBody && !effectBody.classList.contains("lighting-effect-section-body")) {
    effectBody.classList.add("lighting-effect-section-body");
  }
  const effectField = document.querySelector(".lighting-effect-field");
  const sideControls = document.querySelector(".lighting-side-controls");
  if (effectBody && effectField && effectField.parentElement !== effectBody) {
    effectBody.appendChild(effectField);
  }
  if (effectBody && sideControls && sideControls.parentElement !== effectBody) {
    effectBody.appendChild(sideControls);
  }
  if (lockSection && controls.firstElementChild !== lockSection) {
    controls.insertBefore(lockSection, controls.firstElementChild);
  }
  if (layerSection && effectSection && layerSection.nextElementSibling !== effectSection) {
    controls.insertBefore(layerSection, effectSection);
  }
}

function ensureLightingLayerPanel() {
  let panel = _lightingEl("lighting-layer-panel");
  if (panel) return panel;
  ensureLightingSections();
  const section = _lightingEl("lighting-layer-section");
  const body = section?.querySelector(".lighting-section-body");
  if (!body) return null;
  panel = document.createElement("div");
  panel.id = "lighting-layer-panel";
  panel.className = "lighting-layer-panel";
  panel.innerHTML = [
    '<div class="lighting-layer-toolbar">',
    '<div class="lighting-layer-title">Layer overlay colors</div>',
    '<div class="lighting-layer-actions">',
    '<button class="lighting-btn" type="button" onclick="saveLightingLayerOverlays()">保存</button>',
    '<button class="lighting-btn" type="button" onclick="fetchLightingLayerOverlays()">再読込</button>',
    '</div>',
    '</div>',
    '<div id="lighting-layer-status" class="lighting-layer-status">–</div>',
    '<div id="lighting-layer-list" class="lighting-layer-list"></div>',
  ].join("");
  body.appendChild(panel);
  return panel;
}

function setLightingLayerStatus(text, isError = false) {
  const el = _lightingEl("lighting-layer-status");
  if (!el) return;
  el.textContent = text;
  el.classList.toggle("error", isError);
}

function lightingLayerDefaultColor(layer) {
  const color = _lightingLayerOverlays?.palette?.[String(layer)];
  return Array.isArray(color) ? color : [0, 0, 0];
}

function _renderLightingLayerSwatches(row, selectedColor) {
  const swatches = row.querySelector(".lighting-layer-swatches");
  const colorInput = row.querySelector(".lighting-layer-color");
  if (!swatches || !colorInput) return;
  swatches.innerHTML = "";
  const colors = [selectedColor, ...LIGHTING_COLOR_PRESETS]
    .map(color => String(color || "").toLowerCase())
    .filter((color, idx, arr) => /^#[0-9a-f]{6}$/.test(color) && arr.indexOf(color) === idx);
  const setActive = () => {
    const current = colorInput.value.toLowerCase();
    row.style.setProperty("--layer-overlay-color", current);
    for (const item of swatches.querySelectorAll(".lighting-layer-swatch")) {
      item.classList.toggle("active", item.title.toLowerCase() === current);
    }
  };
  for (const color of colors) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "lighting-layer-swatch";
    btn.style.backgroundColor = color;
    btn.title = color;
    btn.setAttribute("aria-label", `Layer color ${color}`);
    btn.addEventListener("click", () => {
      colorInput.value = color;
      const enabled = row.querySelector(".lighting-layer-enabled");
      if (enabled) enabled.checked = true;
      setActive();
    });
    swatches.appendChild(btn);
  }
  colorInput.addEventListener("input", () => {
    const enabled = row.querySelector(".lighting-layer-enabled");
    if (enabled) enabled.checked = true;
    setActive();
  });
  setActive();
}

function _renderLightingLayerPanel(data) {
  _lightingLayerOverlays = data;
  const panel = ensureLightingLayerPanel();
  const list = _lightingEl("lighting-layer-list");
  if (!panel || !list) return;
  list.innerHTML = "";
  const layersByIndex = new Map((data?.layers || []).map(layer => [Number(layer.layer), layer]));
  for (const layer of LIGHTING_LAYER_RANGE) {
    const item = layersByIndex.get(layer) || {
      layer,
      enabled: false,
      color: lightingLayerDefaultColor(layer),
      effect_blend: "max",
      effect_alpha: 0.65,
      include_layer_changes: true,
      keys: [],
      extra_leds: [],
    };
    const row = document.createElement("section");
    row.className = "lighting-layer-row";
    row.dataset.layer = String(layer);
    const colorHex = rgbArrayToHex(item.color);
    const blendModes = data?.blend_modes || LIGHTING_LAYER_BLEND_MODES;
    row.innerHTML = [
      '<div class="lighting-layer-head">',
      `<label><input class="lighting-layer-enabled" type="checkbox" ${item.enabled ? "checked" : ""}> Layer ${layer}</label>`,
      `<input class="lighting-layer-color" type="color" value="${colorHex}" title="Layer ${layer} color">`,
      '</div>',
      '<div class="lighting-layer-controls">',
      '<label><span>Blend</span><select class="lighting-layer-blend">',
      blendModes.map(mode => `<option value="${mode}" ${mode === item.effect_blend ? "selected" : ""}>${mode}</option>`).join(""),
      '</select></label>',
      `<label><span>Alpha</span><input class="lighting-layer-alpha" type="number" min="0" max="1" step="0.05" value="${Number(item.effect_alpha ?? 0.65).toFixed(2)}"></label>`,
      `<label class="lighting-layer-change-check"><input class="lighting-layer-include-changes" type="checkbox" ${item.include_layer_changes ? "checked" : ""}> Changed keys</label>`,
      '</div>',
      '<div class="lighting-layer-swatches"></div>',
    ].join("");
    for (const control of row.querySelectorAll(".lighting-layer-blend, .lighting-layer-alpha, .lighting-layer-include-changes")) {
      control.addEventListener("input", () => {
        const enabled = row.querySelector(".lighting-layer-enabled");
        if (enabled) enabled.checked = true;
      });
      control.addEventListener("change", () => {
        const enabled = row.querySelector(".lighting-layer-enabled");
        if (enabled) enabled.checked = true;
      });
    }
    row._lightingLayerOriginal = {
      keys: Array.isArray(item.keys) ? item.keys : [],
      extra_leds: Array.isArray(item.extra_leds) ? item.extra_leds : [],
    };
    _renderLightingLayerSwatches(row, colorHex);
    list.appendChild(row);
  }
}

function readLightingLayerForm() {
  const layers = [];
  for (const row of document.querySelectorAll(".lighting-layer-row")) {
    const layer = Number(row.dataset.layer);
    const original = row._lightingLayerOriginal || {};
    layers.push({
      layer,
      enabled: Boolean(row.querySelector(".lighting-layer-enabled")?.checked),
      color: hexToRgbArray(row.querySelector(".lighting-layer-color")?.value),
      effect_blend: row.querySelector(".lighting-layer-blend")?.value || "max",
      effect_alpha: Number(row.querySelector(".lighting-layer-alpha")?.value || 0.65),
      include_layer_changes: Boolean(row.querySelector(".lighting-layer-include-changes")?.checked),
      keys: original.keys || [],
      extra_leds: original.extra_leds || [],
    });
  }
  return { layers };
}

async function fetchLightingLayerOverlays() {
  ensureLightingLayerPanel();
  setLightingLayerStatus("読込中");
  try {
    const resp = await fetch("/api/lighting/layer-overlays");
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") {
      setLightingLayerStatus(data.msg || `HTTP ${resp.status}`, true);
      return;
    }
    _renderLightingLayerPanel(data);
    setLightingLayerStatus("同期済み");
  } catch (e) {
    setLightingLayerStatus(e.message, true);
  }
}

async function saveLightingLayerOverlays() {
  setLightingLayerStatus("保存中");
  try {
    const resp = await csrfFetch("/api/lighting/layer-overlays", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(readLightingLayerForm()),
    });
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") {
      setLightingLayerStatus(data.msg || `HTTP ${resp.status}`, true);
      return;
    }
    _renderLightingLayerPanel(data);
    if (data.reload?.result === "error") {
      setLightingLayerStatus(`保存済み / 反映失敗: ${data.reload.msg || "reload error"}`, true);
      return;
    }
    setLightingLayerStatus("保存・反映依頼済み");
  } catch (e) {
    setLightingLayerStatus(e.message, true);
  }
}

function ensureLightingLockPanel() {
  let panel = _lightingEl("lighting-lock-panel");
  if (panel) return panel;
  ensureLightingSections();
  const section = _lightingEl("lighting-lock-section");
  const body = section?.querySelector(".lighting-section-body");
  if (!body) return null;
  panel = document.createElement("div");
  panel.id = "lighting-lock-panel";
  panel.className = "lighting-lock-panel";
  panel.innerHTML = [
    '<div class="lighting-lock-toolbar">',
    '<div class="lighting-lock-title">Host lock LEDs</div>',
    '<div class="lighting-lock-actions">',
    '<button class="lighting-btn" type="button" onclick="saveLightingLockIndicators()">保存</button>',
    '<button class="lighting-btn" type="button" onclick="fetchLightingLockIndicators()">再読込</button>',
    '</div>',
    '</div>',
    '<div id="lighting-lock-status" class="lighting-lock-status">–</div>',
    '<div class="lighting-lock-blend-row">',
    '<label for="lighting-lock-blend">Blend</label>',
    '<select id="lighting-lock-blend">',
    '<option value="max">max</option>',
    '<option value="priority">priority</option>',
    '<option value="add">add</option>',
    '</select>',
    '</div>',
    '<div id="lighting-lock-states" class="lighting-lock-states"></div>',
  ].join("");
  body.appendChild(panel);
  return panel;
}

function setLightingLockStatus(text, isError = false) {
  const el = _lightingEl("lighting-lock-status");
  if (!el) return;
  el.textContent = text;
  el.classList.toggle("error", isError);
}

function _renderLightingLockPanel(data) {
  _lightingLockIndicators = data;
  const panel = ensureLightingLockPanel();
  const list = _lightingEl("lighting-lock-states");
  const blend = _lightingEl("lighting-lock-blend");
  if (!panel || !list) return;
  if (blend) blend.value = data?.blend || "max";
  list.innerHTML = "";
  const states = data?.states || {};
  for (const [name, label] of LIGHTING_LOCK_STATES) {
    const state = states[name] || {};
    const row = document.createElement("section");
    row.className = "lighting-lock-state";
    row.dataset.state = name;
    row.innerHTML = [
      '<div class="lighting-lock-state-head">',
      '<div class="lighting-lock-state-title">',
      `<label><input class="lighting-lock-enabled" type="checkbox" ${state.enabled ? "checked" : ""}> ${label}</label>`,
      `<button type="button" class="lighting-lock-color-chip" title="${label} color"></button>`,
      '</div>',
      '<div class="lighting-lock-color-popover" hidden>',
      `<input class="lighting-lock-color" type="color" value="${rgbArrayToHex(state.color)}" title="${label} color">`,
      '<div class="lighting-lock-swatches"></div>',
      '</div>',
      '</div>',
      '<div class="lighting-lock-input"><span>Extra LEDs</span><div class="lighting-lock-led-list"></div></div>',
      '<div class="lighting-lock-input"><span class="lighting-lock-input-head"><span>Keys</span><button type="button" class="lighting-lock-keys-reset">初期化</button></span><div class="lighting-lock-key-list"></div></div>',
    ].join("");
    renderLightingLockLedList(row, state.extra_leds || []);
    renderLightingLockKeyList(row, state.keys || []);
    setupLightingLockKeyReset(row);
    _renderLightingLockSwatches(row, rgbArrayToHex(state.color));
    setupLightingLockColorPopover(row);
    list.appendChild(row);
  }
}

function lightingLockKeyLabel(keycode) {
  if (typeof keycodeLabel === "function") return keycodeLabel(keycode);
  return String(keycode || "");
}

function lightingLockStateLabel(name) {
  const found = LIGHTING_LOCK_STATES.find(([state]) => state === name);
  return found ? found[1] : String(name || "");
}

function renderLightingLockKeyList(row, keys) {
  const list = row.querySelector(".lighting-lock-key-list");
  if (!list) return;
  const unique = Array.from(new Set((keys || []).map(k => String(k || "").trim()).filter(Boolean)));
  list.innerHTML = "";
  for (const keycode of unique) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "lighting-lock-key-chip";
    chip.dataset.keycode = keycode;
    chip.title = keycode;
    chip.textContent = lightingLockKeyLabel(keycode);
    const remove = document.createElement("span");
    remove.className = "lighting-lock-key-remove";
    remove.textContent = "×";
    remove.setAttribute("aria-hidden", "true");
    chip.appendChild(remove);
    chip.addEventListener("click", () => {
      chip.classList.toggle("removing");
    });
    remove.addEventListener("click", (event) => {
      event.stopPropagation();
      chip.remove();
    });
    list.appendChild(chip);
  }
  const add = document.createElement("button");
  add.type = "button";
  add.className = "lighting-lock-key-add";
  add.textContent = "+";
  add.title = "Add key";
  add.setAttribute("aria-label", "Add lock key");
  add.addEventListener("click", () => openLightingLockKeyPicker(row));
  list.appendChild(add);
}

function readLightingLockKeys(row) {
  return Array.from(row.querySelectorAll(".lighting-lock-key-chip"))
    .map(chip => chip.dataset.keycode || "")
    .filter(Boolean);
}

function defaultLightingLockKeys(stateName) {
  const keys = _lightingLockIndicators?.default_keys?.[stateName];
  return Array.isArray(keys) ? keys : [];
}

function setupLightingLockKeyReset(row) {
  const btn = row.querySelector(".lighting-lock-keys-reset");
  if (!btn) return;
  btn.addEventListener("click", () => {
    renderLightingLockKeyList(row, defaultLightingLockKeys(row.dataset.state));
  });
}

function renderLightingLockLedList(row, leds) {
  const list = row.querySelector(".lighting-lock-led-list");
  if (!list) return;
  const color = row.querySelector(".lighting-lock-color")?.value || "#ffffff";
  row.style.setProperty("--lock-led-color", color);
  const unique = Array.from(new Set((leds || []).map(led => String(led || "").trim()).filter(Boolean)));
  list.innerHTML = "";
  for (const ledId of unique) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "lighting-lock-led-chip";
    chip.dataset.ledId = ledId;
    chip.title = lightingLockLedTitle(ledId);
    const swatch = document.createElement("span");
    swatch.className = "lighting-lock-led-chip-swatch";
    swatch.setAttribute("aria-hidden", "true");
    const label = document.createElement("span");
    label.textContent = ledId;
    chip.appendChild(swatch);
    chip.appendChild(label);
    const remove = document.createElement("span");
    remove.className = "lighting-lock-led-remove";
    remove.textContent = "×";
    remove.setAttribute("aria-hidden", "true");
    chip.appendChild(remove);
    chip.addEventListener("click", () => {
      chip.classList.toggle("removing");
    });
    remove.addEventListener("click", (event) => {
      event.stopPropagation();
      chip.remove();
    });
    list.appendChild(chip);
  }
  const add = document.createElement("button");
  add.type = "button";
  add.className = "lighting-lock-led-add";
  add.textContent = "+";
  add.title = "Add LED";
  add.setAttribute("aria-label", "Add extra LED");
  add.addEventListener("click", () => openLightingLockLedPicker(row));
  list.appendChild(add);
}

function readLightingLockLeds(row) {
  return Array.from(row.querySelectorAll(".lighting-lock-led-chip"))
    .map(chip => chip.dataset.ledId || "")
    .filter(Boolean);
}

function lightingLockLedPositions() {
  const raw = _lightingLockIndicators?.led_positions || {};
  const keys = _lightingLockIndicators?.led_keys || [];
  const entries = [];
  if (raw && typeof raw === "object") {
    for (const [id, pos] of Object.entries(raw)) {
      const x = Number(pos?.x);
      const y = Number(pos?.y);
      if (Number.isFinite(x) && Number.isFinite(y)) entries.push({ id: String(id), x, y });
    }
  }
  if (entries.length) return entries;
  return keys.map((id, index) => ({ id: String(id), x: index % 12, y: Math.floor(index / 12) }));
}

function lightingLockLedPositionById(ledId) {
  return lightingLockLedPositions().find(led => led.id === String(ledId)) || null;
}

function lightingLockLedAssignedStates(ledId) {
  const out = [];
  const states = _lightingLockIndicators?.states || {};
  for (const [name, state] of Object.entries(states)) {
    if ((state?.extra_leds || []).map(String).includes(String(ledId))) {
      out.push(lightingLockStateLabel(name));
    }
  }
  return out;
}

function lightingLockLedTitle(ledId) {
  const pos = lightingLockLedPositionById(ledId);
  const lines = [`LED ${ledId}`];
  if (pos) lines.push(`x: ${pos.x.toFixed(1)}, y: ${pos.y.toFixed(1)}`);
  const assigned = lightingLockLedAssignedStates(ledId);
  if (assigned.length) lines.push(`assigned: ${assigned.join(", ")}`);
  return lines.join("\n");
}

function syncLightingLockLedChipColors(row) {
  const color = row.querySelector(".lighting-lock-color")?.value || "#ffffff";
  row.style.setProperty("--lock-led-color", color);
  const chip = row.querySelector(".lighting-lock-color-chip");
  if (chip) {
    chip.style.backgroundColor = color;
    chip.title = `Color ${color}`;
    chip.setAttribute("aria-label", `Color ${color}`);
  }
}

function _keysFromPc104Rows(rows) {
  const keys = [];
  for (const row of rows || []) {
    if (!row) continue;
    for (const entry of row) {
      if (Array.isArray(entry) && entry[0]) keys.push(entry[0]);
    }
  }
  return keys;
}

function lightingLockKeyCandidates() {
  const groups = [
    ["Lock aliases", ["KC_CAPS", "KC_CAPSLOCK", "KC_NUM", "KC_NUMLOCK", "KC_NLCK", "KC_SCROLL", "KC_SCROLLLOCK", "KC_SLCK", "KC_COMPOSE", "KC_KANA", "KC_INT2"]],
    ["PC104", [
      ..._keysFromPc104Rows(typeof PC104_MAIN_ROWS !== "undefined" ? PC104_MAIN_ROWS : []),
      ..._keysFromPc104Rows(typeof PC104_NAV_ROWS !== "undefined" ? PC104_NAV_ROWS : []),
      ..._keysFromPc104Rows(typeof PC104_NUMPAD_ROWS !== "undefined" ? PC104_NUMPAD_ROWS : []),
    ]],
  ];
  const extraGroups = typeof REMAP_TAB_GROUPS !== "undefined" ? REMAP_TAB_GROUPS : {};
  for (const name of ["layer", "mouse", "media", "bt", "wifi", "system", "script", "other"]) {
    const items = (extraGroups[name] || []).flatMap(group => group.keys || []);
    if (items.length) groups.push([name, items]);
  }
  return groups
    .map(([label, keys]) => [label, Array.from(new Set(keys)).filter(Boolean)])
    .filter(([, keys]) => keys.length);
}

function ensureLightingLockKeyPicker() {
  let picker = _lightingEl("lighting-lock-key-picker");
  if (picker) return picker;
  picker = document.createElement("div");
  picker.id = "lighting-lock-key-picker";
  picker.className = "lighting-lock-key-picker";
  picker.innerHTML = [
    '<div class="lighting-lock-key-picker-backdrop"></div>',
    '<div class="lighting-lock-key-picker-dialog" role="dialog" aria-modal="true">',
    '<div class="lighting-lock-key-picker-head">',
    '<strong>Add lock key</strong>',
    '<button type="button" class="lighting-lock-key-picker-close" aria-label="Close">×</button>',
    '</div>',
    '<input id="lighting-lock-key-search" class="lighting-lock-key-search" type="search" placeholder="keycode / label を検索">',
    '<div id="lighting-lock-key-candidates" class="lighting-lock-key-candidates"></div>',
    '</div>',
  ].join("");
  picker.querySelector(".lighting-lock-key-picker-backdrop").addEventListener("click", closeLightingLockKeyPicker);
  picker.querySelector(".lighting-lock-key-picker-close").addEventListener("click", closeLightingLockKeyPicker);
  picker.querySelector(".lighting-lock-key-search").addEventListener("input", filterLightingLockKeyCandidates);
  document.body.appendChild(picker);
  return picker;
}

function openLightingLockKeyPicker(row) {
  _lightingLockKeyTarget = row;
  const picker = ensureLightingLockKeyPicker();
  picker.classList.add("open");
  const search = _lightingEl("lighting-lock-key-search");
  if (search) {
    search.value = "";
    search.focus();
  }
  renderLightingLockKeyCandidates();
}

function closeLightingLockKeyPicker() {
  const picker = _lightingEl("lighting-lock-key-picker");
  if (picker) picker.classList.remove("open");
  _lightingLockKeyTarget = null;
}

function renderLightingLockKeyCandidates() {
  const root = _lightingEl("lighting-lock-key-candidates");
  if (!root) return;
  root.innerHTML = "";
  const selected = new Set(_lightingLockKeyTarget ? readLightingLockKeys(_lightingLockKeyTarget) : []);
  for (const [groupLabel, keys] of lightingLockKeyCandidates()) {
    const group = document.createElement("section");
    group.className = "lighting-lock-key-candidate-group";
    const title = document.createElement("div");
    title.className = "lighting-lock-key-candidate-title";
    title.textContent = groupLabel;
    group.appendChild(title);
    const grid = document.createElement("div");
    grid.className = "lighting-lock-key-candidate-grid";
    for (const keycode of keys) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "lighting-lock-key-candidate";
      btn.dataset.keycode = keycode;
      btn.dataset.search = `${keycode} ${lightingLockKeyLabel(keycode)}`.toLowerCase();
      btn.textContent = lightingLockKeyLabel(keycode);
      btn.title = keycode;
      btn.disabled = selected.has(keycode);
      btn.addEventListener("click", () => {
        if (!_lightingLockKeyTarget) return;
        renderLightingLockKeyList(_lightingLockKeyTarget, [...readLightingLockKeys(_lightingLockKeyTarget), keycode]);
        closeLightingLockKeyPicker();
      });
      grid.appendChild(btn);
    }
    group.appendChild(grid);
    root.appendChild(group);
  }
  filterLightingLockKeyCandidates();
}

function filterLightingLockKeyCandidates() {
  const query = String(_lightingEl("lighting-lock-key-search")?.value || "").trim().toLowerCase();
  for (const group of document.querySelectorAll(".lighting-lock-key-candidate-group")) {
    let visible = 0;
    for (const btn of group.querySelectorAll(".lighting-lock-key-candidate")) {
      const match = !query || (btn.dataset.search || "").includes(query);
      btn.hidden = !match;
      if (match) visible += 1;
    }
    group.hidden = visible === 0;
  }
}

function ensureLightingLockLedPicker() {
  let picker = _lightingEl("lighting-lock-led-picker");
  if (picker) return picker;
  picker = document.createElement("div");
  picker.id = "lighting-lock-led-picker";
  picker.className = "lighting-lock-led-picker";
  picker.innerHTML = [
    '<div class="lighting-lock-led-picker-backdrop"></div>',
    '<div class="lighting-lock-led-picker-dialog" role="dialog" aria-modal="true">',
    '<div class="lighting-lock-led-picker-head">',
    '<strong>Add extra LED</strong>',
    '<button type="button" class="lighting-lock-led-picker-close" aria-label="Close">×</button>',
    '</div>',
    '<div class="lighting-lock-led-picker-note">LED番号をクリックして追加</div>',
    '<div id="lighting-lock-led-map" class="lighting-lock-led-map"></div>',
    '</div>',
  ].join("");
  picker.querySelector(".lighting-lock-led-picker-backdrop").addEventListener("click", closeLightingLockLedPicker);
  picker.querySelector(".lighting-lock-led-picker-close").addEventListener("click", closeLightingLockLedPicker);
  document.body.appendChild(picker);
  return picker;
}

function openLightingLockLedPicker(row) {
  _lightingLockLedTarget = row;
  const picker = ensureLightingLockLedPicker();
  picker.classList.add("open");
  renderLightingLockLedMap();
}

function closeLightingLockLedPicker() {
  const picker = _lightingEl("lighting-lock-led-picker");
  if (picker) picker.classList.remove("open");
  _lightingLockLedTarget = null;
}

function renderLightingLockLedMap() {
  const root = _lightingEl("lighting-lock-led-map");
  if (!root) return;
  const leds = lightingLockLedPositions();
  root.innerHTML = "";
  if (!leds.length) {
    root.textContent = "LED座標がありません";
    return;
  }
  const selected = new Set(_lightingLockLedTarget ? readLightingLockLeds(_lightingLockLedTarget) : []);
  const xs = leds.map(led => led.x);
  const ys = leds.map(led => led.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = Math.max(1, maxX - minX);
  const spanY = Math.max(1, maxY - minY);
  const pad = 5;
  root.style.setProperty("--led-map-aspect", String(Math.max(1.4, spanX / spanY)));
  for (const led of leds) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "lighting-lock-led-map-point";
    btn.dataset.ledId = led.id;
    btn.textContent = led.id;
    btn.title = lightingLockLedTitle(led.id);
    btn.disabled = selected.has(led.id);
    btn.classList.toggle("selected", selected.has(led.id));
    const left = pad + ((led.x - minX) / spanX) * (100 - pad * 2);
    const top = pad + ((led.y - minY) / spanY) * (100 - pad * 2);
    btn.style.left = `${left}%`;
    btn.style.top = `${top}%`;
    btn.addEventListener("click", () => {
      if (!_lightingLockLedTarget) return;
      if (selected.has(led.id)) return;
      renderLightingLockLedList(_lightingLockLedTarget, [...readLightingLockLeds(_lightingLockLedTarget), led.id]);
      closeLightingLockLedPicker();
    });
    root.appendChild(btn);
  }
}

function _renderLightingLockSwatches(row, selectedColor) {
  const swatches = row.querySelector(".lighting-lock-swatches");
  const colorInput = row.querySelector(".lighting-lock-color");
  if (!swatches || !colorInput) return;
  syncLightingLockLedChipColors(row);
  swatches.innerHTML = "";
  const colors = [selectedColor, ...LIGHTING_COLOR_PRESETS]
    .map(color => String(color || "").toLowerCase())
    .filter((color, idx, arr) => /^#[0-9a-f]{6}$/.test(color) && arr.indexOf(color) === idx);
  for (const color of colors) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "lighting-lock-swatch";
    btn.style.backgroundColor = color;
    btn.title = color;
    btn.setAttribute("aria-label", `Lock color ${color}`);
    btn.classList.toggle("active", color.toLowerCase() === String(selectedColor).toLowerCase());
    btn.addEventListener("click", () => {
      colorInput.value = color;
      syncLightingLockLedChipColors(row);
      for (const item of swatches.querySelectorAll(".lighting-lock-swatch")) {
        item.classList.toggle("active", item === btn);
      }
    });
    swatches.appendChild(btn);
  }
  colorInput.addEventListener("input", () => {
    const current = colorInput.value.toLowerCase();
    syncLightingLockLedChipColors(row);
    for (const item of swatches.querySelectorAll(".lighting-lock-swatch")) {
      item.classList.toggle("active", item.title.toLowerCase() === current);
    }
  });
}

function setupLightingLockColorPopover(row) {
  syncLightingLockLedChipColors(row);
  const chip = row.querySelector(".lighting-lock-color-chip");
  const popover = row.querySelector(".lighting-lock-color-popover");
  if (!chip || !popover) return;
  if (!_lightingLockColorPopoverBound) {
    _lightingLockColorPopoverBound = true;
    document.addEventListener("click", () => {
      for (const other of document.querySelectorAll(".lighting-lock-color-popover")) {
        other.hidden = true;
      }
      for (const otherChip of document.querySelectorAll(".lighting-lock-color-chip")) {
        otherChip.classList.remove("active");
      }
    });
  }
  chip.addEventListener("click", (event) => {
    event.stopPropagation();
    const willOpen = popover.hidden;
    for (const other of document.querySelectorAll(".lighting-lock-color-popover")) {
      other.hidden = true;
    }
    for (const otherChip of document.querySelectorAll(".lighting-lock-color-chip")) {
      otherChip.classList.remove("active");
    }
    popover.hidden = !willOpen;
    chip.classList.toggle("active", willOpen);
  });
  popover.addEventListener("click", (event) => {
    event.stopPropagation();
  });
}

async function fetchLightingLockIndicators() {
  ensureLightingLockPanel();
  setLightingLockStatus("読込中");
  try {
    const resp = await fetch("/api/lighting/lock-indicators");
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") {
      setLightingLockStatus(data.msg || `HTTP ${resp.status}`, true);
      return;
    }
    _renderLightingLockPanel(data);
    updateLightingReactivePanel(data);
    setLightingLockStatus("同期済み");
  } catch (e) {
    setLightingLockStatus(e.message, true);
  }
}

function readLightingLockForm() {
  const states = {};
  for (const row of document.querySelectorAll(".lighting-lock-state")) {
    const name = row.dataset.state;
    const existing = _lightingLockIndicators?.states?.[name] || {};
    states[name] = {
      enabled: Boolean(row.querySelector(".lighting-lock-enabled")?.checked),
      follow_keys: true,
      color: hexToRgbArray(row.querySelector(".lighting-lock-color")?.value),
      extra_leds: readLightingLockLeds(row),
      keys: readLightingLockKeys(row),
      key_colors: existing.key_colors || {},
    };
  }
  return {
    blend: _lightingEl("lighting-lock-blend")?.value || "max",
    states,
  };
}

async function saveLightingLockIndicators() {
  setLightingLockStatus("保存中");
  try {
    const resp = await csrfFetch("/api/lighting/lock-indicators", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(readLightingLockForm()),
    });
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") {
      setLightingLockStatus(data.msg || `HTTP ${resp.status}`, true);
      return;
    }
    _renderLightingLockPanel(data);
    if (data.reload?.result === "error") {
      setLightingLockStatus(`保存済み / 反映失敗: ${data.reload.msg || "reload error"}`, true);
      return;
    }
    setLightingLockStatus("保存・反映依頼済み");
  } catch (e) {
    setLightingLockStatus(e.message, true);
  }
}

function setLightingReactiveStatus(text, isError = false) {
  const el = _lightingEl("lighting-reactive-status");
  if (!el) return;
  el.textContent = text;
  el.classList.toggle("error", isError);
}

async function saveLightingReactiveSettings() {
  const checked = Boolean(_lightingEl("lighting-modifier-trigger-effects")?.checked);
  setLightingReactiveStatus("保存中");
  try {
    const resp = await csrfFetch("/api/lighting/lock-indicators", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reactive: { modifier_triggers_effects: checked } }),
    });
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") {
      setLightingReactiveStatus(data.msg || `HTTP ${resp.status}`, true);
      return;
    }
    _lightingLockIndicators = data;
    updateLightingReactivePanel(data);
    if (data.reload?.result === "error") {
      setLightingReactiveStatus("反映失敗", true);
      return;
    }
    setLightingReactiveStatus("保存済み");
  } catch (e) {
    setLightingReactiveStatus(e.message, true);
  }
}

function _renderLightingEffectButtons() {
  const groupsEl = _lightingEl("lighting-effect-groups");
  if (!groupsEl) return;
  groupsEl.innerHTML = "";

  const effectById = new Map(_lightingEffects.map((effect) => [Number(effect.id), effect]));
  const categories = _lightingEffectCategories.length
    ? _lightingEffectCategories
    : [{ id: "all", label: "All", effects: _lightingEffects.map((effect) => Number(effect.id)) }];

  for (const category of categories) {
    const group = document.createElement("section");
    group.className = "lighting-effect-group";

    const title = document.createElement("div");
    title.className = "lighting-effect-group-title";
    title.textContent = category.label || category.id || "Effects";
    group.appendChild(title);

    const list = document.createElement("div");
    list.className = "lighting-effect-button-grid";
    for (const effectId of category.effects || []) {
      const effect = effectById.get(Number(effectId));
      if (!effect) continue;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "lighting-effect-btn";
      btn.dataset.effectId = String(effect.id);
      btn.title = `${effect.id}: ${effect.name}`;
      const idSpan = document.createElement("span");
      idSpan.className = "lighting-effect-id";
      idSpan.textContent = String(effect.id);
      const nameSpan = document.createElement("span");
      nameSpan.className = "lighting-effect-name";
      nameSpan.textContent = effect.name;
      btn.appendChild(idSpan);
      btn.appendChild(nameSpan);
      btn.addEventListener("click", () => {
        const modeEl = _lightingEl("lighting-mode");
        if (modeEl) modeEl.value = String(effect.id);
        _lightingState.mode = Number(effect.id);
        _updateLightingEffectSelection();
        applyLighting();
      });
      list.appendChild(btn);
    }
    group.appendChild(list);
    groupsEl.appendChild(group);
  }

  _updateLightingEffectSelection();
}

function _updateLightingEffectSelection() {
  const currentEl = _lightingEl("lighting-current-effect");
  if (currentEl) {
    currentEl.textContent = `${_lightingState.mode}: ${_lightingEffectName(_lightingState.mode)}`;
  }
  for (const btn of document.querySelectorAll(".lighting-effect-btn")) {
    btn.classList.toggle("active", Number(btn.dataset.effectId) === Number(_lightingState.mode));
  }
}

function updateLightingUI(state) {
  _lightingState = {
    mode: Number(state.mode),
    speed: Number(state.speed),
    h: Number(state.h),
    s: Number(state.s),
    v: Number(state.v),
  };
  const modeEl = _lightingEl("lighting-mode");
  if (modeEl) modeEl.value = String(_lightingState.mode);
  _updateLightingEffectSelection();
  _setRangeValue("lighting-brightness", _lightingState.v);
  _setRangeValue("lighting-speed", _lightingState.speed);
  _setRangeValue("lighting-hue", _lightingState.h);
  _setRangeValue("lighting-saturation", _lightingState.s);

  const colorEl = _lightingEl("lighting-color");
  if (colorEl) {
    const [r, g, b] = hsvToRgb(_lightingState.h, _lightingState.s, 255);
    colorEl.value = `#${[r, g, b].map(v => v.toString(16).padStart(2, "0")).join("")}`;
  }
}

async function fetchLighting() {
  setLightingStatus("読込中");
  try {
    const resp = await fetch("/api/lighting");
    const data = await resp.json();
    if (!_lightingEffectsLoaded) {
      _lightingEffects = data.effects || [];
      _lightingEffectCategories = data.effect_categories || [];
      _renderLightingEffectButtons();
      _lightingEffectsLoaded = true;
    }
    updateLightingUI(data.state || _lightingState);
    fetchLightingMetrics();
    fetchLightingRolePreview();
    fetchLightingLayerOverlays();
    fetchLightingLockIndicators();
    if (!resp.ok || data.result !== "ok") {
      setLightingStatus(data.msg || data.error || `HTTP ${resp.status}`, true);
      return;
    }
    setLightingStatus("同期済み");
  } catch (e) {
    setLightingStatus(e.message, true);
  }
}

function readLightingForm() {
  return {
    mode: Number(_lightingEl("lighting-mode")?.value ?? _lightingState.mode),
    speed: Number(_lightingEl("lighting-speed")?.value ?? _lightingState.speed),
    h: Number(_lightingEl("lighting-hue")?.value ?? _lightingState.h),
    s: Number(_lightingEl("lighting-saturation")?.value ?? _lightingState.s),
    v: Number(_lightingEl("lighting-brightness")?.value ?? _lightingState.v),
  };
}

async function applyLighting() {
  const payload = readLightingForm();
  setLightingStatus("反映中");
  try {
    const resp = await csrfFetch("/api/lighting", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") {
      setLightingStatus(data.msg || `HTTP ${resp.status}`, true);
      return;
    }
    updateLightingUI(data.state || payload);
    fetchLightingMetrics();
    fetchLightingRolePreview();
    setLightingStatus(data.save === "scheduled" ? "反映済み / 保存待ち" : "反映済み");
  } catch (e) {
    setLightingStatus(e.message, true);
  }
}

async function resetSavedLighting() {
  setLightingStatus("保存済みに戻しています");
  try {
    const resp = await csrfFetch("/api/lighting/reset", { method: "POST" });
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") {
      setLightingStatus(data.msg || `HTTP ${resp.status}`, true);
      return;
    }
    updateLightingUI(data.state || _lightingState);
    fetchLightingMetrics();
    fetchLightingRolePreview();
    setLightingStatus("保存済み状態へ戻しました");
  } catch (e) {
    setLightingStatus(e.message, true);
  }
}

function initLightingPanelEvents() {
  ensureLightingSections();
  _renderLightingColorPresets();
  ensureLightingMetricsPanel();
  ensureLightingRolePreviewPanel();
  ensureLightingReactivePanel();
  ensureLightingLayerPanel();
  ensureLightingLockPanel();
  fetchLightingMetrics();
  fetchLightingRolePreview();
  fetchLightingLayerOverlays();
  fetchLightingLockIndicators();
  const rangeIds = ["lighting-brightness", "lighting-speed", "lighting-hue", "lighting-saturation"];
  for (const id of rangeIds) {
    const input = _lightingEl(id);
    const number = _lightingEl(`${id}-number`);
    const sync = (value) => {
      _setRangeValue(id, value);
      if (id === "lighting-hue" || id === "lighting-saturation") {
        _setColorFromCurrentHs();
      }
    };
    if (input) input.addEventListener("input", () => sync(input.value));
    if (number) {
      number.addEventListener("input", () => sync(number.value));
      number.addEventListener("change", () => sync(number.value));
    }
  }
  const colorEl = _lightingEl("lighting-color");
  if (colorEl) {
    colorEl.addEventListener("input", () => {
      _setHsFromColor(colorEl.value);
    });
  }
}
