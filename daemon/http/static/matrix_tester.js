"use strict";

let ws = null;
let wsReconnectTimer = null;
const MODIFIER_KEYCODES = new Set([
  "KC_LSFT", "KC_RSFT",
  "KC_LCTL", "KC_RCTL",
  "KC_LALT", "KC_RALT",
  "KC_LGUI", "KC_RGUI",
]);
const latchedModifiers = new Map();  // matrixKey -> { row, col, el, keycode }
let matrixTesterEnabled = false;
let matrixTesterTimer = null;
let matrixTesterBusy = false;
let internalPressedKeys = new Set();
const internalFadeTimers = new Map();

function keyElementForMatrix(row, col) {
  return document.querySelector(
    `.key[data-matrix-row="${row}"][data-matrix-col="${col}"]`
  );
}

function setInternalPressed(el) {
  if (!el) return;
  const timer = internalFadeTimers.get(el);
  if (timer) {
    clearTimeout(timer);
    internalFadeTimers.delete(el);
  }
  el.classList.remove("internal-fade");
  el.classList.add("internal-pressed");
}

function fadeInternalPressed(el) {
  if (!el) return;
  el.classList.remove("internal-pressed");
  el.classList.remove("internal-fade");
  void el.offsetWidth;
  el.classList.add("internal-fade");
  const timer = setTimeout(() => {
    el.classList.remove("internal-fade");
    internalFadeTimers.delete(el);
  }, 520);
  internalFadeTimers.set(el, timer);
}

function wsConnect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;

  ws = new WebSocket(csrfWebSocketUrl("/ws"));

  ws.addEventListener("open", () => {
    setStatus(true);
    clearTimeout(wsReconnectTimer);
    wsReconnectTimer = null;
  });

  ws.addEventListener("close", () => {
    setStatus(false);
    scheduleReconnect();
  });

  ws.addEventListener("error", (e) => {
    console.warn("WS error", e);
    ws.close();
  });
}

function scheduleReconnect() {
  if (wsReconnectTimer) return;
  wsReconnectTimer = setTimeout(() => {
    wsReconnectTimer = null;
    wsConnect();
  }, 3000);
}

function setMatrixTesterEnabled(enabled) {
  matrixTesterEnabled = Boolean(enabled);
  const btn = document.getElementById("matrix-tester-toggle");
  if (btn) {
    btn.textContent = matrixTesterEnabled ? "内部キーテスター: ON" : "内部キーテスター: OFF";
    btn.classList.toggle("active", matrixTesterEnabled);
  }
  if (typeof window.refreshKeyboardControlsOverlay === "function") {
    window.refreshKeyboardControlsOverlay();
  }
  document.body?.classList.toggle("matrix-tester-enabled", matrixTesterEnabled);
  if (matrixTesterEnabled) {
    fetchMatrixState();
    if (!matrixTesterTimer) {
      matrixTesterTimer = setInterval(fetchMatrixState, 80);
    }
  } else {
    if (matrixTesterTimer) {
      clearInterval(matrixTesterTimer);
      matrixTesterTimer = null;
    }
    updateInternalPressedKeys([]);
  }
}

function isMatrixTesterEnabled() {
  return matrixTesterEnabled;
}

function toggleMatrixTester() {
  setMatrixTesterEnabled(!matrixTesterEnabled);
}

function updateInternalPressedKeys(pressed) {
  const next = new Set((pressed || []).map(([row, col]) => `${row},${col}`));
  for (const key of internalPressedKeys) {
    if (next.has(key)) continue;
    const [row, col] = key.split(",");
    fadeInternalPressed(keyElementForMatrix(row, col));
  }
  for (const key of next) {
    const [row, col] = key.split(",");
    setInternalPressed(keyElementForMatrix(row, col));
  }
  internalPressedKeys = next;
}

function joystickPressedKeys(joystick) {
  const pressed = [];
  for (const stick of joystick?.sticks || []) {
    for (const direction of stick?.directions || []) {
      if (!direction?.active) continue;
      const row = Number(direction.row);
      const col = Number(direction.col);
      if (!Number.isInteger(row) || !Number.isInteger(col) || row < 0 || col < 0) continue;
      pressed.push([row, col]);
    }
  }
  return pressed;
}

function matrixAndJoystickPressedKeys(data) {
  return [
    ...(data?.pressed || []),
    ...joystickPressedKeys(data?.joystick),
  ];
}

async function fetchMatrixState() {
  if (!matrixTesterEnabled || matrixTesterBusy) return;
  matrixTesterBusy = true;
  try {
    const resp = await fetch("/api/matrix");
    const data = await resp.json();
    if (resp.ok && data.result === "ok") {
      updateInternalPressedKeys(matrixAndJoystickPressedKeys(data));
    }
  } catch (_e) {
    // 次のポーリングで復帰する。
  } finally {
    matrixTesterBusy = false;
  }
}

window.setMatrixTesterEnabled = setMatrixTesterEnabled;
window.isMatrixTesterEnabled = isMatrixTesterEnabled;
window.toggleMatrixTester = toggleMatrixTester;

function sendKey(type, row, col) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(`${type === "keydown" ? "P" : "R"}${Number(row).toString(16)}${Number(col).toString(16)}`);
  if (typeof window.fetchKeyboardActiveLayers === "function") {
    window.setTimeout(() => window.fetchKeyboardActiveLayers(), type === "keydown" ? 30 : 90);
  }
}

function setStatus(connected) {
  const el = document.getElementById("ws-status");
  if (!el) return;
  el.textContent = connected ? "Ready" : "Disconnected";
  el.className = "status " + (connected ? "connected" : "disconnected");
}

function reloadFromReadyStatus() {
  const el = document.getElementById("ws-status");
  if (!el || !el.classList.contains("connected")) return;
  window.location.reload();
}

function handleReadyStatusKeydown(event) {
  if (event.key !== "Enter" && event.key !== " ") return;
  event.preventDefault();
  reloadFromReadyStatus();
}

window.reloadFromReadyStatus = reloadFromReadyStatus;
window.handleReadyStatusKeydown = handleReadyStatusKeydown;
