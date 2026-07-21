"use strict";

let _oledEditorState = {
  customization: null,
  defaults: null,
  itemCatalog: [],
  iconGroups: [],
  display: { width: 64, height: 128 },
  activeIcon: "",
  fillMode: false,
  painting: false,
  paintValue: "1",
  source: "default",
};

function oledEl(id) {
  return document.getElementById(id);
}

function oledClone(value) {
  return JSON.parse(JSON.stringify(value));
}

function setOledStatus(message, error = false) {
  const element = oledEl("oled-status");
  if (!element) return;
  element.textContent = message;
  element.classList.toggle("error", error);
}

function currentOledIcon() {
  return _oledEditorState.customization?.icons?.[_oledEditorState.activeIcon] || null;
}

function oledCatalogEntry(itemId) {
  return _oledEditorState.itemCatalog.find(item => item.id === itemId) || {
    id: itemId,
    label: itemId,
    description: "",
  };
}

async function fetchOledCustomization() {
  setOledStatus("読込中…");
  try {
    const response = await fetch("/api/oled", { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || data.result !== "ok") throw new Error(data.msg || `HTTP ${response.status}`);
    _oledEditorState.customization = oledClone(data.customization);
    _oledEditorState.defaults = oledClone(data.defaults);
    _oledEditorState.itemCatalog = Array.isArray(data.item_catalog) ? data.item_catalog : [];
    _oledEditorState.iconGroups = Array.isArray(data.icon_groups) ? data.icon_groups : [];
    _oledEditorState.display = data.display || { width: 64, height: 128 };
    _oledEditorState.source = data.source || "default";
    const names = Object.keys(_oledEditorState.customization.icons || {});
    const orderedNames = _oledEditorState.iconGroups.flatMap(group =>
      Array.isArray(group.items) ? group.items.map(item => item.name) : []
    );
    if (!names.includes(_oledEditorState.activeIcon)) {
      _oledEditorState.activeIcon = orderedNames.find(name => names.includes(name)) || names[0] || "";
    }
    renderOledEditor();
    const warning = Array.isArray(data.errors) && data.errors.length ? ` (${data.errors.join("; ")})` : "";
    setOledStatus(`読込完了: ${_oledEditorState.source}${warning}`, Boolean(warning));
  } catch (error) {
    setOledStatus(`読込失敗: ${error.message}`, true);
  }
}

function renderOledEditor() {
  renderOledIconList();
  renderOledPixelGrid();
  renderOledLayoutList();
  renderOledScreenPreview();
  const source = oledEl("oled-source-label");
  if (source) source.textContent = `source: ${_oledEditorState.source} / ${_oledEditorState.display.width}×${_oledEditorState.display.height}`;
}

function renderOledIconList() {
  const list = oledEl("oled-icon-list");
  if (!list || !_oledEditorState.customization) return;
  list.replaceChildren();
  const icons = _oledEditorState.customization.icons || {};
  const rendered = new Set();
  const groups = _oledEditorState.iconGroups.map(group => ({
    ...group,
    items: Array.isArray(group.items) ? group.items.filter(item => icons[item.name]) : [],
  }));
  const knownNames = new Set(groups.flatMap(group => group.items.map(item => item.name)));
  const fallbackItems = Object.keys(icons)
    .filter(name => !knownNames.has(name))
    .map(name => ({ name, label: "Other icon" }));
  if (fallbackItems.length) {
    groups.push({ id: "other-runtime", label: "Other", description: "未分類のicon", items: fallbackItems });
  }
  groups.forEach(group => {
    if (!group.items.length) return;
    const section = document.createElement("section");
    section.className = "oled-icon-group";
    section.dataset.iconGroup = group.id;
    section.setAttribute("role", "group");
    const header = document.createElement("div");
    header.className = "oled-icon-group-header";
    const title = document.createElement("strong");
    title.textContent = group.label;
    const description = document.createElement("small");
    description.textContent = group.description || "";
    header.append(title, description);
    const choices = document.createElement("div");
    choices.className = "oled-icon-group-list";
    group.items.forEach(item => {
      const name = item.name;
      const icon = icons[name];
      if (!icon || rendered.has(name)) return;
      rendered.add(name);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "oled-icon-choice";
      button.classList.toggle("active", name === _oledEditorState.activeIcon);
      button.dataset.iconName = name;
      button.setAttribute("role", "option");
      button.setAttribute("aria-selected", name === _oledEditorState.activeIcon ? "true" : "false");
      const canvas = document.createElement("canvas");
      canvas.width = icon.width;
      canvas.height = icon.height;
      drawOledIconCanvas(canvas, icon, false);
      const text = document.createElement("span");
      text.className = "oled-icon-choice-text";
      const code = document.createElement("strong");
      code.textContent = name;
      const label = document.createElement("small");
      label.textContent = item.label || name;
      text.append(code, label);
      button.append(canvas, text);
      button.addEventListener("click", () => selectOledIcon(name));
      choices.appendChild(button);
    });
    section.append(header, choices);
    list.appendChild(section);
  });
}

function selectOledIcon(name) {
  if (!_oledEditorState.customization?.icons?.[name]) return;
  _oledEditorState.activeIcon = name;
  renderOledIconList();
  renderOledPixelGrid();
}

function renderOledPixelGrid() {
  const grid = oledEl("oled-pixel-grid");
  const icon = currentOledIcon();
  if (!grid || !icon) return;
  const title = oledEl("oled-icon-title");
  const size = oledEl("oled-icon-size-label");
  const width = oledEl("oled-icon-width");
  const height = oledEl("oled-icon-height");
  if (title) title.textContent = _oledEditorState.activeIcon;
  if (size) size.textContent = `${icon.width}×${icon.height} / 1-bit`;
  if (width) width.value = String(icon.width);
  if (height) height.value = String(icon.height);
  grid.replaceChildren();
  grid.style.setProperty("--oled-grid-columns", String(icon.width));
  icon.rows.forEach((row, y) => {
    Array.from(row).forEach((pixel, x) => {
      const cell = document.createElement("button");
      cell.type = "button";
      cell.className = `oled-pixel${pixel === "1" ? " on" : ""}`;
      cell.dataset.x = String(x);
      cell.dataset.y = String(y);
      cell.setAttribute("aria-label", `pixel ${x},${y}: ${pixel}`);
      grid.appendChild(cell);
    });
  });
  drawOledIconCanvas(oledEl("oled-icon-preview"), icon, false);
  drawOledIconCanvas(oledEl("oled-icon-preview-inverted"), icon, true);
  renderOledScreenPreview();
}

function drawOledIconCanvas(canvas, icon, inverted) {
  if (!canvas || !icon) return;
  const border = inverted ? 1 : 0;
  canvas.width = icon.width + border * 2;
  canvas.height = icon.height + border * 2;
  const context = canvas.getContext("2d");
  context.imageSmoothingEnabled = false;
  context.fillStyle = inverted ? "#fff" : "#000";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = inverted ? "#000" : "#fff";
  icon.rows.forEach((row, y) => {
    Array.from(row).forEach((pixel, x) => {
      if (pixel === "1") context.fillRect(x + border, y + border, 1, 1);
    });
  });
}

function setOledFillMode(enabled) {
  _oledEditorState.fillMode = Boolean(enabled);
  const button = oledEl("oled-tool-fill");
  if (!button) return;
  button.classList.toggle("active", _oledEditorState.fillMode);
  button.setAttribute("aria-pressed", _oledEditorState.fillMode ? "true" : "false");
  button.textContent = `塗りつぶし: ${_oledEditorState.fillMode ? "ON" : "OFF"}`;
}

function toggleOledFillMode() {
  setOledFillMode(!_oledEditorState.fillMode);
}

function oledPaintValueForPointerButton(pointerButton) {
  if (pointerButton === 0) return "1";
  if (pointerButton === 2) return "0";
  return null;
}

function oledPixelTarget(target) {
  return target instanceof Element ? target.closest(".oled-pixel") : null;
}

function stopOledPainting() {
  _oledEditorState.painting = false;
}

function oledPaintButtonMask(paintValue) {
  return paintValue === "0" ? 2 : 1;
}

function oledPointerButtonIsPressed(event) {
  return Boolean(event.buttons & oledPaintButtonMask(_oledEditorState.paintValue));
}

function applyOledPixel(x, y, value) {
  const icon = currentOledIcon();
  if (!icon || y < 0 || y >= icon.height || x < 0 || x >= icon.width) return;
  const row = Array.from(icon.rows[y]);
  row[x] = value;
  icon.rows[y] = row.join("");
}

function floodFillOledIcon(startX, startY, replacement) {
  const icon = currentOledIcon();
  if (!icon) return;
  const target = icon.rows[startY]?.[startX];
  if (target === undefined || target === replacement) return;
  const queue = [[startX, startY]];
  const visited = new Set();
  while (queue.length) {
    const [x, y] = queue.shift();
    const key = `${x},${y}`;
    if (visited.has(key) || x < 0 || y < 0 || x >= icon.width || y >= icon.height) continue;
    visited.add(key);
    if (icon.rows[y][x] !== target) continue;
    applyOledPixel(x, y, replacement);
    queue.push([x - 1, y], [x + 1, y], [x, y - 1], [x, y + 1]);
  }
}

function paintOledCell(cell, initial = false) {
  if (!cell) return;
  const x = Number(cell.dataset.x);
  const y = Number(cell.dataset.y);
  if (initial && _oledEditorState.fillMode) {
    floodFillOledIcon(x, y, _oledEditorState.paintValue);
    stopOledPainting();
    renderOledPixelGrid();
  } else {
    applyOledPixel(x, y, _oledEditorState.paintValue);
    cell.classList.toggle("on", _oledEditorState.paintValue === "1");
    cell.setAttribute("aria-label", `pixel ${x},${y}: ${_oledEditorState.paintValue}`);
    const icon = currentOledIcon();
    drawOledIconCanvas(oledEl("oled-icon-preview"), icon, false);
    drawOledIconCanvas(oledEl("oled-icon-preview-inverted"), icon, true);
    renderOledScreenPreview();
  }
  renderOledIconList();
}

function handleOledPointerOver(event) {
  if (!_oledEditorState.painting || _oledEditorState.fillMode) return;
  if (!oledPointerButtonIsPressed(event)) {
    stopOledPainting();
    return;
  }
  paintOledCell(oledPixelTarget(event.target));
}

function resizeOledIcon() {
  const icon = currentOledIcon();
  const input = oledEl("oled-icon-width");
  if (!icon || !input) return;
  const width = Math.max(1, Math.min(8, Number(input.value) || icon.width));
  icon.rows = icon.rows.map(row => row.slice(0, width).padEnd(width, "0"));
  icon.width = width;
  renderOledPixelGrid();
  renderOledIconList();
}

function clearOledIcon() {
  const icon = currentOledIcon();
  if (!icon) return;
  icon.rows = Array.from({ length: icon.height }, () => "0".repeat(icon.width));
  renderOledPixelGrid();
  renderOledIconList();
}

function invertOledIcon() {
  const icon = currentOledIcon();
  if (!icon) return;
  icon.rows = icon.rows.map(row => Array.from(row, pixel => pixel === "1" ? "0" : "1").join(""));
  renderOledPixelGrid();
  renderOledIconList();
}

function resetCurrentOledIcon() {
  const name = _oledEditorState.activeIcon;
  const fallback = _oledEditorState.defaults?.icons?.[name];
  if (!fallback) return;
  _oledEditorState.customization.icons[name] = oledClone(fallback);
  renderOledPixelGrid();
  renderOledIconList();
}

function renderOledLayoutList() {
  const list = oledEl("oled-layout-list");
  const items = _oledEditorState.customization?.ready?.items;
  if (!list || !Array.isArray(items)) return;
  list.replaceChildren();
  items.forEach((item, index) => {
    const metadata = oledCatalogEntry(item.id);
    const row = document.createElement("div");
    row.className = "oled-layout-row";
    row.dataset.itemId = item.id;
    const enabled = document.createElement("input");
    enabled.type = "checkbox";
    enabled.checked = item.enabled;
    enabled.title = "表示する";
    enabled.addEventListener("change", () => {
      item.enabled = enabled.checked;
      renderOledScreenPreview();
    });
    const text = document.createElement("div");
    const label = document.createElement("strong");
    label.textContent = metadata.label;
    const description = document.createElement("small");
    description.textContent = metadata.description;
    text.append(label, description);
    const separatorLabel = document.createElement("label");
    separatorLabel.className = "oled-separator-check";
    const separator = document.createElement("input");
    separator.type = "checkbox";
    separator.checked = item.separator_after;
    separator.addEventListener("change", () => {
      item.separator_after = separator.checked;
      renderOledScreenPreview();
    });
    separatorLabel.append(separator, document.createTextNode("線"));
    const controls = document.createElement("div");
    controls.className = "oled-order-controls";
    const up = document.createElement("button");
    up.type = "button";
    up.textContent = "↑";
    up.disabled = index === 0;
    up.addEventListener("click", () => moveOledLayoutItem(index, -1));
    const down = document.createElement("button");
    down.type = "button";
    down.textContent = "↓";
    down.disabled = index === items.length - 1;
    down.addEventListener("click", () => moveOledLayoutItem(index, 1));
    controls.append(up, down);
    row.append(enabled, text, separatorLabel, controls);
    list.appendChild(row);
  });
}

function moveOledLayoutItem(index, delta) {
  const items = _oledEditorState.customization?.ready?.items;
  const next = index + delta;
  if (!Array.isArray(items) || next < 0 || next >= items.length) return;
  [items[index], items[next]] = [items[next], items[index]];
  renderOledLayoutList();
  renderOledScreenPreview();
}

function drawOledPreviewIcon(context, name, x, y, active = false) {
  const icon = _oledEditorState.customization?.icons?.[name];
  if (!icon) return x;
  if (active) {
    context.fillStyle = "#fff";
    context.fillRect(x, y - 1, icon.width + 2, icon.height + 2);
  }
  context.fillStyle = active ? "#000" : "#fff";
  icon.rows.forEach((row, dy) => {
    Array.from(row).forEach((pixel, dx) => {
      if (pixel === "1") context.fillRect(x + 1 + dx, y + dy, 1, 1);
    });
  });
  return x + icon.width + 3;
}

const OLED_WEB_UI_QR_PREVIEW = [
  "111111100010101111111", "100000100000101000001", "101110101010001011101",
  "101110100000101011101", "101110100100101011101", "100000100111001000001",
  "111111101010101111111", "000000001011000000000", "111011111010011000100",
  "001111001000110001111", "101011101001101010000", "010100010010011110000",
  "101110110000101110001", "000000001001110010001", "111111101100001011101",
  "100000101101101100011", "101110101010101010100", "101110100011001000010",
  "101110101010101100001", "100000101010001001011", "111111101000001101001",
];

function drawOledWebUiQrPreview(context, y) {
  const scale = 2;
  const quiet = 4 * scale;
  const size = (21 + 8) * scale;
  const left = Math.floor((64 - size) / 2);
  context.fillStyle = "#fff";
  context.fillRect(left, y, size, size);
  context.fillStyle = "#000";
  OLED_WEB_UI_QR_PREVIEW.forEach((row, moduleY) => {
    Array.from(row).forEach((pixel, moduleX) => {
      if (pixel === "1") {
        context.fillRect(left + quiet + moduleX * scale, y + quiet + moduleY * scale, scale, scale);
      }
    });
  });
  return y + size;
}

function renderOledScreenPreview() {
  const canvas = oledEl("oled-screen-preview");
  const items = _oledEditorState.customization?.ready?.items;
  if (!canvas || !Array.isArray(items)) return;
  canvas.width = _oledEditorState.display.width || 64;
  canvas.height = _oledEditorState.display.height || 128;
  const context = canvas.getContext("2d");
  context.imageSmoothingEnabled = false;
  context.fillStyle = "#000";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.strokeStyle = "#fff";
  context.strokeRect(0.5, 0.5, canvas.width - 1, canvas.height - 1);
  context.fillStyle = "#fff";
  context.font = "7px monospace";
  context.textBaseline = "top";
  let y = 3;
  const text = value => {
    context.fillStyle = "#fff";
    context.fillText(value, 3, y);
    y += 10;
  };
  items.filter(item => item.enabled).forEach(item => {
    if (item.id === "node_name") text("hidloom-02");
    if (item.id === "daemon_status") {
      ["mtx", "core", "cmp", "out", "uid", "led", "btd", "web", "hid", "vial"].forEach((name, index) => {
        drawOledPreviewIcon(context, name, 3 + (index % 5) * 11, y + Math.floor(index / 5) * 8, true);
      });
      y += 16;
    }
    if (item.id === "output_mode") {
      let x = 3;
      ["auto", "usb", "wifi3"].forEach(name => { x = drawOledPreviewIcon(context, name, x, y, true); });
      y += 10;
    }
    if (item.id === "web_ui_qr") y = drawOledWebUiQrPreview(context, y);
    if (item.id === "layer") text("Layer: 0");
    if (item.id === "active_layers") text("[0,1]");
    if (item.id === "cpu") text("CPU:12 %");
    if (item.id === "temperature") text("T:52 C");
    if (item.id === "fps") text("FPS:23.8");
    if (item.id === "clock") text("  12:34");
    if (item.separator_after) {
      context.fillStyle = "#fff";
      context.fillRect(1, y, canvas.width - 2, 1);
      y += 3;
    }
  });
  const usage = oledEl("oled-layout-usage");
  if (usage) {
    const available = canvas.height - 1;
    const overflow = Math.max(0, y - available);
    usage.textContent = overflow
      ? `表示領域を ${overflow}px 超えています。項目を減らすか順序を調整してください。`
      : `使用中: ${Math.max(0, y - 3)} / ${available - 3}px`;
    usage.classList.toggle("error", overflow > 0);
  }
}

async function saveOledCustomization() {
  if (!_oledEditorState.customization) return;
  setOledStatus("保存中…");
  try {
    const response = await csrfFetch("/api/oled", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(_oledEditorState.customization),
    });
    const data = await response.json();
    if (!response.ok || data.result !== "ok") throw new Error(data.msg || `HTTP ${response.status}`);
    _oledEditorState.customization = oledClone(data.customization);
    _oledEditorState.source = data.source || "runtime";
    renderOledEditor();
    const apply = data.apply?.result === "ok" ? "即時反映" : "定期更新で反映";
    setOledStatus(`保存しました (${apply})`);
  } catch (error) {
    setOledStatus(`保存失敗: ${error.message}`, true);
  }
}

async function resetOledCustomization() {
  if (!window.confirm("OLED iconとReady画面を既定値へ戻しますか？")) return;
  setOledStatus("リセット中…");
  try {
    const response = await csrfFetch("/api/oled/reset", { method: "POST" });
    const data = await response.json();
    if (!response.ok || data.result !== "ok") throw new Error(data.msg || `HTTP ${response.status}`);
    _oledEditorState.customization = oledClone(data.customization);
    _oledEditorState.source = "default";
    renderOledEditor();
    setOledStatus("既定値へ戻しました");
  } catch (error) {
    setOledStatus(`リセット失敗: ${error.message}`, true);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const grid = oledEl("oled-pixel-grid");
  if (!grid) return;
  grid.addEventListener("pointerdown", event => {
    const cell = oledPixelTarget(event.target);
    const paintValue = oledPaintValueForPointerButton(event.button);
    if (!cell || paintValue === null) return;
    event.preventDefault();
    _oledEditorState.painting = true;
    _oledEditorState.paintValue = paintValue;
    paintOledCell(cell, true);
  });
  grid.addEventListener("pointerover", handleOledPointerOver);
  grid.addEventListener("contextmenu", event => event.preventDefault());
  window.addEventListener("pointerup", stopOledPainting, true);
  window.addEventListener("pointercancel", stopOledPainting, true);
  window.addEventListener("blur", stopOledPainting);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopOledPainting();
  });
});

window.fetchOledCustomization = fetchOledCustomization;
window.saveOledCustomization = saveOledCustomization;
window.resetOledCustomization = resetOledCustomization;
window.toggleOledFillMode = toggleOledFillMode;
window.resizeOledIcon = resizeOledIcon;
window.clearOledIcon = clearOledIcon;
window.invertOledIcon = invertOledIcon;
window.resetCurrentOledIcon = resetCurrentOledIcon;
