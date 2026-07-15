#!/usr/bin/env python3
"""Regression checks for the read-only Keyboard MCP server."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dev.mcp.keyboard import server  # noqa: E402


def _read_frame(data: bytes) -> dict:
    header, body = data.split(b"\r\n\r\n", 1)
    length = None
    for line in header.splitlines():
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":", 1)[1].strip())
    assert length is not None, header
    assert len(body) == length, (len(body), length, body)
    return json.loads(body.decode("utf-8"))


def _frame(payload: dict) -> bytes:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body


def test_status_reads_repo_config() -> None:
    status = server.get_status()
    assert status["ok"] is True
    assert status["mode"] == "read_only"
    assert status["server"]["name"] == "hidloom-keyboard"
    assert status["config"]["usb_split_keyboard"]["enabled"] is True
    assert status["keymap"]["layer_count"] >= 1


def test_usb_split_reports_known_shape() -> None:
    split = server.get_usb_split_status()
    assert split["ok"] is True
    assert split["usb_split_keyboard"]["enabled"] is True
    assert split["usb_split_keyboard"]["route"] == "jis_special_us_default"
    assert any(item["device"] == "/dev/hidg0" for item in split["endpoints"])
    assert any(item["device"] == "/dev/hidg2" for item in split["endpoints"])
    assert any(item["name"] == "us_sub" and item["device"] == "/dev/hidg2" for item in split["endpoints"])


def test_route_explains_keyboard_mouse_consumer_and_split_keyboard() -> None:
    standard = server.explain_route_for_keycode("KC_A")
    assert standard["route"]["kind"] == "keyboard"
    assert standard["route"]["endpoint"] == "/dev/hidg2"
    assert server.explain_route_for_keycode("KC_BTN1")["route"]["kind"] == "mouse"
    assert server.explain_route_for_keycode("KC_VOLU")["route"]["kind"] == "consumer"

    jp = server.explain_route_for_keycode("KC_HENKAN")
    assert jp["classification"]["hid"] == 138
    assert jp["route"]["kind"] == "split_keyboard"
    assert jp["route"]["endpoint"] == "/dev/hidg0"

    kana = server.explain_route_for_keycode("KC_KANA")
    assert kana["classification"]["hid"] == 136
    assert kana["route"]["kind"] == "split_keyboard"
    assert kana["route"]["endpoint"] == "/dev/hidg0"

    lang1 = server.explain_route_for_keycode("KC_LANG1")
    assert lang1["classification"]["hid"] == 144
    assert lang1["route"]["endpoint"] == "/dev/hidg2"

    zkhk = server.explain_route_for_keycode("KC_ZKHK")
    assert zkhk["route"]["kind"] == "split_keyboard"
    assert zkhk["route"]["endpoint"] == "/dev/hidg0"

    unknown = server.explain_route_for_keycode("KC_DOES_NOT_EXIST")
    assert unknown["ok"] is False
    assert unknown["route"]["endpoint"] is None


def test_run_preflight_collects_read_only_summary() -> None:
    preflight = server.run_preflight(include_systemctl=False)
    assert preflight["ok"] is True
    assert preflight["mode"] == "read_only"
    assert preflight["service_status"]["skipped"] is True
    assert "hid_devices_present" in preflight["summary"]
    assert preflight["routes"]["KC_A"]["endpoint"] == "/dev/hidg2"
    assert preflight["routes"]["KC_HENKAN"]["endpoint"] == "/dev/hidg0"
    assert preflight["routes"]["KC_KANA"]["endpoint"] == "/dev/hidg0"
    assert preflight["routes"]["KC_ZKHK"]["endpoint"] == "/dev/hidg0"


def test_keymap_summary_reports_default_diffs_and_attention_actions() -> None:
    summary = server.get_keymap_summary(current_keymap_path=ROOT / "config" / "default" / "keymap.json")
    assert summary["ok"] is True
    assert summary["mode"] == "read_only"
    assert summary["layer_count"] >= 1
    assert summary["changed_from_default"] >= 0
    assert summary["changed_by_layer"]

    with tempfile.TemporaryDirectory() as tmp:
        current = Path(tmp) / "keymap.json"
        data = json.loads((ROOT / "config" / "default" / "keymap.json").read_text(encoding="utf-8"))
        data["layers"][0]["num"][0] = "KC_SHUTDOWN"
        current.write_text(json.dumps(data), encoding="utf-8")
        changed = server.get_keymap_summary(current_keymap_path=current, max_changes=5)
        assert changed["changed_from_default"] >= 1
        assert changed["sample_changes"][0]["current"] == "KC_SHUTDOWN"
        assert changed["attention_actions"][0]["action"] == "KC_SHUTDOWN"
        assert changed["attention_actions"][0]["kind"] == "attention_action"


def test_collect_journal_excerpt_is_bounded_and_allowlisted() -> None:
    dry = server.collect_journal_excerpt("hidloom-logicd-core", lines=500, execute=False)
    assert dry["ok"] is True
    assert dry["mode"] == "read_only"
    assert dry["lines"] == 200
    assert dry["command"] == ["journalctl", "-u", "hidloom-logicd-core", "-n", "200", "--no-pager"]

    rejected = server.collect_journal_excerpt("ssh", execute=False)
    assert rejected["ok"] is False
    assert "service must be one of" in rejected["error"]


def test_check_runtime_access_reports_identity_and_paths() -> None:
    access = server.check_runtime_access(paths=[str(ROOT / "config" / "default" / "keymap.json"), "/definitely/not/here"])
    assert access["ok"] is True
    assert access["mode"] == "read_only"
    assert access["identity"]["user"]
    assert len(access["paths"]) == 2
    assert access["paths"][0]["exists"] is True
    assert access["paths"][0]["readable"] is True
    assert access["paths"][1]["exists"] is False
    assert access["paths"][1]["readable"] is False


def test_check_runtime_access_recommends_keymap_permission_fix() -> None:
    original = server._runtime_path_access

    def fake_access(path: str) -> dict:
        if path == "/mnt/p3/keymap.json":
            return {
                "path": path,
                "exists": True,
                "kind": "file",
                "mode": "-rw-------",
                "owner": "root",
                "group": "root",
                "readable": False,
                "writable": False,
                "executable": False,
            }
        return original(path)

    server._runtime_path_access = fake_access
    try:
        access = server.check_runtime_access(paths=["/mnt/p3/keymap.json"])
    finally:
        server._runtime_path_access = original
    assert access["runtime_keymap_readable"] is False
    assert access["recommendations"]
    assert access["recommendations"][0]["executed"] is False
    assert "hidloom-diagnostics" in " ".join(access["recommendations"][0]["example_commands"])


def test_script_summary_reports_labels_and_safety() -> None:
    summary = server.get_script_summary()
    assert summary["ok"] is True
    assert summary["mode"] == "read_only"
    assert summary["count"] >= 1
    entries = {entry["keycode"]: entry for entry in summary["entries"]}
    assert entries["KC_SH0"]["label"] == "未割当"
    assert entries["KC_SH8"]["label"] == "matrixd診断"
    assert entries["KC_SH0"]["source"] in {"fallback", "runtime"}
    assert "dangerous_count" in summary


def test_preview_hid_report_for_keyboard_and_consumer() -> None:
    a = server.preview_hid_report("KC_A")
    assert a["ok"] is True
    assert a["report"]["kind"] == "keyboard"
    assert a["report"]["canonical_press"] == "0000040000000000"
    assert a["report"]["with_report_id_press"] == "010000040000000000"
    assert a["route"]["endpoint"] == "/dev/hidg2"

    shifted = server.preview_hid_report("KC_A", modifiers=["KC_LSHIFT"])
    assert shifted["report"]["canonical_press"] == "0200040000000000"

    henkan = server.preview_hid_report("KC_HENKAN")
    assert henkan["report"]["canonical_press"] == "00008a0000000000"
    assert henkan["route"]["endpoint"] == "/dev/hidg0"

    zkhk = server.preview_hid_report("KC_ZKHK")
    assert zkhk["report"]["canonical_press"] == "005a350000000000"
    assert zkhk["report"]["with_report_id_press"] == "01005a350000000000"
    assert zkhk["route"]["endpoint"] == "/dev/hidg0"

    vol = server.preview_hid_report("KC_VOLU")
    assert vol["ok"] is True
    assert vol["report"]["kind"] == "consumer"
    assert vol["report"]["canonical_press"] == "e900"
    assert vol["report"]["with_report_id_press"] == "03e900"

    mouse = server.preview_hid_report("KC_BTN1")
    assert mouse["ok"] is False
    assert mouse["report"] is None


def test_inspect_key_position_reports_layers_and_previews() -> None:
    esc = server.inspect_key_position(matrix="7,0", current_keymap_path=ROOT / "config" / "default" / "keymap.json")
    assert esc["ok"] is True
    assert esc["matrix"] == "7,0"
    assert esc["layers"][0]["current"] == "KC_ESC"
    assert esc["layers"][0]["default"] == "KC_ESC"
    assert esc["layers"][0]["report_preview_ok"] is True
    assert esc["layers"][0]["report"]["canonical_press"] == "0000290000000000"

    script_key = server.inspect_key_position(
        row=6,
        col=2,
        include_reports=False,
        current_keymap_path=ROOT / "config" / "default" / "keymap.json",
    )
    assert script_key["ok"] is True
    assert script_key["layers"][0]["current"] == "KC_SH5"
    assert script_key["layers"][0]["attention"] == "script_action"
    assert "report" not in script_key["layers"][0]

    bad = server.inspect_key_position(matrix="bad")
    assert bad["ok"] is False
    assert "matrix must be formatted" in bad["errors"][0]


def test_repo_state_reports_git_checkout() -> None:
    state = server.get_repo_state(max_files=3)
    assert state["ok"] is True
    assert state["mode"] == "read_only"
    assert state["repo_root"] == str(ROOT.resolve())
    assert state["commit"]
    assert isinstance(state["dirty"], bool)
    assert isinstance(state["dirty_count"], int)
    assert len(state["dirty_files"]) <= 3
    assert state["status_header"].startswith("##")
    missing = server.get_repo_state(repo_root=ROOT / "does-not-exist")
    assert missing["ok"] is False
    assert missing["error"] == "not a git checkout"


def test_repo_dirty_summary_classifies_status_lines() -> None:
    assert server._parse_git_status_short_line(" M config/default/config.json") == {
        "status": "M",
        "path": "config/default/config.json",
        "old_path": "",
    }
    assert server._parse_git_status_short_line("?? dev/mcp/keyboard/server.py")["status"] == "??"
    assert server._dirty_category("config/default/config.json", "M") == "config"
    assert server._dirty_category("system/systemd/logicd.service", "M") == "logicd"
    assert server._dirty_category("system/systemd/httpd.service", "M") == "http"
    assert server._dirty_category("system/systemd/hidloom-usb-gadget.service", "M") == "usb_gadget"
    assert server._dirty_category("dev/mcp/keyboard/server.py", "M") == "mcp"
    assert server._dirty_category("daemon/matrixd/matrixd", "M") == "native_artifact"
    assert server._dirty_category("dev/mcp/keyboard/server.py", "??") == "mcp"
    assert "untracked" in server._dirty_attention("dev/mcp/keyboard/server.py", "??", "mcp")

    summary = server.get_repo_dirty_summary(max_files=5)
    assert summary["ok"] is True
    assert summary["mode"] == "read_only"
    assert isinstance(summary["categories"], dict)
    assert len(summary["files"]) <= 5
    assert "status_counts" in summary
    assert "untracked_count" in summary


def test_checkout_hygiene_summary_flags_untracked_directories() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        subprocess.run(["git", "init"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        subprocess.run(["git", "config", "user.email", "tester@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=root, check=True)
        (root / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        (root / "tools" / "mcp_keyboard").mkdir(parents=True)
        (root / "tools" / "mcp_keyboard" / "scratch.py").write_text("print('x')\n", encoding="utf-8")

        summary = server.get_checkout_hygiene_summary(repo_root=root, max_files=10)

    assert summary["ok"] is True
    assert summary["mode"] == "read_only"
    assert summary["status"] == "needs_review"
    assert summary["buckets"]["untracked_directory"] == 1
    assert summary["issues"][0]["bucket"] == "untracked_directory"
    assert summary["issues"][0]["recommended_action"] == "inspect_directory_before_sync"
    assert any("does not run git" in note for note in summary["notes"])


def test_checkout_drift_summary_attributes_reflection_and_runtime_changes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        subprocess.run(["git", "init"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        subprocess.run(["git", "config", "user.email", "tester@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=root, check=True)
        (root / "config" / "default").mkdir(parents=True)
        (root / "config" / "default" / "config.json").write_text("{}\n", encoding="utf-8")
        subprocess.run(["git", "add", "config/default/config.json"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        (root / "config" / "default" / "config.json").write_text('{"changed": true}\n', encoding="utf-8")
        (root / "codex_tasks" / "inbox").mkdir(parents=True)
        (root / "codex_tasks" / "inbox" / "task.json").write_text("{}\n", encoding="utf-8")

        summary = server.get_checkout_drift_summary(repo_root=root, max_files=20)

    assert summary["ok"] is True
    assert summary["mode"] == "read_only"
    assert summary["status"] == "needs_review"
    assert summary["counts"]["reflection_candidates"] == 1
    assert summary["counts"]["local_runtime_changes"] == 1
    assert summary["groups"]["reflection_candidates"][0]["path"] == "codex_tasks/"
    assert summary["groups"]["local_runtime_changes"][0]["path"] == "config/default/config.json"
    assert any("does not run git pull" in note for note in summary["notes"])


def test_pull_readiness_blocks_dirty_runtime_and_reflection_drift() -> None:
    original_repo = server.get_repo_state
    original_drift = server.get_checkout_drift_summary
    original_run_git = server._run_git

    def fake_repo(repo_root: Path = ROOT, max_files: int = 80) -> dict:
        return {
            "ok": True,
            "branch": "main",
            "commit": "abc123",
            "upstream": "origin/main",
            "dirty": True,
            "dirty_count": 3,
        }

    def fake_drift(repo_root: Path = ROOT, max_files: int = 80, reflection_categories: list[str] | None = None) -> dict:
        return {
            "ok": True,
            "counts": {
                "reflection_candidates": 1,
                "local_runtime_changes": 1,
                "local_untracked_runtime": 0,
                "ordinary_dirty": 1,
                "backup_or_generated": 0,
            },
        }

    def fake_run_git(args: list[str], *, cwd: Path) -> dict:
        assert args[:3] == ["rev-list", "--left-right", "--count"]
        return {"ok": True, "stdout": "2\t0", "stderr": ""}

    server.get_repo_state = fake_repo
    server.get_checkout_drift_summary = fake_drift
    server._run_git = fake_run_git
    try:
        summary = server.get_pull_readiness_summary()
    finally:
        server.get_repo_state = original_repo
        server.get_checkout_drift_summary = original_drift
        server._run_git = original_run_git

    assert summary["mode"] == "read_only"
    assert summary["status"] == "blocked"
    assert summary["behind"] == 2
    assert summary["ahead"] == 0
    assert {item["area"] for item in summary["blockers"]} >= {"local_runtime_changes", "reflection_candidates", "dirty_checkout"}
    assert any("does not run git fetch" in note for note in summary["notes"])


def test_checkout_cleanup_candidates_separates_preserve_and_cleanup() -> None:
    original_drift = server.get_checkout_drift_summary
    original_pull = server.get_pull_readiness_summary

    def fake_drift(repo_root: Path = ROOT, max_files: int = 80, reflection_categories: list[str] | None = None) -> dict:
        return {
            "ok": True,
            "groups": {
                "local_runtime_changes": [{"path": "config/default/config.json", "path_kind": "file"}],
                "local_untracked_runtime": [],
                "reflection_candidates": [{"path": "dev/mcp/keyboard/", "path_kind": "directory"}],
                "backup_or_generated": [],
                "ordinary_dirty": [{"path": "README.md", "path_kind": "file"}],
            },
        }

    def fake_pull(repo_root: Path = ROOT, max_files: int = 80, reflection_categories: list[str] | None = None) -> dict:
        return {"ok": True, "status": "blocked"}

    server.get_checkout_drift_summary = fake_drift
    server.get_pull_readiness_summary = fake_pull
    try:
        summary = server.get_checkout_cleanup_candidates()
    finally:
        server.get_checkout_drift_summary = original_drift
        server.get_pull_readiness_summary = original_pull

    assert summary["mode"] == "read_only"
    assert summary["status"] == "needs_preserve_decision"
    assert summary["counts"] == {"preserve": 1, "cleanup_candidates": 1, "review": 1}
    assert summary["preserve"][0]["recommended_next_step"] == "preserve_or_document_before_pull"
    assert summary["cleanup_candidates"][0]["recommended_next_step"] == "inspect_directory_then_align_or_remove"
    assert any("does not run git clean" in note for note in summary["notes"])


def test_checkout_preserve_diff_summary_redacts_diff_hunks() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        subprocess.run(["git", "init"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        subprocess.run(["git", "config", "user.email", "tester@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=root, check=True)
        (root / "config" / "default").mkdir(parents=True)
        (root / "config" / "default" / "config.json").write_text("{}\n", encoding="utf-8")
        subprocess.run(["git", "add", "config/default/config.json"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        (root / "config" / "default" / "config.json").write_text('{"changed": true}\n', encoding="utf-8")
        (root / "daemon" / "logicd").mkdir(parents=True)
        (root / "daemon" / "logicd" / "local.conf").write_text("local\n", encoding="utf-8")

        original_cleanup = server.get_checkout_cleanup_candidates

        def fake_cleanup(repo_root: Path = root, max_files: int = 80, reflection_categories: list[str] | None = None) -> dict:
            return {
                "ok": True,
                "pull_status": "blocked",
                "preserve": [
                    {"path": "config/default/config.json", "status": "M", "category": "config", "source_group": "local_runtime_changes", "path_kind": "file"},
                    {"path": "daemon/logicd/local.conf", "status": "??", "category": "logicd", "source_group": "local_untracked_runtime", "path_kind": "file"},
                ],
            }

        server.get_checkout_cleanup_candidates = fake_cleanup
        try:
            summary = server.get_checkout_preserve_diff_summary(repo_root=root, max_files=10)
        finally:
            server.get_checkout_cleanup_candidates = original_cleanup

    assert summary["ok"] is True
    assert summary["mode"] == "read_only"
    assert summary["counts"]["tracked"] == 1
    assert summary["counts"]["untracked"] == 1
    assert summary["items"][0]["diff"]["insertions"] == 1
    assert summary["items"][0]["diff"]["deletions"] == 1
    assert summary["items"][1]["diff"] is None
    assert "diff hunks" in summary["redaction"]


def test_checkout_backup_plan_summary_returns_manual_commands_only() -> None:
    original_preserve = server.get_checkout_preserve_diff_summary
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "daemon" / "logicd").mkdir(parents=True)
        (root / "daemon" / "logicd" / "local.conf").write_text("local config\n", encoding="utf-8")

        def fake_preserve(repo_root: Path = root, max_files: int = 80, reflection_categories: list[str] | None = None) -> dict:
            return {
                "ok": True,
                "counts": {"tracked": 1, "untracked": 1},
                "items": [
                    {"path": "config/default/config.json", "status": "M", "category": "config", "source_group": "local_runtime_changes", "path_kind": "file", "diff": {"insertions": 2, "deletions": 1}},
                    {"path": "daemon/logicd/local.conf", "status": "??", "category": "logicd", "source_group": "local_untracked_runtime", "path_kind": "file", "size": 12, "diff": None},
                ],
            }

        server.get_checkout_preserve_diff_summary = fake_preserve
        try:
            summary = server.get_checkout_backup_plan_summary(repo_root=root, backup_root=Path("/tmp/hidloom backup"))
        finally:
            server.get_checkout_preserve_diff_summary = original_preserve

    assert summary["ok"] is True
    assert summary["mode"] == "read_only"
    assert summary["status"] == "backup_recommended"
    assert summary["counts"] == {"files": 2, "tracked": 1, "untracked": 1}
    assert summary["estimated_file_bytes"] == 12
    assert summary["manual_commands"][0] == "mkdir -p '/tmp/hidloom backup'"
    assert "tar -czf" in summary["manual_commands"][1]
    assert "tracked.diff" in summary["manual_commands"][2]
    assert any("does not create directories" in note for note in summary["notes"])


def test_manual_cleanup_verification_plan_blocks_until_backup_confirmed() -> None:
    original_cleanup = server.get_checkout_cleanup_candidates
    original_backup = server.get_checkout_backup_plan_summary
    original_pull = server.get_pull_readiness_summary

    def fake_cleanup(repo_root: Path = ROOT, max_files: int = 80, reflection_categories: list[str] | None = None) -> dict:
        return {
            "ok": True,
            "status": "needs_preserve_decision",
            "counts": {"preserve": 1, "cleanup_candidates": 0, "review": 0},
        }

    def fake_backup(
        repo_root: Path = ROOT,
        max_files: int = 80,
        reflection_categories: list[str] | None = None,
        backup_root: Path | None = None,
    ) -> dict:
        return {
            "ok": True,
            "status": "backup_recommended",
            "backup_root": str(backup_root or Path("/tmp/backup")),
            "counts": {"files": 1, "tracked": 1, "untracked": 0},
        }

    def fake_pull(repo_root: Path = ROOT, max_files: int = 80, reflection_categories: list[str] | None = None) -> dict:
        return {"ok": True, "status": "ready_to_pull", "ahead": 0, "behind": 1, "blockers": []}

    server.get_checkout_cleanup_candidates = fake_cleanup
    server.get_checkout_backup_plan_summary = fake_backup
    server.get_pull_readiness_summary = fake_pull
    try:
        blocked = server.get_manual_cleanup_verification_plan(backup_root=Path("/tmp/hidloom backup"))
        ready = server.get_manual_cleanup_verification_plan(backup_root=Path("/tmp/hidloom backup"), backup_confirmed=True)
    finally:
        server.get_checkout_cleanup_candidates = original_cleanup
        server.get_checkout_backup_plan_summary = original_backup
        server.get_pull_readiness_summary = original_pull

    assert blocked["ok"] is True
    assert blocked["mode"] == "read_only"
    assert blocked["status"] == "blocked"
    assert blocked["summaries"]["backup_root"] == "/tmp/hidloom backup"
    assert any(item["area"] == "backup_confirmation" for item in blocked["blockers"])
    assert ready["status"] == "ready_for_manual_pull"
    assert ready["blockers"] == []
    assert any("does not create backups" in note for note in ready["notes"])


def test_cleanup_review_order_summary_prioritizes_preserve_then_cleanup() -> None:
    original_cleanup = server.get_checkout_cleanup_candidates
    original_gate = server.get_manual_cleanup_verification_plan

    def fake_cleanup(repo_root: Path = ROOT, max_files: int = 80, reflection_categories: list[str] | None = None) -> dict:
        return {
            "ok": True,
            "status": "needs_preserve_decision",
            "preserve": [
                    {"path": "config/default/config.json", "status": "M", "category": "config", "source_group": "local_runtime_changes", "path_kind": "file", "recommended_next_step": "preserve_or_document_before_pull"}
            ],
            "cleanup_candidates": [
                {"path": "dev/mcp/keyboard/", "status": "??", "category": "mcp", "source_group": "reflection_candidates", "path_kind": "directory"},
                {"path": "setup_usb_gadget.sh.before-keyboard-only-jis-id-20260612-233818", "status": "??", "category": "usb_gadget", "source_group": "backup_or_generated", "path_kind": "file"},
            ],
            "review": [
                {"path": "README.md", "status": "M", "category": "docs", "source_group": "ordinary_dirty", "path_kind": "file"}
            ],
        }

    def fake_gate(
        repo_root: Path = ROOT,
        max_files: int = 80,
        reflection_categories: list[str] | None = None,
        backup_root: Path | None = None,
        backup_confirmed: bool = False,
    ) -> dict:
        return {"ok": True, "status": "blocked", "blockers": [{"area": "backup_confirmation"}]}

    server.get_checkout_cleanup_candidates = fake_cleanup
    server.get_manual_cleanup_verification_plan = fake_gate
    try:
        summary = server.get_cleanup_review_order_summary(max_files=10)
    finally:
        server.get_checkout_cleanup_candidates = original_cleanup
        server.get_manual_cleanup_verification_plan = original_gate

    assert summary["ok"] is True
    assert summary["mode"] == "read_only"
    assert summary["status"] == "needs_ordered_review"
    assert summary["counts"] == {"ordered": 4, "preserve": 1, "cleanup_directories": 1, "cleanup_files": 1, "review": 1, "gate_blockers": 1}
    assert [item["bucket"] for item in summary["ordered_review"]] == ["preserve", "cleanup_directory", "cleanup_file", "review"]
    assert "git diff --stat -- config/default/config.json" in summary["ordered_review"][0]["read_only_checks"]
    assert any("git ls-files --others" in cmd for cmd in summary["ordered_review"][1]["read_only_checks"])
    assert any("does not create backups" in note for note in summary["notes"])


def test_reflection_cleanup_alignment_summary_uses_local_reference_only() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        subprocess.run(["git", "init"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        subprocess.run(["git", "config", "user.email", "tester@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=root, check=True)
        (root / "docs").mkdir()
        (root / "docs" / "known.md").write_text("known\n", encoding="utf-8")
        subprocess.run(["git", "add", "docs/known.md"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        original_cleanup = server.get_checkout_cleanup_candidates
        original_repo = server.get_repo_state

        def fake_cleanup(repo_root: Path = root, max_files: int = 80, reflection_categories: list[str] | None = None) -> dict:
            return {
                "ok": True,
                "cleanup_candidates": [
                    {"path": "docs/known.md", "status": "??", "category": "docs", "source_group": "reflection_candidates", "path_kind": "file"},
                    {"path": "docs/missing.md", "status": "??", "category": "docs", "source_group": "reflection_candidates", "path_kind": "file"},
                ],
            }

        def fake_repo(repo_root: Path = root, max_files: int = 80) -> dict:
            return {"ok": True, "upstream": "HEAD"}

        server.get_checkout_cleanup_candidates = fake_cleanup
        server.get_repo_state = fake_repo
        try:
            summary = server.get_reflection_cleanup_alignment_summary(repo_root=root, reference="HEAD")
        finally:
            server.get_checkout_cleanup_candidates = original_cleanup
            server.get_repo_state = original_repo

    assert summary["ok"] is True
    assert summary["mode"] == "read_only"
    assert summary["reference"] == "HEAD"
    assert summary["counts"]["present_in_ref"] == 1
    assert summary["counts"]["absent_in_ref"] == 1
    assert [item["reference_state"] for item in summary["items"]] == ["present_in_ref", "absent_in_ref"]
    assert summary["items"][0]["recommended_next_step"] == "compare_against_reference_before_manual_alignment"
    assert any("does not fetch" in note for note in summary["notes"])


def test_temporary_change_restore_plan_summary_lists_stashes_without_applying() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        subprocess.run(["git", "init"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        subprocess.run(["git", "config", "user.email", "tester@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=root, check=True)
        (root / "config.txt").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "config.txt"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        (root / "config.txt").write_text("temporary\n", encoding="utf-8")
        (root / "local.txt").write_text("untracked\n", encoding="utf-8")
        subprocess.run(["git", "stash", "push", "-u", "-m", "temporary device edit"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        summary = server.get_temporary_change_restore_plan_summary(repo_root=root)

    assert summary["ok"] is True
    assert summary["mode"] == "read_only"
    assert summary["status"] == "has_temporary_changes"
    assert summary["counts"]["listed_stashes"] == 1
    assert summary["stashes"][0]["ref"] == "stash@{0}"
    assert "temporary device edit" in summary["stashes"][0]["message"]
    assert summary["selected"]["available"] is True
    assert "git stash apply --index 'stash@{0}'" in summary["manual_commands"]
    assert any("does not run git stash apply" in note for note in summary["notes"])


def test_real_device_experiment_workflow_summary_blocks_dirty_checkout_without_mutating() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        subprocess.run(["git", "init"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        subprocess.run(["git", "config", "user.email", "tester@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=root, check=True)
        (root / "config.txt").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "config.txt"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        (root / "config.txt").write_text("temporary experiment\n", encoding="utf-8")

        summary = server.get_real_device_experiment_workflow_summary(repo_root=root, max_files=10)

    assert summary["ok"] is True
    assert summary["mode"] == "read_only"
    assert summary["status"] == "experiment_changes_need_revert"
    assert any(item["area"] == "dirty_checkout" for item in summary["blockers"])
    assert "git reset --hard HEAD" in summary["manual_commands_after_recording"]
    assert "git clean -fd" in summary["manual_commands_after_recording"]
    assert any("does not run git stash" in note for note in summary["notes"])


def test_real_device_access_summary_prefers_reachable_clean_target_without_writes() -> None:
    original_resolve = server._resolve_host
    original_probe = server._ssh_checkout_probe

    def fake_resolve(host: str) -> dict:
        if host == "alias":
            return {"ok": False, "host": host, "addresses": [], "error": "not found"}
        return {"ok": True, "host": host, "addresses": [host], "error": None}

    def fake_probe(target: str, repo_root: str, timeout_sec: float) -> dict:
        if target == "192.0.2.44":
            return {
                "ok": True,
                "returncode": 0,
                "error": None,
                "status_header": "## main...origin/main",
                "commit": "abc123def456",
                "dirty": False,
                "dirty_count": 0,
                "stderr": "",
            }
        return {"ok": False, "returncode": 255, "error": "ssh failed", "status_header": "", "commit": "", "dirty": None, "stderr": "ssh failed"}

    server._resolve_host = fake_resolve
    server._ssh_checkout_probe = fake_probe
    try:
        summary = server.get_real_device_access_summary(targets=["alias", "192.0.2.44"])
    finally:
        server._resolve_host = original_resolve
        server._ssh_checkout_probe = original_probe

    assert summary["ok"] is True
    assert summary["mode"] == "read_only"
    assert summary["status"] == "ready"
    assert summary["selected_target"] == "192.0.2.44"
    assert summary["counts"]["resolved"] == 1
    assert summary["counts"]["ssh_reachable"] == 1
    assert summary["targets"][0]["ssh_probe"]["skipped"] is True
    assert "git status --short --branch" in summary["targets"][1]["manual_commands"][1]
    assert any("does not pull" in note for note in summary["notes"])


def test_real_device_access_summary_classifies_ssh_probe_errors() -> None:
    original_resolve = server._resolve_host
    original_probe = server._ssh_checkout_probe

    def fake_resolve(host: str) -> dict:
        return {"ok": True, "host": host, "addresses": [host], "error": None}

    def fake_probe(target: str, repo_root: str, timeout_sec: float) -> dict:
        return {
            "ok": False,
            "returncode": 255,
            "error": "Host key verification failed.",
            "error_kind": "host_key_verification_failed",
            "status_header": "",
            "commit": "",
            "dirty": None,
            "dirty_count": None,
            "stderr": "Host key verification failed.",
        }

    server._resolve_host = fake_resolve
    server._ssh_checkout_probe = fake_probe
    try:
        summary = server.get_real_device_access_summary(targets=["192.0.2.44", "keyboard.example"])
    finally:
        server._resolve_host = original_resolve
        server._ssh_checkout_probe = original_probe

    assert summary["ok"] is False
    assert summary["status"] == "unreachable"
    assert summary["counts"]["ssh_error_kinds"] == {"host_key_verification_failed": 2}
    assert summary["targets"][0]["ssh_probe"]["error_kind"] == "host_key_verification_failed"
    assert any("known_hosts" in item for item in summary["recommendations"])
    assert summary["next_read_only_checks"][0]["error_kind"] == "host_key_verification_failed"
    assert summary["next_read_only_checks"][0]["commands"][0] == "ssh-keygen -F 192.0.2.44"
    assert summary["next_read_only_checks"][0]["commands"][1].startswith("ssh-keyscan")


def test_selective_sync_plan_is_read_only_and_uses_dirty_categories() -> None:
    plan = server.get_selective_sync_plan(target="pi@example", categories=["mcp", "docs"], max_files=20)
    assert plan["ok"] is True
    assert plan["mode"] == "read_only"
    assert plan["target"] == "pi@example"
    assert plan["selected_categories"] == ["mcp", "docs"]
    assert isinstance(plan["selected_paths"], list)
    if plan["selected_paths"]:
        assert plan["rsync_command"]
        assert "rsync -az --relative" in plan["rsync_command"]
        assert "pi@example:/srv/hidloom/" in plan["rsync_command"]
    assert any("does not run rsync" in note for note in plan["notes"])
    assert "dirty_count" in plan["dirty_summary"]


def test_reflection_apply_plan_is_read_only_operator_checklist() -> None:
    original_sync = server.get_selective_sync_plan
    original_readiness = server.get_update_readiness_summary

    def fake_sync(target: str = "pi@example", repo_root: Path = ROOT, categories: list[str] | None = None, max_files: int = 80) -> dict:
        return {
            "ok": True,
            "mode": "read_only",
            "target": target,
            "selected_categories": categories or ["mcp", "docs"],
            "selected_count": 2,
            "selected_paths": ["dev/mcp/keyboard/server.py", "dev/mcp/keyboard/README.md"],
            "rsync_command": "rsync -az --relative dev/mcp/keyboard/server.py dev/mcp/keyboard/README.md pi@example:/srv/hidloom/",
            "remote_smoke_commands": ["python3 script/test_mcp_keyboard_server.py"],
            "blocked_count": 0,
            "runtime_attention_count": 0,
            "recommendations": [],
        }

    def fake_readiness(repo_root: Path = ROOT, include_http_status: bool = True) -> dict:
        return {
            "ok": True,
            "summary": {"surface_count": 6, "apply_tools_recommended_now": False},
            "source_summaries": {
                "repo": {"dirty_count": 2},
                "http_status": {"ok": True},
            },
            "recommendations": ["implement plan/dry-run tools before any apply tool"],
        }

    server.get_selective_sync_plan = fake_sync
    server.get_update_readiness_summary = fake_readiness
    try:
        plan = server.get_reflection_apply_plan(target="pi@example", categories=["mcp", "docs"], include_http_status=True)
    finally:
        server.get_selective_sync_plan = original_sync
        server.get_update_readiness_summary = original_readiness

    assert plan["ok"] is True
    assert plan["mode"] == "read_only"
    assert plan["status"] == "ready_for_operator_review"
    assert plan["confirmation"]["phrase"].startswith("REFLECT ")
    assert plan["selected"]["count"] == 2
    assert plan["manual_commands"][0].startswith("rsync -az --relative")
    assert plan["manual_commands"][1].startswith("ssh pi@example ")
    assert plan["preflight"]["apply_tools_recommended_now"] is False
    assert plan["blockers"] == []
    assert any("does not run rsync" in note for note in plan["notes"])


def test_reflection_apply_plan_blocks_selected_directories() -> None:
    original_sync = server.get_selective_sync_plan
    original_readiness = server.get_update_readiness_summary

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "wide_dir").mkdir()

        def fake_sync(target: str = "pi@example", repo_root: Path = root, categories: list[str] | None = None, max_files: int = 80) -> dict:
            return {
                "ok": True,
                "selected_categories": ["mcp"],
                "selected_count": 1,
                "selected_paths": ["wide_dir"],
                "rsync_command": "rsync -az --relative wide_dir pi@example:/srv/hidloom/",
                "remote_smoke_commands": [],
                "blocked_count": 0,
                "runtime_attention_count": 0,
                "recommendations": [],
            }

        def fake_readiness(repo_root: Path = root, include_http_status: bool = True) -> dict:
            return {
                "ok": True,
                "summary": {"surface_count": 6, "apply_tools_recommended_now": False},
                "source_summaries": {"repo": {"dirty_count": 1}, "http_status": {"ok": True}},
                "recommendations": [],
            }

        server.get_selective_sync_plan = fake_sync
        server.get_update_readiness_summary = fake_readiness
        try:
            plan = server.get_reflection_apply_plan(target="pi@example", repo_root=root, categories=["mcp"])
        finally:
            server.get_selective_sync_plan = original_sync
            server.get_update_readiness_summary = original_readiness

    assert plan["status"] == "blocked_pending_review"
    assert plan["blockers"][0]["area"] == "selected_directory"
    assert plan["blockers"][0]["paths"] == ["wide_dir"]


def test_development_snapshot_collects_compact_sections() -> None:
    snapshot = server.get_development_snapshot(include_systemctl=False, include_http_status=False, max_files=2, max_changes=2)
    assert snapshot["mode"] == "read_only"
    assert snapshot["repo"]["commit"]
    assert len(snapshot["repo"]["dirty_files"]) <= 2
    assert "dirty_categories" in snapshot["repo"]
    assert "hygiene_status" in snapshot["repo"]
    assert snapshot["runtime_access"]["user"]
    assert snapshot["preflight"]["service_status"]["skipped"] is True
    assert "layer_count" in snapshot["keymap"]
    assert "dangerous_count" in snapshot["scripts"]
    assert "keyboard_server" in snapshot["codex_mcp"]
    assert "daemon/matrixd/matrixd" in snapshot["sync_safety"]["rsync_excludes"]
    assert "selected_count" in snapshot["selective_sync"]
    assert snapshot["systemd_units"]["skipped"] is True
    assert "pending_count" in snapshot["codex_task_mailbox"]
    assert snapshot["http_status"]["error"] == "skipped"
    assert snapshot["real_device_access"]["status"] == "skipped"
    assert "issue_count" in snapshot["runtime_issues"]
    assert "board_profile" in snapshot["runtime_state"]


def test_development_snapshot_can_include_real_device_access_summary() -> None:
    original_access = server.get_real_device_access_summary

    def fake_access(timeout_sec: float = 3.0) -> dict:
        return {
            "ok": True,
            "status": "ready",
            "selected_target": "192.0.2.44",
            "counts": {"targets": 1, "resolved": 1, "ssh_reachable": 1, "reachable_clean": 1},
            "recommendations": ["use 192.0.2.44 for the next real-device read-only smoke"],
            "next_read_only_checks": [{"target": "x", "error_kind": "timeout", "commands": ["getent hosts x"]}],
        }

    server.get_real_device_access_summary = fake_access
    try:
        snapshot = server.get_development_snapshot(
            include_systemctl=False,
            include_http_status=False,
            include_real_device_access=True,
            max_files=1,
            max_changes=1,
        )
    finally:
        server.get_real_device_access_summary = original_access

    assert snapshot["real_device_access"]["ok"] is True
    assert snapshot["real_device_access"]["status"] == "ready"
    assert snapshot["real_device_access"]["selected_target"] == "192.0.2.44"
    assert snapshot["real_device_access"]["counts"]["reachable_clean"] == 1
    assert snapshot["real_device_access"]["next_read_only_checks"][0]["error_kind"] == "timeout"


def test_real_device_work_start_summary_orders_start_checks() -> None:
    original_snapshot = server.get_development_snapshot

    def fake_snapshot(**kwargs: object) -> dict:
        return {
            "ok": True,
            "repo": {"branch": "main", "commit": "abc123", "dirty_count": 0},
            "real_device_access": {
                "status": "ready",
                "selected_target": "192.0.2.44",
                "counts": {"reachable_clean": 1},
                "recommendations": [],
                "next_read_only_checks": [],
            },
            "runtime_access": {"runtime_keymap_readable": True, "paths": []},
            "output_readiness": {"issues": []},
        }

    server.get_development_snapshot = fake_snapshot
    try:
        summary = server.get_real_device_work_start_summary()
    finally:
        server.get_development_snapshot = original_snapshot

    assert summary["ok"] is True
    assert summary["status"] == "ready_for_real_device_work"
    assert summary["selected_target"] == "192.0.2.44"
    assert [item["step"] for item in summary["ordered_steps"]] == [
        "select_target",
        "confirm_local_checkout",
        "confirm_runtime_readiness",
        "confirm_output_readiness",
        "choose_next_action",
    ]
    assert summary["blockers"] == []
    assert any("does not run pull" in note for note in summary["notes"])


def test_real_device_work_start_summary_surfaces_access_blockers() -> None:
    original_snapshot = server.get_development_snapshot

    def fake_snapshot(**kwargs: object) -> dict:
        return {
            "ok": True,
            "repo": {"branch": "main", "commit": "abc123", "dirty_count": 2},
            "real_device_access": {
                "status": "unreachable",
                "selected_target": None,
                "counts": {"ssh_error_kinds": {"host_key_verification_failed": 1}},
                "recommendations": ["fix known_hosts"],
                "next_read_only_checks": [{"error_kind": "host_key_verification_failed", "commands": ["ssh-keygen -F host"]}],
            },
            "runtime_access": {
                "runtime_keymap_readable": False,
                "paths": [{"path": "/mnt/p3/keymap.json", "exists": True, "readable": False}],
            },
            "output_readiness": {"issues": [{"area": "hid_broker", "severity": "info"}]},
        }

    server.get_development_snapshot = fake_snapshot
    try:
        summary = server.get_real_device_work_start_summary()
    finally:
        server.get_development_snapshot = original_snapshot

    assert summary["status"] == "needs_review"
    assert {item["area"] for item in summary["blockers"]} == {
        "real_device_access",
        "local_checkout",
        "runtime_access",
        "output_readiness",
    }
    assert summary["ordered_steps"][0]["checks"][0]["error_kind"] == "host_key_verification_failed"
    runtime_blocker = next(item for item in summary["blockers"] if item["area"] == "runtime_access")
    output_blocker = next(item for item in summary["blockers"] if item["area"] == "output_readiness")
    assert runtime_blocker["unreadable_paths"][0]["path"] == "/mnt/p3/keymap.json"
    assert "check_runtime_access" in runtime_blocker["next_read_only_checks"][0]
    assert output_blocker["issue_sample"][0]["area"] == "hid_broker"
    assert "get_runtime_issue_summary" in output_blocker["next_read_only_checks"][1]


def test_http_status_summary_redacts_credentials_and_summarizes_payload() -> None:
    payload = {
        "processes": {"httpd": True, "logicd": True, "matrixd": False, "spid": False},
        "hid": {"device": "/dev/hidg0", "exists": True, "connected": True, "udc_state": "configured"},
        "mode": "gadget",
        "output_target": "auto",
        "output": {"display_label": "AUTO USB", "runtime_mode_label": "USB"},
        "hid_broker": {
            "owner": "hidloom-hidd",
            "process": True,
            "broker_ready": False,
            "hid_report_socket": {"path": "/tmp/usbd_hid_reports.sock", "exists": True},
            "hidd_hid_report_socket_env": "/tmp/usbd_hid_reports.sock",
            "hid_report_socket_enabled_env": "1",
            "logicd_broker_enabled_env": "",
        },
        "text_send": {"available": True, "runner_ready": False, "real_send_allowed": False, "blocking_reasons": ["no-runner"]},
        "bluetooth": {"available": True, "powered": True, "pairable": False, "discoverable": False, "paired_devices": ["a"], "connected_devices": []},
        "wifi": {"available": True, "powered": True, "connected": True, "blocked": False, "recovery_first": True, "persistent_power_off": False},
        "spid": {"process": True, "events_socket": {"exists": False}, "ctrl_socket": {"exists": True}},
    }
    summary = server._summarize_http_status(payload)
    assert summary["processes"]["ok"] is False
    assert summary["processes"]["inactive"] == ["matrixd"]
    assert summary["processes"]["required_inactive"] == ["matrixd"]
    assert summary["processes"]["optional_inactive"] == ["spid"]
    assert "spid" in summary["processes"]["optional"]
    assert summary["hid_broker"]["broker_ready"] is False
    assert summary["hid_broker"]["owner"] == "hidloom-hidd"
    assert summary["usbd"]["broker_ready"] is False
    assert summary["text_send"]["blocking_reasons"] == ["no-runner"]
    assert summary["bluetooth"]["paired_count"] == 1


def test_output_readiness_combines_preflight_and_http_status() -> None:
    preflight = {
        "ok": True,
        "summary": {"config_ok": True, "services_ok": True, "hid_devices_present": True, "sockets_present": True},
        "routes": {
            "KC_A": {"endpoint": "/dev/hidg2"},
            "KC_ZKHK": {"endpoint": "/dev/hidg0"},
            "KC_HENKAN": {"endpoint": "/dev/hidg0"},
            "KC_KANA": {"endpoint": "/dev/hidg0"},
        },
        "service_status": {"services": {"logicd": "active"}},
    }
    http_status = {
        "ok": True,
        "summary": {
            "hid": {"connected": True},
            "hid_broker": {
                "owner": "hidloom-hidd",
                "broker_ready": False,
                "hidd_hid_report_socket_env": "/tmp/usbd_hid_reports.sock",
                "logicd_broker_enabled_env": "",
                "hid_report_socket": {"exists": True},
            },
            "text_send": {"real_send_allowed": False, "blocking_reasons": ["runner_missing"]},
            "processes": {"inactive": [], "optional_inactive": ["spid"]},
            "spid": {"process": False},
        },
    }
    readiness = server._output_readiness_from(preflight, http_status)
    assert readiness["ok"] is True
    assert readiness["readiness"]["hid_broker_ready"] is False
    assert readiness["readiness"]["usbd_broker_ready"] is False
    assert any(issue["area"] == "hid_broker" for issue in readiness["issues"])
    assert not any(issue["area"] == "spid" for issue in readiness["issues"])
    assert readiness["readiness"]["spid_active"] is False


def test_interface_snapshot_combines_http_vial_and_ble_without_writes() -> None:
    original_preflight = server.run_preflight
    original_http = server.get_http_status_summary
    original_runtime = server.get_runtime_state_summary

    def fake_preflight(include_systemctl: bool = True) -> dict:
        return {
            "ok": True,
            "summary": {"services_ok": True, "hid_devices_present": True, "sockets_present": True, "config_ok": True},
            "service_status": {"skipped": False, "services": {"httpd": "active", "viald": "active", "btd": "active"}},
        }

    def fake_http_status(timeout_sec: float = 2.0) -> dict:
        return {
            "ok": True,
            "http_status": 200,
            "summary": {
                "processes": {"ok": True, "inactive": []},
                "hid": {"connected": True, "device": "/dev/hidg0"},
                "output": {"display_label": "AUTO USB"},
                "wifi": {"connected": True},
                "bluetooth": {
                    "available": True,
                    "powered": True,
                    "pairable": False,
                    "discoverable": False,
                    "paired_count": 1,
                    "connected_count": 0,
                },
            },
        }

    def fake_runtime_state(include_keymap_diff: bool = False) -> dict:
        return {
            "bluetooth_hosts": {
                "host_count": 1,
                "hosts": [{"last_seen_name": "WINDOWS-TEST-HOST"}],
            }
        }

    server.run_preflight = fake_preflight
    server.get_http_status_summary = fake_http_status
    server.get_runtime_state_summary = fake_runtime_state
    try:
        snapshot = server.get_interface_snapshot()
    finally:
        server.run_preflight = original_preflight
        server.get_http_status_summary = original_http
        server.get_runtime_state_summary = original_runtime

    assert snapshot["ok"] is True
    assert snapshot["mode"] == "read_only"
    assert snapshot["http"]["ok"] is True
    assert snapshot["vial"]["service_active"] is True
    assert snapshot["ble"]["powered"] is True
    assert snapshot["ble"]["runtime_hosts"]["host_count"] == 1
    encoded = json.dumps(snapshot)
    assert "pair, forget" in encoded


def test_update_readiness_summary_maps_future_apply_prerequisites() -> None:
    original_access = server.check_runtime_access
    original_repo = server.get_repo_dirty_summary
    original_sync = server.get_sync_safety_plan
    original_http = server.get_http_status_summary

    def fake_access() -> dict:
        return {
            "runtime_keymap_readable": True,
            "user": "tester",
            "group": "tester",
            "paths": [
                {
                    "path": "/mnt/p3/keymap.json",
                    "exists": True,
                    "readable": True,
                    "writable": False,
                }
            ],
        }

    def fake_repo(repo_root: Path = ROOT, max_files: int = 20) -> dict:
        return {"dirty_count": 2, "runtime_attention_count": 1, "untracked_count": 1}

    def fake_sync(repo_root: Path = ROOT, target: str = "pi") -> dict:
        return {
            "architecture_warnings": [{"path": "bin/hidloom-key"}],
            "rsync_excludes": ["bin/hidloom-key"],
        }

    def fake_http(timeout_sec: float = 2.0) -> dict:
        return {
            "ok": True,
            "summary": {
                "output": {"display_label": "AUTO USB"},
                "bluetooth": {"available": True, "powered": True, "paired_count": 1, "connected_count": 0},
                "text_send": {"real_send_allowed": False, "blocking_reasons": ["explicit_host_profile_required"]},
            },
        }

    server.check_runtime_access = fake_access
    server.get_repo_dirty_summary = fake_repo
    server.get_sync_safety_plan = fake_sync
    server.get_http_status_summary = fake_http
    try:
        summary = server.get_update_readiness_summary()
    finally:
        server.check_runtime_access = original_access
        server.get_repo_dirty_summary = original_repo
        server.get_sync_safety_plan = original_sync
        server.get_http_status_summary = original_http

    assert summary["ok"] is True
    assert summary["mode"] == "read_only"
    assert summary["summary"]["apply_tools_recommended_now"] is False
    assert summary["surfaces"]["keymap_update"]["readiness"]["runtime_keymap_writable_by_current_user"] is False
    assert summary["surfaces"]["selective_sync"]["readiness"]["architecture_warning_count"] == 1
    assert summary["surfaces"]["key_or_text_send"]["readiness"]["blocking_reasons"] == ["explicit_host_profile_required"]
    assert any("plan/dry-run" in item for item in summary["recommendations"])
    assert "does not write keymaps" in summary["notes"][0]


def test_runtime_issue_summary_explains_broker_and_safety_gates() -> None:
    readiness = {
        "ok": True,
        "readiness": {"core_preflight_ok": True, "usb_keyboard_routes_ok": True},
        "issues": [
            {"area": "hid_broker", "severity": "info", "detail": {"logicd_broker_enabled_env": ""}},
            {"area": "text_send", "severity": "info", "detail": ["runner_missing"]},
        ],
    }
    units = {
        "services": {
            "hidloom-hidd": {"expected_environment": {"missing": ["USBD_HID_REPORT_SOCKET"]}},
            "hidloom-outputd": {"expected_environment": {"missing": []}},
            "hidloom-logicd-core": {"expected_environment": {"missing": []}},
        }
    }
    issues = server._runtime_issue_items_from(readiness, units)
    assert issues[0]["area"] == "hid_broker"
    assert issues[0]["probable_cause"] == "hidd_report_socket_missing"
    assert issues[1]["blocking_reasons"] == ["runner_missing"]


def test_runtime_state_summary_redacts_full_runtime_json() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        keymap = root / "keymap.json"
        led = root / "led_state.json"
        bt = root / "bluetooth_hosts.json"
        board = root / "board_profile.json"
        keymap.write_text((ROOT / "config" / "default" / "keymap.json").read_text(encoding="utf-8"), encoding="utf-8")
        led.write_text(json.dumps({"mode": 3, "speed": 20, "h": 1, "s": 2, "v": 3}), encoding="utf-8")
        bt.write_text(
            json.dumps(
                {
                    "version": 1,
                    "hosts": {
                        "AA:BB:CC:DD:EE:FF": {
                            "last_seen_name": "WINDOWS-TEST-HOST",
                            "last_connected_at": "now",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        board.write_text(json.dumps({"board_version": "ver1.0", "prototype": False, "device_name": "dev01"}), encoding="utf-8")
        summary = server.get_runtime_state_summary(
            keymap_path=keymap,
            led_state_path=led,
            bluetooth_hosts_path=bt,
            board_profile_path=board,
            include_keymap_diff=True,
        )
    assert summary["ok"] is True
    assert summary["keymap"]["layer_count"] >= 1
    assert summary["led_state"]["mode"] == 3
    assert summary["bluetooth_hosts"]["host_count"] == 1
    assert summary["board_profile"]["board_version"] == "ver1.0"
    encoded = json.dumps(summary)
    assert "AA:BB:CC:DD:EE:FF" not in encoded


def test_codex_mcp_status_redacts_config_and_checks_registration() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        bin_dir = Path(tmp) / "bin"
        bin_dir.mkdir()
        fake_codex = bin_dir / "codex"
        fake_codex.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_codex.chmod(0o755)
        config = Path(tmp) / "config.toml"
        config.write_text(
            f"""
[projects."{ROOT}"]
trust_level = "trusted"

[mcp_servers.keyboard]
command = "python3"
args = ["{ROOT / "dev" / "mcp" / "keyboard" / "server.py"}", "--stdio"]
env = {{ SECRET_TOKEN = "do-not-return" }}
bearer_token_env_var = "ALSO_DO_NOT_RETURN"
""".strip(),
            encoding="utf-8",
        )
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{old_path}"
        try:
            status = server.get_codex_mcp_status(config_path=config)
        finally:
            os.environ["PATH"] = old_path
    assert status["ok"] is True
    assert status["mode"] == "read_only"
    assert status["project"]["trusted"] is True
    assert status["keyboard_server"]["configured"] is True
    assert status["keyboard_server"]["matches_this_checkout"] is True
    assert status["keyboard_server"]["has_env"] is True
    encoded = json.dumps(status)
    assert "do-not-return" not in encoded
    assert "ALSO_DO_NOT_RETURN" not in encoded


def test_sync_safety_plan_excludes_native_artifacts() -> None:
    assert server.DEFAULT_REAL_DEVICE_REPO_ROOT == "/srv/hidloom"
    assert server.DEFAULT_REAL_DEVICE_TARGETS == ("keyboard.example",)
    plan = server.get_sync_safety_plan(target="pi@example")
    assert plan["ok"] is True
    assert plan["mode"] == "read_only"
    assert plan["target"] == "pi@example"
    assert "daemon/matrixd/matrixd" in plan["rsync_excludes"]
    assert "bin/hidloom-key" in plan["rsync_excludes"]
    assert plan["standard_update"] == "split_debian_packages"
    assert "rsync -az --delete" in plan["legacy_recovery_rsync_example"]
    assert any("core-deb-package" in command for command in plan["cross_build_commands"])
    assert any("hidloom-profile keyboard-ver1" in command for command in plan["install_and_verify_commands"])
    assert not any("make clean all" in command for command in plan["cross_build_commands"])
    assert not any("rebuild on Raspberry Pi" in item for item in plan["notes"])
    assert any(item["path"] == "daemon/matrixd/matrixd" for item in plan["native_artifacts"])


def test_systemd_unit_summary_redacts_environment_and_uses_allowlist() -> None:
    parsed = server._parse_systemd_environment(
        "LOG_LEVEL=INFO SECRET_TOKEN=abc LOGICD_USBD_HID_REPORT_BROKER=1 USBD_HID_REPORT_SOCKET_ENABLED=1"
    )
    assert parsed["safe_values"]["LOGICD_USBD_HID_REPORT_BROKER"] == "1"
    assert parsed["safe_values"]["USBD_HID_REPORT_SOCKET_ENABLED"] == "1"
    assert parsed["redacted"] == [{"name": "SECRET_TOKEN", "value": "<redacted>"}]

    assert "hidloom-logicd-core" in server.DEFAULT_SERVICES
    assert "logicd-companion" in server.DEFAULT_SERVICES
    assert "logicd" not in server.DEFAULT_SERVICES
    assert "logicd" in server.DIAGNOSTIC_SERVICES

    repo_unit = server._repo_unit_metadata("hidloom-logicd-core")
    assert repo_unit["exists"] is True
    assert repo_unit["relative_path"] == "system/systemd/hidloom-logicd-core.service"
    assert "LOGICD_CORE_HID_REPORT_SOCKET" in repo_unit["environment_names"]
    assert "LOGICD_CORE_HID_REPORT_SOCKET" in repo_unit["safe_environment_values"]
    usb_unit = server._repo_unit_metadata("hidloom-usb-gadget")
    assert usb_unit["exists"] is True
    assert usb_unit["relative_path"] == "system/systemd/hidloom-usb-gadget.service"
    spid_unit = server._repo_unit_metadata("spid")
    assert spid_unit["exists"] is True
    assert spid_unit["relative_path"] == "system/systemd/spid.service"

    skipped = server.get_systemd_unit_summary(service="hidloom-logicd-core", execute=False)
    assert skipped["ok"] is True
    assert skipped["skipped"] is True
    assert "systemctl" in skipped["command"][0]

    rejected = server.get_systemd_unit_summary(service="ssh", execute=False)
    assert rejected["ok"] is False
    assert "service must be one of" in rejected["error"]


def test_codex_task_mailbox_summary_counts_without_bodies() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for dirname in ("inbox", "running", "done", "failed"):
            (root / dirname).mkdir()
        (root / "inbox" / "task-a.task.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "id": "task-a",
                    "mode": "read_only",
                    "requested_by": "desktop-codex",
                    "summary": "short summary",
                    "checks": ["systemctl is-active logicd"],
                }
            ),
            encoding="utf-8",
        )
        (root / "done" / "task-a.result.json").write_text(
            json.dumps(
                {
                    "status": "done",
                    "task": {"id": "task-a", "mode": "read_only", "summary": "short summary", "checks": ["x"]},
                    "checks": [{"stdout": "do-not-return", "stderr": "also-hidden"}],
                    "errors": [],
                }
            ),
            encoding="utf-8",
        )
        (root / "done" / "task-a.result.md").write_text("secret body should not return", encoding="utf-8")
        summary = server.get_codex_task_mailbox_summary(tasks_dir=root, max_items=5)
    assert summary["ok"] is True
    assert summary["pending_count"] == 1
    assert summary["sections"]["inbox"]["count"] == 1
    assert summary["sections"]["done"]["json_count"] == 1
    assert summary["result_pairs"] == [{"status": "done", "id": "task-a", "json": True, "markdown": True}]
    inbox_summary = summary["sections"]["inbox"]["latest"][0]["json_summary"]
    assert inbox_summary["id"] == "task-a"
    assert inbox_summary["check_count"] == 1
    assert inbox_summary["result_check_count"] == 0
    encoded = json.dumps(summary)
    assert "secret body" not in encoded
    assert "do-not-return" not in encoded


def test_mcp_methods() -> None:
    tools = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert tools is not None
    names = {item["name"] for item in tools["result"]["tools"]}
    assert names == {
        "get_status",
        "get_usb_split_status",
        "explain_route_for_keycode",
        "run_preflight",
        "get_keymap_summary",
        "collect_journal_excerpt",
        "check_runtime_access",
        "get_script_summary",
        "preview_hid_report",
        "inspect_key_position",
        "get_repo_state",
        "get_repo_dirty_summary",
        "get_checkout_hygiene_summary",
        "get_checkout_drift_summary",
        "get_pull_readiness_summary",
        "get_checkout_cleanup_candidates",
        "get_checkout_preserve_diff_summary",
        "get_checkout_backup_plan_summary",
        "get_manual_cleanup_verification_plan",
        "get_cleanup_review_order_summary",
        "get_reflection_cleanup_alignment_summary",
        "get_temporary_change_restore_plan_summary",
        "get_real_device_experiment_workflow_summary",
        "get_real_device_access_summary",
        "get_development_snapshot",
        "get_real_device_work_start_summary",
        "get_codex_mcp_status",
        "get_sync_safety_plan",
        "get_selective_sync_plan",
        "get_reflection_apply_plan",
        "get_systemd_unit_summary",
        "get_codex_task_mailbox_summary",
        "get_http_status_summary",
        "get_output_readiness_summary",
        "get_interface_snapshot",
        "get_update_readiness_summary",
        "get_runtime_issue_summary",
        "get_runtime_state_summary",
    }

    call = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "explain_route_for_keycode", "arguments": {"keycode": "KC_HENKAN"}},
        }
    )
    assert call is not None
    text = call["result"]["content"][0]["text"]
    payload = json.loads(text)
    assert payload["route"]["endpoint"] == "/dev/hidg0"


def test_stdio_framed_initialize_and_tool_list() -> None:
    input_data = b"".join(
        [
            _frame({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            _frame({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        ]
    )
    proc = subprocess.run(
        [sys.executable, str(ROOT / "dev" / "mcp" / "keyboard" / "server.py"), "--stdio"],
        input=input_data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    first, second = proc.stdout.split(b"Content-Length: ", 2)[1:]
    initialize = _read_frame(b"Content-Length: " + first)
    tools = _read_frame(b"Content-Length: " + second)

    assert initialize["result"]["serverInfo"]["name"] == "hidloom-keyboard"
    assert "Read-only diagnostics" in initialize["result"]["instructions"]
    assert "service restarts" in initialize["result"]["instructions"]
    assert {tool["name"] for tool in tools["result"]["tools"]} == {
        "get_status",
        "get_usb_split_status",
        "explain_route_for_keycode",
        "run_preflight",
        "get_keymap_summary",
        "collect_journal_excerpt",
        "check_runtime_access",
        "get_script_summary",
        "preview_hid_report",
        "inspect_key_position",
        "get_repo_state",
        "get_repo_dirty_summary",
        "get_checkout_hygiene_summary",
        "get_checkout_drift_summary",
        "get_pull_readiness_summary",
        "get_checkout_cleanup_candidates",
        "get_checkout_preserve_diff_summary",
        "get_checkout_backup_plan_summary",
        "get_manual_cleanup_verification_plan",
        "get_cleanup_review_order_summary",
        "get_reflection_cleanup_alignment_summary",
        "get_temporary_change_restore_plan_summary",
        "get_real_device_experiment_workflow_summary",
        "get_real_device_access_summary",
        "get_development_snapshot",
        "get_real_device_work_start_summary",
        "get_codex_mcp_status",
        "get_sync_safety_plan",
        "get_selective_sync_plan",
        "get_reflection_apply_plan",
        "get_systemd_unit_summary",
        "get_codex_task_mailbox_summary",
        "get_http_status_summary",
        "get_output_readiness_summary",
        "get_interface_snapshot",
        "get_update_readiness_summary",
        "get_runtime_issue_summary",
        "get_runtime_state_summary",
    }


def main() -> None:
    test_status_reads_repo_config()
    test_usb_split_reports_known_shape()
    test_route_explains_keyboard_mouse_consumer_and_split_keyboard()
    test_run_preflight_collects_read_only_summary()
    test_keymap_summary_reports_default_diffs_and_attention_actions()
    test_collect_journal_excerpt_is_bounded_and_allowlisted()
    test_check_runtime_access_reports_identity_and_paths()
    test_check_runtime_access_recommends_keymap_permission_fix()
    test_script_summary_reports_labels_and_safety()
    test_preview_hid_report_for_keyboard_and_consumer()
    test_inspect_key_position_reports_layers_and_previews()
    test_repo_state_reports_git_checkout()
    test_repo_dirty_summary_classifies_status_lines()
    test_checkout_hygiene_summary_flags_untracked_directories()
    test_checkout_drift_summary_attributes_reflection_and_runtime_changes()
    test_pull_readiness_blocks_dirty_runtime_and_reflection_drift()
    test_checkout_cleanup_candidates_separates_preserve_and_cleanup()
    test_checkout_preserve_diff_summary_redacts_diff_hunks()
    test_checkout_backup_plan_summary_returns_manual_commands_only()
    test_manual_cleanup_verification_plan_blocks_until_backup_confirmed()
    test_cleanup_review_order_summary_prioritizes_preserve_then_cleanup()
    test_reflection_cleanup_alignment_summary_uses_local_reference_only()
    test_temporary_change_restore_plan_summary_lists_stashes_without_applying()
    test_real_device_experiment_workflow_summary_blocks_dirty_checkout_without_mutating()
    test_real_device_access_summary_prefers_reachable_clean_target_without_writes()
    test_real_device_access_summary_classifies_ssh_probe_errors()
    test_selective_sync_plan_is_read_only_and_uses_dirty_categories()
    test_reflection_apply_plan_is_read_only_operator_checklist()
    test_reflection_apply_plan_blocks_selected_directories()
    test_development_snapshot_collects_compact_sections()
    test_development_snapshot_can_include_real_device_access_summary()
    test_real_device_work_start_summary_orders_start_checks()
    test_real_device_work_start_summary_surfaces_access_blockers()
    test_http_status_summary_redacts_credentials_and_summarizes_payload()
    test_output_readiness_combines_preflight_and_http_status()
    test_runtime_issue_summary_explains_broker_and_safety_gates()
    test_runtime_state_summary_redacts_full_runtime_json()
    test_codex_mcp_status_redacts_config_and_checks_registration()
    test_sync_safety_plan_excludes_native_artifacts()
    test_systemd_unit_summary_redacts_environment_and_uses_allowlist()
    test_codex_task_mailbox_summary_counts_without_bodies()
    test_mcp_methods()
    test_stdio_framed_initialize_and_tool_list()
    print("ok: keyboard MCP server")


if __name__ == "__main__":
    main()
