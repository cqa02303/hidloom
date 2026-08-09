#!/usr/bin/env python3
"""Regression checks for the boot marker baseline helper."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import boot_marker_baseline as boot  # noqa: E402


def main() -> None:
    assert "hidloom-usb-gadget.service" in boot.DEFAULT_UNITS
    assert "logicd.service" in boot.DEFAULT_UNITS
    assert "logicd-companion.service" in boot.DEFAULT_UNITS
    assert "matrixd.service" in boot.DEFAULT_UNITS
    assert "usbd.service" in boot.DEFAULT_UNITS
    assert "hidloom-hidd.service" in boot.DEFAULT_UNITS
    assert "hidloom-uidd.service" in boot.DEFAULT_UNITS
    assert "hidloom-outputd.service" in boot.DEFAULT_UNITS
    assert "hidloom-logicd-core.service" in boot.DEFAULT_UNITS
    assert "NetworkManager.service" in boot.DEFAULT_UNITS
    assert "ssh.service" in boot.DEFAULT_UNITS
    assert "hidloom-network-late.service" in boot.DEFAULT_UNITS
    assert "/tmp/usbd_hid_reports.sock" in boot.DEFAULT_SOCKET_PATHS
    assert "/tmp/uidd_reports.sock" in boot.DEFAULT_SOCKET_PATHS
    assert "/tmp/hidloom_output_reports.sock" in boot.DEFAULT_SOCKET_PATHS
    assert "/tmp/hidloom_output_ctrl.sock" in boot.DEFAULT_SOCKET_PATHS
    assert "/tmp/matrix_events_shadow.sock" in boot.DEFAULT_SOCKET_PATHS
    assert "/run/hidloom/outputd-status.json" in boot.DEFAULT_STATUS_PATHS
    assert "/run/hidloom/uidd-status.json" in boot.DEFAULT_STATUS_PATHS
    assert "/run/hidloom/logicd-core-status.json" in boot.DEFAULT_STATUS_PATHS

    marker = boot.parse_systemctl_show(
        "logicd.service",
        "\n".join(
            [
                "ActiveState=active",
                "SubState=running",
                "ExecMainStartTimestampMonotonic=1234000",
                "ActiveEnterTimestampMonotonic=2345000",
            ]
        ),
    )
    assert marker.unit == "logicd.service"
    assert marker.active_state == "active"
    assert marker.sub_state == "running"
    assert marker.exec_start_sec == 1.234
    assert marker.active_enter_sec == 2.345

    known = boot.classify_journal_marker(
        "[   15.621301] <keyboard-host> matrixd[611]: logicd に接続しました: /tmp/matrix_events.sock"
    )
    assert known is not None
    assert known.kind == "input-ready"
    assert known.label == "matrixd connected to logic owner"
    assert known.confidence == "known"

    hidd_known = boot.classify_journal_marker(
        "[   13.205073] <keyboard-host> systemd[1]: Started hidloom-hidd.service - CQA02303v5 native HID report broker (hidloom-hidd)."
    )
    assert hidd_known is not None
    assert hidd_known.kind == "hid-broker"
    assert hidd_known.label == "hidd broker active"

    adopt_known = boot.classify_journal_marker(
        "[    4.275100] <keyboard-host> hidloom_usb_gadget_start.sh[404]: "
        "Early USB gadget adopted without configfs mutation"
    )
    assert adopt_known is not None
    assert adopt_known.kind == "usb-adopt"
    assert adopt_known.label == "early gadget adopted"

    wrapper_usb_known = boot.classify_journal_marker(
        "[   11.546000] <keyboard-host> hidloom_usb_gadget_start.sh[421]: "
        "USB HID gadget configured"
    )
    assert wrapper_usb_known is not None
    assert wrapper_usb_known.kind == "usb-gadget"

    outputd_known = boot.classify_journal_marker(
        "[   14.181437] <keyboard-host> systemd[1]: Started hidloom-outputd.service - CQA02303v5 native HID report output router (hidloom-outputd)."
    )
    assert outputd_known is not None
    assert outputd_known.kind == "output-router"

    uidd_known = boot.classify_journal_marker(
        "[   14.164758] <keyboard-host> systemd[1]: Started hidloom-uidd.service - CQA02303v5 native uinput report sink (hidloom-uidd)."
    )
    assert uidd_known is not None
    assert uidd_known.kind == "uinput-sink"

    discovered = boot.classify_journal_marker(
        "[   21.000000] <keyboard-host> customd[777]: widget bus ready for boot probe"
    )
    assert discovered is not None
    assert discovered.kind == "journal-discovered"
    assert discovered.confidence == "discovered"

    result = boot.CommandResult(
        title="boot journal marker candidates",
        command=["journalctl", "-b"],
        returncode=0,
        stdout="\n".join(
            [
                "[   15.621301] <keyboard-host> matrixd[611]: logicd に接続しました: /tmp/matrix_events.sock",
                "[   21.000000] <keyboard-host> customd[777]: widget bus ready for boot probe",
            ]
        ),
        stderr="",
        elapsed_sec=0.0,
    )
    hidg_result = boot.CommandResult(
        title="hidg devices",
        command=["python", "glob:/dev/hidg*"],
        returncode=0,
        stdout="/dev/hidg0 mode=660 uid=0 gid=999\n",
        stderr="",
        elapsed_sec=0.0,
    )
    socket_snapshot = boot.SocketSnapshot(
        path="/tmp/logicd_core_ctrl.sock",
        exists=True,
        is_socket=True,
        mode="660",
        uid=0,
        gid=0,
        error="",
    )
    status_snapshot = boot.StatusSnapshot(
        path="/run/hidloom/logicd-core-status.json",
        exists=True,
        valid_json=True,
        schema="logicd-core.status.v1",
        summary="schema=logicd-core.status.v1, process=False, output_enabled=False, state.pressed_matrix=0",
        raw='{"schema":"logicd-core.status.v1","output_enabled":false}',
        error="",
    )
    report = boot.render_report(
        [marker],
        [result, hidg_result],
        include_http_status=False,
        sockets=[socket_snapshot],
        statuses=[status_snapshot],
    )
    assert "# Boot Marker Baseline" in report
    assert "http_status: `skipped`" in report
    assert "## Readiness Timeline" in report
    assert "matrixd connected to logic owner" in report
    assert "discovered journal candidate" in report
    assert "| logicd.service | active | running | 1.234 | 2.345 |" in report
    assert "## Boot-Critical Socket Snapshots" in report
    assert "| `/tmp/logicd_core_ctrl.sock` | true | true | 660 | 0 | 0 |  |" in report
    assert "## Status Snapshots" in report
    assert "logicd-core.status.v1" in report
    assert "## Raw Command Results" in report
    assert "### hidg devices" in report
    assert "/dev/hidg0" in report
    assert "USB HID gadget configured" in boot.JOURNAL_GREP_PATTERN
    assert "Started hidloom-hidd" in boot.JOURNAL_GREP_PATTERN
    assert "Started hidloom-outputd" in boot.JOURNAL_GREP_PATTERN
    assert "logicd boot marker" in boot.JOURNAL_GREP_PATTERN
    assert "Early USB gadget adopted without configfs mutation" in boot.JOURNAL_GREP_PATTERN
    assert "接続" in boot.JOURNAL_GREP_PATTERN

    with tempfile.TemporaryDirectory(prefix="hidloom-early-evidence-test-") as raw_tmp:
        work = Path(raw_tmp)
        runtime = work / "run" / "hidloom-early"
        runtime.mkdir(parents=True)
        marker_path = runtime / "gadget-bound.json"
        marker_path.write_text(
            json.dumps(
                {
                    "schema": "hidloom.early-gadget-bound.v1",
                    "state": "bound",
                    "kernel_release": "6.18.34+rpt-rpi-v8",
                    "runtime_contract_sha256": "a" * 64,
                    "ready_uptime_seconds": 2.125,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (runtime / "e1-gadget.state").write_text("ready\n", encoding="utf-8")
        outside = work / "outside-secret"
        outside.write_text("must-not-be-read\n", encoding="utf-8")
        (runtime / "outside-link").symlink_to(outside)

        accepted = work / "var" / "lib" / "hidloom" / "early-boot" / "early-image.accepted.json"
        accepted.parent.mkdir(parents=True)
        accepted.write_text(
            json.dumps(
                {
                    "schema": "hidloom.rpi-os-early-initramfs.e1.v1",
                    "source": "fixture-source",
                    "kernel_release": "6.18.34+rpt-rpi-v8",
                    "runtime_contract": {"sha256": "a" * 64},
                    "profile": {"id": "keyboard-ver1", "sha256": "b" * 64},
                    "adopt": {
                        "packages": {
                            "core": {"name": "hidloom-core", "version": "1.0"},
                            "profile": {
                                "name": "hidloom-profile-keyboard-ver1",
                                "version": "1.0",
                            },
                        }
                    },
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        receipt = accepted.parent / "tryboot-install.json"
        receipt.write_text(
            json.dumps(
                {
                    "schema": "hidloom.rpi-os-early-tryboot-install.v1",
                    "status": "installed-disabled",
                    "source": "fixture-source",
                    "placement_sha256": "c" * 64,
                    "activation": {
                        "default_boot_modified": False,
                        "one_shot_requested": False,
                        "reboot_requested": False,
                        "tryboot_published_last": True,
                    },
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        configfs = work / "sys" / "kernel" / "config" / "usb_gadget"
        gadget = configfs / "cqa02303v5"
        gadget.mkdir(parents=True)
        (gadget / "UDC").write_text("3f980000.usb\n", encoding="utf-8")
        sys_udc = work / "sys" / "class" / "udc"
        state_dir = sys_udc / "3f980000.usb"
        state_dir.mkdir(parents=True)
        (state_dir / "state").write_text("configured\n", encoding="utf-8")

        before = {
            path: (path.read_bytes(), path.stat().st_mode)
            for path in (marker_path, accepted, receipt, gadget / "UDC", state_dir / "state")
        }
        evidence = boot.collect_early_boot_evidence(
            runtime_root=runtime,
            accepted_manifest_path=accepted,
            install_receipt_path=receipt,
            configfs_root=configfs,
            sys_class_udc_root=sys_udc,
            gadget_name="cqa02303v5",
            expected_kernel_release="6.18.34+rpt-rpi-v8",
        )
        after = {
            path: (path.read_bytes(), path.stat().st_mode)
            for path in before
        }
        assert after == before
        assert evidence.udc.bound is True
        assert evidence.udc.name == "3f980000.usb"
        assert evidence.udc.state == "configured"
        assert evidence.accepted_manifest.valid_json is True
        assert evidence.accepted_manifest.sha256
        assert evidence.accepted_manifest.details["profile"] == "keyboard-ver1"
        assert boot.trusted_accepted_runtime_contract(evidence.accepted_manifest) == "a" * 64
        assert evidence.install_receipt.details["activation"] == (
            "default_boot_modified=false,one_shot_requested=false,"
            "reboot_requested=false,tryboot_published_last=true"
        )
        link_snapshot = next(
            item for item in evidence.runtime_tree if item.path.endswith("outside-link")
        )
        assert link_snapshot.kind == "symlink"
        assert link_snapshot.preview == ""
        assert link_snapshot.error == "symlink not followed"
        early_markers = boot.early_timeline_markers(evidence)
        assert len(early_markers) == 1
        assert early_markers[0].time_sec == 2.125
        assert early_markers[0].kind == "early-usb-ready"

        evidence_report = boot.render_report(
            [],
            [],
            include_http_status=False,
            early_evidence=evidence,
        )
        assert "early_ready_uptime_seconds: `2.125000`" in evidence_report
        assert "gadget_udc_name: `3f980000.usb`" in evidence_report
        assert "gadget_udc_state: `configured`" in evidence_report
        assert f"accepted_manifest_sha256: `{evidence.accepted_manifest.sha256}`" in evidence_report
        assert "accepted_runtime_contract_sha256: `" + ("a" * 64) + "`" in evidence_report
        assert f"tryboot_receipt_sha256: `{evidence.install_receipt.sha256}`" in evidence_report
        assert "## Early Runtime Tree" in evidence_report
        assert "## USB Device Controller Snapshot" in evidence_report
        assert "## Installed E2 Evidence" in evidence_report
        assert "| early-usb-ready | early gadget bound |" in evidence_report

        bounded = boot.snapshot_evidence_file(
            accepted,
            "bounded accepted manifest",
            max_bytes=1,
            include_preview=False,
        )
        assert bounded.error
        assert "evidence bound" in bounded.error
        unbound = boot.snapshot_udc(
            configfs_root=configfs,
            sys_class_udc_root=sys_udc,
            gadget_name="cqa02303v5",
        )
        assert unbound.bound is True
        (gadget / "UDC").write_text("\n", encoding="utf-8")
        unbound = boot.snapshot_udc(
            configfs_root=configfs,
            sys_class_udc_root=sys_udc,
            gadget_name="cqa02303v5",
        )
        assert unbound.bound is False
        assert unbound.state == "unbound"

        valid_marker = {
            "schema": boot.EARLY_MARKER_SCHEMA,
            "state": "bound",
            "kernel_release": "6.18.34+rpt-rpi-v8",
            "runtime_contract_sha256": "a" * 64,
            "ready_uptime_seconds": 1.25,
        }

        def strict_fixture(
            name: str,
            payload: dict[str, object],
            *,
            nested: bool = False,
        ) -> boot.EarlyBootEvidence:
            strict_root = work / name
            marker_parent = strict_root / "stale" if nested else strict_root
            marker_parent.mkdir(parents=True)
            (marker_parent / "gadget-bound.json").write_text(
                json.dumps(payload) + "\n",
                encoding="utf-8",
            )
            return boot.collect_early_boot_evidence(
                runtime_root=strict_root,
                accepted_manifest_path=accepted,
                install_receipt_path=receipt,
                configfs_root=configfs,
                sys_class_udc_root=sys_udc,
                gadget_name="cqa02303v5",
                expected_kernel_release="6.18.34+rpt-rpi-v8",
            )

        wrong_schema = dict(valid_marker, schema="hidloom.early-gadget-bound.v0")
        wrong_schema_evidence = strict_fixture("wrong-schema", wrong_schema)
        assert boot.early_timeline_markers(wrong_schema_evidence) == []
        assert any(
            "schema mismatch" in item.error
            for item in wrong_schema_evidence.runtime_tree
        )

        wrong_contract = dict(valid_marker, runtime_contract_sha256="d" * 64)
        wrong_contract_evidence = strict_fixture("wrong-contract", wrong_contract)
        assert boot.early_timeline_markers(wrong_contract_evidence) == []
        assert any(
            "mismatch with accepted manifest" in item.error
            for item in wrong_contract_evidence.runtime_tree
        )

        wrong_kernel = dict(valid_marker, kernel_release="6.1.0-stale")
        wrong_kernel_evidence = strict_fixture("wrong-kernel", wrong_kernel)
        assert boot.early_timeline_markers(wrong_kernel_evidence) == []
        assert any(
            "kernel_release mismatch" in item.error
            for item in wrong_kernel_evidence.runtime_tree
        )

        nested_evidence = strict_fixture("nested-marker", valid_marker, nested=True)
        assert boot.early_timeline_markers(nested_evidence) == []
        nested_snapshot = next(
            item
            for item in nested_evidence.runtime_tree
            if item.path.endswith("stale/gadget-bound.json")
        )
        assert "non-canonical gadget-bound.json ignored" in nested_snapshot.error

        string_uptime = dict(valid_marker, ready_uptime_seconds="1.25")
        string_uptime_evidence = strict_fixture("string-uptime", string_uptime)
        assert boot.early_timeline_markers(string_uptime_evidence) == []
        assert any(
            "must be numeric" in item.error
            for item in string_uptime_evidence.runtime_tree
        )

        large_integer_json = work / "large-integer.json"
        large_integer_json.write_text(
            '{"value":' + ("9" * 5000) + "}\n",
            encoding="utf-8",
        )
        large_integer_snapshot = boot.snapshot_evidence_file(
            large_integer_json,
            "large integer JSON",
            max_bytes=32 * 1024,
            include_preview=True,
        )
        assert large_integer_snapshot.valid_json is False
        assert "invalid JSON" in large_integer_snapshot.error

        deep_json = work / "deep.json"
        deep_json.write_text(
            ("[" * 1200) + "0" + ("]" * 1200),
            encoding="utf-8",
        )
        original_json_loads = boot.json.loads

        def recursion_guard(value: object, *args: object, **kwargs: object) -> object:
            if isinstance(value, (str, bytes)) and len(value) > 2000 and value[:1] in ("[", b"["):
                raise RecursionError("fixture nesting exceeds decoder recursion bound")
            return original_json_loads(value, *args, **kwargs)

        boot.json.loads = recursion_guard
        try:
            deep_snapshot = boot.snapshot_evidence_file(
                deep_json,
                "deep JSON",
                max_bytes=32 * 1024,
                include_preview=True,
            )
            status_pathological = boot.snapshot_status_files(
                (str(large_integer_json), str(deep_json))
            )
        finally:
            boot.json.loads = original_json_loads
        assert deep_snapshot.valid_json is False
        assert "invalid JSON" in deep_snapshot.error
        assert [item.valid_json for item in status_pathological] == [False, False]
        assert all(item.error for item in status_pathological)

        large_root = work / "large-runtime"
        large_root.mkdir()
        for index in range(200):
            (large_root / f"entry-{index:03d}").write_text("x\n", encoding="utf-8")
        successful_scandir_entries = 0
        original_scandir = boot.os.scandir

        class CountingScandir:
            def __init__(self, inner: object) -> None:
                self.inner = inner

            def __enter__(self) -> "CountingScandir":
                self.inner.__enter__()  # type: ignore[attr-defined]
                return self

            def __exit__(self, *args: object) -> object:
                return self.inner.__exit__(*args)  # type: ignore[attr-defined]

            def __iter__(self) -> "CountingScandir":
                return self

            def __next__(self) -> object:
                nonlocal successful_scandir_entries
                item = next(self.inner)  # type: ignore[arg-type]
                successful_scandir_entries += 1
                return item

        boot.os.scandir = lambda path: CountingScandir(original_scandir(path))  # type: ignore[assignment]
        try:
            large_tree = boot.snapshot_early_runtime_tree(
                large_root,
                max_entries=8,
                max_depth=1,
            )
        finally:
            boot.os.scandir = original_scandir
        assert successful_scandir_entries == 9
        assert sum(item.kind == "file" for item in large_tree) == 8
        assert any(item.kind == "boundary" for item in large_tree)

        race_root = work / "race-runtime"
        race_dir = race_root / "race"
        race_dir.mkdir(parents=True)
        (race_dir / "pinned.txt").write_text("safe\n", encoding="utf-8")
        race_outside = work / "race-outside"
        race_outside.mkdir()
        (race_outside / "outside-secret.txt").write_text(
            "must-not-be-read\n",
            encoding="utf-8",
        )
        original_verify = boot.verify_queued_directory
        swapped = False

        def swap_before_verify(
            root_fd: int,
            queued: boot.QueuedDirectory,
        ) -> str:
            nonlocal swapped
            if queued.relative_parts == ("race",) and not swapped:
                race_dir.rename(race_root / "race-pinned")
                race_dir.symlink_to(race_outside, target_is_directory=True)
                swapped = True
            return original_verify(root_fd, queued)

        boot.verify_queued_directory = swap_before_verify
        try:
            race_tree = boot.snapshot_early_runtime_tree(race_root)
        finally:
            boot.verify_queued_directory = original_verify
        assert swapped is True
        assert not any(item.path.endswith("outside-secret.txt") for item in race_tree)
        assert not any("must-not-be-read" in item.preview for item in race_tree)
        assert any("no longer safe" in item.error for item in race_tree)

    readme = (ROOT / "tools" / "README.md").read_text(encoding="utf-8")
    assert "boot_marker_baseline.py" in readme
    assert "usable keyboard" in readme
    assert "`/run/hidloom-early`" in readme
    assert "`ready_uptime_seconds`" in readme
    assert "`usb-adopt`" in readme

    plan = (ROOT / "docs" / "ops" / "buildroot-fast-boot-experiment.md").read_text(encoding="utf-8")
    assert "tools/boot_marker_baseline.py" in plan
    assert "hidg ready" in plan
    assert "usable keyboard" in plan

    print("ok: boot marker baseline helper")


if __name__ == "__main__":
    main()
