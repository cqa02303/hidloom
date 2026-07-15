#!/usr/bin/env python3
"""Collect a small performance baseline snapshot for HIDloom."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import platform
import shlex
import socket
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_UNITS = (
    "logicd",
    "ledd",
    "httpd",
    "viald",
    "hidloom-hidd",
    "i2cd",
    "btd",
    "matrixd",
    "spid",
)

PROCESS_NAMES = (
    "python3",
    "logicd",
    "ledd",
    "httpd",
    "viald",
    "hidloom-hidd",
    "btd",
    "spid",
    "i2cd",
    "matrixd",
)


@dataclass(frozen=True)
class CommandResult:
    title: str
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    elapsed_sec: float


def ps_command() -> list[str]:
    cmd = ["ps", "-o", "pid,comm,rss,pcpu,args"]
    for name in PROCESS_NAMES:
        cmd.extend(["-C", name])
    return cmd


def run_command(title: str, command: list[str], *, timeout: float) -> CommandResult:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return CommandResult(
            title=title,
            command=command,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            elapsed_sec=time.monotonic() - started,
        )
    except FileNotFoundError as exc:
        return CommandResult(
            title=title,
            command=command,
            returncode=127,
            stdout="",
            stderr=str(exc),
            elapsed_sec=time.monotonic() - started,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return CommandResult(
            title=title,
            command=command,
            returncode=124,
            stdout=stdout,
            stderr=stderr + f"\nTIMEOUT after {timeout:.1f}s",
            elapsed_sec=time.monotonic() - started,
        )


def collect_results(*, ps_samples: int, ps_interval: float, journal_lines: int, run_validation: bool) -> list[CommandResult]:
    units = list(DEFAULT_UNITS)
    results: list[CommandResult] = [
        run_command("git revision", ["git", "rev-parse", "--short", "HEAD"], timeout=5.0),
        run_command("git status", ["git", "status", "--short"], timeout=5.0),
        run_command("failed services", ["systemctl", "--failed", "--no-pager"], timeout=10.0),
        run_command("service status", ["systemctl", "status", *units, "--no-pager"], timeout=20.0),
        run_command("recent daemon logs", ["journalctl", *sum((["-u", unit] for unit in units), []), "-n", str(journal_lines), "--no-pager"], timeout=20.0),
    ]
    if run_validation:
        results.append(
            run_command(
                "validation suite",
                ["python3", "script/test_validation_suite.py"],
                timeout=180.0,
            )
        )
    for index in range(ps_samples):
        if index > 0:
            time.sleep(ps_interval)
        results.append(run_command(f"process snapshot {index + 1}", ps_command(), timeout=5.0))
    return results


def fenced(text: str) -> str:
    return text.rstrip() if text.strip() else "(no output)"


def render_report(results: list[CommandResult], *, ps_samples: int, ps_interval: float, run_validation: bool) -> str:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        "# Performance Baseline",
        "",
        f"- collected_at: `{now}`",
        f"- host: `{socket.gethostname()}`",
        f"- platform: `{platform.platform()}`",
        f"- ps_samples: `{ps_samples}`",
        f"- ps_interval_sec: `{ps_interval}`",
        f"- validation: `{'enabled' if run_validation else 'skipped'}`",
        "",
        "## Results",
        "",
    ]
    for result in results:
        command_text = " ".join(shlex.quote(part) for part in result.command)
        lines.extend(
            [
                f"### {result.title}",
                "",
                f"- command: `{command_text}`",
                f"- exit: `{result.returncode}`",
                f"- elapsed_sec: `{result.elapsed_sec:.3f}`",
                "",
                "stdout:",
                "",
                "```text",
                fenced(result.stdout),
                "```",
                "",
                "stderr:",
                "",
                "```text",
                fenced(result.stderr),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write Markdown report to this path")
    parser.add_argument("--ps-samples", type=int, default=3, help="number of process snapshots")
    parser.add_argument("--ps-interval", type=float, default=2.0, help="seconds between process snapshots")
    parser.add_argument("--journal-lines", type=int, default=200, help="journal lines to collect")
    parser.add_argument("--run-validation", action="store_true", help="include script/test_validation_suite.py")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.ps_samples < 1:
        raise SystemExit("--ps-samples must be >= 1")
    if args.ps_interval < 0:
        raise SystemExit("--ps-interval must be >= 0")
    results = collect_results(
        ps_samples=args.ps_samples,
        ps_interval=args.ps_interval,
        journal_lines=args.journal_lines,
        run_validation=args.run_validation,
    )
    report = render_report(
        results,
        ps_samples=args.ps_samples,
        ps_interval=args.ps_interval,
        run_validation=args.run_validation,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report + "\n", encoding="utf-8")
        print(args.output)
    else:
        print(report)


if __name__ == "__main__":
    main()
