#!/usr/bin/env python3
"""Freshness checks for docs reorganization state."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    if end == -1:
        return text[start:]
    return text[start:end]


def markdown_table_rows(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or all(set(cell) <= {"-", ":"} for cell in cells):
            continue
        rows.append(cells)
    return rows


def markdown_links(text: str) -> list[str]:
    return re.findall(r"\]\(([^)]+)\)", text)


def documented_category_dirs(policy: str) -> set[str]:
    dirs: set[str] = set()
    for cells in markdown_table_rows(section(policy, "## 配置カテゴリ")):
        if cells[0] == "配置":
            continue
        match = re.fullmatch(r"`docs/([^/<]+)/`", cells[0])
        if match:
            dirs.add(match.group(1))
    dirs.discard("archive")
    return dirs


def bullet_links_under_label(text: str, label: str) -> list[str]:
    lines = text.splitlines()
    try:
        start = lines.index(label)
    except ValueError as exc:
        raise AssertionError(f"missing label: {label}") from exc
    links: list[str] = []
    for line in lines[start + 1 :]:
        if not line.strip():
            if links:
                break
            continue
        if not line.startswith("- "):
            if links:
                break
            continue
        links.extend(markdown_links(line))
    return links


def main() -> None:
    docs = ROOT / "docs"
    if not (docs / "CURRENT_STATUS.md").is_file():
        print("ok: private documentation reorganization state is not shipped in the public source tree")
        return

    reorg = (docs / "REORG_PROGRESS.md").read_text(encoding="utf-8")
    readme = (docs / "README.md").read_text(encoding="utf-8")
    current_status = (docs / "CURRENT_STATUS.md").read_text(encoding="utf-8")
    policy = (docs / "policy" / "documentation-policy.md").read_text(encoding="utf-8")
    reorg_summary = (docs / "ops" / "docs-reorg-review-summary.md").read_text(encoding="utf-8")
    wishlist = (docs / "WISHLIST.md").read_text(encoding="utf-8")
    todo = (docs / "TODO_PRIORITY.md").read_text(encoding="utf-8")

    allowed_root_docs = {
        "CURRENT_STATUS.md",
        "README.md",
        "REORG_PROGRESS.md",
        "TODO_PRIORITY.md",
        "WISHLIST.md",
    }
    root_docs = {path.name for path in docs.glob("*.md")}
    assert root_docs == allowed_root_docs, (
        f"unexpected root docs: extra={sorted(root_docs - allowed_root_docs)}, "
        f"missing={sorted(allowed_root_docs - root_docs)}"
    )
    assert "## root に残す文書" in policy
    for root_name in sorted(allowed_root_docs):
        assert f"`{root_name}`" in policy, f"documentation policy should explain {root_name}"
    for policy_phrase in [
        "実ファイル一覧と一致",
        "カテゴリ外の文書は混ぜない",
        "`まず見る文書` のカテゴリ内リンク",
        "`文書一覧` と実ファイル一覧の完全一致",
    ]:
        assert policy_phrase in policy, f"documentation policy should mention: {policy_phrase}"

    category_dirs = {
        "architecture",
        "bluetooth",
        "connectivity",
        "daemon",
        "feature",
        "gallery",
        "hardware",
        "hid",
        "input",
        "interaction",
        "keycode",
        "lighting",
        "macro",
        "man",
        "midi",
        "morse",
        "ops",
        "policy",
        "research",
        "review",
        "vial",
    }
    discovered_category_dirs = {
        path.name
        for path in docs.iterdir()
        if path.is_dir()
        and path.name != "archive"
        and any(child.suffix == ".md" for child in path.iterdir())
    }
    assert discovered_category_dirs == category_dirs, (
        "docs/README.md, docs reorg summary, and category tests should be updated "
        f"when categories change: extra={sorted(discovered_category_dirs - category_dirs)}, "
        f"missing={sorted(category_dirs - discovered_category_dirs)}"
    )
    policy_category_dirs = documented_category_dirs(policy)
    assert policy_category_dirs == category_dirs, (
        "documentation policy placement table should match category dirs exactly: "
        f"extra={sorted(policy_category_dirs - category_dirs)}, "
        f"missing={sorted(category_dirs - policy_category_dirs)}"
    )
    readme_category_links = set(
        re.findall(r"\]\(([^)]+/README\.md)\)", section(readme, "## 分類別入口"))
    )
    expected_readme_category_links = {f"{dirname}/README.md" for dirname in category_dirs}
    assert readme_category_links == expected_readme_category_links, (
        "docs/README.md category table should match category dirs exactly: "
        f"extra={sorted(readme_category_links - expected_readme_category_links)}, "
        f"missing={sorted(expected_readme_category_links - readme_category_links)}"
    )
    summary_rows = {
        cells[0]: cells
        for cells in markdown_table_rows(section(reorg_summary, "## カテゴリ分布"))
        if cells[0] != "カテゴリ"
    }
    assert set(summary_rows) == category_dirs, (
        "docs reorg summary category table should match category dirs exactly: "
        f"extra={sorted(set(summary_rows) - category_dirs)}, "
        f"missing={sorted(category_dirs - set(summary_rows))}"
    )
    for dirname in sorted(category_dirs):
        category_readme = docs / dirname / "README.md"
        assert category_readme.exists(), f"{dirname}/README.md should exist as category entrypoint"
        category_text = category_readme.read_text(encoding="utf-8")
        assert "まず見る文書:" in category_text, f"{dirname}/README.md should list entry documents"
        assert "文書一覧:" in category_text, f"{dirname}/README.md should list all documents"
        assert f"{dirname}/README.md" in readme, f"docs/README.md should link {dirname}/README.md"
        category_doc_names = {
            doc_path.name
            for doc_path in (docs / dirname).glob("*.md")
            if doc_path.name != "README.md"
        }
        category_doc_count = len(
            [
                doc_path
                for doc_path in (docs / dirname).glob("*.md")
                if doc_path.name != "README.md"
            ]
        )
        document_list_links = set(bullet_links_under_label(category_text, "文書一覧:"))
        assert document_list_links == category_doc_names, (
            f"{dirname}/README.md 文書一覧 should match category docs exactly: "
            f"extra={sorted(document_list_links - category_doc_names)}, "
            f"missing={sorted(category_doc_names - document_list_links)}"
        )
        entry_links = {
            link
            for link in bullet_links_under_label(category_text, "まず見る文書:")
            if link.endswith(".md")
        }
        assert entry_links <= category_doc_names, (
            f"{dirname}/README.md まず見る文書 should only link category docs: "
            f"extra={sorted(entry_links - category_doc_names)}"
        )
        assert f"| {dirname} | {category_doc_count} |" in reorg_summary, (
            f"docs reorg summary should list {dirname} count={category_doc_count}"
        )
        assert int(summary_rows[dirname][1]) == category_doc_count, (
            f"docs reorg summary should list {dirname} count={category_doc_count}"
        )
        if dirname == "ops":
            assert "| ops |" in reorg_summary and "[ops/README.md](README.md)" in reorg_summary
            assert "](README.md)" in summary_rows[dirname][2]
        else:
            assert f"[{dirname}/README.md](../{dirname}/README.md)" in reorg_summary, (
                f"docs reorg summary should link {dirname}/README.md"
            )
            assert f"](../{dirname}/README.md)" in summary_rows[dirname][2]
        for doc_path in sorted((docs / dirname).glob("*.md")):
            if doc_path.name == "README.md":
                continue
            assert f"]({doc_path.name})" in category_text, (
                f"{dirname}/README.md should link {doc_path.name}"
            )

    research_doc = docs / "research" / "windows-split-keyboard-identity.md"
    assert research_doc.exists(), "Windows split keyboard identity research should live under docs/research/"
    vialrgb_research_doc = docs / "research" / "vialrgb-upstream.md"
    assert vialrgb_research_doc.exists(), "VialRGB upstream research should live under docs/research/"
    assert not (docs / "progress").exists(), "Completed progress logs should not remain an active category"
    archived_progress = docs / "archive" / "progress"
    remote_first_slices = archived_progress / "remote-only-first-slices-2026-06-01.md"
    assert remote_first_slices.exists(), "Remote-only first slices should live under docs/archive/progress/"
    todo_audit = archived_progress / "todo-wishlist-implementation-audit-2026-06-01.md"
    assert todo_audit.exists(), "TODO / Wishlist audit should live under docs/archive/progress/"
    for progress_name in [
        "remote-only-followup-2026-05-28.md",
        "remote-only-todo-2026-05-29.md",
        "morse-web-ui-status-2026-05-29.md",
        "led-role-preview-route-progress.md",
    ]:
        assert (archived_progress / progress_name).exists(), f"{progress_name} should live under docs/archive/progress/"
    archived_bugs = docs / "archive" / "bugs"
    assert not (docs / "bugs").exists(), "Completed bug records should not remain an active category"
    assert (archived_bugs / "2026-06-08-vial-board-profile-and-mouse-button-drag.md").exists()
    archived_review = docs / "archive" / "review"
    for review_name in [
        "cross-daemon-review-2026-05-30.md",
        "logicd-matrix-input-path-review-2026-06-02.md",
        "fresh-install-review.md",
        "mcp-codex-extension-retrospective.md",
        "performance-dataflow-review-2026-06-10.md",
    ]:
        assert (archived_review / review_name).exists(), f"{review_name} should live under docs/archive/review/"

    for text in (readme, policy):
        assert "REORG_PROGRESS.md" in text

    assert "docs reorganization progress" in reorg
    assert "root 直下を入口系 13 文書" not in reorg
    assert "docs 整理は root 5 文書とカテゴリ README まで到達済み" in current_status
    assert "ops/docs-reorg-review-summary.md" in current_status
    assert "docs 整理の移動履歴、完了判定、検査入口" in current_status
    assert "docs 整理の移動履歴、完了判定、検査入口" in policy
    assert "文書一覧` は同階層の `.md` 全文書と完全一致" in reorg_summary
    assert "`まず見る文書` は同カテゴリ内の代表文書" in reorg_summary
    assert "docs/research/" in reorg
    assert "architecture/system-overview.md" in readme
    assert "policy/documentation-policy.md" in readme
    for architecture_name in [
        "system-overview.md",
        "specification.md",
        "module-structure.md",
        "single-source-architecture.md",
    ]:
        assert (docs / "architecture" / architecture_name).exists(), (
            f"{architecture_name} should live under docs/architecture/"
        )
    for policy_name in [
        "decisions-spec.md",
        "documentation-policy.md",
        "logging-status-policy.md",
    ]:
        assert (docs / "policy" / policy_name).exists(), (
            f"{policy_name} should live under docs/policy/"
        )
    for matrixd_name in [
        "stability-docs.md",
        "logicd-stability-status-2026-06-02.md",
        "scan-stability-plan.md",
        "variable-scan-debounce-note.md",
        "runtime-priority-ideal.md",
        "scan-stability-progress-2026-06-02.md",
        "real-device-stability-checklist.md",
        "scanner-abstraction-design.md",
        "input-latency-instrumentation-design.md",
    ]:
        assert (docs / "daemon" / "specs" / "matrixd" / matrixd_name).exists(), (
            f"{matrixd_name} should live under docs/daemon/specs/matrixd/"
        )
    for unit_path in sorted((ROOT / "system" / "systemd").glob("*.service")):
        unit_text = unit_path.read_text(encoding="utf-8")
        for rel_path in re.findall(
            r"^Documentation=file://@HIDLOOM_REPO_ROOT@/([^ \n]+)",
            unit_text,
            flags=re.MULTILINE,
        ):
            assert (ROOT / rel_path).exists(), (
                f"{unit_path.relative_to(ROOT)} Documentation path should exist: {rel_path}"
            )
    for hardware_name in [
        "board-profiles.md",
        "charlieplex-specification.md",
        "complete-matrix-coordinates.md",
        "keyswitch-matrix-map.md",
        "touch-panel-vial-layout-notes.md",
        "hardware-ports-buzzer-ir-design.md",
        "paw3805ek-mounted-cursor-settings-design.md",
    ]:
        assert (docs / "hardware" / hardware_name).exists(), f"{hardware_name} should live under docs/hardware/"
    for bluetooth_name in [
        "ble-gatt-hid-spec.md",
        "implementation-plan.md",
        "hid-backend-plan.md",
        "host-led-output-report-design.md",
        "host-last-connected-design.md",
        "host-rename-forget-design.md",
        "multi-host-ui-design.md",
        "consumer-control-gatt-opt-in-design.md",
    ]:
        assert (docs / "bluetooth" / bluetooth_name).exists(), f"{bluetooth_name} should live under docs/bluetooth/"
    for lighting_name in [
        "auto-role-inspector-design.md",
        "led-life-game-effect.md",
        "led-long-run-metrics.md",
        "led-role-editor-plan.md",
        "led-role-preset-sharing-design.md",
        "led-role-semantic-override-design.md",
        "led-semantic-roles.md",
        "lighting-key-alias-compatibility-design.md",
        "oled-connectivity-icon-row.md",
        "vialrgb-protocol.md",
    ]:
        assert (docs / "lighting" / lighting_name).exists(), f"{lighting_name} should live under docs/lighting/"
    assert "docs/lighting/" in policy
    for daemon_name in [
        "logicd-output-router.md",
        "logicd-log-output.md",
        "logicd-resolved-action-handler-split-design.md",
        "kc-sh-report-output-route-design.md",
    ]:
        assert (docs / "daemon" / daemon_name).exists(), f"{daemon_name} should live under docs/daemon/"
    assert "docs/daemon/" in policy
    for feature_name in [
        "design-todo-backlog.md",
        "caps-word-design.md",
        "repeat-key-design.md",
        "conditional-layers-design.md",
        "interaction-inspector-design.md",
        "sticky-state-status-design.md",
        "layer-lock-design.md",
        "key-toggle-lock-design.md",
        "mod-morph-grave-escape-design.md",
        "host-profile-design.md",
        "power-management-preset-design.md",
        "sequence-engine-design.md",
    ]:
        assert (docs / "feature" / feature_name).exists(), f"{feature_name} should live under docs/feature/"
    assert "docs/feature/" in policy
    for macro_name in [
        "compatibility-plan.md",
        "kml-qmk-macro-keycode-design.md",
        "vial-advanced-macro-compatibility-design.md",
        "dynamic-macro-leader-design.md",
    ]:
        assert (docs / "macro" / macro_name).exists(), f"{macro_name} should live under docs/macro/"
    assert "docs/macro/" in policy
    for midi_name in [
        "audio-output-design.md",
        "sequencer-audio-integration-design.md",
    ]:
        assert (docs / "midi" / midi_name).exists(), f"{midi_name} should live under docs/midi/"
    assert "docs/midi/" in policy
    for hid_name in [
        "mouse-hid-extension-design.md",
        "system-control-programmable-hid-report-design.md",
        "digitizer-haptic-steno-feature-design.md",
    ]:
        assert (docs / "hid" / hid_name).exists(), f"{hid_name} should live under docs/hid/"
    assert "docs/hid/" in policy
    for keycode_name in [
        "basic-hid-keycode-completion-design.md",
        "layer-oneshot-completion-design.md",
        "qmk-alias-completion-design.md",
        "magic-key-translation-design.md",
        "key-override-runtime-suppression-design.md",
        "boot-debug-eeprom-action-mapping-design.md",
        "qmk-vial-keycode-support.md",
        "unimplemented-keycodes.md",
        "expansion-plan.md",
        "http-remap-keycode-ui.md",
        "action-validation-unification-plan.md",
    ]:
        assert (docs / "keycode" / keycode_name).exists(), f"{keycode_name} should live under docs/keycode/"
    assert "docs/keycode/" in policy
    for input_name in [
        "unicode-send-string-safety-design.md",
        "autocorrect-safety-design.md",
        "touch-panel-flick-input-design.md",
    ]:
        assert (docs / "input" / input_name).exists(), f"{input_name} should live under docs/input/"
    assert "docs/input/" in policy
    for connectivity_name in [
        "wifi-persistent-off-design.md",
        "usb-host-identity-keymap-hot-swap-design.md",
    ]:
        assert (docs / "connectivity" / connectivity_name).exists(), (
            f"{connectivity_name} should live under docs/connectivity/"
        )
    assert "docs/connectivity/" in policy
    for morse_name in [
        "behavior-current.md",
        "behavior-plan.md",
        "http-route-status.md",
    ]:
        assert (docs / "morse" / morse_name).exists(), f"{morse_name} should live under docs/morse/"
    assert "docs/morse/" in policy
    for vial_name in [
        "implementation-plan.md",
        "vil-import-policy.md",
    ]:
        assert (docs / "vial" / vial_name).exists(), f"{vial_name} should live under docs/vial/"
    assert "docs/vial/" in policy
    for ops_name in [
        "workflow-runbook.md",
        "real-device-test-checklist.md",
        "test-script-inventory.md",
        "performance-tuning-plan.md",
        "script-safety-metadata.md",
        "kc-sh-hid-text-cat-smoke.md",
        "docs-reorg-review-summary.md",
    ]:
        assert (docs / "ops" / ops_name).exists(), f"{ops_name} should live under docs/ops/"
    assert "docs/ops/" in policy
    for interaction_name in [
        "builder-ux.md",
        "ui-plan.md",
    ]:
        assert (docs / "interaction" / interaction_name).exists(), (
            f"{interaction_name} should live under docs/interaction/"
        )
    assert "docs/interaction/" in policy
    assert "research/windows-split-keyboard-identity.md" in wishlist
    assert "Vial serial suffix smoke" in todo

    active_docs = "\n".join(
        path.read_text(encoding="utf-8")
        for path in docs.rglob("*.md")
        if "archive" not in path.relative_to(docs).parts
    )
    assert "JP_KEYBOARD_IDENTITY_RESEARCH.md" not in active_docs
    assert "VIALRGB_UPSTREAM_RESEARCH.md" not in active_docs
    assert "REMOTE_ONLY_FIRST_SLICES_2026_06_01.md" not in active_docs
    assert "TODO_WISHLIST_IMPLEMENTATION_AUDIT_2026_06_01.md" not in active_docs
    assert "REMOTE_ONLY_FOLLOWUP_2026_05_28.md" not in active_docs
    assert "REMOTE_ONLY_TODO_2026_05_29.md" not in active_docs
    assert "MORSE_WEB_UI_STATUS_2026_05_29.md" not in active_docs
    assert "LED_ROLE_PREVIEW_ROUTE_PROGRESS.md" not in active_docs
    assert "CROSS_DAEMON_REVIEW_2026_05_30.md" not in active_docs
    assert "LOGICD_MATRIX_INPUT_PATH_REVIEW_2026_06_02.md" not in active_docs
    assert "FRESH_INSTALL_REVIEW.md" not in active_docs
    assert "MATRIXD_STABILITY_DOCS.md" not in active_docs
    assert "MATRIXD_LOGICD_STABILITY_STATUS_2026_06_02.md" not in active_docs
    assert "MATRIXD_SCAN_STABILITY_PLAN.md" not in active_docs
    assert "MATRIXD_VARIABLE_SCAN_DEBOUNCE_NOTE.md" not in active_docs
    assert "MATRIXD_RUNTIME_PRIORITY_IDEAL.md" not in active_docs
    assert "MATRIXD_SCAN_STABILITY_PROGRESS_2026_06_02.md" not in active_docs
    assert "MATRIXD_REAL_DEVICE_STABILITY_CHECKLIST.md" not in active_docs
    assert "MATRIXD_SCANNER_ABSTRACTION_DESIGN.md" not in active_docs
    assert "MATRIX_INPUT_LATENCY_INSTRUMENTATION_DESIGN.md" not in active_docs
    assert "BOARD_PROFILES.md" not in active_docs
    assert "CHARLIEPLEX_SPECIFICATION.md" not in active_docs
    assert "COMPLETE_MATRIX_COORDINATES.md" not in active_docs
    assert "KEYSWITCH_MATRIX_MAP.md" not in active_docs
    assert "SPID_MOUSE_SENSOR_PLAN.md" not in active_docs
    assert "TOUCH_PANEL_VIAL_LAYOUT_NOTES.md" not in active_docs
    assert "HARDWARE_PORTS_BUZZER_IR_DESIGN.md" not in active_docs
    assert "PAW3805EK_MOUNTED_CURSOR_SETTINGS_DESIGN.md" not in active_docs
    assert "BTD_PROTOCOL.md" not in active_docs
    assert "BLE_GATT_HID_SPEC.md" not in active_docs
    assert "BLUETOOTH_IMPLEMENTATION_PLAN.md" not in active_docs
    assert "BLUETOOTH_HID_BACKEND_PLAN.md" not in active_docs
    assert "BLE_HOST_LED_OUTPUT_REPORT_DESIGN.md" not in active_docs
    assert "BT_HOST_LAST_CONNECTED_DESIGN.md" not in active_docs
    assert "BLUETOOTH_HOST_RENAME_FORGET_DESIGN.md" not in active_docs
    assert "BLUETOOTH_MULTI_HOST_UI_DESIGN.md" not in active_docs
    assert "CONSUMER_CONTROL_GATT_OPT_IN_DESIGN.md" not in active_docs
    assert "AUTO_ROLE_INSPECTOR_DESIGN.md" not in active_docs
    assert "LEDD_DIRECT_FRAME_SOCKET_PLAN.md" not in active_docs
    assert "LEDD_DIRECT_FRAME_FALLBACK.md" not in active_docs
    assert "LED_LIFE_GAME_EFFECT.md" not in active_docs
    assert "LED_LONG_RUN_METRICS.md" not in active_docs
    assert "LED_ROLE_EDITOR_PLAN.md" not in active_docs
    assert "LED_ROLE_PRESET_SHARING_DESIGN.md" not in active_docs
    assert "LED_ROLE_SEMANTIC_OVERRIDE_DESIGN.md" not in active_docs
    assert "LED_SEMANTIC_ROLES.md" not in active_docs
    assert "LIGHTING_KEY_ALIAS_COMPATIBILITY_DESIGN.md" not in active_docs
    assert "OLED_CONNECTIVITY_ICON_ROW.md" not in active_docs
    assert "VIALRGB_PROTOCOL.md" not in active_docs
    assert "LOGICD_RESOLVED_ACTION_HANDLER_SPLIT_DESIGN.md" not in active_docs
    assert "KC_SH_REPORT_OUTPUT_ROUTE_DESIGN.md" not in active_docs
    assert "CAPS_WORD_DESIGN.md" not in active_docs
    assert "REPEAT_KEY_DESIGN.md" not in active_docs
    assert "CONDITIONAL_LAYERS_DESIGN.md" not in active_docs
    assert "INTERACTION_INSPECTOR_DESIGN.md" not in active_docs
    assert "STICKY_STATE_STATUS_DESIGN.md" not in active_docs
    assert "LAYER_LOCK_DESIGN.md" not in active_docs
    assert "KEY_TOGGLE_LOCK_DESIGN.md" not in active_docs
    assert "MOD_MORPH_GRAVE_ESCAPE_DESIGN.md" not in active_docs
    assert "HOST_PROFILE_DESIGN.md" not in active_docs
    assert "POWER_MANAGEMENT_PRESET_DESIGN.md" not in active_docs
    assert "MACRO_COMPATIBILITY_PLAN.md" not in active_docs
    assert "KML_QMK_MACRO_KEYCODE_DESIGN.md" not in active_docs
    assert "VIAL_ADVANCED_MACRO_COMPATIBILITY_DESIGN.md" not in active_docs
    assert "DYNAMIC_MACRO_LEADER_DESIGN.md" not in active_docs
    assert "MIDI_AUDIO_OUTPUT_DESIGN.md" not in active_docs
    assert "MIDI_SEQUENCER_AUDIO_INTEGRATION_DESIGN.md" not in active_docs
    assert "MOUSE_HID_EXTENSION_DESIGN.md" not in active_docs
    assert "SYSTEM_CONTROL_PROGRAMMABLE_HID_REPORT_DESIGN.md" not in active_docs
    assert "DIGITIZER_HAPTIC_STENO_FEATURE_DESIGN.md" not in active_docs
    assert "BASIC_HID_KEYCODE_COMPLETION_DESIGN.md" not in active_docs
    assert "LAYER_ONESHOT_COMPLETION_DESIGN.md" not in active_docs
    assert "QMK_ALIAS_COMPLETION_DESIGN.md" not in active_docs
    assert "MAGIC_KEY_TRANSLATION_DESIGN.md" not in active_docs
    assert "KEY_OVERRIDE_RUNTIME_SUPPRESSION_DESIGN.md" not in active_docs
    assert "UNICODE_SEND_STRING_SAFETY_DESIGN.md" not in active_docs
    assert "AUTOCORRECT_SAFETY_DESIGN.md" not in active_docs
    assert "TOUCH_PANEL_FLICK_INPUT_DESIGN.md" not in active_docs
    assert "SEQUENCE_ENGINE_DESIGN.md" not in active_docs
    assert "WIFI_PERSISTENT_OFF_DESIGN.md" not in active_docs
    assert "USB_HOST_IDENTITY_KEYMAP_HOT_SWAP_DESIGN.md" not in active_docs
    assert "BOOT_DEBUG_EEPROM_ACTION_MAPPING_DESIGN.md" not in active_docs
    assert "MORSE_BEHAVIOR_CURRENT.md" not in active_docs
    assert "MORSE_BEHAVIOR_PLAN.md" not in active_docs
    assert "MORSE_HTTP_ROUTE_TODO.md" not in active_docs
    assert "QMK_VIAL_KEYCODE_SUPPORT.md" not in active_docs
    assert "UNIMPLEMENTED_KEYCODES.md" not in active_docs
    assert "KEYCODE_EXPANSION_PLAN.md" not in active_docs
    assert "HTTP_REMAP_KEYCODE_UI.md" not in active_docs
    assert "VIALD_ARCHITECTURE.md" not in active_docs
    assert "VIAL_IMPLEMENTATION_PLAN.md" not in active_docs
    assert "VIL_IMPORT_POLICY.md" not in active_docs
    assert "WORKFLOW_RUNBOOK.md" not in active_docs
    assert "REAL_DEVICE_TEST_CHECKLIST.md" not in active_docs
    assert "TEST_SCRIPT_INVENTORY.md" not in active_docs
    assert "PERFORMANCE_TUNING_PLAN.md" not in active_docs
    assert "INTERACTION_BUILDER_UX.md" not in active_docs
    assert "INTERACTION_UI_PLAN.md" not in active_docs
    assert "ACTION_VALIDATION_UNIFICATION_PLAN.md" not in active_docs
    assert "SCRIPT_SAFETY_METADATA.md" not in active_docs
    assert "KC_SH_HID_TEXT_CAT_SMOKE.md" not in active_docs

    print("ok: docs reorganization state is fresh")


if __name__ == "__main__":
    main()
