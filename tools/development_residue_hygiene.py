#!/usr/bin/env python3
"""Reject tracked merge residue, debug hooks, and mechanical duplicate code."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from dataclasses import dataclass
import io
from pathlib import Path, PurePosixPath
import re
import sys
import tokenize

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from repository_hygiene import tracked_files  # noqa: E402


CONFLICT_MARKER_RE = re.compile(r"(?:<<<<<<<|>>>>>>>)(?: .*)?")
ENVIRONMENT_NAME_RE = re.compile(r"[A-Z][A-Z0-9_]*")
SHELL_SELF_FALLBACK_RE = re.compile(
    r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r":-\$\{(?P=name)(?::-[^}]*)?\}\}"
)
SHELL_ASSIGNMENT_RE = re.compile(r"(?:^|[ \t])([A-Za-z_][A-Za-z0-9_]*)=")
SHELL_XTRACE_RE = re.compile(
    r"^set\s+(?:-[A-Za-z]*x[A-Za-z]*(?:\s|$)|-o\s+xtrace(?:\s|$))"
)
JAVASCRIPT_DEBUG_RE = re.compile(r"\bconsole\.(?:log|debug|trace)\s*\(")
JAVASCRIPT_DEBUGGER_RE = re.compile(r"\bdebugger\s*;")
RUST_PLACEHOLDER_RE = re.compile(r"\b(?:dbg|todo|unimplemented)!\s*\(")
DEVELOPMENT_MARKER_RE = re.compile(r"\b(?:TODO|FIXME|HACK|XXX|WIP|TBD)\b", re.IGNORECASE)
C_STYLE_COMMENT_SUFFIXES = frozenset(
    {".c", ".cc", ".cpp", ".css", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".js", ".mjs", ".rs"}
)
HASH_COMMENT_SUFFIXES = frozenset(
    {".cfg", ".conf", ".ini", ".mk", ".service", ".socket", ".target", ".timer", ".toml", ".yaml", ".yml"}
)
NOT_LITERAL = object()


@dataclass(frozen=True, order=True)
class Finding:
    kind: str
    path: str
    detail: str


def line_detail(line_number: int, detail: str) -> str:
    return f"line {line_number}: {detail}"


def ast_identity(node: ast.AST) -> str:
    return ast.dump(node, include_attributes=False)


def literal_key(node: ast.AST) -> object:
    try:
        value = ast.literal_eval(node)
        hash(value)
    except (TypeError, ValueError):
        return NOT_LITERAL
    return value


def is_environment_name(value: str) -> bool:
    if not ENVIRONMENT_NAME_RE.fullmatch(value) or value.startswith("KC_"):
        return False
    return "_" in value or value in {
        "DISPLAY",
        "HOME",
        "LANG",
        "PATH",
        "PYTHONPATH",
        "SHELL",
        "TERM",
        "USER",
    }


def is_test_source(relative: str) -> bool:
    path = PurePosixPath(relative)
    return (
        path.name.startswith("test_")
        or path.stem.endswith("_test")
        or "test" in path.parts
        or "tests" in path.parts
    )


def exception_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def development_marker_findings(relative: str, comments: str) -> list[Finding]:
    if is_test_source(relative):
        return []
    return regex_findings(
        relative,
        comments,
        DEVELOPMENT_MARKER_RE,
        "development_marker_comment",
    )


def python_comment_text(text: str) -> str:
    comments = ["\n" if character == "\n" else " " for character in text]
    line_offsets = [0]
    line_offsets.extend(match.end() for match in re.finditer("\n", text))
    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        for token in tokens:
            if token.type != tokenize.COMMENT:
                continue
            line_number, column = token.start
            offset = line_offsets[line_number - 1] + column
            comments[offset : offset + len(token.string)] = token.string
    except (IndentationError, tokenize.TokenError):
        return "".join(comments)
    return "".join(comments)


def python_findings(relative: str, text: str) -> list[Finding]:
    try:
        tree = ast.parse(text, filename=relative)
    except SyntaxError as exc:
        return [
            Finding(
                "python_parse_error",
                relative,
                line_detail(exc.lineno or 1, str(exc.msg)),
            )
        ]

    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not is_test_source(relative) and isinstance(node, ast.ClassDef):
            if "notimplemented" in node.name.lower():
                findings.append(
                    Finding(
                        "python_unfinished_symbol",
                        relative,
                        line_detail(node.lineno, node.name),
                    )
                )

        if not is_test_source(relative) and isinstance(node, ast.Raise):
            name = exception_name(node.exc)
            if "notimplemented" in name.lower():
                findings.append(
                    Finding(
                        "python_not_implemented_raise",
                        relative,
                        line_detail(node.lineno, name),
                    )
                )

        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            seen_operands: dict[str, int] = {}
            for operand in node.values:
                identity = ast_identity(operand)
                if identity in seen_operands:
                    first_line = seen_operands[identity]
                    findings.append(
                        Finding(
                            "duplicate_or_operand",
                            relative,
                            line_detail(
                                operand.lineno,
                                f"duplicates operand from line {first_line}",
                            ),
                        )
                    )
                else:
                    seen_operands[identity] = operand.lineno

        if isinstance(node, ast.Dict):
            seen_keys: dict[object, int] = {}
            for key_node in node.keys:
                if key_node is None:
                    continue
                key = literal_key(key_node)
                if key is NOT_LITERAL:
                    continue
                if key in seen_keys:
                    first_line = seen_keys[key]
                    findings.append(
                        Finding(
                            "duplicate_dict_key",
                            relative,
                            line_detail(
                                key_node.lineno,
                                f"literal key {key!r} duplicates line {first_line}",
                            ),
                        )
                    )
                else:
                    seen_keys[key] = key_node.lineno

        if not is_test_source(relative) and isinstance(
            node, (ast.List, ast.Set, ast.Tuple)
        ):
            seen_names: dict[str, int] = {}
            for element in node.elts:
                if not (
                    isinstance(element, ast.Constant)
                    and isinstance(element.value, str)
                    and is_environment_name(element.value)
                ):
                    continue
                if element.value in seen_names:
                    first_line = seen_names[element.value]
                    findings.append(
                        Finding(
                            "duplicate_environment_name",
                            relative,
                            line_detail(
                                element.lineno,
                                f"{element.value} duplicates line {first_line}",
                            ),
                        )
                    )
                else:
                    seen_names[element.value] = element.lineno

        if isinstance(node, ast.Call):
            function = node.func
            hook = None
            if isinstance(function, ast.Name) and function.id == "breakpoint":
                hook = "breakpoint"
            elif (
                isinstance(function, ast.Attribute)
                and function.attr in {"breakpoint", "set_trace"}
                and isinstance(function.value, ast.Name)
                and function.value.id in {"builtins", "ipdb", "pdb"}
            ):
                hook = f"{function.value.id}.{function.attr}"
            if hook is not None:
                findings.append(
                    Finding(
                        "python_debug_hook",
                        relative,
                        line_detail(node.lineno, hook),
                    )
                )

        if is_test_source(relative):
            continue
        for field in ("body", "orelse", "finalbody"):
            statements = getattr(node, field, None)
            if not isinstance(statements, list):
                continue
            for previous, current in zip(statements, statements[1:]):
                if not isinstance(previous, ast.stmt) or not isinstance(current, ast.stmt):
                    continue
                if ast_identity(previous) != ast_identity(current):
                    continue
                findings.append(
                    Finding(
                        "duplicate_adjacent_statement",
                        relative,
                        line_detail(
                            current.lineno,
                            f"duplicates {type(current).__name__} from line {previous.lineno}",
                        ),
                    )
                )
    return findings


def mask_c_style_literals(text: str, *, quotes: frozenset[str]) -> str:
    """Mask comments and quoted literals while preserving offsets and newlines."""
    masked = list(text)
    index = 0
    state = "code"
    quote = ""
    while index < len(text):
        character = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if state == "code":
            if character == "/" and following == "/":
                masked[index] = masked[index + 1] = " "
                index += 2
                state = "line_comment"
                continue
            if character == "/" and following == "*":
                masked[index] = masked[index + 1] = " "
                index += 2
                state = "block_comment"
                continue
            if character in quotes:
                quote = character
                masked[index] = " "
                index += 1
                state = "string"
                continue
        elif state == "line_comment":
            if character == "\n":
                state = "code"
            else:
                masked[index] = " "
            index += 1
            continue
        elif state == "block_comment":
            if character == "*" and following == "/":
                masked[index] = masked[index + 1] = " "
                index += 2
                state = "code"
                continue
            if character != "\n":
                masked[index] = " "
            index += 1
            continue
        else:
            if character == "\\":
                masked[index] = " "
                if index + 1 < len(text):
                    if text[index + 1] != "\n":
                        masked[index + 1] = " "
                    index += 2
                else:
                    index += 1
                continue
            if character == quote:
                masked[index] = " "
                index += 1
                state = "code"
                continue
            if character != "\n":
                masked[index] = " "
            index += 1
            continue
        index += 1
    return "".join(masked)


def c_style_comment_text(text: str, *, quotes: frozenset[str]) -> str:
    """Return only C-style comments while preserving offsets and newlines."""
    comments = ["\n" if character == "\n" else " " for character in text]
    index = 0
    state = "code"
    quote = ""
    block_depth = 0
    while index < len(text):
        character = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if state == "code":
            if character == "/" and following == "/":
                comments[index] = comments[index + 1] = "/"
                index += 2
                state = "line_comment"
                continue
            if character == "/" and following == "*":
                comments[index] = "/"
                comments[index + 1] = "*"
                index += 2
                state = "block_comment"
                block_depth = 1
                continue
            if character in quotes:
                quote = character
                index += 1
                state = "string"
                continue
        elif state == "line_comment":
            if character == "\n":
                state = "code"
            else:
                comments[index] = character
            index += 1
            continue
        elif state == "block_comment":
            if character == "/" and following == "*":
                comments[index] = "/"
                comments[index + 1] = "*"
                block_depth += 1
                index += 2
                continue
            if character == "*" and following == "/":
                comments[index] = "*"
                comments[index + 1] = "/"
                block_depth -= 1
                index += 2
                if block_depth == 0:
                    state = "code"
                continue
            if character != "\n":
                comments[index] = character
            index += 1
            continue
        else:
            if character == "\\":
                index += 2
                continue
            if character == quote:
                index += 1
                state = "code"
                continue
            index += 1
            continue
        index += 1
    return "".join(comments)


def hash_comment_text(text: str) -> str:
    """Return shell/config hash comments while preserving offsets and newlines."""
    comments = ["\n" if character == "\n" else " " for character in text]
    index = 0
    state = "code"
    while index < len(text):
        character = text[index]
        if state == "comment":
            if character == "\n":
                state = "code"
            else:
                comments[index] = character
            index += 1
            continue
        if state == "single_quote":
            if character == "'":
                state = "code"
            index += 1
            continue
        if state == "double_quote":
            if character == "\\":
                index += 2
                continue
            if character == '"':
                state = "code"
            index += 1
            continue
        if character == "\\":
            index += 2
            continue
        if character == "'":
            state = "single_quote"
            index += 1
            continue
        if character == '"':
            state = "double_quote"
            index += 1
            continue
        if character == "#" and (
            index == 0 or text[index - 1].isspace() or text[index - 1] in ";|&()"
        ):
            comments[index] = "#"
            state = "comment"
        index += 1
    return "".join(comments)


def regex_findings(
    relative: str,
    text: str,
    pattern: re.Pattern[str],
    kind: str,
) -> list[Finding]:
    findings = []
    for match in pattern.finditer(text):
        line_number = text.count("\n", 0, match.start()) + 1
        findings.append(Finding(kind, relative, line_detail(line_number, match.group(0))))
    return findings


def shell_findings(relative: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if match := SHELL_SELF_FALLBACK_RE.search(line):
            findings.append(
                Finding(
                    "shell_self_fallback",
                    relative,
                    line_detail(line_number, match.group("name")),
                )
            )
        if SHELL_XTRACE_RE.match(line.strip()):
            findings.append(
                Finding("shell_xtrace", relative, line_detail(line_number, line.strip()))
            )
        assignments = [
            name
            for name in SHELL_ASSIGNMENT_RE.findall(line)
            if ENVIRONMENT_NAME_RE.fullmatch(name) and is_environment_name(name)
        ]
        for name in sorted({name for name in assignments if assignments.count(name) > 1}):
            findings.append(
                Finding(
                    "duplicate_shell_environment",
                    relative,
                    line_detail(line_number, name),
                )
            )
    return findings


def is_shell_source(path: Path, text: str) -> bool:
    return path.suffix.lower() == ".sh" or text.startswith(
        ("#!/bin/sh", "#!/usr/bin/env sh", "#!/bin/bash", "#!/usr/bin/env bash")
    )


def scan(root: Path, paths: list[str]) -> tuple[list[Finding], Counter[str]]:
    findings: list[Finding] = []
    counts: Counter[str] = Counter()
    for relative in paths:
        path = root / relative
        if path.is_symlink() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        counts["text"] += 1
        for line_number, line in enumerate(text.splitlines(), start=1):
            if line == "=======" or CONFLICT_MARKER_RE.fullmatch(line):
                findings.append(
                    Finding(
                        "merge_conflict_marker",
                        relative,
                        line_detail(line_number, line),
                    )
                )

        suffix = path.suffix.lower()
        if suffix == ".py":
            counts["python"] += 1
            findings.extend(python_findings(relative, text))
            counts["comment_source"] += 1
            findings.extend(
                development_marker_findings(relative, python_comment_text(text))
            )
        shell_source = is_shell_source(path, text)
        if shell_source:
            counts["shell"] += 1
            findings.extend(shell_findings(relative, text))
            counts["comment_source"] += 1
            findings.extend(
                development_marker_findings(relative, hash_comment_text(text))
            )
        elif suffix in HASH_COMMENT_SUFFIXES or path.name in {"GNUmakefile", "Makefile"}:
            counts["comment_source"] += 1
            findings.extend(
                development_marker_findings(relative, hash_comment_text(text))
            )
        if suffix in C_STYLE_COMMENT_SUFFIXES:
            counts["comment_source"] += 1
            if suffix in {".js", ".mjs"}:
                quotes = frozenset({"'", '"', "`"})
            elif suffix == ".rs":
                quotes = frozenset({'"'})
            else:
                quotes = frozenset({"'", '"'})
            findings.extend(
                development_marker_findings(
                    relative,
                    c_style_comment_text(text, quotes=quotes),
                )
            )
        if suffix == ".js":
            counts["javascript"] += 1
            code = mask_c_style_literals(text, quotes=frozenset({"'", '"', "`"}))
            findings.extend(
                regex_findings(relative, code, JAVASCRIPT_DEBUG_RE, "javascript_debug_output")
            )
            findings.extend(
                regex_findings(relative, code, JAVASCRIPT_DEBUGGER_RE, "javascript_debugger")
            )
        if suffix == ".rs":
            counts["rust"] += 1
            code = mask_c_style_literals(text, quotes=frozenset({'"'}))
            findings.extend(
                regex_findings(relative, code, RUST_PLACEHOLDER_RE, "rust_placeholder_macro")
            )
    return sorted(set(findings)), counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    root = args.root.resolve()
    paths, _modes, inventory = tracked_files(root)
    findings, counts = scan(root, paths)
    if findings:
        for finding in findings:
            print(f"{finding.kind}: {finding.path}: {finding.detail}", file=sys.stderr)
        print(
            f"development residue hygiene failed: {len(findings)} finding(s), "
            f"{len(paths)} files from {inventory}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    summary = ", ".join(f"{name}={counts[name]}" for name in sorted(counts))
    print(f"ok: development residue hygiene ({len(paths)} files from {inventory}; {summary})")


if __name__ == "__main__":
    main()
