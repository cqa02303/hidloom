#!/usr/bin/env python3
"""Regression checks for remote boot baseline collection helper."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import remote_boot_baseline_collect as remote  # noqa: E402


def main() -> None:
    remote_target = "pi" + "@" + "keyboard.test"
    assert remote.safe_name(remote_target) == "pi_keyboard.test"
    assert remote.safe_name("///") == "remote"
    assert remote.local_scp_source(Path("/c/Users/operator/repo/tools/helper.py")) == (
        "C:\\Users\\operator\\repo\\tools\\helper.py"
    )
    assert remote.local_scp_source(Path("tools/helper.py")) == "tools/helper.py"

    ssh = remote.ssh_command("pi@host", "hostname", connect_timeout=7)
    assert ssh[:5] == ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=7"]
    assert ssh[-2:] == ["pi@host", "hostname"]

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
    assert "python3 /tmp/helper.py --output /tmp/out/sample-01-boot-baseline.md --no-http-status" in script
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
    assert "sudo -n python3 /tmp/helper.py --output /tmp/out/sample-01-boot-baseline.md --no-http-status" in sudo_script

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
                    "## Readiness Timeline",
                    "",
                    "| time_sec | delta_sec | kind | label | source | confidence | message |",
                    "| ---: | ---: | --- | --- | --- | --- | --- |",
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
        assert timeline["hidd"] == "14.406"
        assert timeline["input"] == "15.621"
        assert timeline["network"] == "34.298"
        assert remote.keyboard_ready_at(timeline) == "15.621"
        assert remote.timeline_delta(timeline, "usb", "input") == "1.236"
        assert remote.timeline_delta(timeline, "hidd", "input") == "1.215"
        assert remote.timeline_delta(timeline, "input", "ssh") == "0.821"
        assert remote.timeline_delta(timeline, "input", "network") == "18.677"
        assert remote.timeline_delta(timeline, "missing", "input") == ""
        assert remote.keyboard_ready_at({"hidd": "14.406"}) == "14.406"
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
        assert "15.621 | 1.236 | 1.215 | 0.821 | 18.677" in summary
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

    print("ok: remote boot baseline collection helper")


if __name__ == "__main__":
    main()
