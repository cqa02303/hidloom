#!/usr/bin/env python3
"""Smoke-test KC_SH script editor helper UI wiring."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _script_hid_options(script_js: str) -> list[tuple[str, int]]:
    match = re.search(
        r"const SCRIPT_HID_KEY_OPTIONS = \[(?P<body>.*?)\];",
        script_js,
        flags=re.S,
    )
    assert match, "SCRIPT_HID_KEY_OPTIONS"
    return [
        (label, int(value, 16))
        for label, value in re.findall(r'\["([^"]+)",\s+"0x([0-9a-f]+)"\]', match.group("body"))
    ]


def main() -> None:
    index_html = (ROOT / "daemon" / "http" / "static" / "index.html").read_text(encoding="utf-8")
    script_js = (ROOT / "daemon" / "http" / "static" / "script_editor.js").read_text(encoding="utf-8")
    scripts_panel_js = (ROOT / "daemon" / "http" / "static" / "scripts_panel.js").read_text(encoding="utf-8")
    keyboard_css = (ROOT / "daemon" / "http" / "static" / "keyboard.css").read_text(encoding="utf-8")

    assert '<button class="script-command-btn"' not in index_html
    assert 'onclick="insertScriptSnippet(\'oledWarning\')"' in index_html
    assert 'onclick="insertScriptSnippet(\'oledAlert\')"' in index_html
    assert 'onclick="insertScriptSnippet(\'notifyWarning\')"' in index_html
    assert 'onclick="insertScriptSnippet(\'notifyAlert\')"' in index_html
    assert 'onclick="insertScriptSnippet(\'keytext\')"' in index_html
    assert 'onclick="insertScriptSnippet(\'keyTap\')"' in index_html
    assert 'onclick="insertScriptSnippet(\'sleep\')"' in index_html
    assert 'onclick="insertScriptSnippet(\'logger\')"' in index_html
    assert 'onclick="insertScriptSnippet(\'ctrlLayerGet\')"' in index_html
    assert 'onclick="insertScriptSnippet(\'ctrlOutputBt\')"' in index_html
    assert 'onclick="insertScriptSnippet(\'ctrlBtPairing\')"' in index_html
    assert 'onclick="insertScriptSnippet(\'ctrlLedEffect\')"' in index_html
    assert 'class="lighting-btn script-save-btn"' in index_html
    assert 'onclick="runSavedScriptContent()"' in index_html
    assert 'onclick="saveAndRunScriptContent()"' in index_html
    assert "通常実行" in index_html
    assert "保存して実行" in index_html
    assert 'onclick="checkRunScriptContent()"' in index_html
    assert "チェック実行" in index_html
    assert "組み込みコマンド" in index_html
    assert "HIDキーコード" in index_html
    assert 'id="script-hid-key-select"' in index_html
    assert 'id="script-hid-key-code"' in index_html
    assert 'id="script-hid-command-prefix"' in index_html
    assert 'class="script-hid-mod"' in index_html
    assert 'class="script-hid-text-mod"' in index_html
    assert 'id="script-hid-text-input"' in index_html
    assert 'id="script-hid-preview"' in index_html
    assert 'id="script-hid-text-preview"' in index_html
    assert 'insertScriptHidCommand()' in index_html
    assert 'insertScriptHidTextCommand()' in index_html
    assert "OLEDにワーニングメッセージを表示する" in index_html
    assert "OLEDに通常通知メッセージを表示する" in index_html
    assert "OLED表示とjournal記録をまとめて行う" in index_html
    assert "通常通知をOLEDとjournalへ送る" in index_html
    assert "文字列をキーボード入力として送る" in index_html
    assert "HIDキーコードとmodifierを直接tapする" in index_html
    assert "次の処理まで少し待つ" in index_html
    assert "systemd journalにログを残す" in index_html
    assert "logicd control socketからlayer状態を取得する" in index_html
    assert "出力先をBluetoothへ切り替える" in index_html
    assert "Bluetoothペアリング状態を切り替える" in index_html
    assert "LED effectを直接指定する" in index_html
    assert "hidloom-oled warning" in index_html
    assert "hidloom-oled alert" in index_html
    assert "hidloom-notify warning" in index_html
    assert "hidloom-notify alert" in index_html
    assert "hidloom-keytext" in index_html
    assert "hidloom-key tap" in index_html
    assert "sleep 0.2" in index_html
    assert 'logger -t KC_SH "message"' in index_html
    assert "hidloom-ctrl layer get" in index_html
    assert "hidloom-ctrl output bt" in index_html
    assert "hidloom-ctrl bt pairing-toggle" in index_html
    assert "hidloom-ctrl led effect 40 128 175 77 160" in index_html

    assert "SCRIPT_SNIPPETS" in script_js
    assert 'oledWarning: \'hidloom-oled warning "message" 3\\n\'' in script_js
    assert 'oledAlert: \'hidloom-oled alert "message" 2\\n\'' in script_js
    assert 'notifyWarning: \'hidloom-notify warning "message" 3\\n\'' in script_js
    assert 'notifyAlert: \'hidloom-notify alert "message" 2\\n\'' in script_js
    assert 'keytext: \'hidloom-keytext "ABCabc\\\\n"\\n\'' in script_js
    assert 'keyTap: "hidloom-key tap 0x0204\\n"' in script_js
    assert 'sleep: "sleep 0.2\\n"' in script_js
    assert 'logger: \'logger -t KC_SH "message"\\n\'' in script_js
    assert 'ctrlLayerGet: "hidloom-ctrl layer get\\n"' in script_js
    assert 'ctrlOutputBt: "hidloom-ctrl output bt\\n"' in script_js
    assert 'ctrlBtPairing: "hidloom-ctrl bt pairing-toggle\\n"' in script_js
    assert 'ctrlLedEffect: "hidloom-ctrl led effect 40 128 175 77 160\\n"' in script_js
    assert "insertScriptText" in script_js
    assert "selectionStart" in script_js
    assert "window.insertScriptSnippet = insertScriptSnippet" in script_js
    assert "checkRunScriptContent" in script_js
    assert "runSavedScriptContent" in script_js
    assert "saveAndRunScriptContent" in script_js
    assert "confirmDangerousScriptRun" in script_js
    assert "/run" in script_js
    assert "/check-run" in script_js
    assert "window.confirm" in script_js
    assert "httpd 権限で一時実行" in script_js
    assert "チェック実行をキャンセルしました" in script_js
    assert "危険scriptの" in script_js
    assert "window.checkRunScriptContent = checkRunScriptContent" in script_js
    assert "window.runSavedScriptContent = runSavedScriptContent" in script_js
    assert "window.saveAndRunScriptContent = saveAndRunScriptContent" in script_js
    assert "SCRIPT_HID_KEY_OPTIONS" in script_js
    hid_options = _script_hid_options(script_js)
    hid_labels = {label for label, _usage in hid_options}
    hid_usages = {usage for _label, usage in hid_options}
    assert len(hid_labels) == len(hid_options), "duplicate script HID labels"
    assert len(hid_usages) == len(hid_options), "duplicate script HID usages"
    assert "A" in hid_labels
    assert "Caps Lock" in hid_labels
    assert "Num Lock" in hid_labels
    assert "F9" in hid_labels
    assert "F24" in hid_labels
    assert "Execute" in hid_labels
    assert "Language 9" in hid_labels
    assert "ExSel" in hid_labels
    assert 0x9A not in hid_usages
    assert [usage for _label, usage in hid_options] == sorted(hid_usages), "script HID usages must be sorted"

    keycodes = json.loads((ROOT / "config" / "default" / "keycodes.json").read_text(encoding="utf-8"))
    for action in [
        "KC_EXECUTE",
        "KC_HELP",
        "KC_MENU",
        "KC_SELECT",
        "KC_STOP",
        "KC_AGAIN",
        "KC_ALTERNATE_ERASE",
        "KC_CANCEL",
        "KC_CLEAR",
        "KC_PRIOR",
        "KC_SEPARATOR",
        "KC_OUT",
        "KC_OPER",
        "KC_CLEAR_AGAIN",
        "KC_CRSEL",
        "KC_EXSEL",
        "KC_KP_EQUAL_AS400",
        "KC_LANG6",
        "KC_LANG7",
        "KC_LANG8",
        "KC_LANG9",
        "KC_LOCKING_CAPS_LOCK",
        "KC_LOCKING_NUM_LOCK",
        "KC_LOCKING_SCROLL_LOCK",
    ]:
        assert keycodes[action]["hid"] in hid_usages, action
    assert 'scriptHidCommand' in script_js
    assert "scriptHidTextCommand" in script_js
    assert "scriptHidChordText" in script_js
    assert "scriptHidAsciiPair" in script_js
    assert '".script-hid-text-mod"' in script_js
    assert "script-hid-command-prefix" in script_js
    assert "window.insertScriptHidCommand = insertScriptHidCommand" in script_js
    assert "window.insertScriptHidTextCommand = insertScriptHidTextCommand" in script_js

    assert "_scriptSafetyIsDangerous" in scripts_panel_js
    assert "_scriptSafetySummary" in scripts_panel_js
    assert "script.safety.dangerous" in scripts_panel_js
    assert "⚠" in scripts_panel_js
    assert "opt.dataset.dangerous" in scripts_panel_js
    assert "script.safety.confirm_message" in scripts_panel_js
    assert "data.safety && data.safety.dangerous" in scripts_panel_js

    assert ".script-command-tools" in keyboard_css
    assert ".script-command-btn" not in keyboard_css
    assert ".script-command-help summary" in keyboard_css
    assert ".script-command-list" in keyboard_css
    assert ".script-command-list span" in keyboard_css
    assert ".script-save-btn" in keyboard_css
    assert ".script-hid-key-panel" in keyboard_css
    assert ".script-hid-modifiers" in keyboard_css
    assert ".script-hid-prefix" in keyboard_css
    assert ".script-hid-text-field" in keyboard_css
    assert ".script-hid-text-modifiers" in keyboard_css

    print("ok: HTTP script editor helper UI assets")


if __name__ == "__main__":
    main()
