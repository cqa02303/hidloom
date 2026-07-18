#!/usr/bin/env python3
"""Regression checks for post-merge pid.codes allocation evidence."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/pid_codes_allocation.py"
IDENTITY_TOOL = ROOT / "tools/public_usb_identity.py"
PR_HEAD = "3b0358d721dfdaa66985b4aceebd1813cb6474a2"
PR_URL = "https://github.com/pidcodes/pidcodes.github.com/pull/1246"
CONFIRMATION = "APPLY PID.CODES ALLOCATION 1209:484C PR#1246"


def run(
    upstream: Path,
    *args: str,
    root: Path,
    check: bool = True,
    environment_overrides: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(environment_overrides)
    return subprocess.run(
        [
            "python3",
            str(TOOL),
            "--root",
            str(root),
            "--upstream-checkout",
            str(upstream),
            *args,
        ],
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
        env=environment,
    )


def copy_project(destination: Path) -> None:
    shutil.copytree(ROOT / "config", destination / "config")
    shutil.copy2(ROOT / "LICENSE", destination / "LICENSE")
    (destination / "kicad").mkdir()
    (destination / "kicad/fixture.kicad_sch").write_text(
        "fixture\n", encoding="utf-8"
    )
    (destination / "kicad/fixture.kicad_pcb").write_text(
        "fixture\n", encoding="utf-8"
    )
    contract = json.loads(
        (destination / "config/public-usb-identity.json").read_text(
            encoding="utf-8"
        )
    )
    bindings = contract["source_bindings"]
    source_paths = [
        bindings["ble_gatt_identity"],
        *bindings["systemd_identity_environment"]["units"],
    ]
    for relative in source_paths:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)


def pull_request_payload(
    merge_commit: str,
    *,
    state: str = "MERGED",
    head: str = PR_HEAD,
    checks: tuple[str, ...] = ("HTML Proofer", "Python Validator"),
    failed_checks: tuple[str, ...] = (),
) -> str:
    return json.dumps(
        {
            "state": state,
            "isDraft": False,
            "headRefOid": head,
            "mergedAt": "2026-07-19T01:02:03.456Z" if state == "MERGED" else None,
            "mergeCommit": {"oid": merge_commit} if state == "MERGED" else None,
            "url": PR_URL,
            "statusCheckRollup": [
                {
                    "name": name,
                    "status": "COMPLETED",
                    "conclusion": "FAILURE" if name in failed_checks else "SUCCESS",
                }
                for name in checks
            ],
        },
        separators=(",", ":"),
    )


def update_origin_head(upstream: Path, commit: str) -> None:
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/master", commit],
        cwd=upstream,
        check=True,
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        temporary_path = Path(temporary)
        owner_slug = "c" + "qa" + "02303"
        project = temporary_path / "project"
        copy_project(project)
        upstream = temporary_path / "pid-codes"
        (upstream / "1209").mkdir(parents=True)
        (upstream / f"org/{owner_slug}").mkdir(parents=True)
        (upstream / "1209/index.md").write_text(
            "---\nlayout: vid\nvid: 1209\n---\n", encoding="utf-8"
        )
        subprocess.run(["git", "init", "-q"], cwd=upstream, check=True)
        subprocess.run(
            ["git", "config", "user.name", "PID Fixture"],
            cwd=upstream,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "pid-fixture@example.invalid"],
            cwd=upstream,
            check=True,
        )
        subprocess.run(["git", "add", "."], cwd=upstream, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "PID base fixture"],
            cwd=upstream,
            check=True,
        )
        (upstream / f"org/{owner_slug}/index.md").write_text(
            "---\n"
            "layout: org\n"
            f"title: {owner_slug}\n"
            f"site: https://github.com/{owner_slug}/\n"
            "---\n"
            "Open-source keyboard hardware and software projects.\n",
            encoding="utf-8",
        )
        (upstream / "1209/484C").mkdir(parents=True)
        (upstream / "1209/484C/index.md").write_text(
            "---\n"
            "layout: pid\n"
            "title: HIDloom Keyboard\n"
            f"owner: {owner_slug}\n"
            "license: GPL-3.0-or-later\n"
            "site: https://github.com/cqa02303/hidloom\n"
            "source: https://github.com/cqa02303/hidloom\n"
            "---\n"
            "Open-source Raspberry Pi keyboard appliance software and hardware "
            "for the cqa02303v5 device profile.\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=upstream, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "Merge PID allocation fixture"],
            cwd=upstream,
            check=True,
        )
        merge_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=upstream, text=True
        ).strip()
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
        update_origin_head(upstream, merge_commit)
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

        real_git = shutil.which("git")
        assert real_git is not None
        wrapper_directory = temporary_path / "wrappers"
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
        gh_wrapper = wrapper_directory / "gh"
        gh_wrapper.write_text(
            "#!/bin/sh\n"
            '[ "$1" = "pr" ] && [ "$2" = "view" ] || exit 64\n'
            'printf "%s\\n" "$HIDLOOM_TEST_PR_JSON"\n',
            encoding="utf-8",
        )
        gh_wrapper.chmod(0o755)
        environment = {
            "PATH": f"{wrapper_directory}:{os.environ.get('PATH', '')}",
            "HIDLOOM_TEST_REMOTE_HEAD": merge_commit,
            "HIDLOOM_TEST_PR_JSON": pull_request_payload(merge_commit),
        }

        contract_path = project / "config/public-usb-identity.json"
        original = contract_path.read_bytes()
        verified = json.loads(
            run(
                upstream,
                root=project,
                environment_overrides=environment,
            ).stdout
        )
        assert verified["schema"] == "hidloom.pid-codes-allocation-plan.v1"
        assert verified["status"] == "verified-ready-to-apply"
        assert verified["applied"] is False
        assert verified["assignment_status"] == "assigned"
        assert verified["public_profile_status"] == "assigned-ready"
        assert verified["public_release_allowed"] is True
        assert verified["active_runtime_profile"] == "development_compatibility"
        assert verified["runtime_profile_changed"] is False
        assert verified["pull_request"]["merge_commit"] == merge_commit
        assert verified["pull_request"]["merged_at"] == "2026-07-19T01:02:03Z"
        assert verified["upstream_check"]["content_verified"] is True
        assert verified["upstream_check"]["merge_commit_reachable"] is True
        assert verified["confirmation_required"] == CONFIRMATION
        assert contract_path.read_bytes() == original

        no_confirmation = run(
            upstream,
            "--apply",
            root=project,
            check=False,
            environment_overrides=environment,
        )
        assert no_confirmation.returncode != 0
        assert "requires --confirm" in no_confirmation.stderr
        assert contract_path.read_bytes() == original

        confirm_without_apply = run(
            upstream,
            "--confirm",
            CONFIRMATION,
            root=project,
            check=False,
            environment_overrides=environment,
        )
        assert confirm_without_apply.returncode != 0
        assert "only valid with --apply" in confirm_without_apply.stderr

        open_environment = dict(environment)
        open_environment["HIDLOOM_TEST_PR_JSON"] = pull_request_payload(
            merge_commit, state="OPEN"
        )
        open_pr = run(
            upstream,
            root=project,
            check=False,
            environment_overrides=open_environment,
        )
        assert open_pr.returncode != 0
        assert "is not merged" in open_pr.stderr

        wrong_head_environment = dict(environment)
        wrong_head_environment["HIDLOOM_TEST_PR_JSON"] = pull_request_payload(
            merge_commit, head="4" * 40
        )
        wrong_head = run(
            upstream,
            root=project,
            check=False,
            environment_overrides=wrong_head_environment,
        )
        assert wrong_head.returncode != 0
        assert "head does not match recorded evidence" in wrong_head.stderr

        missing_check_environment = dict(environment)
        missing_check_environment["HIDLOOM_TEST_PR_JSON"] = pull_request_payload(
            merge_commit, checks=("Python Validator",)
        )
        missing_check = run(
            upstream,
            root=project,
            check=False,
            environment_overrides=missing_check_environment,
        )
        assert missing_check.returncode != 0
        assert "required checks are missing" in missing_check.stderr

        failed_check_environment = dict(environment)
        failed_check_environment["HIDLOOM_TEST_PR_JSON"] = pull_request_payload(
            merge_commit,
            checks=("HTML Proofer", "Python Validator", "HTML Proofer"),
            failed_checks=("HTML Proofer",),
        )
        failed_check = run(
            upstream,
            root=project,
            check=False,
            environment_overrides=failed_check_environment,
        )
        assert failed_check.returncode != 0
        assert "required checks are not successful" in failed_check.stderr

        unreachable_environment = dict(environment)
        unreachable_environment["HIDLOOM_TEST_PR_JSON"] = pull_request_payload(
            "f" * 40
        )
        unreachable = run(
            upstream,
            root=project,
            check=False,
            environment_overrides=unreachable_environment,
        )
        assert unreachable.returncode != 0
        assert "merge commit is not reachable" in unreachable.stderr

        candidate_path = upstream / "1209/484C/index.md"
        candidate_path.write_text(
            candidate_path.read_text(encoding="utf-8") + "drift\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=upstream, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "Drift fixture"], cwd=upstream, check=True
        )
        drift_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=upstream, text=True
        ).strip()
        update_origin_head(upstream, drift_commit)
        drift_environment = dict(environment)
        drift_environment["HIDLOOM_TEST_REMOTE_HEAD"] = drift_commit
        drift = run(
            upstream,
            root=project,
            check=False,
            environment_overrides=drift_environment,
        )
        assert drift.returncode != 0
        assert "device page does not match" in drift.stderr
        subprocess.run(
            ["git", "reset", "--hard", merge_commit],
            cwd=upstream,
            check=True,
            capture_output=True,
        )
        update_origin_head(upstream, merge_commit)

        applied = json.loads(
            run(
                upstream,
                "--apply",
                "--confirm",
                CONFIRMATION,
                root=project,
                environment_overrides=environment,
            ).stdout
        )
        assert applied["status"] == "applied"
        assert applied["applied"] is True
        assert applied["confirmation_required"] is None
        assigned = json.loads(contract_path.read_text(encoding="utf-8"))
        assert assigned["active_runtime_profile"] == "development_compatibility"
        assert assigned["assignment"]["status"] == "assigned"
        evidence = assigned["assignment"]["allocation_evidence"]
        assert evidence["merge_commit"] == merge_commit
        assert evidence["upstream_commit"] == merge_commit
        assert evidence["content_verified"] is True
        assert assigned["profiles"]["public_formal"]["status"] == "assigned-ready"
        assert assigned["profiles"]["public_formal"]["public_release_allowed"] is True

        formal_output = temporary_path / "formal-profile"
        formal = subprocess.run(
            [
                "python3",
                str(IDENTITY_TOOL),
                "--root",
                str(project),
                "--output",
                str(formal_output),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        formal_plan = json.loads(formal.stdout)
        assert formal_plan["activation_allowed"] is True
        assert formal_plan["device_config"]["vendor_id"] == "0x1209"
        assert formal_plan["device_config"]["product_id"] == "0x484c"

        repeated = run(
            upstream,
            root=project,
            check=False,
            environment_overrides=environment,
        )
        assert repeated.returncode != 0
        assert "must remain candidate-unassigned" in repeated.stderr

    print("ok: merged pid.codes evidence, content guard, and confirmed allocation apply")


if __name__ == "__main__":
    main()
