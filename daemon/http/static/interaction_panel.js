"use strict";

const INTERACTION_ACTION_SUGGESTIONS = [
  "KC_ESC",
  "KC_TAB",
  "KC_ENTER",
  "KC_SPACE",
  "KC_BSPACE",
  "KC_LSFT",
  "KC_LCTL",
  "KC_LALT",
  "S(KC_1)",
  "LCTL(KC_C)",
  "LCTL(KC_V)",
  "MO(1)",
  "TG(1)",
  "TO(0)",
  "DF(0)",
  "OSL(1)",
  "LT(1,KC_SPACE)",
  "MT(KC_LSFT,KC_A)",
];

const INTERACTION_SNIPPETS = {
  combo: '{\n  "keys": [[0, 1], [0, 2]],\n  "action": "KC_ESC"\n}',
  tapDance: '"TD0": {\n  "1": "KC_A",\n  "2": "KC_ESC"\n}',
  override: '{\n  "trigger": "KC_LSFT",\n  "key": "KC_1",\n  "replacement": "KC_EXLM"\n}',
  conditional: '{\n  "name": "lower_raise_adjust",\n  "if_all": [1, 2],\n  "then": 3\n}',
  timing: '"tapping_term": 0.2,\n"hold_on_other_key_press": true,\n"combo_term": 0.05,\n"tap_dance_term": 0.2',
};

const INTERACTION_EDITOR_MODE_KEY = "hidloom-interaction-editor-mode";
const INTERACTION_ACCORDION_STATE_KEY = "hidloom-interaction-accordion-open";
const INTERACTION_ACCORDION_HASHES = {
  "interaction-raw": "interaction-raw-accordion",
  "interaction-morse": "interaction-morse-accordion",
  "interaction-builders": "interaction-builders-accordion",
};
const INTERACTION_ACCORDION_IDS = Object.values(INTERACTION_ACCORDION_HASHES);
const INTERACTION_BUILDER_WARNING_TARGETS = {
  combos: ".interaction-combo-builder",
  tap_dances: ".interaction-tap-dance-builder",
  key_overrides: ".interaction-key-override-builder",
};
const INTERACTION_BUILDER_UX_TARGETS = {
  combo: ".interaction-combo-builder",
  tap_dance: ".interaction-tap-dance-builder",
  key_override: ".interaction-key-override-builder",
  timing: ".interaction-timing-builder",
};

let _interactionActionOptions = [];
let _lastInteractionActionInput = null;
let _interactionActionPickerTarget = null;
let _interactionActionPickerCallback = null;
let _interactionActiveLayers = null;
let _interactionBuilderUx = null;
let _interactionComboPickTarget = null;
let _interactionConditionalInspector = null;
let _interactionEditingComboIndex = null;
let _interactionEditingTapDanceIndex = null;
let _interactionEditingOverrideIndex = null;
let _interactionInspector = null;
let _interactionRuntimeStatus = null;
let _interactionSavedText = "";
let _interactionTextSendPlan = null;
let _interactionTextSendSafety = null;
let _interactionValidatedText = "";

function uniqueInteractionActions(values) {
  return Array.from(new Set(values.filter((value) => typeof value === "string" && value.length)));
}

function interactionMetadataActions(metadata) {
  const shiftedAliases = metadata && metadata.shifted_aliases ? Object.keys(metadata.shifted_aliases) : [];
  const canonicalAliases = metadata && metadata.canonical_aliases ? Object.keys(metadata.canonical_aliases) : [];
  const canonicalActions = metadata && metadata.canonical_aliases ? Object.values(metadata.canonical_aliases) : [];
  const wrappers = metadata && metadata.modifier_wrappers ? Object.keys(metadata.modifier_wrappers) : [];
  const wrapperExamples = wrappers.slice(0, 4).map((wrapper) => `${wrapper}(KC_A)`);
  return uniqueInteractionActions([
    ...INTERACTION_ACTION_SUGGESTIONS,
    ...canonicalActions.slice(0, 10),
    ...canonicalAliases.slice(0, 10),
    ...shiftedAliases.slice(0, 8),
    ...wrapperExamples,
  ]);
}

function interactionLayoutActions(layout) {
  if (!layout || !Array.isArray(layout.keycodes)) return [];
  return layout.keycodes;
}

async function fetchInteractionLayoutActions() {
  try {
    const resp = await fetch("/api/layout");
    const data = await resp.json();
    if (!resp.ok) return [];
    return interactionLayoutActions(data);
  } catch (_err) {
    return [];
  }
}

function renderInteractionActionTools(metadata = {}, layoutActions = []) {
  const target = document.getElementById("interaction-action-buttons");
  const actions = uniqueInteractionActions([
    ...interactionMetadataActions(metadata),
    ...layoutActions,
  ]);

  _interactionActionOptions = actions;
  renderInteractionActionDatalist(actions);
  renderInteractionKeycodePicker(actions);
  if (!target) return;

  target.replaceChildren();
  for (const action of actions) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "interaction-action-btn";
    button.textContent = action;
    button.title = `Insert ${action}`;
    button.addEventListener("click", () => insertInteractionAction(action));
    target.appendChild(button);
  }
}

function renderInteractionKeycodePicker(actions) {
  const select = document.getElementById("interaction-keycode-picker");
  if (!select) return;
  const previous = select.value;
  select.replaceChildren();
  for (const action of actions) {
    const option = document.createElement("option");
    option.value = action;
    option.textContent = action;
    select.appendChild(option);
  }
  if (previous && actions.includes(previous)) select.value = previous;
}

function renderInteractionActionDatalist(actions) {
  const target = document.getElementById("interaction-action-datalist");
  if (!target) return;

  target.replaceChildren();
  for (const action of actions) {
    const option = document.createElement("option");
    option.value = action;
    target.appendChild(option);
  }
}

function insertInteractionText(text) {
  const editor = document.getElementById("interaction-editor");
  const status = document.getElementById("interaction-status");
  if (!editor) return;

  const start = editor.selectionStart ?? editor.value.length;
  const end = editor.selectionEnd ?? editor.value.length;
  editor.value = `${editor.value.slice(0, start)}${text}${editor.value.slice(end)}`;
  editor.focus();
  const next = start + text.length;
  editor.setSelectionRange(next, next);
  if (status) status.textContent = "挿入しました";
}

function ensureInteractionGuiLayout() {
  const gui = document.getElementById("interaction-gui-editors");
  const builders = document.getElementById("interaction-builders-accordion");
  if (gui && builders && builders.parentElement !== gui) gui.appendChild(builders);
}

function interactionSavedEditorMode() {
  try {
    return window.localStorage.getItem(INTERACTION_EDITOR_MODE_KEY) || "gui";
  } catch (_e) {
    return "gui";
  }
}

function setInteractionEditorMode(mode, options = {}) {
  const wrap = document.querySelector(".interaction-editor-wrap");
  const raw = document.getElementById("interaction-raw-accordion");
  const normalized = mode === "raw" ? "raw" : "gui";
  if (options.persist !== false) {
    try {
      window.localStorage.setItem(INTERACTION_EDITOR_MODE_KEY, normalized);
    } catch (_e) {
      // localStorage が使えない環境では現在のページ内だけで保持する
    }
  }
  if (wrap) {
    wrap.classList.toggle("interaction-mode-raw", normalized === "raw");
    wrap.classList.toggle("interaction-mode-gui", normalized === "gui");
  }
  if (raw && normalized === "raw") raw.open = true;
  document.getElementById("interaction-mode-gui-btn")?.classList.toggle("active", normalized === "gui");
  document.getElementById("interaction-mode-raw-btn")?.classList.toggle("active", normalized === "raw");
}

function interactionHashAccordionId() {
  const hash = String(window.location.hash || "").replace(/^#/, "");
  return INTERACTION_ACCORDION_HASHES[hash] || "";
}

function readInteractionAccordionState() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(INTERACTION_ACCORDION_STATE_KEY) || "[]");
    return new Set(Array.isArray(parsed) ? parsed.filter((id) => INTERACTION_ACCORDION_IDS.includes(id)) : []);
  } catch (_e) {
    return new Set();
  }
}

function persistInteractionAccordionState() {
  const openIds = INTERACTION_ACCORDION_IDS.filter((id) => document.getElementById(id)?.open);
  try {
    window.localStorage.setItem(INTERACTION_ACCORDION_STATE_KEY, JSON.stringify(openIds));
  } catch (_e) {
    // localStorage が使えない環境では現在のページ内だけで保持する
  }
}

function applyInteractionAccordionState() {
  const hashId = interactionHashAccordionId();
  if (hashId) {
    setInteractionEditorMode(hashId === "interaction-raw-accordion" ? "raw" : "gui");
    const target = document.getElementById(hashId);
    if (target) target.open = true;
    return;
  }
  const openIds = readInteractionAccordionState();
  if (!openIds.size) return;
  for (const id of INTERACTION_ACCORDION_IDS) {
    const accordion = document.getElementById(id);
    if (accordion) accordion.open = openIds.has(id);
  }
}

function bindInteractionAccordionState() {
  for (const id of INTERACTION_ACCORDION_IDS) {
    const accordion = document.getElementById(id);
    if (!accordion || accordion.dataset.interactionStateBound === "1") continue;
    accordion.dataset.interactionStateBound = "1";
    accordion.addEventListener("toggle", persistInteractionAccordionState);
  }
}

function focusedInteractionActionInput() {
  const active = document.activeElement;
  if (active && active.classList && active.classList.contains("interaction-action-input")) {
    return active;
  }
  return _lastInteractionActionInput || document.getElementById("interaction-combo-action");
}

function setInteractionActionInputValue(input, action) {
  if (!input || !action) return;
  const appendTrigger = input.id === "interaction-override-trigger" && input.value.trim();
  const text = appendTrigger ? `${input.value.trim()}, ${action}` : action;
  input.value = text;
  input.focus();
  input.setSelectionRange(text.length, text.length);
  _lastInteractionActionInput = input;
}

function interactionActionInputHelp(input) {
  if (!input || !input.id) return "Pick opens the shared Action picker; Plan is a read-only Text Send preview.";
  if (input.id.startsWith("interaction-tap-dance-action-")) {
    return "Tap Dance stores actions in TD(name); assign TD(name) to a keymap slot separately.";
  }
  if (input.id === "interaction-override-trigger") {
    return "Trigger accepts one or more action names, not row/col matrix positions.";
  }
  if (input.id === "interaction-override-key") {
    return "Key Override target is an action name; use Combo for physical row/col source keys.";
  }
  if (input.id === "interaction-override-replacement") {
    return "Replacement is the action emitted when trigger and key match.";
  }
  if (input.id === "interaction-combo-action") {
    return "Combo sources use row/col blocks; this field is only the emitted action.";
  }
  return "Pick opens the shared Action picker; Plan is a read-only Text Send preview.";
}

function ensureInteractionActionInputTools() {
  document.querySelectorAll(".interaction-action-input").forEach((input) => {
    const label = input.closest("label");
    if (!label || label.querySelector(".interaction-action-input-tools")) return;
    const tools = document.createElement("div");
    tools.className = "interaction-action-input-tools";

    const pick = document.createElement("button");
    pick.type = "button";
    pick.className = "lighting-btn interaction-action-input-tool";
    pick.textContent = "Pick";
    pick.title = "Open Action picker";
    pick.addEventListener("click", () => openInteractionActionPicker(input));

    const plan = document.createElement("button");
    plan.type = "button";
    plan.className = "lighting-btn interaction-action-input-tool";
    plan.textContent = "Plan";
    plan.title = "Preview Text Send plan";
    plan.addEventListener("click", () => previewInteractionTextSendPlanForInput(input));

    tools.append(pick, plan);
    input.after(tools);
    const help = document.createElement("small");
    help.className = "interaction-action-input-help";
    help.textContent = interactionActionInputHelp(input);
    tools.after(help);
  });
}

function insertInteractionAction(action) {
  const input = focusedInteractionActionInput();
  if (input) {
    setInteractionActionInputValue(input, action);
    const status = document.getElementById("interaction-status");
    if (status) status.textContent = "Action を入力欄へ入れました";
    return;
  }
  insertInteractionText(JSON.stringify(action));
}

function interactionActionLabel(action) {
  if (typeof remapChoiceLabel === "function") return remapChoiceLabel(action);
  if (typeof keycodeLabel === "function") return keycodeLabel(action);
  return String(action || "").replace(/^KC_/, "").slice(0, 12);
}

function ensureInteractionActionPickerDialog() {
  let picker = document.getElementById("interaction-action-picker-dialog");
  if (picker) return picker;
  picker = document.createElement("div");
  picker.id = "interaction-action-picker-dialog";
  picker.className = "interaction-action-picker-dialog";
  picker.innerHTML = [
    '<div class="interaction-action-picker-backdrop"></div>',
    '<div class="interaction-action-picker-panel" role="dialog" aria-modal="true">',
    '<div class="interaction-action-picker-head">',
    '<strong>Action picker</strong>',
    '<button type="button" class="interaction-action-picker-close" aria-label="Close">×</button>',
    '</div>',
    '<input id="interaction-action-picker-search" class="interaction-action-picker-search" type="search" placeholder="keycode / label / alias を検索">',
    '<div id="interaction-action-picker-list" class="interaction-action-picker-list"></div>',
    '</div>',
  ].join("");
  picker.querySelector(".interaction-action-picker-backdrop").addEventListener("click", closeInteractionActionPicker);
  picker.querySelector(".interaction-action-picker-close").addEventListener("click", closeInteractionActionPicker);
  picker.querySelector(".interaction-action-picker-search").addEventListener("input", filterInteractionActionPicker);
  document.body.appendChild(picker);
  return picker;
}

function interactionActionSearchText(action) {
  const cached = typeof _labelsCache === "object" && _labelsCache ? (_labelsCache[action] || "") : "";
  return `${action} ${interactionActionLabel(action)} ${cached}`.toLowerCase();
}

function renderInteractionActionPickerList() {
  const list = document.getElementById("interaction-action-picker-list");
  if (!list) return;
  list.replaceChildren();
  const actions = uniqueInteractionActions(_interactionActionOptions.length ? _interactionActionOptions : INTERACTION_ACTION_SUGGESTIONS);
  for (const action of actions) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "interaction-action-picker-key";
    button.dataset.action = action;
    button.dataset.search = interactionActionSearchText(action);
    button.title = action;
    const label = document.createElement("span");
    label.className = "interaction-action-picker-label";
    label.textContent = interactionActionLabel(action);
    const code = document.createElement("code");
    code.textContent = action;
    button.append(label, code);
    button.addEventListener("click", () => chooseInteractionAction(action));
    list.appendChild(button);
  }
  filterInteractionActionPicker();
}

function filterInteractionActionPicker() {
  const input = document.getElementById("interaction-action-picker-search");
  const query = (input && input.value ? input.value : "").trim().toLowerCase();
  for (const button of document.querySelectorAll(".interaction-action-picker-key")) {
    button.hidden = Boolean(query) && !(button.dataset.search || "").includes(query);
  }
}

function openInteractionActionPicker(input, onSelect) {
  const remapPicker = window.openRemapChoicePicker || (typeof openRemapChoicePicker === "function" ? openRemapChoicePicker : null);
  if (typeof remapPicker === "function") {
    const target = input || focusedInteractionActionInput();
    if (target) _lastInteractionActionInput = target;
    remapPicker({
      currentKeycode: target?.value?.trim() || "KC_NONE",
      title: "Action選択",
      onSelect: (action) => {
        if (target) setInteractionActionInputValue(target, action);
        if (typeof onSelect === "function") onSelect(action);
        const status = document.getElementById("interaction-status");
        if (status) status.textContent = "Action を選択しました";
      },
    });
    return;
  }
  _interactionActionPickerTarget = input || focusedInteractionActionInput();
  _interactionActionPickerCallback = typeof onSelect === "function" ? onSelect : null;
  if (_interactionActionPickerTarget) _lastInteractionActionInput = _interactionActionPickerTarget;
  const picker = ensureInteractionActionPickerDialog();
  picker.classList.add("open");
  const search = document.getElementById("interaction-action-picker-search");
  if (search) search.value = "";
  renderInteractionActionPickerList();
  if (search) search.focus();
}

function closeInteractionActionPicker() {
  const picker = document.getElementById("interaction-action-picker-dialog");
  if (picker) picker.classList.remove("open");
  _interactionActionPickerCallback = null;
}

function chooseInteractionAction(action) {
  const input = _interactionActionPickerTarget || focusedInteractionActionInput();
  if (input) setInteractionActionInputValue(input, action);
  if (_interactionActionPickerCallback) _interactionActionPickerCallback(action, input);
  closeInteractionActionPicker();
  const status = document.getElementById("interaction-status");
  if (status) status.textContent = "Action を入力欄へ入れました";
}

function insertSelectedInteractionAction() {
  const select = document.getElementById("interaction-keycode-picker");
  const action = select && select.value ? select.value : _interactionActionOptions[0];
  if (action) insertInteractionAction(action);
}

function insertInteractionSnippet(kind) {
  const snippet = INTERACTION_SNIPPETS[kind];
  if (snippet) insertInteractionText(snippet);
}

function parsedInteractionEditor() {
  const editor = document.getElementById("interaction-editor");
  if (!editor) return null;
  return JSON.parse(editor.value);
}

function interactionEditorIsDirty() {
  const editor = document.getElementById("interaction-editor");
  return Boolean(editor && _interactionSavedText && editor.value !== _interactionSavedText);
}

function setInteractionSavedTextFromEditor() {
  const editor = document.getElementById("interaction-editor");
  _interactionSavedText = editor ? editor.value : "";
  updateInteractionDirtyState();
}

function setInteractionValidatedTextFromEditor() {
  const editor = document.getElementById("interaction-editor");
  _interactionValidatedText = editor ? editor.value : "";
  updateInteractionValidationState();
}

function interactionValidationIsStale() {
  const editor = document.getElementById("interaction-editor");
  return Boolean(editor && _interactionValidatedText && editor.value !== _interactionValidatedText);
}

function updateInteractionValidationState() {
  const stale = interactionValidationIsStale();
  const status = document.getElementById("interaction-status");
  if (status) {
    status.dataset.validation = stale ? "stale" : "current";
    status.classList.toggle("interaction-status-validation-stale", stale);
  }
  return stale;
}

function warnBeforeLeavingInteractionEditor(event) {
  if (!interactionEditorIsDirty()) return;
  event.preventDefault();
  event.returnValue = "";
}

function updateInteractionDirtyState() {
  const dirty = interactionEditorIsDirty();
  const status = document.getElementById("interaction-status");
  if (status) {
    status.dataset.dirty = dirty ? "1" : "0";
    status.classList.toggle("interaction-status-dirty", dirty);
  }
  return dirty;
}

function markInteractionEditorChanged() {
  _interactionInspector = null;
  _interactionConditionalInspector = null;
  updateInteractionDirtyState();
  updateInteractionValidationState();
  renderInteractionWarnings([]);
  renderInteractionValidationPreview(null);
  renderInteractionReloadResult(null);
}

function updateInteractionEditor(settings) {
  const editor = document.getElementById("interaction-editor");
  if (!editor) return;
  editor.value = JSON.stringify(settings, null, 2);
  editor.focus();
  markInteractionEditorChanged();
  renderInteractionSummary();
}

function interactionSettingsFromEditor() {
  const editor = document.getElementById("interaction-editor");
  if (!editor) return null;
  try {
    const value = JSON.parse(editor.value || "{}");
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  } catch (_err) {
    return null;
  }
}

function ensureInteractionSummary() {
  const wrap = document.querySelector(".interaction-editor-wrap");
  const editor = document.getElementById("interaction-editor");
  if (!wrap || !editor || document.getElementById("interaction-summary-panel")) return;
  const panel = document.createElement("div");
  panel.id = "interaction-summary-panel";
  panel.className = "interaction-summary-panel";
  editor.before(panel);
}

function moveInteractionItem(items, index, delta) {
  const next = index + delta;
  if (next < 0 || next >= items.length) return items;
  const copy = items.slice();
  const [item] = copy.splice(index, 1);
  copy.splice(next, 0, item);
  return copy;
}

function adjustedInteractionEditIndex(editIndex, movedIndex, delta, itemCount) {
  if (!Number.isInteger(editIndex)) return null;
  const nextIndex = movedIndex + delta;
  if (nextIndex < 0 || nextIndex >= itemCount) return editIndex;
  if (editIndex === movedIndex) return nextIndex;
  if (editIndex === nextIndex) return movedIndex;
  return editIndex;
}

function adjustedInteractionEditIndexAfterRemove(editIndex, removedIndex) {
  if (!Number.isInteger(editIndex)) return null;
  if (editIndex === removedIndex) return null;
  return editIndex > removedIndex ? editIndex - 1 : editIndex;
}

function interactionSummaryButton(label, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "interaction-summary-btn";
  button.textContent = label;
  button.addEventListener("click", onClick);
  return button;
}

function renderInteractionSummarySection(panel, title, rows, handlers) {
  const section = document.createElement("div");
  section.className = "interaction-summary-section";

  const header = document.createElement("div");
  header.className = "interaction-summary-title";
  header.textContent = `${title} (${rows.length})`;
  section.appendChild(header);

  if (!rows.length) {
    const empty = document.createElement("div");
    empty.className = "interaction-summary-empty";
    empty.textContent = "未定義";
    section.appendChild(empty);
  }

  rows.forEach((row, index) => {
    const item = document.createElement("div");
    item.className = "interaction-summary-row";

    const text = document.createElement("code");
    text.textContent = row;

    const actions = document.createElement("div");
    actions.className = "interaction-summary-actions";
    if (typeof handlers.edit === "function") {
      actions.append(interactionSummaryButton("Edit", () => handlers.edit(index)));
    }
    if (typeof handlers.copyAction === "function") {
      actions.append(interactionSummaryButton("Copy TD", () => handlers.copyAction(index)));
    }
    if (typeof handlers.move === "function") {
      actions.append(
        interactionSummaryButton("↑", () => handlers.move(index, -1)),
        interactionSummaryButton("↓", () => handlers.move(index, 1)),
      );
    }
    if (typeof handlers.remove === "function") {
      actions.append(interactionSummaryButton("削除", () => handlers.remove(index)));
    }

    item.append(text, actions);
    section.appendChild(item);
  });
  panel.appendChild(section);
}

function setInteractionStatus(text) {
  const status = document.getElementById("interaction-status");
  if (status) status.textContent = text;
}

function copyInteractionText(text) {
  if (!text) return false;
  if (typeof window.__interactionCopyTextForTest === "function") {
    window.__interactionCopyTextForTest(text);
    return true;
  }
  if (window.navigator && window.navigator.clipboard && typeof window.navigator.clipboard.writeText === "function") {
    const result = window.navigator.clipboard.writeText(text);
    if (result && typeof result.catch === "function") {
      result.catch(() => setInteractionStatus(`Copy failed: ${text}`));
    }
    return true;
  }
  return false;
}

function copyInteractionActionToClipboard(action) {
  if (copyInteractionText(action)) setInteractionStatus(`Copied ${action}`);
  else setInteractionStatus(`Action: ${action}`);
}

function setInteractionInputValue(id, value) {
  const input = document.getElementById(id);
  if (!input) return;
  input.value = value === undefined || value === null ? "" : String(value);
}

function focusInteractionBuilder(selector, focusId) {
  setInteractionEditorMode("gui");
  const builders = document.getElementById("interaction-builders-accordion");
  if (builders) builders.open = true;
  const builder = document.querySelector(selector);
  if (builder && typeof builder.scrollIntoView === "function") {
    builder.scrollIntoView({ block: "nearest" });
  }
  const input = document.getElementById(focusId);
  if (input) {
    input.focus();
    input.select?.();
  }
}

function loadInteractionComboIntoBuilder(combo, index = null) {
  const keys = combo && Array.isArray(combo.keys) ? combo.keys : [];
  for (const index of [1, 2, 3]) {
    const key = Array.isArray(keys[index - 1]) ? keys[index - 1] : [];
    setInteractionInputValue(`interaction-combo-row-${index}`, key[0]);
    setInteractionInputValue(`interaction-combo-col-${index}`, key[1]);
  }
  setInteractionInputValue("interaction-combo-action", combo && combo.action);
  _interactionEditingComboIndex = Number.isInteger(index) ? index : null;
  focusInteractionBuilder(".interaction-combo-builder", "interaction-combo-action");
  setInteractionStatus(_interactionEditingComboIndex === null ? "Combo を builder に読み戻しました" : `Combo ${_interactionEditingComboIndex + 1} を builder に読み戻しました`);
}

function loadInteractionTapDanceIntoBuilder(entry, index = null) {
  const name = Array.isArray(entry) ? entry[0] : "";
  const actions = Array.isArray(entry) && entry[1] && typeof entry[1] === "object" ? entry[1] : {};
  setInteractionInputValue("interaction-tap-dance-name", name);
  for (const count of [1, 2, 3]) {
    setInteractionInputValue(`interaction-tap-dance-action-${count}`, actions[String(count)]);
  }
  _interactionEditingTapDanceIndex = Number.isInteger(index) ? index : null;
  focusInteractionBuilder(".interaction-tap-dance-builder", "interaction-tap-dance-name");
  setInteractionStatus(_interactionEditingTapDanceIndex === null ? "Tap Dance を builder に読み戻しました" : `Tap Dance ${_interactionEditingTapDanceIndex + 1} を builder に読み戻しました`);
}

function loadInteractionKeyOverrideIntoBuilder(override, index = null) {
  const trigger = override && Array.isArray(override.trigger)
    ? override.trigger.join(", ")
    : (override ? override.trigger : "");
  setInteractionInputValue("interaction-override-trigger", trigger);
  setInteractionInputValue("interaction-override-key", override && override.key);
  setInteractionInputValue("interaction-override-replacement", override && override.replacement);
  _interactionEditingOverrideIndex = Number.isInteger(index) ? index : null;
  focusInteractionBuilder(".interaction-key-override-builder", "interaction-override-trigger");
  setInteractionStatus(_interactionEditingOverrideIndex === null ? "Key Override を builder に読み戻しました" : `Key Override ${_interactionEditingOverrideIndex + 1} を builder に読み戻しました`);
}

function interactionEnabledLabel(value) {
  return value === false ? "off" : "on";
}

function interactionListLength(value) {
  return Array.isArray(value) ? value.length : 0;
}

function interactionObjectLength(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? Object.keys(value).length : 0;
}

function interactionTextSendActionsInSettings(value, actions = []) {
  if (typeof value === "string") {
    const raw = value.trim();
    if (/^(TEXT|SEND_STRING)\([A-Za-z0-9_.-]{1,48}\)$/.test(raw) || /^U\+[0-9A-Fa-f]{4,6}$/.test(raw)) {
      actions.push(raw);
    }
    return actions;
  }
  if (Array.isArray(value)) {
    value.forEach((item) => interactionTextSendActionsInSettings(item, actions));
    return actions;
  }
  if (value && typeof value === "object") {
    Object.values(value).forEach((item) => interactionTextSendActionsInSettings(item, actions));
  }
  return actions;
}

function interactionAccordionBadge(text, alert = false) {
  const badge = document.createElement("span");
  badge.className = `interaction-accordion-badge${alert ? " interaction-accordion-badge-alert" : ""}`;
  badge.textContent = text;
  return badge;
}

function interactionValidationSummary() {
  return _interactionInspector && _interactionInspector.validation_summary
    ? _interactionInspector.validation_summary
    : null;
}

function interactionSaveHintLabel(hint) {
  if (hint === "blocked") return "blocked";
  if (hint === "review") return "review";
  if (hint === "ok") return "ok";
  return "unknown";
}

function renderInteractionAccordionSummary(id, label, badges) {
  const summary = document.querySelector(`#${id} > summary`);
  if (!summary) return;
  const title = document.createElement("span");
  title.className = "interaction-accordion-title";
  title.textContent = label;
  const badgeWrap = document.createElement("span");
  badgeWrap.className = "interaction-accordion-badges";
  for (const badge of badges) badgeWrap.appendChild(badge);
  summary.replaceChildren(title, badgeWrap);
}

function updateInteractionAccordionHeaders(settings = interactionSettingsFromEditor()) {
  const parseError = settings === null;
  const normalized = !parseError && settings && typeof settings === "object" && !Array.isArray(settings)
    ? settings
    : {};
  const combos = interactionListLength(normalized.combos);
  const tapDances = interactionObjectLength(normalized.tap_dances);
  const overrides = interactionListLength(normalized.key_overrides);
  const morse = interactionObjectLength(normalized.morse_behaviors);
  const caps = normalized.caps_word && typeof normalized.caps_word === "object" ? normalized.caps_word : {};
  const repeat = normalized.repeat_key && typeof normalized.repeat_key === "object" ? normalized.repeat_key : {};
  const conditional = Array.isArray(normalized.conditional_layers) ? normalized.conditional_layers : [];
  const textSendActions = interactionTextSendActionsInSettings(normalized);
  const inspectorSummary = _interactionInspector && _interactionInspector.summary ? _interactionInspector.summary : {};
  const validationSummary = interactionValidationSummary();
  const saveHint = interactionSaveHintLabel(validationSummary && validationSummary.save_hint);
  const warnings = Number(inspectorSummary.warnings || 0);
  const dirty = updateInteractionDirtyState();
  const validationStale = updateInteractionValidationState();
  const activeOneshot = _interactionActiveLayers && Array.isArray(_interactionActiveLayers.oneshot)
    ? _interactionActiveLayers.oneshot
    : [];
  const activeLocked = _interactionActiveLayers && Array.isArray(_interactionActiveLayers.locked)
    ? _interactionActiveLayers.locked
    : [];

  renderInteractionAccordionSummary("interaction-raw-accordion", "Raw editor", [
    interactionAccordionBadge(parseError ? "JSON error" : "JSON ok", parseError),
    interactionAccordionBadge(dirty ? "Unsaved" : "Saved", dirty),
    interactionAccordionBadge(validationStale ? "Needs check" : "Checked", validationStale),
    interactionAccordionBadge(`OSL ${activeOneshot.length}`, activeOneshot.length > 0),
    interactionAccordionBadge(`Lock ${activeLocked.length}`, activeLocked.length > 0),
    interactionAccordionBadge(`Caps ${interactionEnabledLabel(caps.enabled)}`),
    interactionAccordionBadge(`Repeat ${interactionListLength(repeat.alternate_pairs)}`),
    interactionAccordionBadge(`Cond ${conditional.length}`),
    interactionAccordionBadge(`Text ${textSendActions.length}`, textSendActions.length > 0),
  ]);
  renderInteractionAccordionSummary("interaction-morse-accordion", "Morse editor", [
    interactionAccordionBadge(`Morse ${morse}`),
  ]);
  renderInteractionAccordionSummary("interaction-builders-accordion", "Combo / Tap Dance / Key Override / Timing", [
    interactionAccordionBadge(`Combo ${combos}`),
    interactionAccordionBadge(`TD ${tapDances}`),
    interactionAccordionBadge(`Override ${overrides}`),
    interactionAccordionBadge(`Save ${saveHint}`, saveHint !== "ok"),
    interactionAccordionBadge(`Warn ${warnings}`, warnings > 0),
  ]);
}

function appendInteractionSummaryMetric(panel, label, value) {
  const item = document.createElement("div");
  item.className = "interaction-summary-metric";
  const labelEl = document.createElement("span");
  labelEl.textContent = label;
  const valueEl = document.createElement("code");
  valueEl.textContent = value;
  item.append(labelEl, valueEl);
  panel.appendChild(item);
}

function renderInteractionRuntimeSummary(panel, settings) {
  const section = document.createElement("div");
  section.className = "interaction-summary-section interaction-runtime-summary";

  const header = document.createElement("div");
  header.className = "interaction-summary-title";
  header.textContent = "Runtime helpers";
  section.appendChild(header);

  const metrics = document.createElement("div");
  metrics.className = "interaction-summary-metrics";
  const caps = settings.caps_word && typeof settings.caps_word === "object" ? settings.caps_word : {};
  const repeat = settings.repeat_key && typeof settings.repeat_key === "object" ? settings.repeat_key : {};
  const runtimeStatus = _interactionRuntimeStatus && _interactionRuntimeStatus.result === "ok" ? _interactionRuntimeStatus : null;
  const capsRuntime = runtimeStatus && runtimeStatus.caps_word ? runtimeStatus.caps_word : null;
  const repeatRuntime = runtimeStatus && runtimeStatus.repeat_key ? runtimeStatus.repeat_key : null;
  const keyLockRuntime = runtimeStatus && runtimeStatus.key_lock ? runtimeStatus.key_lock : null;
  const keyLockKeys = keyLockRuntime && Array.isArray(keyLockRuntime.keys) ? keyLockRuntime.keys : [];
  const conditional = Array.isArray(settings.conditional_layers) ? settings.conditional_layers : [];
  const conditionalRuntimeFresh = !interactionEditorIsDirty();
  const activeConditional = conditionalRuntimeFresh && _interactionActiveLayers && Array.isArray(_interactionActiveLayers.conditional)
    ? _interactionActiveLayers.conditional
    : [];
  const activeOneshot = _interactionActiveLayers && Array.isArray(_interactionActiveLayers.oneshot)
    ? _interactionActiveLayers.oneshot
    : [];
  const activeLocked = _interactionActiveLayers && Array.isArray(_interactionActiveLayers.locked)
    ? _interactionActiveLayers.locked
    : [];
  const conditionalInspector = _interactionConditionalInspector && _interactionConditionalInspector.result === "ok"
    ? _interactionConditionalInspector
    : null;
  const inspectorSummary = _interactionInspector && _interactionInspector.summary ? _interactionInspector.summary : {};
  const textSendGate = _interactionTextSendSafety && _interactionTextSendSafety.execution_gate
    ? _interactionTextSendSafety.execution_gate
    : {};
  const textSendHost = _interactionTextSendSafety && _interactionTextSendSafety.host_profile
    ? _interactionTextSendSafety.host_profile
    : {};
  const textSendDryRun = _interactionTextSendSafety && _interactionTextSendSafety.tap_dry_run
    ? _interactionTextSendSafety.tap_dry_run
    : {};
  const textSendDryRunModes = Array.isArray(textSendDryRun.supported_modes)
    ? textSendDryRun.supported_modes.join(",")
    : "-";
  const validationSummary = interactionValidationSummary();
  const saveHint = interactionSaveHintLabel(validationSummary && validationSummary.save_hint);
  appendInteractionSummaryMetric(metrics, "Caps Word", capsRuntime
    ? `${interactionEnabledLabel(capsRuntime.enabled)} / ${capsRuntime.active ? "active" : "inactive"}`
    : interactionEnabledLabel(caps.enabled));
  appendInteractionSummaryMetric(metrics, "Repeat Key", repeatRuntime
    ? `${interactionEnabledLabel(repeatRuntime.enabled)} / repeat ${repeatRuntime.history_available ? "ready" : "-"} / alt ${repeatRuntime.alternate_available ? "ready" : "-"} / pairs ${Number(repeatRuntime.alternate_pair_count || 0)}`
    : `${interactionEnabledLabel(repeat.enabled)} / pairs ${interactionListLength(repeat.alternate_pairs)}`);
  appendInteractionSummaryMetric(metrics, "Key Lock", keyLockKeys.length
    ? keyLockKeys.map((entry) => `${entry.action || "?"}:${entry.kind || "lock"}`).join(",")
    : "-");
  appendInteractionSummaryMetric(metrics, "One Shot Layer", activeOneshot.length ? activeOneshot.map((layer) => `OSL(${layer})`).join(",") : "-");
  appendInteractionSummaryMetric(metrics, "Locked Layer", activeLocked.length ? activeLocked.map((layer) => `LL(${layer})`).join(",") : "-");
  appendInteractionSummaryMetric(metrics, "Conditional", `rules ${conditional.length} / active ${conditionalRuntimeFresh ? (activeConditional.join(",") || "-") : "pending-save"}`);
  appendInteractionSummaryMetric(metrics, "Conditional Inspector", conditionalInspector ? `${conditionalInspector.rule_count} / ${conditionalInspector.active_source}` : "unavailable");
  appendInteractionSummaryMetric(metrics, "Inspector", `warnings ${Number(inspectorSummary.warnings || 0)}`);
  appendInteractionSummaryMetric(metrics, "Text Send", textSendGate.real_send_allowed ? "real-send ready" : "preview/no-op");
  appendInteractionSummaryMetric(metrics, "Host Profile", textSendHost.explicit ? String(textSendHost.profile || "configured") : "required");
  appendInteractionSummaryMetric(metrics, "Tap Dry Run", textSendDryRun.sends_hid_reports === false ? textSendDryRunModes || "-" : "unavailable");
  appendInteractionSummaryMetric(metrics, "Save check", saveHint);
  appendInteractionSummaryMetric(metrics, "Combos", String(interactionListLength(settings.combos)));
  appendInteractionSummaryMetric(metrics, "Tap Dance", String(interactionObjectLength(settings.tap_dances)));
  appendInteractionSummaryMetric(metrics, "Overrides", String(interactionListLength(settings.key_overrides)));
  section.appendChild(metrics);
  renderInteractionLayerLockUnlock(section, activeLocked);
  if (validationSummary) {
    const hint = document.createElement("div");
    hint.className = `interaction-validation-hint interaction-validation-hint-${saveHint}`;
    const title = document.createElement("strong");
    title.textContent = `Save ${saveHint}`;
    const detail = document.createElement("span");
    const counts = validationSummary.severity_counts || {};
    detail.textContent = `errors ${Number(counts.error || 0)} / warnings ${Number(counts.warning || 0)} / info ${Number(counts.info || 0)}`;
    hint.append(title, detail);
    section.appendChild(hint);
  }
  renderInteractionTextSendWarning(section);
  renderInteractionTextSendEditorWarning(section, settings);
  renderInteractionTextSendPlan(section);
  renderInteractionConditionalInspectorRows(section);
  const rows = interactionInspectorRows();
  if (rows.length) {
    const list = document.createElement("div");
    list.className = "interaction-inspector-rows";
    for (const row of rows.slice(0, 6)) {
      const item = document.createElement("div");
      item.className = `interaction-inspector-row interaction-inspector-${row.status || "ok"}`;
      const source = document.createElement("code");
      source.textContent = row.source || row.id || "-";
      const text = document.createElement("span");
      text.textContent = (row.warnings || []).map((warning) => warning.message || warning).join("; ") || "ok";
      item.append(source, text);
      list.appendChild(item);
    }
    section.appendChild(list);
  }
  panel.appendChild(section);
}

function renderInteractionLayerLockUnlock(section, activeLocked) {
  if (!Array.isArray(activeLocked) || !activeLocked.length) return;
  const box = document.createElement("div");
  box.className = "interaction-validation-hint interaction-validation-hint-review interaction-layer-lock-unlock";
  const title = document.createElement("strong");
  title.textContent = "Layer Lock active";
  const detail = document.createElement("span");
  detail.textContent = activeLocked.map((layer) => `LL(${layer})`).join(", ");
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary";
  button.textContent = "Unlock";
  button.addEventListener("click", () => clearInteractionLayerLock());
  box.append(title, detail, button);
  section.appendChild(box);
}

async function clearInteractionLayerLock() {
  const status = document.getElementById("interaction-status");
  try {
    const request = (typeof csrfFetch === "function" ? csrfFetch : fetch);
    const resp = await request("/api/keymap/layer-lock/clear", { method: "POST" });
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") throw new Error(data.msg || `HTTP ${resp.status}`);
    _interactionActiveLayers = data.active || null;
    renderInteractionSummary();
    await refreshInteractionRuntimeSummary();
    if (status) status.textContent = data.changed ? "Layer Lock を解除しました" : "Layer Lock は既に解除済みです";
  } catch (err) {
    if (status) status.textContent = `ERROR: ${err.message}`;
  }
}

function renderInteractionConditionalInspectorRows(section) {
  const inspector = _interactionConditionalInspector;
  if (!inspector || inspector.result !== "ok" || !Array.isArray(inspector.rules) || !inspector.rules.length) return;
  const list = document.createElement("div");
  list.className = "interaction-inspector-rows interaction-conditional-inspector-rows";
  for (const rule of inspector.rules.slice(0, 6)) {
    const item = document.createElement("div");
    item.className = `interaction-inspector-row${rule.active ? " interaction-inspector-warning" : ""}`;
    const source = document.createElement("code");
    source.textContent = `${rule.name || "rule"} -> ${rule.then}`;
    const text = document.createElement("span");
    const missing = Array.isArray(rule.source_missing) ? rule.source_missing.join(",") : "";
    const active = Array.isArray(rule.source_active) ? rule.source_active.join(",") : "";
    text.textContent = rule.active
      ? `active from ${active || "-"}`
      : `missing ${missing || "-"} / active ${active || "-"}`;
    item.append(source, text);
    list.appendChild(item);
  }
  section.appendChild(list);
}

function renderInteractionTextSendWarning(section) {
  const warning = _interactionTextSendSafety && _interactionTextSendSafety.http_warning
    ? _interactionTextSendSafety.http_warning
    : null;
  if (!warning || !warning.required) return;
  const box = document.createElement("div");
  box.className = "interaction-validation-hint interaction-validation-hint-review interaction-text-send-warning";
  const title = document.createElement("strong");
  title.textContent = "Text Send preview/no-op";
  const detail = document.createElement("span");
  const reasons = Array.isArray(warning.blocking_reasons) ? warning.blocking_reasons.join(", ") : "";
  detail.textContent = reasons || warning.message || "warning";
  box.append(title, detail);
  section.appendChild(box);
}

function renderInteractionTextSendEditorWarning(section, settings) {
  const allActions = interactionTextSendActionsInSettings(settings);
  const actions = allActions.slice(0, 6);
  if (!actions.length) return;
  const box = document.createElement("div");
  box.className = "interaction-validation-hint interaction-validation-hint-review interaction-text-send-editor-warning";
  const title = document.createElement("strong");
  title.textContent = "Text Send actions present";
  const detail = document.createElement("span");
  detail.textContent = `${actions.join(", ")}${allActions.length > actions.length ? ", ..." : ""}: use Plan preview for warning / blocked reasons`;
  box.append(title, detail);
  section.appendChild(box);
}

function renderInteractionTextSendPlan(section) {
  const payload = _interactionTextSendPlan;
  if (!payload || payload.result !== "ok" || !payload.plan) return;
  const plan = payload.plan;
  const box = document.createElement("div");
  box.className = `interaction-validation-hint interaction-validation-hint-${plan.real_send_allowed ? "ok" : "review"} interaction-text-send-plan`;
  const title = document.createElement("strong");
  title.textContent = "Text Send plan";
  const detail = document.createElement("span");
  const reasons = Array.isArray(plan.blocking_reasons) ? plan.blocking_reasons.join(", ") : "";
  const action = plan.action && plan.action.normalized ? plan.action.normalized : payload.action || "-";
  const dryRun = plan.tap_dry_run && typeof plan.tap_dry_run === "object" ? plan.tap_dry_run : {};
  const dryRunText = dryRun.available === true ? ` / taps ${Number(dryRun.sequence_count || 0)}` : "";
  const entry = plan.entry && typeof plan.entry === "object" ? plan.entry : null;
  const entryErrors = entry && Array.isArray(entry.errors) ? entry.errors : [];
  const entryWarnings = entry && Array.isArray(entry.warnings) ? entry.warnings : [];
  const entryText = entryErrors.length
    ? ` / entry errors: ${entryErrors.join(", ")}`
    : entryWarnings.length
    ? ` / entry warnings: ${entryWarnings.join(", ")}`
    : "";
  detail.textContent = `${action}: ${plan.real_send_allowed ? "ready" : reasons || "preview/no-op"}${dryRunText}${entryText}`;
  box.append(title, detail);
  section.appendChild(box);
}

function interactionBuilderWarnings(sectionName) {
  const sections = _interactionInspector && _interactionInspector.sections ? _interactionInspector.sections : {};
  const items = Array.isArray(sections[sectionName]) ? sections[sectionName] : [];
  return items.flatMap((item) => (
    Array.isArray(item.warnings)
      ? item.warnings.map((warning) => ({
        source: item.source || warning.source || "",
        severity: warning.severity || item.status || "warning",
        message: warning.message || String(warning),
      }))
      : []
  ));
}

function ensureInteractionBuilderWarningBox(builder, sectionName) {
  let box = builder.querySelector(`.interaction-builder-inline-warning[data-section="${sectionName}"]`);
  if (box) return box;
  box = document.createElement("div");
  box.className = "interaction-builder-inline-warning";
  box.dataset.section = sectionName;
  builder.appendChild(box);
  return box;
}

function renderInteractionBuilderInlineWarnings() {
  for (const [sectionName, selector] of Object.entries(INTERACTION_BUILDER_WARNING_TARGETS)) {
    const builder = document.querySelector(selector);
    if (!builder) continue;
    const box = ensureInteractionBuilderWarningBox(builder, sectionName);
    const warnings = interactionBuilderWarnings(sectionName);
    builder.classList.toggle("interaction-builder-has-warning", warnings.length > 0);
    box.hidden = warnings.length === 0;
    box.replaceChildren();
    if (!warnings.length) continue;

    const title = document.createElement("strong");
    title.textContent = `Inspector warning ${warnings.length}`;
    const list = document.createElement("ul");
    for (const warning of warnings.slice(0, 4)) {
      const item = document.createElement("li");
      item.className = `interaction-builder-inline-warning-${warning.severity}`;
      const source = warning.source ? `${warning.source}: ` : "";
      item.textContent = `${source}${warning.message}`;
      list.appendChild(item);
    }
    box.append(title, list);
  }
}

function ensureInteractionBuilderSubtitle(builder, builderKey) {
  let subtitle = builder.querySelector(`.interaction-builder-subtitle[data-builder="${builderKey}"]`);
  if (subtitle) return subtitle;
  const title = builder.querySelector(".interaction-action-title");
  subtitle = document.createElement("div");
  subtitle.className = "interaction-builder-subtitle";
  subtitle.dataset.builder = builderKey;
  if (title) {
    title.after(subtitle);
  } else {
    builder.prepend(subtitle);
  }
  return subtitle;
}

function renderInteractionBuilderUx() {
  const payload = _interactionBuilderUx && _interactionBuilderUx.builders ? _interactionBuilderUx : null;
  const polish = payload && payload.polish_status ? payload.polish_status : null;
  for (const [builderKey, selector] of Object.entries(INTERACTION_BUILDER_UX_TARGETS)) {
    const builder = document.querySelector(selector);
    if (!builder) continue;
    const spec = payload ? payload.builders[builderKey] : null;
    const subtitle = ensureInteractionBuilderSubtitle(builder, builderKey);
    const text = spec && spec.subtitle ? String(spec.subtitle) : "";
    const polishScope = polish && polish[builderKey]?.editor_scope ? `scope: ${polish[builderKey].editor_scope}` : "";
    const hover = spec
      ? [spec.source_policy, spec.save_scope, polishScope, polish?.warning_display?.dedupe_rule].filter(Boolean).join(" / ")
      : "";
    subtitle.textContent = text;
    subtitle.title = hover || text;
    subtitle.hidden = !text;
  }
}

function interactionInspectorRows() {
  const sections = _interactionInspector && _interactionInspector.sections ? _interactionInspector.sections : {};
  return ["combos", "tap_dances", "key_overrides", "mod_morphs"].flatMap((key) => (
    Array.isArray(sections[key]) ? sections[key] : []
  )).filter((item) => item && item.status !== "ok");
}

function writeInteractionSettingsFromSummary(settings) {
  const editor = document.getElementById("interaction-editor");
  if (!editor) return;
  editor.value = JSON.stringify(settings, null, 2);
  markInteractionEditorChanged();
  renderInteractionSummary();
}

function numberInputValue(id, fallback) {
  const input = document.getElementById(id);
  if (!input) return fallback;
  const value = Number(input.value);
  return Number.isFinite(value) && value >= 0.001 ? value : fallback;
}

function setNumberInputValue(id, value, fallback) {
  const input = document.getElementById(id);
  if (!input) return;
  const next = Number.isFinite(Number(value)) ? Number(value) : fallback;
  input.value = next.toFixed(3);
}

function renderInteractionTimingControls(settings = interactionSettingsFromEditor()) {
  if (!settings || Array.isArray(settings) || typeof settings !== "object") return;
  setNumberInputValue("interaction-tapping-term", settings.tapping_term, 0.2);
  setNumberInputValue("interaction-combo-term", settings.combo_term, 0.05);
  setNumberInputValue("interaction-tap-dance-term", settings.tap_dance_term, 0.2);
  const hold = document.getElementById("interaction-hold-on-other-key-press");
  if (hold) hold.checked = settings.hold_on_other_key_press !== false;
}

function applyInteractionTiming() {
  const status = document.getElementById("interaction-status");
  let settings;
  try {
    settings = parsedInteractionEditor();
  } catch (err) {
    if (status) status.textContent = `JSON ERROR: ${err.message}`;
    return;
  }
  if (!settings || Array.isArray(settings) || typeof settings !== "object") {
    if (status) status.textContent = "JSON root は object にしてください";
    return;
  }

  settings.tapping_term = numberInputValue("interaction-tapping-term", 0.2);
  settings.combo_term = numberInputValue("interaction-combo-term", 0.05);
  settings.tap_dance_term = numberInputValue("interaction-tap-dance-term", 0.2);
  const hold = document.getElementById("interaction-hold-on-other-key-press");
  settings.hold_on_other_key_press = hold ? Boolean(hold.checked) : true;
  updateInteractionEditor(settings);
  if (status) status.textContent = "Advanced Timing を反映しました";
}

function parseConditionalLayerList(value) {
  const parts = value.split(/[,+\s]+/).map((part) => part.trim()).filter(Boolean);
  if (parts.length < 2) {
    throw new Error("Conditional source layer は 2 個以上入力してください");
  }
  const layers = parts.map((part) => Number(part));
  if (layers.some((layer) => !Number.isInteger(layer) || layer < 0 || layer > 31)) {
    throw new Error("Conditional source layer は 0-31 の整数にしてください");
  }
  if (new Set(layers).size !== layers.length) {
    throw new Error("Conditional source layer が重複しています");
  }
  return layers;
}

function conditionalLayerNumberInput(id, label) {
  const raw = actionInputValue(id);
  const value = Number(raw);
  if (!raw || !Number.isInteger(value) || value < 0 || value > 31) {
    throw new Error(`${label} は 0-31 の整数にしてください`);
  }
  return value;
}

function collectInteractionConditionalLayerRule() {
  const name = actionInputValue("interaction-conditional-name");
  if (!name) {
    throw new Error("Conditional name を入力してください");
  }
  const ifAll = parseConditionalLayerList(actionInputValue("interaction-conditional-if-all"));
  const then = conditionalLayerNumberInput("interaction-conditional-then", "Conditional target layer");
  if (ifAll.includes(then)) {
    throw new Error("Conditional target layer は source layer と分けてください");
  }
  return { name, if_all: ifAll, then };
}

function addInteractionConditionalLayer() {
  const status = document.getElementById("interaction-status");
  let settings;
  try {
    settings = parsedInteractionEditor();
  } catch (err) {
    if (status) status.textContent = `JSON ERROR: ${err.message}`;
    return;
  }

  if (!settings || Array.isArray(settings) || typeof settings !== "object") {
    if (status) status.textContent = "JSON root は object にしてください";
    return;
  }

  let nextRule;
  try {
    nextRule = collectInteractionConditionalLayerRule();
  } catch (err) {
    if (status) status.textContent = err.message;
    return;
  }

  if (settings.conditional_layers === undefined) {
    settings.conditional_layers = [];
  }
  if (!Array.isArray(settings.conditional_layers)) {
    if (status) status.textContent = "conditional_layers は配列にしてください";
    return;
  }

  settings.conditional_layers.push(nextRule);
  updateInteractionEditor(settings);
  if (status) status.textContent = "Conditional Layer rule を追加しました";
}

function removeInteractionConditionalLayer(settings, index) {
  const conditional = Array.isArray(settings.conditional_layers) ? settings.conditional_layers : [];
  settings.conditional_layers = conditional.filter((_value, idx) => idx !== index);
  writeInteractionSettingsFromSummary(settings);
  const status = document.getElementById("interaction-status");
  if (status) status.textContent = "Conditional Layer rule を削除しました";
}

function renderInteractionConditionalLayerEditor(panel) {
  const section = document.createElement("div");
  section.className = "interaction-summary-section interaction-conditional-editor";

  const title = document.createElement("div");
  title.className = "interaction-summary-title";
  title.textContent = "Conditional Layers editor";

  const grid = document.createElement("div");
  grid.className = "interaction-builder-grid interaction-conditional-grid";

  const nameLabel = document.createElement("label");
  const nameText = document.createElement("span");
  nameText.textContent = "Name";
  const nameInput = document.createElement("input");
  nameInput.id = "interaction-conditional-name";
  nameInput.type = "text";
  nameInput.value = "lower_raise_adjust";
  nameLabel.append(nameText, nameInput);

  const sourceLabel = document.createElement("label");
  const sourceText = document.createElement("span");
  sourceText.textContent = "Source layers";
  const sourceInput = document.createElement("input");
  sourceInput.id = "interaction-conditional-if-all";
  sourceInput.type = "text";
  sourceInput.value = "1, 2";
  sourceLabel.append(sourceText, sourceInput);

  const targetLabel = document.createElement("label");
  const targetText = document.createElement("span");
  targetText.textContent = "Target layer";
  const targetInput = document.createElement("input");
  targetInput.id = "interaction-conditional-then";
  targetInput.type = "number";
  targetInput.min = "0";
  targetInput.max = "31";
  targetInput.value = "3";
  targetLabel.append(targetText, targetInput);

  grid.append(nameLabel, sourceLabel, targetLabel);
  section.append(
    title,
    grid,
    interactionSummaryButton("Add Conditional", addInteractionConditionalLayer),
  );
  panel.appendChild(section);
}

function interactionConditionalLayerLabel(rule) {
  if (!rule || typeof rule !== "object") return String(rule);
  const name = rule.name || "conditional";
  const sources = Array.isArray(rule.if_all) ? rule.if_all.join("+") : "";
  return `${name}: ${sources} -> ${rule.then}`;
}

function renderInteractionSummary() {
  ensureInteractionSummary();
  const panel = document.getElementById("interaction-summary-panel");
  if (!panel) return;
  panel.replaceChildren();
  const settings = interactionSettingsFromEditor();
  if (settings === null) {
    updateInteractionAccordionHeaders(null);
    panel.textContent = "Interaction summary: JSON parse error";
    return;
  }
  updateInteractionAccordionHeaders(settings);
  renderInteractionTimingControls(settings);
  renderInteractionRuntimeSummary(panel, settings);
  renderInteractionBuilderInlineWarnings();

  const combos = Array.isArray(settings.combos) ? settings.combos : [];
  const overrides = Array.isArray(settings.key_overrides) ? settings.key_overrides : [];
  const conditional = Array.isArray(settings.conditional_layers) ? settings.conditional_layers : [];
  const tapDanceEntries = settings.tap_dances && typeof settings.tap_dances === "object" && !Array.isArray(settings.tap_dances)
    ? Object.entries(settings.tap_dances)
    : [];

  renderInteractionConditionalLayerEditor(panel);
  renderInteractionSummarySection(panel, "Conditional Layers", conditional.map(interactionConditionalLayerLabel), {
    remove: (index) => removeInteractionConditionalLayer(settings, index),
  });
  renderInteractionSummarySection(panel, "Combo", combos.map((combo) => `${JSON.stringify(combo.keys)} -> ${combo.action || ""}`), {
    edit: (index) => {
      loadInteractionComboIntoBuilder(combos[index], index);
    },
    move: (index, delta) => {
      _interactionEditingComboIndex = adjustedInteractionEditIndex(_interactionEditingComboIndex, index, delta, combos.length);
      settings.combos = moveInteractionItem(combos, index, delta);
      writeInteractionSettingsFromSummary(settings);
    },
    remove: (index) => {
      _interactionEditingComboIndex = adjustedInteractionEditIndexAfterRemove(_interactionEditingComboIndex, index);
      settings.combos = combos.filter((_value, idx) => idx !== index);
      writeInteractionSettingsFromSummary(settings);
    },
  });
  renderInteractionSummarySection(panel, "Tap Dance", tapDanceEntries.map(([name, actions]) => `${name}: ${JSON.stringify(actions)}`), {
    edit: (index) => {
      loadInteractionTapDanceIntoBuilder(tapDanceEntries[index], index);
    },
    copyAction: (index) => {
      const name = tapDanceEntries[index] ? tapDanceEntries[index][0] : "";
      if (name) copyInteractionActionToClipboard(`TD(${name})`);
    },
    move: (index, delta) => {
      _interactionEditingTapDanceIndex = adjustedInteractionEditIndex(_interactionEditingTapDanceIndex, index, delta, tapDanceEntries.length);
      settings.tap_dances = Object.fromEntries(moveInteractionItem(tapDanceEntries, index, delta));
      writeInteractionSettingsFromSummary(settings);
    },
    remove: (index) => {
      _interactionEditingTapDanceIndex = adjustedInteractionEditIndexAfterRemove(_interactionEditingTapDanceIndex, index);
      settings.tap_dances = Object.fromEntries(tapDanceEntries.filter((_value, idx) => idx !== index));
      writeInteractionSettingsFromSummary(settings);
    },
  });
  renderInteractionSummarySection(panel, "Key Override", overrides.map((override) => `${JSON.stringify(override.trigger)} + ${override.key || ""} -> ${override.replacement || ""}`), {
    edit: (index) => {
      loadInteractionKeyOverrideIntoBuilder(overrides[index], index);
    },
    move: (index, delta) => {
      _interactionEditingOverrideIndex = adjustedInteractionEditIndex(_interactionEditingOverrideIndex, index, delta, overrides.length);
      settings.key_overrides = moveInteractionItem(overrides, index, delta);
      writeInteractionSettingsFromSummary(settings);
    },
    remove: (index) => {
      _interactionEditingOverrideIndex = adjustedInteractionEditIndexAfterRemove(_interactionEditingOverrideIndex, index);
      settings.key_overrides = overrides.filter((_value, idx) => idx !== index);
      writeInteractionSettingsFromSummary(settings);
    },
  });
}

async function refreshInteractionRuntimeSummary() {
  try {
    const resp = await fetch("/api/keymap/active");
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") throw new Error(data.msg || `HTTP ${resp.status}`);
    _interactionActiveLayers = data.active || null;
  } catch (_err) {
    _interactionActiveLayers = null;
  }
  renderInteractionSummary();
}

async function refreshInteractionRuntimeStatus() {
  try {
    const resp = await fetch("/api/interaction/runtime-status");
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") throw new Error(data.msg || `HTTP ${resp.status}`);
    _interactionRuntimeStatus = data;
  } catch (_err) {
    _interactionRuntimeStatus = null;
  }
  renderInteractionSummary();
}

async function refreshInteractionBuilderUx() {
  try {
    const resp = await fetch("/api/interaction/builder-ux");
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") throw new Error(data.msg || `HTTP ${resp.status}`);
    _interactionBuilderUx = data;
  } catch (_err) {
    _interactionBuilderUx = null;
  }
  renderInteractionBuilderUx();
}

async function refreshInteractionTextSendSafety() {
  try {
    const resp = await fetch("/api/interaction/text-send-safety");
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") throw new Error(data.msg || `HTTP ${resp.status}`);
    _interactionTextSendSafety = data;
  } catch (_err) {
    _interactionTextSendSafety = null;
  }
  renderInteractionSummary();
}

async function refreshInteractionConditionalInspector() {
  try {
    const resp = await fetch("/api/interaction/conditional-layers/inspector");
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") throw new Error(data.msg || `HTTP ${resp.status}`);
    _interactionConditionalInspector = data;
  } catch (_err) {
    _interactionConditionalInspector = null;
  }
  renderInteractionSummary();
}

async function previewInteractionTextSendPlanForInput(input) {
  const status = document.getElementById("interaction-status");
  const action = input && input.value ? input.value.trim() : "";
  if (!action) {
    if (status) status.textContent = "Text Send plan の action が空です";
    return;
  }
  try {
    const request = (typeof csrfFetch === "function" ? csrfFetch : fetch);
    const resp = await request("/api/interaction/text-send-safety/plan", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ action }),
    });
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") throw new Error(data.reason || data.msg || `HTTP ${resp.status}`);
    _interactionTextSendPlan = { ...data, action };
    renderInteractionSummary();
    if (status) status.textContent = "Text Send plan を preview しました";
  } catch (err) {
    _interactionTextSendPlan = null;
    renderInteractionSummary();
    if (status) status.textContent = `ERROR: ${err.message}`;
  }
}

function flattenInteractionInspectorWarnings(inspector) {
  const warnings = [];
  if (!inspector || typeof inspector !== "object") return warnings;
  for (const warning of Array.isArray(inspector.warnings) ? inspector.warnings : []) {
    const message = typeof warning === "string" ? warning : warning.message;
    const source = typeof warning === "object" ? warning.source : "";
    if (message) warnings.push(source ? `${source}: ${message}` : message);
  }
  return warnings;
}

async function refreshInteractionInspector() {
  try {
    const resp = await fetch("/api/interaction/inspector");
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") throw new Error(data.msg || `HTTP ${resp.status}`);
    _interactionInspector = data;
    renderInteractionWarnings(flattenInteractionInspectorWarnings(data));
  } catch (_err) {
    _interactionInspector = null;
  }
  renderInteractionSummary();
}

function actionInputValue(id) {
  const input = document.getElementById(id);
  return input ? input.value.trim() : "";
}

function parseOverrideTrigger(value) {
  const parts = value.split(",").map((part) => part.trim()).filter(Boolean);
  if (parts.length > 1) return parts;
  return value.trim();
}

function readOptionalMatrixKey(rowId, colId, label) {
  const rowValue = actionInputValue(rowId);
  const colValue = actionInputValue(colId);
  if (!rowValue && !colValue) return null;
  if (!rowValue || !colValue) {
    throw new Error(`${label} の row/col が不足しています`);
  }

  const row = Number(rowValue);
  const col = Number(colValue);
  if (!Number.isInteger(row) || !Number.isInteger(col) || row < 0 || col < 0) {
    throw new Error(`${label} は 0 以上の整数にしてください`);
  }
  return [row, col];
}

function collectInteractionComboKeys() {
  const keys = [
    readOptionalMatrixKey("interaction-combo-row-1", "interaction-combo-col-1", "Key 1"),
    readOptionalMatrixKey("interaction-combo-row-2", "interaction-combo-col-2", "Key 2"),
    readOptionalMatrixKey("interaction-combo-row-3", "interaction-combo-col-3", "Key 3"),
  ].filter(Boolean);

  if (keys.length < 2) {
    throw new Error("Combo は 2 個以上の key が必要です");
  }

  const seen = new Set(keys.map((key) => key.join(",")));
  if (seen.size !== keys.length) {
    throw new Error("Combo key が重複しています");
  }
  return keys;
}

function interactionComboInputPair(index) {
  return {
    row: document.getElementById(`interaction-combo-row-${index}`),
    col: document.getElementById(`interaction-combo-col-${index}`),
  };
}

function clearInteractionComboPickMode() {
  _interactionComboPickTarget = null;
  document.getElementById("keyboard-container")?.classList.remove("interaction-combo-pick-mode");
  document.querySelectorAll(".interaction-combo-pick-btn").forEach((button) => {
    button.classList.remove("active");
    button.removeAttribute("aria-pressed");
  });
}

function pickInteractionComboKey(index) {
  const pair = interactionComboInputPair(index);
  const status = document.getElementById("interaction-status");
  if (!pair.row || !pair.col) return;
  _interactionComboPickTarget = { index, rowInput: pair.row, colInput: pair.col };
  document.getElementById("keyboard-container")?.classList.add("interaction-combo-pick-mode");
  document.querySelectorAll(".interaction-combo-pick-btn").forEach((button, idx) => {
    const active = idx + 1 === index;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-pressed", "true");
    else button.removeAttribute("aria-pressed");
  });
  if (typeof setActiveTab === "function") setActiveTab("keyboard");
  if (status) status.textContent = `Combo Key ${index}: キーボード上の source key を選択してください`;
}

function handleInteractionComboKeyPick(row, col) {
  if (!_interactionComboPickTarget) return false;
  const target = _interactionComboPickTarget;
  target.rowInput.value = String(row);
  target.colInput.value = String(col);
  clearInteractionComboPickMode();
  if (typeof setActiveTab === "function") setActiveTab("interaction", { fetch: false });
  setInteractionEditorMode("gui");
  const builders = document.getElementById("interaction-builders-accordion");
  if (builders) builders.open = true;
  const status = document.getElementById("interaction-status");
  if (status) status.textContent = `Combo Key ${target.index}: ${row},${col} を選択しました`;
  return true;
}

function appendInteractionCombo() {
  const status = document.getElementById("interaction-status");
  let settings;
  try {
    settings = parsedInteractionEditor();
  } catch (err) {
    if (status) status.textContent = `JSON ERROR: ${err.message}`;
    return;
  }

  if (!settings || Array.isArray(settings) || typeof settings !== "object") {
    if (status) status.textContent = "JSON root は object にしてください";
    return;
  }

  let keys;
  try {
    keys = collectInteractionComboKeys();
  } catch (err) {
    if (status) status.textContent = err.message;
    return;
  }

  const action = actionInputValue("interaction-combo-action");
  if (!action) {
    if (status) status.textContent = "Combo action を入力してください";
    return;
  }

  if (settings.combos === undefined) {
    settings.combos = [];
  }
  if (!Array.isArray(settings.combos)) {
    if (status) status.textContent = "combos は配列にしてください";
    return;
  }

  const replacing = Number.isInteger(_interactionEditingComboIndex)
    && _interactionEditingComboIndex >= 0
    && _interactionEditingComboIndex < settings.combos.length;
  if (replacing) {
    settings.combos[_interactionEditingComboIndex] = { keys, action };
  } else {
    settings.combos.push({ keys, action });
  }
  _interactionEditingComboIndex = null;
  updateInteractionEditor(settings);
  if (status) status.textContent = replacing ? "Combo を更新しました" : "Combo を追加しました";
}

function collectInteractionTapDanceActions() {
  const actions = {};
  for (const count of [1, 2, 3]) {
    const action = actionInputValue(`interaction-tap-dance-action-${count}`);
    if (action) actions[String(count)] = action;
  }
  if (Object.keys(actions).length === 0) {
    throw new Error("Tap Dance action を 1 つ以上入力してください");
  }
  return actions;
}

function appendInteractionTapDance() {
  const status = document.getElementById("interaction-status");
  let settings;
  try {
    settings = parsedInteractionEditor();
  } catch (err) {
    if (status) status.textContent = `JSON ERROR: ${err.message}`;
    return;
  }

  if (!settings || Array.isArray(settings) || typeof settings !== "object") {
    if (status) status.textContent = "JSON root は object にしてください";
    return;
  }

  const name = actionInputValue("interaction-tap-dance-name");
  if (!name) {
    if (status) status.textContent = "Tap Dance name を入力してください";
    return;
  }

  let actions;
  try {
    actions = collectInteractionTapDanceActions();
  } catch (err) {
    if (status) status.textContent = err.message;
    return;
  }

  if (settings.tap_dances === undefined) {
    settings.tap_dances = {};
  }
  if (!settings.tap_dances || Array.isArray(settings.tap_dances) || typeof settings.tap_dances !== "object") {
    if (status) status.textContent = "tap_dances は object にしてください";
    return;
  }

  const tapDanceEntries = Object.entries(settings.tap_dances);
  const replacing = Number.isInteger(_interactionEditingTapDanceIndex)
    && _interactionEditingTapDanceIndex >= 0
    && _interactionEditingTapDanceIndex < tapDanceEntries.length;
  if (replacing) {
    const duplicateIndex = tapDanceEntries.findIndex(([existingName], index) => existingName === name && index !== _interactionEditingTapDanceIndex);
    if (duplicateIndex !== -1) {
      if (status) status.textContent = `Tap Dance ${name} は既に存在します`;
      return;
    }
    tapDanceEntries[_interactionEditingTapDanceIndex] = [name, actions];
    settings.tap_dances = Object.fromEntries(tapDanceEntries);
  } else {
    const updating = Object.prototype.hasOwnProperty.call(settings.tap_dances, name);
    settings.tap_dances[name] = actions;
    _interactionEditingTapDanceIndex = null;
    updateInteractionEditor(settings);
    if (status) status.textContent = updating ? "Tap Dance を更新しました" : "Tap Dance を追加しました";
    return;
  }
  _interactionEditingTapDanceIndex = null;
  updateInteractionEditor(settings);
  if (status) status.textContent = replacing ? "Tap Dance を更新しました" : "Tap Dance を追加しました";
}

function appendInteractionKeyOverride() {
  const status = document.getElementById("interaction-status");
  let settings;
  try {
    settings = parsedInteractionEditor();
  } catch (err) {
    if (status) status.textContent = `JSON ERROR: ${err.message}`;
    return;
  }

  if (!settings || Array.isArray(settings) || typeof settings !== "object") {
    if (status) status.textContent = "JSON root は object にしてください";
    return;
  }

  const triggerText = actionInputValue("interaction-override-trigger");
  const key = actionInputValue("interaction-override-key");
  const replacement = actionInputValue("interaction-override-replacement");
  if (!triggerText || !key || !replacement) {
    if (status) status.textContent = "Override の入力が不足しています";
    return;
  }

  if (settings.key_overrides === undefined) {
    settings.key_overrides = [];
  }
  if (!Array.isArray(settings.key_overrides)) {
    if (status) status.textContent = "key_overrides は配列にしてください";
    return;
  }

  const nextOverride = {
    trigger: parseOverrideTrigger(triggerText),
    key,
    replacement,
  };
  const replacing = Number.isInteger(_interactionEditingOverrideIndex)
    && _interactionEditingOverrideIndex >= 0
    && _interactionEditingOverrideIndex < settings.key_overrides.length;
  if (replacing) {
    settings.key_overrides[_interactionEditingOverrideIndex] = nextOverride;
  } else {
    settings.key_overrides.push(nextOverride);
  }
  _interactionEditingOverrideIndex = null;
  updateInteractionEditor(settings);
  if (status) status.textContent = replacing ? "Key Override を更新しました" : "Key Override を追加しました";
}

function renderInteractionWarnings(warnings = []) {
  const target = document.getElementById("interaction-warnings");
  const count = document.getElementById("interaction-warning-count");
  const items = Array.isArray(warnings) ? warnings.filter((warning) => typeof warning === "string") : [];

  if (count) {
    count.textContent = String(items.length);
    count.classList.toggle("interaction-warning-count-ok", items.length === 0);
    count.classList.toggle("interaction-warning-count-alert", items.length > 0);
  }

  if (!target) return;
  target.replaceChildren();
  target.classList.toggle("interaction-warnings-ok", items.length === 0);
  target.classList.toggle("interaction-warnings-alert", items.length > 0);

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "interaction-warning-empty";
    empty.textContent = "warnings なし";
    target.appendChild(empty);
    return;
  }

  for (const warning of items) {
    const row = document.createElement("div");
    row.className = "interaction-warning-row";

    const marker = document.createElement("span");
    marker.className = "interaction-warning-marker";
    marker.textContent = "!";

    const text = document.createElement("span");
    text.className = "interaction-warning-text";
    text.textContent = warning;

    row.append(marker, text);
    target.appendChild(row);
  }
}

function renderInteractionReloadResult(reload) {
  const target = document.getElementById("interaction-reload-result");
  if (!target) return;
  target.textContent = reload ? JSON.stringify(reload, null, 2) : "–";
}

function renderInteractionValidationPreview(settings) {
  const target = document.getElementById("interaction-validation-preview");
  if (!target) return;
  target.textContent = settings ? JSON.stringify(settings, null, 2) : "–";
}

async function fetchInteractionSettings() {
  const status = document.getElementById("interaction-status");
  try {
    if (status) status.textContent = "読み込み中…";
    const resp = await fetch("/api/interaction");
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") {
      throw new Error(data.msg || `HTTP ${resp.status}`);
    }

    const editor = document.getElementById("interaction-editor");
    if (editor) {
      editor.value = JSON.stringify(data.settings || {}, null, 2);
    }
    setInteractionSavedTextFromEditor();
    setInteractionValidatedTextFromEditor();
    renderInteractionSummary();

    renderInteractionWarnings(data.warnings || []);
    renderInteractionValidationPreview(null);
    renderInteractionReloadResult(null);

    const metadata = document.getElementById("interaction-metadata");
    if (metadata) {
      metadata.textContent = JSON.stringify(data.metadata || {}, null, 2);
    }
    const layoutActions = await fetchInteractionLayoutActions();
    renderInteractionActionTools(data.metadata || {}, layoutActions);
    await refreshInteractionRuntimeSummary();
    await refreshInteractionRuntimeStatus();
    await refreshInteractionConditionalInspector();
    await refreshInteractionTextSendSafety();
    await refreshInteractionBuilderUx();
    await refreshInteractionInspector();

    if (status) status.textContent = "OK";
  } catch (err) {
    console.error(err);
    if (status) status.textContent = `ERROR: ${err.message}`;
  }
}

async function validateInteractionSettings() {
  const status = document.getElementById("interaction-status");
  let parsed;
  try {
    parsed = parsedInteractionEditor();
  } catch (err) {
    if (status) status.textContent = `JSON ERROR: ${err.message}`;
    return;
  }

  try {
    if (status) status.textContent = "検証中…";
    const resp = await csrfFetch("/api/interaction/validate", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ settings: parsed }),
    });

    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") {
      throw new Error(data.msg || `HTTP ${resp.status}`);
    }

    renderInteractionWarnings(data.warnings || []);
    renderInteractionValidationPreview(data.settings || {});
    renderInteractionReloadResult(null);
    setInteractionValidatedTextFromEditor();
    renderInteractionSummary();
    if (status) status.textContent = "検証完了";
  } catch (err) {
    console.error(err);
    if (status) status.textContent = `ERROR: ${err.message}`;
  }
}

function formatInteractionSettings() {
  const editor = document.getElementById("interaction-editor");
  const status = document.getElementById("interaction-status");
  if (!editor) return;
  try {
    const parsed = JSON.parse(editor.value);
    editor.value = JSON.stringify(parsed, null, 2);
    markInteractionEditorChanged();
    renderInteractionSummary();
    if (status) status.textContent = "整形しました";
  } catch (err) {
    if (status) status.textContent = `JSON ERROR: ${err.message}`;
  }
}

async function saveInteractionSettings(reload) {
  const editor = document.getElementById("interaction-editor");
  const status = document.getElementById("interaction-status");
  if (!editor) return;

  if (typeof window.flushMorseBehaviorBuilderToEditor === "function") {
    const ok = window.flushMorseBehaviorBuilderToEditor();
    if (!ok) {
      if (status) status.textContent = "Morse editor の内容を確認してください";
      return;
    }
  }

  let parsed;
  try {
    parsed = JSON.parse(editor.value);
  } catch (err) {
    if (status) status.textContent = `JSON ERROR: ${err.message}`;
    return;
  }

  try {
    if (status) status.textContent = reload ? "保存+reload中…" : "保存中…";
    const resp = await csrfFetch("/api/interaction", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        settings: parsed,
        reload,
      }),
    });

    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") {
      throw new Error(data.msg || `HTTP ${resp.status}`);
    }

    editor.value = JSON.stringify(data.settings || {}, null, 2);
    setInteractionSavedTextFromEditor();
    setInteractionValidatedTextFromEditor();
    renderInteractionSummary();
    renderInteractionWarnings(data.warnings || []);
    renderInteractionValidationPreview(data.settings || {});
    renderInteractionReloadResult(data.reload || null);
    await refreshInteractionInspector();

    if (status) status.textContent = reload ? "保存+reload完了" : "保存完了";
  } catch (err) {
    console.error(err);
    if (status) status.textContent = `ERROR: ${err.message}`;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  ensureInteractionGuiLayout();
  setInteractionEditorMode(interactionSavedEditorMode(), { persist: false });
  ensureInteractionSummary();
  bindInteractionAccordionState();
  applyInteractionAccordionState();
  const editor = document.getElementById("interaction-editor");
  if (editor) editor.addEventListener("input", renderInteractionSummary);
  document.querySelectorAll(".interaction-action-input").forEach((input) => {
    input.addEventListener("focus", () => {
      _lastInteractionActionInput = input;
    });
  });
  ensureInteractionActionInputTools();
  renderInteractionSummary();
  renderInteractionBuilderUx();
});

window.addEventListener("hashchange", applyInteractionAccordionState);
window.addEventListener("beforeunload", warnBeforeLeavingInteractionEditor);

window.renderInteractionSummary = renderInteractionSummary;
window.renderInteractionBuilderUx = renderInteractionBuilderUx;
window.pickInteractionComboKey = pickInteractionComboKey;
window.handleInteractionComboKeyPick = handleInteractionComboKeyPick;
window.updateInteractionAccordionHeaders = updateInteractionAccordionHeaders;
window.bindInteractionAccordionState = bindInteractionAccordionState;
window.applyInteractionAccordionState = applyInteractionAccordionState;
window.insertSelectedInteractionAction = insertSelectedInteractionAction;
window.applyInteractionTiming = applyInteractionTiming;
window.addInteractionConditionalLayer = addInteractionConditionalLayer;
window.openInteractionActionPicker = openInteractionActionPicker;
window.previewInteractionTextSendPlanForInput = previewInteractionTextSendPlanForInput;
window.closeInteractionActionPicker = closeInteractionActionPicker;
window.setInteractionEditorMode = setInteractionEditorMode;
