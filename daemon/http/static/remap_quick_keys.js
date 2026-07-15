"use strict";

// Remap popup quick access helpers.
//
// This file intentionally stores only UI preferences in localStorage.  It does
// not change keymap data until the user clicks one of the normal remap choices.
// The main remap_panel.js remains the source of truth for validation and save.

const REMAP_PINNED_STORAGE_KEY = "hidloom.remap.pinnedKeycodes.v1";
const REMAP_RECENT_STORAGE_KEY = "hidloom.remap.recentKeycodes.v1";
const REMAP_RECENT_LIMIT = 16;
const REMAP_QUICK_DOC_URL = "https://github.com/cqa02303/hidloom/blob/main/docs/keycode/unimplemented-keycodes.md";

function _remapQuickLoadList(key) {
  try {
    const raw = window.localStorage.getItem(key);
    const parsed = JSON.parse(raw || "[]");
    return Array.isArray(parsed) ? parsed.filter(kc => typeof kc === "string" && kc.length > 0) : [];
  } catch (_err) {
    return [];
  }
}

function _remapQuickSaveList(key, values) {
  try {
    const unique = Array.from(new Set(values.filter(kc => typeof kc === "string" && kc.length > 0)));
    window.localStorage.setItem(key, JSON.stringify(unique));
  } catch (_err) {
    // localStorage can be unavailable in private / restricted browser modes.
  }
}

function remapPinnedKeycodes() {
  return _remapQuickLoadList(REMAP_PINNED_STORAGE_KEY);
}

function remapRecentKeycodes() {
  return _remapQuickLoadList(REMAP_RECENT_STORAGE_KEY);
}

function isRemapPinnedKeycode(kc) {
  return remapPinnedKeycodes().includes(kc);
}

function toggleRemapPinnedKeycode(kc) {
  if (!kc) return;
  const pinned = remapPinnedKeycodes();
  const next = pinned.includes(kc) ? pinned.filter(item => item !== kc) : [kc, ...pinned];
  _remapQuickSaveList(REMAP_PINNED_STORAGE_KEY, next.slice(0, 32));
  refreshRemapQuickAccess();
}

function rememberRemapRecentKeycode(kc) {
  if (!kc || /^LT\(\d+\)$/.test(kc)) return;
  const recent = remapRecentKeycodes().filter(item => item !== kc);
  _remapQuickSaveList(REMAP_RECENT_STORAGE_KEY, [kc, ...recent].slice(0, REMAP_RECENT_LIMIT));
}

function remapQuickChoiceLabel(kc) {
  try {
    if (typeof remapChoiceLabel === "function") return remapChoiceLabel(kc);
    if (typeof keycodeLabel === "function") return keycodeLabel(kc);
  } catch (_err) {
    // fall back below
  }
  return String(kc || "").replace(/^KC_/, "").slice(0, 8);
}

function _remapQuickMakeButton(kc, options = {}) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "remap-quick-key";
  btn.dataset.keycode = kc;
  btn.title = kc;
  btn.textContent = remapQuickChoiceLabel(kc);
  if (options.pinned) btn.classList.add("remap-quick-key-pinned");
  btn.addEventListener("click", () => {
    if (typeof applyRemap === "function") applyRemap(kc);
  });
  return btn;
}

function _remapQuickMakePinButton(kc) {
  const pin = document.createElement("button");
  pin.type = "button";
  pin.className = "remap-pin-toggle";
  pin.dataset.keycode = kc;
  const pinned = isRemapPinnedKeycode(kc);
  pin.classList.toggle("active", pinned);
  pin.textContent = pinned ? "★" : "☆";
  pin.title = pinned ? "Pin解除" : "Pinに追加";
  pin.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    toggleRemapPinnedKeycode(kc);
  });
  return pin;
}

function decorateRemapPinButtons() {
  for (const key of document.querySelectorAll(".remap-tab-pane .remap-key")) {
    const kc = key.dataset.keycode || key.title || "";
    key.classList.toggle("remap-key-pinned", isRemapPinnedKeycode(kc));
    if (!kc || key.querySelector(".remap-pin-toggle")) continue;
    key.appendChild(_remapQuickMakePinButton(kc));
  }
}

function ensureRemapUnimplementedGuide() {
  const searchRow = document.querySelector("#remap-popup .remap-search-row");
  if (!searchRow || document.getElementById("remap-unimplemented-guide")) return;
  const guide = document.createElement("div");
  guide.id = "remap-unimplemented-guide";
  guide.className = "remap-unimplemented-guide";
  guide.innerHTML = '未実装・未対応候補は <a href="' + REMAP_QUICK_DOC_URL + '" target="_blank" rel="noopener noreferrer">docs/keycode/unimplemented-keycodes.md</a> を確認。追加時は keycodes / runtime / HTTP validation / Vial codec / docs を同期します。';
  searchRow.after(guide);
}

function renderRemapQuickAccess() {
  const popup = document.querySelector("#remap-popup .remap-popup-content");
  const tabs = document.querySelector("#remap-popup .remap-tabs");
  if (!popup || !tabs) return;

  let panel = document.getElementById("remap-quick-access");
  if (!panel) {
    panel = document.createElement("div");
    panel.id = "remap-quick-access";
    panel.className = "remap-quick-access";
    tabs.parentNode.insertBefore(panel, tabs.nextSibling);
  }
  panel.innerHTML = "";

  const pinned = remapPinnedKeycodes();
  const recent = remapRecentKeycodes().filter(kc => !pinned.includes(kc));
  if (pinned.length === 0 && recent.length === 0) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;

  if (pinned.length) {
    const group = document.createElement("div");
    group.className = "remap-quick-group";
    const label = document.createElement("span");
    label.className = "remap-quick-label";
    label.textContent = "Pinned";
    group.appendChild(label);
    for (const kc of pinned) group.appendChild(_remapQuickMakeButton(kc, { pinned: true }));
    panel.appendChild(group);
  }

  if (recent.length) {
    const group = document.createElement("div");
    group.className = "remap-quick-group";
    const label = document.createElement("span");
    label.className = "remap-quick-label";
    label.textContent = "Recent";
    group.appendChild(label);
    for (const kc of recent.slice(0, REMAP_RECENT_LIMIT)) group.appendChild(_remapQuickMakeButton(kc));
    panel.appendChild(group);
  }
}

function refreshRemapQuickAccess() {
  renderRemapQuickAccess();
  decorateRemapPinButtons();
  ensureRemapUnimplementedGuide();
}

function patchRemapQuickAccess() {
  if (typeof renderAllRemapTabs === "function" && !renderAllRemapTabs.__remapQuickAccessPatched) {
    const baseRenderAllRemapTabs = renderAllRemapTabs;
    renderAllRemapTabs = function patchedRenderAllRemapTabs() {
      const result = baseRenderAllRemapTabs.apply(this, arguments);
      refreshRemapQuickAccess();
      return result;
    };
    renderAllRemapTabs.__remapQuickAccessPatched = true;
  }

  if (typeof switchRemapTab === "function" && !switchRemapTab.__remapQuickAccessPatched) {
    const baseSwitchRemapTab = switchRemapTab;
    switchRemapTab = function patchedSwitchRemapTab() {
      const result = baseSwitchRemapTab.apply(this, arguments);
      refreshRemapQuickAccess();
      return result;
    };
    switchRemapTab.__remapQuickAccessPatched = true;
  }

  if (typeof applyRemap === "function" && !applyRemap.__remapQuickAccessPatched) {
    const baseApplyRemap = applyRemap;
    applyRemap = async function patchedApplyRemap(keycode) {
      const result = await baseApplyRemap.apply(this, arguments);
      rememberRemapRecentKeycode(keycode);
      refreshRemapQuickAccess();
      return result;
    };
    applyRemap.__remapQuickAccessPatched = true;
  }

  refreshRemapQuickAccess();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", patchRemapQuickAccess);
} else {
  patchRemapQuickAccess();
}
