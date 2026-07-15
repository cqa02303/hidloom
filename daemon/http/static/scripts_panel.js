"use strict";

let _scriptsLoaded = false;

function setScriptStatus(text, isError = false) {
  const el = document.getElementById("script-status");
  if (!el) return;
  el.textContent = text;
  el.classList.toggle("error", isError);
}

function _scriptSafetyIsDangerous(script) {
  return Boolean(script && script.safety && script.safety.dangerous);
}

function _scriptSafetySummary(script) {
  if (!_scriptSafetyIsDangerous(script)) return "";
  const safety = script.safety || {};
  const names = [
    ...(Array.isArray(safety.dangers) ? safety.dangers : []),
    ...(Array.isArray(safety.auto_dangers) ? safety.auto_dangers : []),
  ];
  return Array.from(new Set(names)).join(", ") || "dangerous";
}

function _scriptOptionLabel(script) {
  const label = script.label ? ` - ${script.label}` : "";
  const danger = _scriptSafetyIsDangerous(script) ? ` ⚠ ${_scriptSafetySummary(script)}` : "";
  const suffix = script.exists ? "" : " (未作成)";
  return `${script.keycode}${label}${danger}${suffix}`;
}

async function fetchScripts(force = false, preferredKeycode = "") {
  const select = document.getElementById("script-select");
  const contentEl = document.getElementById("script-content");
  if (!select || !contentEl) return;
  if (_scriptsLoaded && !force) return;
  const previous = preferredKeycode || select.value;

  setScriptStatus("読込中");
  try {
    const resp = await fetch("/api/scripts");
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") {
      setScriptStatus(data.msg || `HTTP ${resp.status}`, true);
      return;
    }

    select.innerHTML = "";
    for (const script of data.scripts || []) {
      const opt = document.createElement("option");
      opt.value = script.keycode;
      opt.textContent = _scriptOptionLabel(script);
      opt.title = _scriptSafetyIsDangerous(script)
        ? `${script.path || ""}\nDanger: ${_scriptSafetySummary(script)}\n${script.safety.confirm_message || ""}`.trim()
        : script.path || "";
      opt.dataset.dangerous = _scriptSafetyIsDangerous(script) ? "1" : "0";
      select.appendChild(opt);
    }
    if (previous && [...select.options].some((option) => option.value === previous)) {
      select.value = previous;
    }
    _scriptsLoaded = true;
    setScriptStatus(select.options.length ? "同期済み" : "スクリプトなし", select.options.length === 0);
    if (select.options.length) {
      await window.fetchScriptContent(select.value);
    } else {
      if ("value" in contentEl) {
        contentEl.value = "表示できるスクリプトがありません";
      } else {
        contentEl.textContent = "表示できるスクリプトがありません";
      }
    }
  } catch (e) {
    setScriptStatus(e.message, true);
  }
}

async function fetchScriptContent(keycode) {
  const contentEl = document.getElementById("script-content");
  if (!contentEl || !keycode) return;
  contentEl.textContent = "読込中...";
  setScriptStatus("読込中");
  try {
    const resp = await fetch(`/api/scripts/${encodeURIComponent(keycode)}`);
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") {
      contentEl.textContent = data.msg || `HTTP ${resp.status}`;
      setScriptStatus(data.msg || `HTTP ${resp.status}`, true);
      return;
    }
    contentEl.textContent = data.content || "";
    const source = data.source === "runtime" ? "/mnt/p3" : data.source === "missing" ? "未作成" : "fallback";
    const safety = data.safety && data.safety.dangerous ? ` / ⚠ ${_scriptSafetySummary(data)}` : "";
    setScriptStatus(`${data.keycode} (${source})${safety}`);
  } catch (e) {
    contentEl.textContent = `取得失敗: ${e.message}`;
    setScriptStatus(e.message, true);
  }
}

function initScriptPanelEvents() {
  const select = document.getElementById("script-select");
  if (!select) return;
  select.addEventListener("change", () => window.fetchScriptContent(select.value));
}

window.refreshScripts = async function refreshScripts(preferredKeycode = "") {
  _scriptsLoaded = false;
  await fetchScripts(true, preferredKeycode);
};
