#!/usr/bin/env python3
"""Static checks for HTTP remap popup categories."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMAP_JS = ROOT / "daemon" / "http" / "static" / "remap_panel.js"
REMAP_GROUPS_JS = ROOT / "daemon" / "http" / "static" / "remap_key_groups.js"
EXTRA_GROUPS_JS = ROOT / "daemon" / "http" / "static" / "extra_key_groups.js"
INDEX_HTML = ROOT / "daemon" / "http" / "static" / "index.html"


def main() -> None:
    remap = REMAP_JS.read_text(encoding="utf-8")
    remap_groups = REMAP_GROUPS_JS.read_text(encoding="utf-8")
    extra_groups = EXTRA_GROUPS_JS.read_text(encoding="utf-8")
    remap_all = remap + "\n" + remap_groups + "\n" + extra_groups
    index = INDEX_HTML.read_text(encoding="utf-8")

    expected_tabs = ["pc104", "layer", "mouse", "media", "lighting", "bt", "wifi", "system", "interaction", "script", "other"]
    for tab in expected_tabs:
        assert f'data-tab="{tab}"' in index, f"missing remap tab button: {tab}"
        assert f'id="remap-tab-{tab}"' in index, f"missing remap tab pane: {tab}"

    assert "preferredRemapTabForKeycode" in remap
    assert 'switchRemapTab(preferredRemapTabForKeycode(currentKc))' in remap

    # Current key should open the tab containing its own category.
    assert 'if (/^(MO|TG|TO|DF|OSL)\\(\\d+\\)$/.test(kc)) return "layer";' in remap
    assert 'if (/^LT\\(\\d+,\\s*KC_[A-Z0-9_]+\\)$/.test(kc)) return "layer";' in remap
    assert 'if (/^(QK_LAYER_LOCK|QK_LLCK|DRAG_LOCK)$/.test(kc)) return "interaction";' in remap
    assert 'if (/^BT_/.test(kc)) return "bt";' in remap
    assert 'if (/^WIFI_/.test(kc)) return "wifi";' in remap
    assert 'if (/^KC_SH\\d+$/.test(kc) || /^SCRIPT\\(/.test(kc)) return "script";' in remap
    assert 'if (/^KC_(CONN|CONSOLE|USB|BT|SHUTDOWN)/.test(kc)) return "system";' in remap
    assert "...PC104_EXTRA_KEY_GROUPS.flatMap(g => g.keys)" in remap
    assert "_renderRemapKeyGroups(container, PC104_EXTRA_KEY_GROUPS, { append: true });" in remap

    # Important action groups should be present and discoverable.
    for label in (
        "Layer Tap（短押しで次に選ぶキー、押している間だけ対象レイヤー）",
        "Momentary（押している間だけ対象レイヤー）",
        "Toggle（対象レイヤーをトグル切り替え）",
        "To（対象レイヤーへ移動）",
        "Default（既定レイヤーを変更）",
        "One Shot（次の1キーだけ対象レイヤー）",
        "Wi-Fi Control（既定は再起動で on に戻る一時操作）",
        "日本語IME",
        "言語",
        "特殊",
    ):
        assert label in remap_all, f"missing remap group explanation: {label}"

    for action in (
        "KC_BT",
        "LSFT(LGUI(KC_F23))",
        "Copilot",
        "LT(${_pendingLayerTap.layer},${keycode})",
        "BT_STATUS",
        "BT_POWER_TOGGLE",
        "BT_PAIRING_TOGGLE",
        "BT_DISCONNECT",
        "WIFI_STATUS",
        "WIFI_POWER_ON",
        "WIFI_POWER_OFF",
        "WIFI_POWER_TOGGLE",
        "KC_CONNAUTO",
        "KC_CONSOLE",
        "KC_USB",
        "RGB_TOG",
        "RM_TOGG",
        "MS_BTN1",
        "MS_BTN5",
        "MS_ACL0",
        "MS_ACL2",
        "KC_MS_U",
        "MS_WHLR",
        "KC_MPLY",
        "KC_SH10",
        "CAPS_WORD",
        "REPEAT_KEY",
        "ALT_REPEAT_KEY",
        "QK_LAYER_LOCK",
        "QK_LLCK",
        "DRAG_LOCK",
        "KC_HENKAN",
        "KC_MUHENKAN",
        "KC_HENK",
        "KC_MHEN",
        "KC_ZKHK",
        "KC_LANG1",
        "KC_LANG5",
    ):
        assert action in remap_all, f"missing remap category action: {action}"

    # KC_BT is in the Output group, while BT_* controls are in the BT group.
    assert 'keys: ["KC_CONNAUTO","KC_CONSOLE","KC_USB","KC_BT"]' in remap_groups
    assert 'keys: ["LSFT(LGUI(KC_F23))"]' in remap_groups
    assert 'keys: ["KC_BTN1","KC_BTN2","KC_BTN3","KC_BTN4","KC_BTN5","MS_BTN1","MS_BTN2","MS_BTN3","MS_BTN4","MS_BTN5"]' in remap_groups
    assert 'keys: ["MS_ACL0","MS_ACL1","MS_ACL2"]' in remap_groups
    assert 'keys: ["CAPS_WORD","REPEAT_KEY","ALT_REPEAT_KEY","QK_LAYER_LOCK","QK_LLCK","DRAG_LOCK"]' in remap_groups
    assert 'keys: ["KC_BT"]' in remap_groups
    assert 'keys: ["BT_STATUS","BT_POWER_ON","BT_POWER_OFF","BT_POWER_TOGGLE"' in remap_groups
    assert 'keys: ["WIFI_STATUS","WIFI_POWER_ON","WIFI_POWER_OFF","WIFI_POWER_TOGGLE"]' in remap_groups
    assert 'const PC104_EXTRA_KEY_GROUPS = [' in remap_groups
    pc104_extra_start = remap_groups.index("const PC104_EXTRA_KEY_GROUPS = [")
    pc104_extra_end = remap_groups.index("];", pc104_extra_start)
    pc104_extra_block = remap_groups[pc104_extra_start:pc104_extra_end]
    assert pc104_extra_block.index('label: "日本語IME"') < pc104_extra_block.index('label: "言語"')
    assert pc104_extra_block.index('label: "言語"') < pc104_extra_block.index("...SPECIAL_KEY_GROUPS")
    assert 'keys: ["KC_ZKHK","KC_RO","KC_KANA","KC_JYEN","KC_HENKAN","KC_MUHENKAN","KC_HENK","KC_MHEN"]' in remap_groups
    assert 'keys: ["KC_LANG1","KC_LANG2","KC_LANG3","KC_LANG4","KC_LANG5"]' in remap_groups
    other_start = remap_groups.index("const OTHER_KEY_GROUPS = [")
    other_end = remap_groups.index("];", other_start)
    other_block = remap_groups[other_start:other_end]
    assert "KC_HENKAN" not in other_block
    assert "KC_HENK" not in other_block
    assert "KC_LANG1" not in other_block
    assert "function _cqaPatchWifiPowerOffWarning()" in extra_groups
    assert 'keycode === "WIFI_POWER_OFF"' in extra_groups
    assert "SSH / HTTP UI 接続を切る可能性" in extra_groups

    labels = json.loads((ROOT / "config" / "default" / "key_labels.json").read_text(encoding="utf-8"))
    assert labels["MS_BTN1"] == labels["KC_BTN1"] == "Btn1"
    assert labels["MS_BTN5"] == labels["KC_BTN5"] == "Btn5"
    assert labels["MS_ACL0"] == "Mouse\nSlow"
    assert labels["KC_HENK"] == labels["KC_HENKAN"] == "変換"
    assert labels["KC_MHEN"] == labels["KC_MUHENKAN"] == "無変換"
    assert labels["MS_ACL1"] == "Mouse\nMed"
    assert labels["MS_ACL2"] == "Mouse\nFast"
    assert labels["KC_ZKHK"] == "全/半"
    assert labels["KC_ZENKAKU_HANKAKU"] == "全/半"

    print("ok: HTTP remap categories")


if __name__ == "__main__":
    main()
