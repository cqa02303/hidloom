#!/usr/bin/env python3
"""Regression checks for current status / TODO freshness."""
from __future__ import annotations

from pathlib import Path
import json


ROOT = Path(__file__).resolve().parents[1]


def _require_all(text: str, phrases: list[str]) -> None:
    for phrase in phrases:
        assert phrase in text, phrase


def _reject_all(text: str, phrases: list[str]) -> None:
    for phrase in phrases:
        assert phrase not in text, phrase


def main() -> None:
    if not (ROOT / "docs" / "CURRENT_STATUS.md").is_file():
        print("ok: private current-status documentation is not shipped in the public source tree")
        return

    docs = ROOT / "docs"
    current = (docs / "CURRENT_STATUS.md").read_text(encoding="utf-8")
    current_archive = (docs / "archive" / "CURRENT_STATUS_2026_06_08.md").read_text(
        encoding="utf-8"
    )
    archive_readme = (docs / "archive" / "README.md").read_text(encoding="utf-8")
    docs_readme = (docs / "README.md").read_text(encoding="utf-8")
    todo = (docs / "TODO_PRIORITY.md").read_text(encoding="utf-8")
    checklist = (docs / "ops" / "real-device-test-checklist.md").read_text(encoding="utf-8")
    wishlist = (docs / "WISHLIST.md").read_text(encoding="utf-8")
    design_todo = (docs / "feature" / "design-todo-backlog.md").read_text(encoding="utf-8")
    board_profiles = (docs / "hardware" / "board-profiles.md").read_text(encoding="utf-8")
    touch_panel_flick_input_design = (
        docs / "input" / "touch-panel-flick-input-design.md"
    ).read_text(encoding="utf-8")
    config = json.loads((ROOT / "config" / "default" / "config.json").read_text(encoding="utf-8"))

    _require_all(
        current,
        [
            "更新日: 2026-06-27",
            "## 2026-06-27 update",
            "## 2026-06-25 update",
            "## 2026-06-23 update",
            "## 2026-06-22 update",
            "ops/release-packaging-runbook.md",
            "make release-candidate-check",
            "make release-prerelease-plan",
            "make release-prerelease-publish",
            "make release-download-verify RELEASE_TAG=v0.0.1746+git74f764e",
            "make release-stable-check RELEASE_TAG=v0.0.1746+git74f764e",
            "gh release create --prerelease",
            "v0.0.1729+gitf4ee944",
            "absolute path",
            "superseded",
            "v0.0.1731+gitc59e9e0",
            "v0.0.1735+git8176d3a",
            "v0.0.1738+git2546367",
            "portable sha256",
            "publish 後の自動 download verify",
            "isPrerelease=false",
            "isDraft=false",
            "hidloom-usb-gadget-fast",
            "v0.0.1746+git74f764e",
            "<keyboard-host>` install / `make deb-verify-smoke-01",
            "<keyboard-host>` install / `make deb-verify-smoke-02",
            "現行 stable release `v0.0.1746+git74f764e`",
            "hidd `write_errors=0` / `dropped_reports=0`",
            "local candidate / prerelease / stable release",
            "release note draft",
            "keycode/action-routing-matrix.md",
            "keycode/action-inventory.md",
            "keycode/action-patterns.md",
            "native-output-routing-uidd-design.md",
            "`LOGICD_NATIVE_OUTPUTD_CTRL=1`",
            "`frames_to_uinput=4`",
            "このファイルは、作業開始時に現在地だけを短く確認する入口です。",
            "[archive/CURRENT_STATUS_2026_06_08.md](archive/CURRENT_STATUS_2026_06_08.md)",
            "[TODO_PRIORITY.md](TODO_PRIORITY.md)",
            "[ops/real-device-test-checklist.md](ops/real-device-test-checklist.md)",
            "`hidloom-hidd` native HID report broker M0 は実装済み",
            "## 現在の構成",
            "BLE HID keyboard / mouse",
            "## 直近の要点",
            "USB report broker",
            "`hidloom-hidd` M0",
            "[daemon/specs/hidd/m0-implementation-spec.md](daemon/specs/hidd/m0-implementation-spec.md)",
            "Mouse report scheduler",
            "Windows JIS / US split keyboard",
            "Bluetooth host metadata",
            "Unicode / Send String",
            "OLED / analog stick",
            "Package / release tooling",
            "Keycode action routing inventory",
            "active broker owner (`hidloom-hidd`、legacy rollback では `usbd`) の outlet 側で `kind=mouse`",
            "jis_special_us_default",
            "auto BT は `btd`",
            "auto uinput は mouse backend 未実装のため drop",
            "## 進行中の判断",
            "古い作業ログ",
            "## 主要な参照先",
            "[daemon/specs/hidd/usb-gadget-multi-report-plan.md](daemon/specs/hidd/usb-gadget-multi-report-plan.md)",
            "[input/windows-us-custom-hid-ime-routing-design.md](input/windows-us-custom-hid-ime-routing-design.md)",
            "[research/windows-jis-keyboard-vid-pid.md](research/windows-jis-keyboard-vid-pid.md)",
            "[review/design-gap-goals-2026-06-10.md](review/design-gap-goals-2026-06-10.md)",
            "[hardware/board-profiles.md](hardware/board-profiles.md)",
            "[keycode/unimplemented-keycodes.md](keycode/unimplemented-keycodes.md)",
            "[input/touch-panel-flick-input-design.md](input/touch-panel-flick-input-design.md)",
            "[ops/performance-tuning-plan.md](ops/performance-tuning-plan.md)",
            "[ops/release-packaging-runbook.md](ops/release-packaging-runbook.md)",
            "[keycode/action-routing-matrix.md](keycode/action-routing-matrix.md)",
            "[keycode/action-inventory.md](keycode/action-inventory.md)",
            "[keycode/action-patterns.md](keycode/action-patterns.md)",
            "[ops/test-script-inventory.md](ops/test-script-inventory.md)",
            "## 確認コマンド",
        ],
    )
    _reject_all(
        current,
        [
            "2026-06-04 の作業前提",
            "Remote-only design cleanup continued",
            "Bluetooth host rename / per-host forget design is fixed",
            "QMK alias completion has a first runtime slice",
            "`<keyboard-host>` の kiosk Chromium 実 DOM",
        ],
    )

    _require_all(
        current_archive,
        [
            "# Current Status Archive 2026-06-08",
            "[../CURRENT_STATUS.md](../CURRENT_STATUS.md)",
            "Bluetooth host rename / per-host forget design is fixed",
            "Remote-only design cleanup continued",
            "QMK alias completion has a first runtime slice",
            "Key Override runtime suppression first slice is now implemented",
        ],
    )
    assert "CURRENT_STATUS_2026_06_08.md" in archive_readme

    _require_all(
        docs_readme,
        [
            "[CURRENT_STATUS.md](CURRENT_STATUS.md)",
            "[TODO_PRIORITY.md](TODO_PRIORITY.md)",
            "[ops/real-device-test-checklist.md](ops/real-device-test-checklist.md)",
            "[archive/](archive/)",
        ],
    )

    _require_all(
        todo,
        [
            "[archive/TODO_PRIORITY_2026_06_06.md](archive/TODO_PRIORITY_2026_06_06.md)",
            "Unicode / Send String real runner",
            "Bluetooth paired-host event source / last-connected writer",
            "Windows IME helperless standard HID route policy",
            "Windows JIS main + US sub split keyboard",
            "`jis_special_us_default` runtime routing",
            "usbd USB report broker",
            "Mouse report scheduler / stick-SPID convergence",
            "Persistent Wi-Fi off implementation decision",
            "Bluetooth host rename / per-host forget runtime",
            "HTTP analog stick calibration 2D map",
            "OLED freeze recovery / I2C diagnostics",
            "Dynamic Macro / Leader groundwork",
            "python3 script/test_current_todo_completion.py",
            "native owner の `KC_CONSOLE` / `KC_USB` / `KC_CONNAUTO` 復旧",
            "architecture/native-output-routing-uidd-design.md",
            "package unit migration / checkout retirement documentation",
            "keycode action routing / output behavior inventory",
            "script/test_keycode_action_inventory.py",
            "script/test_release_bundle_tools.py",
        ],
    )
    _reject_all(
        todo,
        [
            "Morse builder / feedback final smoke",
            "LED role preview real-LED route / UI: 2026-05-30",
            "QMK Canonical Alias Follow-up",
            "Conditional Layers Browser DOM Follow-up",
        ],
    )

    _require_all(
        design_todo,
        [
            "# Design TODO backlog",
            "### Persistent Wi-Fi off setting design",
            "### Bluetooth host last connected timestamp design",
            "### Caps Word feedback / status design",
            "### Power management preset implementation readiness",
            "local rename metadata route",
        ],
    )

    _require_all(
        checklist,
        [
            "2026-06-10",
            "HTTP analog stick calibration 2D map",
            "OLED freeze recovery / I2C diagnostics",
            "LED role preview",
            "OLED connectivity icon row",
            "`/ws` CSRF 403",
            "Wi-Fi recovery-first power control",
        ],
    )

    _require_all(
        wishlist,
        [
            "更新日: 2026-07-10",
            "VIA app 互換入口",
            "HTTP analog stick calibration 2D map",
            "Bluetooth host local rename metadata first slice",
            "OLED freeze recovery / I2C diagnostics",
            "Unicode / Send String",
            "keycode action routing / output behavior inventory",
            "release packaging / package unit migration runbook",
        ],
    )
    _reject_all(
        wishlist,
        [
            "| W1 | Interaction GUI editor / advanced timing",
            "| W1 | Keymap editor search / filter",
        ],
    )

    _require_all(
        board_profiles,
        [
            "# Board profiles",
            "/mnt/p3/board_profile.json",
            "--reset-runtime-keymap",
        ],
    )
    _require_all(
        touch_panel_flick_input_design,
        [
            "# Touch Panel Flick Input Design",
            "`osoyoo-4.3`",
            "800x480",
            "12-key phone-style pad",
            "host IME / layout",
            "`POST /api/touch-panel/flick/dispatch`",
        ],
    )

    interaction = config["settings"]["interaction"]
    assert interaction["combos"] == []
    assert interaction["tap_dances"] == {}
    assert interaction["key_overrides"] == []
    assert config["settings"]["http_basic_auth"]["password"] == "__HOSTNAME__"

    print("ok: current status and TODO documents are fresh")


if __name__ == "__main__":
    main()
