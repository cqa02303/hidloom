#!/usr/bin/env python3
"""Distinct private/public histories and fail-closed publication mapping fixtures."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import public_export_manifest as export


def module(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools/package" / (name + ".py"))
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


publisher = module("publish_public_release_bundle")
verifier = module("verify_github_public_release_bundle")


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


def initialize(root: Path) -> None:
    root.mkdir()
    git(root, "init", "--quiet")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@localhost")
    git(root, "config", "core.autocrlf", "false")
    git(root, "config", "core.filemode", "true")


def commit(root: Path) -> str:
    # Only this test's disposable fixture files are ever staged.
    git(root, "add", "--all", ".")
    git(root, "commit", "--quiet", "--allow-empty", "-m", "fixture")
    return git(root, "rev-parse", "HEAD")


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hidloom-mapping-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.private = self.root / "private"
        self.public = self.root / "public"
        initialize(self.private)
        (self.private / "private-only.txt").write_text("private history, never copied to public\n")
        self.source_commit = commit(self.private)
        initialize(self.public)
        git(self.public, "remote", "add", "origin", "https://github.com/cqa02303/hidloom.git")
        (self.public / "tool.py").write_text("print('public source')\n")
        (self.public / "tool.py").chmod(0o755)
        self.provenance = {
            "schema": export.PROVENANCE_SCHEMA, "mode": "clean-head", "publishable": True,
            "base_commit": self.source_commit, "base_tree": git(self.private, "rev-parse", "HEAD^{tree}"),
            "base_revision_count": 1, "selected_path_count": 1,
            "selected_snapshot_sha256": hashlib.sha256(b"private selected source snapshot").hexdigest(),
        }
        write_json(self.public / export.REPORT_NAME, {
            "schema": export.REPORT_SCHEMA, "source_provenance": self.provenance, "file_count": 1,
            "source_selection": {"tracked_paths": 1, "public_source_paths": 1,
                                 "private_only_paths": 0, "generated_output_paths": 0, "unclassified_paths": 0},
        })
        self.refresh_manifest()
        self.public_commit = commit(self.public)
        self.mapping = export.verify_git_commit(self.public, self.public_commit)
        self.source = {"commit": self.source_commit, "tree": self.provenance["base_tree"],
                       "snapshot_sha256": self.provenance["selected_snapshot_sha256"],
                       "export_manifest_sha256": self.mapping["export_manifest_sha256"]}
        self.bundle = self.root / "bundle"
        self.bundle.mkdir()
        self.manifest = {"schema": "hidloom.public-release-bundle.v5", "version": "1.0+git" + self.source_commit[:12],
                         "source": self.source, "release_channels": {"selected": "stable-public",
                         "statuses": {"stable-public": {"ready": True, "blockers": []}}}}
        write_json(self.bundle / "RELEASE_MANIFEST.json", self.manifest)
        (self.bundle / "RELEASE_NOTES.md").write_text("fixture\n")
        self.checksums()
        self.patch_root = patch.object(publisher, "ROOT", self.public)
        self.patch_verify = patch.object(publisher, "verify_local_bundle", return_value={
            "source_mapping": {key: value for key, value in self.mapping.items() if key not in {"commit", "tree"}}})
        self.patch_root.start()
        self.patch_verify.start()
        self.addCleanup(self.patch_root.stop)
        self.addCleanup(self.patch_verify.stop)

    def refresh_manifest(self):
        entries = []
        for name in ("tool.py", export.REPORT_NAME):
            path = self.public / name
            content = path.read_bytes()
            entries.append({"path": name, "kind": "file", "mode": 0o755 if name == "tool.py" else 0o644,
                            "size": len(content), "sha256": hashlib.sha256(content).hexdigest()})
        write_json(self.public / export.MANIFEST_NAME, {"schema": export.MANIFEST_SCHEMA,
                   "source_provenance": self.provenance, "files": entries})

    def checksums(self):
        (self.bundle / "SHA256SUMS").write_text("".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
            for path in sorted(self.bundle.iterdir()) if path.name != "SHA256SUMS"))

    def plan(self):
        return publisher.build_plan(self.bundle, "cqa02303/hidloom", "vfixture")

    def test_distinct_history_success_and_immutable_target(self):
        self.assertNotEqual(self.source_commit, self.public_commit)
        absent = subprocess.run(["git", "-C", str(self.public), "cat-file", "-e", self.source_commit], capture_output=True)
        self.assertNotEqual(absent.returncode, 0)
        plan = self.plan()
        self.assertTrue(plan["ready"], plan["blockers"])
        self.assertEqual(plan["source_commit"], self.source_commit)
        self.assertEqual(plan["public_target"]["commit"], self.public_commit)
        self.assertEqual(plan["command"][plan["command"].index("--target") + 1], self.public_commit)
        self.assertEqual(plan["bundle_manifest_sha256"], plan["asset_sha256"]["RELEASE_MANIFEST.json"])
        publisher.revalidate_plan(plan)

    def test_committed_object_validation_ignores_mutable_files(self):
        (self.public / "tool.py").write_text("dirty\n")
        self.assertEqual(export.verify_git_commit(self.public, self.public_commit), self.mapping)
        self.assertIn("git-worktree-not-clean", self.plan()["blockers"])

    def test_committed_extra_missing_bytes_modes_and_kinds(self):
        original = (self.public / "tool.py").read_bytes()
        for mutation in ("extra", "missing", "bytes", "mode", "kind"):
            with self.subTest(mutation=mutation):
                work = self.root / mutation
                subprocess.run(["git", "clone", "--quiet", str(self.public), str(work)], check=True, capture_output=True)
                git(work, "config", "user.name", "Fixture")
                git(work, "config", "user.email", "fixture@localhost")
                target = work / "tool.py"
                if mutation == "extra":
                    (work / "extra.txt").write_text("unlisted\n")
                elif mutation == "missing":
                    target.unlink()
                elif mutation == "bytes":
                    target.write_bytes(original.replace(b"public", b"edited"))
                elif mutation == "mode":
                    target.chmod(0o644)
                    git(work, "update-index", "--chmod=-x", "tool.py")
                else:
                    target.unlink()
                    target.symlink_to(export.REPORT_NAME)
                changed = commit(work)
                with self.assertRaises(SystemExit):
                    export.verify_git_commit(work, changed)

    def test_invalid_manifest_report_provenance_and_draft(self):
        for mutation in ("report", "draft", "manifest-schema", "unsafe-path", "self-listed"):
            with self.subTest(mutation=mutation):
                manifest = json.loads((self.public / export.MANIFEST_NAME).read_text())
                if mutation == "report":
                    manifest["source_provenance"] = {**self.provenance, "base_commit": "c" * 40}
                elif mutation == "draft":
                    self.provenance.update(mode="dirty-worktree", publishable=False)
                    report = json.loads((self.public / export.REPORT_NAME).read_text())
                    report["source_provenance"] = self.provenance
                    write_json(self.public / export.REPORT_NAME, report)
                    self.refresh_manifest()
                    manifest = json.loads((self.public / export.MANIFEST_NAME).read_text())
                elif mutation == "manifest-schema":
                    manifest["schema"] = "wrong"
                elif mutation == "unsafe-path":
                    manifest["files"][0]["path"] = "../outside"
                else:
                    manifest["files"].append({"path": export.MANIFEST_NAME})
                write_json(self.public / export.MANIFEST_NAME, manifest)
                with self.assertRaises(SystemExit):
                    export.verify_git_commit(self.public, commit(self.public))
                self.provenance.update(mode="clean-head", publishable=True)
                report = json.loads((self.public / export.REPORT_NAME).read_text())
                report["source_provenance"] = self.provenance
                write_json(self.public / export.REPORT_NAME, report)
                self.refresh_manifest()

    def test_each_source_binding_field_must_match(self):
        for field in self.source:
            changed = dict(self.source)
            changed[field] = "0" * len(str(changed[field]))
            with self.subTest(field=field), self.assertRaises(SystemExit):
                export.bind_release_source(self.mapping, changed)

    def test_refuses_origin_channel_and_hardware_gates(self):
        git(self.public, "remote", "set-url", "origin", "https://github.com/private/wrong.git")
        self.assertIn("origin-is-not-public-repository", self.plan()["blockers"])
        for gate in ("public-usb-identity-not-assigned", "hardware-smoke-not-passed",
                     "touch-hardware-smoke-not-passed", "public-build-provenance-missing"):
            self.manifest["release_channels"]["statuses"]["stable-public"] = {"ready": False, "blockers": [gate]}
            write_json(self.bundle / "RELEASE_MANIFEST.json", self.manifest)
            self.checksums()
            self.assertIn("release-channel:" + gate, self.plan()["blockers"])

    def test_revalidation_refuses_moved_head_and_asset_replacement(self):
        plan = self.plan()
        (self.bundle / "RELEASE_NOTES.md").write_text("changed\n")
        self.checksums()
        with self.assertRaisesRegex(SystemExit, "changed after planning"):
            publisher.revalidate_plan(plan)
        self.assertNotEqual(plan["confirmation"], self.plan()["confirmation"])
        moved_plan = self.plan()
        commit(self.public)
        with self.assertRaisesRegex(SystemExit, "changed after planning"):
            publisher.revalidate_plan(moved_plan)
        with self.assertRaisesRegex(SystemExit, "v3"):
            publisher.revalidate_plan({**plan, "schema": "hidloom.public-release-publish-plan.v2"})

    def online(self, command, *, unavailable=False, release=False, tag=False, api_error=False):
        if command[:3] == ["gh", "repo", "view"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"nameWithOwner": "cqa02303/hidloom", "visibility": "PUBLIC"}), "")
        self.assertEqual(command[:2], ["gh", "api"])
        if "/commits/" in command[2]:
            self.assertTrue(command[2].endswith(self.public_commit))
            return subprocess.CompletedProcess(command, int(unavailable), self.public_commit, "unavailable" if unavailable else "")
        present = release if "/releases/tags/" in command[2] else tag
        return subprocess.CompletedProcess(command, 0 if present else 1, "{}", "HTTP 500" if api_error else "HTTP 404")

    def test_online_uses_only_public_commit_and_all_failures_block(self):
        plan = self.plan()
        with patch.object(publisher.shutil, "which", return_value="/fixture/gh"):
            with patch.object(publisher, "run", side_effect=self.online):
                publisher.online_preflight(plan)
            for flag in ("unavailable", "release", "tag", "api_error"):
                with self.subTest(flag=flag), patch.object(publisher, "run", side_effect=lambda command: self.online(command, **{flag: True})):
                    with self.assertRaises(SystemExit):
                        publisher.online_preflight(plan)
        with patch.object(publisher, "online_preflight") as online:
            with self.assertRaises(SystemExit):
                publisher.execute_plan(plan, "wrong confirmation")
            online.assert_not_called()

    def test_execution_rechecks_before_mutation_and_binds_readback(self):
        plan = self.plan()
        calls = []
        def fake_run(command, **kwargs):
            calls.append(command)
            if command[:3] == ["gh", "release", "create"]:
                return subprocess.CompletedProcess(command, 0, "created", "")
            expected = json.loads(Path(command[command.index("--expected-plan") + 1]).read_text())
            self.assertEqual(expected, plan)
            return subprocess.CompletedProcess(command, 0, "verified", "")
        with patch.object(publisher, "online_preflight"), patch.object(publisher, "revalidate_plan") as recheck, patch.object(publisher, "run", side_effect=fake_run):
            publisher.execute_plan(plan, plan["confirmation"])
            recheck.assert_called_once_with(plan)
        self.assertEqual(calls[0][calls[0].index("--target") + 1], self.public_commit)
        with patch.object(publisher, "online_preflight"), patch.object(publisher, "revalidate_plan", side_effect=SystemExit("moved")), patch.object(publisher, "run") as run:
            with self.assertRaises(SystemExit):
                publisher.execute_plan(plan, plan["confirmation"])
            run.assert_not_called()

    def test_lightweight_annotated_wrong_api_and_cyclic_tags(self):
        lightweight = {"ref": "refs/tags/vfixture", "object": {"type": "commit", "sha": self.public_commit}}
        annotated = {"ref": "refs/tags/vfixture", "object": {"type": "tag", "sha": "a" * 40}}
        annotation = {"sha": "a" * 40, "object": lightweight["object"]}
        with patch.object(verifier, "api_json", return_value=lightweight):
            self.assertEqual(verifier.resolve_release_tag("cqa02303/hidloom", "vfixture"), self.public_commit)
        with patch.object(verifier, "api_json", side_effect=[annotated, annotation]):
            self.assertEqual(verifier.resolve_release_tag("cqa02303/hidloom", "vfixture"), self.public_commit)
        for result in ({**lightweight, "ref": "refs/tags/wrong"},
                       {**lightweight, "object": {"type": "blob", "sha": self.public_commit}}):
            with patch.object(verifier, "api_json", return_value=result), self.assertRaises(SystemExit):
                verifier.resolve_release_tag("cqa02303/hidloom", "vfixture")
        for second in ({**annotation, "sha": "b" * 40}, {**annotation, "object": annotated["object"]}):
            with patch.object(verifier, "api_json", side_effect=[annotated, second]), self.assertRaises(SystemExit):
                verifier.resolve_release_tag("cqa02303/hidloom", "vfixture")
        with patch.object(verifier, "run", return_value=subprocess.CompletedProcess([], 1, "", "HTTP 403")), self.assertRaises(SystemExit):
            verifier.resolve_release_tag("cqa02303/hidloom", "vfixture")

    def test_readback_fetches_only_public_objects_and_refuses_wrong_mapping(self):
        result = {"source_mapping": {key: value for key, value in self.mapping.items() if key not in {"commit", "tree"}}}
        expected = {"repository": "cqa02303/hidloom", **self.mapping}
        real_run = verifier.run
        def local_fetch(command, **kwargs):
            command = list(command)
            if "fetch" in command:
                self.assertEqual(command[-2], "https://github.com/cqa02303/hidloom.git")
                self.assertEqual(command[-1], self.public_commit)
                command[-2] = str(self.public)
            return real_run(command, **kwargs)
        with patch.object(verifier, "run", side_effect=local_fetch), patch.object(verifier, "resolve_release_tag", return_value=self.public_commit):
            self.assertEqual(verifier.verify_remote_target("cqa02303/hidloom", "vfixture", result, expected), expected)
            with self.assertRaisesRegex(SystemExit, "expected public target"):
                verifier.verify_remote_target("cqa02303/hidloom", "vfixture", result, {**expected, "commit": "e" * 40})
            with self.assertRaisesRegex(SystemExit, "corresponding source"):
                verifier.verify_remote_target("cqa02303/hidloom", "vfixture", {"source_mapping": {**result["source_mapping"], "source_snapshot_sha256": "0" * 64}})
            with self.assertRaisesRegex(SystemExit, "mapping changed"):
                verifier.verify_remote_target("cqa02303/hidloom", "vfixture", result, {**expected, "tree": "e" * 40})
        with patch.object(verifier, "run", side_effect=local_fetch), patch.object(verifier, "resolve_release_tag", side_effect=[self.public_commit, "e" * 40]), self.assertRaisesRegex(SystemExit, "moved"):
            verifier.verify_remote_target("cqa02303/hidloom", "vfixture", result, expected)

    def make_archive(self, mutation=None):
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode="w") as tar:
            root = tarfile.TarInfo("source")
            root.type = tarfile.DIRTYPE
            root.mode = 0o755
            tar.addfile(root)
            for name in (export.MANIFEST_NAME, export.REPORT_NAME, "tool.py"):
                content = (self.public / name).read_bytes()
                item = tarfile.TarInfo("source/" + name)
                item.mode = 0o755 if name == "tool.py" else 0o644
                if mutation == "bytes" and name == "tool.py":
                    content += b"altered\n"
                if mutation == "mode" and name == "tool.py":
                    item.mode = 0o644
                if mutation == "kind" and name == "tool.py":
                    item.type = tarfile.SYMTYPE
                    item.linkname = export.REPORT_NAME
                    item.mode = 0o777
                item.size = len(content) if item.isfile() else 0
                tar.addfile(item, io.BytesIO(content) if item.isfile() else None)
            if mutation == "extra":
                item = tarfile.TarInfo("source/unlisted")
                item.mode = 0o644
                tar.addfile(item)
        archive = self.root / (str(mutation) + ".tar.zst")
        compressed = subprocess.run(["zstd", "-q", "-c"], input=raw.getvalue(), capture_output=True, check=True)
        archive.write_bytes(compressed.stdout)
        return archive

    def test_archive_identity_bytes_modes_kinds_and_exact_paths(self):
        for mutation in (None, "bytes", "mode", "kind", "extra"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                if mutation is None:
                    _, identity = verifier.extract_verified_source(self.make_archive(), Path(temporary))
                    export.bind_release_source(identity, self.source)
                else:
                    with self.assertRaises(SystemExit):
                        verifier.extract_verified_source(self.make_archive(mutation), Path(temporary))

    def test_deep_verification_refuses_source_asset_hash_before_execution(self):
        archive = self.make_archive()
        content = archive.read_bytes()
        (self.bundle / archive.name).write_bytes(content)
        self.manifest["assets"] = [{"role": "corresponding-source", "path": archive.name,
                                     "sha256": "0" * 64, "size": len(content)}]
        write_json(self.bundle / "RELEASE_MANIFEST.json", self.manifest)
        self.checksums()
        with self.assertRaisesRegex(SystemExit, "asset does not match"):
            verifier.deep_verify(self.bundle, require_publication_ready=False,
                                 require_hardware_pass=False, require_channel_ready=None)


if __name__ == "__main__":
    unittest.main()
