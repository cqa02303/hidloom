#!/usr/bin/env python3
"""Audit a local dotenv file without exposing its values."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
ASSIGNMENT_RE = re.compile(
    r"^[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*="
)
RETIRED_PREFIX = "C" + "QA_"
CANONICAL_PREFIX = "HIDLOOM_"
REWRITE_CONFIRMATION = "REWRITE-LOCAL-ENV-KEYS"


@dataclass(frozen=True, order=True)
class Finding:
    kind: str
    path: str
    line: int
    key: str = ""


@dataclass(frozen=True)
class Assignment:
    line: int
    key: str
    start: int
    end: int


@dataclass(frozen=True)
class Inspection:
    relative: str
    findings: tuple[Finding, ...]
    assignments: tuple[Assignment, ...]
    text: str | None
    mode: int | None
    signature: tuple[int, int, int, int, int] | None


def display_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def canonical_key(key: str) -> str:
    if key.upper().startswith(RETIRED_PREFIX):
        return CANONICAL_PREFIX + key[len(RETIRED_PREFIX) :]
    return key


def parse_environment(relative: str, text: str) -> tuple[list[Finding], list[Assignment]]:
    findings: list[Finding] = []
    keys: dict[str, int] = {}
    assignments: list[Assignment] = []
    for line_number, line in enumerate(text.splitlines(keepends=True), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = ASSIGNMENT_RE.match(line)
        if match is None:
            findings.append(Finding("invalid_environment_assignment", relative, line_number))
            continue
        key = match.group(1)
        assignments.append(
            Assignment(line_number, key, match.start(1), match.end(1))
        )
        if key in keys:
            findings.append(Finding("duplicate_environment_name", relative, line_number, key))
        else:
            keys[key] = line_number
        if key.upper().startswith(RETIRED_PREFIX):
            findings.append(Finding("retired_environment_name", relative, line_number, key))
    return sorted(findings), assignments


def file_signature(file_stat: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_size,
        file_stat.st_mtime_ns,
        file_stat.st_mode,
    )


def inspect(root: Path, path: Path) -> Inspection:
    relative = display_path(root, path)
    if path.is_symlink():
        return Inspection(
            relative,
            (Finding("symlink_environment_file", relative, 0),),
            (),
            None,
            None,
            None,
        )
    if not path.exists():
        return Inspection(relative, (), (), None, None, None)
    try:
        file_stat = path.stat()
    except OSError:
        return Inspection(
            relative,
            (Finding("unreadable_environment_file", relative, 0),),
            (),
            None,
            None,
            None,
        )
    if not stat.S_ISREG(file_stat.st_mode):
        return Inspection(
            relative,
            (Finding("non_regular_environment_file", relative, 0),),
            (),
            None,
            None,
            None,
        )

    findings: list[Finding] = []
    if path.name == ".env" and file_stat.st_mode & 0o077:
        findings.append(Finding("insecure_environment_mode", relative, 0))
    try:
        raw = path.read_bytes()
    except OSError:
        findings.append(Finding("unreadable_environment_file", relative, 0))
        return Inspection(relative, tuple(sorted(findings)), (), None, None, None)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        findings.append(Finding("non_utf8_environment_file", relative, 0))
        return Inspection(relative, tuple(sorted(findings)), (), None, None, None)

    parsed_findings, assignments = parse_environment(relative, text)
    findings.extend(parsed_findings)
    return Inspection(
        relative,
        tuple(sorted(findings)),
        tuple(assignments),
        text,
        stat.S_IMODE(file_stat.st_mode),
        file_signature(file_stat),
    )


def audit(root: Path, path: Path) -> tuple[list[Finding], int]:
    inspection = inspect(root, path)
    return list(inspection.findings), len(inspection.assignments)


def migration_plan(
    inspection: Inspection,
) -> tuple[list[Finding], list[tuple[str, str]], str | None]:
    blocking = [
        finding
        for finding in inspection.findings
        if finding.kind != "retired_environment_name"
    ]
    if blocking or inspection.text is None:
        return sorted(blocking), [], inspection.text

    existing = {assignment.key for assignment in inspection.assignments}
    target_sources: dict[str, str] = {}
    mappings: list[tuple[str, str]] = []
    collisions: list[Finding] = []
    replacements: dict[int, str] = {}
    for assignment in inspection.assignments:
        replacement = canonical_key(assignment.key)
        if replacement == assignment.key:
            continue
        prior_source = target_sources.get(replacement)
        if replacement in existing or prior_source is not None:
            collisions.append(
                Finding(
                    "environment_rewrite_collision",
                    inspection.relative,
                    assignment.line,
                    assignment.key,
                )
            )
            continue
        target_sources[replacement] = assignment.key
        mappings.append((assignment.key, replacement))
        replacements[assignment.line] = replacement
    if collisions:
        return sorted(collisions), [], inspection.text

    lines = inspection.text.splitlines(keepends=True)
    for assignment in inspection.assignments:
        replacement = replacements.get(assignment.line)
        if replacement is None:
            continue
        line = lines[assignment.line - 1]
        lines[assignment.line - 1] = (
            line[: assignment.start] + replacement + line[assignment.end :]
        )
    rendered = "".join(lines)
    rendered_findings, _ = parse_environment(inspection.relative, rendered)
    if rendered_findings:
        return sorted(rendered_findings), [], inspection.text
    return [], mappings, rendered


def atomic_rewrite(path: Path, inspection: Inspection, rendered: str) -> None:
    if inspection.mode is None or inspection.signature is None:
        raise RuntimeError("environment file is not rewriteable")
    current = path.stat()
    if current.st_uid != os.geteuid():
        raise RuntimeError("environment file is not owned by the current user")
    if file_signature(current) != inspection.signature:
        raise RuntimeError("environment file changed after inspection")

    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name.lstrip('.')}.hidloom-key-rewrite.",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(file_descriptor, inspection.mode)
        with os.fdopen(file_descriptor, "wb") as stream:
            file_descriptor = -1
            stream.write(rendered.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_symlink() or file_signature(path.stat()) != inspection.signature:
            raise RuntimeError("environment file changed before atomic replace")
        os.replace(temporary, path)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_descriptor = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        temporary.unlink(missing_ok=True)


def print_findings(findings: list[Finding] | tuple[Finding, ...]) -> None:
    for finding in findings:
        location = finding.path
        if finding.line:
            location += f":{finding.line}"
        detail = ""
        if finding.key:
            detail = f" key={finding.key}"
            replacement = canonical_key(finding.key)
            if replacement != finding.key:
                detail += f" replacement={replacement}"
        print(f"{finding.kind}: {location}{detail}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument(
        "--rewrite-retired-keys",
        action="store_true",
        help="plan a key-only rewrite without changing values or the file",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="atomically apply the planned key-only rewrite without a backup",
    )
    parser.add_argument(
        "--confirm",
        metavar="TOKEN",
        help=f"required with --apply: {REWRITE_CONFIRMATION}",
    )
    args = parser.parse_args()

    if args.apply and not args.rewrite_retired_keys:
        parser.error("--apply requires --rewrite-retired-keys")
    if args.confirm is not None and not args.apply:
        parser.error("--confirm requires --apply")

    root = args.root.resolve()
    path = args.env_file or root / ".env"
    if not path.is_absolute():
        path = root / path
    inspection = inspect(root, path)

    if args.rewrite_retired_keys:
        rewrite_findings, mappings, rendered = migration_plan(inspection)
        if rewrite_findings:
            print_findings(rewrite_findings)
            print(
                f"local environment key rewrite refused: {len(rewrite_findings)} finding(s); "
                "values were not printed and the file was unchanged",
                file=sys.stderr,
            )
            raise SystemExit(1)
        if not mappings:
            print("ok: local environment key rewrite (no retired keys; file unchanged)")
            return
        if not args.apply:
            for key, replacement in mappings:
                print(f"rewrite: key={key} replacement={replacement}")
            print(
                f"plan: {len(mappings)} key(s) would be rewritten; "
                "values were not printed and the file was unchanged"
            )
            return
        if args.confirm != REWRITE_CONFIRMATION:
            print(
                f"local environment key rewrite refused: pass --confirm {REWRITE_CONFIRMATION}; "
                "values were not printed and the file was unchanged",
                file=sys.stderr,
            )
            raise SystemExit(1)
        assert rendered is not None
        try:
            atomic_rewrite(path, inspection, rendered)
        except (OSError, RuntimeError) as error:
            print(
                f"local environment key rewrite failed: {error}; "
                "values were not printed",
                file=sys.stderr,
            )
            raise SystemExit(1) from error
        rewritten = inspect(root, path)
        if rewritten.findings:
            print_findings(rewritten.findings)
            print("local environment key rewrite verification failed", file=sys.stderr)
            raise SystemExit(1)
        print(
            f"ok: rewrote {len(mappings)} local environment key(s) atomically; "
            "values were not printed and no backup was created"
        )
        return

    if inspection.findings:
        print_findings(inspection.findings)
        print(
            f"local environment hygiene failed: {len(inspection.findings)} finding(s); "
            "values were not printed",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if path.exists():
        print(
            f"ok: local environment hygiene ({len(inspection.assignments)} assignments, "
            f"mode={inspection.mode:04o}; values were not printed)"
        )
    else:
        print("ok: local environment hygiene (no local environment file)")


if __name__ == "__main__":
    main()
