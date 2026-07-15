/**
 * CQA02303v5 Virtual Keyboard
 *
 * 1. /api/layout から keyboard-layout.json + vial.json (keymap) を取得
 * 2. KLE JSON をパースしてキーを DOM に配置
 * 3. vial.json の keymap からキー座標 → matrix 座標 ("row,col") テーブルを構築
 * 4. クリック/タッチで WebSocket 経由で keydown/keyup を logicd へ転送
 * 5. ブラウザのキーボード入力を matrix 座標へ変換して転送（トグル ON 時）
 */

"use strict";

// -----------------------------------------------------------------------
// Constants
// -----------------------------------------------------------------------
const KEY_UNIT_PX = 54;   // 1u = 54px
const KEY_GAP_PX  = 4;    // キー間隔
const KEYBOARD_LAYER_DISPLAY_KEY = "hidloom-keyboard-display-layer";
const KEYBOARD_FIT_KEY = "hidloom-keyboard-fit-enabled";
const KEYBOARD_MATRIX_COORDS_KEY = "hidloom-keyboard-matrix-coords-enabled";
const TOUCH_FLICK_PREVIEW_KEY = "hidloom-touch-flick-preview-enabled";
const TOUCH_FLICK_SEND_KEY = "hidloom-touch-flick-send-enabled";
const KEYBOARD_LAYER_TINTS = [
  { tint: "rgba(22, 101, 170, 0.14)", border: "#8fb3d8" },
  { tint: "rgba(44, 132, 86, 0.14)", border: "#8ac29f" },
  { tint: "rgba(191, 128, 32, 0.16)", border: "#d9b36a" },
  { tint: "rgba(184, 71, 99, 0.14)", border: "#d99aac" },
  { tint: "rgba(98, 91, 172, 0.14)", border: "#aaa5dc" },
  { tint: "rgba(28, 135, 137, 0.14)", border: "#86c7c8" },
];
let _kleLayoutSource = [];
let _keyboardDisplayLayer = "active";
let _keyboardActiveLayers = [0];
let _keyboardActiveLayerTimer = null;
let _keyboardActiveLayerBusy = false;
let keyboardFitEnabled = false;
let keyboardMatrixCoordsEnabled = false;
let touchFlickPreviewEnabled = false;
let touchFlickSendEnabled = false;
let touchFlickTextDispatchQueue = Promise.resolve();
let touchFlickTextDispatchQueued = 0;
let _keyboardFitResizeObserver = null;
let _touchFlickMetadata = null;
let _touchFlickPointer = null;

function getVialEncoderLegend(label) {
  if (_controlMetadata.encoderDirections.size === 0 && _controlMetadata.encoderClickKeys.size === 0) {
    return null;
  }
  const parts = String(label || "").split("\n");
  const top = (parts[0] || "").trim();
  const center = (parts[parts.length - 1] || "").trim().toLowerCase();
  const match = /^(\d+),(\d+)$/.exec(top);
  if (!match || center !== "e") return null;
  return {
    index: Number(match[1]),
    action: Number(match[2]),
  };
}

function matrixForVialEncoderLegend(encoderLegend) {
  if (!encoderLegend) return null;
  const direction = encoderLegend.action === 0 ? "ccw" : "cw";
  const encoderActions = _controlMetadata.encoderActions.get(encoderLegend.index);
  const matrixKey = encoderActions ? encoderActions[direction] : null;
  if (matrixKey) {
    const [row, col] = matrixKey.split(",");
    return { row: parseInt(row), col: parseInt(col) };
  }
  if (encoderLegend.index !== 0) return null;
  for (const [matrixKey, mappedDirection] of _controlMetadata.encoderDirections) {
    if (mappedDirection !== direction) continue;
    const [row, col] = matrixKey.split(",");
    return { row: parseInt(row), col: parseInt(col) };
  }
  return null;
}

// -----------------------------------------------------------------------
// KLE parser
// Ref: https://github.com/nickcoutsos/keypos (simplified)
// -----------------------------------------------------------------------

/**
 * KLE JSON → KeySlot[] に変換する。
 * @returns {Array<{row,col,x,y,w,h,label}>}
 *   row/col はこの段階では KLE の行インデックス/列順。
 *   matrix 座標は後段で vial keymap から付与する。
 */
function parseKLE(layout) {
  const slots = [];
  let curY = 0;

  for (let ri = 0; ri < layout.length; ri++) {
    const row = layout[ri];
    let curX = 0;
    let w = 1, h = 1;
    let rowBaseY = curY;
    let isFirstKey = true;

    for (const item of row) {
      if (typeof item === "object" && item !== null) {
        if ("y" in item) curY += item.y;
        if ("x" in item) curX += item.x;
        if ("w" in item) w = item.w;
        if ("h" in item) h = item.h;
        if (isFirstKey) rowBaseY = curY;
        continue;
      }

      const label = String(item);
      const encoderLegend = getVialEncoderLegend(label);
      // 先頭トークン（\n で複数行のラベルの最初の行）
      const head = label.split("\n")[0].trim();

      // matrix 座標を先頭トークンから抽出（"row,col" 形式）
      const matrixMatch = /^(\d+),(\d+)$/.exec(head);
      const matrix = encoderLegend
        ? matrixForVialEncoderLegend(encoderLegend)
        : matrixMatch
          ? { row: parseInt(matrixMatch[1]), col: parseInt(matrixMatch[2]) }
          : null;

      slots.push({
        kleRow: ri,
        x: curX,
        y: curY,
        w,
        h,
        label,
        head,
        matrix,   // null の場合は後段で vial keymap から解決
      });

      curX += w;
      w = 1;
      h = 1;
      isFirstKey = false;
    }

    // 次の行へ
    curY = rowBaseY + 1;
  }

  return slots;
}

// -----------------------------------------------------------------------
// vial keymap → position テーブル構築
// vial keymap は KLE と同じ構造で、各キーの文字列が "row,col" になっている
// -----------------------------------------------------------------------

function buildMatrixTable(keymap) {
  // position_index → {row, col}
  // KLE と同じパーサーを使い、order 順に取得
  const table = [];
  let idx = 0;
  for (const row of keymap) {
    for (const item of row) {
      if (typeof item === "string") {
        const m = /^(\d+),(\d+)$/.exec(item.trim());
        if (m) {
          table[idx] = { row: parseInt(m[1]), col: parseInt(m[2]) };
        }
        idx++;
      }
    }
  }
  return table;
}

// -----------------------------------------------------------------------
// DOM レンダリング
// -----------------------------------------------------------------------

/**
 * キーラベルを DOM 要素に描画する。
 * "shifted\nnormal" 形式の場合は上下 2 段に分けて表示する。
 */
function renderKeyLabel(el, labelText) {
  const coordBadge = el.querySelector(":scope > .key-matrix-coord");
  el.innerHTML = "";
  const labelWrap = document.createElement("span");
  labelWrap.className = "key-label-main";
  if (labelText && labelText.includes("\n")) {
    const parts = labelText.split("\n");
    const top = document.createElement("span");
    top.className = "key-shifted";
    top.textContent = parts[0];
    const bottom = document.createElement("span");
    bottom.className = "key-normal";
    bottom.textContent = parts[1] || "";
    labelWrap.appendChild(top);
    labelWrap.appendChild(bottom);
  } else {
    labelWrap.textContent = labelText || "";
  }
  el.appendChild(labelWrap);
  if (coordBadge) el.appendChild(coordBadge);
}

function ensureKeyMatrixCoordBadge(el, row, col) {
  let badge = el.querySelector(":scope > .key-matrix-coord");
  if (!badge) {
    badge = document.createElement("span");
    badge.className = "key-matrix-coord";
    badge.setAttribute("aria-hidden", "true");
    el.appendChild(badge);
  }
  badge.textContent = `${row},${col}`;
}

function pointerKeycodeLabel(kc) {
  const pointerLabels = {
    KC_MS_U: "🖱↑",
    KC_MS_D: "🖱↓",
    KC_MS_L: "🖱←",
    KC_MS_R: "🖱→",
    KC_WH_U: "🛞↑",
    KC_WH_D: "🛞↓",
    KC_WH_L: "🛞←",
    KC_WH_R: "🛞→",
  };
  return pointerLabels[kc] || "";
}

function parseTouchFlickAction(kc) {
  const match = /^KC_FLICK\((\d+),(\d+)\)$/.exec(kc || "");
  if (!match) return null;
  const layer = Number.parseInt(match[1], 10);
  const index = Number.parseInt(match[2], 10);
  if (!Number.isFinite(layer) || !Number.isFinite(index)) return null;
  return { layer, index };
}

function touchFlickPadByAction(kc) {
  const parsed = parseTouchFlickAction(kc);
  if (!parsed) return null;
  const layers = _touchFlickMetadata?.layout?.layers || [];
  const layer = layers.find((entry) => entry.index === parsed.layer) || layers[parsed.layer];
  const pads = layer?.pads || [];
  return pads.find((pad) => pad.index === parsed.index) || null;
}

function keycodeDisplayLabel(kc, labels, fallbackLabel) {
  const flickPad = touchFlickPadByAction(kc);
  if (flickPad) return flickPad.label || "";
  const pointerLabel = pointerKeycodeLabel(kc);
  if (pointerLabel) return pointerLabel;
  const interactionMatch = /^(TD|MORSE)\(([A-Za-z0-9_.-]+)\)$/.exec(kc || "");
  if (interactionMatch) return `${interactionMatch[1]}\n${interactionMatch[2]}`;
  if (/^(MO|TG)\(\d+\)$/.test(kc || "")) return kc;
  if (kc && labels && kc in labels) return labels[kc];
  return fallbackLabel || "";
}

function ensureControlLabelSpan(el) {
  if (el.children.length > 0) return;
  const text = el.textContent || "";
  el.textContent = "";
  const span = document.createElement("span");
  span.className = "key-normal";
  span.textContent = text;
  el.appendChild(span);
}

function applySpecialKeyStyle(el, slot, matrixKey) {
  const encoderLegend = getVialEncoderLegend(slot.label);
  if (encoderLegend) {
    const direction = encoderLegend.action === 0 ? "ccw" : "cw";
    el.classList.add("control-label", "encoder-key", `encoder-${direction}`);
    el.title = `Rotary encoder ${encoderLegend.index} ${direction}`;
    ensureControlLabelSpan(el);
    return;
  }

  const joystickDirection = matrixKey ? _controlMetadata.joystickDirections.get(matrixKey) : null;
  if (joystickDirection) {
    el.classList.add("control-label", "joystick-key", `joystick-${joystickDirection}`);
    el.title = `Analog stick ${joystickDirection} (${matrixKey})`;
    ensureControlLabelSpan(el);
    return;
  }

  const encoderDirection = matrixKey ? _controlMetadata.encoderDirections.get(matrixKey) : null;
  if (encoderDirection) {
    el.classList.add("control-label", "encoder-key", `encoder-${encoderDirection}`);
    el.title = `Rotary encoder ${encoderDirection} (${matrixKey})`;
    ensureControlLabelSpan(el);
    return;
  }

  if (matrixKey && _controlMetadata.encoderClickKeys.has(matrixKey)) {
    el.classList.add("control-label", "encoder-click");
    el.title = `Rotary encoder click (${matrixKey})`;
    ensureControlLabelSpan(el);
    return;
  }

  if (!matrixKey && slot.head.toLowerCase() === "wheel") {
    el.classList.add("encoder-wheel");
    el.title = "Rotary encoder";
  }
}

function keyBox(el) {
  const left = Number.parseFloat(el.style.left) || 0;
  const top = Number.parseFloat(el.style.top) || 0;
  const width = Number.parseFloat(el.style.width) || 0;
  const height = Number.parseFloat(el.style.height) || 0;
  return { left, top, width, height, right: left + width, bottom: top + height };
}

function boundingBox(elements) {
  const boxes = elements.map(keyBox);
  const left = Math.min(...boxes.map(b => b.left));
  const top = Math.min(...boxes.map(b => b.top));
  const right = Math.max(...boxes.map(b => b.right));
  const bottom = Math.max(...boxes.map(b => b.bottom));
  return { left, top, width: right - left, height: bottom - top };
}

function addControlCluster(container, className, elements) {
  if (!elements.every(Boolean)) return null;
  const box = boundingBox(elements);
  const pad = 8;
  const cluster = document.createElement("div");
  cluster.className = `control-cluster ${className}`;
  cluster.style.left = `${box.left - pad}px`;
  cluster.style.top = `${box.top - pad}px`;
  cluster.style.width = `${box.width + pad * 2}px`;
  cluster.style.height = `${box.height + pad * 2}px`;
  container.appendChild(cluster);
  return { cluster, box, pad };
}

function createControlClusters(container) {
  container.querySelectorAll(".control-cluster").forEach(el => el.remove());

  const keyForMatrix = (matrixKey) => {
    const [row, col] = matrixKey.split(",");
    return container.querySelector(`.key[data-matrix-row="${row}"][data-matrix-col="${col}"]`);
  };

  addControlCluster(
    container,
    "joystick-control",
    Array.from(_controlMetadata.joystickDirections.keys()).map(keyForMatrix)
  );

  addControlCluster(
    container,
    "encoder-control",
    [
      ...Array.from(_controlMetadata.encoderDirections.keys()),
      ...Array.from(_controlMetadata.encoderClickKeys),
    ].map(keyForMatrix)
  );
}

function displayFallbackLabel(slot, keycode) {
  if (keycode) return keycodeLabel(keycode);
  return slot.label.split("\n").pop() || slot.label;
}

function layerKeycodeForMatrix(matrixKey, layer) {
  const layerMap = _allLayers[layer] || {};
  if (matrixKey in layerMap) return layerMap[matrixKey];
  return layer === 0 ? "" : "KC_TRNS";
}

function normalizeLayerStack(layers) {
  const layerCount = Math.max(1, _allLayers.length || 1);
  const normalized = [];
  for (const raw of Array.isArray(layers) ? layers : []) {
    const layer = Number.parseInt(raw, 10);
    if (!Number.isFinite(layer) || layer < 0 || layer >= layerCount) continue;
    if (!normalized.includes(layer)) normalized.push(layer);
  }
  if (!normalized.includes(0)) normalized.push(0);
  return normalized;
}

function effectiveKeycodeForMatrix(matrixKey, layers) {
  return effectiveKeyInfoForMatrix(matrixKey, layers).keycode;
}

function effectiveKeyInfoForMatrix(matrixKey, layers) {
  const stack = normalizeLayerStack(layers);
  const transparentLayers = [];
  for (const layer of stack) {
    const keycode = layerKeycodeForMatrix(matrixKey, layer);
    if (!keycode || keycode === "KC_TRNS") {
      if (layer !== 0) transparentLayers.push(layer);
      continue;
    }
    return { keycode, resolvedLayer: layer, transparentLayers, stack };
  }
  return { keycode: "", resolvedLayer: 0, transparentLayers, stack };
}

function layerVisualColors(layer) {
  if (layer <= 0) return { tint: "rgba(255,255,255,0)", border: "#bbb" };
  return KEYBOARD_LAYER_TINTS[(layer - 1) % KEYBOARD_LAYER_TINTS.length];
}

function keyboardDisplayLayerStack() {
  if (_keyboardDisplayLayer === "active") return normalizeLayerStack(_keyboardActiveLayers);
  const layer = Number.parseInt(_keyboardDisplayLayer, 10);
  if (!Number.isFinite(layer)) return [0];
  return normalizeLayerStack(layer === 0 ? [0] : [layer, 0]);
}

function keyboardDisplayLayerLabel() {
  const stack = keyboardDisplayLayerStack();
  if (_keyboardDisplayLayer === "active") {
    return `実機: ${stack.map(layer => `Layer ${layer}`).join(" > ")}`;
  }
  return `表示: ${stack.map(layer => `Layer ${layer}`).join(" > ")}`;
}

function updateKeyboardLayerStatus() {
  const status = document.getElementById("keyboard-layer-status");
  if (status) status.textContent = keyboardDisplayLayerLabel();
}

function updateKeyboardLayerSelector() {
  const sel = document.getElementById("keyboard-layer-sel");
  if (!sel) return;
  const current = _keyboardDisplayLayer;
  sel.innerHTML = "";

  const activeOpt = document.createElement("option");
  activeOpt.value = "active";
  activeOpt.textContent = "実機";
  sel.appendChild(activeOpt);

  const count = Math.max(1, _allLayers.length || 0);
  for (let layer = 0; layer < count; layer++) {
    const opt = document.createElement("option");
    opt.value = String(layer);
    opt.textContent = `Layer ${layer}`;
    sel.appendChild(opt);
  }

  const currentLayer = Number.parseInt(current, 10);
  _keyboardDisplayLayer = current === "active" || (Number.isFinite(currentLayer) && currentLayer >= 0 && currentLayer < count)
    ? current
    : "active";
  sel.value = _keyboardDisplayLayer;
  updateKeyboardLayerStatus();
}

function updateKeyElementForLayer(el, slot, layer) {
  const matrixKey = slot.matrix ? `${slot.matrix.row},${slot.matrix.col}` : null;
  const keycode = matrixKey ? layerKeycodeForMatrix(matrixKey, layer) : "";
  const rawLabel = keycodeDisplayLabel(
    keycode,
    _labelsCache,
    displayFallbackLabel(slot, keycode),
  );
  renderKeyLabel(el, rawLabel);
  el.dataset.flickLabel = rawLabel;
  clearKeyLayerVisualState(el);
  if (matrixKey) {
    el.dataset.keycode = keycode;
  }
}

function updateKeyboardLayerDisplay(layer = _remapLayer) {
  for (const slot of _keyboardSlots) {
    if (slot._el) updateKeyElementForLayer(slot._el, slot, layer);
  }
  updateKeyboardLayerStatus();
}

function clearKeyLayerVisualState(el) {
  el.classList.remove("layer-override", "layer-fallback");
  el.style.removeProperty("--layer-tint");
  el.style.removeProperty("--layer-border");
  if ("layerOriginalTitle" in el.dataset) {
    el.title = el.dataset.layerOriginalTitle;
    delete el.dataset.layerOriginalTitle;
  }
  delete el.dataset.resolvedLayer;
  delete el.dataset.transparentLayers;
}

function applyKeyLayerVisualState(el, info) {
  clearKeyLayerVisualState(el);
  const topLayer = info.stack.find(layer => layer !== 0) || 0;
  const isLayerOverride = info.resolvedLayer > 0;
  const fellThroughToBase = topLayer > 0 && info.resolvedLayer === 0;
  const visualLayer = isLayerOverride ? info.resolvedLayer : topLayer;

  if (visualLayer <= 0) return;

  const colors = layerVisualColors(visualLayer);
  el.style.setProperty("--layer-tint", colors.tint);
  el.style.setProperty("--layer-border", colors.border);
  el.dataset.resolvedLayer = String(info.resolvedLayer);
  el.dataset.transparentLayers = info.transparentLayers.join(",");
  if (!("layerOriginalTitle" in el.dataset)) {
    el.dataset.layerOriginalTitle = el.title || "";
  }

  if (isLayerOverride) {
    el.classList.add("layer-override");
    const passthrough = info.transparentLayers.length
      ? ` (${info.transparentLayers.map(layer => `Layer ${layer}`).join(", ")} は KC_TRNS)`
      : "";
    el.title = `Layer ${info.resolvedLayer} で置換${passthrough}`;
  } else if (fellThroughToBase) {
    el.classList.add("layer-fallback");
    el.title = `Layer ${topLayer} は KC_TRNS、Layer 0 から表示`;
  }
}

function updateKeyElementForEffectiveLayers(el, slot, layers) {
  const matrixKey = slot.matrix ? `${slot.matrix.row},${slot.matrix.col}` : null;
  const info = matrixKey
    ? effectiveKeyInfoForMatrix(matrixKey, layers)
    : { keycode: "", resolvedLayer: 0, transparentLayers: [], stack: [0] };
  const keycode = info.keycode;
  const rawLabel = keycodeDisplayLabel(
    keycode,
    _labelsCache,
    displayFallbackLabel(slot, keycode),
  );
  renderKeyLabel(el, rawLabel);
  el.dataset.flickLabel = rawLabel;
  applyKeyLayerVisualState(el, info);
  if (matrixKey) {
    el.dataset.keycode = keycode;
  }
}

function updateKeyboardEffectiveDisplay() {
  const layers = keyboardDisplayLayerStack();
  for (const slot of _keyboardSlots) {
    if (slot._el) updateKeyElementForEffectiveLayers(slot._el, slot, layers);
  }
  updateKeyboardLayerStatus();
}

function updateKeyboardDisplayForCurrentMode() {
  if (remapMode) {
    updateKeyboardLayerDisplay(_remapLayer);
  } else {
    updateKeyboardEffectiveDisplay();
  }
}

function updateKeyboardActiveLayers(active) {
  _keyboardActiveLayers = normalizeLayerStack(active?.all || active || [0]);
  if (!remapMode && _keyboardDisplayLayer === "active") {
    updateKeyboardEffectiveDisplay();
  } else {
    updateKeyboardLayerStatus();
  }
}

function setKeyboardDisplayLayer(value) {
  _keyboardDisplayLayer = value === "active" ? "active" : String(Number.parseInt(value, 10));
  try {
    window.localStorage.setItem(KEYBOARD_LAYER_DISPLAY_KEY, _keyboardDisplayLayer);
  } catch (_e) {
    // localStorage が使えない環境では現在のページ内だけで保持する
  }
  updateKeyboardLayerSelector();
  updateKeyboardDisplayForCurrentMode();
}

function initKeyboardDisplayLayerPreference() {
  const params = new URLSearchParams(window.location.search || "");
  if (params.get("keyboard") === "1") {
    _keyboardDisplayLayer = "active";
    try {
      window.localStorage.setItem(KEYBOARD_LAYER_DISPLAY_KEY, "active");
    } catch (_e) {
      // localStorage が使えない環境では現在のページ内だけで保持する
    }
    return;
  }
  try {
    _keyboardDisplayLayer = window.localStorage.getItem(KEYBOARD_LAYER_DISPLAY_KEY) || "active";
  } catch (_e) {
    _keyboardDisplayLayer = "active";
  }
}

async function fetchKeyboardActiveLayers() {
  if (_keyboardActiveLayerBusy || _keyboardDisplayLayer !== "active" || remapMode || _activeAppTab !== "keyboard") return;
  _keyboardActiveLayerBusy = true;
  try {
    const resp = await fetch("/api/keymap/active");
    const data = await resp.json();
    if (data.active) updateKeyboardActiveLayers(data.active);
  } catch (_e) {
    // 次のポーリングで復帰する。
  } finally {
    _keyboardActiveLayerBusy = false;
  }
}

function startKeyboardActiveLayerPolling(intervalMs = 250) {
  if (_keyboardActiveLayerTimer) return;
  _keyboardActiveLayerTimer = setInterval(fetchKeyboardActiveLayers, intervalMs);
}

window.fetchKeyboardActiveLayers = fetchKeyboardActiveLayers;

function updateKeyboardFitScale() {
  const stage = document.getElementById("keyboard-stage");
  const keyboard = document.getElementById("keyboard");
  if (!stage || !keyboard) return;

  if (!keyboardFitEnabled) {
    keyboard.style.removeProperty("transform");
    keyboard.style.removeProperty("position");
    keyboard.style.removeProperty("left");
    keyboard.style.removeProperty("top");
    stage.style.removeProperty("height");
    stage.style.removeProperty("width");
    return;
  }

  const baseWidth = Number.parseFloat(keyboard.dataset.baseWidth || keyboard.style.width || "0");
  const baseHeight = Number.parseFloat(keyboard.dataset.baseHeight || keyboard.style.height || "0");
  if (!baseWidth || !baseHeight) return;

  const availableWidth = stage.clientWidth || stage.parentElement?.clientWidth || baseWidth;
  const availableHeight = stage.clientHeight || window.innerHeight || baseHeight;
  const demoMode = document.body.classList.contains("keyboard-demo-mode");
  const fitPadding = demoMode ? 8 : 0;
  const topPadding = demoMode ? 2 : fitPadding;
  const widthScale = (availableWidth - fitPadding * 2) / baseWidth;
  const heightScale = (availableHeight - topPadding - fitPadding) / baseHeight;
  const scale = Math.min(1.5, Math.max(0.25, Math.min(widthScale, heightScale)));
  const left = Math.max(fitPadding, Math.floor((availableWidth - baseWidth * scale) / 2));
  const top = Math.max(topPadding, Math.floor((availableHeight - baseHeight * scale) / 2));
  keyboard.style.transform = `scale(${scale})`;
  keyboard.style.position = "absolute";
  keyboard.style.left = `${left}px`;
  keyboard.style.top = `${top}px`;
  stage.style.height = document.body.classList.contains("keyboard-demo-mode")
    ? `${availableHeight}px`
    : `${Math.ceil(baseHeight * scale)}px`;
  stage.style.width = "100%";
}

function setKeyboardFitEnabled(enabled) {
  keyboardFitEnabled = Boolean(enabled);
  const container = document.getElementById("keyboard-container");
  const btn = document.getElementById("keyboard-fit-toggle");
  document.body.classList.toggle("keyboard-demo-mode", keyboardFitEnabled);
  if (container) container.classList.toggle("keyboard-fit-enabled", keyboardFitEnabled);
  if (btn) {
    btn.textContent = keyboardFitEnabled ? "X" : "全体表示: OFF";
    btn.classList.toggle("active", keyboardFitEnabled);
    btn.title = keyboardFitEnabled ? "全体表示を閉じる" : "キーボードだけを全体表示";
    btn.setAttribute("aria-label", btn.title);
  }
  try {
    window.localStorage.setItem(KEYBOARD_FIT_KEY, keyboardFitEnabled ? "1" : "0");
  } catch (_e) {
    // localStorage が使えない環境では現在のページ内だけで保持する
  }
  updateKeyboardFitScale();
  refreshKeyboardControlsOverlay();
}

function refreshKeyboardControlsOverlay() {
  const fitBtn = document.getElementById("overlay-fit-btn");
  const flickBtn = document.getElementById("overlay-flick-btn");
  const flickSendBtn = document.getElementById("overlay-flick-send-btn");
  const passthroughBtn = document.getElementById("overlay-passthrough-btn");
  const matrixBtn = document.getElementById("overlay-matrix-btn");
  const shutdownConfirm = document.getElementById("overlay-shutdown-confirm");
  const shutdownBtn = document.getElementById("overlay-shutdown-btn");
  if (fitBtn) {
    fitBtn.textContent = keyboardFitEnabled ? "Show full UI" : "Keyboard only";
    fitBtn.classList.toggle("active", keyboardFitEnabled);
  }
  if (flickBtn) {
    flickBtn.textContent = touchFlickPreviewEnabled ? "Flick preview: ON" : "Flick preview: OFF";
    flickBtn.classList.toggle("active", touchFlickPreviewEnabled);
    flickBtn.disabled = !(_touchFlickMetadata?.available);
    flickBtn.title = _touchFlickMetadata?.available ? "4.3 inch flick preview" : "osoyoo-4.3 profile only";
  }
  if (flickSendBtn) {
    flickSendBtn.textContent = touchFlickSendEnabled ? "Flick send: ON" : "Flick send: OFF";
    flickSendBtn.classList.toggle("active", touchFlickSendEnabled);
    flickSendBtn.classList.toggle("danger", touchFlickSendEnabled);
    flickSendBtn.disabled = !touchFlickCanEnableSend();
    flickSendBtn.title = touchFlickCanEnableSend() ? "Send flick keycode/text actions" : "Flick preview and dispatch policy required";
  }
  if (passthroughBtn) {
    passthroughBtn.textContent = keyPassthroughEnabled ? "Passthrough: ON" : "Passthrough: OFF";
    passthroughBtn.classList.toggle("active", keyPassthroughEnabled);
  }
  if (matrixBtn && typeof window.isMatrixTesterEnabled === "function") {
    const enabled = window.isMatrixTesterEnabled();
    matrixBtn.textContent = enabled ? "Matrix tester: ON" : "Matrix tester: OFF";
    matrixBtn.classList.toggle("active", enabled);
  }
  if (shutdownConfirm?.hidden && shutdownBtn) {
    shutdownBtn.hidden = false;
    shutdownBtn.disabled = false;
    shutdownBtn.textContent = "Shutdown";
    shutdownBtn.removeAttribute("title");
  }
}

function openKeyboardControlsOverlay() {
  const overlay = document.getElementById("keyboard-controls-overlay");
  if (!overlay) return;
  refreshKeyboardControlsOverlay();
  overlay.hidden = false;
}

function closeKeyboardControlsOverlay() {
  const overlay = document.getElementById("keyboard-controls-overlay");
  hideShutdownConfirm();
  if (overlay) overlay.hidden = true;
}

function toggleKeyboardControlsOverlay() {
  const overlay = document.getElementById("keyboard-controls-overlay");
  if (!overlay) return;
  if (overlay.hidden) {
    openKeyboardControlsOverlay();
  } else {
    closeKeyboardControlsOverlay();
  }
}

function showShutdownConfirm() {
  cancelTouchFlickPreview("shutdown_menu");
  const shutdownBtn = document.getElementById("overlay-shutdown-btn");
  const confirmEl = document.getElementById("overlay-shutdown-confirm");
  const confirmBtn = document.getElementById("overlay-shutdown-confirm-btn");
  if (shutdownBtn) shutdownBtn.hidden = true;
  if (confirmEl) confirmEl.hidden = false;
  if (confirmBtn) {
    confirmBtn.disabled = false;
    confirmBtn.textContent = "Shutdown now";
    confirmBtn.removeAttribute("title");
    confirmBtn.focus();
  }
}

function hideShutdownConfirm() {
  const shutdownBtn = document.getElementById("overlay-shutdown-btn");
  const confirmEl = document.getElementById("overlay-shutdown-confirm");
  const confirmBtn = document.getElementById("overlay-shutdown-confirm-btn");
  if (confirmEl) confirmEl.hidden = true;
  if (confirmBtn) {
    confirmBtn.disabled = false;
    confirmBtn.textContent = "Shutdown now";
    confirmBtn.removeAttribute("title");
  }
  if (shutdownBtn) {
    shutdownBtn.hidden = false;
    shutdownBtn.disabled = false;
    shutdownBtn.textContent = "Shutdown";
    shutdownBtn.removeAttribute("title");
  }
}

async function shutdownSystemFromOverlay() {
  const btn = document.getElementById("overlay-shutdown-confirm-btn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Shutting down...";
  }
  try {
    const resp = await csrfFetch("/api/system/shutdown", { method: "POST" });
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") {
      throw new Error(data.msg || `HTTP ${resp.status}`);
    }
    closeKeyboardControlsOverlay();
  } catch (e) {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Shutdown now";
      btn.title = `Shutdown failed: ${e.message}`;
    }
    console.warn("Shutdown failed", e);
  }
}

window.refreshKeyboardControlsOverlay = refreshKeyboardControlsOverlay;
window.openKeyboardControlsOverlay = openKeyboardControlsOverlay;
window.closeKeyboardControlsOverlay = closeKeyboardControlsOverlay;
window.toggleKeyboardControlsOverlay = toggleKeyboardControlsOverlay;
window.showShutdownConfirm = showShutdownConfirm;
window.hideShutdownConfirm = hideShutdownConfirm;
window.shutdownSystemFromOverlay = shutdownSystemFromOverlay;

function touchFlickDirection(dx, dy, threshold) {
  const absX = Math.abs(dx);
  const absY = Math.abs(dy);
  if (Math.max(absX, absY) < threshold) return "center";
  if (absY > absX) return dy < 0 ? "up" : "down";
  return dx < 0 ? "left" : "right";
}

function resolveTouchFlickPreviewAction(pad, direction) {
  const requestedDirection = direction || "center";
  const actions = pad?.actions || {};
  const resolvedDirection = actions[requestedDirection] ? requestedDirection : "center";
  const action = actions[resolvedDirection] || null;
  return {
    kind: "flick_pad",
    key: pad?.key || "",
    layer: pad?.layer,
    index: pad?.index,
    label: pad?.label || pad?.key || "",
    requestedDirection,
    resolvedDirection,
    action,
    dispatch: "preview_noop",
  };
}

function touchFlickPadOutputFamily(pad) {
  const actions = Object.values(pad?.actions || {});
  if (actions.some((action) => action?.text_family === "named_send_string")) return "named-text";
  if (actions.some((action) => action?.output === "preview")) return "preview";
  if (actions.some((action) => action?.output === "text")) return "text";
  return "keycode";
}

function touchFlickPadActionTitle(pad) {
  const actions = pad?.actions || {};
  const parts = [];
  for (const direction of ["center", "up", "right", "down", "left"]) {
    const action = actions[direction];
    if (!action?.action) continue;
    const family = action.text_family ? ` ${action.text_family}` : action.output ? ` ${action.output}` : "";
    const preflight = action.preflight_route ? " preflight" : "";
    parts.push(`${direction}: ${action.action}${family}${preflight}`);
  }
  return parts.join("\n");
}

function resolveTouchFlickImePreviewAction(control) {
  return {
    kind: "ime_control",
    key: control?.key || "",
    label: control?.label || control?.key || "",
    role: control?.role || "",
    action: {
      label: control?.label || control?.key || "",
      action: control?.action || "",
      output: control?.output || "keycode",
    },
    dispatch: "preview_noop",
  };
}

function touchFlickResolveRoute() {
  return _touchFlickMetadata?.action_resolution?.resolve_route || "/api/touch-panel/flick/resolve";
}

function touchFlickDispatchRoute() {
  return _touchFlickMetadata?.dispatch_policy?.dispatch_route
    || _touchFlickMetadata?.action_resolution?.dispatch_route
    || "/api/touch-panel/flick/dispatch";
}

function touchFlickCompositionPlanRoute() {
  return _touchFlickMetadata?.composition_mode?.plan_route
    || _touchFlickMetadata?.action_resolution?.composition_plan_route
    || "/api/touch-panel/flick/composition-plan";
}

function touchFlickDispatchPolicy() {
  return _touchFlickMetadata?.dispatch_policy || {};
}

function touchFlickCanEnableSend() {
  const policy = touchFlickDispatchPolicy();
  return Boolean(_touchFlickMetadata?.available && policy.browser_may_call_dispatch === true);
}

function touchFlickBrowserDispatchEnabled() {
  const policy = touchFlickDispatchPolicy();
  return touchFlickCanEnableSend() && (policy.browser_default_enabled === true || touchFlickSendEnabled);
}

function touchFlickDispatchBlockedReason(event) {
  if (!touchFlickCanEnableSend()) return "browser_dispatch_disabled";
  if (!touchFlickSendEnabled && touchFlickDispatchPolicy().browser_default_enabled !== true) return "local_send_disabled";
  if (!event || event.enabled !== true || event.dispatch !== "tap_action") return event?.reason || "dispatch_event_not_enabled";
  const allowedOutput = touchFlickDispatchPolicy()?.allowed_event?.output || "keycode";
  if (allowedOutput === "keycode" && !["keycode", "text"].includes(event.output)) return "output_not_dispatchable";
  return "";
}

function touchFlickTextPreflightRoute() {
  return touchFlickDispatchPolicy()?.text_output_preflight_route
    || _touchFlickMetadata?.unicode_prerequisite?.plan_route
    || "/api/interaction/text-send-safety/plan";
}

async function touchFlickTextDispatchPreflight(event, envelope = null) {
  if (event?.output !== "text") return { blockingReason: "", plan: null };
  const composition = envelope?.composition_plan || null;
  if (composition?.available === true) return { blockingReason: "", plan: null };
  const reasons = Array.isArray(composition?.blocking_reasons) ? composition.blocking_reasons : [];
  return { blockingReason: reasons[0] || "composition_plan_unavailable", plan: null };
}

function enqueueTouchFlickTextDispatch(runDispatch) {
  touchFlickTextDispatchQueued += 1;
  const queuedDispatch = touchFlickTextDispatchQueue
    .catch(() => {})
    .then(async () => {
      try {
        return await runDispatch();
      } finally {
        touchFlickTextDispatchQueued = Math.max(0, touchFlickTextDispatchQueued - 1);
      }
    });
  touchFlickTextDispatchQueue = queuedDispatch.catch(() => {});
  return queuedDispatch;
}

function touchFlickPadByLabel(label) {
  const text = String(label || "").split("\n").pop() || "";
  const pads = _touchFlickMetadata?.layout?.pads || [];
  return pads.find((pad) => pad.label === text) || null;
}

function touchFlickHostImeWarning() {
  const profile = _touchFlickMetadata?.host_ime_profile || {};
  if (profile.explicit_profile_required && !profile.active_profile) {
    return "host-profile-required";
  }
  return profile.warning || "";
}

function touchFlickLocalDispatchEnvelope(resolved, reason = "resolve_endpoint_unavailable") {
  const action = resolved?.action || {};
  return {
    result: "local_preview",
    resolved_action: resolved,
    dispatch_event: {
      source: "touch_panel_flick",
      kind: resolved?.kind || "",
      key: resolved?.key || "",
      layer: resolved?.layer,
      index: resolved?.index,
      action: action.action || "",
      output: action.output || "preview",
      dispatch: "preview_noop",
      enabled: false,
      reason,
    },
  };
}

async function resolveTouchFlickDispatchEnvelope(payload, fallbackResolved) {
  try {
    const resp = await csrfFetch(touchFlickResolveRoute(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) throw new Error(`resolve failed: ${resp.status}`);
    const data = await resp.json();
    if (data?.result !== "ok" || !data?.dispatch_event?.action) {
      throw new Error("resolve returned invalid dispatch envelope");
    }
    return data;
  } catch (err) {
    console.warn("Touch flick resolve fallback", err);
    return touchFlickLocalDispatchEnvelope(fallbackResolved);
  }
}

async function resolveTouchFlickCompositionPlan(payload) {
  try {
    const resp = await csrfFetch(touchFlickCompositionPlanRoute(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) return null;
    return await resp.json();
  } catch (err) {
    console.warn("Touch flick composition plan failed", err);
    return null;
  }
}

function touchFlickDispatchPayload(envelope) {
  const payload = { event: envelope?.dispatch_event };
  delete payload.composition_plan;
  delete payload.compositionPlan;
  return payload;
}

async function dispatchTouchFlickEnvelope(envelope) {
  const event = envelope?.dispatch_event;
  if (event?.output === "text") {
    return enqueueTouchFlickTextDispatch(() => dispatchTouchFlickEnvelopeNow(envelope));
  }
  return dispatchTouchFlickEnvelopeNow(envelope);
}

async function dispatchTouchFlickEnvelopeNow(envelope) {
  const event = envelope?.dispatch_event;
  const blockedReason = touchFlickDispatchBlockedReason(event);
  if (blockedReason) return { result: "blocked", reason: blockedReason };
  const textPreflight = await touchFlickTextDispatchPreflight(event, envelope);
  if (textPreflight?.plan && envelope) envelope.text_send_plan = textPreflight.plan;
  if (textPreflight.blockingReason) return { result: "blocked", reason: textPreflight.blockingReason };
  const resp = await csrfFetch(touchFlickDispatchRoute(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(touchFlickDispatchPayload(envelope)),
  });
  const data = await resp.json();
  if (!resp.ok || data?.result !== "ok") {
    throw new Error(data?.reason || data?.msg || `dispatch failed: ${resp.status}`);
  }
  return data;
}

function beginKeyboardFlickPointer(el, pad, e) {
  const threshold = _touchFlickMetadata?.event_boundary?.threshold_px || 28;
  const overlay = renderKeyboardFlickCandidates(el, pad, "center");
  _touchFlickPointer = {
    pointerId: e.pointerId,
    startX: e.clientX,
    startY: e.clientY,
    direction: "center",
    threshold,
    pad,
    layer: pad?.layer,
    index: pad?.index,
    el,
    overlay,
    keyboardKey: true,
  };
  el.classList.add("active", "pressed", "flicking");
  el.dataset.activePointerId = String(e.pointerId);
  const captureTarget = overlay || el;
  if (captureTarget.setPointerCapture) {
    try {
      captureTarget.setPointerCapture(e.pointerId);
    } catch (_err) {
      // Pointer capture can fail after browser-side cancellation.
    }
  }
}

function moveKeyboardFlickPointer(e) {
  if (!_touchFlickPointer || !_touchFlickPointer.keyboardKey || _touchFlickPointer.pointerId !== e.pointerId) return false;
  e.preventDefault();
  _touchFlickPointer.direction = touchFlickDirection(
    e.clientX - _touchFlickPointer.startX,
    e.clientY - _touchFlickPointer.startY,
    _touchFlickPointer.threshold,
  );
  renderKeyboardFlickCandidates(_touchFlickPointer.el, _touchFlickPointer.pad, _touchFlickPointer.direction);
  return true;
}

async function finishKeyboardFlickPointer(e) {
  if (!_touchFlickPointer || !_touchFlickPointer.keyboardKey || _touchFlickPointer.pointerId !== e.pointerId) return false;
  e.preventDefault();
  const pointer = _touchFlickPointer;
  _touchFlickPointer = null;
  delete pointer.el.dataset.activePointerId;
  pointer.el.classList.remove("active", "pressed", "flicking");
  clearKeyboardFlickCandidates(pointer.el);
  const direction = pointer.direction || "center";
  const resolved = resolveTouchFlickPreviewAction(pointer.pad, direction);
  const envelope = await resolveTouchFlickDispatchEnvelope(
    {
      kind: "flick_pad",
      key: pointer.pad?.key || "",
      layer: pointer.layer,
      index: pointer.index,
      direction,
    },
    resolved,
  );
  envelope.composition_plan = await resolveTouchFlickCompositionPlan({
    kind: "flick_pad",
    key: pointer.pad?.key || "",
    layer: pointer.layer,
    index: pointer.index,
    direction,
  });
  const dispatchResult = await dispatchTouchFlickEnvelope(envelope);
  if (dispatchResult?.result === "blocked") {
    envelope.dispatch_result = dispatchResult;
  }
  updateTouchFlickDispatchPreview(envelope, resolved, direction);
  return true;
}

function keyboardFlickCandidateLabel(pad, direction) {
  const resolved = resolveTouchFlickPreviewAction(pad, direction);
  return resolved.action?.label || "";
}

function renderKeyboardFlickCandidates(el, pad, activeDirection) {
  const stage = document.getElementById("keyboard-stage");
  const keyboard = document.getElementById("keyboard");
  if (!stage || !keyboard) return null;
  let wrap = stage.querySelector(":scope > .key-flick-candidates");
  if (!wrap) {
    wrap = document.createElement("div");
    wrap.className = "key-flick-candidates";
    stage.appendChild(wrap);
  }
  const signature = `${pad?.layer ?? ""}:${pad?.index ?? ""}:${pad?.key ?? ""}`;
  const keyRect = el.getBoundingClientRect();
  const stageRect = stage.getBoundingClientRect();
  const unitW = Math.max(1, keyRect.width);
  const unitH = Math.max(1, keyRect.height);
  wrap.style.left = `${keyRect.left - stageRect.left + stage.scrollLeft - unitW - KEY_GAP_PX}px`;
  wrap.style.top = `${keyRect.top - stageRect.top + stage.scrollTop - unitH - KEY_GAP_PX}px`;
  wrap.style.width = `${unitW * 3 + KEY_GAP_PX * 2}px`;
  wrap.style.height = `${unitH * 3 + KEY_GAP_PX * 2}px`;
  wrap.style.setProperty("--flick-unit-w", `${unitW}px`);
  wrap.style.setProperty("--flick-unit-h", `${unitH}px`);
  wrap.style.setProperty("--flick-gap", `${KEY_GAP_PX}px`);
  wrap.dataset.activeDirection = activeDirection || "center";
  if (wrap.dataset.padSignature === signature && wrap.childElementCount > 0) {
    return wrap;
  }
  wrap.dataset.padSignature = signature;
  wrap.innerHTML = "";
  for (const direction of ["hit", "center"]) {
    const item = document.createElement("span");
    item.className = `key-flick-${direction}`;
    item.setAttribute("aria-hidden", "true");
    wrap.appendChild(item);
  }
  for (const direction of ["up", "right", "down", "left"]) {
    const label = keyboardFlickCandidateLabel(pad, direction);
    if (!label) continue;
    const item = document.createElement("span");
    item.className = `key-flick-candidate key-flick-${direction}`;
    item.dataset.direction = direction;
    item.textContent = label;
    wrap.appendChild(item);
  }
  const relayPointer = (event) => {
    if (event.type === "pointermove") {
      moveKeyboardFlickPointer(event);
    } else if (event.type === "pointerup" || event.type === "pointercancel") {
      finishKeyboardFlickPointer(event).catch((err) => console.warn("Keyboard flick dispatch failed", err));
    }
  };
  wrap.addEventListener("pointermove", relayPointer);
  wrap.addEventListener("pointerup", relayPointer);
  wrap.addEventListener("pointercancel", relayPointer);
  return wrap;
}

function clearKeyboardFlickCandidates(el) {
  document.getElementById("keyboard-stage")?.querySelector(":scope > .key-flick-candidates")?.remove();
}

function updateTouchFlickDispatchPreview(envelope, fallbackResolved, direction = "center") {
  const resolved = envelope?.resolved_action || fallbackResolved || {};
  const event = envelope?.dispatch_event || {};
  const label = resolved.label || resolved.key || event.key || "";
  const resolvedDirection = resolved.resolved_direction || resolved.resolvedDirection || direction;
  const action = event.action || resolved.action?.action || "";
  const dispatch = event.dispatch || "preview_noop";
  const reason = event.reason ? ` (${event.reason})` : "";
  const dispatchResult = envelope?.dispatch_result;
  const policy = touchFlickBrowserDispatchEnabled() ? "send-ready" : "send-off";
  const result = dispatchResult?.result
    ? ` / ${dispatchResult.result}${dispatchResult.reason ? `:${dispatchResult.reason}` : ""}`
    : "";
  const textPlan = envelope?.text_send_plan || null;
  const textDry = textPlan?.tap_dry_run || {};
  const textReasons = Array.isArray(textPlan?.blocking_reasons) ? textPlan.blocking_reasons : [];
  const textPlanText = textPlan
    ? textPlan.real_send_allowed
      ? ` / text-plan:ready${textDry.available ? `/taps:${Number(textDry.sequence_count || 0)}` : ""}`
      : ` / text-plan:${textReasons.join(",") || "blocked"}`
    : "";
  const composition = envelope?.composition_plan;
  const compositionText = composition?.available
    ? ` / romaji:${(composition.tap_sequence || []).map((tap) => tap.key).filter(Boolean).join("+")}`
    : composition?.not_applicable
      ? ""
      : composition?.blocking_reasons?.length
      ? ` / composition:${composition.blocking_reasons.join(",")}`
      : "";
  updateTouchFlickPreview(`${label} ${resolvedDirection}: ${action} is ${dispatch}${reason} / ${policy}${result}${textPlanText}${compositionText}`, direction);
}

function updateTouchFlickStatus(text) {
  const status = document.getElementById("touch-flick-status");
  if (status) status.textContent = text;
}

function touchFlickStatusText(metadata, dispatchState) {
  const profile = metadata?.profile_guard?.profile || "missing";
  const namedTextCount = Number(metadata?.named_text?.entry_count || 0);
  const namedText = namedTextCount ? ` / named-text:${namedTextCount}` : "";
  const hostWarning = touchFlickHostImeWarning();
  const warningText = hostWarning ? ` / ${hostWarning}` : "";
  return metadata?.available ? `profile ${profile} / ${dispatchState}${namedText}${warningText}` : `guard: ${profile}`;
}

function updateTouchFlickPreview(text, direction = "center") {
  const preview = document.getElementById("touch-flick-preview");
  if (!preview) return;
  preview.textContent = text;
  preview.dataset.direction = direction;
}

function cancelTouchFlickPreview(reason = "cancel") {
  const active = document.querySelector(".touch-flick-pad.active");
  if (active) active.classList.remove("active");
  _touchFlickPointer = null;
  updateTouchFlickPreview(`preview/no-op (${reason})`);
}

function setTouchFlickPreviewEnabled(enabled) {
  touchFlickPreviewEnabled = Boolean(enabled && _touchFlickMetadata?.available);
  const panel = document.getElementById("touch-flick-panel");
  const btn = document.getElementById("touch-flick-toggle");
  document.body.classList.toggle("touch-flick-preview-mode", touchFlickPreviewEnabled);
  if (panel) panel.hidden = !touchFlickPreviewEnabled || document.body.classList.contains("keyboard-demo-mode");
  if (btn) {
    btn.textContent = touchFlickPreviewEnabled ? "Flick preview: ON" : "Flick preview: OFF";
    btn.classList.toggle("active", touchFlickPreviewEnabled);
    btn.disabled = !(_touchFlickMetadata?.available);
    btn.title = _touchFlickMetadata?.available ? "4.3 inch flick preview" : "osoyoo-4.3 profile only";
  }
  try {
    window.localStorage.setItem(TOUCH_FLICK_PREVIEW_KEY, touchFlickPreviewEnabled ? "1" : "0");
  } catch (_e) {
    // localStorage が使えない環境では現在のページ内だけで保持する
  }
  if (!touchFlickPreviewEnabled) cancelTouchFlickPreview("hidden");
  refreshKeyboardControlsOverlay();
}

function setTouchFlickSendEnabled(enabled) {
  touchFlickSendEnabled = Boolean(enabled && touchFlickCanEnableSend());
  const btn = document.getElementById("touch-flick-send-toggle");
  if (btn) {
    btn.textContent = touchFlickSendEnabled ? "送信: ON" : "送信: OFF";
    btn.classList.toggle("active", touchFlickSendEnabled);
    btn.disabled = !touchFlickCanEnableSend();
    btn.title = touchFlickSendEnabled ? "keycode/text actionを送信します" : "keycode/text actionを送信できるようにします";
  }
  try {
    window.localStorage.setItem(TOUCH_FLICK_SEND_KEY, touchFlickSendEnabled ? "1" : "0");
  } catch (_e) {
    // localStorage が使えない環境では現在のページ内だけで保持する
  }
  const dispatchState = touchFlickBrowserDispatchEnabled() ? "send-ready" : "send-off";
  updateTouchFlickStatus(touchFlickStatusText(_touchFlickMetadata, dispatchState));
  refreshKeyboardControlsOverlay();
}

function bindTouchFlickPadEvents(el, pad) {
  if (!window.PointerEvent) return;
  el.addEventListener("pointerdown", (e) => {
    if (!touchFlickPreviewEnabled || (e.pointerType === "mouse" && e.button !== 0)) return;
    e.preventDefault();
    const threshold = _touchFlickMetadata?.event_boundary?.threshold_px || 28;
    _touchFlickPointer = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      direction: "center",
      threshold,
      pad,
      el,
    };
    el.classList.add("active");
    if (el.setPointerCapture) {
      try {
        el.setPointerCapture(e.pointerId);
      } catch (_err) {
        // Pointer capture can fail after browser-side cancellation.
      }
    }
    const resolved = resolveTouchFlickPreviewAction(pad, "center");
    updateTouchFlickPreview(`${resolved.label}: ${resolved.action?.label || ""} (${resolved.action?.output || "preview"})`, "center");
  });
  el.addEventListener("pointermove", (e) => {
    if (!_touchFlickPointer || _touchFlickPointer.pointerId !== e.pointerId) return;
    e.preventDefault();
    const direction = touchFlickDirection(
      e.clientX - _touchFlickPointer.startX,
      e.clientY - _touchFlickPointer.startY,
      _touchFlickPointer.threshold,
    );
    _touchFlickPointer.direction = direction;
    const resolved = resolveTouchFlickPreviewAction(pad, direction);
    updateTouchFlickPreview(
      `${resolved.label} ${direction}: ${resolved.action?.label || "-"} (${resolved.action?.output || "preview"})`,
      direction,
    );
  });
  const finishPointer = async (e) => {
    if (!_touchFlickPointer || _touchFlickPointer.pointerId !== e.pointerId) return;
    e.preventDefault();
    const direction = _touchFlickPointer.direction || "center";
    const resolved = resolveTouchFlickPreviewAction(pad, direction);
    el.classList.remove("active");
    _touchFlickPointer = null;
    updateTouchFlickPreview(`${resolved.label} ${resolved.resolvedDirection}: resolving preview/no-op`, direction);
    const envelope = await resolveTouchFlickDispatchEnvelope(
      { kind: "flick_pad", key: pad?.key || "", direction },
      resolved,
    );
    envelope.composition_plan = await resolveTouchFlickCompositionPlan({ kind: "flick_pad", key: pad?.key || "", direction });
    const dispatchResult = await dispatchTouchFlickEnvelope(envelope);
    if (dispatchResult?.result) envelope.dispatch_result = dispatchResult;
    updateTouchFlickDispatchPreview(envelope, resolved, direction);
  };
  el.addEventListener("pointerup", finishPointer);
  el.addEventListener("pointercancel", () => cancelTouchFlickPreview("pointercancel"));
  el.addEventListener("lostpointercapture", () => {
    if (_touchFlickPointer?.keyboardKey) return;
    cancelTouchFlickPreview("lostpointercapture");
  });
}

function renderTouchFlickPad(metadata) {
  const grid = document.getElementById("touch-flick-grid");
  if (!grid) return;
  grid.innerHTML = "";
  const pads = metadata?.layout?.pads || [];
  for (const pad of pads) {
    const el = document.createElement("button");
    el.type = "button";
    el.className = "touch-flick-pad";
    el.textContent = pad.label || pad.key || "";
    el.dataset.flickKey = pad.key || "";
    el.dataset.previewOutput = touchFlickPadOutputFamily(pad);
    el.title = touchFlickPadActionTitle(pad);
    bindTouchFlickPadEvents(el, pad);
    grid.appendChild(el);
  }
  renderTouchFlickImeControls(metadata);
  const dispatchState = touchFlickBrowserDispatchEnabled() ? "send-ready" : "send-off";
  updateTouchFlickStatus(touchFlickStatusText(metadata, dispatchState));
  const namedTextCount = Number(metadata?.named_text?.entry_count || 0);
  const namedText = namedTextCount ? ` / named-text:${namedTextCount}` : "";
  const hostWarning = touchFlickHostImeWarning();
  const warningText = hostWarning ? ` / ${hostWarning}` : "";
  updateTouchFlickPreview(metadata?.available ? `preview/no-op ready / ${dispatchState}${namedText}${warningText}` : "osoyoo-4.3 profile only");
  updateKeyboardDisplayForCurrentMode();
}

function renderTouchFlickImeControls(metadata) {
  const container = document.getElementById("touch-flick-ime-controls");
  if (!container) return;
  container.innerHTML = "";
  const controls = metadata?.ime_controls?.controls || [];
  for (const control of controls) {
    const el = document.createElement("button");
    el.type = "button";
    el.className = "touch-flick-ime-control";
    el.textContent = control.label || control.key || "";
    el.dataset.imeControl = control.key || "";
    el.dataset.imeRole = control.role || "";
    el.title = `${control.action || ""}${control.alternatives?.length ? ` alt: ${control.alternatives.join(", ")}` : ""}`;
    el.addEventListener("click", async () => {
      if (!touchFlickPreviewEnabled) return;
      const resolved = resolveTouchFlickImePreviewAction(control);
      updateTouchFlickPreview(`${resolved.label}: resolving preview/no-op`, "ime");
      const envelope = await resolveTouchFlickDispatchEnvelope(
        { kind: "ime_control", key: control?.key || "" },
        resolved,
      );
      envelope.composition_plan = await resolveTouchFlickCompositionPlan({ kind: "ime_control", key: control?.key || "" });
      const dispatchResult = await dispatchTouchFlickEnvelope(envelope);
      if (dispatchResult?.result) envelope.dispatch_result = dispatchResult;
      updateTouchFlickDispatchPreview(envelope, resolved, "ime");
    });
    container.appendChild(el);
  }
}

async function initTouchFlickPreview() {
  try {
    const resp = await fetch("/api/touch-panel/flick");
    const data = await resp.json();
    _touchFlickMetadata = data;
    renderTouchFlickPad(data);
  } catch (_e) {
    _touchFlickMetadata = { available: false };
    updateTouchFlickStatus("metadata failed");
  }
  try {
    touchFlickPreviewEnabled = window.localStorage.getItem(TOUCH_FLICK_PREVIEW_KEY) === "1";
    touchFlickSendEnabled = window.localStorage.getItem(TOUCH_FLICK_SEND_KEY) === "1";
  } catch (_e) {
    touchFlickPreviewEnabled = false;
    touchFlickSendEnabled = false;
  }
  setTouchFlickPreviewEnabled(touchFlickPreviewEnabled);
  setTouchFlickSendEnabled(touchFlickSendEnabled);
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) cancelTouchFlickPreview("visibilitychange");
});

window.touchFlickDirection = touchFlickDirection;
window.cancelTouchFlickPreview = cancelTouchFlickPreview;
window.setTouchFlickPreviewEnabled = setTouchFlickPreviewEnabled;
window.setTouchFlickSendEnabled = setTouchFlickSendEnabled;

function updateKeyboardMatrixCoordsOverlay() {
  const container = document.getElementById("keyboard-container");
  const btn = document.getElementById("matrix-coords-toggle");
  const visible = keyboardMatrixCoordsEnabled && remapMode;
  if (container) container.classList.toggle("show-matrix-coords", visible);
  if (btn) {
    btn.textContent = keyboardMatrixCoordsEnabled ? "Matrix座標: ON" : "Matrix座標: OFF";
    btn.classList.toggle("active", keyboardMatrixCoordsEnabled);
    btn.title = "キーコード変更画面のキー中央に matrix row,col を表示";
    btn.setAttribute("aria-pressed", keyboardMatrixCoordsEnabled ? "true" : "false");
  }
}

function setKeyboardMatrixCoordsEnabled(enabled) {
  keyboardMatrixCoordsEnabled = Boolean(enabled);
  try {
    window.localStorage.setItem(KEYBOARD_MATRIX_COORDS_KEY, keyboardMatrixCoordsEnabled ? "1" : "0");
  } catch (_e) {
    // localStorage が使えない環境では現在のページ内だけで保持する
  }
  updateKeyboardMatrixCoordsOverlay();
}

function initKeyboardMatrixCoordsPreference() {
  try {
    keyboardMatrixCoordsEnabled = window.localStorage.getItem(KEYBOARD_MATRIX_COORDS_KEY) === "1";
  } catch (_e) {
    keyboardMatrixCoordsEnabled = false;
  }
  updateKeyboardMatrixCoordsOverlay();
}

function initKeyboardFitMode() {
  try {
    const params = new URLSearchParams(window.location.search);
    keyboardFitEnabled = params.get("keyboard") === "1" || window.localStorage.getItem(KEYBOARD_FIT_KEY) === "1";
  } catch (_e) {
    keyboardFitEnabled = false;
  }
  const stage = document.getElementById("keyboard-stage");
  if (window.ResizeObserver && stage) {
    _keyboardFitResizeObserver = new ResizeObserver(updateKeyboardFitScale);
    _keyboardFitResizeObserver.observe(stage);
  } else {
    window.addEventListener("resize", updateKeyboardFitScale);
  }
  setKeyboardFitEnabled(keyboardFitEnabled);
}

function renderKeyboard(slots, labels, layer0) {
  const container = document.getElementById("keyboard");
  container.innerHTML = "";

  // 全スロットの最大X/Yを計算してコンテナサイズを決定
  let maxX = 0, maxY = 0;
  for (const s of slots) {
    if (s.x + s.w > maxX) maxX = s.x + s.w;
    if (s.y + s.h > maxY) maxY = s.y + s.h;
  }
  const keyboardWidth = maxX * (KEY_UNIT_PX + KEY_GAP_PX);
  const keyboardHeight = maxY * (KEY_UNIT_PX + KEY_GAP_PX);
  container.dataset.baseWidth = String(keyboardWidth);
  container.dataset.baseHeight = String(keyboardHeight);
  container.style.width  = `${keyboardWidth}px`;
  container.style.height = `${keyboardHeight}px`;

  for (const s of slots) {
    const el = document.createElement("div");
    el.className = "key";
    if (s.kleRow === 0) {
      el.classList.add("top-row-key");
    }
    const matrixKey = s.matrix ? `${s.matrix.row},${s.matrix.col}` : null;
    el.style.left   = `${s.x * (KEY_UNIT_PX + KEY_GAP_PX)}px`;
    el.style.top    = `${s.y * (KEY_UNIT_PX + KEY_GAP_PX)}px`;
    el.style.width  = `${s.w * (KEY_UNIT_PX + KEY_GAP_PX) - KEY_GAP_PX}px`;
    el.style.height = `${s.h * (KEY_UNIT_PX + KEY_GAP_PX) - KEY_GAP_PX}px`;

    const keycode = matrixKey ? (layer0[matrixKey] || "") : "";
    const rawLabel = keycodeDisplayLabel(
      keycode,
      labels,
      displayFallbackLabel(s, keycode),
    );
    el.dataset.flickLabel = rawLabel;
    renderKeyLabel(el, rawLabel);
    applySpecialKeyStyle(el, s, matrixKey);

    // buildCodeMaps 用に DOM 要素をスロットに保持
    s._el = el;

    if (s.matrix) {
      el.dataset.matrixRow = s.matrix.row;
      el.dataset.matrixCol = s.matrix.col;
      el.dataset.keycode = keycode;
      ensureKeyMatrixCoordBadge(el, s.matrix.row, s.matrix.col);
      attachKeyEvents(el, s.matrix.row, s.matrix.col);
    } else {
      el.classList.add("no-matrix");
    }

    container.appendChild(el);
  }

  createControlClusters(container);

  // DOM 構築後に code→matrix マップを構築
  buildCodeMaps(slots);
  updateKeyboardFitScale();
}

function attachKeyEvents(el, row, col) {
  const matrixKey = `${row},${col}`;
  const isMouseButtonKey = () => isMouseButtonElement(el);

  const pressKey = () => {
    if (typeof window.handleInteractionComboKeyPick === "function" && window.handleInteractionComboKeyPick(row, col, matrixKey)) {
      return false;
    }
    if (remapMode) {
      openRemapPopup(row, col, matrixKey);
      return false;
    }
    if (handleVirtualKeyPress(el, row, col, matrixKey)) return false;
    el.classList.add("pressed");
    sendKey("keydown", row, col);
    return true;
  };

  const releaseKey = () => {
    if (remapMode) return;
    if (isModifierElement(el)) return;
    if (el.dataset.virtualTap === "1") {
      delete el.dataset.virtualTap;
      return;
    }
    if (!el.classList.contains("pressed")) return;
    el.classList.remove("pressed");
    sendKey("keyup", row, col);
  };

  if (window.PointerEvent) {
    el.addEventListener("pointerdown", (e) => {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      e.preventDefault();
      const pad = _touchFlickMetadata?.available
        ? touchFlickPadByAction(el.dataset.keycode || "") || touchFlickPadByLabel(el.dataset.flickLabel || el.textContent)
        : null;
      if (pad && !remapMode) {
        beginKeyboardFlickPointer(el, pad, e);
        return;
      }
      if (!pressKey()) return;
      el.dataset.activePointerId = String(e.pointerId);
      if (el.setPointerCapture) {
        try {
          el.setPointerCapture(e.pointerId);
        } catch (_e) {
          // Some browsers reject capture for already-cancelled pointers.
        }
      }
    });

    el.addEventListener("pointermove", (e) => {
      moveKeyboardFlickPointer(e);
    });

    const releasePointer = (e) => {
      if (_touchFlickPointer?.keyboardKey && _touchFlickPointer.pointerId === e.pointerId) {
        finishKeyboardFlickPointer(e).catch((err) => console.warn("Keyboard flick dispatch failed", err));
        return;
      }
      if (el.dataset.activePointerId && el.dataset.activePointerId !== String(e.pointerId)) return;
      e.preventDefault();
      delete el.dataset.activePointerId;
      releaseKey();
    };

    el.addEventListener("pointerup", releasePointer);
    el.addEventListener("pointercancel", releasePointer);
    el.addEventListener("lostpointercapture", (e) => {
      if (_touchFlickPointer?.keyboardKey && _touchFlickPointer.pointerId === e.pointerId) return;
      if (isMouseButtonKey()) return;
      releasePointer(e);
    });
    return;
  }

  el.addEventListener("mousedown", (e) => {
    e.preventDefault();
    pressKey();
  });
  el.addEventListener("mouseup", () => {
    releaseKey();
  });
  el.addEventListener("mouseleave", () => {
    if (isMouseButtonKey()) return;
    releaseKey();
  });

  el.addEventListener("touchstart", (e) => {
    e.preventDefault();
    pressKey();
  }, { passive: false });
  el.addEventListener("touchend", (e) => {
    e.preventDefault();
    releaseKey();
  }, { passive: false });
  el.addEventListener("touchcancel", (e) => {
    e.preventDefault();
    releaseKey();
  }, { passive: false });
}

function isModifierElement(el) {
  return MODIFIER_KEYCODES.has(el.dataset.keycode || "");
}

function isMouseButtonElement(el) {
  return /^(?:KC|MS)_BTN[1-5]$/.test(el.dataset.keycode || "");
}

function tapKey(row, col) {
  sendKey("keydown", row, col);
  sendKey("keyup", row, col);
}

function clearLatchedModifiers() {
  for (const mod of latchedModifiers.values()) {
    mod.el.classList.remove("latched");
  }
  latchedModifiers.clear();
}

function handleVirtualKeyPress(el, row, col, matrixKey) {
  const keycode = el.dataset.keycode || "";

  if (MODIFIER_KEYCODES.has(keycode)) {
    if (latchedModifiers.has(matrixKey)) {
      // 2回目の押下は、そのモディファイア単体の tap として送信する。
      tapKey(row, col);
      latchedModifiers.delete(matrixKey);
      el.classList.remove("latched");
    } else {
      latchedModifiers.set(matrixKey, { row, col, el, keycode });
      el.classList.add("latched");
    }
    return true;
  }

  if (latchedModifiers.size > 0) {
    const modifiers = Array.from(latchedModifiers.values());
    for (const mod of modifiers) sendKey("keydown", mod.row, mod.col);
    tapKey(row, col);
    el.dataset.virtualTap = "1";
    for (const mod of modifiers.slice().reverse()) {
      sendKey("keyup", mod.row, mod.col);
    }
    clearLatchedModifiers();
    return true;
  }

  return false;
}

// -----------------------------------------------------------------------
// 初期化
// -----------------------------------------------------------------------

async function init() {
  wsConnect();
  initStatusViewMode();
  startStatusPolling();
  initLogPanelEvents();
  initLightingPanelEvents();
  initScriptPanelEvents();
  fetchLighting();
  initKeyboardDisplayLayerPreference();
  initKeyboardMatrixCoordsPreference();

  let layout, keymap, labels = {}, layer0 = {};
  try {
    const resp = await fetch("/api/layout");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    layout = data.layout;
    keymap = data.keymap;
    labels = data.labels || {};
    layer0 = data.layer0 || {};
    _allLayers = data.all_layers || [];
    if (_allLayers.length === 0 && Object.keys(layer0).length > 0) {
      _allLayers = [layer0];
    }
    _defaultLayers = Array.isArray(data.default_layers) ? data.default_layers : [];
    if (_defaultLayers.length === 0 && data.default_layer0 && Object.keys(data.default_layer0).length > 0) {
      _defaultLayers = [data.default_layer0];
    }
    _labelsCache = labels;
    setAvailableRemapKeycodes(data.keycodes || []);
    updateControlMetadata(data.controls || {});
    updateKeyboardActiveLayers(data.logicd_active || {});
    _kleLayoutSource = Array.isArray(layout) ? layout : [];
  } catch (e) {
    showError(`レイアウト取得失敗: ${e.message}`);
    return;
  }

  // KLE slots をパース
  const slots = parseKLE(layout);

  // vial keymap から matrix テーブルを構築し、未割当スロットに付与
  const matrixTable = buildMatrixTable(keymap);
  let idx = 0;
  for (const s of slots) {
    if (!s.matrix && matrixTable[idx]) {
      s.matrix = matrixTable[idx];
      if (s.matrix) {
        // 未解決スロットに付与されたので head を更新
        s.head = `${s.matrix.row},${s.matrix.col}`;
      }
    }
    idx++;
  }

  _keyboardSlots = slots;
  renderKeyboard(slots, labels, layer0);
  updateKeyboardLayerSelector();
  updateKeyboardDisplayForCurrentMode();
  startKeyboardActiveLayerPolling();
  initKeyboardFitMode();
  initTouchFlickPreview();
  initRemapPopupEvents();
  initActiveTab();
}

function showError(msg) {
  const el = document.getElementById("error-banner");
  if (!el) return;
  el.textContent = msg;
  el.style.display = "block";
}

document.addEventListener("DOMContentLoaded", init);
