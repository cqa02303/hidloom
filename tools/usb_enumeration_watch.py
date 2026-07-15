#!/usr/bin/env python3
"""Watch host-side USB enumeration events for fast-boot experiments."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import platform
import queue
import shlex
import socket
import subprocess
import threading
import time


@dataclass(frozen=True)
class CommandResult:
    title: str
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    elapsed_sec: float


def run_command(title: str, command: list[str], *, timeout: float) -> CommandResult:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return CommandResult(title, command, proc.returncode, proc.stdout, proc.stderr, time.monotonic() - started)
    except FileNotFoundError as exc:
        return CommandResult(title, command, 127, "", str(exc), time.monotonic() - started)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return CommandResult(title, command, 124, stdout, stderr + f"\nTIMEOUT after {timeout:.1f}s", time.monotonic() - started)


def watch_process(title: str, command: list[str], *, duration: float, shutdown_grace: float = 1.0) -> CommandResult:
    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )
    except FileNotFoundError as exc:
        return CommandResult(title, command, 127, "", str(exc), time.monotonic() - started)

    events: queue.Queue[tuple[str, float, str]] = queue.Queue()

    def read_stream(name: str, stream) -> None:  # type: ignore[no-untyped-def]
        try:
            for line in stream:
                events.put((name, time.monotonic() - started, line.rstrip("\n")))
        finally:
            try:
                stream.close()
            except Exception:
                pass

    threads = [
        threading.Thread(target=read_stream, args=("stdout", proc.stdout), daemon=True),
        threading.Thread(target=read_stream, args=("stderr", proc.stderr), daemon=True),
    ]
    for thread in threads:
        thread.start()

    try:
        proc.wait(timeout=duration)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=shutdown_grace)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    for thread in threads:
        thread.join(timeout=shutdown_grace)

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    while not events.empty():
        name, elapsed, line = events.get()
        target = stdout_lines if name == "stdout" else stderr_lines
        target.append(f"[+{elapsed:.3f}s] {line}")
    returncode = proc.returncode if proc.returncode is not None else 0
    if returncode < 0:
        returncode = 0
    return CommandResult(
        title,
        command,
        returncode,
        "\n".join(stdout_lines) + ("\n" if stdout_lines else ""),
        "\n".join(stderr_lines) + ("\n" if stderr_lines else ""),
        time.monotonic() - started,
    )


def collect_results(*, duration: float, include_kernel_log: bool) -> list[CommandResult]:
    results = [
        run_command("pre lsusb", ["lsusb"], timeout=5.0),
        watch_process(
            "udev usb/hid monitor",
            [
                "udevadm",
                "monitor",
                "--udev",
                "--kernel",
                "--property",
                "--subsystem-match=usb",
                "--subsystem-match=hidraw",
            ],
            duration=duration,
        ),
        run_command("post lsusb", ["lsusb"], timeout=5.0),
    ]
    if include_kernel_log:
        results.append(run_command("recent kernel usb log", ["dmesg", "--ctime", "--color=never"], timeout=8.0))
    return results


def fenced(text: str) -> str:
    return text.rstrip() if text.strip() else "(no output)"


def render_report(results: list[CommandResult], *, duration: float, include_kernel_log: bool) -> str:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        "# USB Enumeration Watch",
        "",
        f"- collected_at: `{now}`",
        f"- host: `{socket.gethostname()}`",
        f"- platform: `{platform.platform()}`",
        f"- duration_sec: `{duration}`",
        f"- kernel_log: `{'enabled' if include_kernel_log else 'skipped'}`",
        "",
        "## Operator Steps",
        "",
        "1. Start this watcher on the USB host.",
        "2. Power or reconnect the Raspberry Pi target.",
        "3. Stop touching the host keyboard until the watch duration has elapsed.",
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
    parser.add_argument("--duration", type=float, default=30.0, help="seconds to watch udev events")
    parser.add_argument("--output", type=Path, help="write Markdown report to this path")
    parser.add_argument("--include-kernel-log", action="store_true", help="append dmesg output if permitted")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.duration <= 0:
        raise SystemExit("--duration must be > 0")
    results = collect_results(duration=args.duration, include_kernel_log=args.include_kernel_log)
    report = render_report(results, duration=args.duration, include_kernel_log=args.include_kernel_log)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report + "\n", encoding="utf-8")
        print(args.output)
    else:
        print(report)


if __name__ == "__main__":
    main()
