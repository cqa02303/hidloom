"use strict";

// Static key groups used by the keymap remap popup. Runtime state and rendering
// stay in remap_panel.js.

// PC104 main typing area rows: [keycode, width_units] | null (half-unit gap)
const PC104_MAIN_ROWS = [
  [ ["KC_ESC",1], null,
    ["KC_F1",1],["KC_F2",1],["KC_F3",1],["KC_F4",1], null,
    ["KC_F5",1],["KC_F6",1],["KC_F7",1],["KC_F8",1], null,
    ["KC_F9",1],["KC_F10",1],["KC_F11",1],["KC_F12",1] ],
  [ ["KC_GRAVE",1],["KC_1",1],["KC_2",1],["KC_3",1],["KC_4",1],["KC_5",1],["KC_6",1],
    ["KC_7",1],["KC_8",1],["KC_9",1],["KC_0",1],["KC_MINUS",1],["KC_EQUAL",1],["KC_BSPACE",2] ],
  [ ["KC_TAB",1.5],["KC_Q",1],["KC_W",1],["KC_E",1],["KC_R",1],["KC_T",1],["KC_Y",1],
    ["KC_U",1],["KC_I",1],["KC_O",1],["KC_P",1],["KC_LBRACKET",1],["KC_RBRACKET",1],["KC_BSLASH",1.5] ],
  [ ["KC_CAPSLOCK",1.75],["KC_A",1],["KC_S",1],["KC_D",1],["KC_F",1],["KC_G",1],["KC_H",1],
    ["KC_J",1],["KC_K",1],["KC_L",1],["KC_SCOLON",1],["KC_QUOTE",1],["KC_ENTER",2.25] ],
  [ ["KC_LSHIFT",2.25],["KC_Z",1],["KC_X",1],["KC_C",1],["KC_V",1],["KC_B",1],["KC_N",1],
    ["KC_M",1],["KC_COMMA",1],["KC_DOT",1],["KC_SLASH",1],["KC_RSHIFT",2.75] ],
  [ ["KC_LCTRL",1.25],["KC_LWIN",1.25],["KC_LALT",1.25],["KC_SPACE",6.25],
    ["KC_RALT",1.25],["KC_RWIN",1.25],["KC_APPLICATION",1.25],["KC_RCTRL",1.25] ],
];

const PC104_NAV_ROWS = [
  [ ["KC_PSCREEN",1],["KC_SCROLLLOCK",1],["KC_PAUSE",1] ],
  [],
  [ ["KC_INSERT",1],["KC_HOME",1],["KC_PGUP",1] ],
  [ ["KC_DELETE",1],["KC_END",1],["KC_PGDN",1] ],
  [],
  [ null, ["KC_UP",1], null ],
  [ ["KC_LEFT",1],["KC_DOWN",1],["KC_RIGHT",1] ],
];

const PC104_NUMPAD_ROWS = [
  [ ["KC_NUMLOCK",1],["KC_KP_SLASH",1],["KC_KP_ASTERISK",1],["KC_KP_MINUS",1] ],
  [ ["KC_KP_7",1],["KC_KP_8",1],["KC_KP_9",1],["KC_KP_PLUS",1] ],
  [ ["KC_KP_4",1],["KC_KP_5",1],["KC_KP_6",1] ],
  [ ["KC_KP_1",1],["KC_KP_2",1],["KC_KP_3",1],["KC_KP_ENTER",1] ],
  [ ["KC_KP_0",1],["KC_KP_DOT",1] ],
];

const LAYER_KEY_GROUPS = [
  { label: "Momentary（押している間だけ対象レイヤー）", keys: Array.from({ length: 8 }, (_, i) => `MO(${i})`), perRow: 8 },
  { label: "Toggle（対象レイヤーをトグル切り替え）", keys: Array.from({ length: 8 }, (_, i) => `TG(${i})`), perRow: 8 },
  { label: "To（対象レイヤーへ移動）", keys: Array.from({ length: 8 }, (_, i) => `TO(${i})`), perRow: 8 },
  { label: "Default（既定レイヤーを変更）", keys: Array.from({ length: 8 }, (_, i) => `DF(${i})`), perRow: 8 },
  { label: "One Shot（次の1キーだけ対象レイヤー）", keys: Array.from({ length: 8 }, (_, i) => `OSL(${i})`), perRow: 8 },
];

const MOUSE_KEY_GROUPS = [
  { label: "Buttons", keys: ["KC_BTN1","KC_BTN2","KC_BTN3","KC_BTN4","KC_BTN5","MS_BTN1","MS_BTN2","MS_BTN3","MS_BTN4","MS_BTN5"], perRow: 5 },
  { label: "Move", keys: ["KC_MS_U","KC_MS_D","KC_MS_L","KC_MS_R","MS_UP","MS_DOWN","MS_LEFT","MS_RGHT"], perRow: 4 },
  { label: "Wheel", keys: ["KC_WH_U","KC_WH_D","KC_WH_L","KC_WH_R","MS_WHLU","MS_WHLD","MS_WHLL","MS_WHLR"], perRow: 4 },
  { label: "Acceleration", keys: ["MS_ACL0","MS_ACL1","MS_ACL2"], perRow: 3 },
];

const MEDIA_KEY_GROUPS = [
  { label: "Audio", keys: ["KC_MUTE","KC_VOLU","KC_VOLD","KC_AUDIO_MUTE","KC_AUDIO_VOL_UP","KC_AUDIO_VOL_DOWN"], perRow: 3 },
  { label: "Media", keys: ["KC_MPLY","KC_MNXT","KC_MPRV","KC_MSTP","KC_MFFD","KC_MRWD","KC_EJCT"], perRow: 4 },
  { label: "Application", keys: ["KC_MAIL","KC_CALC","KC_MYCM","KC_WSCH","KC_WHOM","KC_WBAK","KC_WFWD","KC_WSTP","KC_WREF","KC_WFAV"], perRow: 5 },
  { label: "Brightness", keys: ["KC_BRIU","KC_BRID"], perRow: 2 },
];

const LIGHTING_KEY_GROUPS = [
  { label: "RGB", keys: ["RGB_TOG","RGB_MOD","RGB_RMOD","RGB_HUI","RGB_HUD","RGB_SAI","RGB_SAD","RGB_VAI","RGB_VAD","RGB_SPI","RGB_SPD"], perRow: 4 },
  { label: "RGB Matrix", keys: ["RM_ON","RM_OFF","RM_TOGG","RM_NEXT","RM_PREV","RM_HUEU","RM_HUED","RM_SATU","RM_SATD","RM_VALU","RM_VALD","RM_SPDU","RM_SPDD"], perRow: 4 },
];

const BT_KEY_GROUPS = [
  { label: "Bluetooth Control", keys: ["BT_STATUS","BT_POWER_ON","BT_POWER_OFF","BT_POWER_TOGGLE","BT_PAIRING_ON","BT_PAIRING_OFF","BT_PAIRING_TOGGLE","BT_DISCONNECT","BT_FORGET_DEVICE"], perRow: 3 },
  { label: "Bluetooth Output", keys: ["KC_BT"], perRow: 4 },
];

const WIFI_KEY_GROUPS = [
  { label: "Wi-Fi Control（既定は再起動で on に戻る一時操作）", keys: ["WIFI_STATUS","WIFI_POWER_ON","WIFI_POWER_OFF","WIFI_POWER_TOGGLE"], perRow: 2 },
];

const SYSTEM_KEY_GROUPS = [
  { label: "Output", keys: ["KC_CONNAUTO","KC_CONSOLE","KC_USB","KC_BT"], perRow: 4 },
  { label: "System", keys: ["KC_SHUTDOWN"], perRow: 4 },
  { label: "Special", keys: ["KC_TRNS","KC_NONE"], perRow: 4 },
];

const OTHER_KEY_GROUPS = [
  { label: "ショートカット", keys: ["LSFT(LGUI(KC_F23))"], perRow: 4 },
  { label: "F13-F24",   keys: ["KC_F13","KC_F14","KC_F15","KC_F16","KC_F17","KC_F18","KC_F19","KC_F20","KC_F21","KC_F22","KC_F23","KC_F24"] },
];

const SCRIPT_KEY_GROUPS = [
  { label: "スクリプト", keys: ["KC_SH0","KC_SH1","KC_SH2","KC_SH3","KC_SH4","KC_SH5","KC_SH6","KC_SH7","KC_SH8","KC_SH9","KC_SH10"], perRow: 4 },
];

const INTERACTION_KEY_GROUPS = [
  { label: "Runtime helpers", keys: ["CAPS_WORD","REPEAT_KEY","ALT_REPEAT_KEY","QK_LAYER_LOCK","QK_LLCK","DRAG_LOCK"], perRow: 3 },
];

const SPECIAL_KEY_GROUPS = [
  { label: "特殊", keys: ["KC_TRNS","KC_NONE"] },
];

const PC104_EXTRA_KEY_GROUPS = [
  { label: "日本語IME", keys: ["KC_ZKHK","KC_RO","KC_KANA","KC_JYEN","KC_HENKAN","KC_MUHENKAN","KC_HENK","KC_MHEN"] },
  { label: "言語", keys: ["KC_LANG1","KC_LANG2","KC_LANG3","KC_LANG4","KC_LANG5"] },
  ...SPECIAL_KEY_GROUPS,
];

const REMAP_TAB_GROUPS = {
  layer: LAYER_KEY_GROUPS,
  mouse: MOUSE_KEY_GROUPS,
  media: MEDIA_KEY_GROUPS,
  lighting: LIGHTING_KEY_GROUPS,
  bt: BT_KEY_GROUPS,
  wifi: WIFI_KEY_GROUPS,
  system: SYSTEM_KEY_GROUPS,
  interaction: INTERACTION_KEY_GROUPS,
  script: SCRIPT_KEY_GROUPS,
  other: OTHER_KEY_GROUPS,
};

const REMAP_TAB_ORDER = ["pc104", "layer", "mouse", "media", "lighting", "bt", "wifi", "system", "interaction", "script", "other"];
