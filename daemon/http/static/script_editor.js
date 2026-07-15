"use strict";

// Editable KC_SHn script panel frontend.
// Backend endpoints expected:
//   PUT  /api/scripts/{KC_SHn}        { content: string }
//   POST /api/scripts/{KC_SHn}/reset
// The GET/list endpoints are already implemented in httpd.py.

const SCRIPT_SNIPPETS = {
  oledWarning: 'hidloom-oled warning "message" 3\n',
  oledAlert: 'hidloom-oled alert "message" 2\n',
  notifyWarning: 'hidloom-notify warning "message" 3\n',
  notifyAlert: 'hidloom-notify alert "message" 2\n',
  keytext: 'hidloom-keytext "ABCabc\\n"\n',
  keyTap: "hidloom-key tap 0x0204\n",
  sleep: "sleep 0.2\n",
  logger: 'logger -t KC_SH "message"\n',
  ctrlLayerGet: "hidloom-ctrl layer get\n",
  ctrlOutputBt: "hidloom-ctrl output bt\n",
  ctrlBtPairing: "hidloom-ctrl bt pairing-toggle\n",
  ctrlLedEffect: "hidloom-ctrl led effect 40 128 175 77 160\n",
};

const SCRIPT_HID_KEY_OPTIONS = [
  ["A", "0x04"], ["B", "0x05"], ["C", "0x06"], ["D", "0x07"],
  ["E", "0x08"], ["F", "0x09"], ["G", "0x0a"], ["H", "0x0b"],
  ["I", "0x0c"], ["J", "0x0d"], ["K", "0x0e"], ["L", "0x0f"],
  ["M", "0x10"], ["N", "0x11"], ["O", "0x12"], ["P", "0x13"],
  ["Q", "0x14"], ["R", "0x15"], ["S", "0x16"], ["T", "0x17"],
  ["U", "0x18"], ["V", "0x19"], ["W", "0x1a"], ["X", "0x1b"],
  ["Y", "0x1c"], ["Z", "0x1d"],
  ["1", "0x1e"], ["2", "0x1f"], ["3", "0x20"], ["4", "0x21"],
  ["5", "0x22"], ["6", "0x23"], ["7", "0x24"], ["8", "0x25"],
  ["9", "0x26"], ["0", "0x27"],
  ["Enter", "0x28"], ["Esc", "0x29"], ["Backspace", "0x2a"],
  ["Tab", "0x2b"], ["Space", "0x2c"],
  ["Minus", "0x2d"], ["Equal", "0x2e"], ["Left Bracket", "0x2f"],
  ["Right Bracket", "0x30"], ["Backslash", "0x31"], ["Non-US Hash", "0x32"],
  ["Semicolon", "0x33"],
  ["Quote", "0x34"], ["Grave", "0x35"], ["Comma", "0x36"],
  ["Dot", "0x37"], ["Slash", "0x38"], ["Caps Lock", "0x39"],
  ["F1", "0x3a"], ["F2", "0x3b"], ["F3", "0x3c"], ["F4", "0x3d"],
  ["F5", "0x3e"], ["F6", "0x3f"], ["F7", "0x40"], ["F8", "0x41"],
  ["F9", "0x42"], ["F10", "0x43"], ["F11", "0x44"], ["F12", "0x45"],
  ["Print Screen", "0x46"], ["Scroll Lock", "0x47"], ["Pause", "0x48"],
  ["Insert", "0x49"], ["Home", "0x4a"], ["Page Up", "0x4b"],
  ["Delete", "0x4c"], ["End", "0x4d"], ["Page Down", "0x4e"],
  ["Right", "0x4f"], ["Left", "0x50"], ["Down", "0x51"], ["Up", "0x52"],
  ["Num Lock", "0x53"],
  ["Keypad /", "0x54"], ["Keypad *", "0x55"], ["Keypad -", "0x56"],
  ["Keypad +", "0x57"], ["Keypad Enter", "0x58"], ["Keypad 1", "0x59"],
  ["Keypad 2", "0x5a"], ["Keypad 3", "0x5b"], ["Keypad 4", "0x5c"],
  ["Keypad 5", "0x5d"], ["Keypad 6", "0x5e"], ["Keypad 7", "0x5f"],
  ["Keypad 8", "0x60"], ["Keypad 9", "0x61"], ["Keypad 0", "0x62"],
  ["Keypad .", "0x63"], ["Application", "0x65"], ["Keypad =", "0x67"],
  ["F13", "0x68"], ["F14", "0x69"], ["F15", "0x6a"], ["F16", "0x6b"],
  ["F17", "0x6c"], ["F18", "0x6d"], ["F19", "0x6e"], ["F20", "0x6f"],
  ["F21", "0x70"], ["F22", "0x71"], ["F23", "0x72"], ["F24", "0x73"],
  ["Execute", "0x74"], ["Help", "0x75"], ["Menu", "0x76"],
  ["Select", "0x77"], ["Stop", "0x78"], ["Again", "0x79"],
  ["Undo", "0x7a"], ["Cut", "0x7b"], ["Copy", "0x7c"], ["Paste", "0x7d"],
  ["Find", "0x7e"], ["Mute", "0x7f"], ["Volume Up", "0x80"],
  ["Volume Down", "0x81"], ["Locking Caps Lock", "0x82"],
  ["Locking Num Lock", "0x83"], ["Locking Scroll Lock", "0x84"],
  ["Keypad Comma", "0x85"], ["Keypad = AS/400", "0x86"],
  ["International 1", "0x87"], ["International 2", "0x88"],
  ["International 3", "0x89"], ["International 4", "0x8a"],
  ["International 5", "0x8b"], ["International 6", "0x8c"],
  ["International 7", "0x8d"], ["International 8", "0x8e"],
  ["International 9", "0x8f"], ["Language 1", "0x90"],
  ["Language 2", "0x91"], ["Language 3", "0x92"], ["Language 4", "0x93"],
  ["Language 5", "0x94"], ["Language 6", "0x95"], ["Language 7", "0x96"],
  ["Language 8", "0x97"], ["Language 9", "0x98"],
  ["Alternate Erase", "0x99"], ["Cancel", "0x9b"], ["Clear", "0x9c"],
  ["Prior", "0x9d"], ["Separator", "0x9f"], ["Out", "0xa0"],
  ["Oper", "0xa1"], ["Clear Again", "0xa2"], ["CrSel", "0xa3"],
  ["ExSel", "0xa4"],
];

const SCRIPT_DANGER_PATTERNS = [
  ["reboot", /(^|[;&|`$()\s])(?:sudo\s+)?(?:systemctl\s+)?reboot(?:\s|$)/m],
  ["shutdown", /(^|[;&|`$()\s])(?:sudo\s+)?(?:shutdown|poweroff|halt)(?:\s|$)/m],
  ["systemctl-power", /(^|[;&|`$()\s])(?:sudo\s+)?systemctl\s+(?:poweroff|halt|reboot)(?:\s|$)/m],
  ["destructive-rm", /(^|[;&|`$()\s])(?:sudo\s+)?rm\s+-[A-Za-z]*r[fA-Za-z]*\s+\/(?:\s|$|[^/])/m],
];

function uniqueStrings(values) {
  return Array.from(new Set(values.filter((value) => typeof value === "string" && value.length)));
}

function analyzeScriptSafetyContent(content) {
  const text = content || "";
  const commandText = text.split(/\r?\n/).filter((line) => !line.trimStart().startsWith("#")).join("\n");
  const dangers = Array.from(text.matchAll(/^\s*#\s*@danger\s+([A-Za-z0-9_.:-]+)/gm)).map((m) => m[1].trim());
  const confirmations = Array.from(text.matchAll(/^\s*#\s*@confirm\s+(.+)$/gm)).map((m) => m[1].trim());
  const autoDangers = [];
  for (const [name, pattern] of SCRIPT_DANGER_PATTERNS) {
    if (pattern.test(commandText)) autoDangers.push(name);
  }
  return {
    dangers: uniqueStrings(dangers),
    confirmations: uniqueStrings(confirmations),
    auto_dangers: uniqueStrings(autoDangers),
    dangerous: dangers.length > 0 || autoDangers.length > 0,
  };
}

function scriptSafetySummary(meta) {
  if (!meta || !meta.dangerous) return "";
  return uniqueStrings([...(meta.dangers || []), ...(meta.auto_dangers || [])]).join(", ") || "dangerous";
}

function scriptSafetyConfirmMessage(meta) {
  if (!meta || !meta.dangerous) return "";
  if (Array.isArray(meta.confirmations) && meta.confirmations.length) return meta.confirmations.join("\n");
  return `危険操作候補を検出しました: ${scriptSafetySummary(meta)}\n本当に実行しますか？`;
}

function ensureScriptSafetyPanel() {
  const toolbar = document.querySelector("#scripts-panel .script-toolbar");
  if (!toolbar || document.getElementById("script-safety-panel")) return;
  const panel = document.createElement("div");
  panel.id = "script-safety-panel";
  panel.className = "script-safety-panel";
  panel.textContent = "Script safety: 未解析";
  toolbar.after(panel);
}

function updateScriptSafetyPanel() {
  ensureScriptSafetyPanel();
  const panel = document.getElementById("script-safety-panel");
  if (!panel) return;
  const meta = analyzeScriptSafetyContent(_scriptContentValue());
  panel.dataset.dangerous = meta.dangerous ? "1" : "0";
  if (meta.dangerous) {
    panel.textContent = `Dangerous script: ${scriptSafetySummary(meta)}. 実行前に追加確認します。`;
  } else {
    panel.textContent = "Script safety: 危険操作メタデータ/自動検出なし";
  }
}

function scriptHidAsciiPair(ch) {
  const code = ch.charCodeAt(0);
  if (code >= 97 && code <= 122) return [`0x${(0x04 + code - 97).toString(16).padStart(2, "0")}`, "0x00"];
  if (code >= 65 && code <= 90) return [`0x${(0x04 + code - 65).toString(16).padStart(2, "0")}`, "0x02"];
  if (code >= 49 && code <= 57) return [`0x${(0x1e + code - 49).toString(16).padStart(2, "0")}`, "0x00"];
  if (ch === "0") return ["0x27", "0x00"];
  const plain = {
    "\n": "0x28", "\r": "0x28", "\t": "0x2b", " ": "0x2c",
    "-": "0x2d", "=": "0x2e", "[": "0x2f", "]": "0x30",
    "\\": "0x31", ";": "0x33", "'": "0x34", "`": "0x35",
    ",": "0x36", ".": "0x37", "/": "0x38",
  };
  if (plain[ch]) return [plain[ch], "0x00"];
  const shifted = {
    "!": "0x1e", "@": "0x1f", "#": "0x20", "$": "0x21",
    "%": "0x22", "^": "0x23", "&": "0x24", "*": "0x25",
    "(": "0x26", ")": "0x27", "_": "0x2d", "+": "0x2e",
    "{": "0x2f", "}": "0x30", "|": "0x31", ":": "0x33",
    '"': "0x34", "~": "0x35", "<": "0x36", ">": "0x37",
    "?": "0x38",
  };
  if (shifted[ch]) return [shifted[ch], "0x02"];
  return null;
}

function _scriptEditorEl() {
  return document.getElementById("script-content");
}

function _scriptContentValue() {
  const el = _scriptEditorEl();
  if (!el) return "";
  if ("value" in el) return el.value;
  return el.textContent || "";
}

function _setScriptContentValue(content) {
  const el = _scriptEditorEl();
  if (!el) return;
  if ("value" in el) {
    el.value = content || "";
  } else {
    el.textContent = content || "";
  }
}

function insertScriptText(text) {
  const el = _scriptEditorEl();
  if (!el || !("value" in el)) return;
  const start = el.selectionStart ?? el.value.length;
  const end = el.selectionEnd ?? el.value.length;
  el.value = `${el.value.slice(0, start)}${text}${el.value.slice(end)}`;
  el.focus();
  const next = start + text.length;
  el.setSelectionRange(next, next);
  setScriptStatus("挿入しました");
  updateScriptSafetyPanel();
}

function insertScriptSnippet(kind) {
  const snippet = SCRIPT_SNIPPETS[kind];
  if (snippet) insertScriptText(snippet);
}

function _normalizeScriptHexByte(value) {
  const text = String(value || "").trim();
  if (!text) return "0x00";
  const parsed = Number(text.startsWith("0x") || text.startsWith("0X") ? text : `0x${text}`);
  if (!Number.isInteger(parsed) || parsed < 0 || parsed > 255) return "0x00";
  return `0x${parsed.toString(16).padStart(2, "0")}`;
}

function _scriptHidModifierHex(selector = ".script-hid-mod") {
  let modifier = 0;
  for (const input of document.querySelectorAll(selector)) {
    if (input.checked) modifier |= Number(input.value);
  }
  return `0x${modifier.toString(16).padStart(2, "0")}`;
}

function _scriptHidCommandPrefixEnabled() {
  const checkbox = document.getElementById("script-hid-command-prefix");
  return Boolean(checkbox && checkbox.checked);
}

function _scriptHidPrefix() {
  return _scriptHidCommandPrefixEnabled() ? "hidloom-key tap " : "";
}

function _scriptHidChordArg(keycode, modifier) {
  const key = Number(keycode);
  const mod = Number(modifier);
  if (!Number.isInteger(key) || key < 0 || key > 255) return "0x00";
  if (!Number.isInteger(mod) || mod < 0 || mod > 255) return `0x${key.toString(16).padStart(2, "0")}`;
  if (mod === 0) return `0x${key.toString(16).padStart(2, "0")}`;
  return `0x${((mod << 8) | key).toString(16).padStart(4, "0")}`;
}

function scriptHidChordText(keycode, modifier) {
  return `${_scriptHidPrefix()}${_scriptHidChordArg(keycode, modifier)}`;
}

function scriptHidCommand() {
  const keyInput = document.getElementById("script-hid-key-code");
  return scriptHidChordText(_normalizeScriptHexByte(keyInput ? keyInput.value : "0x04"), _scriptHidModifierHex());
}

function scriptHidTextPairs() {
  const input = document.getElementById("script-hid-text-input");
  const text = input ? input.value : "";
  const pairs = [];
  for (const ch of text) {
    const pair = scriptHidAsciiPair(ch);
    if (pair) pairs.push(pair);
  }
  return pairs;
}

function scriptHidTextCommand() {
  const pairs = scriptHidTextPairs();
  if (!pairs.length) return _scriptHidCommandPrefixEnabled() ? "hidloom-key tap" : "";
  const textModifier = Number(_scriptHidModifierHex(".script-hid-text-mod"));
  return `${_scriptHidPrefix()}${pairs.map((pair) => _scriptHidChordArg(pair[0], Number(pair[1]) | textModifier)).join(" ")}`;
}

function updateScriptHidPreview() {
  const preview = document.getElementById("script-hid-preview");
  if (preview) preview.textContent = scriptHidCommand();
  const textPreview = document.getElementById("script-hid-text-preview");
  if (textPreview) textPreview.textContent = scriptHidTextCommand() || "文字列を入力してください";
}

function selectScriptHidKeyCode(value) {
  const keyInput = document.getElementById("script-hid-key-code");
  if (keyInput) keyInput.value = value || "0x04";
  updateScriptHidPreview();
}

function insertScriptHidCommand() {
  const suffix = _scriptHidCommandPrefixEnabled() ? "\n" : " ";
  insertScriptText(`${scriptHidCommand()}${suffix}`);
}

function insertScriptHidTextCommand() {
  const command = scriptHidTextCommand();
  if (!command) return;
  const suffix = _scriptHidCommandPrefixEnabled() ? "\n" : " ";
  insertScriptText(`${command}${suffix}`);
}

function initScriptHidKeyPopup() {
  const select = document.getElementById("script-hid-key-select");
  if (!select || select.options.length) return;
  for (const [label, value] of SCRIPT_HID_KEY_OPTIONS) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = `${label} (${value})`;
    select.appendChild(option);
  }
  select.value = "0x04";
  updateScriptHidPreview();
}

function _scriptsPanelIsActive() {
  const panel = document.getElementById("scripts-panel");
  return Boolean(panel && !panel.classList.contains("tab-hidden"));
}

function handleScriptEditorShortcut(e) {
  if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== "s") return;
  if (!_scriptsPanelIsActive()) return;
  e.preventDefault();
  saveScriptContent();
}

async function saveScriptContent() {
  return await saveScriptContentOnly();
}

async function saveScriptContentOnly() {
  const select = document.getElementById("script-select");
  const keycode = select ? select.value : "";
  if (!keycode) return false;
  setScriptStatus("保存中");
  try {
    const resp = await csrfFetch(`/api/scripts/${encodeURIComponent(keycode)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: _scriptContentValue() }),
    });
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") {
      setScriptStatus(data.msg || `HTTP ${resp.status}`, true);
      return false;
    }
    if (typeof window.refreshScripts === "function") {
      await window.refreshScripts(keycode);
    }
    setScriptStatus(`${keycode} 保存済み`);
    return true;
  } catch (e) {
    setScriptStatus(e.message, true);
    return false;
  }
}

function confirmDangerousScriptRun(actionLabel) {
  const safety = analyzeScriptSafetyContent(_scriptContentValue());
  if (!safety.dangerous) return true;
  const message = `${scriptSafetyConfirmMessage(safety)}\n\n対象操作: ${actionLabel}`;
  if (window.confirm(message)) return true;
  setScriptStatus(`危険scriptの${actionLabel}をキャンセルしました`);
  return false;
}

function scriptRunStatus(data, resp) {
  const out = [data.stdout, data.stderr].filter(Boolean).join(" / ");
  const suffix = out ? `: ${out.slice(0, 160)}` : "";
  return `${data.keycode || ""} ${data.msg || `HTTP ${resp.status}`}${suffix}`.trim();
}

async function runSavedScriptContent() {
  const select = document.getElementById("script-select");
  const keycode = select ? select.value : "";
  if (!keycode) return;
  if (!confirmDangerousScriptRun("通常実行")) return;
  const ok = window.confirm(`${keycode} の保存済みスクリプトを通常実行します。続行しますか？`);
  if (!ok) {
    setScriptStatus("通常実行をキャンセルしました");
    return;
  }
  setScriptStatus("通常実行中");
  try {
    const resp = await csrfFetch(`/api/scripts/${encodeURIComponent(keycode)}/run`, { method: "POST" });
    const data = await resp.json();
    setScriptStatus(scriptRunStatus(data, resp), !resp.ok || data.result !== "ok");
  } catch (e) {
    setScriptStatus(e.message, true);
  }
}

async function saveAndRunScriptContent() {
  const select = document.getElementById("script-select");
  const keycode = select ? select.value : "";
  if (!keycode) return;
  if (!confirmDangerousScriptRun("保存して実行")) return;
  const ok = window.confirm(`${keycode} を保存してから通常実行します。続行しますか？`);
  if (!ok) {
    setScriptStatus("保存して実行をキャンセルしました");
    return;
  }
  const saved = await saveScriptContentOnly();
  if (!saved) return;
  setScriptStatus("保存後に通常実行中");
  try {
    const resp = await csrfFetch(`/api/scripts/${encodeURIComponent(keycode)}/run`, { method: "POST" });
    const data = await resp.json();
    setScriptStatus(scriptRunStatus(data, resp), !resp.ok || data.result !== "ok");
  } catch (e) {
    setScriptStatus(e.message, true);
  }
}

async function checkRunScriptContent() {
  const select = document.getElementById("script-select");
  const keycode = select ? select.value : "";
  if (!keycode) return;
  if (!confirmDangerousScriptRun("チェック実行")) return;
  const ok = window.confirm(
    `${keycode} の現在のエディタ内容を httpd 権限で一時実行します。\n` +
    "保存はされませんが、スクリプト内のコマンドは実行されます。続行しますか？"
  );
  if (!ok) {
    setScriptStatus("チェック実行をキャンセルしました");
    return;
  }
  setScriptStatus("チェック実行中");
  try {
    const resp = await csrfFetch(`/api/scripts/${encodeURIComponent(keycode)}/check-run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: _scriptContentValue() }),
    });
    const data = await resp.json();
    setScriptStatus(scriptRunStatus(data, resp), !resp.ok || data.result !== "ok");
  } catch (e) {
    setScriptStatus(e.message, true);
  }
}

async function resetScriptContent() {
  const select = document.getElementById("script-select");
  const keycode = select ? select.value : "";
  if (!keycode) return;
  const ok = window.confirm(`${keycode} を初期テンプレートに戻します。よろしいですか？`);
  if (!ok) return;
  setScriptStatus("リセット中");
  try {
    const resp = await csrfFetch(`/api/scripts/${encodeURIComponent(keycode)}/reset`, { method: "POST" });
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") {
      setScriptStatus(data.msg || `HTTP ${resp.status}`, true);
      return;
    }
    if (typeof window.refreshScripts === "function") {
      await window.refreshScripts(keycode);
    } else {
      _setScriptContentValue(data.content || "");
    }
    const source = data.source === "missing" ? "未作成" : "初期状態";
    setScriptStatus(`${keycode} ${source}`);
  } catch (e) {
    setScriptStatus(e.message, true);
  }
}

// Override the display-only loader from keyboard.js so the same UI becomes editable.
window.fetchScriptContent = async function fetchScriptContentEditable(keycode) {
  if (!keycode) return;
  _setScriptContentValue("読込中...");
  setScriptStatus("読込中");
  try {
    const resp = await fetch(`/api/scripts/${encodeURIComponent(keycode)}`);
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") {
      _setScriptContentValue(data.msg || `HTTP ${resp.status}`);
      setScriptStatus(data.msg || `HTTP ${resp.status}`, true);
      return;
    }
    _setScriptContentValue(data.content || "");
    updateScriptSafetyPanel();
    const source = data.source === "runtime" ? "/mnt/p3" : data.source === "missing" ? "未作成" : "fallback";
    setScriptStatus(`${data.keycode} (${source})`);
  } catch (e) {
    _setScriptContentValue(`取得失敗: ${e.message}`);
    setScriptStatus(e.message, true);
  }
};

document.addEventListener("keydown", handleScriptEditorShortcut);
document.addEventListener("DOMContentLoaded", () => {
  initScriptHidKeyPopup();
  ensureScriptSafetyPanel();
  const editor = _scriptEditorEl();
  if (editor) editor.addEventListener("input", updateScriptSafetyPanel);
  updateScriptSafetyPanel();
});

window.analyzeScriptSafetyContent = analyzeScriptSafetyContent;
window.updateScriptSafetyPanel = updateScriptSafetyPanel;
window.insertScriptSnippet = insertScriptSnippet;
window.selectScriptHidKeyCode = selectScriptHidKeyCode;
window.updateScriptHidPreview = updateScriptHidPreview;
window.insertScriptHidCommand = insertScriptHidCommand;
window.insertScriptHidTextCommand = insertScriptHidTextCommand;
window.checkRunScriptContent = checkRunScriptContent;
window.runSavedScriptContent = runSavedScriptContent;
window.saveAndRunScriptContent = saveAndRunScriptContent;
