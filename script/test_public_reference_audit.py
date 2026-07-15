#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def run_audit(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(root / "tools/public_reference_audit.py"), str(root)],
        cwd=root,
        capture_output=True,
        text=True,
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        export = Path(temporary) / "public"
        subprocess.run(
            ["python3", str(ROOT / "tools/public_export.py"), str(export), "--draft"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        report = json.loads((export / "PUBLIC_REFERENCE_AUDIT.json").read_text(encoding="utf-8"))
        assert report["ready"] is True
        assert report["summary"]["blockers"] == 0
        assert report["summary"]["public_repository_references"] > 0
        assert report["public_repository"]["slug"] == "cqa02303/hidloom"
        assert report["published_release_tags"] == []

        release_tag = "v9.9.9+test"
        encoded_release_tag = release_tag.replace("+", "%2B")
        public_release_url = (
            "https://github.com/"
            + "cqa02303/hidloom"
            + f"/releases/tag/{encoded_release_tag}"
        )
        with (export / "README.md").open("a", encoding="utf-8") as stream:
            stream.write(f"\n{public_release_url}.\n")
        undeclared_release = run_audit(export)
        assert undeclared_release.returncode == 2
        release_report = json.loads(
            (export / "PUBLIC_REFERENCE_AUDIT.json").read_text(encoding="utf-8")
        )
        assert any(
            item["kind"] == "undeclared_public_release_reference"
            and item["tag"] == release_tag
            for item in release_report["findings"]
        )

        policy_path = export / "config/publication-policy.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy.pop("published_release_tags")
        policy_path.write_text(
            json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        missing_declaration = run_audit(export)
        assert missing_declaration.returncode != 0
        assert "requires a list" in missing_declaration.stderr

        policy["published_release_tags"] = [release_tag, release_tag]
        policy_path.write_text(
            json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        duplicate_declaration = run_audit(export)
        assert duplicate_declaration.returncode != 0
        assert "unique and sorted" in duplicate_declaration.stderr

        policy["published_release_tags"] = [release_tag]
        policy_path.write_text(
            json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        declared_release = run_audit(export)
        assert declared_release.returncode == 0, (
            declared_release.stdout + declared_release.stderr
        )
        declared_report = json.loads(
            (export / "PUBLIC_REFERENCE_AUDIT.json").read_text(encoding="utf-8")
        )
        assert declared_report["published_release_tags"] == [release_tag]

        owner = "c" + "qa" + "02303"
        private_slug = owner + "/" + owner + "v5rpi"
        local_remote = "file:" + "///tmp/private-hidloom.git"
        with (export / "README.md").open("a", encoding="utf-8") as stream:
            stream.write(f"\nhttps://github.com/{private_slug}.git\n")
            stream.write(local_remote + "\n")
        blocked = run_audit(export)
        assert blocked.returncode == 2
        blocked_report = json.loads((export / "PUBLIC_REFERENCE_AUDIT.json").read_text(encoding="utf-8"))
        kinds = {item["kind"] for item in blocked_report["findings"]}
        assert "blocked_private_repository_reference" in kinds
        assert "absolute_local_repository_remote" in kinds

    print("ok: public references reject private/local remotes and undeclared releases")


if __name__ == "__main__":
    main()
