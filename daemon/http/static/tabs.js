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
    btn.classList.toggle("active", btn.dataset.appTab === tab);
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
