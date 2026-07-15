"use strict";

// -----------------------------------------------------------------------
// KeyboardEvent.code → 表示ラベル 静的テーブル
// KLE の displayLabel (最後の \n トークン) と照合して matrix を解決する
// -----------------------------------------------------------------------

const CODE_LABEL_MAP = {
  // Letters
  KeyA:"A", KeyB:"B", KeyC:"C", KeyD:"D", KeyE:"E", KeyF:"F", KeyG:"G",
  KeyH:"H", KeyI:"I", KeyJ:"J", KeyK:"K", KeyL:"L", KeyM:"M", KeyN:"N",
  KeyO:"O", KeyP:"P", KeyQ:"Q", KeyR:"R", KeyS:"S", KeyT:"T", KeyU:"U",
  KeyV:"V", KeyW:"W", KeyX:"X", KeyY:"Y", KeyZ:"Z",
  // Digits (top row)
  Digit1:"1", Digit2:"2", Digit3:"3", Digit4:"4", Digit5:"5",
  Digit6:"6", Digit7:"7", Digit8:"8", Digit9:"9", Digit0:"0",
  // Function keys
  F1:"F1", F2:"F2", F3:"F3", F4:"F4", F5:"F5", F6:"F6",
  F7:"F7", F8:"F8", F9:"F9", F10:"F10", F11:"F11", F12:"F12",
  // Control keys
  Escape:"Esc", Backspace:"BackSpace", Tab:"Tab", CapsLock:"Caps Lock",
  Enter:"Enter", Space:"Space",
  // Modifiers
  ShiftLeft:"Shift",   ShiftRight:"Shift",
  ControlLeft:"Ctrl",  ControlRight:"Ctrl",
  AltLeft:"Alt",       AltRight:"Alt",
  MetaLeft:"Win",      MetaRight:"Win",
  // Punctuation (US layout)
  Minus:"-",         Equal:"=",
  BracketLeft:"[",   BracketRight:"]",
  Backslash:"\\",    Semicolon:";",  Quote:"'",
  Backquote:"`",     Comma:",",      Period:".",  Slash:"/",
  // Navigation
  ArrowUp:"↑", ArrowDown:"↓", ArrowLeft:"←", ArrowRight:"→",
  Delete:"Delete", Insert:"Insert", Home:"Home", End:"End",
  PageUp:"Page Up", PageDown:"Page Down",
  // Numpad
  Numpad0:"0", Numpad1:"1", Numpad2:"2", Numpad3:"3", Numpad4:"4",
  Numpad5:"5", Numpad6:"6", Numpad7:"7", Numpad8:"8", Numpad9:"9",
  NumpadAdd:"+", NumpadSubtract:"-", NumpadMultiply:"*", NumpadDivide:"/",
  NumpadDecimal:".", NumpadEnter:"Enter", NumLock:"Num Lock",
  // Media / browser
  AudioVolumeMute:"Mute", AudioVolumeUp:"Vol+", AudioVolumeDown:"Vol-",
};

// code → slot element の Map（renderKeyboard 後に構築）
let codeToElement = new Map();
let codeToMatrix  = new Map();

/**
 * 全スロットの displayLabel を正規化して CODE_LABEL_MAP と照合し、
 * code → {row, col} と code → DOM element の 2 つの Map を構築する。
 */
function buildCodeMaps(slots) {
  codeToElement = new Map();
  codeToMatrix  = new Map();

  // label → elements の逆引き（同ラベルが複数ある場合は最初の1つを使う）
  const labelToEntry = new Map();
  for (const s of slots) {
    if (!s.matrix) continue;
    const parts = s.label.split("\n");
    // KLE では最後のトークンが人間向けラベルとなる慣例
    // 加えて最初のトークンも登録しておく（"BackSpace" など）
    const tokens = new Set([
      parts[0].trim(),
      parts[parts.length - 1].trim(),
    ]);
    for (const t of tokens) {
      if (t && !labelToEntry.has(t.toLowerCase())) {
        labelToEntry.set(t.toLowerCase(), { matrix: s.matrix, el: s._el });
      }
    }
  }

  for (const [code, label] of Object.entries(CODE_LABEL_MAP)) {
    const entry = labelToEntry.get(label.toLowerCase());
    if (entry) {
      codeToMatrix.set(code, entry.matrix);
      if (entry.el) codeToElement.set(code, entry.el);
    }
  }
}

// -----------------------------------------------------------------------
// ブラウザキーボード入力転送
// -----------------------------------------------------------------------

let keyPassthroughEnabled = false;
// 押下中の code を管理（keydown の連打を防ぐ）
const _pressedCodes = new Set();

function setKeyPassthrough(enabled) {
  keyPassthroughEnabled = enabled;
  const btn = document.getElementById("passthrough-toggle");
  if (btn) {
    btn.textContent = enabled ? "キー入力転送: ON" : "キー入力転送: OFF";
    btn.classList.toggle("active", enabled);
  }
  if (typeof window.refreshKeyboardControlsOverlay === "function") {
    window.refreshKeyboardControlsOverlay();
  }
  if (!enabled) {
    // 押しっぱなしになっているキーを全て解放
    for (const code of _pressedCodes) {
      const m = codeToMatrix.get(code);
      if (m) sendKey("keyup", m.row, m.col);
      const el = codeToElement.get(code);
      if (el) el.classList.remove("pressed");
    }
    _pressedCodes.clear();
  }
}

document.addEventListener("keydown", (e) => {
  if (!keyPassthroughEnabled) return;
  if (_pressedCodes.has(e.code)) return;  // autorepeat を無視
  const m = codeToMatrix.get(e.code);
  if (!m) return;
  e.preventDefault();
  _pressedCodes.add(e.code);
  sendKey("keydown", m.row, m.col);
  const el = codeToElement.get(e.code);
  if (el) el.classList.add("pressed");
});

document.addEventListener("keyup", (e) => {
  if (!keyPassthroughEnabled) return;
  _pressedCodes.delete(e.code);
  const m = codeToMatrix.get(e.code);
  if (!m) return;
  e.preventDefault();
  sendKey("keyup", m.row, m.col);
  const el = codeToElement.get(e.code);
  if (el) el.classList.remove("pressed");
});
