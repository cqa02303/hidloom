"use strict";

// -----------------------------------------------------------------------
// Keymap remap mode
// -----------------------------------------------------------------------

let remapMode = false;
let _remapTarget = null;   // { row, col, matrixKey, currentKeycode }
let _remapLayer  = 0;
let _allLayers   = [];     // all_layers from /api/layout
let _defaultLayers = [];    // default layers from config/default/keymap.json
let _labelsCache = {};     // labels cache (filled in init)
let _availableKeycodes = []; // config/default/keycodes.json names exposed by /api/layout
let _keyboardSlots = [];    // parsed KLE slots rendered in the main keyboard
let _pendingLayerTap = null; // { layer }
let _remapChoicePicker = null; // { currentKeycode, onSelect, title }
let _remapSearchReady = false;
let _remapScriptEntries = new Map();
let _remapScriptRequest = null;
let _remapInteractionSettings = null;
let _remapInteractionRequest = null;
let _controlMetadata = {
  joystickDirections: new Map(),
  encoderDirections: new Map(),
  encoderActions: new Map(),
  encoderClickKeys: new Set(),
};

function updateControlMetadata(controls = {}) {
  _controlMetadata = {
    joystickDirections: new Map(Object.entries(controls.joystick_directions || {})),
    encoderDirections: new Map(Object.entries(controls.encoder_directions || {})),
    encoderActions: new Map(Object.entries(controls.encoder_actions || {}).map(([idx, actions]) => [
      Number.parseInt(idx, 10),
      actions || {},
    ])),
    encoderClickKeys: new Set(controls.encoder_click_keys || []),
  };
}

function setAvailableRemapKeycodes(keycodes) {
  _availableKeycodes = Array.isArray(keycodes)
    ? keycodes.filter(kc => typeof kc === "string" && kc.length > 0)
    : [];
}

function setRemapScriptEntries(scripts) {
  _remapScriptEntries = new Map();
  for (const script of Array.isArray(scripts) ? scripts : []) {
    if (script && typeof script.keycode === "string") {
      _remapScriptEntries.set(script.keycode, script);
    }
  }
}

function _remapPopupVisible() {
  const popup = document.getElementById("remap-popup");
  return Boolean(popup && popup.style.display !== "none");
}

function _refreshRemapScriptChoices() {
  if (!_remapPopupVisible()) return;
  const activeTab = document.querySelector(".remap-tab.active")?.dataset.tab || "script";
  renderAllRemapTabs();
  switchRemapTab(activeTab);
}

async function fetchRemapScriptEntries(force = false) {
  if (_remapScriptRequest && !force) return _remapScriptRequest;
  _remapScriptRequest = (async () => {
    const resp = await fetch("/api/scripts");
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") throw new Error(data.msg || `HTTP ${resp.status}`);
    setRemapScriptEntries(data.scripts || []);
  })();
  try {
    await _remapScriptRequest;
  } finally {
    _remapScriptRequest = null;
  }
}

async function fetchRemapInteractionSettings(force = false) {
  if (_remapInteractionRequest && !force) return _remapInteractionRequest;
  _remapInteractionRequest = (async () => {
    const resp = await fetch("/api/interaction");
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") throw new Error(data.msg || `HTTP ${resp.status}`);
    _remapInteractionSettings = data.settings || {};
  })();
  try {
    await _remapInteractionRequest;
  } finally {
    _remapInteractionRequest = null;
  }
}

async function refreshLayoutLayers() {
  const resp = await fetch("/api/layout");
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const data = await resp.json();
  const layer0 = data.layer0 || {};
  _allLayers = data.all_layers || [];
  if (_allLayers.length === 0 && Object.keys(layer0).length > 0) {
    _allLayers = [layer0];
  }
  _defaultLayers = Array.isArray(data.default_layers) ? data.default_layers : [];
  if (_defaultLayers.length === 0 && data.default_layer0 && Object.keys(data.default_layer0).length > 0) {
    _defaultLayers = [data.default_layer0];
  }
  if (data.labels) _labelsCache = data.labels;
  setAvailableRemapKeycodes(data.keycodes || []);
  updateControlMetadata(data.controls || {});
  _updateLayerSelector();
  updateKeyboardLayerSelector();
  updateKeyboardLayerDisplay(_remapLayer);
  if (_remapTarget) updateRemapTargetForCurrentLayer();
}

function _allKeysInRows(rows) {
  const keys = [];
  for (const row of rows) {
    if (!row) continue;
    for (const entry of row) {
      if (Array.isArray(entry)) keys.push(entry[0]);
    }
  }
  return keys;
}

function _keysForRemapTab(tabName) {
  if (tabName === "pc104") {
    return [
      ..._allKeysInRows(PC104_MAIN_ROWS),
      ..._allKeysInRows(PC104_NAV_ROWS),
      ..._allKeysInRows(PC104_NUMPAD_ROWS),
      ...PC104_EXTRA_KEY_GROUPS.flatMap(g => g.keys),
    ];
  }
  return _remapGroupsForTab(tabName).flatMap(g => g.keys);
}

function _staticKeysForRemapTab(tabName) {
  if (tabName === "pc104") return _keysForRemapTab("pc104");
  return (REMAP_TAB_GROUPS[tabName] || []).flatMap(g => g.keys);
}

function _explicitRemapKeySet() {
  const explicit = new Set();
  for (const tab of REMAP_TAB_ORDER) {
    for (const kc of _staticKeysForRemapTab(tab)) explicit.add(kc);
  }
  return explicit;
}

function _internalKeycodeGroup() {
  if (_availableKeycodes.length === 0) return null;
  const explicit = _explicitRemapKeySet();
  const keys = _availableKeycodes.filter(kc => !explicit.has(kc));
  if (keys.length === 0) return null;
  return {
    label: "内部キーコード（未分類・別名）",
    keys,
    perRow: 6,
  };
}

function _remapGroupsForTab(tabName) {
  if (tabName === "layer") return _remapLayerGroupsForCurrentLayer();
  if (tabName === "interaction") return [...INTERACTION_KEY_GROUPS, ..._remapInteractionGroups()];
  const groups = REMAP_TAB_GROUPS[tabName] || [];
  if (tabName !== "other") return groups;
  const internalGroup = _internalKeycodeGroup();
  return internalGroup ? [...groups, internalGroup] : groups;
}

function preferredRemapTabForKeycode(kc) {
  if (!kc) return "pc104";
  for (const tab of REMAP_TAB_ORDER) {
    if (_keysForRemapTab(tab).includes(kc)) return tab;
  }
  if (/^LT\(\d+,\s*KC_[A-Z0-9_]+\)$/.test(kc)) return "layer";
  if (/^(MO|TG|TO|DF|OSL)\(\d+\)$/.test(kc)) return "layer";
  if (/^(QK_LAYER_LOCK|QK_LLCK|DRAG_LOCK)$/.test(kc)) return "interaction";
  if (/^(TD|MORSE)\([A-Za-z0-9_.-]+\)$/.test(kc)) return "interaction";
  if (/^BT_/.test(kc)) return "bt";
  if (/^WIFI_/.test(kc)) return "wifi";
  if (/^KC_SH\d+$/.test(kc) || /^SCRIPT\(/.test(kc)) return "script";
  if (/^(RGB_|RM_)/.test(kc)) return "lighting";
  if (/^(KC_MS_|KC_WH_|KC_BTN|MS_)/.test(kc)) return "mouse";
  if (/^(KC_M|KC_AUDIO|KC_VOL|KC_BRI|KC_CALC|KC_W)/.test(kc)) return "media";
  if (/^KC_(CONN|CONSOLE|USB|BT|SHUTDOWN)/.test(kc)) return "system";
  return "other";
}

function keycodeLabel(kc) {
  if (!kc) return "";
  const ltMatch = /^LT\((\d+),\s*(KC_[A-Z0-9_]+)\)$/.exec(kc);
  if (ltMatch) return `LT${ltMatch[1]}(${keycodeLabel(ltMatch[2])})`;
  const pointerLabel = pointerKeycodeLabel(kc);
  if (pointerLabel) return pointerLabel;
  const lab = _labelsCache[kc];
  if (lab) {
    const lines = lab.split("\n");
    return lines[lines.length - 1].trim() || lines[0].trim();
  }
  return kc.replace(/^KC_/, "").slice(0, 8);
}

function _isRemapScriptKeycode(kc) {
  return /^KC_SH\d+$/.test(kc || "");
}

function _remapScriptEntryForKeycode(kc) {
  return _isRemapScriptKeycode(kc) ? _remapScriptEntries.get(kc) : null;
}

function _remapScriptSafetyIsDangerous(script) {
  return Boolean(script && script.safety && script.safety.dangerous);
}

function _remapScriptSafetySummary(script) {
  if (!_remapScriptSafetyIsDangerous(script)) return "";
  const safety = script.safety || {};
  const names = [
    ...(Array.isArray(safety.dangers) ? safety.dangers : []),
    ...(Array.isArray(safety.auto_dangers) ? safety.auto_dangers : []),
  ];
  return Array.from(new Set(names)).join(", ") || "dangerous";
}

function _decorateRemapScriptKey(keyEl, kc) {
  if (!_isRemapScriptKeycode(kc) || !keyEl) return;
  const script = _remapScriptEntryForKeycode(kc);
  const label = (script && script.label) || "";
  const source = (script && script.source) || "";
  const safetySummary = _remapScriptSafetySummary(script);
  const dangerous = _remapScriptSafetyIsDangerous(script);

  keyEl.classList.add("remap-key-script");
  keyEl.classList.toggle("remap-key-script-danger", dangerous);
  keyEl.dataset.scriptLabel = label;
  keyEl.dataset.scriptSource = source;
  keyEl.dataset.scriptSafety = safetySummary;
  keyEl.dataset.dangerous = dangerous ? "1" : "0";

  if (label || dangerous) {
    keyEl.textContent = "";
    const main = document.createElement("span");
    main.className = "remap-script-main";
    main.textContent = remapChoiceLabel(kc);
    keyEl.appendChild(main);

    if (label) {
      const meta = document.createElement("span");
      meta.className = "remap-script-meta";
      meta.textContent = label;
      keyEl.appendChild(meta);
    }

    if (dangerous) {
      const badge = document.createElement("span");
      badge.className = "remap-script-badge";
      badge.textContent = "DANGER";
      keyEl.appendChild(badge);
    }
  }

  const titleLines = [kc];
  if (label) titleLines.push(`Label: ${label}`);
  if (source) titleLines.push(`Source: ${source}`);
  if (dangerous) titleLines.push(`Danger: ${safetySummary}`);
  if (dangerous && script?.safety?.confirm_message) titleLines.push(script.safety.confirm_message);
  keyEl.title = titleLines.join("\n");
}

function remapChoiceLabel(kc) {
  const label = _labelsCache[kc] || window.HIDLOOM_EXTRA_KEY_LABELS?.[kc];
  if (label) {
    const lines = label.split("\n");
    return lines[lines.length - 1].trim() || lines[0].trim();
  }
  const interactionMatch = /^(TD|MORSE)\(([A-Za-z0-9_.-]+)\)$/.exec(kc);
  if (interactionMatch) return `${interactionMatch[1]} ${interactionMatch[2]}`;
  const ltChoice = /^LT\((\d+)\)$/.exec(kc);
  if (ltChoice) return `LT(${ltChoice[1]})`;
  const wrapperMatch = /^([A-Z0-9_]+)\((.+)\)$/.exec(kc);
  if (wrapperMatch) {
    const inner = wrapperMatch[2].replace(/\s+/g, "");
    return `${wrapperMatch[1]}(${remapChoiceLabel(inner)})`;
  }
  if (/^(MO|TG|TO|DF|OSL)\(\d+\)$/.test(kc)) return kc;
  return keycodeLabel(kc);
}

function normalizeDirectRemapAction(value) {
  return String(value || "").trim().replace(/[\s\u3000]+/g, "");
}

function setDirectRemapInputValue(value = "") {
  const input = document.getElementById("remap-direct-input");
  const status = document.getElementById("remap-direct-status");
  if (input) input.value = value;
  if (status) status.textContent = "";
}

function directRemapInputValue() {
  const input = document.getElementById("remap-direct-input");
  return normalizeDirectRemapAction(input ? input.value : "");
}

function applyDirectRemapInput() {
  const keycode = directRemapInputValue();
  const status = document.getElementById("remap-direct-status");
  if (!keycode) {
    if (status) status.textContent = "入力してください";
    showToast("QMK code を入力してください", true);
    return;
  }
  if (status) status.textContent = keycode;
  applyRemap(keycode);
}

function ensureRemapSearchFilter() {
  const popup = document.querySelector("#remap-popup .remap-popup-content");
  const tabs = document.querySelector("#remap-popup .remap-tabs");
  if (!popup || !tabs) return;
  if (!document.getElementById("remap-search")) {
    const wrap = document.createElement("div");
    wrap.className = "remap-search-row";

    const input = document.createElement("input");
    input.id = "remap-search";
    input.type = "search";
    input.placeholder = "keycode / label / alias を検索";
    input.autocomplete = "off";
    input.addEventListener("input", applyRemapSearchFilter);

    const count = document.createElement("span");
    count.id = "remap-search-count";

    const hint = document.createElement("span");
    hint.className = "remap-search-hint";
    hint.textContent = "Script は label / safety も見て選択";

    wrap.append(input, count, hint);
    popup.insertBefore(wrap, tabs.nextSibling);
  }
  _remapSearchReady = true;
}

function remapSearchNeedle(el) {
  const kc = el.dataset.keycode || el.title || "";
  const label = el.dataset.label || el.textContent || "";
  const group = el.dataset.group || "";
  const tab = el.dataset.tab || "";
  const scriptLabel = el.dataset.scriptLabel || "";
  const scriptSource = el.dataset.scriptSource || "";
  const scriptSafety = el.dataset.scriptSafety || "";
  const systemDefault = el.dataset.systemDefault === "1" ? "system default 初期配置 デフォルト" : "";
  const dangerous = el.dataset.dangerous === "1" ? "danger dangerous-script warning" : "";
  const cached = _labelsCache[kc] || "";
  return `${kc} ${label} ${cached} ${group} ${tab} ${scriptLabel} ${scriptSource} ${scriptSafety} ${systemDefault} ${dangerous}`.toLowerCase();
}

function applyRemapSearchFilter() {
  if (!_remapSearchReady) return;
  const input = document.getElementById("remap-search");
  const count = document.getElementById("remap-search-count");
  const query = (input && input.value ? input.value : "").trim().toLowerCase();
  let total = 0;
  let visible = 0;
  for (const key of document.querySelectorAll(".remap-tab-pane .remap-key")) {
    total += 1;
    const match = !query || remapSearchNeedle(key).includes(query);
    key.hidden = !match;
    if (match) visible += 1;
  }
  for (const group of document.querySelectorAll(".remap-other-group")) {
    const hasVisible = Array.from(group.querySelectorAll(".remap-key")).some((key) => !key.hidden);
    group.hidden = !hasVisible;
  }
  if (count) count.textContent = query ? `${visible}/${total}` : "";
}

function initRemapSearchFilter() {
  ensureRemapSearchFilter();
  applyRemapSearchFilter();
}

function _layerTapGroupForCurrentLayer() {
  const layerCount = Math.max(1, _allLayers.length || 0);
  const keys = [];
  for (let layer = 0; layer < layerCount; layer++) {
    if (layer !== _remapLayer) keys.push(`LT(${layer})`);
  }
  if (keys.length === 0) return null;
  return {
    label: "Layer Tap（短押しで次に選ぶキー、押している間だけ対象レイヤー）",
    keys,
    perRow: keys.length,
  };
}

function _interactionNamesFromSettings(key) {
  const entries = _remapInteractionSettings && _remapInteractionSettings[key];
  if (!entries || typeof entries !== "object" || Array.isArray(entries)) return [];
  return Object.keys(entries).filter((name) => /^[A-Za-z0-9_.-]{1,64}$/.test(name));
}

function _remapInteractionGroups() {
  if (_remapInteractionSettings === null) {
    return [
      { label: "Interaction設定を読み込み中", keys: [], perRow: 1 },
    ];
  }
  const tapDances = _interactionNamesFromSettings("tap_dances").map((name) => `TD(${name})`);
  const morses = _interactionNamesFromSettings("morse_behaviors").map((name) => `MORSE(${name})`);
  const groups = [
    { label: "Tap Dance（settings.interaction.tap_dances）", keys: tapDances, perRow: 4 },
    { label: "Morse（settings.interaction.morse_behaviors）", keys: morses, perRow: 4 },
  ];
  if (!tapDances.length && !morses.length) {
    groups.push({ label: "Interactionタブで Tap Dance / Morse を定義するとここに表示されます", keys: [], perRow: 1 });
  }
  return groups;
}

function _remapLayerGroupsForCurrentLayer() {
  const layerTapGroup = _layerTapGroupForCurrentLayer();
  return layerTapGroup ? [layerTapGroup, ...LAYER_KEY_GROUPS] : LAYER_KEY_GROUPS;
}

function _systemDefaultKeycodeForRemapTarget() {
  if (!_remapTarget || !_remapTarget.matrixKey) return "";
  const layer = _defaultLayers[_remapLayer];
  if (!layer || typeof layer !== "object") return "";
  return layer[_remapTarget.matrixKey] || "";
}

function _decorateSystemDefaultRemapKey(keyEl, kc) {
  if (!keyEl || !kc) return;
  const defaultKc = _systemDefaultKeycodeForRemapTarget();
  if (!defaultKc || kc !== defaultKc) return;
  keyEl.classList.add("system-default");
  keyEl.dataset.systemDefault = "1";
  keyEl.title = `${keyEl.title || kc}\nSystem default for this key`;
}

function _isLayerTapChoice(kc) {
  return /^LT\(\d+\)$/.test(kc || "");
}

function _layerTapChoiceLayer(kc) {
  const match = /^LT\((\d+)\)$/.exec(kc || "");
  return match ? Number(match[1]) : null;
}

function _currentLayerTapLayer() {
  const match = /^LT\((\d+),\s*KC_[A-Z0-9_]+\)$/.exec(_remapTarget?.currentKeycode || "");
  return match ? Number(match[1]) : null;
}

function _isAllowedLayerTapTapKey(kc) {
  return /^KC_[A-Z0-9_]+$/.test(kc || "") && !["KC_NONE", "KC_TRNS"].includes(kc);
}

function _setPendingLayerTap(layer) {
  _pendingLayerTap = { layer };
  _updateRemapTargetLabel();
  renderAllRemapTabs();
  showToast(`LT(${layer}) のタップキーを選択してください`);
}

function _clearPendingLayerTap() {
  _pendingLayerTap = null;
  _updateRemapTargetLabel();
}

function _formatRemapTargetLabel() {
  if (_remapChoicePicker) return _remapChoicePicker.title || "Action選択";
  if (!_remapTarget) return "キーコード変更";
  const pending = _pendingLayerTap ? ` / LT(${_pendingLayerTap.layer}) のタップキーを選択中` : "";
  return `キー (${_remapTarget.row},${_remapTarget.col}) → 現在: ${_remapTarget.currentKeycode}${pending}`;
}

function _updateRemapTargetLabel() {
  const label = document.getElementById("remap-target-label");
  if (label) label.textContent = _formatRemapTargetLabel();
}

function setRemapMode(enabled, options = {}) {
  const syncTab = options.syncTab !== false;
  remapMode = enabled;
  if (syncTab) {
    setActiveTab(enabled ? "keymap" : "keyboard", { syncMode: false });
  }
  if (enabled) clearLatchedModifiers();
  if (enabled) {
    _updateLayerSelector();
    updateKeyboardLayerDisplay(_remapLayer);
    refreshLayoutLayers().catch(e => showToast(`レイヤー再読込失敗: ${e.message}`, true));
  }
  const btn = document.getElementById("remap-toggle");
  if (btn) {
    btn.textContent = enabled ? "変更モード: ON" : "キーコード変更";
    btn.classList.toggle("active", enabled);
  }
  if (enabled && keyPassthroughEnabled) setKeyPassthrough(false);
  document.querySelectorAll(".key[data-matrix-row]").forEach(el => {
    el.classList.toggle("remap-mode", enabled);
  });
  if (typeof updateKeyboardMatrixCoordsOverlay === "function") {
    updateKeyboardMatrixCoordsOverlay();
  }
  if (!enabled) {
    closeRemapPopup();
    _remapLayer = 0;
    updateKeyboardDisplayForCurrentMode();
  }
}

function openRemapPopup(row, col, matrixKey) {
  const currentKc = layerKeycodeForMatrix(matrixKey, _remapLayer) || "KC_NONE";
  _remapChoicePicker = null;
  _remapTarget = { row, col, matrixKey, currentKeycode: currentKc };

  _updateLayerSelector();
  updateKeyboardLayerDisplay(_remapLayer);

  const label = document.getElementById("remap-target-label");
  _clearPendingLayerTap();
  if (label) label.textContent = _formatRemapTargetLabel();
  setDirectRemapInputValue(currentKc);

  renderAllRemapTabs();
  switchRemapTab(preferredRemapTabForKeycode(currentKc));

  document.getElementById("remap-popup").style.display = "flex";
  refreshLayoutLayers().catch(e => showToast(`レイヤー再読込失敗: ${e.message}`, true));
  fetchRemapScriptEntries(true)
    .then(_refreshRemapScriptChoices)
    .catch(e => showToast(`スクリプト情報読込失敗: ${e.message}`, true));
  fetchRemapInteractionSettings(true)
    .then(() => {
      const activeTab = document.querySelector(".remap-tab.active")?.dataset.tab || preferredRemapTabForKeycode(currentKc);
      renderAllRemapTabs();
      switchRemapTab(activeTab);
    })
    .catch(e => showToast(`Interaction情報読込失敗: ${e.message}`, true));
}

function closeRemapPopup() {
  _remapTarget = null;
  _pendingLayerTap = null;
  _remapChoicePicker = null;
  const popup = document.getElementById("remap-popup");
  if (popup) popup.style.display = "none";
}

function openRemapChoicePicker(options = {}) {
  const currentKeycode = String(options.currentKeycode || "KC_NONE");
  _remapChoicePicker = {
    currentKeycode,
    onSelect: typeof options.onSelect === "function" ? options.onSelect : null,
    title: options.title || "Action選択",
  };
  _remapTarget = { row: null, col: null, matrixKey: "", currentKeycode };
  _clearPendingLayerTap();
  _updateLayerSelector();
  updateKeyboardLayerDisplay(_remapLayer);
  setDirectRemapInputValue(currentKeycode);
  renderAllRemapTabs();
  switchRemapTab(preferredRemapTabForKeycode(currentKeycode));
  document.getElementById("remap-popup").style.display = "flex";
  fetchRemapScriptEntries(true)
    .then(_refreshRemapScriptChoices)
    .catch(e => showToast(`スクリプト情報読込失敗: ${e.message}`, true));
  fetchRemapInteractionSettings(true)
    .then(() => {
      const activeTab = document.querySelector(".remap-tab.active")?.dataset.tab || preferredRemapTabForKeycode(currentKeycode);
      renderAllRemapTabs();
      switchRemapTab(activeTab);
    })
    .catch(e => showToast(`Interaction情報読込失敗: ${e.message}`, true));
}

function _updateLayerSelector() {
  const sel = document.getElementById("remap-layer-sel");
  if (!sel) return;
  sel.innerHTML = "";
  const count = Math.max(1, _allLayers.length);
  for (let i = 0; i < count; i++) {
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = `Layer ${i}`;
    if (i === _remapLayer) opt.selected = true;
    sel.appendChild(opt);
  }
}

function updateRemapTargetForCurrentLayer() {
  if (!_remapTarget) return;
  const { matrixKey, row, col } = _remapTarget;
  const currentKc = layerKeycodeForMatrix(matrixKey, _remapLayer) || "KC_NONE";
  const previousTab = preferredRemapTabForKeycode(_remapTarget.currentKeycode);
  _remapTarget.currentKeycode = currentKc;
  const label = document.getElementById("remap-target-label");
  if (label) label.textContent = _formatRemapTargetLabel();
  setDirectRemapInputValue(currentKc);
  renderAllRemapTabs();
  const nextTab = preferredRemapTabForKeycode(currentKc);
  if (previousTab !== nextTab) switchRemapTab(nextTab);
}

function switchRemapTab(tabName) {
  document.querySelectorAll(".remap-tab").forEach(t => {
    t.classList.toggle("active", t.dataset.tab === tabName);
  });
  document.querySelectorAll(".remap-tab-pane").forEach(p => {
    p.style.display = (p.id === `remap-tab-${tabName}`) ? "" : "none";
  });
}

const REMAP_UNIT = 26;
const REMAP_GAP  = 2;

function _renderMiniKeyRows(rows, containerEl) {
  containerEl.innerHTML = "";
  for (const row of rows) {
    if (!row || row.length === 0) {
      const sp = document.createElement("div");
      sp.style.height = "4px";
      containerEl.appendChild(sp);
      continue;
    }
    const rowEl = document.createElement("div");
    rowEl.className = "remap-key-row";
    for (const entry of row) {
      if (entry === null) {
        const sep = document.createElement("div");
        sep.className = "remap-key-sep";
        sep.style.width = `${Math.round(0.5 * (REMAP_UNIT + REMAP_GAP))}px`;
        rowEl.appendChild(sep);
        continue;
      }
      const [kc, w] = entry;
      const keyEl = document.createElement("button");
      keyEl.className = "remap-key";
      keyEl.style.width = `${Math.round(w * (REMAP_UNIT + REMAP_GAP) - REMAP_GAP)}px`;
      keyEl.textContent = remapChoiceLabel(kc);
      keyEl.title = kc;
      keyEl.dataset.keycode = kc;
      keyEl.dataset.label = keycodeLabel(kc);
      keyEl.dataset.tab = "pc104";
      _decorateRemapScriptKey(keyEl, kc);
      _decorateSystemDefaultRemapKey(keyEl, kc);
      if (_pendingLayerTap && _isAllowedLayerTapTapKey(kc)) {
        keyEl.classList.add("layer-tap-candidate");
      }
      if (_remapTarget && kc === _remapTarget.currentKeycode) {
        keyEl.classList.add("current");
      }
      keyEl.addEventListener("click", () => applyRemap(kc));
      rowEl.appendChild(keyEl);
    }
    containerEl.appendChild(rowEl);
  }
}

function _renderRemapTabPc104() {
  const container = document.getElementById("remap-tab-pc104");
  if (!container) return;
  container.innerHTML = "";

  const wrap = document.createElement("div");
  wrap.className = "remap-pc104-wrap";

  const mainEl = document.createElement("div");
  mainEl.className = "remap-zone";
  _renderMiniKeyRows(PC104_MAIN_ROWS, mainEl);

  const rightEl = document.createElement("div");
  rightEl.className = "remap-right";

  const navEl = document.createElement("div");
  navEl.className = "remap-zone";
  _renderMiniKeyRows(PC104_NAV_ROWS, navEl);

  const numEl = document.createElement("div");
  numEl.className = "remap-zone";
  _renderMiniKeyRows(PC104_NUMPAD_ROWS, numEl);

  rightEl.appendChild(navEl);
  rightEl.appendChild(numEl);
  wrap.appendChild(mainEl);
  wrap.appendChild(rightEl);
  container.appendChild(wrap);
  _renderRemapKeyGroups(container, PC104_EXTRA_KEY_GROUPS, { append: true });
}

function _renderRemapKeyGroups(container, groups, options = {}) {
  if (!container) return;
  if (!options.append) container.innerHTML = "";
  for (const group of groups) {
    const groupEl = document.createElement("div");
    groupEl.className = "remap-other-group";

    const labelEl = document.createElement("div");
    labelEl.className = "remap-other-label";
    labelEl.textContent = group.label;
    groupEl.appendChild(labelEl);

    const keyRows = [];
    const perRow = Number(group.perRow) || group.keys.length;
    for (let i = 0; i < group.keys.length; i += perRow) {
      keyRows.push(group.keys.slice(i, i + perRow));
    }
    for (const keyRow of keyRows) {
      const keysEl = document.createElement("div");
      keysEl.className = "remap-other-keys";
      for (const kc of keyRow) {
        const keyEl = document.createElement("button");
        keyEl.className = "remap-key remap-key-other";
        keyEl.textContent = remapChoiceLabel(kc);
        keyEl.title = kc;
        keyEl.dataset.keycode = kc;
        keyEl.dataset.label = keycodeLabel(kc);
        keyEl.dataset.group = group.label || "";
        _decorateRemapScriptKey(keyEl, kc);
        _decorateSystemDefaultRemapKey(keyEl, kc);
        if (_pendingLayerTap && _isAllowedLayerTapTapKey(kc)) {
          keyEl.classList.add("layer-tap-candidate");
        }
        if (_isLayerTapChoice(kc) && _layerTapChoiceLayer(kc) === (_pendingLayerTap?.layer ?? _currentLayerTapLayer())) {
          keyEl.classList.add("current");
        }
        if (_remapTarget && kc === _remapTarget.currentKeycode) {
          keyEl.classList.add("current");
        }
        keyEl.addEventListener("click", () => applyRemap(kc));
        keysEl.appendChild(keyEl);
      }
      groupEl.appendChild(keysEl);
    }
    container.appendChild(groupEl);
  }
}

function _renderRemapTabGroups(tabName, groups) {
  _renderRemapKeyGroups(document.getElementById(`remap-tab-${tabName}`), _remapGroupsForTab(tabName));
  const pane = document.getElementById(`remap-tab-${tabName}`);
  for (const key of pane ? pane.querySelectorAll(".remap-key") : []) {
    key.dataset.tab = tabName;
  }
}

function renderAllRemapTabs() {
  _renderRemapTabPc104();
  for (const [tabName, groups] of Object.entries(REMAP_TAB_GROUPS)) {
    _renderRemapTabGroups(tabName, groups);
  }
  initRemapSearchFilter();
}

async function applyRemap(keycode) {
  if (!_remapTarget) return;
  if (_isLayerTapChoice(keycode)) {
    const layer = _layerTapChoiceLayer(keycode);
    if (layer === null) return;
    _setPendingLayerTap(layer);
    return;
  }
  if (_pendingLayerTap) {
    if (!_isAllowedLayerTapTapKey(keycode)) {
      showToast("LTのタップキーには通常キーを選択してください", true);
      return;
    }
    keycode = `LT(${_pendingLayerTap.layer},${keycode})`;
  }
  if (_remapChoicePicker) {
    const callback = _remapChoicePicker.onSelect;
    if (callback) callback(keycode);
    showToast(`✓ ${keycode}`);
    _clearPendingLayerTap();
    closeRemapPopup();
    return;
  }
  const { row, col, matrixKey } = _remapTarget;
  const layer = _remapLayer;

  try {
    const resp = await csrfFetch("/api/keymap", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ layer, row, col, action: keycode }),
    });
    const data = await resp.json();
    if (data.result === "ok") {
      while (_allLayers.length <= layer) {
        _allLayers.push({});
      }
      _allLayers[layer][matrixKey] = keycode;
      const keyEl = document.querySelector(
        `.key[data-matrix-row="${row}"][data-matrix-col="${col}"]`
      );
      if (keyEl) {
        const slot = _keyboardSlots.find(s => (
          s.matrix && s.matrix.row === row && s.matrix.col === col
        ));
        if (slot) {
          updateKeyElementForLayer(keyEl, slot, _remapLayer);
        }
      }
      showToast(`✓ (${row},${col}) → ${keycode}`);
      _clearPendingLayerTap();
      closeRemapPopup();
    } else {
      showToast(`エラー: ${data.msg || "不明なエラー"}`, true);
    }
  } catch (e) {
    showToast(`通信エラー: ${e.message}`, true);
  }
}

async function resetSavedKeymap() {
  const ok = window.confirm(
    "Vial / HTTP UI から保存したキー配置を消去し、config/default/keymap.json の初期配置へ戻します。よろしいですか？"
  );
  if (!ok) return;

  try {
    const resp = await csrfFetch("/api/keymap/reset", { method: "POST" });
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") {
      showToast(`初期化エラー: ${data.msg || resp.status}`, true);
      return;
    }
    await refreshLayoutLayers();
    _updateLayerSelector();
    updateRemapTargetForCurrentLayer();
    showToast("保存済みキー配置を初期化しました");
  } catch (e) {
    showToast(`通信エラー: ${e.message}`, true);
  }
}

async function refreshRemapAfterExternalKeymapUpdate() {
  await refreshLayoutLayers();
  _updateLayerSelector();
  updateRemapTargetForCurrentLayer();
}

let _toastTimer = null;

function showToast(msg, isError = false) {
  let toast = document.getElementById("remap-toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "remap-toast";
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.className = "remap-toast" + (isError ? " error" : "");
  toast.style.display = "block";
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { toast.style.display = "none"; }, 2500);
}

function initRemapPopupEvents() {
  const sel = document.getElementById("remap-layer-sel");
  if (sel) {
    sel.addEventListener("change", (e) => {
      _clearPendingLayerTap();
      _remapLayer = parseInt(e.target.value);
      updateKeyboardLayerDisplay(_remapLayer);
      updateRemapTargetForCurrentLayer();
    });
  }
  const directInput = document.getElementById("remap-direct-input");
  if (directInput) {
    directInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        applyDirectRemapInput();
      }
    });
  }
}

window.openRemapChoicePicker = openRemapChoicePicker;
window.applyDirectRemapInput = applyDirectRemapInput;
