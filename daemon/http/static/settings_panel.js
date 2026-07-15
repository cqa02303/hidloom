"use strict";

function settingsEl(id) {
  return document.getElementById(id);
}

function setSettingsStatus(message, isError = false) {
  const el = settingsEl("settings-status");
  if (!el) return;
  el.textContent = message;
  el.classList.toggle("error", Boolean(isError));
}

function clearSettingsPasswordFields() {
  for (const id of ["settings-current-password", "settings-new-password", "settings-confirm-password"]) {
    const el = settingsEl(id);
    if (el) el.value = "";
  }
}

function setSendStringsStatus(message, isError = false) {
  const el = settingsEl("settings-send-strings-status");
  if (!el) return;
  el.textContent = message;
  el.classList.toggle("error", Boolean(isError));
}

function setAnalogStickStatus(message, isError = false) {
  const el = settingsEl("settings-stick-status");
  if (!el) return;
  el.textContent = message;
  el.classList.toggle("error", Boolean(isError));
}

let _analogStickCurrent = null;

function analogStickNumber(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function analogStickAxisModel(axis) {
  if (!axis || typeof axis !== "object") return null;
  const low = analogStickNumber(axis.low);
  const center = analogStickNumber(axis.center);
  const high = analogStickNumber(axis.high);
  if (low === null || center === null || high === null || high <= low) return null;
  return {
    low,
    center,
    high,
    span: high - low,
    invert: Boolean(axis.invert),
  };
}

function analogStickPercent(value, axis) {
  const numeric = analogStickNumber(value);
  if (numeric === null || !axis) return null;
  return Math.max(0, Math.min(100, ((numeric - axis.low) / axis.span) * 100));
}

function analogStickNormalized(value, axis) {
  const numeric = analogStickNumber(value);
  if (numeric === null || !axis) return null;
  const denom = numeric >= axis.center ? axis.high - axis.center : axis.center - axis.low;
  if (denom <= 0) return null;
  const direction = axis.invert ? -1 : 1;
  return Math.round(Math.max(-100, Math.min(100, ((numeric - axis.center) / denom) * 100 * direction)));
}

function mergeAnalogStickCalibration(base, update) {
  if (!base) return update || null;
  if (!update) return base;
  const merged = { ...base, ...update };
  for (const axisName of ["x", "y"]) {
    merged[axisName] = { ...(base[axisName] || {}), ...(update[axisName] || {}) };
  }
  return merged;
}

function analogStickMapModel(data) {
  const xAxis = analogStickAxisModel(data?.x);
  const yAxis = analogStickAxisModel(data?.y);
  if (!xAxis || !yAxis) return null;
  const xValue = analogStickNumber(data?.current?.x ?? data?.x?.value ?? data?.x?.center);
  const yValue = analogStickNumber(data?.current?.y ?? data?.y?.value ?? data?.y?.center);
  const pointX = analogStickPercent(xValue, xAxis);
  const pointY = analogStickPercent(yValue, yAxis);
  const centerX = analogStickPercent(xAxis.center, xAxis);
  const centerY = analogStickPercent(yAxis.center, yAxis);
  if (pointX === null || pointY === null || centerX === null || centerY === null) return null;
  const deadzone = Math.max(0, Math.min(100, Number(data?.deadzone || 0)));
  return {
    valid: data?.valid !== false,
    point: {
      x: pointX,
      y: 100 - pointY,
      normalized_x: analogStickNormalized(xValue, xAxis),
      normalized_y: analogStickNormalized(yValue, yAxis),
    },
    center: {
      x: centerX,
      y: 100 - centerY,
    },
    deadzone_radius: deadzone / 2,
    x: xAxis,
    y: yAxis,
  };
}

function renderAnalogStickMap(data) {
  const el = settingsEl("settings-stick-map");
  if (!el) return;
  const model = analogStickMapModel(data);
  if (!model) {
    el.textContent = "calibration map unavailable";
    el.classList.add("empty");
    return;
  }
  el.classList.remove("empty");
  const pointLabel = `x ${model.point.normalized_x ?? "?"} / y ${model.point.normalized_y ?? "?"}`;
  el.innerHTML = `
    <svg class="settings-stick-map-svg" viewBox="0 0 100 100" role="img" aria-label="Analog stick X/Y calibration map">
      <rect class="settings-stick-map-range" x="4" y="4" width="92" height="92" rx="3"></rect>
      <line class="settings-stick-map-axis" x1="${model.center.x}" y1="4" x2="${model.center.x}" y2="96"></line>
      <line class="settings-stick-map-axis" x1="4" y1="${model.center.y}" x2="96" y2="${model.center.y}"></line>
      <circle class="settings-stick-map-deadzone" cx="${model.center.x}" cy="${model.center.y}" r="${model.deadzone_radius}"></circle>
      <circle class="settings-stick-map-center" cx="${model.center.x}" cy="${model.center.y}" r="2.4"></circle>
      <circle class="settings-stick-map-point" cx="${model.point.x}" cy="${model.point.y}" r="3.3"></circle>
    </svg>
    <div class="settings-stick-map-meta">
      <span>${model.valid ? "valid" : "check range"}</span>
      <span>${pointLabel}</span>
    </div>`;
}

function renderAnalogStickResult(data) {
  const el = settingsEl("settings-stick-result");
  if (!el) return;
  el.textContent = data ? JSON.stringify(data, null, 2) : "–";
  renderAnalogStickMap(mergeAnalogStickCalibration(_analogStickCurrent, data));
}

function renderAnalogStickCurrent(data) {
  const el = settingsEl("settings-stick-current");
  _analogStickCurrent = data || null;
  if (!el) return;
  el.textContent = data ? JSON.stringify(data, null, 2) : "–";
  renderAnalogStickMap(data);
  const minRangeEl = settingsEl("settings-stick-min-range-volts");
  const minRangeVolts = Number(data?.min_range_volts);
  if (minRangeEl && Number.isFinite(minRangeVolts)) {
    minRangeEl.value = String(minRangeVolts);
  }
}

function renderSendStringsValidation(validation) {
  const target = settingsEl("settings-send-strings-validation");
  if (!target) return;
  target.textContent = validation ? JSON.stringify(validation, null, 2) : "–";
}

function normalizedSendStringEntry(entry) {
  if (typeof entry === "string") {
    return { text: entry, enabled: true, confirm: false, allow_newline: false };
  }
  const value = entry && typeof entry === "object" && !Array.isArray(entry) ? entry : {};
  return {
    text: typeof value.text === "string" ? value.text : "",
    enabled: value.enabled !== false,
    confirm: Boolean(value.confirm),
    allow_newline: Boolean(value.allow_newline),
  };
}

function addSendStringRow(name = "", entry = {}) {
  const rows = settingsEl("settings-send-strings-rows");
  if (!rows) return;
  const empty = rows.querySelector(".settings-send-strings-empty");
  if (empty) empty.remove();

  const normalized = normalizedSendStringEntry(entry);
  const row = document.createElement("div");
  row.className = "settings-send-string-row";

  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.placeholder = "name";
  nameInput.value = name;
  nameInput.dataset.field = "name";
  nameInput.addEventListener("input", syncSendStringRowsToEditor);

  const textInput = document.createElement("input");
  textInput.type = "text";
  textInput.placeholder = "text";
  textInput.value = normalized.text;
  textInput.dataset.field = "text";
  textInput.addEventListener("input", syncSendStringRowsToEditor);

  row.append(
    nameInput,
    textInput,
    sendStringCheckbox("enabled", "enabled", normalized.enabled),
    sendStringCheckbox("confirm", "confirm", normalized.confirm),
    sendStringCheckbox("allow_newline", "newline", normalized.allow_newline),
    sendStringActionButton(row, "Plan", previewSendStringRowPlan),
    sendStringActionButton(row, "Copy", copySendStringRowAction),
    sendStringRemoveButton(row),
  );
  rows.appendChild(row);
  syncSendStringRowsToEditor();
}

function sendStringCheckbox(field, labelText, checked) {
  const label = document.createElement("label");
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = checked;
  input.dataset.field = field;
  input.addEventListener("change", syncSendStringRowsToEditor);
  label.append(input, document.createTextNode(labelText));
  return label;
}

function sendStringRemoveButton(row) {
  const button = document.createElement("button");
  button.className = "lighting-btn";
  button.type = "button";
  button.textContent = "削除";
  button.addEventListener("click", () => {
    row.remove();
    syncSendStringRowsToEditor();
  });
  return button;
}

function sendStringActionButton(row, label, handler) {
  const button = document.createElement("button");
  button.className = "lighting-btn";
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", () => handler(row));
  return button;
}

function sendStringRowAction(row) {
  const name = row.querySelector('[data-field="name"]')?.value.trim();
  return name ? `TEXT(${name})` : "";
}

function previewSendStringRowPlan(row) {
  const action = sendStringRowAction(row);
  if (!action) {
    setSendStringsStatus("name を入力してください", true);
    return;
  }
  const input = settingsEl("settings-send-strings-plan-action");
  if (input) input.value = action;
  previewSendStringPlan();
}

async function copySendStringRowAction(row) {
  const action = sendStringRowAction(row);
  if (!action) {
    setSendStringsStatus("name を入力してください", true);
    return;
  }
  const input = settingsEl("settings-send-strings-plan-action");
  if (input) input.value = action;
  try {
    await navigator.clipboard.writeText(action);
    setSendStringsStatus(`${action} をコピーしました`);
  } catch (e) {
    setSendStringsStatus(`${action} をPlan actionへ入れました`);
  }
}

function renderSendStringRows(entries) {
  const rows = settingsEl("settings-send-strings-rows");
  if (!rows) return;
  rows.replaceChildren();
  const names = Object.keys(entries || {}).sort();
  if (!names.length) {
    const empty = document.createElement("div");
    empty.className = "settings-send-strings-empty";
    empty.textContent = "named entry は未設定です";
    rows.appendChild(empty);
    return;
  }
  for (const name of names) addSendStringRow(name, entries[name]);
}

function collectSendStringRows() {
  const rows = settingsEl("settings-send-strings-rows");
  const entries = {};
  if (!rows) return entries;
  for (const row of rows.querySelectorAll(".settings-send-string-row")) {
    const name = row.querySelector('[data-field="name"]')?.value.trim();
    if (!name) continue;
    const text = row.querySelector('[data-field="text"]')?.value || "";
    const entry = { text };
    if (!row.querySelector('[data-field="enabled"]')?.checked) entry.enabled = false;
    if (row.querySelector('[data-field="confirm"]')?.checked) entry.confirm = true;
    if (row.querySelector('[data-field="allow_newline"]')?.checked) entry.allow_newline = true;
    entries[name] = entry;
  }
  return entries;
}

function syncSendStringRowsToEditor() {
  const editor = settingsEl("settings-send-strings");
  if (!editor) return;
  editor.value = JSON.stringify(collectSendStringRows(), null, 2);
}

function renderSendStrings(entries, validation) {
  const editor = settingsEl("settings-send-strings");
  if (editor) editor.value = JSON.stringify(entries || {}, null, 2);
  renderSendStringRows(entries || {});
  const actionInput = settingsEl("settings-send-strings-plan-action");
  if (actionInput && !actionInput.value.trim()) {
    const firstName = Object.keys(entries || {}).sort()[0];
    if (firstName) actionInput.value = `TEXT(${firstName})`;
  }
  renderSendStringsValidation(validation || null);
}

async function fetchSettings() {
  try {
    const resp = await fetch("/api/settings");
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") {
      setSettingsStatus(data.msg || `HTTP ${resp.status}`, true);
      return;
    }
    const usernameEl = settingsEl("settings-http-username");
    if (usernameEl) usernameEl.value = data.http_basic_auth?.username || "admin";
    renderSendStrings(data.send_strings || {}, data.send_string_validation || null);
    renderAnalogStickCurrent(data.analog_stick_calibration || null);
    setSettingsStatus("–");
    setSendStringsStatus("–");
  } catch (e) {
    setSettingsStatus(`取得失敗: ${e.message}`, true);
  }
}

function parseSendStringsEditor() {
  const editor = settingsEl("settings-send-strings");
  const raw = editor?.value || "{}";
  const parsed = JSON.parse(raw);
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error("send_strings は JSON object にしてください");
  }
  return parsed;
}

function formatSendStrings() {
  try {
    renderSendStrings(parseSendStringsEditor(), null);
    setSendStringsStatus("整形しました");
  } catch (e) {
    setSendStringsStatus(`JSON ERROR: ${e.message}`, true);
  }
}

async function saveSendStrings(event) {
  if (event) event.preventDefault();
  const saveBtn = settingsEl("settings-send-strings-save");
  let entries;
  try {
    entries = parseSendStringsEditor();
  } catch (e) {
    setSendStringsStatus(`JSON ERROR: ${e.message}`, true);
    return;
  }

  if (saveBtn) saveBtn.disabled = true;
  setSendStringsStatus("保存中…");
  try {
    const reload = Boolean(settingsEl("settings-send-strings-reload")?.checked);
    const resp = await csrfFetch("/api/settings/send-strings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ send_strings: entries, reload }),
    });
    const data = await resp.json();
    renderSendStringsValidation(data.send_string_validation || null);
    if (!resp.ok || data.result !== "ok") {
      setSendStringsStatus(data.msg || `HTTP ${resp.status}`, true);
      return;
    }
    renderSendStrings(data.send_strings || {}, data.send_string_validation || null);
    const reloadText = data.reload ? ` / reload ${data.reload.result}` : "";
    setSendStringsStatus(`保存しました${reloadText}`);
  } catch (e) {
    setSendStringsStatus(`保存失敗: ${e.message}`, true);
  } finally {
    if (saveBtn) saveBtn.disabled = false;
  }
}

async function previewSendStringPlan() {
  const action = settingsEl("settings-send-strings-plan-action")?.value.trim() || "";
  const preview = settingsEl("settings-send-strings-plan-preview");
  const button = settingsEl("settings-send-strings-plan");
  if (!action) {
    setSendStringsStatus("Plan action を入力してください", true);
    return;
  }
  if (button) button.disabled = true;
  setSendStringsStatus("Plan preview中…");
  try {
    const resp = await csrfFetch("/api/interaction/text-send-safety/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    const data = await resp.json();
    if (preview) preview.textContent = JSON.stringify(data, null, 2);
    if (!resp.ok || data.result !== "ok") {
      setSendStringsStatus(data.reason || data.msg || `HTTP ${resp.status}`, true);
      return;
    }
    const plan = data.plan || {};
    const reasons = Array.isArray(plan.blocking_reasons) ? plan.blocking_reasons.join(", ") : "";
    const dry = plan.tap_dry_run || {};
    const suffix = dry.available ? ` / taps ${Number(dry.sequence_count || 0)}` : "";
    setSendStringsStatus(plan.real_send_allowed ? `Plan ready${suffix}` : reasons || "preview/no-op", !plan.real_send_allowed);
  } catch (e) {
    setSendStringsStatus(`Plan失敗: ${e.message}`, true);
  } finally {
    if (button) button.disabled = false;
  }
}

async function calibrateAnalogStick(phase, write = true) {
  const buttons = [
    settingsEl("settings-stick-center-dry"),
    settingsEl("settings-stick-center"),
    settingsEl("settings-stick-range-dry"),
    settingsEl("settings-stick-range"),
    settingsEl("settings-stick-validate"),
  ];
  const minRangeVolts = Number(settingsEl("settings-stick-min-range-volts")?.value || 0.1);
  if (!Number.isFinite(minRangeVolts) || minRangeVolts < 0 || minRangeVolts > 2) {
    setAnalogStickStatus("最小span電圧を確認してください", true);
    return;
  }
  if (phase === "validate") {
    for (const button of buttons) if (button) button.disabled = true;
    setAnalogStickStatus("保存値を検査中…");
    try {
      const resp = await csrfFetch("/api/settings/analog-stick/calibrate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phase, min_range_volts: minRangeVolts }),
      });
      const data = await resp.json();
      renderAnalogStickResult(data);
      setAnalogStickStatus(data.valid ? "保存値は有効です" : data.msg || "保存値を確認してください", !data.valid);
    } catch (e) {
      setAnalogStickStatus(`検査失敗: ${e.message}`, true);
    } finally {
      for (const button of buttons) if (button) button.disabled = false;
    }
    return;
  }
  const durationEl = phase === "center"
    ? settingsEl("settings-stick-center-duration")
    : settingsEl("settings-stick-range-duration");
  const duration = Number(durationEl?.value || (phase === "center" ? 2.0 : 10.0));
  if (!Number.isFinite(duration) || duration <= 0) {
    setAnalogStickStatus("測定秒数を確認してください", true);
    return;
  }
  if (phase === "range" && write && !window.confirm("測定中にスティックを外周まで大きく回してください。最大/最小を保存します。")) {
    setAnalogStickStatus("最大/最小測定をキャンセルしました");
    return;
  }

  for (const button of buttons) if (button) button.disabled = true;
  setAnalogStickStatus(phase === "center" ? "中心測定中…" : "最大/最小測定中…");
  try {
    const resp = await csrfFetch("/api/settings/analog-stick/calibrate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        phase,
        duration,
        write,
        backup: true,
        confirm_range: phase === "range" && write,
        min_range_volts: minRangeVolts,
      }),
    });
    const data = await resp.json();
    renderAnalogStickResult(data);
    if (!resp.ok || data.result !== "ok") {
      setAnalogStickStatus(data.msg || `HTTP ${resp.status}`, true);
      return;
    }
    if (write) {
      setAnalogStickStatus(phase === "center" ? "中心を保存しました" : "最大/最小を保存しました");
      fetchSettings();
    } else {
      setAnalogStickStatus(phase === "center" ? "中心を測定しました" : "最大/最小を測定しました");
    }
  } catch (e) {
    setAnalogStickStatus(`測定失敗: ${e.message}`, true);
  } finally {
    for (const button of buttons) if (button) button.disabled = false;
  }
}

async function saveHttpAuthPassword(event) {
  if (event) event.preventDefault();
  const currentPassword = settingsEl("settings-current-password")?.value || "";
  const newPassword = settingsEl("settings-new-password")?.value || "";
  const confirmPassword = settingsEl("settings-confirm-password")?.value || "";
  const saveBtn = settingsEl("settings-http-auth-save");

  if (newPassword !== confirmPassword) {
    setSettingsStatus("確認用パスワードが一致しません", true);
    return;
  }
  if (!newPassword) {
    setSettingsStatus("新しいパスワードを入力してください", true);
    return;
  }

  if (saveBtn) saveBtn.disabled = true;
  setSettingsStatus("保存中…");
  try {
    const resp = await csrfFetch("/api/settings/http-auth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
        confirm_password: confirmPassword,
      }),
    });
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") {
      setSettingsStatus(data.msg || `HTTP ${resp.status}`, true);
      return;
    }
    clearSettingsPasswordFields();
    setSettingsStatus("保存しました。次のアクセスから新しいパスワードでログインしてください。");
  } catch (e) {
    setSettingsStatus(`保存失敗: ${e.message}`, true);
  } finally {
    if (saveBtn) saveBtn.disabled = false;
  }
}
