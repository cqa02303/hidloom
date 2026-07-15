# Windows US custom HID warning metadata

更新日: 2026-06-10

実送信 route を有効化する前に、HTTP UI / key picker / inspector では warning-only metadata として見せる。

## 目的

- `KC_INT4` / `KC_INT5` / `KC_LANG1` / `KC_LANG2` / `KC_HENK` / `KC_MHEN` が Windows US layout では標準 keyboard endpoint で期待通り処理されない可能性を表示する。
- custom HID route は設計済みでも、Windows receiver と opt-in descriptor がない限り実送信しないことを明示する。
- ユーザーが keymap に設定した時に、なぜ no-op / fallback になるか分かるようにする。

## metadata 候補

```json
{
  "family": "windows_ime_custom_hid",
  "requires_host_profile": "windows_us_custom_hid_ime",
  "requires_custom_hid_endpoint": true,
  "requires_windows_receiver": true,
  "default_behavior": "keyboard_or_warning",
  "safe_to_send_without_receiver": false
}
```

## warning 文言候補

- `Windows US layout may ignore this IME key on the standard keyboard endpoint.`
- `Enable only with windows_us_custom_hid_ime profile and a companion Windows receiver.`
- `Custom HID route is not active; this key will use the normal keyboard path or no-op policy.`

## 実装方針

- 初期は docs / metadata のみ。
- key picker へ追加する場合も、保存 payload は変えない。
- `daemon/logicd/windows_ime_custom_hid.py` の dry-run plan を使い、blocked reason を UI に出す。
- `receiver_required` / `receiver_available` を UI から手で true にしない。将来 receiver status path で更新する。

## 残タスク

- Interaction inspector または key picker metadata へ warning を接続するか判断する。
- `blocked_reason` の文言を i18n / UI helper で扱うか判断する。
- Windows receiver PoC 後に receiver status をどう伝えるか決める。
