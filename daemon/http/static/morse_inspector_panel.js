"use strict";

const MORSE_SNIPPET = `"morse_behaviors": {
  "main": {
    "dot_threshold": 0.18,
    "sequence_timeout": 0.70,
    "max_depth": 4,
    "fallback_action": "KC_ESC",
    "force_commit": [".-"],
    "map": {
      ".": "KC_E",
      "-": "KC_T",
      ".-": "KC_A",
      ".-.": "KC_R"
    }
  }
}`;

const MORSE_DEFAULT_MAP_TEXT = `.=KC_NO
-=KC_NO`;
const MORSE_ADD_OPTION = "__add_morse__";
let _morseFeedbackTimer = null;
let _lastMorseFeedbackEvents = [];
let _morseTreeExpanded = new Set();
let _morseAutoLoadedName = "";
const MORSE_EDITOR_MAX_DEPTH = 8;

function morseInspectorSettingsFromEditor() {
  const editor = document.getElementById("interaction-editor");
  if (!editor) return null;
  try {
    const parsed = JSON.parse(editor.value || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch (_err) {
    return null;
  }
}

function ensureMorseInspectorPanel() {
  const aside = document.querySelector(".interaction-help");
  if (!aside) return null;
  let panel = document.getElementById("interaction-morse-inspector");
  if (panel) return panel;

  const title = document.createElement("h3");
  title.textContent = "Morse Tree";
  title.id = "interaction-morse-inspector-title";
  const note = document.createElement("p");
  note.className = "interaction-morse-note";
  note.textContent = "MORSE(name) の分岐を read-only 表示します。leaf は自動確定、force_commit は枝があっても強制確定です。fallback_action は不発時に発行されます。";
  panel = document.createElement("div");
  panel.id = "interaction-morse-inspector";
  panel.className = "interaction-morse-inspector";
  panel.textContent = "–";
  aside.append(title, note, panel);
  return panel;
}

function ensureMorseFeedbackPanel() {
  const help = document.querySelector(".interaction-help");
  if (!help) return null;
  let panel = document.getElementById("interaction-morse-feedback");
  if (panel) return panel;

  const title = document.createElement("h3");
  title.textContent = "Morse Feedback";
  title.id = "interaction-morse-feedback-title";
  panel = document.createElement("div");
  panel.id = "interaction-morse-feedback";
  panel.className = "interaction-morse-feedback";
  panel.textContent = "待機中";

  const validation = document.getElementById("interaction-validation-preview");
  if (validation && validation.parentElement === help) {
    validation.before(title, panel);
  } else {
    help.append(title, panel);
  }
  return panel;
}

function ensureMorseSnippetButton() {
  const target = document.querySelector(".interaction-snippet-buttons");
  if (!target || document.getElementById("interaction-morse-snippet-btn")) return;
  const button = document.createElement("button");
  button.id = "interaction-morse-snippet-btn";
  button.className = "lighting-btn";
  button.type = "button";
  button.textContent = "Morse";
  button.addEventListener("click", insertMorseBehaviorSnippet);
  target.appendChild(button);
}

function ensureMorseEditorPanel() {
  const wrap = document.querySelector(".interaction-editor-wrap");
  const gui = document.getElementById("interaction-gui-editors");
  if (!wrap || document.getElementById("interaction-morse-builder")) return;
  const accordion = document.createElement("details");
  accordion.id = "interaction-morse-accordion";
  accordion.className = "interaction-accordion interaction-morse-accordion";
  accordion.open = true;
  const summary = document.createElement("summary");
  summary.textContent = "Morse editor";
  const panel = document.createElement("div");
  panel.id = "interaction-morse-builder";
  panel.className = "interaction-builder interaction-morse-builder interaction-accordion-body";
  panel.innerHTML = `
    <div class="interaction-action-title">Morse behavior builder</div>
    <div class="interaction-builder-grid interaction-morse-grid">
      <label><span>Defined</span><select id="interaction-morse-existing"></select></label>
      <div class="interaction-morse-builder-actions interaction-morse-top-actions">
        <button class="lighting-btn" type="button" onclick="saveMorseBehaviorBuilder(true)">Morseを保存してreload</button>
        <button class="lighting-btn" type="button" onclick="deleteMorseBehaviorBuilder()">Delete Morse</button>
        <button class="lighting-btn" type="button" onclick="renderMorseTreeEditorFromBuilder()">Refresh Tree</button>
        <button class="lighting-btn interaction-icon-btn" type="button" onclick="copyMorseActionForBuilder()" title="Copy MORSE(name)" aria-label="Copy MORSE(name)">⧉</button>
      </div>
      <label><span>Dot threshold sec</span><input id="interaction-morse-dot" type="number" min="0.001" step="0.001" value="0.180"></label>
      <label><span>Timeout sec</span><input id="interaction-morse-timeout" type="number" min="0.001" step="0.001" value="0.700"></label>
      <label class="interaction-builder-action"><span>fallback_action</span><span class="interaction-morse-action-field"><input id="interaction-morse-fallback" class="interaction-action-input" type="text" value="" placeholder="optional, e.g. KC_ESC"><button class="interaction-summary-btn" type="button" onclick="pickMorseFallbackAction()">選択</button></span></label>
    </div>
    <div class="interaction-morse-hidden-state" aria-hidden="true">
      <input id="interaction-morse-name" type="hidden" value="main">
      <input id="interaction-morse-force" type="hidden" value="">
      <textarea id="interaction-morse-map" spellcheck="false" tabindex="-1">${MORSE_DEFAULT_MAP_TEXT}</textarea>
    </div>
    <div id="interaction-morse-tree-warning" class="interaction-morse-tree-warning"></div>
    <div id="interaction-morse-tree-editor" class="interaction-morse-tree-editor"></div>
  `;
  accordion.append(summary, panel);
  const builders = document.getElementById("interaction-builders-accordion");
  const target = gui || wrap;
  if (builders && builders.parentElement === target) {
    builders.before(accordion);
  } else {
    target.appendChild(accordion);
  }
  if (typeof window.updateInteractionAccordionHeaders === "function") {
    window.updateInteractionAccordionHeaders();
  }
  if (typeof window.bindInteractionAccordionState === "function") {
    window.bindInteractionAccordionState();
  }
  if (typeof window.applyInteractionAccordionState === "function") {
    window.applyInteractionAccordionState();
  }
  const map = document.getElementById("interaction-morse-map");
  const force = document.getElementById("interaction-morse-force");
  const existing = document.getElementById("interaction-morse-existing");
  if (map) map.addEventListener("input", renderMorseTreeEditorFromBuilder);
  if (force) force.addEventListener("input", renderMorseTreeEditorFromBuilder);
  if (existing) {
    existing.addEventListener("change", () => {
      if (existing.value === MORSE_ADD_OPTION) {
        promptAddMorseBehavior();
        return;
      }
      if (existing.value) loadMorseBehaviorByName(existing.value, { setStatus: true });
    });
  }
  syncMorseBehaviorList();
  autoLoadCurrentMorseBehavior();
  renderMorseTreeEditorFromBuilder();
}

function insertMorseBehaviorSnippet() {
  if (typeof insertInteractionText === "function") {
    insertInteractionText(MORSE_SNIPPET);
  }
}

function validMorseSequence(sequence) {
  return typeof sequence === "string" && /^[.-]+$/.test(sequence);
}

function validMorseName(name) {
  return typeof name === "string" && /^[A-Za-z0-9_.-]{1,64}$/.test(name);
}

function morseForceCommitSet(definition) {
  const raw = definition.force_commit ?? definition.terminal ?? definition.terminal_sequences ?? [];
  const values = typeof raw === "string" ? [raw] : Array.isArray(raw) ? raw : [];
  return new Set(values.map((value) => String(value).trim()).filter(validMorseSequence));
}

function morseFallbackAction(definition) {
  const fallback = definition && typeof definition.fallback_action === "string" ? definition.fallback_action.trim() : "";
  return fallback && !["KC_NO", "KC_NONE", "NO", "NONE"].includes(fallback.toUpperCase()) ? fallback : "";
}

function morseHasDeeper(sequence, actions) {
  return Object.keys(actions).some((candidate) => candidate !== sequence && candidate.startsWith(sequence));
}

function morseChildSequences(sequence, actions, includeCancel) {
  const children = new Set();
  for (const candidate of Object.keys(actions)) {
    if (candidate.startsWith(sequence) && candidate.length > sequence.length) {
      children.add(candidate.slice(0, sequence.length + 1));
    }
  }
  if (includeCancel) {
    children.add(`${sequence}.`);
    children.add(`${sequence}-`);
  }
  return Array.from(children).sort((a, b) => {
    if (a.endsWith(".") !== b.endsWith(".")) return a.endsWith(".") ? -1 : 1;
    return a.localeCompare(b);
  });
}

function buildMorseNode(sequence, actions, forceCommit, maxDepth) {
  const action = actions[sequence] || null;
  const hasDeeper = morseHasDeeper(sequence, actions);
  const forced = forceCommit.has(sequence) && Boolean(action);
  let state = "cancel";
  if (!sequence) state = "root";
  else if (forced) state = "force_commit";
  else if (action && hasDeeper) state = "prefix";
  else if (action) state = "leaf";
  else if (hasDeeper) state = "unassigned_prefix";

  const node = {
    sequence,
    stroke: sequence ? sequence[sequence.length - 1] : "",
    action,
    state,
    force_commit: forced,
    children: [],
  };
  if (sequence.length >= maxDepth) return node;
  const childSequences = morseChildSequences(sequence, actions, !sequence || hasDeeper || Boolean(action));
  node.children = childSequences.map((child) => buildMorseNode(child, actions, forceCommit, maxDepth));
  return node;
}

function normalizeMorseDefinition(raw) {
  const map = raw && raw.map && typeof raw.map === "object" && !Array.isArray(raw.map) ? raw.map : raw;
  const actions = {};
  if (map && typeof map === "object" && !Array.isArray(map)) {
    for (const [sequence, action] of Object.entries(map)) {
      if (["dot_threshold", "sequence_timeout", "max_depth", "force_commit", "terminal", "terminal_sequences", "fallback_action"].includes(sequence)) continue;
      if (validMorseSequence(sequence)) actions[sequence] = String(action || "");
    }
  }
  const maxDepthRaw = Number(raw && raw.max_depth);
  const inferredDepth = Object.keys(actions).reduce((max, sequence) => Math.max(max, sequence.length), 1);
  const maxDepth = Number.isInteger(maxDepthRaw) && maxDepthRaw > 0 ? Math.min(maxDepthRaw, 8) : inferredDepth;
  return {
    dot_threshold: raw && raw.dot_threshold !== undefined ? raw.dot_threshold : 0.18,
    sequence_timeout: raw && raw.sequence_timeout !== undefined ? raw.sequence_timeout : 0.70,
    max_depth: maxDepth,
    actions,
    force_commit: morseForceCommitSet(raw || {}),
    fallback_action: morseFallbackAction(raw || {}),
  };
}

function morseMapTextToObject(text) {
  const result = {};
  for (const line of String(text || "").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq <= 0) throw new Error(`Map line must be sequence=action: ${trimmed}`);
    const sequence = trimmed.slice(0, eq).trim();
    const action = trimmed.slice(eq + 1).trim();
    if (!validMorseSequence(sequence)) throw new Error(`Invalid Morse sequence: ${sequence}`);
    if (!action) throw new Error(`Action is empty for ${sequence}`);
    result[sequence] = action;
  }
  if (!Object.keys(result).length) throw new Error("Morse map を 1 行以上入力してください");
  return result;
}

function morseMapObjectToText(map) {
  return Object.entries(map || {}).map(([sequence, action]) => `${sequence}=${action}`).join("\n");
}

function morseCsvToList(text) {
  return String(text || "").split(",").map((item) => item.trim()).filter(Boolean);
}

function setMorseMapText(map) {
  const textarea = document.getElementById("interaction-morse-map");
  if (textarea) textarea.value = morseMapObjectToText(map);
}

function setMorseForceList(force) {
  const input = document.getElementById("interaction-morse-force");
  if (input) input.value = Array.from(force).filter(validMorseSequence).sort(morseSequenceSort).join(", ");
}

function morseBehaviorNames(settings = morseInspectorSettingsFromEditor()) {
  const behaviors = settings && settings.morse_behaviors;
  if (!behaviors || typeof behaviors !== "object" || Array.isArray(behaviors)) return [];
  return Object.keys(behaviors).filter(validMorseName).sort((a, b) => a.localeCompare(b));
}

function morseBehaviorExists(name) {
  if (!validMorseName(name)) return false;
  return morseBehaviorNames().includes(name);
}

function syncMorseBehaviorList(selectedName) {
  const select = document.getElementById("interaction-morse-existing");
  if (!select) return;
  const names = morseBehaviorNames();
  const hidden = document.getElementById("interaction-morse-name");
  const currentName = selectedName || hidden?.value.trim() || names[0] || "";
  const effectiveName = names.includes(currentName) ? currentName : (names[0] || "");
  select.replaceChildren();
  const add = document.createElement("option");
  add.value = MORSE_ADD_OPTION;
  add.textContent = "Morseを追加";
  select.appendChild(add);
  for (const name of names) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    if (name === effectiveName) option.selected = true;
    select.appendChild(option);
  }
  select.value = effectiveName || MORSE_ADD_OPTION;
  if (hidden) hidden.value = effectiveName;
}

function selectedMorseBehaviorName() {
  const selectName = document.getElementById("interaction-morse-existing")?.value.trim() || "";
  const hiddenName = document.getElementById("interaction-morse-name")?.value.trim() || "";
  return selectName && selectName !== MORSE_ADD_OPTION ? selectName : hiddenName;
}

function morseSequenceSort(a, b) {
  if (a.length !== b.length) return a.length - b.length;
  return a.replaceAll(".", "0").replaceAll("-", "1").localeCompare(b.replaceAll(".", "0").replaceAll("-", "1"));
}

function inferredMorseMaxDepth(actions) {
  const inferred = Object.keys(actions || {}).reduce((max, sequence) => (
    validMorseSequence(sequence) ? Math.max(max, sequence.length) : max
  ), 1);
  return Math.max(1, Math.min(MORSE_EDITOR_MAX_DEPTH, inferred));
}

function morseTreeSequences(actions, maxDepth) {
  const sequences = new Set([""]);
  for (const sequence of Object.keys(actions || {})) {
    if (!validMorseSequence(sequence)) continue;
    for (let i = 1; i <= sequence.length; i += 1) sequences.add(sequence.slice(0, i));
  }
  return Array.from(sequences)
    .filter((sequence) => sequence.length <= maxDepth)
    .sort(morseSequenceSort);
}

function readMorseBuilderMapAllowEmpty() {
  try {
    return morseMapTextToObject(document.getElementById("interaction-morse-map")?.value || "");
  } catch (_err) {
    const result = {};
    for (const line of String(document.getElementById("interaction-morse-map")?.value || "").split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      const eq = trimmed.indexOf("=");
      if (eq <= 0) continue;
      const sequence = trimmed.slice(0, eq).trim();
      const action = trimmed.slice(eq + 1).trim();
      if (validMorseSequence(sequence) && action) result[sequence] = action;
    }
    return result;
  }
}

function morseTreeWarnings(actions, force, fallback) {
  const warnings = [];
  for (const sequence of force) {
    if (!validMorseSequence(sequence)) continue;
    if (!actions[sequence]) warnings.push(`force_commit ${sequence} has no action`);
    const hidden = Object.keys(actions).filter((candidate) => candidate !== sequence && candidate.startsWith(sequence));
    if (hidden.length) warnings.push(`force_commit ${sequence} hides deeper sequence: ${hidden.sort(morseSequenceSort).join(", ")}`);
  }
  if (fallback && !String(fallback).trim()) warnings.push("fallback_action is empty");
  return warnings;
}

function renderMorseTreeWarnings(actions, force) {
  const target = document.getElementById("interaction-morse-tree-warning");
  if (!target) return;
  const fallback = document.getElementById("interaction-morse-fallback")?.value || "";
  const warnings = morseTreeWarnings(actions, force, fallback);
  target.replaceChildren();
  target.classList.toggle("interaction-morse-tree-warning-ok", warnings.length === 0);
  target.classList.toggle("interaction-morse-tree-warning-alert", warnings.length > 0);
  if (!warnings.length) {
    target.textContent = "Morse tree warnings なし";
    return;
  }
  for (const warning of warnings) {
    const row = document.createElement("div");
    row.textContent = warning;
    target.appendChild(row);
  }
}

function updateMorseTreeAction(sequence, action) {
  const actions = readMorseBuilderMapAllowEmpty();
  const trimmed = String(action || "").trim();
  if (trimmed) actions[sequence] = trimmed;
  else delete actions[sequence];
  setMorseMapText(actions);
  renderMorseTreeEditorFromBuilder();
}

function morseElementHasClass(element, className) {
  return String(element?.className || "").split(/\s+/).includes(className);
}

function syncMorseTreeInputsToMap() {
  const panel = document.getElementById("interaction-morse-tree-editor");
  if (!panel) return;
  const actions = readMorseBuilderMapAllowEmpty();
  for (const row of Array.from(panel.children || [])) {
    if (!morseElementHasClass(row, "interaction-morse-tree-row")) continue;
    if (morseElementHasClass(row, "interaction-morse-tree-head")) continue;
    const sequence = row.children?.[0]?.children?.[1]?.textContent || "";
    const input = row.children?.[1]?.children?.[0] || null;
    if (validMorseSequence(sequence) && input) actions[sequence] = String(input.value || "").trim() || "KC_NO";
  }
  setMorseMapText(actions);
}

function updateMorseTreeForce(sequence, checked) {
  const force = new Set(morseCsvToList(document.getElementById("interaction-morse-force")?.value || ""));
  if (checked) force.add(sequence);
  else {
    force.delete(sequence);
    _morseTreeExpanded.delete(sequence);
  }
  if (checked) {
    for (const candidate of Array.from(_morseTreeExpanded)) {
      if (candidate === sequence || candidate.startsWith(sequence)) _morseTreeExpanded.delete(candidate);
    }
  }
  setMorseForceList(force);
  renderMorseTreeEditorFromBuilder();
}

function addMorseTreeSequence(sequence) {
  if (!validMorseSequence(sequence)) return;
  if (sequence.length > MORSE_EDITOR_MAX_DEPTH) return;
  const actions = readMorseBuilderMapAllowEmpty();
  if (!actions[sequence]) actions[sequence] = "KC_NO";
  setMorseMapText(actions);
  renderMorseTreeEditorFromBuilder();
}

function ensureMorseTreeChildren(sequence) {
  if (sequence.length >= MORSE_EDITOR_MAX_DEPTH) return false;
  const actions = readMorseBuilderMapAllowEmpty();
  let changed = false;
  for (const child of [`${sequence}.`, `${sequence}-`]) {
    if (!actions[child]) {
      actions[child] = "KC_NO";
      changed = true;
    }
  }
  if (changed) setMorseMapText(actions);
  return changed;
}

function toggleMorseTreeSequence(sequence) {
  if (!validMorseSequence(sequence)) return;
  if (_morseTreeExpanded.has(sequence)) {
    _morseTreeExpanded.delete(sequence);
  } else {
    expandMorseTreeSequence(sequence);
  }
  renderMorseTreeEditorFromBuilder();
}

function expandMorseTreeSequence(sequence) {
  if (!validMorseSequence(sequence)) return;
  ensureMorseTreeChildren(sequence);
  _morseTreeExpanded.add(sequence);
}

function removeMorseTreeSequence(sequence) {
  const actions = readMorseBuilderMapAllowEmpty();
  for (const candidate of Object.keys(actions)) {
    if (candidate === sequence || candidate.startsWith(sequence)) delete actions[candidate];
  }
  const force = new Set(morseCsvToList(document.getElementById("interaction-morse-force")?.value || ""));
  for (const candidate of Array.from(force)) {
    if (candidate === sequence || candidate.startsWith(sequence)) force.delete(candidate);
  }
  for (const candidate of Array.from(_morseTreeExpanded)) {
    if (candidate === sequence || candidate.startsWith(sequence)) _morseTreeExpanded.delete(candidate);
  }
  setMorseMapText(actions);
  setMorseForceList(force);
  renderMorseTreeEditorFromBuilder();
}

function morseVisibleTreeSequences(actions, force, maxDepth) {
  const visible = [];
  const visit = (sequence) => {
    if (sequence && sequence.length > 1 && !actions[sequence]) return;
    if (sequence) visible.push(sequence);
    if (sequence.length >= maxDepth) return;
    if (sequence && force.has(sequence)) return;
    if (sequence && !_morseTreeExpanded.has(sequence)) return;
    for (const child of [`${sequence}.`, `${sequence}-`]) visit(child);
  };
  visit("");
  return visible;
}

function expandMorseTreeForActions(actions, force = new Set()) {
  _morseTreeExpanded = new Set();
  for (const sequence of Object.keys(actions || {})) {
    if (!validMorseSequence(sequence)) continue;
    for (let i = 1; i < sequence.length; i += 1) {
      const prefix = sequence.slice(0, i);
      if (force.has(prefix)) break;
      _morseTreeExpanded.add(prefix);
    }
  }
}

function renderMorseTreeEditorFromBuilder() {
  const panel = document.getElementById("interaction-morse-tree-editor");
  if (!panel) return;
  const actions = readMorseBuilderMapAllowEmpty();
  const force = new Set(morseCsvToList(document.getElementById("interaction-morse-force")?.value || ""));
  const maxDepth = MORSE_EDITOR_MAX_DEPTH;
  panel.replaceChildren();

  const header = document.createElement("div");
  header.className = "interaction-morse-tree-row interaction-morse-tree-head";
  header.innerHTML = "<span>Sequence</span><span>Action</span><span>Force</span><span>Branch</span>";
  panel.appendChild(header);

  for (const sequence of morseVisibleTreeSequences(actions, force, maxDepth)) {
    const row = document.createElement("div");
    row.className = "interaction-morse-tree-row";
    row.style.marginLeft = `${Math.max(0, sequence.length - 1) * 16}px`;

    const sequenceCell = document.createElement("div");
    sequenceCell.className = "interaction-morse-sequence-cell";
    const isForced = force.has(sequence);
    const canBranch = sequence.length < maxDepth && !isForced;
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "interaction-morse-tree-toggle";
    toggle.disabled = !canBranch;
    toggle.textContent = canBranch ? (_morseTreeExpanded.has(sequence) ? "v" : ">") : "";
    toggle.title = canBranch ? "子 node を開閉" : "";
    toggle.addEventListener("click", () => toggleMorseTreeSequence(sequence));
    const code = document.createElement("code");
    code.textContent = sequence;
    sequenceCell.append(toggle, code);

    const input = document.createElement("input");
    input.className = "interaction-action-input interaction-morse-tree-action";
    input.value = actions[sequence] || "";
    input.placeholder = "optional action";
    input.addEventListener("input", () => syncMorseTreeInputsToMap());
    input.addEventListener("change", () => updateMorseTreeAction(sequence, input.value));
    input.addEventListener("focus", () => {
      if (typeof _lastInteractionActionInput !== "undefined") _lastInteractionActionInput = input;
    });
    const actionField = document.createElement("div");
    actionField.className = "interaction-morse-action-field";
    const pick = document.createElement("button");
    pick.type = "button";
    pick.className = "interaction-summary-btn";
    pick.textContent = "選択";
    pick.addEventListener("click", () => pickMorseTreeAction(sequence, input));
    actionField.append(input, pick);

    const forceWrap = document.createElement("label");
    forceWrap.className = "interaction-morse-force-check";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = force.has(sequence);
    checkbox.addEventListener("change", () => updateMorseTreeForce(sequence, checkbox.checked));
    forceWrap.append(checkbox);

    const branch = document.createElement("div");
    branch.className = "interaction-morse-tree-actions";
    if (canBranch) {
      const expand = document.createElement("button");
      expand.type = "button";
      expand.className = "interaction-summary-btn";
      expand.textContent = _morseTreeExpanded.has(sequence) ? "閉じる" : "開く";
      expand.addEventListener("click", () => toggleMorseTreeSequence(sequence));
      branch.appendChild(expand);
    }
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "interaction-summary-btn";
    remove.textContent = "削除";
    remove.addEventListener("click", () => removeMorseTreeSequence(sequence));
    branch.appendChild(remove);

    row.append(sequenceCell, actionField, forceWrap, branch);
    panel.appendChild(row);
  }

  renderMorseTreeWarnings(actions, force);
}

function setMorseBuilderStatus(message) {
  const status = document.getElementById("interaction-status");
  if (status) status.textContent = message;
}

function loadMorseBehaviorByName(name, options = {}) {
  const settings = morseInspectorSettingsFromEditor();
  if (!settings || !settings.morse_behaviors || !settings.morse_behaviors[name]) {
    if (options.setStatus) setMorseBuilderStatus(`Morse ${name} は未定義です`);
    return;
  }
  const raw = settings.morse_behaviors[name];
  const def = normalizeMorseDefinition(raw || {});
  document.getElementById("interaction-morse-name").value = name;
  document.getElementById("interaction-morse-dot").value = Number(def.dot_threshold).toFixed(3);
  document.getElementById("interaction-morse-timeout").value = Number(def.sequence_timeout).toFixed(3);
  document.getElementById("interaction-morse-fallback").value = def.fallback_action;
  document.getElementById("interaction-morse-force").value = Array.from(def.force_commit).join(", ");
  document.getElementById("interaction-morse-map").value = morseMapObjectToText(def.actions);
  expandMorseTreeForActions(def.actions, def.force_commit);
  syncMorseBehaviorList(name);
  renderMorseTreeEditorFromBuilder();
  _morseAutoLoadedName = name;
  if (options.setStatus) setMorseBuilderStatus(`Morse ${name} を読み込みました`);
}

function defaultMorseBehaviorDefinition() {
  const map = morseMapTextToObject(MORSE_DEFAULT_MAP_TEXT);
  return {
    dot_threshold: 0.18,
    sequence_timeout: 0.7,
    max_depth: inferredMorseMaxDepth(map),
    map,
  };
}

function addMorseBehaviorByName(name) {
  const settings = morseInspectorSettingsFromEditor();
  if (settings === null) {
    setMorseBuilderStatus("JSON parse error");
    syncMorseBehaviorList();
    return false;
  }
  if (!validMorseName(name)) {
    setMorseBuilderStatus("Morse name は A-Z a-z 0-9 _ . - の1〜64文字にしてください");
    syncMorseBehaviorList();
    return false;
  }
  if (!settings.morse_behaviors || typeof settings.morse_behaviors !== "object" || Array.isArray(settings.morse_behaviors)) {
    settings.morse_behaviors = {};
  }
  if (settings.morse_behaviors[name]) {
    loadMorseBehaviorByName(name, { setStatus: true });
    return true;
  }
  settings.morse_behaviors[name] = defaultMorseBehaviorDefinition();
  if (typeof updateInteractionEditor === "function") updateInteractionEditor(settings);
  renderMorseInspectorFromEditor();
  loadMorseBehaviorByName(name, { setStatus: false });
  setMorseBuilderStatus(`Morse ${name} を追加しました`);
  return true;
}

function promptAddMorseBehavior() {
  const previous = selectedMorseBehaviorName();
  const entered = typeof window.prompt === "function"
    ? window.prompt("新しい Morse 定義名", "")
    : "";
  const name = String(entered || "").trim();
  if (entered === null || !name) {
    syncMorseBehaviorList(previous);
    setMorseBuilderStatus("Morse 追加をキャンセルしました");
    return;
  }
  if (!addMorseBehaviorByName(name)) syncMorseBehaviorList(previous);
}

function autoLoadCurrentMorseBehavior() {
  const name = selectedMorseBehaviorName() || "main";
  if (name && name !== _morseAutoLoadedName && morseBehaviorExists(name)) {
    loadMorseBehaviorByName(name, { setStatus: false });
  }
}

function applyMorseBehaviorBuilder(options = {}) {
  const settings = morseInspectorSettingsFromEditor();
  if (settings === null) {
    if (!options.silent) setMorseBuilderStatus("JSON parse error");
    return false;
  }
  const name = selectedMorseBehaviorName();
  if (!validMorseName(name)) {
    if (!options.silent) setMorseBuilderStatus("Defined から更新する Morse 定義を選択してください");
    return false;
  }
  syncMorseTreeInputsToMap();
  let map;
  try {
    map = morseMapTextToObject(document.getElementById("interaction-morse-map")?.value || "");
  } catch (err) {
    if (!options.silent) setMorseBuilderStatus(err.message);
    return false;
  }
  const dot = Number(document.getElementById("interaction-morse-dot")?.value || 0.18);
  const timeout = Number(document.getElementById("interaction-morse-timeout")?.value || 0.7);
  const fallback = document.getElementById("interaction-morse-fallback")?.value.trim() || "";
  const force = morseCsvToList(document.getElementById("interaction-morse-force")?.value || "");
  if (!settings.morse_behaviors || typeof settings.morse_behaviors !== "object" || Array.isArray(settings.morse_behaviors)) {
    settings.morse_behaviors = {};
  }
  settings.morse_behaviors[name] = {
    dot_threshold: Number.isFinite(dot) && dot > 0 ? dot : 0.18,
    sequence_timeout: Number.isFinite(timeout) && timeout > 0 ? timeout : 0.7,
    max_depth: inferredMorseMaxDepth(map),
    fallback_action: fallback,
    force_commit: force,
    map,
  };
  if (!fallback) delete settings.morse_behaviors[name].fallback_action;
  if (!force.length) delete settings.morse_behaviors[name].force_commit;
  if (typeof updateInteractionEditor === "function") {
    updateInteractionEditor(settings);
  }
  syncMorseBehaviorList(name);
  renderMorseInspectorFromEditor();
  renderMorseTreeEditorFromBuilder();
  if (!options.silent) setMorseBuilderStatus(`Morse ${name} を追加/更新しました`);
  return true;
}

async function saveMorseBehaviorBuilder(reload = true) {
  if (!applyMorseBehaviorBuilder()) return;
  if (typeof saveInteractionSettings === "function") {
    await saveInteractionSettings(reload);
  }
}

function flushMorseBehaviorBuilderToEditor() {
  const panel = document.getElementById("interaction-morse-builder");
  if (!panel) return true;
  const name = selectedMorseBehaviorName();
  if (!validMorseName(name)) return true;
  return applyMorseBehaviorBuilder({ silent: true });
}

function deleteMorseBehaviorBuilder() {
  const settings = morseInspectorSettingsFromEditor();
  const name = selectedMorseBehaviorName();
  if (!settings || !settings.morse_behaviors || !settings.morse_behaviors[name]) {
    setMorseBuilderStatus(`Morse ${name || "(empty)"} は未定義です`);
    return;
  }
  delete settings.morse_behaviors[name];
  if (!Object.keys(settings.morse_behaviors).length) delete settings.morse_behaviors;
  if (typeof updateInteractionEditor === "function") updateInteractionEditor(settings);
  _morseAutoLoadedName = "";
  const next = morseBehaviorNames(settings)[0] || "main";
  document.getElementById("interaction-morse-name").value = next;
  syncMorseBehaviorList(next);
  if (morseBehaviorExists(next)) loadMorseBehaviorByName(next, { setStatus: true });
  else renderMorseTreeEditorFromBuilder();
  renderMorseInspectorFromEditor();
  setMorseBuilderStatus(`Morse ${name} を削除しました`);
}

function copyTextToClipboard(text) {
  if (typeof window.__morseCopyTextForTest === "function") {
    window.__morseCopyTextForTest(text);
    return true;
  }
  if (window.navigator && window.navigator.clipboard && typeof window.navigator.clipboard.writeText === "function") {
    const result = window.navigator.clipboard.writeText(text);
    if (result && typeof result.then === "function") {
      result.catch(() => setMorseBuilderStatus(`コピーできませんでした: ${text}`));
    }
    return true;
  }
  return false;
}

function copyMorseActionForBuilder() {
  const name = selectedMorseBehaviorName();
  if (!validMorseName(name)) {
    setMorseBuilderStatus("Defined からコピーする Morse 定義を選択してください");
    return;
  }
  const action = `MORSE(${name})`;
  if (copyTextToClipboard(action)) setMorseBuilderStatus(`${action} をコピーしました`);
  else setMorseBuilderStatus(`コピー用 action: ${action}`);
}

function pickMorseFallbackAction() {
  const input = document.getElementById("interaction-morse-fallback");
  if (typeof openInteractionActionPicker === "function") {
    openInteractionActionPicker(input);
  }
}

function pickMorseTreeAction(sequence, input) {
  if (typeof openInteractionActionPicker === "function") {
    openInteractionActionPicker(input, (action) => updateMorseTreeAction(sequence, action));
  }
}

function morseStateLabel(node) {
  if (node.state === "force_commit") return "force";
  if (node.state === "leaf") return "leaf";
  if (node.state === "prefix") return "prefix";
  if (node.state === "unassigned_prefix") return "prefix/no action";
  if (node.state === "cancel") return "cancel";
  return "root";
}

function morseFeedbackLabel(event) {
  const phase = event.phase || "unknown";
  const name = event.name || "morse";
  const sequence = event.sequence ? ` ${event.sequence}` : "";
  const action = event.action ? ` -> ${event.action}` : "";
  const reason = event.reason ? ` (${event.reason})` : "";
  return `${name}: ${phase}${sequence}${action}${reason}`;
}

function renderMorseFeedback(events = _lastMorseFeedbackEvents) {
  const panel = ensureMorseFeedbackPanel();
  if (!panel) return;
  panel.replaceChildren();
  if (!events.length) {
    panel.textContent = "待機中";
    return;
  }
  for (const event of events.slice(-6).reverse()) {
    const row = document.createElement("div");
    row.className = `interaction-morse-feedback-row feedback-${event.phase || "unknown"}`;
    row.textContent = morseFeedbackLabel(event);
    panel.appendChild(row);
  }
}

async function fetchMorseFeedback() {
  const panel = ensureMorseFeedbackPanel();
  if (!panel) return;
  try {
    const resp = await fetch("/api/interaction/morse-feedback", { credentials: "same-origin" });
    const data = await resp.json();
    if (!resp.ok || data.result !== "ok") {
      panel.textContent = data.msg || "feedback unavailable";
      panel.classList.add("interaction-morse-feedback-error");
      return;
    }
    panel.classList.remove("interaction-morse-feedback-error");
    if (Array.isArray(data.events) && data.events.length) {
      _lastMorseFeedbackEvents = _lastMorseFeedbackEvents.concat(data.events).slice(-20);
    }
    renderMorseFeedback();
  } catch (_err) {
    panel.textContent = "feedback unavailable";
    panel.classList.add("interaction-morse-feedback-error");
  }
}

function startMorseFeedbackPolling() {
  ensureMorseFeedbackPanel();
  fetchMorseFeedback();
  if (_morseFeedbackTimer) return;
  _morseFeedbackTimer = window.setInterval(fetchMorseFeedback, 500);
}

function renderMorseNode(node) {
  const row = document.createElement("div");
  row.className = `interaction-morse-row morse-${node.state}`;
  row.style.marginLeft = `${Math.max(0, node.sequence.length) * 12}px`;
  const seq = node.sequence || "<root>";
  const action = node.action || (node.state === "cancel" ? "cancel" : "–");
  row.innerHTML = `<code>${seq}</code> <span>${action}</span> <em>${morseStateLabel(node)}</em>`;

  const frag = document.createDocumentFragment();
  frag.appendChild(row);
  for (const child of node.children) frag.appendChild(renderMorseNode(child));
  return frag;
}

function renderMorseInspectorFromEditor() {
  const panel = ensureMorseInspectorPanel();
  if (!panel) return;
  const settings = morseInspectorSettingsFromEditor();
  panel.replaceChildren();
  if (settings === null) {
    panel.textContent = "JSON parse error";
    return;
  }
  const behaviors = settings.morse_behaviors && typeof settings.morse_behaviors === "object" && !Array.isArray(settings.morse_behaviors)
    ? settings.morse_behaviors
    : {};
  const entries = Object.entries(behaviors);
  if (!entries.length) {
    panel.textContent = "morse_behaviors 未定義";
    return;
  }
  for (const [name, raw] of entries) {
    const def = normalizeMorseDefinition(raw || {});
    const section = document.createElement("div");
    section.className = "interaction-morse-behavior";
    const title = document.createElement("div");
    title.className = "interaction-morse-title";
    title.textContent = `${name}  dot=${def.dot_threshold}s timeout=${def.sequence_timeout}s depth=${def.max_depth}${def.fallback_action ? ` fallback=${def.fallback_action}` : ""}`;
    section.appendChild(title);
    section.appendChild(renderMorseNode(buildMorseNode("", def.actions, def.force_commit, def.max_depth)));
    panel.appendChild(section);
  }
}

(function installMorseInspectorHook() {
  const init = () => {
    const editor = document.getElementById("interaction-editor");
    if (editor) editor.addEventListener("input", renderMorseInspectorFromEditor);
    ensureMorseSnippetButton();
    ensureMorseEditorPanel();
    syncMorseBehaviorList();
    autoLoadCurrentMorseBehavior();
    renderMorseInspectorFromEditor();
    startMorseFeedbackPolling();
  };
  const original = window.renderInteractionSummary;
  if (typeof original === "function") {
    window.renderInteractionSummary = function wrappedRenderInteractionSummary() {
      original();
      init();
    };
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

window.renderMorseInspectorFromEditor = renderMorseInspectorFromEditor;
window.insertMorseBehaviorSnippet = insertMorseBehaviorSnippet;
window.applyMorseBehaviorBuilder = applyMorseBehaviorBuilder;
window.deleteMorseBehaviorBuilder = deleteMorseBehaviorBuilder;
window.copyMorseActionForBuilder = copyMorseActionForBuilder;
window.pickMorseFallbackAction = pickMorseFallbackAction;
window.pickMorseTreeAction = pickMorseTreeAction;
window.renderMorseTreeEditorFromBuilder = renderMorseTreeEditorFromBuilder;
window.addMorseTreeSequence = addMorseTreeSequence;
window.toggleMorseTreeSequence = toggleMorseTreeSequence;
window.expandMorseTreeSequence = expandMorseTreeSequence;
window.updateMorseTreeAction = updateMorseTreeAction;
window.updateMorseTreeForce = updateMorseTreeForce;
window.syncMorseTreeInputsToMap = syncMorseTreeInputsToMap;
window.saveMorseBehaviorBuilder = saveMorseBehaviorBuilder;
window.flushMorseBehaviorBuilderToEditor = flushMorseBehaviorBuilderToEditor;
window.fetchMorseFeedback = fetchMorseFeedback;
