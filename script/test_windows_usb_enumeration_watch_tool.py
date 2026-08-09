#!/usr/bin/env python3
"""Static and fixture checks for the Windows-native USB enumeration watcher."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "windows_usb_enumeration_watch.ps1"
VID = "ABCD"
PID = "0123"
SELECTORS = ("MI_00&COL01", "MI_01", "MI_02")
EXPECTED_PREFIXES = tuple(f"HID\\VID_{VID}&PID_{PID}&{selector}" for selector in SELECTORS)
Device = tuple[str, str]
Observation = tuple[int, str, object]


def normalize_instance_prefix(instance_id: str) -> str:
    parts = instance_id.upper().split("\\")
    return "\\".join(parts[:2])


def readiness(devices: list[Device]) -> bool:
    ready_prefixes = {
        normalize_instance_prefix(instance_id)
        for instance_id, status in devices
        if status.upper() == "OK"
    }
    return set(EXPECTED_PREFIXES).issubset(ready_prefixes)


@dataclass(frozen=True)
class FixtureResult:
    exit_code: int
    reason: str
    initial_disconnect_ms: int | None
    first_ready_ms: int | None
    post_ready_disconnect: bool
    final_ready: bool


def analyze_fixture(observations: list[Observation]) -> FixtureResult:
    """Model snapshots plus exact target operation events in chronological order."""
    assert observations
    baseline_ms, baseline_kind, baseline_payload = observations[0]
    assert baseline_ms == 0
    assert baseline_kind == "snapshot"
    assert isinstance(baseline_payload, list)
    last_devices: list[Device] = baseline_payload
    if not readiness(last_devices):
        return FixtureResult(
            20,
            "baseline_missing_required_selector",
            None,
            None,
            False,
            readiness(last_devices),
        )

    phase = "waiting_for_initial_disconnect"
    initial_disconnect: int | None = None
    first_ready: int | None = None
    post_ready_disconnect = False

    for elapsed_ms, kind, payload in observations[1:]:
        if kind == "event":
            assert isinstance(payload, tuple) and len(payload) == 2
            operation, instance_id = payload
            assert isinstance(operation, str) and isinstance(instance_id, str)
            if normalize_instance_prefix(instance_id) not in EXPECTED_PREFIXES:
                continue
            if operation != "deletion":
                continue
            if phase == "waiting_for_initial_disconnect":
                phase = "waiting_for_first_ready"
                initial_disconnect = elapsed_ms
            elif phase == "first_ready":
                assert first_ready is not None
                if elapsed_ms <= first_ready:
                    continue
                phase = "post_ready_disconnect"
                post_ready_disconnect = True
            continue

        assert kind == "snapshot"
        assert isinstance(payload, list)
        last_devices = payload
        ready = readiness(last_devices)
        if phase == "waiting_for_initial_disconnect" and not ready:
            phase = "waiting_for_first_ready"
            initial_disconnect = elapsed_ms
        elif phase == "waiting_for_first_ready" and ready:
            phase = "first_ready"
            first_ready = elapsed_ms
        elif phase == "first_ready" and not ready:
            phase = "post_ready_disconnect"
            post_ready_disconnect = True

    final_ready = readiness(last_devices)
    if post_ready_disconnect:
        return FixtureResult(
            23,
            "post_first_ready_disconnect_observed",
            initial_disconnect,
            first_ready,
            True,
            final_ready,
        )
    if initial_disconnect is None:
        return FixtureResult(21, "initial_disconnect_not_observed", None, None, False, final_ready)
    if first_ready is None:
        return FixtureResult(22, "no_readd_before_timeout", initial_disconnect, None, False, final_ready)
    if not final_ready:
        return FixtureResult(
            24,
            "final_required_selector_not_ready",
            initial_disconnect,
            first_ready,
            False,
            False,
        )
    return FixtureResult(0, "pass", initial_disconnect, first_ready, False, True)


def composite(suffix: str, status: str = "OK") -> list[Device]:
    return [
        (rf"HID\VID_{VID}&PID_{PID}&MI_00&COL01\{suffix}-MAIN", status),
        (rf"HID\VID_{VID}&PID_{PID}&MI_01\{suffix}-RAW", status),
        (rf"HID\VID_{VID}&PID_{PID}&MI_02\{suffix}-SUB", status),
    ]


def snapshot(elapsed_ms: int, devices: list[Device]) -> Observation:
    return elapsed_ms, "snapshot", devices


def pnp_event(elapsed_ms: int, operation: str, instance_id: str) -> Observation:
    return elapsed_ms, "event", (operation, instance_id)


def render_fixture(result: FixtureResult, final_devices: list[Device]) -> str:
    prefixes = sorted(
        {normalize_instance_prefix(instance_id) for instance_id, _status in final_devices}
    )
    return "\n".join(
        [
            "# Windows USB Enumeration Watch",
            f"- result: `{'pass' if result.exit_code == 0 else 'fail'}`",
            f"- reason: `{result.reason}`",
            f"- exit_code: `{result.exit_code}`",
            *[f"- normalized: `{prefix}`" for prefix in prefixes],
        ]
    )


def main() -> None:
    text = TOOL.read_text(encoding="utf-8")

    # Identity is always supplied by the operator. The active development VID/PID
    # belongs only in the candidate-specific runbook command, never a hidden default.
    candidate_vid = "1D" + "6B"
    candidate_pid = "01" + "05"
    for name in ("VendorId", "ProductId"):
        parameter = re.search(
            rf"\[Parameter\(Mandatory = \$true\)\]\s+\[ValidatePattern\('[^']+'\)\]\s+\[string\]\${name}",
            text,
        )
        assert parameter, name
    assert candidate_vid not in text.upper()
    assert candidate_pid not in text

    # PowerShell variable names are case-insensitive, so a parameter named $Pid
    # attempts to overwrite the automatic, read-only $PID process variable.
    assert not re.search(
        r"(?im)^\s*(?:\[[^\]\r\n]+\]\s*)*\$pid\b(?:\s*[,)=])",
        text,
    )
    assert "-ProductId $ProductId" in text

    # Mandatory PowerShell collection parameters reject empty collections and
    # empty string members unless the matching Allow* attribute is explicit.
    # Both states occur before WATCHER_READY on a normal five-second gate.
    empty_array_list = (
        "[AllowEmptyCollection()]\n"
        "        [System.Collections.ArrayList]$Transitions"
    )
    assert text.count(empty_array_list) == text.count(
        "[System.Collections.ArrayList]$Transitions"
    )
    assert (
        "[AllowEmptyCollection()]\n"
        "        [System.Collections.ArrayList]$EventRecords"
    ) in text
    assert (
        "[AllowEmptyString()]\n"
        "        [System.Collections.Generic.List[string]]$Lines"
    ) in text

    for selector in SELECTORS:
        assert f"'{selector}'" in text
    for required_contract in (
        "Get-PnpDevice -PresentOnly",
        "Register-CimIndicationEvent",
        "__InstanceOperationEvent WITHIN",
        "TargetInstance ISA 'Win32_PnPEntity'",
        "$targetInstance.DeviceID",
        "TIME_CREATED",
        "__InstanceCreationEvent",
        "__InstanceDeletionEvent",
        "expected_instance_prefix",
        "event_utc",
        "event_elapsed_ms",
        "dequeued_at_utc",
        "dequeued_elapsed_ms",
        "dequeue_delay_ms",
        "$_.instance_prefix -eq $expectedPrefix",
        "$ExpectedPrefixes -notcontains $instancePrefix",
        "Update-WatchStateFromDeletion",
        "watcher_ready_elapsed_ms",
        "target_operation_before_ready_zero",
        "delayed_initial_deletion_event_count",
        "$ElapsedMs -le [double]$firstReadyElapsedMs",
        "waiting_for_initial_disconnect",
        "waiting_for_first_ready",
        "post_first_ready_disconnect",
        "baseline_missing_required_selector",
        "no_readd_before_timeout",
        "final_required_selector_not_ready",
        "Write-AtomicReportBundle",
        "normalized_prefix_without_machine_suffix",
        "pnp_instance_events = @($pnpInstanceEvents)",
        "WATCHER_READY",
    ):
        assert required_contract in text, required_contract
    assert "[ValidateRange(5, 900)]" in text
    assert "[ValidateRange(50, 2000)]" in text
    assert text.startswith("#requires -Version 5.1")
    assert "$ExitInternalError = 70" in text
    assert "Win32_DeviceChangeEvent" not in text
    assert "device_change_events" not in text
    assert text.index("Register-CimIndicationEvent") < text.index("WATCHER_READY")
    assert text.count("(snapshot unavailable)") == 1

    # Both report files are staged together and become visible with one directory
    # rename. Publication errors use stderr plus exit 70 rather than Write-Error.
    assert "'report.json'" in text
    assert "'report.md'" in text
    assert "if (Test-Path -LiteralPath $bundlePath)" in text
    atomic_move = "Move-Item -LiteralPath $temporaryDirectory -Destination $bundlePath"
    assert text.count(atomic_move) == 1
    assert text.count("Move-Item -LiteralPath") == 1
    assert "[Console]::Error.WriteLine" in text
    assert "exit $ExitInternalError" in text
    assert "Write-Error" not in text

    forbidden_mutations = (
        "Disable-PnpDevice",
        "Enable-PnpDevice",
        "Uninstall-PnpDevice",
        "Update-PnpDevice",
        "pnputil",
    )
    implementation = re.sub(r"<#.*?#>", "", text, flags=re.DOTALL)
    for forbidden in forbidden_mutations:
        assert forbidden.lower() not in implementation.lower(), forbidden
    assert not re.search(
        r"(?im)^\s*(?:Restart-Computer|Stop-Computer|shutdown\.exe|reboot)(?:\s|$)",
        implementation,
    )

    baseline = composite("MACHINE-A")
    readded = composite("MACHINE-B")

    # Readiness is exact: USB parents, near HID names, and non-OK children do not
    # satisfy any expected HID child prefix.
    usb_parents: list[Device] = [
        (rf"USB\VID_{VID}&PID_{PID}&{selector}\PARENT-{index}", "OK")
        for index, selector in enumerate(SELECTORS)
    ]
    near_hid: list[Device] = [
        (rf"HID\VID_{VID}&PID_{PID}&MI_00\NEAR-MAIN", "OK"),
        (rf"HID\VID_{VID}&PID_{PID}&MI_010\NEAR-RAW", "OK"),
        (rf"HID\VID_{VID}&PID_{PID}&MI_02&COL01\NEAR-SUB", "OK"),
    ]
    non_ok = baseline.copy()
    non_ok[2] = (non_ok[2][0], "ERROR")
    assert readiness(baseline)
    assert not readiness(usb_parents)
    assert not readiness(near_hid)
    assert not readiness(non_ok)

    passed = analyze_fixture(
        [
            snapshot(0, baseline),
            snapshot(1000, baseline[:2]),
            snapshot(1300, []),
            snapshot(4800, readded[:1]),
            snapshot(5200, readded),
            snapshot(12000, readded),
        ]
    )
    assert passed == FixtureResult(0, "pass", 1000, 5200, False, True)

    # A remove/re-add cycle wholly between ready snapshots must still be driven by
    # the exact target deletion event.
    between_snapshots = analyze_fixture(
        [
            snapshot(0, baseline),
            pnp_event(1000, "deletion", baseline[0][0]),
            pnp_event(1100, "deletion", baseline[1][0]),
            pnp_event(2500, "creation", readded[0][0]),
            snapshot(3200, readded),
            snapshot(12000, readded),
        ]
    )
    assert between_snapshots == FixtureResult(0, "pass", 1000, 3200, False, True)

    # Delivery order is not event order: an initial deletion dequeued only after
    # first-ready must be classified by event time, not as a later disconnect.
    delayed_initial_event = analyze_fixture(
        [
            snapshot(0, baseline),
            snapshot(800, []),
            snapshot(1200, readded),
            pnp_event(700, "deletion", baseline[0][0]),
            snapshot(12000, readded),
        ]
    )
    assert delayed_initial_event == FixtureResult(0, "pass", 800, 1200, False, True)

    baseline_missing = analyze_fixture([snapshot(0, baseline[:2]), snapshot(1000, baseline)])
    assert baseline_missing.exit_code == 20
    no_disconnect = analyze_fixture([snapshot(0, baseline), snapshot(12000, baseline)])
    assert no_disconnect.exit_code == 21
    no_readd = analyze_fixture(
        [snapshot(0, baseline), snapshot(1000, []), snapshot(12000, readded[:2])]
    )
    assert no_readd.exit_code == 22

    post_ready_cycle = analyze_fixture(
        [
            snapshot(0, baseline),
            pnp_event(1000, "deletion", baseline[0][0]),
            snapshot(5000, readded),
            snapshot(7000, readded),
            pnp_event(7100, "deletion", readded[2][0]),
            pnp_event(7200, "creation", readded[2][0]),
            snapshot(9000, readded),
        ]
    )
    assert post_ready_cycle.exit_code == 23
    assert post_ready_cycle.post_ready_disconnect

    # Unrelated parent/VID events are ignored and cannot manufacture a disconnect.
    unrelated_events = analyze_fixture(
        [
            snapshot(0, baseline),
            pnp_event(1000, "deletion", usb_parents[0][0]),
            pnp_event(1500, "deletion", r"HID\VID_FFFF&PID_9999&MI_00&COL01\OTHER"),
            snapshot(12000, baseline),
        ]
    )
    assert unrelated_events.exit_code == 21

    final_not_ready = analyze_fixture(
        [
            snapshot(0, baseline),
            snapshot(1000, []),
            snapshot(5000, readded),
            snapshot(7000, readded[:2]),
        ]
    )
    assert final_not_ready.exit_code != 0
    assert not final_not_ready.final_ready

    report = render_fixture(passed, readded)
    assert "MACHINE-A" not in report
    assert "MACHINE-B" not in report
    assert rf"HID\VID_{VID}&PID_{PID}&MI_00&COL01" in report
    assert all("\\MACHINE" not in line for line in report.splitlines())

    readme = (ROOT / "tools" / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "docs" / "ops" / "rpi-os-early-initramfs-experiment.md").read_text(
        encoding="utf-8"
    )
    checklist = (ROOT / "docs" / "ops" / "real-device-test-checklist.md").read_text(
        encoding="utf-8"
    )
    inventory = (ROOT / "docs" / "ops" / "test-script-inventory.md").read_text(
        encoding="utf-8"
    )
    assert "windows_usb_enumeration_watch.ps1" in readme
    assert "-VendorId <VID> -ProductId <PID>" in readme
    assert "__InstanceOperationEvent" in readme
    assert "report.json" in readme and "report.md" in readme
    assert "windows_usb_enumeration_watch.ps1" in runbook
    assert f"-VendorId {candidate_vid} -ProductId {candidate_pid}" in runbook
    assert "exact HID child" in runbook
    assert "post-first-ready" in checklist
    assert "PnP instance operation" in inventory

    print("ok: Windows USB enumeration watcher static and fixture contract")


if __name__ == "__main__":
    main()
