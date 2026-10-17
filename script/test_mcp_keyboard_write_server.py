#!/usr/bin/env python3
"""Regression checks for the guarded keyboard-write MCP companion."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dev.mcp.keyboard_write import server


def test_versioned_release_imports_packaged_dependencies() -> None:
    with tempfile.TemporaryDirectory() as raw:
        release_root = Path(raw) / "release"
        write_root = release_root / "dev" / "mcp" / "keyboard_write"
        write_root.mkdir(parents=True)
        shutil.copy2(ROOT / "dev/mcp/keyboard_write/server.py", write_root / "server.py")

        env = dict(os.environ)
        inherited_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(
            part for part in (str(ROOT), inherited_pythonpath) if part
        )
        completed = subprocess.run(
            [sys.executable, str(write_root / "server.py"), "--help"],
            cwd=release_root,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        assert "--stdio" in completed.stdout


def _keymap(path: Path, action: str = "KC_A") -> None:
    path.write_text(
        json.dumps(
            {
                "_layout_def": {"alpha": [[1, 1, "SW11"]]},
                "layers": [{"_name": "L0", "alpha": [action]}],
            }
        )
        + "\n",
        encoding="utf-8",
    )


class FakeCtrl:
    def __init__(self, *, action: str = "KC_A", save_ok: bool = True) -> None:
        self.action = action
        self.save_ok = save_ok
        self.calls: list[dict] = []
        self.pressed: list[list[int]] = []
        self.owner_action = None
        self.layer_revision = 1
        self.outcomes = {}
        self.tap_count = 0
        self.drop_tap_response = False

    def __call__(self, command: dict) -> dict:
        self.calls.append(dict(command))
        kind = command["t"]
        if kind == "G":
            return {
                "t": "keymap",
                "layers": [{"1,1": self.action}],
                "active": {"all": [0]},
                "output_target": "auto",
            }
        if kind == "K":
            return {"t": "matrix", "pressed": self.pressed}
        if kind == "CONTROL_OWNER":
            return {"result": "ok", "coordinator_epoch": "test-coordinator", "runtime_revision": 1, "persisted": True,
                    "capabilities": ["keymap_compare_apply", "guarded_tap"],
                    "owner": {"owner_epoch": "test-owner", "keymap_revision": 1, "layer_revision": self.layer_revision,
                              "capabilities": ["guarded_tap"], "effective_action": self.owner_action or self.action,
                              "idle": not self.pressed, "output_revision": 1}}
        if kind == "KEYMAP_COMPARE_APPLY":
            assert command["expected_coordinator_epoch"] == "test-coordinator"
            assert command["expected_owner"]["owner_epoch"] == "test-owner"
            self.action = command["a"]
            return {"result": "ok" if self.save_ok else "error", "runtime_applied": True, "persisted": self.save_ok}
        if kind == "GUARDED_TAP":
            assert command["expected_action"] == self.action
            if command["expected_layer_revision"] != self.layer_revision:
                return {"result": "error"}
            operation_id = command["operation_id"]
            if operation_id not in self.outcomes:
                self.tap_count += 1
                self.outcomes[operation_id] = {"result": "ok", "operation_id": operation_id, "status": "released"}
            if self.drop_tap_response:
                raise OSError("fixture dropped response after owner press")
            return self.outcomes[operation_id]
        if kind == "GUARDED_OPERATION":
            return {"operation": self.outcomes.get(command["operation_id"], {"result": "unknown"})}
        if kind == "M":
            self.action = str(command["a"])
            return {"t": "M", "result": "ok"}
        if kind == "S":
            return {"t": "S", "result": "ok" if self.save_ok else "error", "path": "/mnt/p3/keymap.json"}
        raise AssertionError(command)


def test_keymap_plan_and_apply() -> None:
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "keymap.json"
        _keymap(path)
        ctrl = FakeCtrl()
        plan = server.plan_keymap_change(0, 1, 1, "KC_B", keymap_path=path, query_ctrl=ctrl)
        assert plan["ok"] is True
        assert plan["executed"] is False
        assert plan["before"]["action"] == "KC_A"
        assert plan["after"]["action"] == "KC_B"
        assert plan["confirmation_phrase"].startswith("APPLY_KEYMAP_CHANGE ")
        assert ctrl.calls == [{"t": "G"}, {"t": "K"}, {"t": "CONTROL_OWNER"}]

        rejected = server.apply_keymap_change(
            0,
            1,
            1,
            "KC_B",
            expected_sha256=plan["keymap_sha256"],
            confirm="wrong",
            keymap_path=path,
            query_ctrl=ctrl,
        )
        assert rejected["ok"] is False
        assert rejected["executed"] is False
        assert ctrl.calls == [{"t": "G"}, {"t": "K"}, {"t": "CONTROL_OWNER"}] * 2

        def saving_ctrl(command: dict) -> dict:
            response = ctrl(command)
            if command["t"] == "KEYMAP_COMPARE_APPLY" and response["result"] == "ok":
                _keymap(path, ctrl.action)
            return response

        fresh = server.plan_keymap_change(0, 1, 1, "KC_B", keymap_path=path, query_ctrl=saving_ctrl)
        applied = server.apply_keymap_change(
            0,
            1,
            1,
            "KC_B",
            expected_sha256=fresh["keymap_sha256"],
            confirm=fresh["confirmation_phrase"],
            keymap_path=path,
            query_ctrl=saving_ctrl,
        )
        assert applied["ok"] is True
        assert applied["executed"] is True
        assert applied["readback"]["live_action"] == "KC_B"
        assert applied["readback"]["persisted_action"] == "KC_B"
        assert ctrl.action == "KC_B"


def test_keymap_digest_and_save_failure_guards() -> None:
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "keymap.json"
        _keymap(path)
        ctrl = FakeCtrl(save_ok=False)
        plan = server.plan_keymap_change(0, 1, 1, "KC_B", keymap_path=path, query_ctrl=ctrl)
        mismatch = server.apply_keymap_change(
            0,
            1,
            1,
            "KC_B",
            expected_sha256="0" * 64,
            confirm=plan["confirmation_phrase"],
            keymap_path=path,
            query_ctrl=ctrl,
        )
        assert mismatch["ok"] is False
        assert mismatch["blocker"] == "keymap_digest_changed"
        assert not any(call["t"] in {"M", "KEYMAP_COMPARE_APPLY"} for call in ctrl.calls)

        failed = server.apply_keymap_change(
            0,
            1,
            1,
            "KC_B",
            expected_sha256=plan["keymap_sha256"],
            confirm=plan["confirmation_phrase"],
            keymap_path=path,
            query_ctrl=ctrl,
        )
        assert failed["ok"] is False
        assert failed["executed"] is True
        assert failed["rollback"]["attempted"] is False
        assert failed["rollback"]["confirmation_required"] is True
        assert ctrl.action == "KC_B"
        assert sum(call["t"] == "KEYMAP_COMPARE_APPLY" for call in ctrl.calls) == 1
        assert not any(call["t"] in {"M", "S"} for call in ctrl.calls)


def test_keymap_readback_failure_preserves_newer_work() -> None:
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "keymap.json"
        _keymap(path)
        ctrl = FakeCtrl()
        plan = server.plan_keymap_change(0, 1, 1, "KC_B", keymap_path=path, query_ctrl=ctrl)
        result = server.apply_keymap_change(
            0,
            1,
            1,
            "KC_B",
            expected_sha256=plan["keymap_sha256"],
            confirm=plan["confirmation_phrase"],
            keymap_path=path,
            query_ctrl=ctrl,
        )
        assert result["ok"] is False
        assert result["blocker"] == "apply_or_readback_unconfirmed"
        assert result["rollback"]["attempted"] is False
        assert result["rollback"]["confirmation_required"] is True
        assert ctrl.action == "KC_B"
        assert not any(call["t"] in {"M", "S"} for call in ctrl.calls)


def test_keymap_file_bounds() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        keymap = root / "keymap.json"
        _keymap(keymap)
        alias = root / "alias.json"
        alias.symlink_to(keymap)
        try:
            server.plan_keymap_change(0, 1, 1, "KC_B", keymap_path=alias, query_ctrl=FakeCtrl())
        except ValueError as exc:
            assert "non-symlink" in str(exc)
        else:
            raise AssertionError("symlink keymap was accepted")

        oversized = root / "oversized.json"
        oversized.write_bytes(b" " * (server.MAX_KEYMAP_BYTES + 1))
        try:
            server.plan_key_tap(1, 1, keymap_path=oversized, query_ctrl=FakeCtrl())
        except ValueError as exc:
            assert "exceeds" in str(exc)
        else:
            raise AssertionError("oversized keymap was accepted")


def test_control_status_is_bounded_and_secret_free() -> None:
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "keymap.json"
        _keymap(path)
        original = server.keyboard_read.get_output_readiness_summary
        server.keyboard_read.get_output_readiness_summary = lambda **_: {"ok": True, "issues": []}
        try:
            result = server.get_control_status(keymap_path=path, query_ctrl=FakeCtrl())
        finally:
            server.keyboard_read.get_output_readiness_summary = original
        assert result["ok"] is True
        assert len(result["keymap"]["sha256"]) == 64
        assert result["credentials_returned"] is False
        serialized = json.dumps(result).lower()
        assert "password" not in serialized
        assert "token" not in serialized


def test_key_tap_is_dry_run_by_default_and_always_releases() -> None:
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "keymap.json"
        _keymap(path)
        ctrl = FakeCtrl()
        sent: list[str] = []
        plan = server.plan_key_tap(1, 1, keymap_path=path, query_ctrl=ctrl)
        assert plan["ok"] is True
        assert plan["effective_action"] == "KC_A"
        assert plan["confirmation_phrase"].startswith("SEND_MATRIX_TAP ")

        dry = server.send_key_tap(
            1,
            1,
            expected_sha256=plan["keymap_sha256"],
            confirm="",
            keymap_path=path,
            query_ctrl=ctrl,
            send_event=sent.append,
            sleep=lambda _: None,
        )
        assert dry["executed"] is False
        assert sent == []

        executed = server.send_key_tap(
            1,
            1,
            expected_sha256=plan["keymap_sha256"],
            confirm=plan["confirmation_phrase"],
            keymap_path=path,
            query_ctrl=ctrl,
            send_event=sent.append,
            sleep=lambda _: None,
        )
        assert executed["ok"] is True
        assert executed["executed"] is True
        assert sent == [], "unguarded raw matrix transport must never be used"
        assert ctrl.tap_count == 1
        assert executed["owner_result"]["status"] == "released"
        ctrl.drop_tap_response = True
        recovered = server.send_key_tap(1, 1, expected_sha256=plan["keymap_sha256"], confirm=plan["confirmation_phrase"],
            keymap_path=path, query_ctrl=ctrl, send_event=sent.append)
        assert recovered["ok"] and ctrl.tap_count == 1 and sent == []
        ctrl.layer_revision += 1
        changed = server.send_key_tap(1, 1, expected_sha256=plan["keymap_sha256"], confirm=plan["confirmation_phrase"],
            keymap_path=path, query_ctrl=ctrl, send_event=sent.append)
        assert not changed["ok"] and ctrl.tap_count == 1 and sent == []
        ctrl.owner_action = "KC_ENT"
        mismatch = server.plan_key_tap(1, 1, keymap_path=path, query_ctrl=ctrl)
        assert not mismatch["ok"] and "executing_owner_action_mismatch" in mismatch["blockers"]
        _keymap(path, "KC_ENT")
        mismatch = server.plan_key_tap(1, 1, keymap_path=path, query_ctrl=FakeCtrl())
        assert not mismatch["ok"] and "live_keymap_has_unpersisted_changes" in mismatch["blockers"]


def test_unsafe_action_and_pressed_state_are_blocked() -> None:
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "keymap.json"
        _keymap(path, "KC_SH1")
        unsafe = server.plan_key_tap(1, 1, keymap_path=path, query_ctrl=FakeCtrl(action="KC_SH1"))
        assert unsafe["ok"] is False
        assert "unsafe_action" in unsafe["blockers"]

        _keymap(path, "KC_A")
        ctrl = FakeCtrl()
        ctrl.pressed = [[2, 2]]
        pressed = server.plan_key_tap(1, 1, keymap_path=path, query_ctrl=ctrl)
        assert pressed["ok"] is False
        assert "owner_not_idle" in pressed["blockers"]


def test_keymap_change_blocks_unpersisted_or_pressed_state() -> None:
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "keymap.json"
        _keymap(path, "KC_A")
        drifted = server.plan_keymap_change(0, 1, 1, "KC_C", keymap_path=path, query_ctrl=FakeCtrl(action="KC_B"))
        assert drifted["ok"] is False
        assert "live_keymap_has_unpersisted_changes" in drifted["blockers"]

        ctrl = FakeCtrl(action="KC_A")
        ctrl.pressed = [[1, 1]]
        pressed = server.plan_keymap_change(0, 1, 1, "KC_C", keymap_path=path, query_ctrl=ctrl)
        assert pressed["ok"] is False
        assert "matrix_not_idle" in pressed["blockers"]


def test_mcp_boundary_and_tool_list() -> None:
    init = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert init is not None
    assert init["result"]["serverInfo"]["name"] == "hidloom-keyboard-write"
    listed = server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert listed is not None
    names = {item["name"] for item in listed["result"]["tools"]}
    assert names == {
        "get_control_status",
        "plan_key_tap",
        "send_key_tap",
        "plan_keymap_change",
        "apply_keymap_change",
    }
    assert "restart_keyboard_service" not in names
    assert "run_shell" not in names
    tools = {item["name"]: item for item in listed["result"]["tools"]}
    assert set(tools["send_key_tap"]["inputSchema"]["required"]) == {
        "row", "col", "expected_sha256", "confirm"
    }
    assert set(tools["apply_keymap_change"]["inputSchema"]["required"]) == {
        "layer", "row", "col", "action", "expected_sha256", "confirm"
    }


def main() -> None:
    test_versioned_release_imports_packaged_dependencies()
    test_keymap_plan_and_apply()
    test_keymap_digest_and_save_failure_guards()
    test_keymap_readback_failure_preserves_newer_work()
    test_keymap_file_bounds()
    test_control_status_is_bounded_and_secret_free()
    test_key_tap_is_dry_run_by_default_and_always_releases()
    test_unsafe_action_and_pressed_state_are_blocked()
    test_keymap_change_blocks_unpersisted_or_pressed_state()
    test_mcp_boundary_and_tool_list()
    print("ok: guarded keyboard-write MCP companion")


if __name__ == "__main__":
    main()
