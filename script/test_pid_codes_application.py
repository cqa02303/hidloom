#!/usr/bin/env python3
from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/pid_codes_application.py"


def run(
    *args: str,
    root: Path = ROOT,
    check: bool = True,
    environment_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    if environment_overrides:
        environment.update(environment_overrides)
    return subprocess.run(
        ["python3", str(TOOL), "--root", str(root), *args],
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
        env=environment,
    )


def main() -> None:
    owner_slug = "c" + "qa" + "02303"
    plan = json.loads(run().stdout)
    assert plan["schema"] == "hidloom.pid-codes-application-plan.v1"
    assert plan["status"] == "candidate-unassigned"
    assert plan["candidate"] == {
        "vid": "0x1209",
        "pid": "0x484C",
        "path": "1209/484C/index.md",
    }
    assert plan["owner_path"] == f"org/{owner_slug}/index.md"
    assert plan["activation_allowed"] is False
    assert plan["availability_recheck_required"] is True

    with tempfile.TemporaryDirectory() as temporary:
        temporary_path = Path(temporary)
        upstream = temporary_path / "pid-codes"
        (upstream / "1209").mkdir(parents=True)
        (upstream / "org").mkdir()
        (upstream / "1209/index.md").write_text(
            "---\nlayout: vid\nvid: 1209\n---\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "init", "-q"], cwd=upstream, check=True)
        subprocess.run(["git", "config", "user.name", "PID Fixture"], cwd=upstream, check=True)
        subprocess.run(
            ["git", "config", "user.email", "pid-fixture@example.invalid"],
            cwd=upstream,
            check=True,
        )
        subprocess.run(["git", "add", "."], cwd=upstream, check=True)
        subprocess.run(["git", "commit", "-qm", "PID fixture"], cwd=upstream, check=True)
        subprocess.run(
            [
                "git",
                "remote",
                "add",
                "origin",
                "https://github.com/pidcodes/pidcodes.github.com.git",
            ],
            cwd=upstream,
            check=True,
        )
        upstream_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=upstream, text=True
        ).strip()
        subprocess.run(
            ["git", "update-ref", "refs/remotes/origin/master", upstream_commit],
            cwd=upstream,
            check=True,
        )
        subprocess.run(
            [
                "git",
                "symbolic-ref",
                "refs/remotes/origin/HEAD",
                "refs/remotes/origin/master",
            ],
            cwd=upstream,
            check=True,
        )

        project = temporary_path / "project"
        shutil.copytree(ROOT / "config", project / "config")
        shutil.copy2(ROOT / "LICENSE", project / "LICENSE")
        (project / "kicad").mkdir()
        (project / "kicad/fixture.kicad_sch").write_text("fixture\n", encoding="utf-8")
        (project / "kicad/fixture.kicad_pcb").write_text("fixture\n", encoding="utf-8")
        contract_path = project / "config/public-usb-identity.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        identity_bindings = contract["source_bindings"]
        identity_sources = [
            identity_bindings["ble_gatt_identity"],
            *identity_bindings["systemd_identity_environment"]["units"],
        ]
        for relative in identity_sources:
            destination = project / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
        contract["assignment"]["availability_evidence"] = {
            "checked_date": date.today().isoformat(),
            "upstream_commit": upstream_commit,
            "origin_head_ref": "refs/remotes/origin/master",
            "remote_head_commit": upstream_commit,
            "checkout_clean": True,
            "head_matches_origin_head": True,
            "origin_head_matches_remote_head": True,
            "candidate_path_absent": True,
            "owner_path_absent": True,
        }
        contract_path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        real_git = shutil.which("git")
        assert real_git is not None
        wrapper_directory = temporary_path / "git-wrapper"
        wrapper_directory.mkdir()
        git_wrapper = wrapper_directory / "git"
        git_wrapper.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "ls-remote" ] && [ "$2" = "--exit-code" ] '
            '&& [ "$3" = "origin" ] && [ "$4" = "HEAD" ]; then\n'
            '  [ -n "${HIDLOOM_TEST_REMOTE_HEAD:-}" ] || exit 2\n'
            '  printf "%s\\tHEAD\\n" "$HIDLOOM_TEST_REMOTE_HEAD"\n'
            "  exit 0\n"
            "fi\n"
            f"exec {shlex.quote(real_git)} \"$@\"\n",
            encoding="utf-8",
        )
        git_wrapper.chmod(0o755)
        upstream_environment = {
            "PATH": f"{wrapper_directory}:{os.environ.get('PATH', '')}",
            "HIDLOOM_TEST_REMOTE_HEAD": upstream_commit,
        }

        checked = json.loads(
            run(
                "--upstream-checkout",
                str(upstream),
                root=project,
                environment_overrides=upstream_environment,
            ).stdout
        )
        assert checked["upstream_check"]["candidate_path_absent"] is True
        assert checked["upstream_check"]["owner_path_absent"] is True
        assert checked["upstream_check"]["origin"].endswith("pidcodes.github.com.git")
        assert checked["upstream_check"]["origin_head_ref"] == (
            "refs/remotes/origin/master"
        )
        assert checked["upstream_check"]["origin_head_commit"] == upstream_commit
        assert checked["upstream_check"]["remote_head_commit"] == upstream_commit
        assert checked["upstream_check"]["checkout_clean"] is True
        assert checked["upstream_check"]["head_matches_origin_head"] is True
        assert checked["upstream_check"]["origin_head_matches_remote_head"] is True

        subprocess.run(
            [
                "git",
                "config",
                "url.file:///tmp/unrelated.insteadOf",
                "https://example.invalid/",
            ],
            cwd=upstream,
            check=True,
        )
        run(
            "--upstream-checkout",
            str(upstream),
            root=project,
            environment_overrides=upstream_environment,
        )
        subprocess.run(
            [
                "git",
                "config",
                "--unset-all",
                "url.file:///tmp/unrelated.insteadOf",
            ],
            cwd=upstream,
            check=True,
        )

        subprocess.run(
            [
                "git",
                "config",
                "url.file:///tmp/untrusted-pid-codes.insteadOf",
                "https://github.com/pidcodes/pidcodes.github.com.git",
            ],
            cwd=upstream,
            check=True,
        )
        rewritten_remote = run(
            "--upstream-checkout",
            str(upstream),
            root=project,
            check=False,
            environment_overrides=upstream_environment,
        )
        assert rewritten_remote.returncode != 0
        assert "must not use a Git URL rewrite" in rewritten_remote.stderr
        subprocess.run(
            [
                "git",
                "config",
                "--unset-all",
                "url.file:///tmp/untrusted-pid-codes.insteadOf",
            ],
            cwd=upstream,
            check=True,
        )

        unavailable_remote_environment = dict(upstream_environment)
        unavailable_remote_environment.pop("HIDLOOM_TEST_REMOTE_HEAD")
        unavailable_remote = run(
            "--upstream-checkout",
            str(upstream),
            root=project,
            check=False,
            environment_overrides=unavailable_remote_environment,
        )
        assert unavailable_remote.returncode != 0
        assert "canonical remote HEAD could not be resolved" in unavailable_remote.stderr

        stale_remote_environment = dict(upstream_environment)
        stale_remote_environment["HIDLOOM_TEST_REMOTE_HEAD"] = "2" * 40
        stale_remote = run(
            "--upstream-checkout",
            str(upstream),
            root=project,
            check=False,
            environment_overrides=stale_remote_environment,
        )
        assert stale_remote.returncode != 0
        assert "origin/HEAD does not match canonical remote HEAD" in stale_remote.stderr

        subprocess.run(
            ["git", "symbolic-ref", "--delete", "refs/remotes/origin/HEAD"],
            cwd=upstream,
            check=True,
        )
        missing_origin_head = run(
            "--upstream-checkout",
            str(upstream),
            root=project,
            check=False,
            environment_overrides=upstream_environment,
        )
        assert missing_origin_head.returncode != 0
        assert "no canonical origin/HEAD" in missing_origin_head.stderr
        subprocess.run(
            [
                "git",
                "symbolic-ref",
                "refs/remotes/origin/HEAD",
                "refs/remotes/origin/master",
            ],
            cwd=upstream,
            check=True,
        )

        missing_upstream = run(
            "--output", str(temporary_path / "unchecked"), root=project, check=False
        )
        assert missing_upstream.returncode != 0
        assert "requires --upstream-checkout" in missing_upstream.stderr

        dirty_path = upstream / "UNTRACKED.txt"
        dirty_path.write_text("dirty\n", encoding="utf-8")
        dirty = run(
            "--upstream-checkout",
            str(upstream),
            root=project,
            check=False,
            environment_overrides=upstream_environment,
        )
        assert dirty.returncode != 0
        assert "checkout must be clean" in dirty.stderr
        dirty_path.unlink()

        local_only = upstream / "LOCAL_ONLY.txt"
        local_only.write_text("local\n", encoding="utf-8")
        subprocess.run(["git", "add", local_only.name], cwd=upstream, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "Local-only fixture"], cwd=upstream, check=True
        )
        stale = run(
            "--upstream-checkout",
            str(upstream),
            root=project,
            check=False,
            environment_overrides=upstream_environment,
        )
        assert stale.returncode != 0
        assert "HEAD does not match origin/HEAD" in stale.stderr
        subprocess.run(
            ["git", "reset", "--hard", "refs/remotes/origin/master"],
            cwd=upstream,
            check=True,
            capture_output=True,
        )

        contract["assignment"]["availability_evidence"]["checked_date"] = "2026-07-13"
        contract_path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        mismatched_evidence = run(
            "--upstream-checkout",
            str(upstream),
            root=project,
            check=False,
            environment_overrides=upstream_environment,
        )
        assert mismatched_evidence.returncode != 0
        assert "availability evidence does not match" in mismatched_evidence.stderr
        contract["assignment"]["availability_evidence"][
            "checked_date"
        ] = date.today().isoformat()
        contract_path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        output = temporary_path / "application"
        generated = json.loads(
            run(
                "--upstream-checkout",
                str(upstream),
                "--output",
                str(output),
                root=project,
                environment_overrides=upstream_environment,
            ).stdout
        )
        assert generated["output"] == str(output)
        owner = (output / f"org/{owner_slug}/index.md").read_text(encoding="utf-8")
        device = (output / "1209/484C/index.md").read_text(encoding="utf-8")
        assert "layout: org" in owner
        assert f"title: {owner_slug}" in owner
        assert "layout: pid" in device
        assert "title: HIDloom Keyboard" in device
        assert f"owner: {owner_slug}" in device
        assert "license: GPL-3.0-or-later" in device
        assert "source: https://github.com/cqa02303/hidloom" in device

        exists = run(
            "--upstream-checkout",
            str(upstream),
            "--output",
            str(output),
            root=project,
            check=False,
            environment_overrides=upstream_environment,
        )
        assert exists.returncode != 0
        assert "output already exists" in exists.stderr
        run(
            "--upstream-checkout",
            str(upstream),
            "--output",
            str(output),
            "--force",
            root=project,
            environment_overrides=upstream_environment,
        )
        unexpected_path = output / "DO_NOT_DELETE.txt"
        unexpected_path.write_text("preserve\n", encoding="utf-8")
        unexpected = run(
            "--upstream-checkout",
            str(upstream),
            "--output",
            str(output),
            "--force",
            root=project,
            check=False,
            environment_overrides=upstream_environment,
        )
        assert unexpected.returncode != 0
        assert "unexpected files" in unexpected.stderr
        assert unexpected_path.read_text(encoding="utf-8") == "preserve\n"
        unexpected_path.unlink()
        owner_page = output / f"org/{owner_slug}/index.md"
        owner_page.unlink()
        owner_page.symlink_to(output / "1209/484C/index.md")
        symlinked = run(
            "--upstream-checkout",
            str(upstream),
            "--output",
            str(output),
            "--force",
            root=project,
            check=False,
            environment_overrides=upstream_environment,
        )
        assert symlinked.returncode != 0
        assert "containing symlinks" in symlinked.stderr
        owner_page.unlink()
        run(
            "--upstream-checkout",
            str(upstream),
            "--output",
            str(output),
            "--force",
            root=project,
            environment_overrides=upstream_environment,
        )

        source_output = run(
            "--upstream-checkout",
            str(upstream),
            "--output",
            str(project / "build/pid-codes"),
            "--force",
            root=project,
            check=False,
            environment_overrides=upstream_environment,
        )
        assert source_output.returncode != 0
        assert "outside the HIDloom source repository" in source_output.stderr
        upstream_output = run(
            "--upstream-checkout",
            str(upstream),
            "--output",
            str(upstream),
            "--force",
            root=project,
            check=False,
            environment_overrides=upstream_environment,
        )
        assert upstream_output.returncode != 0
        assert "must not replace" in upstream_output.stderr
        assert (upstream / "1209/index.md").is_file()

        occupied = upstream / "1209/484C"
        occupied.mkdir(parents=True)
        conflict = run(
            "--upstream-checkout",
            str(upstream),
            root=project,
            check=False,
            environment_overrides=upstream_environment,
        )
        assert conflict.returncode != 0
        assert "PID candidate is already present" in conflict.stderr

    print("ok: pid.codes application draft, availability guard, and activation boundary")


if __name__ == "__main__":
    main()
