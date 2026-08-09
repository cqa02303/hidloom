#!/usr/bin/env python3
"""Regression checks for remote boot baseline collection helper."""
from __future__ import annotations

import os
from pathlib import Path
from pathlib import PurePosixPath
import stat
import subprocess
from types import SimpleNamespace
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import remote_boot_baseline_collect as remote  # noqa: E402


def main() -> None:
    remote_target = "pi" + "@" + "keyboard.test"
    assert remote.safe_name(remote_target) == "pi_keyboard.test"
    assert remote.safe_name("///") == "remote"
    assert remote.local_scp_source(PurePosixPath("/c/Users/operator/repo/tools/helper.py")) == (
        "C:\\Users\\operator\\repo\\tools\\helper.py"
    )
    assert remote.local_scp_source(Path("tools/helper.py")) == str(Path("tools/helper.py"))
    bash_path = remote.bash_local_path(Path("build/artifacts/example"))
    if os.name == "nt":
        assert "\\" not in bash_path
        assert bash_path[1:3] == ":/"
    else:
        assert bash_path == "build/artifacts/example"

    ssh = remote.ssh_command("pi@host", "hostname", connect_timeout=7)
    assert ssh[:5] == ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=7"]
    assert ssh[-2:] == ["pi@host", "hostname"]

    utf8_probe = "設定読み込み完了\n"
    utf8_result = remote.run_with_input(
        [
            sys.executable,
            "-c",
            "import sys; print(sys.stdin.buffer.read().hex())",
        ],
        utf8_probe,
        timeout=3.0,
    )
    assert utf8_result.returncode == 0
    assert utf8_result.stdout.strip().startswith("設定読み込み完了".encode("utf-8").hex())

    uploaded: list[tuple[list[str], str, float]] = []
    original_run_with_input = remote.run_with_input

    def fake_run_with_input(command: list[str], stdin: str, *, timeout: float) -> remote.CommandResult:
        uploaded.append((command, stdin, timeout))
        return remote.CommandResult(command, 0, "", "", 0.0)

    remote.run_with_input = fake_run_with_input
    try:
        upload_result = remote.upload_text_file("pi@host", "/tmp/helper.py", "print('ok')\n", connect_timeout=7)
        remote.upload_helper("pi@host", "/tmp/helper.py", "print('ok')\n", connect_timeout=7)
    finally:
        remote.run_with_input = original_run_with_input
    assert upload_result.returncode == 0
    assert uploaded[0][0][-2] == "pi@host"
    assert "cat > /tmp/helper.py" in uploaded[0][0][-1]
    assert uploaded[0][1] == "print('ok')\n"
    assert len(uploaded) == 2

    fallback_runs: list[list[str]] = []
    original_run = remote.run

    def fake_failed_upload(command: list[str], stdin: str, *, timeout: float) -> remote.CommandResult:
        return remote.CommandResult(command, 1, "", "upload failed", 0.0)

    def fake_fallback_run(command: list[str], *, timeout: float) -> remote.CommandResult:
        fallback_runs.append(command)
        return remote.CommandResult(command, 0, "", "", 0.0)

    remote.run_with_input = fake_failed_upload
    remote.run = fake_fallback_run
    try:
        remote.upload_helper("pi@host", "/tmp/helper.py", "print('ok')\n", connect_timeout=7)
    finally:
        remote.run_with_input = original_run_with_input
        remote.run = original_run
    assert fallback_runs
    assert fallback_runs[0][0] == "scp"
    assert fallback_runs[0][-1] == "pi@host:/tmp/helper.py"

    script = remote.remote_collect_script(
        "/tmp/helper.py",
        "/tmp/out",
        "sample-01",
        no_http_status=True,
    )
    assert "umask 077" in script
    assert "report=/tmp/out/sample-01-boot-baseline.md" in script
    assert "python3 /tmp/helper.py --no-http-status > \"$report_tmp\"" in script
    assert "--output" not in script
    assert "test -s \"$report_tmp\"" in script
    assert "mv -- \"$report_tmp\" \"$report\"" in script
    assert "systemd-analyze blame" in script
    assert "lsmod | egrep 'dwc2|libcomposite|configfs|usb_f_hid|g_hid'" in script
    assert "## module availability" in script
    assert "modules.builtin" in script
    assert "modules.dep" in script
    assert "ls -l /dev/hidg*" in script
    sudo_script = remote.remote_collect_script(
        "/tmp/helper.py",
        "/tmp/out",
        "sample-01",
        no_http_status=True,
        sudo=True,
    )
    assert "sudo -n python3 /tmp/helper.py --no-http-status > \"$report_tmp\"" in sudo_script
    assert "sudo -n python3 /tmp/helper.py --output" not in sudo_script

    if os.name != "nt":
        with tempfile.TemporaryDirectory(prefix="hidloom-remote-permissions-") as raw_tmp:
            work = Path(raw_tmp)
            helper = work / "collector.py"
            helper.write_text(
                "#!/usr/bin/env python3\nprint('# fixture boot report')\n",
                encoding="utf-8",
            )
            fake_bin = work / "bin"
            fake_bin.mkdir()
            fake_sudo = fake_bin / "sudo"
            fake_sudo.write_text(
                "#!/bin/sh\n"
                "if [ \"${1-}\" = -n ]; then shift; fi\n"
                "exec \"$@\"\n",
                encoding="utf-8",
            )
            fake_sudo.chmod(0o755)
            remote_out = work / "remote-out"
            permission_script = remote.remote_collect_script(
                str(helper),
                str(remote_out),
                "root-helper",
                no_http_status=True,
                sudo=True,
            )
            environment = os.environ.copy()
            environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"
            completed = subprocess.run(
                [remote.bash_executable(), "-c", permission_script],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                env=environment,
            )
            assert completed.returncode == 0, completed.stderr
            user_report = remote_out / "root-helper-boot-baseline.md"
            report_details = user_report.stat()
            assert report_details.st_uid == os.getuid()
            assert stat.S_IMODE(report_details.st_mode) == 0o600
            assert user_report.read_text(encoding="utf-8") == "# fixture boot report\n"

    if os.name != "nt":
        with tempfile.TemporaryDirectory(prefix="hidloom-remote-tar-failure-") as raw_tmp:
            work = Path(raw_tmp)
            fake_bin = work / "bin"
            fake_bin.mkdir()
            fake_ssh = fake_bin / "ssh"
            fake_ssh.write_text(
                "#!/bin/sh\n"
                "tar -cf - --files-from /dev/null\n"
                "echo 'tar: ./root-0600-report.md: Cannot open: Permission denied' >&2\n"
                "exit 2\n",
                encoding="utf-8",
            )
            fake_ssh.chmod(0o755)
            original_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{fake_bin}{os.pathsep}{original_path}"
            try:
                try:
                    remote.copy_remote_dir(
                        "pi@host",
                        "/tmp/root-0600-fixture",
                        work / "copied",
                        connect_timeout=2,
                        required_name="sample-boot-baseline.md",
                    )
                except SystemExit as exc:
                    failure = str(exc)
                    assert "command failed (2)" in failure
                    assert "root-0600-report.md" in failure
                else:
                    raise AssertionError("upstream unreadable tar failure must propagate")
            finally:
                os.environ["PATH"] = original_path

    original_run = remote.run

    def fake_successful_copy(command: list[str], *, timeout: float) -> remote.CommandResult:
        assert command[1:4] == ["-o", "pipefail", "-c"]
        assert command[0].endswith("bash") or command[0].endswith("bash.exe")
        return remote.CommandResult(command, 0, "", "", 0.0)

    with tempfile.TemporaryDirectory(prefix="hidloom-remote-missing-report-") as raw_tmp:
        remote.run = fake_successful_copy
        try:
            try:
                remote.copy_remote_dir(
                    "pi@host",
                    "/tmp/fixture",
                    Path(raw_tmp),
                    connect_timeout=2,
                    required_name="required-boot-baseline.md",
                )
            except SystemExit as exc:
                assert "copied artifact is missing" in str(exc)
            else:
                raise AssertionError("missing required report must fail")
        finally:
            remote.run = original_run

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        (out / "pi-sample-01-systemd-analyze.txt").write_text(
            "Startup finished in 1.000s (kernel) + 2.000s (userspace) = 3.000s\n",
            encoding="utf-8",
        )
        (out / "pi-sample-01-systemd-blame.txt").write_text(
            "1.000s NetworkManager.service\n",
            encoding="utf-8",
        )
        (out / "pi-sample-01-snapshot.txt").write_text(
            "## modules\n## module availability\n/lib/modules/example/libcomposite.ko.xz\n## hidg\n",
            encoding="utf-8",
        )
        (out / "pi-sample-01-boot-baseline.md").write_text(
            "\n".join(
                [
                    "# Boot Marker Baseline",
                    "",
                    "- early_runtime_tree: `present`",
                    "- early_ready_uptime_seconds: `2.125000`",
                    "- gadget_udc_name: `3f980000.usb`",
                    "- gadget_udc_state: `configured`",
                    f"- accepted_manifest_sha256: `{'a' * 64}`",
                    f"- tryboot_receipt_sha256: `{'b' * 64}`",
                    "- tryboot_activation: `default_boot_modified=false,one_shot_requested=false,reboot_requested=false,tryboot_published_last=true`",
                    "",
                    "## Readiness Timeline",
                    "",
                    "| time_sec | delta_sec | kind | label | source | confidence | message |",
                    "| ---: | ---: | --- | --- | --- | --- | --- |",
                    "| 2.125 |  | early-usb-ready | early gadget bound | /run/hidloom-early/gadget-bound.json | runtime-marker | state=bound kernel_release=fixture |",
                    "| 12.050 | 9.925 | usb-adopt | early gadget adopted | hidloom_usb_gadget_start.sh[404] | known | Early USB gadget adopted without configfs mutation |",
                    "| 14.385 |  | usb-gadget | usb gadget configured | setup_usb_gadget.sh[1] | known | USB HID gadget configured |",
                    "| 14.406 | 0.021 | hid-broker | hidd broker active | systemd[1] | known | Started hidloom-hidd.service |",
                    "| 15.287 | 0.881 | input-core | logicd-core active | systemd[1] | known | Started hidloom-logicd-core.service |",
                    "| 15.621 | 0.334 | input-ready | matrixd connected to logic owner | matrixd[1] | known | logicd に接続しました |",
                    "| 17.693 | 2.072 | socket-ready | logicd sockets listening | logicd[1] | known | Listening on /tmp/key_events.sock |",
                    "| 16.442 | -1.251 | network-access | ssh listening | sshd[1] | known | Server listening on 0.0.0.0 port 22. |",
                    "| 34.298 | 17.856 | network-ready | network connected | NetworkManager[1] | known | CONNECTED_GLOBAL |",
                    "",
                    "## Systemd Unit Markers",
                ]
            ),
            encoding="utf-8",
        )
        timeline = remote.parse_boot_timeline((out / "pi-sample-01-boot-baseline.md").read_text(encoding="utf-8"))
        assert timeline["usb"] == "14.385"
        assert timeline["early"] == "2.125"
        assert timeline["adopt"] == "12.050"
        assert timeline["hidd"] == "14.406"
        assert timeline["input"] == "15.621"
        assert timeline["network"] == "34.298"
        assert remote.keyboard_ready_at(timeline) == "15.621"
        assert remote.timeline_delta(timeline, "usb", "input") == "1.236"
        assert remote.timeline_delta(timeline, "early", "adopt") == "9.925"
        assert remote.timeline_delta(timeline, "early", "input") == "13.496"
        assert remote.timeline_delta(timeline, "hidd", "input") == "1.215"
        assert remote.timeline_delta(timeline, "input", "ssh") == "0.821"
        assert remote.timeline_delta(timeline, "input", "network") == "18.677"
        assert remote.timeline_delta(timeline, "missing", "input") == ""
        assert remote.keyboard_ready_at({"hidd": "14.406"}) == "14.406"
        metadata = remote.parse_report_metadata(
            (out / "pi-sample-01-boot-baseline.md").read_text(encoding="utf-8")
        )
        assert metadata["early_runtime_tree"] == "present"
        assert metadata["gadget_udc_name"] == "3f980000.usb"
        assert metadata["gadget_udc_state"] == "configured"
        assert metadata["accepted_manifest_sha256"] == "a" * 64
        assert metadata["tryboot_receipt_sha256"] == "b" * 64
        assert metadata["tryboot_activation"].startswith("default_boot_modified=false")
        unit_fallback = remote.parse_boot_timeline(
            "\n".join(
                [
                    "## Readiness Timeline",
                    "",
                    "| time_sec | delta_sec | kind | label | source | confidence | message |",
                    "| ---: | ---: | --- | --- | --- | --- | --- |",
                    "| 12.000 |  | unit-active | hidloom-usb-gadget.service active | hidloom-usb-gadget.service | systemd | ActiveState=active SubState=exited |",
                    "| 12.100 | 0.100 | unit-active | hidloom-hidd.service active | hidloom-hidd.service | systemd | ActiveState=active SubState=running |",
                    "| 12.400 | 0.300 | unit-active | hidloom-logicd-core.service active | hidloom-logicd-core.service | systemd | ActiveState=active SubState=running |",
                    "| 12.800 | 0.400 | unit-active | matrixd.service active | matrixd.service | systemd | ActiveState=active SubState=running |",
                    "| 13.500 | 0.700 | unit-active | ssh.service active | ssh.service | systemd | ActiveState=active SubState=running |",
                    "| 26.000 | 12.500 | unit-active | NetworkManager.service active | NetworkManager.service | systemd | ActiveState=active SubState=running |",
                    "",
                    "## Systemd Unit Markers",
                ]
            )
        )
        assert unit_fallback == {
            "usb": "12.000",
            "hidd": "12.100",
            "core": "12.400",
            "input": "12.800",
            "ssh": "13.500",
            "network": "26.000",
        }
        preferred_input = remote.parse_boot_timeline(
            "\n".join(
                [
                    "## Readiness Timeline",
                    "",
                    "| time_sec | delta_sec | kind | label | source | confidence | message |",
                    "| ---: | ---: | --- | --- | --- | --- | --- |",
                    "| 12.800 |  | unit-active | matrixd.service active | matrixd.service | systemd | ActiveState=active SubState=running |",
                    "| 13.100 | 0.300 | input-ready | matrixd connected to logic owner | matrixd[1] | known | logicd に接続しました |",
                    "| 26.000 | 12.900 | unit-active | NetworkManager.service active | NetworkManager.service | systemd | ActiveState=active SubState=running |",
                    "| 34.000 | 8.000 | network-ready | network connected | NetworkManager[1] | known | CONNECTED_GLOBAL |",
                    "",
                    "## Systemd Unit Markers",
                ]
            )
        )
        assert preferred_input["input"] == "13.100"
        assert preferred_input["network"] == "34.000"
        summary = remote.render_summary("pi@host", out)
        assert "# Remote Boot Baseline Summary" in summary
        assert "NetworkManager.service" in summary
        assert "| `pi-sample-01` |" in summary
        assert "2.125 | 12.050 | 9.925 | 15.621 | 13.496 | 1.236 | 1.215 | 0.821 | 18.677" in summary
        assert "3f980000.usb | configured" in summary
        assert "a" * 64 in summary
        assert "b" * 64 in summary
        assert "default_boot_modified=false" in summary
        assert "| none | not loaded |" in summary

    assert remote.section_text("## modules\ndwc2 1\n## hidg\n", "## modules") == "dwc2 1"
    reboot_script = remote.remote_reboot_script("sudo -n systemctl reboot")
    assert "nohup sh -c" in reboot_script
    assert "sudo -n systemctl reboot" in reboot_script
    assert "/tmp/hidloom-remote-boot-reboot.log" in reboot_script

    calls: list[list[str]] = []
    original_run = remote.run

    def fake_run(command: list[str], *, timeout: float) -> remote.CommandResult:
        calls.append(command)
        return remote.CommandResult(command, 0, "", "", 0.0)

    remote.run = fake_run
    try:
        remote.wait_for_ssh(
            "pi@host",
            connect_timeout=2,
            boot_wait_timeout_sec=3,
            poll_sec=0.01,
            settle_sec=0,
        )
    finally:
        remote.run = original_run
    assert calls
    assert calls[0][-2:] == ["pi@host", "true"]

    remote.run = fake_run
    try:
        remote.require_ssh_transport("pi@host", connect_timeout=2)
    finally:
        remote.run = original_run

    with tempfile.TemporaryDirectory() as tmp:
        events: list[str] = []
        output_dir = Path(tmp) / "out"
        args = SimpleNamespace(
            target="pi@host",
            label="reboot-series",
            output_dir=output_dir,
            samples=3,
            interval_sec=0.0,
            remote_dir="/tmp/hidloom-remote-boot-baseline",
            remote_helper="/tmp/hidloom-boot_marker_baseline.py",
            connect_timeout=2,
            sample_timeout_sec=3.0,
            no_http_status=True,
            sudo=True,
            reboot_before_sample=True,
            reboot_command="sudo -n systemctl reboot",
            boot_wait_timeout_sec=3.0,
            boot_poll_sec=0.01,
            post_reboot_request_delay_sec=0.0,
            post_ssh_settle_sec=0.0,
        )
        original_parse_args = remote.parse_args
        original_require_ssh = remote.require_ssh_transport
        original_upload_helper = remote.upload_helper
        original_wait_for_ssh = remote.wait_for_ssh
        original_copy_remote_dir = remote.copy_remote_dir
        original_render_summary = remote.render_summary
        original_run = remote.run

        def fake_series_run(command: list[str], *, timeout: float) -> remote.CommandResult:
            remote_script = command[-1] if command and command[0] == "ssh" else ""
            if "boot-baseline.md" in remote_script:
                events.append("collect")
            return remote.CommandResult(command, 0, "", "", 0.0)

        def fake_series_copy(
            target: str,
            remote_dir: str,
            local_dir: Path,
            *,
            connect_timeout: int,
            required_name: str | None = None,
        ) -> None:
            assert target == "pi@host"
            assert remote_dir.startswith("/tmp/hidloom-remote-boot-baseline-reboot-series-")
            assert local_dir == output_dir
            assert connect_timeout == 2
            assert required_name is not None
            assert required_name.endswith("-boot-baseline.md")
            events.append("copy")

        remote.parse_args = lambda: args
        remote.require_ssh_transport = lambda *unused, **unused_kwargs: None
        remote.upload_helper = lambda *unused, **unused_kwargs: None
        remote.wait_for_ssh = lambda *unused, **unused_kwargs: None
        remote.copy_remote_dir = fake_series_copy
        remote.render_summary = lambda target, local_dir: "# summary\n"
        remote.run = fake_series_run
        try:
            remote.main()
        finally:
            remote.parse_args = original_parse_args
            remote.require_ssh_transport = original_require_ssh
            remote.upload_helper = original_upload_helper
            remote.wait_for_ssh = original_wait_for_ssh
            remote.copy_remote_dir = original_copy_remote_dir
            remote.render_summary = original_render_summary
            remote.run = original_run
        assert events == ["collect", "copy", "collect", "copy", "collect", "copy"]
        assert (output_dir / "summary.md").read_text(encoding="utf-8") == "# summary\n"

    def fake_failed_run(command: list[str], *, timeout: float) -> remote.CommandResult:
        return remote.CommandResult(command, 255, "", "Permission denied", 0.0)

    remote.run = fake_failed_run
    try:
        try:
            remote.require_ssh_transport("pi@host", connect_timeout=2)
        except SystemExit as exc:
            assert "SSH transport preflight failed" in str(exc)
            assert "Permission denied" in str(exc)
        else:
            raise AssertionError("require_ssh_transport should fail")
    finally:
        remote.run = original_run

    timeout_result = remote.run(
        ["python3", "-c", "import time; time.sleep(1)"],
        timeout=0.01,
    )
    assert timeout_result.returncode == 124
    assert "TIMEOUT after 0.0s" in timeout_result.stderr or "TIMEOUT after 0.1s" in timeout_result.stderr

    readme = (ROOT / "tools" / "README.md").read_text(encoding="utf-8")
    assert "remote_boot_baseline_collect.py" in readme
    assert "<keyboard-host>" in readme
    assert "accepted manifest hash" in readme
    assert "tryboot receipt hash" in readme

    print("ok: remote boot baseline collection helper")


if __name__ == "__main__":
    main()
