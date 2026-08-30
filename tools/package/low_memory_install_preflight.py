#!/usr/bin/env python3
"""Read-only safety gate for package installation on a low-memory device.

The helper intentionally does not install packages, acquire package-manager
locks, stop services, or change swap configuration.  It only snapshots the
memory, dpkg, process, and lock state and emits one JSON result.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


SCHEMA = "hidloom.low-memory-install-preflight.v2"
MIB = 1024 * 1024
DEFAULT_MIN_MEM_AVAILABLE_MIB = 128
DEFAULT_MIN_SWAP_FREE_MIB = 256
DEFAULT_MIN_SWAP_FREE_PERCENT = 75.0
DEFAULT_STEADY_MIN_MEM_AVAILABLE_MIB = 96
DEFAULT_STEADY_MIN_SWAP_FREE_PERCENT = 60.0
DEFAULT_STEADY_MIN_COMBINED_HEADROOM_MIB = 384
DEFAULT_LOCK_PATHS = (
    "/var/lib/dpkg/lock-frontend",
    "/var/lib/dpkg/lock",
    "/var/cache/apt/archives/lock",
    "/var/lib/apt/lists/lock",
)
PACKAGE_PROCESS_NAMES = frozenset({"apt", "apt-get", "dpkg", "mandb"})
MAX_TEXT_BYTES = 1024 * 1024
MAX_PROC_FIELD_BYTES = 64 * 1024
LOCK_RE = re.compile(
    r"^\s*(?P<id>\d+):\s+(?P<blocked>->\s+)?"
    r"(?P<kind>\S+)\s+(?P<scope>\S+)\s+(?P<access>\S+)\s+"
    r"(?P<pid>-?\d+)\s+(?P<major>[0-9a-fA-F]+):"
    r"(?P<minor>[0-9a-fA-F]+):(?P<inode>\d+)\s+"
)


def bounded_read_text(path: Path, limit: int = MAX_TEXT_BYTES) -> str:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        value = handle.read(limit + 1)
    if len(value) > limit:
        raise ValueError(f"input exceeds {limit} characters: {path}")
    return value


def parse_meminfo(raw: str) -> dict[str, int]:
    wanted = {"MemAvailable", "SwapTotal", "SwapFree"}
    values: dict[str, int] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        name, payload = line.split(":", 1)
        if name not in wanted:
            continue
        if name in values:
            raise ValueError(f"duplicate {name} entry")
        fields = payload.split()
        if len(fields) != 2 or fields[1] != "kB":
            raise ValueError(f"invalid {name} entry: {line!r}")
        try:
            kibibytes = int(fields[0], 10)
        except ValueError as exc:
            raise ValueError(f"invalid {name} value: {fields[0]!r}") from exc
        if kibibytes < 0:
            raise ValueError(f"negative {name} value")
        values[name] = kibibytes * 1024
    missing = sorted(wanted - values.keys())
    if missing:
        raise ValueError("missing meminfo entries: " + ", ".join(missing))
    if values["SwapFree"] > values["SwapTotal"]:
        raise ValueError("SwapFree exceeds SwapTotal")
    return values


def memory_check(
    path: Path,
    min_mem_available_mib: int,
    min_swap_free_mib: int,
    min_swap_free_percent: float,
    steady_min_mem_available_mib: int,
    steady_min_swap_free_percent: float,
    steady_min_combined_headroom_mib: int,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "source": str(path),
        "minimum_mem_available_bytes": min_mem_available_mib * MIB,
        "minimum_swap_free_mib": min_swap_free_mib,
        "minimum_swap_free_bytes": min_swap_free_mib * MIB,
        "minimum_swap_free_percent": min_swap_free_percent,
        "steady_minimum_mem_available_bytes": steady_min_mem_available_mib * MIB,
        "steady_minimum_swap_free_percent": steady_min_swap_free_percent,
        "steady_minimum_combined_headroom_bytes": (
            steady_min_combined_headroom_mib * MIB
        ),
    }
    try:
        values = parse_meminfo(bounded_read_text(path))
    except (OSError, ValueError) as exc:
        result["error"] = str(exc)
        return result

    mem_available = values["MemAvailable"]
    swap_total = values["SwapTotal"]
    swap_free = values["SwapFree"]
    minimum_swap_free_by_percent = math.ceil(
        swap_total * min_swap_free_percent / 100.0
    )
    steady_minimum_swap_free_by_percent = math.ceil(
        swap_total * steady_min_swap_free_percent / 100.0
    )
    combined_headroom = mem_available + swap_free
    mem_ok = mem_available >= min_mem_available_mib * MIB
    swap_free_mib_ok = swap_free >= min_swap_free_mib * MIB
    swap_free_percent_ok = swap_free >= minimum_swap_free_by_percent
    swap_ok = swap_free_mib_ok and swap_free_percent_ok
    strict_ok = mem_ok and swap_ok
    steady_mem_ok = mem_available >= steady_min_mem_available_mib * MIB
    steady_swap_free_percent_ok = swap_free >= steady_minimum_swap_free_by_percent
    steady_combined_headroom_ok = (
        combined_headroom >= steady_min_combined_headroom_mib * MIB
    )
    steady_state_ok = (
        steady_mem_ok
        and swap_free_mib_ok
        and steady_swap_free_percent_ok
        and steady_combined_headroom_ok
    )
    admission_policy = (
        "strict"
        if strict_ok
        else "steady_state_headroom"
        if steady_state_ok
        else None
    )
    result.update(
        {
            "ok": strict_ok or steady_state_ok,
            "admission_policy": admission_policy,
            "strict_ok": strict_ok,
            "steady_state_ok": steady_state_ok,
            "mem_available_bytes": mem_available,
            "mem_available_ok": mem_ok,
            "steady_mem_available_ok": steady_mem_ok,
            "swap_total_bytes": swap_total,
            "swap_free_bytes": swap_free,
            "minimum_swap_free_by_percent_bytes": minimum_swap_free_by_percent,
            "steady_minimum_swap_free_by_percent_bytes": (
                steady_minimum_swap_free_by_percent
            ),
            "swap_free_percent": (
                round(swap_free * 100.0 / swap_total, 3) if swap_total else 100.0
            ),
            "swap_free_mib_ok": swap_free_mib_ok,
            "swap_free_percent_ok": swap_free_percent_ok,
            "swap_free_ok": swap_ok,
            "steady_swap_free_percent_ok": steady_swap_free_percent_ok,
            "combined_headroom_bytes": combined_headroom,
            "steady_combined_headroom_ok": steady_combined_headroom_ok,
        }
    )
    return result


def dpkg_audit_check(fixture: Path | None, timeout_seconds: float) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "source": str(fixture) if fixture is not None else "dpkg --audit",
    }
    try:
        if fixture is not None:
            output = bounded_read_text(fixture)
            returncode = 0
            stderr = ""
        else:
            completed = subprocess.run(
                ["dpkg", "--audit"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
            output = completed.stdout
            stderr = completed.stderr
            returncode = completed.returncode
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        result["error"] = str(exc)
        return result

    result.update(
        {
            "ok": returncode == 0 and not output.strip() and not stderr.strip(),
            "returncode": returncode,
            "output": output,
            "stderr": stderr,
        }
    )
    return result


def read_proc_field(path: Path, binary: bool = False) -> str:
    mode = "rb" if binary else "r"
    kwargs: dict[str, Any] = (
        {} if binary else {"encoding": "utf-8", "errors": "replace"}
    )
    with path.open(mode, **kwargs) as handle:
        value = handle.read(MAX_PROC_FIELD_BYTES + 1)
    if len(value) > MAX_PROC_FIELD_BYTES:
        raise ValueError(f"process field exceeds safety bound: {path}")
    if isinstance(value, bytes):
        return value.replace(b"\0", b" ").decode("utf-8", errors="replace")
    return value


def process_state(status: str) -> str | None:
    for line in status.splitlines():
        if line.startswith("State:"):
            fields = line.split()
            return fields[1] if len(fields) >= 2 else None
    return None


def package_process_check(proc_root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "source": str(proc_root),
        "names": sorted(PACKAGE_PROCESS_NAMES),
        "active": [],
        "inspection_errors": [],
    }
    try:
        entries = sorted(
            (entry for entry in proc_root.iterdir() if entry.name.isdigit()),
            key=lambda entry: int(entry.name),
        )
    except OSError as exc:
        result["inspection_errors"].append(str(exc))
        return result

    for entry in entries:
        try:
            comm = read_proc_field(entry / "comm").strip()
            cmdline = read_proc_field(entry / "cmdline", binary=True).strip()
            status_path = entry / "status"
            status = read_proc_field(status_path) if status_path.exists() else ""
        except FileNotFoundError:
            # A process exiting between directory enumeration and inspection is
            # normal and cannot still own a lock after it has disappeared.
            continue
        except (OSError, ValueError) as exc:
            result["inspection_errors"].append(f"pid {entry.name}: {exc}")
            continue

        argv0 = cmdline.split(None, 1)[0] if cmdline else ""
        executable = os.path.basename(argv0)
        matched = comm if comm in PACKAGE_PROCESS_NAMES else executable
        if matched not in PACKAGE_PROCESS_NAMES:
            continue
        state = process_state(status)
        if state == "Z":
            continue
        result["active"].append(
            {
                "pid": int(entry.name),
                "name": matched,
                "comm": comm,
                "state": state,
            }
        )

    result["ok"] = not result["active"] and not result["inspection_errors"]
    return result


def package_lock_check(proc_locks: Path, lock_paths: list[Path]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "source": str(proc_locks),
        "paths": [],
        "active": [],
        "inspection_errors": [],
    }
    identities: dict[tuple[int, int, int], list[str]] = {}
    for path in lock_paths:
        record: dict[str, Any] = {"path": str(path), "exists": False}
        try:
            details = path.stat()
        except FileNotFoundError:
            result["paths"].append(record)
            continue
        except OSError as exc:
            record["error"] = str(exc)
            result["paths"].append(record)
            result["inspection_errors"].append(f"{path}: {exc}")
            continue
        identity = (os.major(details.st_dev), os.minor(details.st_dev), details.st_ino)
        record.update(
            {
                "exists": True,
                "device_major": identity[0],
                "device_minor": identity[1],
                "inode": identity[2],
            }
        )
        result["paths"].append(record)
        identities.setdefault(identity, []).append(str(path))

    try:
        raw_locks = bounded_read_text(proc_locks)
    except (OSError, ValueError) as exc:
        result["inspection_errors"].append(str(exc))
        return result

    for line in raw_locks.splitlines():
        match = LOCK_RE.match(line)
        if match is None:
            if line.strip():
                result["inspection_errors"].append(
                    f"unrecognized lock record: {line[:160]}"
                )
            continue
        identity = (
            int(match.group("major"), 16),
            int(match.group("minor"), 16),
            int(match.group("inode"), 10),
        )
        for path in identities.get(identity, []):
            result["active"].append(
                {
                    "path": path,
                    "pid": int(match.group("pid"), 10),
                    "kind": match.group("kind"),
                    "access": match.group("access"),
                    "blocked": match.group("blocked") is not None,
                }
            )

    result["ok"] = not result["active"] and not result["inspection_errors"]
    return result


def percentage(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid percentage: {value}") from exc
    if not math.isfinite(parsed) or not 0.0 <= parsed <= 100.0:
        raise argparse.ArgumentTypeError("percentage must be between 0 and 100")
    return parsed


def positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid number: {value}") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument(
        "--meminfo",
        type=Path,
        default=Path("/proc/meminfo"),
        help="meminfo input; default /proc/meminfo",
    )
    value.add_argument(
        "--min-mem-available-mib",
        type=int,
        default=DEFAULT_MIN_MEM_AVAILABLE_MIB,
        help=f"minimum MemAvailable in MiB; default {DEFAULT_MIN_MEM_AVAILABLE_MIB}",
    )
    value.add_argument(
        "--min-swap-free-mib",
        type=int,
        default=DEFAULT_MIN_SWAP_FREE_MIB,
        help=f"minimum SwapFree in MiB; default {DEFAULT_MIN_SWAP_FREE_MIB}",
    )
    value.add_argument(
        "--min-swap-free-percent",
        type=percentage,
        default=DEFAULT_MIN_SWAP_FREE_PERCENT,
        help=f"minimum free swap percentage; default {DEFAULT_MIN_SWAP_FREE_PERCENT:g}",
    )
    value.add_argument(
        "--steady-min-mem-available-mib",
        type=int,
        default=DEFAULT_STEADY_MIN_MEM_AVAILABLE_MIB,
        help=(
            "steady-state minimum MemAvailable in MiB; default "
            f"{DEFAULT_STEADY_MIN_MEM_AVAILABLE_MIB}"
        ),
    )
    value.add_argument(
        "--steady-min-swap-free-percent",
        type=percentage,
        default=DEFAULT_STEADY_MIN_SWAP_FREE_PERCENT,
        help=(
            "steady-state minimum free swap percentage; default "
            f"{DEFAULT_STEADY_MIN_SWAP_FREE_PERCENT:g}"
        ),
    )
    value.add_argument(
        "--steady-min-combined-headroom-mib",
        type=int,
        default=DEFAULT_STEADY_MIN_COMBINED_HEADROOM_MIB,
        help=(
            "steady-state minimum MemAvailable plus SwapFree in MiB; default "
            f"{DEFAULT_STEADY_MIN_COMBINED_HEADROOM_MIB}"
        ),
    )
    value.add_argument(
        "--dpkg-audit-output",
        type=Path,
        help="read dpkg --audit output from a fixture instead of running dpkg",
    )
    value.add_argument(
        "--dpkg-audit-timeout-seconds",
        type=positive_float,
        default=10.0,
        help="dpkg --audit timeout; default 10",
    )
    value.add_argument(
        "--proc-root",
        type=Path,
        default=Path("/proc"),
        help="process tree to inspect; default /proc",
    )
    value.add_argument(
        "--proc-locks",
        type=Path,
        default=Path("/proc/locks"),
        help="kernel lock table to inspect; default /proc/locks",
    )
    value.add_argument(
        "--lock-path",
        action="append",
        type=Path,
        help="package lock path; repeat to replace the built-in path set",
    )
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.min_mem_available_mib < 0:
        parser().error("--min-mem-available-mib must not be negative")
    if args.min_swap_free_mib < 0:
        parser().error("--min-swap-free-mib must not be negative")
    if args.steady_min_mem_available_mib < 0:
        parser().error("--steady-min-mem-available-mib must not be negative")
    if args.steady_min_combined_headroom_mib < 0:
        parser().error("--steady-min-combined-headroom-mib must not be negative")
    lock_paths = args.lock_path or [Path(path) for path in DEFAULT_LOCK_PATHS]
    checks = {
        "memory": memory_check(
            args.meminfo,
            args.min_mem_available_mib,
            args.min_swap_free_mib,
            args.min_swap_free_percent,
            args.steady_min_mem_available_mib,
            args.steady_min_swap_free_percent,
            args.steady_min_combined_headroom_mib,
        ),
        "package_processes": package_process_check(args.proc_root),
        "package_locks": package_lock_check(args.proc_locks, lock_paths),
        "dpkg_audit": dpkg_audit_check(
            args.dpkg_audit_output, args.dpkg_audit_timeout_seconds
        ),
    }
    failures = [name for name, check in checks.items() if not check["ok"]]
    result = {
        "schema": SCHEMA,
        "ready": not failures,
        "failures": failures,
        "checks": checks,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
