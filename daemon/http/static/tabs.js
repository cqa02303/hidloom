"use strict";

const APP_TAB_KEY = "hidloom-active-app-tab";
const APP_TABS = new Set(["keyboard", "keymap", "lighting", "oled", "scripts", "interaction", "settings"]);
const INTERACTION_TAB_HASHES = new Set(["interaction-raw", "interaction-morse", "interaction-builders"]);
let _activeAppTab = "keyboard";
let _morseInspectorPanelScriptLoaded = false;

function appTabFromHash() {
  const hash = String(window.location.hash || "").replace(/^#/, "");
  if (INTERACTION_TAB_HASHES.has(hash)) return "interaction";
  return "";
}

function ensureMorseInspectorPanelScript() {
  if (_morseInspectorPanelScriptLoaded) return;
  _morseInspectorPanelScriptLoaded = true;
  const script = document.createElement("script");
  script.src = "/static/morse_inspector_panel.js";
  script.async = true;
  document.body.appendChild(script);
}

function setActiveTab(tab, options = {}) {
  const syncMode = options.syncMode !== false;
  const persist = options.persist !== false;
  const fetchOnActivate = options.fetch !== false;
  if (!APP_TABS.has(tab)) return;
  if (tab !== "keyboard" && typeof window.cancelTouchFlickPreview === "function") {
    window.cancelTouchFlickPreview("tab_switch");
  }
  _activeAppTab = tab;
  if (persist) {
    try {
      window.localStorage.setItem(APP_TAB_KEY, tab);
    } catch (_e) {
      // localStorage が使えない環境では現在のページ内だけで保持する
    }
  }

  document.querySelectorAll(".app-tab").forEach(btn => {
    const selected = btn.dataset.appTab === tab;
    btn.classList.toggle("active", selected);
    btn.setAttribute("aria-selected", String(selected));
    btn.tabIndex = selected ? 0 : -1;
  });

  const keyboardContainer = document.getElementById("keyboard-container");
  const keyboardToolbar = document.getElementById("keyboard-tab-toolbar");
  const keymapToolbar = document.getElementById("keymap-tab-toolbar");
  const lightingPanel = document.getElementById("lighting-panel");
  const oledPanel = document.getElementById("oled-panel");
  const scriptsPanel = document.getElementById("scripts-panel");
  const interactionPanel = document.getElementById("interaction-panel");
  const settingsPanel = document.getElementById("settings-panel");
  const nonKeyboardTab = tab === "lighting" || tab === "oled" || tab === "scripts" || tab === "interaction" || tab === "settings";
  if (keyboardContainer) keyboardContainer.classList.toggle("tab-hidden", nonKeyboardTab);
  if (keyboardToolbar) keyboardToolbar.classList.toggle("tab-hidden", tab !== "keyboard");
  if (keymapToolbar) keymapToolbar.classList.toggle("tab-hidden", tab !== "keymap");
  if (lightingPanel) {
    lightingPanel.classList.toggle("tab-hidden", tab !== "lighting");
    if (tab === "lighting") {
      fetchLighting();
    }
  }
  if (oledPanel) {
    oledPanel.classList.toggle("tab-hidden", tab !== "oled");
    if (tab === "oled" && fetchOnActivate && typeof fetchOledCustomization === "function") {
      fetchOledCustomization();
    }
  }
  if (scriptsPanel) {
    scriptsPanel.classList.toggle("tab-hidden", tab !== "scripts");
    if (tab === "scripts") fetchScripts();
  }
  if (interactionPanel) {
    interactionPanel.classList.toggle("tab-hidden", tab !== "interaction");
    if (tab === "interaction" && fetchOnActivate) {
      ensureMorseInspectorPanelScript();
      fetchInteractionSettings();
    }
  }
  if (settingsPanel) {
    settingsPanel.classList.toggle("tab-hidden", tab !== "settings");
    if (tab === "settings") fetchSettings();
  }

  const activePanel = tab === "keyboard" || tab === "keymap"
    ? keyboardContainer
    : document.getElementById(`${tab}-panel`);
  if (activePanel) {
    activePanel.classList.remove("panel-entering");
    void activePanel.offsetWidth;
    activePanel.classList.add("panel-entering");
  }

  if (!syncMode) return;
  if (tab === "keymap") {
    setRemapMode(true, { syncTab: false });
  } else {
    setRemapMode(false, { syncTab: false });
  }
}

function initActiveTab() {
  const hashTab = appTabFromHash();
  if (hashTab) {
    setActiveTab(hashTab, { persist: false });
    return;
  }
  let saved = "keyboard";
  try {
    saved = window.localStorage.getItem(APP_TAB_KEY) || "keyboard";
  } catch (_e) {
    saved = "keyboard";
  }
  setActiveTab(APP_TABS.has(saved) ? saved : "keyboard", { persist: false });
}

window.addEventListener("hashchange", () => {
  const hashTab = appTabFromHash();
  if (hashTab && hashTab !== _activeAppTab) setActiveTab(hashTab);
});

document.getElementById("app-tabs")?.addEventListener("keydown", event => {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  const tabs = [...document.querySelectorAll("#app-tabs .app-tab")];
  const current = Math.max(0, tabs.indexOf(document.activeElement));
  let next = current;
  if (event.key === "ArrowLeft") next = (current - 1 + tabs.length) % tabs.length;
  if (event.key === "ArrowRight") next = (current + 1) % tabs.length;
  if (event.key === "Home") next = 0;
  if (event.key === "End") next = tabs.length - 1;
  event.preventDefault();
  tabs[next].focus();
  setActiveTab(tabs[next].dataset.appTab);
});

function enhanceOperationFeedback() {
  const selectors = [".script-status", ".lighting-status", "#remap-direct-status"];
  const statusElements = document.querySelectorAll(selectors.join(","));
  const pendingPattern = /(読込|保存|測定|検査|反映|実行|リセット|reload)(中|しています|待ち)/i;
  const errorPattern = /失敗|error|invalid|確認してください/i;
  for (const el of statusElements) {
    if (!el.hasAttribute("role")) el.setAttribute("role", "status");
    if (!el.hasAttribute("aria-live")) el.setAttribute("aria-live", "polite");
    const update = () => {
      const text = el.textContent || "";
      const state = errorPattern.test(text) || el.classList.contains("error")
        ? "error"
        : pendingPattern.test(text)
          ? "pending"
          : text && text !== "–" ? "complete" : "idle";
      el.dataset.state = state;
      el.setAttribute("aria-busy", String(state === "pending"));
      el.classList.remove("status-feedback-pop");
      void el.offsetWidth;
      el.classList.add("status-feedback-pop");
    };
    new MutationObserver(update).observe(el, { childList: true, characterData: true, subtree: true });
    update();
  }
}

enhanceOperationFeedback();
