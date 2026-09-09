#!/usr/bin/env python3
"""Exercise profile transitions and preflight using isolated runtime trees."""
from __future__ import annotations

import copy
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import importlib.util
import io
import shlex
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("profile_reconcile", ROOT / "script/apply_device_profile.py")
assert spec and spec.loader
profile_tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile_tool)


class ProfileTransitions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.runtime = self.root / "runtime"
        self.units = self.root / "systemd"
        self.profiles = profile_tool.load_profiles(ROOT / "config/device-profiles")
        self.calls = []
        self.patches = [
            patch.object(profile_tool, "SYSTEMD_ETC_DIR", self.units),
            patch.object(profile_tool, "systemctl", side_effect=lambda args, **kw: self.calls.append(args)),
            patch.object(profile_tool, "wait_for_sockets"),
        ]
        for mocked in self.patches:
            mocked.start()
            self.addCleanup(mocked.stop)

    def apply(self, name, profile=None, dry_run=False, restart=False):
        data, base = self.profiles[name]
        with redirect_stdout(io.StringIO()):
            profile_tool.apply_profile(name, data if profile is None else profile, base,
                runtime_dir=self.runtime, dry_run=dry_run, backup=True, restart=restart)

    def override(self, unit="httpd.service"):
        return self.units / (unit + ".d") / "10-hidloom-device-profile.conf"

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def test_touch_keyboard_removes_only_owned_overrides(self):
        self.apply("touch-waveshare-8.8")
        old = self.override().read_bytes()
        user = self.override().with_name("90-user.conf")
        user.write_text("[Service]\nNice=5\n")
        self.apply("keyboard-ver1", restart=True)
        self.assertFalse(self.override().exists())
        self.assertEqual(user.read_text(), "[Service]\nNice=5\n")
        backups = list(self.override().parent.glob("10-hidloom-device-profile.conf.bak.*"))
        self.assertTrue(any(p.read_bytes() == old for p in backups))
        self.apply("touch-waveshare-8.8", restart=True)
        self.assertIn("Wants=logicd.service", self.override().read_text())
        self.assertTrue(any(c[0] == "mask" and "hidloom-logicd-core.service" in c for c in self.calls))

    def test_missing_last_source_has_zero_mutations(self):
        self.apply("keyboard-ver1")
        before = self.snapshot()
        profile = copy.deepcopy(self.profiles["keyboard-ver1"][0])
        profile["config_files"]["missing.json"] = "does-not-exist.json"
        self.calls.clear()
        with self.assertRaises(SystemExit):
            self.apply("keyboard-ver1", profile)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.calls, [])

    def test_unknown_reserved_override_rejected_before_writes(self):
        self.apply("touch-waveshare-8.8")
        self.override().write_text("[Unit]\nWants=user-custom.service\n")
        before = self.snapshot()
        self.calls.clear()
        with self.assertRaises(SystemExit):
            self.apply("keyboard-ver1")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.calls, [])

    def test_symlink_reserved_override_rejected(self):
        path = self.override()
        path.parent.mkdir(parents=True)
        target = self.root / "user.conf"
        target.write_text("[Unit]\nWants=logicd.service\n")
        path.symlink_to(target)
        with self.assertRaises(SystemExit):
            self.apply("keyboard-ver1")
        self.assertFalse(self.runtime.exists())
        self.assertTrue(path.is_symlink())

    def test_service_failure_does_not_publish_success_marker(self):
        self.apply("touch-waveshare-8.8")
        marker = (self.runtime / "device_profile.json").read_bytes()
        with patch.object(profile_tool, "systemctl", side_effect=subprocess.CalledProcessError(1, ["systemctl", "daemon-reload"])):
            with self.assertRaises(subprocess.CalledProcessError):
                self.apply("keyboard-ver1", restart=True)
        self.assertEqual((self.runtime / "device_profile.json").read_bytes(), marker)

    def test_same_second_backup_preserves_each_previous_value(self):
        self.apply("keyboard-ver1")
        path = self.runtime / "keymap.json"
        with patch.object(profile_tool.time, "strftime", return_value="same-second"):
            path.write_text("first\n")
            self.apply("keyboard-ver1")
            path.write_text("second\n")
            self.apply("keyboard-ver1")
        values = {p.read_text() for p in self.runtime.glob("keymap.json.bak.*")}
        self.assertTrue({"first\n", "second\n"}.issubset(values))

    def test_dry_run_is_zero_write(self):
        self.apply("touch-waveshare-8.8")
        before = self.snapshot()
        self.apply("keyboard-ver1", dry_run=True, restart=True)
        self.assertEqual(self.snapshot(), before)

    def test_same_profile_dropin_mode_or_line_endings_have_recoverable_backup(self):
        self.apply("touch-waveshare-8.8")
        path = self.override()
        for change in ("mode", "line-endings"):
            with self.subTest(change=change):
                if change == "mode":
                    path.chmod(0o600)
                else:
                    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
                before = (path.read_bytes(), path.stat().st_mode & 0o777)
                old_backups = set(path.parent.glob(path.name + ".bak.*"))
                self.apply("touch-waveshare-8.8")
                new_backups = set(path.parent.glob(path.name + ".bak.*")) - old_backups
                self.assertEqual(len(new_backups), 1)
                saved = next(iter(new_backups))
                self.assertEqual((saved.read_bytes(), saved.stat().st_mode & 0o777), before)

    def test_implicit_nonregular_destinations_fail_before_any_change(self):
        for name in ("flick.json", "device_profile.json"):
            with self.subTest(name=name):
                self.apply("keyboard-ver1")
                destination = self.runtime / name
                if destination.exists():
                    destination.unlink()
                destination.mkdir()
                before = self.snapshot()
                self.calls.clear()
                with self.assertRaisesRegex(SystemExit, "runtime destination conflict"):
                    self.apply("keyboard-ver1")
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(self.calls, [])
                destination.rmdir()

    def test_preflight_render_and_destination_fail_without_writes(self):
        self.apply("keyboard-ver1")
        for mutation in ("render", "destination", "service"):
            with self.subTest(mutation=mutation):
                data = copy.deepcopy(self.profiles["keyboard-ver1"][0])
                if mutation == "render":
                    data["dropins"] = {"httpd.service": {}}
                elif mutation == "destination":
                    data["runtime_files"]["../outside.json"] = next(iter(data["runtime_files"].values()))
                else:
                    data["services"]["enable"].append(data["services"]["disable"][0])
                before = self.snapshot()
                self.calls.clear()
                with self.assertRaises(SystemExit):
                    self.apply("keyboard-ver1", data)
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(self.calls, [])

    def test_partial_failures_report_phase_and_recover_original_bytes_modes(self):
        for failure in ("copy", "remove", "dropin-replace", "dropin-remove", "daemon-reload", "restart", "readiness"):
            with self.subTest(failure=failure):
                self.apply("touch-waveshare-8.8")
                if failure == "remove":
                    (self.runtime / "flick.json").write_text("{\"legacy\": true}\n")
                (self.runtime / "keymap.json").chmod(0o600)
                self.override().chmod(0o600)
                original_paths = [p for p in self.root.rglob("*") if p.is_file() and ".bak." not in p.name]
                original = {path: (path.read_bytes(), path.stat().st_mode & 0o777) for path in original_paths}
                marker = (self.runtime / "device_profile.json").read_bytes()
                data = copy.deepcopy(self.profiles["keyboard-ver1"][0])
                profile_id = "keyboard-ver1"
                if failure == "dropin-replace":
                    data = copy.deepcopy(self.profiles["touch-waveshare-8.8"][0])
                    data["dropins"]["httpd.service"]["Unit"]["Description"] = "Updated owned fixture"
                    profile_id = "touch-waveshare-8.8"
                real_atomic = profile_tool.atomic_content
                real_unlink = Path.unlink
                copy_target = self.runtime / next(iter(data["config_files"]), "keymap.json")
                def write(path, content, *args):
                    if (failure == "copy" and path == copy_target) or (failure == "dropin-replace" and path == self.override()):
                        raise OSError("fixture write failure")
                    return real_atomic(path, content, *args)
                def unlink(path, *args, **kwargs):
                    if (failure == "remove" and path == self.runtime / "flick.json") or (failure == "dropin-remove" and path == self.override()):
                        raise OSError("fixture remove failure")
                    return real_unlink(path, *args, **kwargs)
                def service(arguments, **kwargs):
                    self.calls.append(arguments)
                    if arguments[0] == failure:
                        raise subprocess.CalledProcessError(19, ["systemctl", *arguments])
                output = io.StringIO()
                with ExitStack() as stack:
                    stack.enter_context(redirect_stderr(output))
                    stack.enter_context(patch.object(profile_tool, "atomic_content", side_effect=write))
                    stack.enter_context(patch.object(Path, "unlink", unlink))
                    stack.enter_context(patch.object(profile_tool, "systemctl", side_effect=service))
                    if failure == "readiness":
                        stack.enter_context(patch.object(profile_tool, "wait_for_sockets", side_effect=SystemExit("fixture readiness timeout")))
                    with self.assertRaises((OSError, subprocess.CalledProcessError, SystemExit)):
                        self.apply(profile_id, data, restart=True)
                report = output.getvalue()
                self.assertIn("profile apply incomplete; failed phase:", report)
                phase = "reconcile-dropins" if failure.startswith("dropin-") else failure
                self.assertIn(phase, report)
                self.assertIn("backup verified:", report)
                self.assertIn("does not restore service state or downgrade packages", report)
                self.assertEqual((self.runtime / "device_profile.json").read_bytes(), marker)
                # Exercise the reported file-recovery commands against fixtures only.
                for line in report.splitlines():
                    if not line.startswith("  sudo "):
                        continue
                    command = shlex.split(line)
                    if command[1] == "cp":
                        source, destination = map(Path, command[-2:])
                        self.assertTrue(source.is_relative_to(self.root))
                        self.assertTrue(destination.is_relative_to(self.root))
                        shutil.copy2(source, destination)
                    elif command[1] == "rm":
                        destination = Path(command[-1])
                        self.assertTrue(destination.is_relative_to(self.root))
                        destination.unlink()
                for path, expected in original.items():
                    self.assertEqual((path.read_bytes(), path.stat().st_mode & 0o777), expected, str(path))


if __name__ == "__main__":
    unittest.main()
