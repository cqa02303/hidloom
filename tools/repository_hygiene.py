#!/usr/bin/env python3
"""Reject generated artifacts and accidental workspace state in tracked files."""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "repository-hygiene.json"
PUBLIC_MANIFEST = "PUBLIC_EXPORT_MANIFEST.json"
WINDOWS_INVALID_CHARACTERS = frozenset('<>:"\\|?*')
WINDOWS_RESERVED_BASENAMES = frozenset(
    {
        "AUX",
        "CLOCK$",
        "CON",
        "CONIN$",
        "CONOUT$",
        "NUL",
        "PRN",
        "COM¹",
        "COM²",
        "COM³",
        "LPT¹",
        "LPT²",
        "LPT³",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
)


@dataclass(frozen=True, order=True)
class Finding:
    kind: str
    path: str
    detail: str


def load_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("schema") != "hidloom.repository-hygiene.v5":
        raise ValueError(f"unsupported repository hygiene schema: {config.get('schema')}")
    policy = config.get("portable_path_policy")
    if not isinstance(policy, dict) or policy.get("unicode_normalization") != "NFC":
        raise ValueError("repository hygiene requires NFC portable path policy")
    if policy.get("casefold_collisions") is not True:
        raise ValueError("repository hygiene must reject casefold path collisions")
    for field in ("max_relative_path_utf16_units", "max_component_utf16_units"):
        if not isinstance(policy.get(field), int) or policy[field] <= 0:
            raise ValueError(f"invalid portable path limit: {field}")
    content_policy = config.get("tracked_content_policy")
    if not isinstance(content_policy, dict):
        raise ValueError("repository hygiene requires tracked content policy")
    if content_policy.get("encoding") != "UTF-8":
        raise ValueError("tracked text encoding must be UTF-8")
    if content_policy.get("line_endings") != "LF":
        raise ValueError("tracked text line endings must be LF")
    for field in (
        "reject_bom",
        "require_final_newline",
        "reject_trailing_whitespace",
        "executable_requires_shebang",
        "shell_requires_executable",
    ):
        if content_policy.get(field) is not True:
            raise ValueError(f"tracked content policy must enable {field}")
    for field in ("shell_path_globs", "binary_path_globs", "empty_file_allow_globs"):
        values = content_policy.get(field)
        if not isinstance(values, list) or not all(
            isinstance(value, str) and value for value in values
        ):
            raise ValueError(f"tracked content policy requires string list: {field}")
    duplicate_threshold = config.get("duplicate_file_threshold_bytes")
    if (
        not isinstance(duplicate_threshold, int)
        or isinstance(duplicate_threshold, bool)
        or duplicate_threshold < 1
    ):
        raise ValueError("duplicate file threshold must be a positive integer")
    duplicate_allow_groups = config.get("duplicate_file_allow_groups")
    if not isinstance(duplicate_allow_groups, list):
        raise ValueError("repository hygiene requires duplicate file allow groups")
    group_signatures: list[tuple[str, ...]] = []
    allowed_paths: set[str] = set()
    for index, rule in enumerate(duplicate_allow_groups):
        if not isinstance(rule, dict):
            raise ValueError(f"duplicate file allow group {index} must be an object")
        paths = rule.get("paths")
        reason = rule.get("reason")
        if (
            not isinstance(paths, list)
            or len(paths) < 2
            or not all(isinstance(value, str) and value for value in paths)
        ):
            raise ValueError(f"duplicate file allow group {index} requires at least two paths")
        normalized_paths = [normalized_path(value) for value in paths]
        if paths != sorted(set(normalized_paths)):
            raise ValueError(
                f"duplicate file allow group {index} paths must be unique and sorted"
            )
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"duplicate file allow group {index} requires a reason")
        overlap = allowed_paths.intersection(paths)
        if overlap:
            raise ValueError(
                "duplicate file allow paths may appear in only one group: "
                + ",".join(sorted(overlap))
            )
        allowed_paths.update(paths)
        group_signatures.append(tuple(paths))
    if group_signatures != sorted(group_signatures):
        raise ValueError("duplicate file allow groups must be sorted by path set")
    return config


def matches(path: str, pattern: str) -> bool:
    if fnmatch.fnmatch(path, pattern):
        return True
    return pattern.startswith("**/") and fnmatch.fnmatch(path, pattern[3:])


def normalized_path(path: str) -> str:
    normalized = PurePosixPath(path)
    if (
        not path
        or normalized.is_absolute()
        or ".." in normalized.parts
        or normalized.as_posix() != path
    ):
        raise ValueError(f"unsafe tracked path: {path}")
    return normalized.as_posix()


def utf16_units(value: str) -> int | None:
    try:
        return len(value.encode("utf-16-le")) // 2
    except UnicodeEncodeError:
        return None


def portable_path_findings(paths: list[str], policy: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    normalization = str(policy["unicode_normalization"])
    max_path_units = int(policy["max_relative_path_utf16_units"])
    max_component_units = int(policy["max_component_utf16_units"])
    portable_prefixes: dict[tuple[str, ...], str] = {}
    reported_collisions: set[tuple[str, str]] = set()

    for relative in paths:
        path_units = utf16_units(relative)
        if path_units is None:
            findings.append(
                Finding("nonportable_path", relative, "path is not valid Unicode")
            )
        elif path_units > max_path_units:
            findings.append(
                Finding(
                    "nonportable_path",
                    relative,
                    f"path uses {path_units} UTF-16 units; maximum is {max_path_units}",
                )
            )

        original_parts: list[str] = []
        portable_parts: list[str] = []
        for component in PurePosixPath(relative).parts:
            original_parts.append(component)
            component_units = utf16_units(component)
            if component_units is None:
                findings.append(
                    Finding("nonportable_path", relative, "component is not valid Unicode")
                )
                normalized_component = component
            else:
                normalized_component = unicodedata.normalize(normalization, component)
                if normalized_component != component:
                    findings.append(
                        Finding(
                            "nonportable_path",
                            relative,
                            f"component is not {normalization}-normalized: {component!r}",
                        )
                    )
                if component_units > max_component_units:
                    findings.append(
                        Finding(
                            "nonportable_path",
                            relative,
                            f"component uses {component_units} UTF-16 units; maximum is "
                            f"{max_component_units}",
                        )
                    )

            if component.endswith((" ", ".")):
                findings.append(
                    Finding(
                        "nonportable_path",
                        relative,
                        f"component ends with a Windows-trimmed character: {component!r}",
                    )
                )
            invalid_codepoints = [
                f"U+{ord(character):04X}"
                for character in component
                if ord(character) < 32 or character in WINDOWS_INVALID_CHARACTERS
            ]
            if invalid_codepoints:
                findings.append(
                    Finding(
                        "nonportable_path",
                        relative,
                        "component contains Windows-invalid code point(s): "
                        + ",".join(sorted(set(invalid_codepoints))),
                    )
                )
            device_basename = component.split(".", 1)[0].upper()
            if device_basename in WINDOWS_RESERVED_BASENAMES or component.casefold() == ".git":
                findings.append(
                    Finding(
                        "nonportable_path",
                        relative,
                        f"component is reserved on Windows/Git: {component!r}",
                    )
                )

            portable_parts.append(normalized_component.casefold())
            portable_key = tuple(portable_parts)
            original_prefix = "/".join(original_parts)
            previous = portable_prefixes.setdefault(portable_key, original_prefix)
            if previous == original_prefix:
                continue
            collision = tuple(sorted((previous, original_prefix)))
            if collision in reported_collisions:
                continue
            reported_collisions.add(collision)
            findings.append(
                Finding(
                    "portable_path_collision",
                    collision[0],
                    f"collides with {collision[1]} after {normalization}/casefold",
                )
            )
    return findings


def git_tracked_files(root: Path) -> tuple[list[str], dict[str, int]] | None:
    try:
        top_level = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    if Path(top_level).resolve() != root:
        return None
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--stage", "-z"],
        check=True,
        stdout=subprocess.PIPE,
    )
    modes: dict[str, int] = {}
    for item in result.stdout.split(b"\0"):
        if not item:
            continue
        metadata, raw_path = item.split(b"\t", 1)
        raw_mode, _object_id, raw_stage = metadata.split()
        path = normalized_path(os.fsdecode(raw_path))
        if raw_stage != b"0":
            raise ValueError(f"unmerged tracked path is not publishable: {path}")
        modes[path] = int(raw_mode, 8)
    return sorted(modes), modes


def git_ignored_tracked_files(root: Path) -> list[str]:
    try:
        top_level = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return []
    if Path(top_level).resolve() != root:
        return []
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-ci", "--exclude-standard", "-z"],
        check=True,
        stdout=subprocess.PIPE,
    )
    return sorted(normalized_path(os.fsdecode(item)) for item in result.stdout.split(b"\0") if item)


def public_manifest_files(root: Path) -> tuple[list[str], dict[str, int]] | None:
    manifest_path = root / PUBLIC_MANIFEST
    if not manifest_path.is_file():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "hidloom.public-export-manifest.v2":
        raise ValueError(f"unsupported public export manifest: {manifest.get('schema')}")
    modes: dict[str, int] = {}
    for item in manifest.get("files", []):
        path = normalized_path(item["path"])
        mode = item.get("mode")
        if not isinstance(mode, int) or mode < 0 or mode > 0o777:
            raise ValueError(f"invalid public manifest mode for {path}: {mode!r}")
        modes[path] = mode
    paths = list(modes)
    paths.append(PUBLIC_MANIFEST)
    modes[PUBLIC_MANIFEST] = 0o644
    return sorted(set(paths)), modes


def tracked_files(root: Path) -> tuple[list[str], dict[str, int], str]:
    inventory = git_tracked_files(root)
    if inventory is not None:
        paths, modes = inventory
        return paths, modes, "git index"
    inventory = public_manifest_files(root)
    if inventory is not None:
        paths, modes = inventory
        return paths, modes, PUBLIC_MANIFEST
    raise RuntimeError(
        f"cannot determine tracked files below {root}; use a Git checkout or a public export manifest"
    )


def scan(
    root: Path,
    paths: list[str],
    modes: dict[str, int],
    config: dict[str, Any],
) -> tuple[list[Finding], int]:
    findings = portable_path_findings(paths, config["portable_path_policy"])
    sizes: dict[str, int] = {}
    duplicate_candidates: dict[str, list[str]] = {}
    forbidden_path_globs = config["forbidden_path_globs"]
    forbidden_path_allow_globs = config.get("forbidden_path_allow_globs", [])
    large_threshold = int(config["large_file_threshold_bytes"])
    duplicate_threshold = int(config["duplicate_file_threshold_bytes"])
    allowed_duplicate_groups = {
        frozenset(rule["paths"]): str(rule["reason"])
        for rule in config["duplicate_file_allow_groups"]
    }
    observed_allowed_groups: set[frozenset[str]] = set()
    content_policy = config["tracked_content_policy"]
    binary_path_globs = content_policy["binary_path_globs"]
    empty_file_allow_globs = content_policy["empty_file_allow_globs"]
    shell_path_globs = content_policy["shell_path_globs"]
    path_set = set(paths)

    for rule in config.get("required_companion_rules", []):
        companion_name = str(rule["companion_name"])
        if PurePosixPath(companion_name).name != companion_name:
            raise ValueError(f"companion_name must be a filename: {companion_name}")
        for relative in paths:
            if not matches(relative, str(rule["source_glob"])):
                continue
            companion = PurePosixPath(relative).with_name(companion_name).as_posix()
            if companion not in path_set:
                findings.append(
                    Finding(
                        "missing_companion_file",
                        companion,
                        f"required by tracked source {relative}",
                    )
                )

    for relative in paths:
        path = root / relative
        if not path.exists() and not path.is_symlink():
            findings.append(Finding("missing_tracked_file", relative, "listed file is absent"))
            continue
        if path.is_dir():
            findings.append(Finding("tracked_directory", relative, "inventory entries must be files"))
            continue

        if any(matches(relative, pattern) for pattern in forbidden_path_globs) and not any(
            matches(relative, pattern) for pattern in forbidden_path_allow_globs
        ):
            findings.append(Finding("generated_path", relative, "path is reserved for generated output"))

        basename = PurePosixPath(relative).name
        if any(fnmatch.fnmatch(basename, pattern) for pattern in config["forbidden_name_globs"]):
            findings.append(Finding("forbidden_artifact", relative, "filename matches generated artifact policy"))

        for rule in config.get("ephemeral_roots", []):
            if relative.startswith(rule["path"]) and not any(
                matches(relative, pattern) for pattern in rule.get("allowed_globs", [])
            ):
                findings.append(
                    Finding("runtime_artifact", relative, f"runtime files below {rule['path']} are private state")
                )

        if path.is_symlink():
            target = os.readlink(path)
            resolved = (path.parent / target).resolve()
            if Path(target).is_absolute() or (resolved != root and root not in resolved.parents):
                findings.append(Finding("unsafe_symlink", relative, f"target escapes repository: {target}"))
            content = target.encode()
            size = len(content)
        else:
            content = path.read_bytes()
            size = len(content)
            if not modes[relative] & 0o111 and any(
                matches(relative, pattern) for pattern in shell_path_globs
            ):
                findings.append(
                    Finding(
                        "non_executable_shell",
                        relative,
                        "tracked shell entrypoints must retain an executable mode",
                    )
                )
            if modes[relative] & 0o111 and not content.startswith(b"#!"):
                findings.append(
                    Finding(
                        "executable_without_shebang",
                        relative,
                        "tracked executable source must start with #!",
                    )
                )
            if not any(matches(relative, pattern) for pattern in binary_path_globs):
                if not content:
                    if not any(
                        matches(relative, pattern) for pattern in empty_file_allow_globs
                    ):
                        findings.append(
                            Finding(
                                "empty_tracked_file",
                                relative,
                                "empty source files require an explicit package-marker exception",
                            )
                        )
                else:
                    if content.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
                        findings.append(
                            Finding("text_bom", relative, "tracked UTF-8 text must not use a BOM")
                        )
                    try:
                        content.decode("utf-8")
                    except UnicodeDecodeError as exc:
                        findings.append(
                            Finding(
                                "non_utf8_text",
                                relative,
                                f"text does not decode as UTF-8 at byte {exc.start}",
                            )
                        )
                    if b"\r" in content:
                        findings.append(
                            Finding(
                                "non_lf_line_ending",
                                relative,
                                "tracked text contains a CR byte",
                            )
                        )
                    if not content.endswith(b"\n"):
                        findings.append(
                            Finding(
                                "missing_final_newline",
                                relative,
                                "non-empty tracked text must end with LF",
                            )
                        )
                    trailing_lines = [
                        line_number
                        for line_number, line in enumerate(content.splitlines(), start=1)
                        if line.endswith((b" ", b"\t"))
                    ]
                    if trailing_lines:
                        preview = ",".join(str(line) for line in trailing_lines[:8])
                        suffix = "..." if len(trailing_lines) > 8 else ""
                        findings.append(
                            Finding(
                                "trailing_whitespace",
                                relative,
                                f"line(s) {preview}{suffix} end with space or tab",
                            )
                        )
        sizes[relative] = size

        if size > large_threshold and not any(
            matches(relative, pattern) for pattern in config.get("large_file_allow_globs", [])
        ):
            findings.append(
                Finding("unapproved_large_file", relative, f"{size} bytes exceeds {large_threshold}")
            )

        if size >= duplicate_threshold:
            digest = hashlib.sha256(content).hexdigest()
            duplicate_candidates.setdefault(digest, []).append(relative)

    for digest, duplicates in sorted(duplicate_candidates.items()):
        if len(duplicates) < 2:
            continue
        ordered = sorted(duplicates)
        duplicate_group = frozenset(ordered)
        if duplicate_group in allowed_duplicate_groups:
            observed_allowed_groups.add(duplicate_group)
            continue
        findings.append(
            Finding(
                "unapproved_duplicate_file",
                ordered[0],
                f"sha256={digest}; duplicates={','.join(ordered[1:])}",
            )
        )

    for allowed_group, reason in sorted(
        allowed_duplicate_groups.items(), key=lambda item: tuple(sorted(item[0]))
    ):
        ordered = sorted(allowed_group)
        present = allowed_group.intersection(path_set)
        if not present:
            continue
        if present != allowed_group:
            missing = sorted(allowed_group.difference(path_set))
            findings.append(
                Finding(
                    "incomplete_duplicate_allowance",
                    ordered[0],
                    f"missing={','.join(missing)}; reason={reason}",
                )
            )
        elif allowed_group not in observed_allowed_groups:
            findings.append(
                Finding(
                    "stale_duplicate_allowance",
                    ordered[0],
                    f"declared paths no longer have identical content; reason={reason}",
                )
            )

    total_bytes = sum(sizes.values())
    maximum = int(config["max_total_tracked_bytes"])
    if total_bytes > maximum:
        findings.append(
            Finding("repository_size", ".", f"{total_bytes} tracked bytes exceeds {maximum}")
        )
    return sorted(findings), total_bytes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()

    root = args.root.resolve()
    config = load_config(args.config.resolve())
    paths, modes, inventory = tracked_files(root)
    findings, total_bytes = scan(root, paths, modes, config)
    findings.extend(
        Finding(
            "tracked_ignored_file",
            relative,
            "tracked files must not depend on force-add to bypass .gitignore",
        )
        for relative in git_ignored_tracked_files(root)
    )
    findings.sort()
    if findings:
        for finding in findings:
            print(f"{finding.kind}: {finding.path}: {finding.detail}", file=sys.stderr)
        print(
            f"repository hygiene failed: {len(findings)} finding(s), "
            f"{len(paths)} files, {total_bytes} bytes from {inventory}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    print(
        f"ok: repository hygiene ({len(paths)} files, {total_bytes} bytes from {inventory})"
    )


if __name__ == "__main__":
    main()
