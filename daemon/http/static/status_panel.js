"use strict";

const STATUS_VIEW_KEY = "hidloom-status-view-mode";
let _statusViewMode = "detail";
let _currentLogService = null;
let _statusFetchBusy = false;

async function fetchStatus() {
  if (_statusFetchBusy) return;
  _statusFetchBusy = true;
  try {
    const resp = await fetch("/api/status");
    if (!resp.ok) return;
    const data = await resp.json();
    updateStatusUI(data);
  } catch (_e) {
    // ネットワークエラーは無視
  } finally {
    _statusFetchBusy = false;
  }
}

function setStatusViewMode(mode) {
  _statusViewMode = mode === "simple" ? "simple" : "detail";
  const panel = document.getElementById("system-status");
  if (panel) {
    panel.classList.toggle("simple", _statusViewMode === "simple");
  }
  const hostPanel = document.getElementById("bt-host-panel");
  if (hostPanel) hostPanel.hidden = _statusViewMode === "simple";
  for (const name of ["simple", "detail"]) {
    const btn = document.getElementById(`status-view-${name}`);
    if (!btn) continue;
    const active = name === _statusViewMode;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-pressed", active ? "true" : "false");
  }
  try {
    window.localStorage.setItem(STATUS_VIEW_KEY, _statusViewMode);
  } catch (_e) {
    // localStorage が使えない環境では現在のページ内だけで保持する
  }
}

function initStatusViewMode() {
  let saved = "detail";
  try {
    saved = window.localStorage.getItem(STATUS_VIEW_KEY) || "detail";
  } catch (_e) {
    saved = "detail";
  }
  setStatusViewMode(saved);
}

function outputModeDisplayLabel(mode) {
  const labels = {
    gadget: "USB",
    bt: "BT",
    uinput: "Pi",
  };
  return labels[mode] || mode || "";
}

function ensureWifiStatusRow() {
  if (document.getElementById("stat-wifi")) return;
  const bluetoothRow = document.getElementById("stat-bluetooth")?.closest(".sysstat-row");
  const systemStatus = document.getElementById("system-status");
  if (!bluetoothRow || !systemStatus) return;
  const row = document.createElement("div");
  row.className = "sysstat-row";
  const label = document.createElement("span");
  label.className = "sysstat-label";
  label.textContent = "Wi-Fi";
  const status = document.createElement("span");
  status.id = "stat-wifi";
  status.className = "status disconnected";
  status.textContent = "–";
  row.append(label, status);
  bluetoothRow.after(row);
}

function updateWifiStatusUI(wifi) {
  ensureWifiStatusRow();
  const wifiEl = document.getElementById("stat-wifi");
  if (!wifiEl) return;
  wifi = wifi || {};
  if (!wifi.available) {
    wifiEl.textContent = "Unavailable";
    wifiEl.className = "status status-dot disconnected";
  } else if (wifi.blocked) {
    wifiEl.textContent = "Off";
    wifiEl.className = "status status-dot disconnected";
  } else if (wifi.connected) {
    wifiEl.textContent = wifi.ssid ? `On ${wifi.ssid}` : "Connected";
    wifiEl.className = "status status-dot connected";
  } else if (wifi.powered) {
    wifiEl.textContent = "On";
    wifiEl.className = "status status-dot output-warning";
  } else {
    wifiEl.textContent = "Unknown";
    wifiEl.className = "status status-dot disconnected";
  }
  const mode = wifi.persistent_power_off ? "persistent-off capable" : wifi.recovery_first ? "recovery-first" : "unknown policy";
  const errors = Array.isArray(wifi.errors) && wifi.errors.length ? ` errors=${wifi.errors.join("; ")}` : "";
  wifiEl.title = `Wi-Fi: interface=${wifi.interface || ""}, powered=${wifi.powered}, blocked=${wifi.blocked}, connected=${wifi.connected}, ssid=${wifi.ssid || ""}, ${mode}${errors}`;
}

function ensureBoardProfileStatusRow() {
  if (document.getElementById("stat-board-profile")) return;
  const modeRow = document.getElementById("stat-mode")?.closest(".sysstat-row");
  const systemStatus = document.getElementById("system-status");
  if (!modeRow || !systemStatus) return;
  const row = document.createElement("div");
  row.className = "sysstat-row";
  const label = document.createElement("span");
  label.className = "sysstat-label";
  label.textContent = "Board";
  const status = document.createElement("span");
  status.id = "stat-board-profile";
  status.className = "status status-dot disconnected";
  status.textContent = "–";
  row.append(label, status);
  modeRow.after(row);
}

function ensureInteractionStatusRow() {
  if (document.getElementById("stat-interaction")) return;
  const boardRow = document.getElementById("stat-board-profile")?.closest(".sysstat-row")
    || document.getElementById("stat-mode")?.closest(".sysstat-row");
  const systemStatus = document.getElementById("system-status");
  if (!boardRow || !systemStatus) return;
  const row = document.createElement("div");
  row.className = "sysstat-row";
  const label = document.createElement("span");
  label.className = "sysstat-label";
  label.textContent = "Interaction";
  const status = document.createElement("span");
  status.id = "stat-interaction";
  status.className = "status status-dot disconnected";
  status.textContent = "–";
  row.append(label, status);
  boardRow.after(row);
}

function ensureTextSendStatusRow() {
  if (document.getElementById("stat-text-send")) return;
  const interactionRow = document.getElementById("stat-interaction")?.closest(".sysstat-row")
    || document.getElementById("stat-board-profile")?.closest(".sysstat-row")
    || document.getElementById("stat-mode")?.closest(".sysstat-row");
  const systemStatus = document.getElementById("system-status");
  if (!interactionRow || !systemStatus) return;
  const row = document.createElement("div");
  row.className = "sysstat-row";
  const label = document.createElement("span");
  label.className = "sysstat-label";
  label.textContent = "Text Send";
  const status = document.createElement("span");
  status.id = "stat-text-send";
  status.className = "status status-dot disconnected";
  status.textContent = "–";
  row.append(label, status);
  interactionRow.after(row);
}

function updateTextSendStatusUI(textSend) {
  ensureTextSendStatusRow();
  const el = document.getElementById("stat-text-send");
  if (!el) return;
  textSend = textSend || {};
  if (!textSend.available) {
    el.textContent = "Unavailable";
    el.className = "status status-dot disconnected";
    el.title = `Text Send: unavailable (${textSend.reason || "unknown"})`;
    return;
  }
  const mode = textSend.unicode_mode || "none";
  const entryCount = Number(textSend.send_string_entry_count || 0);
  const blocking = Array.isArray(textSend.blocking_reasons) ? textSend.blocking_reasons : [];
  if (textSend.real_send_allowed) {
    el.textContent = `Ready ${mode}`;
    el.className = "status status-dot connected";
  } else {
    el.textContent = `Blocked ${mode}`;
    el.className = "status status-dot output-warning";
  }
  el.title = `Text Send: real_send_allowed=${Boolean(textSend.real_send_allowed)}, runner_ready=${Boolean(textSend.runner_ready)}, runner_connected=${Boolean(textSend.runner_connected)}, host_profile_explicit=${Boolean(textSend.host_profile_explicit)}, host_profile=${textSend.host_profile || "-"}, named_entries=${entryCount}, errors=${Number(textSend.send_string_error_count || 0)}, warnings=${Number(textSend.send_string_warning_count || 0)}, blocking=${blocking.join(", ") || "-"}`;
}

function updateInteractionStatusUI(interaction) {
  ensureInteractionStatusRow();
  const el = document.getElementById("stat-interaction");
  if (!el) return;
  interaction = interaction || {};
  const caps = interaction.caps_word || {};
  const repeat = interaction.repeat_key || {};
  const keyLock = interaction.key_lock || {};
  const oneShot = interaction.one_shot_layer || {};
  if (!interaction.available) {
    el.textContent = "Unavailable";
    el.className = "status status-dot disconnected";
    el.title = "Interaction runtime: unavailable";
    return;
  }
  const capsText = caps.active ? "CW on" : "CW";
  const repeatText = repeat.history_available ? "Repeat ready" : "Repeat -";
  const altText = repeat.alternate_available ? "Alt ready" : "Alt -";
  const keyLockCount = Number(keyLock.active_count || 0);
  const keyLockText = keyLockCount > 0 ? `KeyLock ${keyLockCount}` : "KeyLock -";
  const oneShotCount = Number(oneShot.active_count || 0);
  const oneShotText = oneShotCount > 0 ? `OSL ${oneShotCount}` : "OSL -";
  el.textContent = `${capsText} / ${repeatText} / ${oneShotText} / ${keyLockText}`;
  el.className = "status status-dot " + (caps.active || repeat.history_available || oneShotCount > 0 || keyLockCount > 0 ? "output-warning" : "connected");
  el.title = `Interaction runtime: schema=${interaction.schema || ""}, caps_word.active=${caps.active}, repeat.history_available=${repeat.history_available}, repeat.alternate_available=${repeat.alternate_available}, repeat.alternate_pair_count=${repeat.alternate_pair_count}, one_shot_layer.active_count=${oneShotCount}, key_lock.active_count=${keyLockCount}, ${altText}, save_payload_includes_runtime_state=${interaction.save_payload_includes_runtime_state}`;
}

function updateBoardProfileStatusUI(board) {
  ensureBoardProfileStatusRow();
  const el = document.getElementById("stat-board-profile");
  if (!el) return;
  board = board || {};
  const version = board.board_version || "ver1.0";
  const source = board.source || "fallback";
  const prototype = Boolean(board.prototype);
  const runtime = board.runtime_profile || null;
  const label = board.display_label || (prototype ? `${version} prototype` : version);
  el.textContent = label;
  el.className = "status status-dot " + (
    source === "error" ? "disconnected" :
    runtime?.kind === "touch-panel" ? "connected" :
    prototype ? "output-warning" :
    "connected"
  );
  const runtimeText = runtime
    ? `, runtime=${runtime.kind}, touch_profile=${runtime.profile || ""}, touch_marker=${runtime.marker_path || ""}`
    : "";
  el.title = `Board profile: version=${version}, source=${source}, marker=${board.marker_path || ""}, device=${board.device_name || ""}${runtimeText}${board.error ? `, error=${board.error}` : ""}`;
}

function ensureBluetoothHostPanel() {
  if (document.getElementById("bt-host-panel")) return;
  const bluetoothRow = document.getElementById("stat-bluetooth")?.closest(".sysstat-row");
  if (!bluetoothRow) return;
  const panel = document.createElement("div");
  panel.id = "bt-host-panel";
  panel.className = "bt-host-panel";
  panel.innerHTML = '<div class="bt-host-panel-title">Bluetooth hosts</div><div id="bt-host-list" class="bt-host-list">–</div>';
  bluetoothRow.after(panel);
}

function bluetoothHostDisplayName(device) {
  const displayName = String(device?.display_name || "").trim();
  const name = String(device?.name || "").trim();
  const mac = String(device?.mac || "").trim();
  if (displayName && name && mac) return `${displayName} (${name} / ${mac})`;
  if (displayName && mac) return `${displayName} (${mac})`;
  if (name && mac) return `${name} (${mac})`;
  return name || mac || "unknown host";
}

function bluetoothHostStateText(device) {
  const states = [];
  if (device?.connected === true) states.push("connected");
  if (device?.paired === true || device?.bonded === true) states.push("paired");
  if (device?.trusted === true) states.push("trusted");
  if (device?.connected === false && states.length === 0) states.push("known");
  return states.join(" / ") || "unknown";
}

function bluetoothHostClassName(device) {
  if (device?.connected === true) return "bt-host connected";
  if (device?.paired === true || device?.bonded === true) return "bt-host paired";
  if (device?.error) return "bt-host error";
  return "bt-host";
}

function bluetoothHostLastConnectedText(device) {
  const value = String(device?.last_connected_at || "").trim();
  if (!value) return "Last connected: -";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return `Last connected: ${value}`;
  return `Last connected: ${date.toLocaleString()}`;
}

function updateBluetoothHostPanel(bt) {
  ensureBluetoothHostPanel();
  const list = document.getElementById("bt-host-list");
  const panel = document.getElementById("bt-host-panel");
  if (!list || !panel) return;
  const devices = Array.isArray(bt?.devices) ? bt.devices : [];
  panel.hidden = _statusViewMode === "simple";
  list.innerHTML = "";
  if (!bt?.available) {
    list.textContent = "Bluetooth unavailable";
    return;
  }
  if (!devices.length) {
    list.textContent = "No known hosts";
    return;
  }
  for (const device of devices) {
    const row = document.createElement("div");
    row.className = bluetoothHostClassName(device);
    const name = document.createElement("span");
    name.className = "bt-host-name";
    name.textContent = bluetoothHostDisplayName(device);
    const state = document.createElement("span");
    state.className = "bt-host-state";
    state.textContent = bluetoothHostStateText(device);
    const last = document.createElement("span");
    last.className = "bt-host-last-connected";
    last.textContent = bluetoothHostLastConnectedText(device);
    const rename = document.createElement("button");
    rename.type = "button";
    rename.className = "bt-host-rename";
    rename.textContent = "Rename";
    rename.disabled = !device?.mac;
    rename.addEventListener("click", (event) => {
      event.stopPropagation();
      renameBluetoothHost(device);
    });
    row.title = device?.error
      ? `${bluetoothHostDisplayName(device)}: ${device.error}`
      : `paired=${device?.paired}, bonded=${device?.bonded}, trusted=${device?.trusted}, connected=${device?.connected}, display_name_source=${device?.display_name_source || "-"}, last_connected_at=${device?.last_connected_at || "-"}, last_connected_source=${device?.last_connected_source || "-"}`;
    row.append(name, state, last, rename);
    list.appendChild(row);
  }
}

async function renameBluetoothHost(device) {
  const mac = String(device?.mac || "").trim();
  if (!mac) return;
  const current = String(device?.display_name || device?.name || "").trim();
  const next = window.prompt(`Bluetooth host ${mac} の表示名`, current);
  if (next === null) return;
  const trimmed = next.trim();
  const body = trimmed ? { display_name: trimmed } : { clear: true };
  try {
    const resp = await csrfFetch(`/api/bluetooth/hosts/${encodeURIComponent(mac)}/rename`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      console.warn("Bluetooth host rename failed", data);
    }
  } catch (e) {
    console.warn("Bluetooth host rename failed", e);
  } finally {
    await fetchStatus();
  }
}

function updateStatusUI(data) {
  const hidEl = document.getElementById("stat-hid");
  if (hidEl) {
    const hid = data.hid || {};
    if (!hid.exists) {
      hidEl.textContent = "No device";
      hidEl.className = "status status-dot disconnected";
    } else if (hid.connected) {
      hidEl.textContent = "Connected";
      hidEl.className = "status status-dot connected";
    } else {
      hidEl.textContent = hid.udc_state || "Disconnected";
      hidEl.className = "status status-dot disconnected";
    }
    hidEl.title = `HID Gadget: ${hidEl.textContent}`;
  }

  const modeEl = document.getElementById("stat-mode");
  if (modeEl) {
    const mode = data.mode || "";
    const target = data.output_target || data.output?.output_target || "";
    const modeLabel = outputModeDisplayLabel(mode);
    const targetLabel = outputModeDisplayLabel(target);
    const label = data.output?.display_label || (target === "auto" && modeLabel ? `AUTO ${modeLabel}` : (targetLabel || modeLabel));
    modeEl.textContent = label || "Unavailable";
    modeEl.className = "status status-dot " + (
      mode === "gadget" || target === "auto" ? "connected" :
      mode === "bt" ? "output-bt" :
      mode === "uinput" ? "output-warning" :
      "disconnected"
    );
    modeEl.title = target === "auto"
      ? `Output mode: auto (${mode || "unknown"})`
      : `Output mode: ${modeEl.textContent}`;
  }

  const procs = data.processes || {};
  for (const [name, running] of Object.entries(procs)) {
    const el = document.getElementById(`stat-${name}`);
    if (!el) continue;
    el.textContent = running ? "Running" : "Stopped";
    el.className = "status status-dot " + (running ? "connected" : "disconnected");
    el.title = `${name}: ${el.textContent}`;
  }
  const hiddEl = document.getElementById("stat-hidd");
  if (hiddEl) {
    const broker = data.hid_broker || data.hidd || data.usbd || {};
    const ready = Boolean(broker.broker_ready);
    const owner = broker.owner || "unknown";
    hiddEl.textContent = ready ? "Ready" : (procs.hidd ? "Running" : "Stopped");
    hiddEl.className = "status status-dot " + (ready || procs.hidd ? "connected" : "disconnected");
    hiddEl.title = `HID broker: owner=${owner}, ready=${ready}`;
  }

  const btEl = document.getElementById("stat-bluetooth");
  if (btEl) {
    const bt = data.bluetooth || {};
    const paired = bt.paired_devices?.length || 0;
    const connected = bt.connected_devices?.length || 0;
    if (!bt.available) {
      btEl.textContent = "Unavailable";
      btEl.className = "status status-dot disconnected";
    } else if (bt.powered) {
      btEl.textContent = connected ? `Connected ${connected}` : (bt.pairable || bt.discoverable ? "Pairing" : "Powered");
      btEl.className = "status status-dot connected";
    } else {
      btEl.textContent = "Off";
      btEl.className = "status status-dot disconnected";
    }
    btEl.title = `Bluetooth: powered=${bt.powered}, pairable=${bt.pairable}, discoverable=${bt.discoverable}, paired=${paired}, connected=${connected}`;
    updateBluetoothIndicators(bt, { paired, connected });
    updateBluetoothHostPanel(bt);
  }
  updateWifiStatusUI(data.wifi || {});
  updateBoardProfileStatusUI(data.board_profile || {});
  updateInteractionStatusUI(data.interaction || {});
  updateTextSendStatusUI(data.text_send || {});
}

function setBtStep(id, state, title) {
  const el = document.getElementById(id);
  if (!el) return;
  el.className = `bt-step ${state}`;
  el.title = title;
  el.setAttribute("aria-label", title);
}

function updateBluetoothIndicators(bt, counts = {}) {
  const available = Boolean(bt.available);
  const powered = Boolean(bt.powered);
  const pairing = powered && Boolean(bt.pairable || bt.discoverable);
  const connected = Number(counts.connected || 0);
  const paired = Number(counts.paired || 0);

  if (!available) {
    setBtStep("stat-bt-power", "error", "Power: unavailable");
    setBtStep("stat-bt-pairing", "error", "Pairing: unavailable");
    setBtStep("stat-bt-connected", "error", "Connected: unavailable");
    return;
  }

  setBtStep(
    "stat-bt-power",
    powered ? "on" : "off",
    powered ? "Power: on" : "Power: off",
  );
  setBtStep(
    "stat-bt-pairing",
    pairing ? "pairing" : "off",
    pairing
      ? `Pairing: on (pairable=${Boolean(bt.pairable)}, discoverable=${Boolean(bt.discoverable)})`
      : "Pairing: off",
  );
  setBtStep(
    "stat-bt-connected",
    connected > 0 ? "connected" : "off",
    connected > 0 ? `Connected: ${connected} / Paired: ${paired}` : `Connected: none / Paired: ${paired}`,
  );

  const pairOnBtn = document.getElementById("bt-pair-on-btn");
  const pairOffBtn = document.getElementById("bt-pair-off-btn");
  const forgetBtn = document.getElementById("bt-forget-btn");
  if (pairOnBtn) pairOnBtn.disabled = !available || !powered || pairing;
  if (pairOffBtn) pairOffBtn.disabled = !available || !powered || !pairing;
  if (forgetBtn) forgetBtn.disabled = !available || !powered || paired <= 0;
}

async function setBluetoothPairing(mode) {
  const buttons = [
    document.getElementById("bt-pair-on-btn"),
    document.getElementById("bt-pair-off-btn"),
    document.getElementById("bt-forget-btn"),
  ].filter(Boolean);
  buttons.forEach(btn => { btn.disabled = true; });
  try {
    const resp = await csrfFetch("/api/bluetooth/pairing", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      console.warn("Bluetooth pairing action failed", data);
    }
  } catch (e) {
    console.warn("Bluetooth pairing action failed", e);
  } finally {
    await fetchStatus();
  }
}

async function forgetBluetoothDevices() {
  const ok = window.confirm("Bluetoothのペア済みデバイスを削除します。続行しますか？");
  if (!ok) return;
  const buttons = [
    document.getElementById("bt-pair-on-btn"),
    document.getElementById("bt-pair-off-btn"),
    document.getElementById("bt-forget-btn"),
  ].filter(Boolean);
  buttons.forEach(btn => { btn.disabled = true; });
  try {
    const resp = await csrfFetch("/api/bluetooth/forget", { method: "POST" });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      console.warn("Bluetooth forget action failed", data);
    }
  } catch (e) {
    console.warn("Bluetooth forget action failed", e);
  } finally {
    await fetchStatus();
  }
}

function startStatusPolling(intervalMs = 3000) {
  fetchStatus();
  setInterval(fetchStatus, intervalMs);
}

async function fetchLogs(service, lines = 100) {
  const outputEl = document.getElementById("log-output");
  if (outputEl) outputEl.textContent = "読み込み中…";
  try {
    const resp = await fetch(`/api/logs?service=${encodeURIComponent(service)}&lines=${lines}`);
    const data = await resp.json();
    if (!resp.ok) {
      if (outputEl) outputEl.textContent = `エラー: ${data.error || resp.status}`;
      return;
    }
    if (outputEl) {
      outputEl.textContent = data.lines.length > 0
        ? data.lines.join("\n")
        : "(ログなし)";
      outputEl.scrollTop = outputEl.scrollHeight;
    }
  } catch (e) {
    if (outputEl) outputEl.textContent = `取得失敗: ${e.message}`;
  }
}

function openLogPanel(service) {
  _currentLogService = service;
  const panel = document.getElementById("log-panel");
  const title = document.getElementById("log-panel-title");
  if (title) title.textContent = `${service} ログ`;
  if (panel) panel.style.display = "flex";
  fetchLogs(service);
}

function closeLogPanel() {
  _currentLogService = null;
  const panel = document.getElementById("log-panel");
  if (panel) panel.style.display = "none";
}

function refreshLog() {
  if (_currentLogService) fetchLogs(_currentLogService);
}

function closeLogPanelOnOutsidePointer(event) {
  if (!_currentLogService) return;
  const panel = document.getElementById("log-panel");
  if (!panel || panel.style.display === "none") return;
  if (panel.contains(event.target)) return;
  closeLogPanel();
}

function initLogPanelEvents() {
  document.querySelectorAll(".sysstat-row[data-service]").forEach(row => {
    row.addEventListener("click", () => openLogPanel(row.dataset.service));
  });
  document.addEventListener("pointerdown", closeLogPanelOnOutsidePointer);
}
