#!/usr/bin/env python3
"""Run local validation/logging regression tests that do not require hardware."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "script"))

from suite_runner import run_suite, test_environment  # noqa: E402

TESTS = [
    "script/test_hidloom_identity.py",
    "script/test_pid_codes_application.py",
    "script/test_public_usb_identity.py",
    "script/test_hidloom_runtime_environment.py",
    "script/test_local_environment_hygiene.py",
    "script/test_hidloom_name_audit.py",
    "script/test_repository_hygiene.py",
    "script/test_source_syntax_hygiene.py",
    "script/test_development_residue_hygiene.py",
    "script/test_generated_binary_hygiene.py",
    "script/test_workspace_debris_hygiene.py",
    "script/test_validation_suite_isolation.py",
    "script/test_rust_lockfile_policy.py",
    "script/test_public_export.py",
    "script/test_public_export_bundle.py",
    "script/test_public_source_archive.py",
    "script/test_public_buildroot_rebuild.py",
    "script/test_public_privacy_audit.py",
    "script/test_public_asset_inventory.py",
    "script/test_public_documentation_audit.py",
    "script/test_public_community_health.py",
    "script/test_public_reference_audit.py",
    "script/test_public_release_bundle.py",
    "script/test_public_release_readiness.py",
    "script/test_public_repository_create.py",
    "script/test_public_repository_bootstrap.py",
    "script/test_public_sync_branch.py",
    "script/test_public_ci_workflow.py",
    "script/test_github_workflow_security.py",
    "script/test_public_repository_policy.py",
    "script/test_license_evidence_tools.py",
    "script/test_buildroot_legal_summary.py",
    "script/test_buildroot_compliance_bundle.py",
    "script/test_third_party_inventory.py",
    "script/test_logicd_ctrl_validation.py",
    "script/test_logicd_lighting_keys.py",
    "script/test_logicd_host_led_output.py",
    "script/test_logicd_host_led_reader.py",
    "script/test_logicd_ledd_semantic_roles_snapshot.py",
    "script/test_logicd_consumer_aliases.py",
    "script/test_logicd_bt_alert.py",
    "script/test_logicd_bt_power_services.py",
    "script/test_logicd_encoder.py",
    "script/test_logicd_daemon_status.py",
    "script/test_logicd_sessiond_client_autostart.py",
    "script/test_logicd_i2cd_mode_reconnect.py",
    "script/test_logicd_joystick.py",
    "script/test_logicd_mouse_aliases.py",
    "script/test_logicd_mouse_acceleration.py",
    "script/test_layer_action.py",
    "script/test_action_expansion.py",
    "script/test_input_action_expansion_dispatch.py",
    "script/test_macro_output_switch.py",
    "script/test_native_outputd_ctrl.py",
    "script/test_layer_lock_output_switch_clear.py",
    "script/test_output_switch_auto.py",
    "script/test_matrixd_scan_optimization.py",
    "script/test_matrixd_debounce.py",
    "script/test_matrixd_build.py",
    "script/test_matrixd_led_stress_sweep_tool.py",
    "script/test_logicd_matrix_input_priority.py",
    "script/test_logicd_socket_env_overrides.py",
    "script/test_logicd_matrix_event_processing_boundary.py",
    "script/test_logicd_output_router_boundary.py",
    "script/test_logicd_resolved_action_heavy_boundary.py",
    "script/test_interaction_engine_passthrough.py",
    "script/test_interaction_engine_tap_hold.py",
    "script/test_interaction_engine_morse.py",
    "script/test_interaction_engine_caps_repeat_conditional.py",
    "script/test_interaction_physical_runtime.py",
    "script/test_key_override_cross_clear.py",
    "script/test_key_override_replacement_validation.py",
    "script/test_key_lock_state.py",
    "script/test_mod_morph.py",
    "script/test_sequence_engine_primitives.py",
    "script/test_sequence_engine_compatibility_guard.py",
    "script/test_sequence_morse_profile.py",
    "script/test_autocorrect_runtime.py",
    "script/test_dynamic_macro_leader_runtime.py",
    "script/test_macro_integration_runtime.py",
    "script/test_basic_hid_keycode_runtime.py",
    "script/test_qmk_unicode_map_runtime.py",
    "script/test_vial_keycode_codec.py",
    "script/test_vil_layout_codec.py",
    "script/test_vial_protocol_local.py",
    "script/test_vialrgb_ledd.py",
    "script/test_ledd_direct_frame.py",
    "script/test_ledd_direct_frame_socket.py",
    "script/test_ledd_direct_frame_apply.py",
    "script/test_ledd_direct_frame_fallback.py",
    "script/test_led_video_ledd_direct.py",
    "script/test_demo_asset_paths.py",
    "script/test_usbd_hid_report_broker.py",
    "script/test_usbd_validation.py",
    "script/test_btd_protocol_doc.py",
    "script/test_bluetooth_docs_current.py",
    "script/test_bluetooth_host_rename_forget_design_doc.py",
    "script/test_http_lighting_api.py",
    "script/test_http_lighting_layer_overlays.py",
    "script/test_http_lighting_lock_indicators.py",
    "script/test_http_interaction_api.py",
    "script/test_http_interaction_ui_assets.py",
    "script/test_interaction_inspector.py",
    "script/test_interaction_builder_ux.py",
    "script/test_text_send_safety.py",
    "script/test_touch_panel_flick_input.py",
    "script/test_touch_flick_composition_smoke.py",
    "script/test_touch_flick_dispatch.py",
    "script/test_morse_behavior.py",
    "script/test_morse_interaction_config.py",
    "script/test_morse_inspector.py",
    "script/test_morse_feedback.py",
    "script/test_morse_feedback_api.py",
    "script/test_morse_ctrl_feedback.py",
    "script/test_morse_oled_alert.py",
    "script/test_morse_led_feedback.py",
    "script/test_morse_browser_smoke_tool.py",
    "script/test_morse_browser_dom.py",
    "script/test_morse_documentation.py",
    "script/test_http_settings_api.py",
    "script/test_http_keymap_action_validation.py",
    "script/test_http_security.py",
    "tests/test_status_displays.py",
    "script/test_http_security_module_split.py",
    "script/test_http_vil_module_split.py",
    "script/test_http_remap_categories.py",
    "script/test_http_remap_keycode_coverage.py",
    "script/test_http_system_status.py",
    "script/test_http_wifi_status.py",
    "script/test_http_matrix_api.py",
    "script/test_http_layout_controls.py",
    "script/test_http_keyboard_layout_labels.py",
    "script/test_http_keymap_active.py",
    "script/test_http_keymap_api_save.py",
    "script/test_http_script_store.py",
    "script/test_http_script_check_run.py",
    "script/test_http_script_module_split.py",
    "script/test_http_script_ui_assets.py",
    "script/test_http_ui_assets.py",
    "script/test_hidloom_icon_assets.py",
    "script/test_led_semantic_roles.py",
    "script/test_led_life_game_effect.py",
    "script/test_led_role_preview.py",
    "script/test_led_pattern_metrics_runtime.py",
    "script/test_led_pattern_editor_long_run_design_doc.py",
    "script/test_lighting_role_preview_api.py",
    "script/test_lighting_role_inspector_api.py",
    "script/test_i2cd_oled_icons.py",
    "script/test_logicd_wifi_actions.py",
    "script/test_logicd_wifi_manager.py",
    "script/test_script_metadata.py",
    "script/test_script_directory_resolution.py",
    "script/test_board_profiles.py",
    "script/test_install_account_portability.py",
    "script/test_fresh_install_docs.py",
    "script/test_buildroot_fast_boot_assets.py",
    "script/test_usb_gadget_descriptor.py",
    "script/test_logicd_hidg0_multi_report_runtime.py",
    "script/test_jis_zenkaku_hankaku_routing.py",
    "script/test_logicd_usbd_report_broker_backend.py",
    "script/test_logicd_core_rs_tool.py",
    "script/test_keymap_cli_helpers.py",
    "script/test_runtime_keymap_permissions.py",
    "script/test_kicad_generation.py",
    "script/test_hidloom_send_tools.py",
    "script/test_command_help_surfaces.py",
    "script/test_hidloom_hidd_tool.py",
    "script/test_hidloom_uidd_tool.py",
    "script/test_hidloom_outputd_tool.py",
    "script/test_daemon_readme_diagrams.py",
    "script/test_tools_readme.py",
    "script/test_mcp_keyboard_server.py",
    "script/test_codex_task_mailbox.py",
    "script/test_keycode_expansion_plan_doc.py",
    "script/test_keycode_action_inventory.py",
    "script/test_unimplemented_keycodes_doc.py",
    "script/test_man_pages.py",
    "script/test_test_inventory_doc.py",
    "script/test_docs_archive.py",
    "script/test_docs_reorg.py",
    "script/test_docs_links.py",
    "script/test_daemon_specs_coverage.py",
    "script/test_logging_status_policy_doc.py",
    "script/test_module_structure_doc.py",
    "script/test_module_structure_http_split_doc.py",
    "script/test_macro_compatibility_plan_doc.py",
    "script/test_performance_tuning_plan_doc.py",
    "script/test_perf_baseline_tool.py",
    "script/test_boot_marker_baseline_tool.py",
    "script/test_remote_boot_baseline_collect_tool.py",
    "script/test_remote_fresh_install_tool.py",
    "script/test_cross_build_host_check_tool.py",
    "script/test_release_bundle_tools.py",
    "script/test_buildroot_m1_compare_tool.py",
    "script/test_logicd_core_action_classification_tool.py",
    "script/test_logicd_core_owner_recovery_tool.py",
    "script/test_logicd_core_native_owner_restore_tool.py",
    "script/test_logicd_core_native_owner_live_smoke_tool.py",
    "script/test_hid_release_roll_analyzer.py",
    "script/test_logicd_core_active_owner_preflight_tool.py",
    "script/test_logicd_core_active_owner_smoke_tool.py",
    "script/test_logicd_core_active_owner_units.py",
    "script/test_usb_enumeration_watch_tool.py",
    "script/test_logicd_event_benchmark_tool.py",
    "script/test_matrixd_diagnostics_snapshot_tool.py",
    "script/test_matrix_input_latency_instrumentation_design_doc.py",
    "script/test_sequence_engine_design_doc.py",
    "script/test_current_status_doc.py",
    "script/test_unicode_send_string_safety_design_doc.py",
    "script/test_touch_panel_flick_input_design_doc.py",
    "script/test_morse_romaji_composition_design_doc.py",
    "script/test_input_event_tap_output.py",
    "script/test_i2cd_device_fallback.py",
    "script/test_i2cd_warning_render.py",
    "script/test_i2cd_immediate_alert.py",
    "script/test_i2cd_ads1115.py",
    "script/test_i2cd_direct_frame_fps.py",
    "script/test_i2cd_output_mode_label.py",
]


def run_from_clean_snapshot() -> None:
    if os.environ.get("HIDLOOM_VALIDATION_SNAPSHOT") == "1":
        return
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    if untracked:
        paths = [os.fsdecode(item) for item in untracked.split(b"\0") if item]
        raise SystemExit(f"stage or remove untracked validation inputs: {paths}")
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    with tempfile.TemporaryDirectory(prefix="hidloom-validation-snapshot-") as temporary:
        snapshot = Path(temporary) / "repo"
        snapshot.mkdir()
        for encoded in tracked.split(b"\0"):
            if not encoded:
                continue
            relative = Path(os.fsdecode(encoded))
            source = ROOT / relative
            destination = snapshot / relative
            if not source.exists() and not source.is_symlink():
                raise SystemExit(f"tracked validation input is missing: {relative}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_symlink():
                destination.symlink_to(os.readlink(source))
            else:
                shutil.copy2(source, destination)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=snapshot, check=True)
        subprocess.run(
            ["git", "config", "user.name", "HIDloom Validation"], cwd=snapshot, check=True
        )
        subprocess.run(
            ["git", "config", "user.email", "validation@example.invalid"],
            cwd=snapshot,
            check=True,
        )
        subprocess.run(["git", "add", "-f", "-A"], cwd=snapshot, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "Validation snapshot"], cwd=snapshot, check=True
        )
        environment = os.environ.copy()
        environment["HIDLOOM_VALIDATION_SNAPSHOT"] = "1"
        completed = subprocess.run(
            [sys.executable, "script/test_validation_suite.py"],
            cwd=snapshot,
            env=environment,
        )
        raise SystemExit(completed.returncode)


def main() -> None:
    isolated = test_environment(
        {
            "PATH": os.environ.get("PATH", ""),
            "CARGO_TARGET_DIR": "/tmp/shared-target",
            "PYTHONDONTWRITEBYTECODE": "0",
        }
    )
    assert isolated["PATH"] == os.environ.get("PATH", "")
    assert "CARGO_TARGET_DIR" not in isolated
    assert isolated["PYTHONDONTWRITEBYTECODE"] == "1"
    run_from_clean_snapshot()
    duplicates = sorted({test for test in TESTS if TESTS.count(test) > 1})
    if duplicates:
        raise SystemExit(f"duplicate validation suite entries: {duplicates}")
    run_suite("validation regression suite passed", TESTS, stop_on_failure=True)


if __name__ == "__main__":
    main()
