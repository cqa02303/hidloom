# Keycode action inventory

この文書は `config/default/keycodes.json` から生成した action 完全一覧です。
分類と出力先ごとの読み方は [action-routing-matrix.md](action-routing-matrix.md) を参照してください。

更新する時は次を実行します。

```bash
python3 tools/keycode_action_inventory.py --document --output docs/keycode/action-inventory.md
```

| action | canonical | category | hid_page | hid_usage | linux_code | logicd | logicd_core_rs | usb | uinput | bt | special_notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BT_DISCONNECT |  | local_command | none | 990 | null | internal | not_in_m0 | no | no | no |  |
| BT_FORGET_DEVICE |  | local_command | none | 991 | null | internal | not_in_m0 | no | no | no |  |
| BT_PAIRING_OFF |  | local_command | none | 988 | null | internal | not_in_m0 | no | no | no |  |
| BT_PAIRING_ON |  | local_command | none | 987 | null | internal | not_in_m0 | no | no | no |  |
| BT_PAIRING_TOGGLE |  | local_command | none | 989 | null | internal | not_in_m0 | no | no | no |  |
| BT_POWER_OFF |  | local_command | none | 985 | null | internal | not_in_m0 | no | no | no |  |
| BT_POWER_ON |  | local_command | none | 984 | null | internal | not_in_m0 | no | no | no |  |
| BT_POWER_TOGGLE |  | local_command | none | 986 | null | internal | not_in_m0 | no | no | no |  |
| BT_STATUS |  | local_command | none | 983 | null | internal | not_in_m0 | no | no | no |  |
| KC_0 |  | keyboard | keyboard | 39 | 11 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_1 |  | keyboard | keyboard | 30 | 2 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_2 |  | keyboard | keyboard | 31 | 3 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_3 |  | keyboard | keyboard | 32 | 4 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_4 |  | keyboard | keyboard | 33 | 5 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_5 |  | keyboard | keyboard | 34 | 6 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_6 |  | keyboard | keyboard | 35 | 7 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_7 |  | keyboard | keyboard | 36 | 8 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_8 |  | keyboard | keyboard | 37 | 9 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_9 |  | keyboard | keyboard | 38 | 10 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_A |  | keyboard | keyboard | 4 | 30 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_AGAIN |  | keyboard | keyboard | 121 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_ALTERNATE_ERASE |  | keyboard | keyboard | 153 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_APP | KC_APPLICATION | keyboard | keyboard | 101 | 127 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_APPLICATION |  | keyboard | keyboard | 101 | 127 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_AUDIO_MUTE |  | consumer | consumer | 226 | 113 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_AUDIO_VOL_DOWN |  | consumer | consumer | 234 | 114 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_AUDIO_VOL_UP |  | consumer | consumer | 233 | 115 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_B |  | keyboard | keyboard | 5 | 48 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_BACKSPACE | KC_BSPACE | keyboard | keyboard | 42 | 14 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_BRID | KC_BRIGHTNESS_DOWN | consumer | consumer | 112 | 224 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_BRIGHTNESS_DOWN |  | consumer | consumer | 112 | 224 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_BRIGHTNESS_UP |  | consumer | consumer | 111 | 225 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_BRIU | KC_BRIGHTNESS_UP | consumer | consumer | 111 | 225 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_BSLASH |  | keyboard | keyboard | 49 | 43 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_BSLS | KC_BSLASH | keyboard | keyboard | 49 | 43 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_BSPACE |  | keyboard | keyboard | 42 | 14 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_BSPC | KC_BSPACE | keyboard | keyboard | 42 | 14 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_BT |  | local_command | none | 992 | null | internal | not_in_m0 | no | no | no |  |
| KC_BTN1 |  | mouse | mouse | 512 | null | send | not_in_m0 | mouse | partial | mouse |  |
| KC_BTN2 |  | mouse | mouse | 513 | null | send | not_in_m0 | mouse | partial | mouse |  |
| KC_BTN3 |  | mouse | mouse | 514 | null | send | not_in_m0 | mouse | partial | mouse |  |
| KC_BTN4 |  | mouse | mouse | 515 | null | send | not_in_m0 | mouse | partial | mouse |  |
| KC_BTN5 |  | mouse | mouse | 516 | null | send | not_in_m0 | mouse | partial | mouse |  |
| KC_C |  | keyboard | keyboard | 6 | 46 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_CALC | KC_CALCULATOR | consumer | consumer | 402 | 140 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_CALCULATOR |  | consumer | consumer | 402 | 140 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_CANCEL |  | keyboard | keyboard | 155 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_CAPS | KC_CAPSLOCK | keyboard | keyboard | 57 | 58 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_CAPSLOCK |  | keyboard | keyboard | 57 | 58 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_CLEAR |  | keyboard | keyboard | 156 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_CLEAR_AGAIN |  | keyboard | keyboard | 162 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_COMM | KC_COMMA | keyboard | keyboard | 54 | 51 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_COMMA |  | keyboard | keyboard | 54 | 51 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_CONNAUTO |  | local_command | none | 980 | null | internal | not_in_m0 | no | no | no |  |
| KC_CONSOLE |  | local_command | none | 981 | null | internal | not_in_m0 | no | no | no |  |
| KC_COPY |  | keyboard | keyboard | 124 | 133 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_CRSEL |  | keyboard | keyboard | 163 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_CUT |  | keyboard | keyboard | 123 | 137 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_D |  | keyboard | keyboard | 7 | 32 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_DEL | KC_DELETE | keyboard | keyboard | 76 | 111 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_DELETE |  | keyboard | keyboard | 76 | 111 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_DOT |  | keyboard | keyboard | 55 | 52 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_DOWN |  | keyboard | keyboard | 81 | 108 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_E |  | keyboard | keyboard | 8 | 18 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_EJCT | KC_MEDIA_EJECT | consumer | consumer | 184 | 161 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_END |  | keyboard | keyboard | 77 | 107 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_ENT | KC_ENTER | keyboard | keyboard | 40 | 28 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_ENTER |  | keyboard | keyboard | 40 | 28 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_EQL | KC_EQUAL | keyboard | keyboard | 46 | 13 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_EQUAL |  | keyboard | keyboard | 46 | 13 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_ESC |  | keyboard | keyboard | 41 | 1 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_ESCAPE | KC_ESC | keyboard | keyboard | 41 | 1 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_EXECUTE |  | keyboard | keyboard | 116 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_EXSEL |  | keyboard | keyboard | 164 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_F |  | keyboard | keyboard | 9 | 33 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_F1 |  | keyboard | keyboard | 58 | 59 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_F10 |  | keyboard | keyboard | 67 | 68 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_F11 |  | keyboard | keyboard | 68 | 87 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_F12 |  | keyboard | keyboard | 69 | 88 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_F13 |  | keyboard | keyboard | 104 | 183 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_F14 |  | keyboard | keyboard | 105 | 184 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_F15 |  | keyboard | keyboard | 106 | 185 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_F16 |  | keyboard | keyboard | 107 | 186 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_F17 |  | keyboard | keyboard | 108 | 187 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_F18 |  | keyboard | keyboard | 109 | 188 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_F19 |  | keyboard | keyboard | 110 | 189 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_F2 |  | keyboard | keyboard | 59 | 60 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_F20 |  | keyboard | keyboard | 111 | 190 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_F21 |  | keyboard | keyboard | 112 | 191 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_F22 |  | keyboard | keyboard | 113 | 192 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_F23 |  | keyboard | keyboard | 114 | 193 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_F24 |  | keyboard | keyboard | 115 | 194 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_F3 |  | keyboard | keyboard | 60 | 61 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_F4 |  | keyboard | keyboard | 61 | 62 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_F5 |  | keyboard | keyboard | 62 | 63 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_F6 |  | keyboard | keyboard | 63 | 64 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_F7 |  | keyboard | keyboard | 64 | 65 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_F8 |  | keyboard | keyboard | 65 | 66 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_F9 |  | keyboard | keyboard | 66 | 67 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_FIND |  | keyboard | keyboard | 126 | 136 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_G |  | keyboard | keyboard | 10 | 34 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_GRAVE |  | keyboard | keyboard | 53 | 41 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_GRV | KC_GRAVE | keyboard | keyboard | 53 | 41 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_H |  | keyboard | keyboard | 11 | 35 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_HELP |  | keyboard | keyboard | 117 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_HENK | KC_INT4 | keyboard | keyboard | 138 | 92 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_HENKAN | KC_INT4 | keyboard | keyboard | 138 | 92 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_HOME |  | keyboard | keyboard | 74 | 102 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_I |  | keyboard | keyboard | 12 | 23 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_INS | KC_INSERT | keyboard | keyboard | 73 | 110 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_INSERT |  | keyboard | keyboard | 73 | 110 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_INT1 |  | keyboard | keyboard | 135 | 89 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_INT2 |  | keyboard | keyboard | 136 | 93 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_INT3 |  | keyboard | keyboard | 137 | 124 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_INT4 |  | keyboard | keyboard | 138 | 92 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_INT5 |  | keyboard | keyboard | 139 | 94 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_INT6 |  | keyboard | keyboard | 140 | 95 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_INT7 |  | keyboard | keyboard | 141 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_INT8 |  | keyboard | keyboard | 142 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_INT9 |  | keyboard | keyboard | 143 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_J |  | keyboard | keyboard | 13 | 36 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_JYEN | KC_INT3 | keyboard | keyboard | 137 | 124 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_K |  | keyboard | keyboard | 14 | 37 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_KANA | KC_INT2 | keyboard | keyboard | 136 | 93 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_KB_MUTE |  | keyboard | keyboard | 127 | 113 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_KB_VOLUME_DOWN |  | keyboard | keyboard | 129 | 114 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_KB_VOLUME_UP |  | keyboard | keyboard | 128 | 115 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_KP_0 |  | keyboard | keyboard | 98 | 82 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_KP_1 |  | keyboard | keyboard | 89 | 79 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_KP_2 |  | keyboard | keyboard | 90 | 80 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_KP_3 |  | keyboard | keyboard | 91 | 81 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_KP_4 |  | keyboard | keyboard | 92 | 75 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_KP_5 |  | keyboard | keyboard | 93 | 76 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_KP_6 |  | keyboard | keyboard | 94 | 77 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_KP_7 |  | keyboard | keyboard | 95 | 71 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_KP_8 |  | keyboard | keyboard | 96 | 72 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_KP_9 |  | keyboard | keyboard | 97 | 73 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_KP_ASTERISK |  | keyboard | keyboard | 85 | 55 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_KP_COMMA |  | keyboard | keyboard | 133 | 121 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_KP_DOT |  | keyboard | keyboard | 99 | 83 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_KP_ENTER |  | keyboard | keyboard | 88 | 96 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_KP_EQUAL |  | keyboard | keyboard | 103 | 117 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_KP_EQUAL_AS400 |  | keyboard | keyboard | 134 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_KP_MINUS |  | keyboard | keyboard | 86 | 74 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_KP_PLUS |  | keyboard | keyboard | 87 | 78 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_KP_SLASH |  | keyboard | keyboard | 84 | 98 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_L |  | keyboard | keyboard | 15 | 38 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_LALT |  | modifier | keyboard | 226 | 56 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_LANG1 |  | keyboard | keyboard | 144 | 122 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_LANG2 |  | keyboard | keyboard | 145 | 123 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_LANG3 |  | keyboard | keyboard | 146 | 90 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_LANG4 |  | keyboard | keyboard | 147 | 91 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_LANG5 |  | keyboard | keyboard | 148 | 85 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_LANG6 |  | keyboard | keyboard | 149 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_LANG7 |  | keyboard | keyboard | 150 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_LANG8 |  | keyboard | keyboard | 151 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_LANG9 |  | keyboard | keyboard | 152 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_LANGUAGE_6 | KC_LANG6 | keyboard | keyboard | 149 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_LANGUAGE_7 | KC_LANG7 | keyboard | keyboard | 150 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_LANGUAGE_8 | KC_LANG8 | keyboard | keyboard | 151 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_LANGUAGE_9 | KC_LANG9 | keyboard | keyboard | 152 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_LBRACKET |  | keyboard | keyboard | 47 | 26 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_LBRC | KC_LBRACKET | keyboard | keyboard | 47 | 26 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_LCMD | KC_LWIN | modifier | keyboard | 227 | 125 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_LCTL | KC_LCTRL | modifier | keyboard | 224 | 29 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_LCTRL |  | modifier | keyboard | 224 | 29 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_LEFT |  | keyboard | keyboard | 80 | 105 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_LGUI | KC_LWIN | modifier | keyboard | 227 | 125 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_LOCKING_CAPS_LOCK |  | keyboard | keyboard | 130 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_LOCKING_NUM_LOCK |  | keyboard | keyboard | 131 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_LOCKING_SCROLL_LOCK |  | keyboard | keyboard | 132 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_LOPT | KC_LWIN | modifier | keyboard | 227 | 125 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_LSFT | KC_LSHIFT | modifier | keyboard | 225 | 42 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_LSHIFT |  | modifier | keyboard | 225 | 42 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_LWIN |  | modifier | keyboard | 227 | 125 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_M |  | keyboard | keyboard | 16 | 50 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_MAIL |  | consumer | consumer | 394 | 215 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_MEDIA_EJECT |  | consumer | consumer | 184 | 161 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_MEDIA_FAST_FORWARD |  | consumer | consumer | 179 | 208 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_MEDIA_NEXT_TRACK |  | consumer | consumer | 181 | 163 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_MEDIA_PLAY_PAUSE |  | consumer | consumer | 205 | 164 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_MEDIA_PREV_TRACK |  | consumer | consumer | 182 | 165 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_MEDIA_REWIND |  | consumer | consumer | 180 | 168 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_MEDIA_SELECT |  | consumer | consumer | 387 | 226 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_MEDIA_STOP |  | consumer | consumer | 183 | 166 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_MENU |  | keyboard | keyboard | 118 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_MFFD | KC_MEDIA_FAST_FORWARD | consumer | consumer | 179 | 208 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_MHEN | KC_INT5 | keyboard | keyboard | 139 | 94 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_MINS | KC_MINUS | keyboard | keyboard | 45 | 12 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_MINUS |  | keyboard | keyboard | 45 | 12 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_MNXT | KC_MEDIA_NEXT_TRACK | consumer | consumer | 181 | 163 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_MPLY | KC_MEDIA_PLAY_PAUSE | consumer | consumer | 205 | 164 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_MPRV | KC_MEDIA_PREV_TRACK | consumer | consumer | 182 | 165 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_MRWD | KC_MEDIA_REWIND | consumer | consumer | 180 | 168 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_MSEL | KC_MEDIA_SELECT | consumer | consumer | 387 | 226 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_MSTP | KC_MEDIA_STOP | consumer | consumer | 183 | 166 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_MS_D |  | mouse | mouse | 521 | null | send | not_in_m0 | mouse | partial | mouse |  |
| KC_MS_L |  | mouse | mouse | 522 | null | send | not_in_m0 | mouse | partial | mouse |  |
| KC_MS_R |  | mouse | mouse | 523 | null | send | not_in_m0 | mouse | partial | mouse |  |
| KC_MS_U |  | mouse | mouse | 520 | null | send | not_in_m0 | mouse | partial | mouse |  |
| KC_MUHENKAN | KC_INT5 | keyboard | keyboard | 139 | 94 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_MUTE | KC_AUDIO_MUTE | consumer | consumer | 226 | 113 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_MYCM | KC_MY_COMPUTER | consumer | consumer | 404 | 157 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_MY_COMPUTER |  | consumer | consumer | 404 | 157 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_N |  | keyboard | keyboard | 17 | 49 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_NLCK | KC_NUMLOCK | keyboard | keyboard | 83 | 69 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_NONE |  | no-op | none | 0 | null | internal | not_in_m0 | no | no | no |  |
| KC_NONUS_BACKSLASH |  | keyboard | keyboard | 100 | 86 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_NUBS | KC_NONUS_BACKSLASH | keyboard | keyboard | 100 | 86 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_NUHS |  | keyboard | keyboard | 50 | 86 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_NUMLOCK |  | keyboard | keyboard | 83 | 69 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_O |  | keyboard | keyboard | 18 | 24 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_OPER |  | keyboard | keyboard | 161 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_OUT |  | keyboard | keyboard | 160 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_P |  | keyboard | keyboard | 19 | 25 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_PASTE |  | keyboard | keyboard | 125 | 135 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_PAUS | KC_PAUSE | keyboard | keyboard | 72 | 119 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_PAUSE |  | keyboard | keyboard | 72 | 119 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_PCMM | KC_KP_COMMA | keyboard | keyboard | 133 | 121 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_PEQL | KC_KP_EQUAL | keyboard | keyboard | 103 | 117 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_PGDN |  | keyboard | keyboard | 78 | 109 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_PGUP |  | keyboard | keyboard | 75 | 104 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_PRIOR |  | keyboard | keyboard | 157 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_PSCR | KC_PSCREEN | keyboard | keyboard | 70 | 99 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_PSCREEN |  | keyboard | keyboard | 70 | 99 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_PSTE | KC_PASTE | keyboard | keyboard | 125 | 135 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_Q |  | keyboard | keyboard | 20 | 16 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_QUOT | KC_QUOTE | keyboard | keyboard | 52 | 40 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_QUOTE |  | keyboard | keyboard | 52 | 40 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_R |  | keyboard | keyboard | 21 | 19 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_RALT |  | modifier | keyboard | 230 | 100 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_RBRACKET |  | keyboard | keyboard | 48 | 27 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_RBRC | KC_RBRACKET | keyboard | keyboard | 48 | 27 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_RCMD | KC_RWIN | modifier | keyboard | 231 | 126 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_RCTL | KC_RCTRL | modifier | keyboard | 228 | 97 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_RCTRL |  | modifier | keyboard | 228 | 97 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_RGHT | KC_RIGHT | keyboard | keyboard | 79 | 106 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_RGUI | KC_RWIN | modifier | keyboard | 231 | 126 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_RIGHT |  | keyboard | keyboard | 79 | 106 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_RO | KC_INT1 | keyboard | keyboard | 135 | 89 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_ROPT | KC_RALT | modifier | keyboard | 230 | 100 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_RSFT | KC_RSHIFT | modifier | keyboard | 229 | 54 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_RSHIFT |  | modifier | keyboard | 229 | 54 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_RWIN |  | modifier | keyboard | 231 | 126 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_S |  | keyboard | keyboard | 22 | 31 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_SCLN | KC_SCOLON | keyboard | keyboard | 51 | 39 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_SCOLON |  | keyboard | keyboard | 51 | 39 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_SCROLLLOCK |  | keyboard | keyboard | 71 | 70 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_SELECT |  | keyboard | keyboard | 119 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_SEPARATOR |  | keyboard | keyboard | 159 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_SH0 |  | local_command | none | 960 | null | internal | not_in_m0 | no | no | no |  |
| KC_SH1 |  | local_command | none | 961 | null | internal | not_in_m0 | no | no | no |  |
| KC_SH10 |  | local_command | none | 970 | null | internal | not_in_m0 | no | no | no |  |
| KC_SH2 |  | local_command | none | 962 | null | internal | not_in_m0 | no | no | no |  |
| KC_SH3 |  | local_command | none | 963 | null | internal | not_in_m0 | no | no | no |  |
| KC_SH4 |  | local_command | none | 964 | null | internal | not_in_m0 | no | no | no |  |
| KC_SH5 |  | local_command | none | 965 | null | internal | not_in_m0 | no | no | no |  |
| KC_SH6 |  | local_command | none | 966 | null | internal | not_in_m0 | no | no | no |  |
| KC_SH7 |  | local_command | none | 967 | null | internal | not_in_m0 | no | no | no |  |
| KC_SH8 |  | local_command | none | 968 | null | internal | not_in_m0 | no | no | no |  |
| KC_SH9 |  | local_command | none | 969 | null | internal | not_in_m0 | no | no | no |  |
| KC_SHUTDOWN |  | local_command | none | 999 | null | internal | not_in_m0 | no | no | no |  |
| KC_SLASH |  | keyboard | keyboard | 56 | 53 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_SLCK | KC_SCROLLLOCK | keyboard | keyboard | 71 | 70 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_SLSH | KC_SLASH | keyboard | keyboard | 56 | 53 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_SPACE |  | keyboard | keyboard | 44 | 57 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_SPC | KC_SPACE | keyboard | keyboard | 44 | 57 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_STOP |  | keyboard | keyboard | 120 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_SYSTEM_REQUEST |  | keyboard | keyboard | 154 | null | send | keyboard_page | keyboard | no | keyboard |  |
| KC_T |  | keyboard | keyboard | 23 | 20 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_TAB |  | keyboard | keyboard | 43 | 15 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_TRNS |  | no-op | none | 0 | null | internal | not_in_m0 | no | no | no |  |
| KC_U |  | keyboard | keyboard | 24 | 22 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_UNDO |  | keyboard | keyboard | 122 | 131 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_UP |  | keyboard | keyboard | 82 | 103 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_USB |  | local_command | none | 982 | null | internal | not_in_m0 | no | no | no |  |
| KC_V |  | keyboard | keyboard | 25 | 47 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_VOLD | KC_AUDIO_VOL_DOWN | consumer | consumer | 234 | 114 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_VOLU | KC_AUDIO_VOL_UP | consumer | consumer | 233 | 115 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_W |  | keyboard | keyboard | 26 | 17 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_WBAK | KC_WWW_BACK | consumer | consumer | 548 | 158 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_WFAV | KC_WWW_FAVORITES | consumer | consumer | 554 | 156 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_WFWD | KC_WWW_FORWARD | consumer | consumer | 549 | 159 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_WHOM | KC_WWW_HOME | consumer | consumer | 547 | 172 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_WH_D |  | mouse | mouse | 525 | null | send | not_in_m0 | mouse | partial | mouse |  |
| KC_WH_L |  | mouse | mouse | 526 | null | send | not_in_m0 | mouse | partial | mouse |  |
| KC_WH_R |  | mouse | mouse | 527 | null | send | not_in_m0 | mouse | partial | mouse |  |
| KC_WH_U |  | mouse | mouse | 524 | null | send | not_in_m0 | mouse | partial | mouse |  |
| KC_WREF | KC_WWW_REFRESH | consumer | consumer | 551 | 173 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_WSCH | KC_WWW_SEARCH | consumer | consumer | 545 | 217 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_WSTP | KC_WWW_STOP | consumer | consumer | 550 | 128 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_WWW_BACK |  | consumer | consumer | 548 | 158 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_WWW_FAVORITES |  | consumer | consumer | 554 | 156 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_WWW_FORWARD |  | consumer | consumer | 549 | 159 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_WWW_HOME |  | consumer | consumer | 547 | 172 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_WWW_REFRESH |  | consumer | consumer | 551 | 173 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_WWW_SEARCH |  | consumer | consumer | 545 | 217 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_WWW_STOP |  | consumer | consumer | 550 | 128 | send | not_in_m0 | consumer | yes | consumer |  |
| KC_X |  | keyboard | keyboard | 27 | 45 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_Y |  | keyboard | keyboard | 28 | 21 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_Z |  | keyboard | keyboard | 29 | 44 | send | keyboard_page | keyboard | yes | keyboard |  |
| KC_ZENKAKU_HANKAKU | KC_ZKHK | local_command | none | 997 | null | internal | not_in_m0 | no | no | no |  |
| KC_ZKHK |  | local_command | none | 997 | null | internal | not_in_m0 | no | no | no |  |
| MS_ACL0 |  | keyboard | keyboard | 528 | null | send | keyboard_page | keyboard | no | keyboard |  |
| MS_ACL1 |  | keyboard | keyboard | 529 | null | send | keyboard_page | keyboard | no | keyboard |  |
| MS_ACL2 |  | keyboard | keyboard | 530 | null | send | keyboard_page | keyboard | no | keyboard |  |
| MS_BTN1 | KC_BTN1 | mouse | mouse | 512 | null | send | not_in_m0 | mouse | partial | mouse |  |
| MS_BTN2 | KC_BTN2 | mouse | mouse | 513 | null | send | not_in_m0 | mouse | partial | mouse |  |
| MS_BTN3 | KC_BTN3 | mouse | mouse | 514 | null | send | not_in_m0 | mouse | partial | mouse |  |
| MS_BTN4 | KC_BTN4 | mouse | mouse | 515 | null | send | not_in_m0 | mouse | partial | mouse |  |
| MS_BTN5 | KC_BTN5 | mouse | mouse | 516 | null | send | not_in_m0 | mouse | partial | mouse |  |
| WIFI_POWER_OFF |  | local_command | none | 995 | null | internal | not_in_m0 | no | no | no |  |
| WIFI_POWER_ON |  | local_command | none | 994 | null | internal | not_in_m0 | no | no | no |  |
| WIFI_POWER_TOGGLE |  | local_command | none | 996 | null | internal | not_in_m0 | no | no | no |  |
| WIFI_STATUS |  | local_command | none | 993 | null | internal | not_in_m0 | no | no | no |  |
