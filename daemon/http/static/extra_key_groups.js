"use strict";

// UI-only label aliases for keycodes that are useful in the remap popup.
// Category ownership lives in remap_key_groups.js. This file enriches labels
// and keeps those labels stable even when /api/layout refreshes _labelsCache.

try {
  const mediaGroup = OTHER_KEY_GROUPS.find(g => g.label === "メディア");
  if (mediaGroup) {
    const mediaKeys = [
      "KC_MPLY", "KC_MNXT", "KC_MPRV", "KC_MSTP",
      "KC_MFFD", "KC_MRWD", "KC_BRIU", "KC_BRID",
    ];
    for (const kc of mediaKeys) {
      if (!mediaGroup.keys.includes(kc)) mediaGroup.keys.push(kc);
    }
  }

  const EXTRA_KEY_LABELS = {
    MS_UP: "Mouse\n↑",
    MS_DOWN: "Mouse\n↓",
    MS_LEFT: "Mouse\n←",
    MS_RGHT: "Mouse\n→",
    MS_RIGHT: "Mouse\n→",
    MS_WHLU: "Wheel\n↑",
    MS_WHLD: "Wheel\n↓",
    MS_WHLL: "Wheel\n←",
    MS_WHLR: "Wheel\n→",
    KC_MPLY: "Play\nPause",
    KC_MNXT: "Next",
    KC_MPRV: "Prev",
    KC_MSTP: "Stop",
    KC_MFFD: "Fast\nFwd",
    KC_MRWD: "Rewind",
    KC_BRIU: "Bright\n+",
    KC_BRID: "Bright\n-",
    KC_BT: "Bluetooth",
    BT_STATUS: "BT\nStatus",
    BT_POWER_ON: "BT Pwr\nOn",
    BT_POWER_OFF: "BT Pwr\nOff",
    BT_POWER_TOGGLE: "BT Pwr\nToggle",
    BT_PAIRING_ON: "BT Pair\nOn",
    BT_PAIRING_OFF: "BT Pair\nOff",
    BT_PAIRING_TOGGLE: "BT Pair\nToggle",
    BT_DISCONNECT: "BT\nDisconnect",
    BT_FORGET_DEVICE: "BT\nForget",
    WIFI_STATUS: "Wi-Fi\nStatus",
    WIFI_POWER_ON: "Wi-Fi\nOn",
    WIFI_POWER_OFF: "Wi-Fi\nOff",
    WIFI_POWER_TOGGLE: "Wi-Fi\nToggle",
    "LSFT(LGUI(KC_F23))": "Copilot",
    KC_SH0: "Script\n0",
    KC_SH1: "Script\n1",
    KC_SH2: "Script\n2",
    KC_SH3: "Script\n3",
    KC_SH4: "Script\n4",
    KC_SH5: "Script\n5",
    KC_SH6: "Script\n6",
    KC_SH7: "Script\n7",
    KC_SH8: "Script\n8",
    KC_SH9: "Script\n9",
    KC_SH10: "Script\n10 ⚠",
  };

  window.HIDLOOM_EXTRA_KEY_LABELS = EXTRA_KEY_LABELS;
  Object.assign(_labelsCache, EXTRA_KEY_LABELS);

  const _baseKeycodeLabel = keycodeLabel;
  keycodeLabel = function patchedKeycodeLabel(kc) {
    const lab = EXTRA_KEY_LABELS[kc];
    if (lab) {
      const lines = lab.split("\n");
      return lines[lines.length - 1].trim() || lines[0].trim();
    }
    return _baseKeycodeLabel(kc);
  };
} catch (e) {
  console.warn("extra key labels unavailable", e);
}

function _cqaEnsureRemapSearchBox() {
  const popup = document.querySelector("#remap-popup .remap-popup-content");
  const tabs = document.querySelector("#remap-popup .remap-tabs");
  if (!popup || !tabs || document.getElementById("remap-search")) return;
  const wrap = document.createElement("div");
  wrap.className = "remap-search-row";
  wrap.style.cssText = "display:flex;gap:8px;align-items:center;margin:0 0 8px;flex-wrap:wrap";
  const input = document.createElement("input");
  input.id = "remap-search";
  input.type = "search";
  input.placeholder = "keycode / label / alias を検索";
  input.autocomplete = "off";
  input.style.cssText = "min-width:260px;flex:1;padding:6px 8px;border:1px solid #b9c3cf;border-radius:6px";
  const count = document.createElement("span");
  count.id = "remap-search-count";
  count.style.cssText = "color:#5b6673;font-size:12px;font-weight:700";
  const hint = document.createElement("span");
  hint.textContent = "Script 10 は危険操作候補として表示します";
  hint.style.cssText = "color:#8a5a00;font-size:12px;font-weight:700";
  input.addEventListener("input", _cqaApplyRemapSearchFilter);
  wrap.append(input, count, hint);
  popup.insertBefore(wrap, tabs.nextSibling);
}

function _cqaRemapSearchNeedle(el) {
  const kc = el.dataset.keycode || el.title || "";
  const label = el.textContent || "";
  const aria = el.getAttribute("aria-label") || "";
  return `${kc} ${label} ${aria}`.toLowerCase();
}

function _cqaApplyRemapSearchFilter() {
  const input = document.getElementById("remap-search");
  const count = document.getElementById("remap-search-count");
  const query = (input && input.value ? input.value : "").trim().toLowerCase();
  let total = 0;
  let visible = 0;
  for (const key of document.querySelectorAll(".remap-tab-pane .remap-key")) {
    total += 1;
    const match = !query || _cqaRemapSearchNeedle(key).includes(query);
    key.style.display = match ? "" : "none";
    if (match) visible += 1;
  }
  for (const group of document.querySelectorAll(".remap-other-group")) {
    const hasVisible = Array.from(group.querySelectorAll(".remap-key")).some((key) => key.style.display !== "none");
    group.style.display = hasVisible ? "" : "none";
  }
  if (count) count.textContent = query ? `${visible}/${total}` : "";
}

function _cqaPatchRemapSearch() {
  if (typeof window.initRemapSearchFilter === "function") {
    window.initRemapSearchFilter();
    return;
  }
  if (typeof renderAllRemapTabs === "function" && !renderAllRemapTabs.__cqaSearchPatched) {
    const baseRenderAllRemapTabs = renderAllRemapTabs;
    renderAllRemapTabs = function patchedRenderAllRemapTabs() {
      const result = baseRenderAllRemapTabs.apply(this, arguments);
      _cqaEnsureRemapSearchBox();
      _cqaApplyRemapSearchFilter();
      return result;
    };
    renderAllRemapTabs.__cqaSearchPatched = true;
  }
  if (typeof switchRemapTab === "function" && !switchRemapTab.__cqaSearchPatched) {
    const baseSwitchRemapTab = switchRemapTab;
    switchRemapTab = function patchedSwitchRemapTab() {
      const result = baseSwitchRemapTab.apply(this, arguments);
      _cqaApplyRemapSearchFilter();
      return result;
    };
    switchRemapTab.__cqaSearchPatched = true;
  }
}

function _cqaPatchWifiPowerOffWarning() {
  if (typeof applyRemap !== "function" || applyRemap.__cqaWifiWarningPatched) return;
  const baseApplyRemap = applyRemap;
  applyRemap = async function patchedApplyRemap(keycode) {
    if (keycode === "WIFI_POWER_OFF") {
      const ok = window.confirm(
        "Wi-Fi Off は SSH / HTTP UI 接続を切る可能性があります。\n再起動すると既定で Wi-Fi は復帰します。割り当てますか？"
      );
      if (!ok) {
        if (typeof showToast === "function") showToast("Wi-Fi Off の割り当てをキャンセルしました");
        return;
      }
    }
    return baseApplyRemap.apply(this, arguments);
  };
  applyRemap.__cqaWifiWarningPatched = true;
}

function _cqaAnalyzeScriptContent(content) {
  const text = content || "";
  const dangers = Array.from(text.matchAll(/^\s*#\s*@danger\s+([^\s#]+)/gm)).map((m) => m[1]);
  const confirmations = Array.from(text.matchAll(/^\s*#\s*@confirm\s+(.+)$/gm)).map((m) => m[1].trim());
  const auto = [];
  const patterns = [
    ["reboot", /(^|[;&|`$()\s])(?:sudo\s+)?(?:systemctl\s+)?reboot(?:\s|$)/m],
    ["shutdown", /(^|[;&|`$()\s])(?:sudo\s+)?(?:shutdown|poweroff|halt)(?:\s|$)/m],
    ["systemctl-power", /(^|[;&|`$()\s])(?:sudo\s+)?systemctl\s+(?:poweroff|halt|reboot)(?:\s|$)/m],
    ["destructive-rm", /(^|[;&|`$()\s])(?:sudo\s+)?rm\s+-[A-Za-z]*r[fA-Za-z]*\s+\/(?:\s|$|[^/])/m],
  ];
  for (const [name, re] of patterns) if (re.test(text)) auto.push(name);
  const unique = (values) => Array.from(new Set(values));
  return {
    dangers: unique(dangers),
    confirmations: unique(confirmations),
    auto_dangers: unique(auto),
    dangerous: dangers.length > 0 || auto.length > 0,
  };
}

function _cqaEnsureScriptSafetyPanel() {
  const toolbar = document.querySelector("#scripts-panel .script-toolbar");
  if (!toolbar || document.getElementById("script-safety-panel")) return;
  const panel = document.createElement("div");
  panel.id = "script-safety-panel";
  panel.style.cssText = "width:100%;padding:8px 10px;border:1px solid #d7dce3;border-radius:8px;background:#f7f9fb;color:#5b6673;font-size:12px;font-weight:700";
  panel.textContent = "Script safety: 未解析";
  toolbar.after(panel);
}

function _cqaUpdateScriptSafetyPanel() {
  _cqaEnsureScriptSafetyPanel();
  const panel = document.getElementById("script-safety-panel");
  const editor = document.getElementById("script-content");
  if (!panel || !editor) return;
  const content = "value" in editor ? editor.value : editor.textContent || "";
  const meta = _cqaAnalyzeScriptContent(content);
  panel.dataset.dangerous = meta.dangerous ? "1" : "0";
  if (meta.dangerous) {
    const labels = [...meta.dangers, ...meta.auto_dangers].join(", ");
    panel.textContent = `⚠ Dangerous script: ${labels || "unknown"}. check-run 前に追加確認します。`;
    panel.style.background = "#fff3cd";
    panel.style.borderColor = "#e7c665";
    panel.style.color = "#8a5a00";
  } else {
    panel.textContent = "Script safety: 危険操作メタデータ/自動検出なし";
    panel.style.background = "#f7f9fb";
    panel.style.borderColor = "#d7dce3";
    panel.style.color = "#5b6673";
  }
}

function _cqaPatchScriptSafety() {
  if (typeof window.updateScriptSafetyPanel === "function" && typeof window.analyzeScriptSafetyContent === "function") {
    window.updateScriptSafetyPanel();
    return;
  }
  _cqaEnsureScriptSafetyPanel();
  const editor = document.getElementById("script-content");
  if (editor && !editor.__cqaSafetyPatched) {
    editor.addEventListener("input", _cqaUpdateScriptSafetyPanel);
    editor.__cqaSafetyPatched = true;
  }
  if (window.fetchScriptContent && !window.fetchScriptContent.__cqaSafetyPatched) {
    const baseFetchScriptContent = window.fetchScriptContent;
    window.fetchScriptContent = async function patchedFetchScriptContent() {
      const result = await baseFetchScriptContent.apply(this, arguments);
      _cqaUpdateScriptSafetyPanel();
      return result;
    };
    window.fetchScriptContent.__cqaSafetyPatched = true;
  }
  if (window.checkRunScriptContent && !window.checkRunScriptContent.__cqaSafetyPatched) {
    const baseCheckRunScriptContent = window.checkRunScriptContent;
    window.checkRunScriptContent = async function patchedCheckRunScriptContent() {
      const editorNow = document.getElementById("script-content");
      const content = editorNow ? ("value" in editorNow ? editorNow.value : editorNow.textContent || "") : "";
      const meta = _cqaAnalyzeScriptContent(content);
      if (meta.dangerous) {
        const labels = [...meta.dangers, ...meta.auto_dangers].join(", ") || "unknown";
        const msg = meta.confirmations.join("\n") || `危険操作候補を検出しました: ${labels}\n本当にチェック実行しますか？`;
        if (!window.confirm(msg)) {
          if (typeof setScriptStatus === "function") setScriptStatus("危険scriptのチェック実行をキャンセルしました");
          return;
        }
      }
      return baseCheckRunScriptContent.apply(this, arguments);
    };
    window.checkRunScriptContent.__cqaSafetyPatched = true;
  }
  _cqaUpdateScriptSafetyPanel();
}

function _cqaInteractionSettingsFromEditor() {
  const editor = document.getElementById("interaction-editor");
  if (!editor) return null;
  try {
    const value = JSON.parse(editor.value || "{}");
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  } catch (_err) {
    return null;
  }
}

function _cqaWriteInteractionSettings(settings) {
  if (typeof updateInteractionEditor === "function") {
    updateInteractionEditor(settings);
  } else {
    const editor = document.getElementById("interaction-editor");
    if (editor) editor.value = JSON.stringify(settings, null, 2);
  }
  _cqaRenderInteractionSummary();
}

function _cqaEnsureInteractionSummary() {
  const wrap = document.querySelector(".interaction-editor-wrap");
  const editor = document.getElementById("interaction-editor");
  if (!wrap || !editor || document.getElementById("interaction-summary-panel")) return;
  const panel = document.createElement("div");
  panel.id = "interaction-summary-panel";
  panel.style.cssText = "display:grid;gap:8px;padding:10px;border:1px solid #d7dce3;border-radius:8px;background:#fff";
  editor.before(panel);
}

function _cqaMoveArrayItem(items, index, delta) {
  const next = index + delta;
  if (next < 0 || next >= items.length) return items;
  const copy = items.slice();
  const [item] = copy.splice(index, 1);
  copy.splice(next, 0, item);
  return copy;
}

function _cqaSummaryButton(label, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.className = "lighting-btn";
  button.style.minHeight = "24px";
  button.addEventListener("click", onClick);
  return button;
}

function _cqaRenderInteractionSection(panel, title, rows, handlers) {
  const section = document.createElement("div");
  section.style.cssText = "display:grid;gap:4px";
  const header = document.createElement("div");
  header.textContent = `${title} (${rows.length})`;
  header.style.cssText = "color:#1665aa;font-size:12px;font-weight:800";
  section.appendChild(header);
  if (!rows.length) {
    const empty = document.createElement("div");
    empty.textContent = "未定義";
    empty.style.cssText = "color:#6b7682;font-size:12px";
    section.appendChild(empty);
  }
  rows.forEach((row, index) => {
    const item = document.createElement("div");
    item.style.cssText = "display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px;align-items:center;padding:5px;border:1px solid #e0e5ea;border-radius:6px;background:#f7f9fb";
    const text = document.createElement("code");
    text.textContent = row;
    text.style.cssText = "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px";
    const actions = document.createElement("div");
    actions.style.cssText = "display:flex;gap:4px";
    actions.append(
      _cqaSummaryButton("↑", () => handlers.move(index, -1)),
      _cqaSummaryButton("↓", () => handlers.move(index, 1)),
      _cqaSummaryButton("削除", () => handlers.remove(index)),
    );
    item.append(text, actions);
    section.appendChild(item);
  });
  panel.appendChild(section);
}

function _cqaRenderInteractionSummary() {
  _cqaEnsureInteractionSummary();
  const panel = document.getElementById("interaction-summary-panel");
  if (!panel) return;
  panel.replaceChildren();
  const settings = _cqaInteractionSettingsFromEditor();
  if (settings === null) {
    panel.textContent = "Interaction summary: JSON parse error";
    return;
  }
  const combos = Array.isArray(settings.combos) ? settings.combos : [];
  const overrides = Array.isArray(settings.key_overrides) ? settings.key_overrides : [];
  const tapDanceEntries = settings.tap_dances && typeof settings.tap_dances === "object" && !Array.isArray(settings.tap_dances)
    ? Object.entries(settings.tap_dances)
    : [];
  _cqaRenderInteractionSection(panel, "Combo", combos.map((c) => `${JSON.stringify(c.keys)} → ${c.action || ""}`), {
    move: (i, d) => { settings.combos = _cqaMoveArrayItem(combos, i, d); _cqaWriteInteractionSettings(settings); },
    remove: (i) => { settings.combos = combos.filter((_v, idx) => idx !== i); _cqaWriteInteractionSettings(settings); },
  });
  _cqaRenderInteractionSection(panel, "Tap Dance", tapDanceEntries.map(([name, actions]) => `${name}: ${JSON.stringify(actions)}`), {
    move: (i, d) => {
      const moved = _cqaMoveArrayItem(tapDanceEntries, i, d);
      settings.tap_dances = Object.fromEntries(moved);
      _cqaWriteInteractionSettings(settings);
    },
    remove: (i) => {
      const next = tapDanceEntries.filter((_v, idx) => idx !== i);
      settings.tap_dances = Object.fromEntries(next);
      _cqaWriteInteractionSettings(settings);
    },
  });
  _cqaRenderInteractionSection(panel, "Key Override", overrides.map((o) => `${JSON.stringify(o.trigger)} + ${o.key || ""} → ${o.replacement || ""}`), {
    move: (i, d) => { settings.key_overrides = _cqaMoveArrayItem(overrides, i, d); _cqaWriteInteractionSettings(settings); },
    remove: (i) => { settings.key_overrides = overrides.filter((_v, idx) => idx !== i); _cqaWriteInteractionSettings(settings); },
  });
}

function _cqaPatchInteractionSummary() {
  if (typeof window.renderInteractionSummary === "function") {
    window.renderInteractionSummary();
    return;
  }
  _cqaEnsureInteractionSummary();
  const editor = document.getElementById("interaction-editor");
  if (editor && !editor.__cqaSummaryPatched) {
    editor.addEventListener("input", _cqaRenderInteractionSummary);
    editor.__cqaSummaryPatched = true;
  }
  for (const name of ["fetchInteractionSettings", "validateInteractionSettings", "saveInteractionSettings", "appendInteractionCombo", "appendInteractionTapDance", "appendInteractionKeyOverride", "formatInteractionSettings"]) {
    if (window[name] && !window[name].__cqaSummaryPatched) {
      const base = window[name];
      window[name] = async function patchedInteractionFunction() {
        const result = await base.apply(this, arguments);
        _cqaRenderInteractionSummary();
        return result;
      };
      window[name].__cqaSummaryPatched = true;
    }
  }
  _cqaRenderInteractionSummary();
}

window.addEventListener("load", () => {
  _cqaPatchRemapSearch();
  _cqaPatchWifiPowerOffWarning();
  _cqaPatchScriptSafety();
  _cqaPatchInteractionSummary();
});
