#!/usr/bin/env python3
"""Profile-specific deployment orchestration with no device access."""
import os
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DeploymentOrder(unittest.TestCase):
    def migration_fixture(self, root, states=None, real_profile=False):
        bindir, etc, package = (root / name for name in ("bin", "etc", "package"))
        for path in (bindir, etc, package):
            path.mkdir()
        source = (ROOT / "tools/package/switch_deb_systemd_units.sh").read_text()
        units = source.split('units="', 1)[1].split('"', 1)[0].split()
        for unit in units:
            (package / unit).write_text("[Unit]\nDescription=fixture\n")
            (etc / unit).write_text("[Unit]\nDescription=old\n")
        script = root / "switch.sh"
        script.write_text(source)
        (bindir / "id").write_text("#!/bin/sh\necho 0\n")
        (bindir / "systemctl").write_text("""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ['TASK_CALLS'], 'a') as stream:
    stream.write('systemctl ' + ' '.join(args) + '\\n')
if os.environ.get('TASK_FAIL') == args[0]:
    raise SystemExit(19)
if args[0] == 'show' and 'UnitFileState' in args:
    print(json.loads(os.environ['TASK_STATES']).get(args[-1], 'disabled'))
""")
        profile_body = """#!/usr/bin/env python3
import importlib.util, os, sys
with open(os.environ['TASK_CALLS'], 'a') as stream:
    stream.write('profile ' + ' '.join(sys.argv[1:]) + '\\n')
if os.environ.get('TASK_FAIL') == 'profile':
    raise SystemExit(19)
"""
        if real_profile:
            profile_body += """
spec = importlib.util.spec_from_file_location('apply_fixture', os.environ['TASK_PROFILE_TOOL'])
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
def readiness(paths):
    with open(os.environ['TASK_CALLS'], 'a') as stream:
        stream.write('readiness fixture\\n')
    if os.environ.get('TASK_FAIL') == 'readiness':
        raise SystemExit(19)
tool.wait_for_sockets = readiness
tool.main()
"""
        (bindir / "hidloom-profile").write_text(profile_body)
        for child in bindir.iterdir():
            child.chmod(0o755)
        env = {**os.environ, "PATH": str(bindir) + ":" + os.environ["PATH"],
               "TASK_CALLS": str(root / "calls"), "TASK_STATES": json.dumps(states or {}),
               "TASK_PROFILE_TOOL": str(ROOT / "script/apply_device_profile.py"),
               "HIDLOOM_RUNTIME_DIR": str(root / "runtime"),
               "HIDLOOM_SYSTEMD_ETC_DIR": str(etc), "HIDLOOM_SYSTEMD_PACKAGE_DIR": str(package),
               "HIDLOOM_SYSTEMD_UNIT_BACKUP_ROOT": str(root / "backup"), "PYTHONDONTWRITEBYTECODE": "1"}
        return script, env, etc, package, units

    def test_wrapper_defers_profile_until_selected_unit_transition(self):
        for profile in ("keyboard-ver1", "touch-waveshare-8.8"):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                wrapper = root / "deploy_github_release_deb.sh"
                wrapper.write_text((ROOT / "tools/package/deploy_github_release_deb.sh").read_text())
                names = ("install_github_release_deb.sh", "deploy_deb_unit_switch.sh", "deploy_deb_verify.sh")
                for name in names:
                    child = root / name
                    child.write_text("#!/bin/sh\n" + f"echo '{name}' \"$@\" >> \"$TASK_CALLS\"\n" + f"[ \"${{TASK_FAIL:-}}\" != '{name}' ] || exit 19\n")
                    child.chmod(0o755)
                env = {**os.environ, "TASK_CALLS": str(root / "calls")}
                command = ["sh", str(wrapper), "--tag", "fixture", "--host", "pi@example.invalid", "--profile", profile, "--install", "--no-smoke"]
                result = subprocess.run(command, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                lines = (root / "calls").read_text().splitlines()
                self.assertEqual(len(lines), 3)
                self.assertIn("--defer-profile-apply", lines[0])
                self.assertIn("--profile " + profile, lines[1])
                self.assertIn("--restart", lines[1])
                self.assertIn("--profile " + profile, lines[2])
                self.assertNotIn("--smoke", lines[2])
                for index, name in enumerate(names):
                    (root / "calls").write_text("")
                    failed = subprocess.run(command, env={**env, "TASK_FAIL": name}, capture_output=True, text=True)
                    self.assertEqual(failed.returncode, 19)
                    self.assertEqual(len((root / "calls").read_text().splitlines()), index + 1)

    def test_unit_migration_restarts_via_profile_only(self):
        for profile in ("keyboard-ver1", "touch-waveshare-8.8"):
            for migrate in (False, True):
                with self.subTest(profile=profile, migrate=migrate), tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    bindir, etc, package = (root / name for name in ("bin", "etc", "package"))
                    for path in (bindir, etc, package):
                        path.mkdir()
                    source = (ROOT / "tools/package/switch_deb_systemd_units.sh").read_text()
                    units = source.split('units="', 1)[1].split('"', 1)[0].split()
                    for unit in units:
                        (package / unit).write_text("[Unit]\nDescription=fixture\n")
                        if migrate:
                            (etc / unit).write_text("[Unit]\nDescription=old\n")
                    for name, body in {
                        "id": "echo 0\n",
                        "systemctl": 'echo "systemctl $*" >> "$TASK_CALLS"\ncase "$*" in *UnitFileState*) echo disabled;; esac\n',
                        "hidloom-profile": 'echo "profile $*" >> "$TASK_CALLS"\n',
                    }.items():
                        path = bindir / name
                        path.write_text("#!/bin/sh\n" + body)
                        path.chmod(0o755)
                    script = root / "switch.sh"
                    script.write_text(source)
                    env = {**os.environ, "PATH": str(bindir) + ":" + os.environ["PATH"], "TASK_CALLS": str(root / "calls"), "HIDLOOM_SYSTEMD_ETC_DIR": str(etc), "HIDLOOM_SYSTEMD_PACKAGE_DIR": str(package), "HIDLOOM_SYSTEMD_UNIT_BACKUP_ROOT": str(root / "backup")}
                    result = subprocess.run(["sh", str(script), "--restart", "--profile", profile], env=env, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    calls = (root / "calls").read_text().splitlines()
                    self.assertEqual([line for line in calls if line.startswith("profile ")], [f"profile {profile} --apply --backup --restart"])
                    self.assertFalse(any(line.startswith("systemctl restart") for line in calls))

    def test_unit_state_fidelity_and_user_override_preservation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            selected = {"btd.service": "enabled-runtime", "httpd.service": "masked-runtime",
                        "i2cd.service": "linked-runtime", "ledd.service": "linked"}
            script, env, etc, package, units = self.migration_fixture(root, selected)
            user = etc / "httpd.service.d/90-user.conf"
            user.parent.mkdir()
            user.write_text("[Service]\nNice=3\n")
            result = subprocess.run(["sh", str(script), "--restart", "--profile", "touch-waveshare-8.8"], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = (root / "calls").read_text().splitlines()
            self.assertIn("systemctl enable --runtime btd.service", calls)
            self.assertIn("systemctl mask --runtime httpd.service", calls)
            self.assertIn("systemctl link --runtime " + str(package / "i2cd.service"), calls)
            self.assertIn("systemctl link " + str(package / "ledd.service"), calls)
            self.assertFalse(any(line == "systemctl enable " + unit for unit in selected for line in calls))
            self.assertEqual(user.read_text(), "[Service]\nNice=3\n")
            receipt = next((root / "backup").glob("*/unit-states.tsv"))
            for unit, state in selected.items():
                self.assertIn(unit + "\t" + state, receipt.read_text())

    def test_migration_failure_keeps_receipt_and_prevents_final_apply(self):
        for failed, state in (("daemon-reload", "disabled"), ("enable", "enabled-runtime"),
                              ("disable", "disabled"), ("mask", "masked-runtime"), ("link", "linked-runtime")):
            with self.subTest(failed=failed), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                script, env, etc, package, units = self.migration_fixture(root, {"btd.service": state})
                result = subprocess.run(["sh", str(script), "--restart", "--profile", "keyboard-ver1"], env={**env, "TASK_FAIL": failed}, capture_output=True, text=True)
                self.assertEqual(result.returncode, 19, result.stderr)
                self.assertIn("unit migration incomplete:", result.stderr)
                self.assertIn("retained backup and unit state receipt:", result.stderr)
                self.assertNotIn("profile ", (root / "calls").read_text())
                receipt = next((root / "backup").glob("*/unit-states.tsv"))
                self.assertEqual(len(receipt.read_text().splitlines()), len(units))
                self.assertTrue((receipt.parent / "btd.service").is_file())

    def test_metadata_failure_precedes_unit_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script, env, etc, package, units = self.migration_fixture(root)
            before = {path.name: path.read_bytes() for path in etc.iterdir()}
            result = subprocess.run(["sh", str(script), "--restart", "--profile", "keyboard-ver1"], env={**env, "TASK_FAIL": "show"}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 19)
            self.assertEqual({path.name: path.read_bytes() for path in etc.iterdir()}, before)
            self.assertFalse((root / "backup").exists())
            self.assertNotIn("profile ", (root / "calls").read_text())

    def test_real_final_profile_has_exact_keyboard_and_touch_policy(self):
        for profile in ("keyboard-ver1", "touch-waveshare-8.8"):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                script, env, etc, package, units = self.migration_fixture(root, real_profile=True)
                user = etc / "httpd.service.d/90-user.conf"
                user.parent.mkdir()
                user.write_text("[Service]\nNice=3\n")
                result = subprocess.run(["sh", str(script), "--restart", "--profile", profile], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                calls = (root / "calls").read_text().splitlines()
                profiles = [index for index, line in enumerate(calls) if line.startswith("profile ")]
                self.assertEqual(len(profiles), 1)
                restarts = [index for index, line in enumerate(calls) if line.startswith("systemctl restart ")]
                self.assertEqual(len(restarts), 1)
                self.assertGreater(restarts[0], profiles[0])
                restarted = calls[restarts[0]].split()[2:]
                expected = json.loads((ROOT / f"config/device-profiles/{profile}.json").read_text())["services"]
                self.assertEqual(restarted, expected["enable"])
                if profile == "touch-waveshare-8.8":
                    self.assertNotIn("hidloom-logicd-core.service", restarted)
                    self.assertTrue(any(line.startswith("systemctl mask ") and "hidloom-logicd-core.service" in line for line in calls))
                else:
                    self.assertNotIn("logicd.service", restarted)
                    self.assertIn("hidloom-logicd-core.service", restarted)
                    self.assertIn("readiness fixture", calls)
                self.assertEqual(user.read_text(), "[Service]\nNice=3\n")


if __name__ == "__main__":
    unittest.main()
