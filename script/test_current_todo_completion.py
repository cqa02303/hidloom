#!/usr/bin/env python3
"""Regression checks that revived TODO items are visible after the archive audit."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    if not (ROOT / "docs" / "CURRENT_STATUS.md").is_file():
        print("ok: private TODO documentation is not shipped in the public source tree")
        return

    todo = (ROOT / "docs" / "TODO_PRIORITY.md").read_text(encoding="utf-8")
    status = (ROOT / "docs" / "CURRENT_STATUS.md").read_text(encoding="utf-8")
    checklist = (ROOT / "docs" / "ops" / "real-device-test-checklist.md").read_text(encoding="utf-8")
    design_todo = (ROOT / "docs" / "feature" / "design-todo-backlog.md").read_text(encoding="utf-8")
    sequence_design = (ROOT / "docs" / "feature" / "sequence-engine-design.md").read_text(encoding="utf-8")
    keycode_todo = (ROOT / "docs" / "keycode" / "unimplemented-keycodes.md").read_text(encoding="utf-8")
    m6_handoff = (ROOT / "docs" / "ops" / "real-device-next-start.md").read_text(encoding="utf-8")
    failure_patterns = (ROOT / "docs" / "ops" / "failure-patterns.md").read_text(encoding="utf-8")

    assert "## 現在の未完了TODO" in todo
    assert "古い archive / progress / design backlog を再確認" in todo
    active_todo_section = todo.split("## 現在の未完了TODO", 1)[1].split("## 実機なしで進められる候補", 1)[0]
    assert "early-initramfs実験" in active_todo_section
    assert "- [x] E0:" in active_todo_section
    assert "- [x] E1:" in active_todo_section
    assert "- [x] E2:" in active_todo_section
    assert "- [x] E3-E4:" in active_todo_section
    assert "- [x] E5:" in active_todo_section
    assert "- [x] E6:" in active_todo_section
    for e6_evidence in [
        "f9fdce0556fa51356b18f4f93cdf7c9909bfc8d5c3e93d40b04acde7619dfc15",
        "d52c66d8-3938-4d49-b09c-5622cb96c93e",
        "1d117305-9560-4b0f-82c0-b59c5dd7a160",
        "reinstall/remove/reinstall",
        "E0-E6を完了",
    ]:
        assert e6_evidence in active_todo_section
    for e5_partial_evidence in [
        "device側controlled reboot 10回はpass",
        "<keyboard-host>-rpi-os-early-e5-controlled-reboot-20260808T071706Z",
        "`keyboard_ready` median 14.917秒",
        "`usb->input` median 0.7255秒",
        "LI" + "01 Windows watcher付きcontrolled reboot 10 sample run `20260808T075206Z`",
        "post-first-ready disconnect 0",
        "LI" + "01 cold boot run `20260808T085207Z`",
        "Windows Vial Raw HID",
        "E5を完了",
    ]:
        assert e5_partial_evidence in active_todo_section
    for e3_e4_evidence in [
        "799c74a6-62f9-48db-b495-cb0b6725274f",
        "296462dd-672e-4e6b-8eb6-6b8b3305ddb5",
        "0d059889-6b87-447b-870c-2497bf89cab5",
        "c44838d2-a104-43f5-bcd6-d813f3adceff",
        "US-subの`KC_A` + `KC_LSFT`",
        "E4 barrier `3=3=3=3 -> 5`",
        "既存固定prefixの上書き拒否でexit 70",
        "e3-normal-fallback-20260808T065844Z",
        "E3/E4 closeoutを完了",
    ]:
        assert e3_e4_evidence in active_todo_section
    assert "package / device profile split M1-M3" not in active_todo_section
    completed_section = todo.split("## 最近完了した作業", 1)[1]
    assert "package / device profile split M1-M4 first target" in completed_section
    assert "hidloom-profile-touch-waveshare-8.8" in completed_section
    assert "native owner の `KC_CONSOLE` / `KC_USB` / `KC_CONNAUTO` 復旧" in completed_section
    assert "architecture/native-output-routing-uidd-design.md" in todo
    assert "| P1 |" not in active_todo_section
    assert "| P2 |" not in active_todo_section
    assert "## 直近の要点" in status
    assert "## 2026-06-09 自動で完了した作業" in todo
    assert "Bluetooth host local rename metadata first slice" in todo
    assert "## 進行中の判断" in status
    for e3_e4_status in [
        "## 2026-08-08 Raspberry Pi OS early-initramfs E3/E4 final normal-fallback PASS",
        "native input ready 5.050秒",
        "normal adopter 16.114秒",
        "main endpointのnonzero実入力は本候補ではN/A",
        "`3 = 3 = 3 = 3`",
        "terminal releaseはattempted/delivered/errors `2/2/0`",
        "全checkをpass",
        "固定prefix衝突でexit 70",
        "c44838d2-a104-43f5-bcd6-d813f3adceff",
        "e91ad0670f56bd4c5b809db44e820f6da953701381faf282eea6a7a9b62b3471",
        "runtime fileのmodeは緩めていない",
    ]:
        assert e3_e4_status in status
    for e5_status in [
        "## 2026-08-08 Raspberry Pi OS early-initramfs E5 device controlled reboot soak",
        "<keyboard-host>-rpi-os-early-e5-controlled-reboot-20260808T071706Z",
        "`keyboard_ready`はmin 14.238秒、median 14.917秒、max 15.575秒",
        "`usb->input`はmin 0.571秒",
        "final outputは`auto`",
        "E6 package昇格は別の未完了task",
        "## 2026-08-08 Raspberry Pi OS early-initramfs E5 Windows watcher controlled reboot soak",
        "`e5-controlled-reboot-20260808T075206Z-01`から`-10`",
        "initial disconnectは9,670.536-11,874.002 ms",
        "first readyは32,456.852-34,648.330 ms",
        "direct smokeを実行",
        "## 2026-08-08 Raspberry Pi OS early-initramfs E5 final operator/shutdown closeout PASS",
        "`e5-cold-boot-20260808T085207Z-01`から`-03`",
        "`keyboard_ready=15.268 / 14.541 / 15.668s`",
        "modifier非固着を確認した独立cold boot",
        "`8321a180-09a4-43ef-9adf-a1ccd1ab2fc9`",
        "E0通常baselineの`keyboard_ready` median 14.681秒",
        "約65.6%短縮",
        "native-owner live smoke `ok=true`",
        "runner側のStrictMode null handling",
    ]:
        assert e5_status in status

    for m6_closeout_evidence in [
        "a09de9e149a3bc7c06a54bf67a8307ae417b41e69e4898ddc993c973b94cf4d1",
        "`usable keyboard`は15秒",
        "dedicated `KC_SHUTDOWN`",
        "8b02c919652cb9afd003e0d9e1353957e683c841bea536188ba23400bcd0219a",
        "`internal-rc ready=true` / blocker 0",
        "最終稼働imageはRaspberry Pi OS",
    ]:
        assert m6_closeout_evidence in status
        assert m6_closeout_evidence in checklist
    assert "7. [x] source `a0f283708fd5`" in todo
    assert "- [x] exact M6 media:" in checklist
    assert "- [x] promotion:" in checklist
    assert "exact M6はRaspberry Pi OS用`hidloom-ctrl`を収録しない" in m6_handoff
    assert "`KC_USB`はUSBへ戻せるが最終targetが`usb`" in m6_handoff
    for failure_heading in [
        "## Raspberry Pi Imager accepts only the canonical-cased Windows device path",
        "## Buildroot M6 handoff calls a Raspberry Pi OS-only control CLI",
        "## Reduced install-ready directory is used as an all-mode bundle input",
        "## Windows dirty public export records NTFS mode 0666",
        "## POSIX shebang fake CLI is not executable on Windows",
        "## Cargo metadata UTF-8 is decoded with the Windows locale",
        "## Windows newline translation changes generated inventory bytes",
        "## Windows validation host has no zstd CLI",
        "## Windows bash validation receives an unconverted native absolute path",
        "## Windows public text replacement converts shell scripts to CRLF",
        "## KiCad generators produce host-dependent line endings",
        "## Git UTF-8 output is decoded with the Windows locale",
        "## Repository hygiene scans smudged Windows line endings as artifact bytes",
        "## Windows source syntax hygiene cannot invoke POSIX parsers",
        "## POSIX deploy integration is launched as a Win32 executable",
        "## POSIX dotenv permission fixture cannot model mode 0600 on Windows",
        "## Host-observed license collector assumes a Debian host",
    ]:
        assert failure_heading in failure_patterns

    for revived_todo in [
        "Unicode / Send String real runner",
        "Bluetooth paired-host event source / last-connected writer",
        "OLED freeze recovery / I2C diagnostics",
        "Persistent Wi-Fi off implementation decision",
        "Bluetooth host rename / per-host forget runtime",
        "HTTP analog stick calibration 2D map",
    ]:
        assert revived_todo in todo
    for status_summary in [
        "Unicode / Send String",
        "Bluetooth host metadata",
        "OLED / analog stick",
    ]:
        assert status_summary in status

    for completed_gate in [
        "matrixd / splash brightness guard",
        "4.3 inch touch panel flick",
        "Touch flick IME composition",
        "BT paired host recovery boundary",
        "Unicode / Send String safety",
        "Interaction status / feedback owner",
        "Vial serial suffix smoke",
        "SequenceEngine timed interaction safety boundary",
        "Autocorrect runtime first slice",
    ]:
        assert completed_gate in todo

    assert "| P3 |" not in todo
    assert "package-profile-split-plan.md" in status
    assert "feature/design-todo-backlog.md" in todo
    assert "keycode/unimplemented-keycodes.md" in todo
    assert todo.count("- [ ]") == 0
    assert "- [ ]" not in design_todo
    assert "- [ ]" not in sequence_design
    assert "現在、未完了の受け入れchecklistはありません。" in design_todo
    assert "公開実装へ追加しない境界" in design_todo
    assert "private workspace reference" not in design_todo
    for low_priority_keycode in [
        "Mouse buttons 6-8",
        "QMK Unicode",
    ]:
        assert low_priority_keycode in keycode_todo

    forbidden_todo_markers = [
        "| 1 | matrixd / splash brightness guard の物理確認 |",
        "| P1 | matrixd / LED brightness 実機安定化 |",
        "| P1 | package / device profile split M1-M3 |",
        "| 3 | Vial serial suffix |",
    ]
    for marker in forbidden_todo_markers:
        assert marker not in todo

    assert "外部 host / 肉眼観測が必要な追加検証" in checklist
    assert "device側controlled reboot 10 sample" in checklist
    assert "LI" + "01 Windows watcher付きcontrolled reboot 10 sample" in checklist
    assert "e5-controlled-reboot-20260808T075206Z-01" in checklist
    assert "完全電源断cold bootは" + "LI" + "01 fresh run `20260808T085207Z`で3回実施" in checklist
    assert "Ctrl / Shift / Alt非固着は独立boot" in checklist
    assert "全go条件を満たしE5を完了" in checklist

    print("ok: current TODO and public design boundaries are explicit")


if __name__ == "__main__":
    main()
