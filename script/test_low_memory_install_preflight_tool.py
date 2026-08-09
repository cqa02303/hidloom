#!/usr/bin/env python3
"""Focused regression checks for the low-memory package-install preflight."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "package" / "low_memory_install_preflight.py"


def write_meminfo(
    path: Path, *, available_mib: int, total_mib: int, free_mib: int
) -> None:
    path.write_text(
        "MemTotal:         512000 kB\n"
        f"MemAvailable:     {available_mib * 1024} kB\n"
        f"SwapTotal:        {total_mib * 1024} kB\n"
        f"SwapFree:         {free_mib * 1024} kB\n",
        encoding="utf-8",
    )


def run_tool(case: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(TOOL),
        "--meminfo",
        str(case / "meminfo"),
        "--dpkg-audit-output",
        str(case / "dpkg-audit"),
        "--proc-root",
        str(case / "proc"),
        "--proc-locks",
        str(case / "proc-locks"),
        "--lock-path",
        str(case / "dpkg-lock"),
        *extra,
    ]
    return subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def result_json(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert not result.stderr, result.stderr
    return json.loads(result.stdout)


def make_case(root: Path, name: str) -> Path:
    case = root / name
    case.mkdir()
    (case / "proc").mkdir()
    (case / "dpkg-audit").write_text("", encoding="utf-8")
    (case / "proc-locks").write_text("", encoding="utf-8")
    (case / "dpkg-lock").write_text("", encoding="utf-8")
    write_meminfo(case / "meminfo", available_mib=256, total_mib=400, free_mib=320)
    return case


def add_process(case: Path, pid: int, name: str, state: str = "S") -> None:
    process = case / "proc" / str(pid)
    process.mkdir()
    (process / "comm").write_text(name + "\n", encoding="utf-8")
    (process / "cmdline").write_bytes(f"/usr/bin/{name}\0install\0".encode())
    (process / "status").write_text(
        f"Name:\t{name}\nState:\t{state} (fixture)\n", encoding="utf-8"
    )


def main() -> None:
    assert TOOL.is_file(), TOOL
    help_result = subprocess.run(
        [sys.executable, str(TOOL), "--help"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert help_result.returncode == 0, help_result.stderr
    assert "--min-mem-available-mib" in help_result.stdout
    assert "--min-swap-free-mib" in help_result.stdout
    assert "--min-swap-free-percent" in help_result.stdout

    with tempfile.TemporaryDirectory(prefix="hidloom-memory-preflight-") as raw:
        root = Path(raw)

        safe = make_case(root, "safe")
        before = {
            path.name: path.read_bytes() for path in safe.iterdir() if path.is_file()
        }
        result = run_tool(safe)
        assert result.returncode == 0, (result.stdout, result.stderr)
        payload = result_json(result)
        assert payload["schema"] == "hidloom.low-memory-install-preflight.v1"
        assert payload["ready"] is True
        assert payload["failures"] == []
        memory = payload["checks"]["memory"]
        assert memory["minimum_mem_available_bytes"] == 128 * 1024 * 1024
        assert memory["minimum_swap_free_mib"] == 256
        assert memory["minimum_swap_free_bytes"] == 256 * 1024 * 1024
        assert memory["minimum_swap_free_percent"] == 75.0
        assert memory["swap_free_percent"] == 80.0
        assert memory["swap_free_mib_ok"] is True
        assert memory["swap_free_percent_ok"] is True
        after = {
            path.name: path.read_bytes() for path in safe.iterdir() if path.is_file()
        }
        assert after == before, "read-only preflight changed an input fixture"

        exact = make_case(root, "exact")
        write_meminfo(exact / "meminfo", available_mib=128, total_mib=256, free_mib=256)
        result = run_tool(exact)
        assert result.returncode == 0, result.stdout
        exact_memory = result_json(result)["checks"]["memory"]
        assert exact_memory["minimum_swap_free_by_percent_bytes"] == 192 * 1024 * 1024
        assert exact_memory["swap_free_mib_ok"] is True
        assert exact_memory["swap_free_percent_ok"] is True

        percent_exact = make_case(root, "percent-exact")
        write_meminfo(
            percent_exact / "meminfo",
            available_mib=128,
            total_mib=400,
            free_mib=300,
        )
        result = run_tool(percent_exact)
        assert result.returncode == 0, result.stdout
        percent_exact_memory = result_json(result)["checks"]["memory"]
        assert percent_exact_memory["swap_free_percent"] == 75.0
        assert percent_exact_memory["swap_free_mib_ok"] is True
        assert percent_exact_memory["swap_free_percent_ok"] is True

        low_memory = make_case(root, "low-memory")
        write_meminfo(
            low_memory / "meminfo", available_mib=127, total_mib=400, free_mib=400
        )
        result = run_tool(low_memory)
        assert result.returncode == 1
        payload = result_json(result)
        assert payload["ready"] is False
        assert payload["failures"] == ["memory"]
        assert payload["checks"]["memory"]["mem_available_ok"] is False

        low_swap = make_case(root, "low-swap")
        write_meminfo(
            low_swap / "meminfo", available_mib=256, total_mib=400, free_mib=299
        )
        result = run_tool(low_swap)
        assert result.returncode == 1
        payload = result_json(result)
        assert payload["checks"]["memory"]["swap_free_ok"] is False
        assert payload["checks"]["memory"]["swap_free_mib_ok"] is True
        assert payload["checks"]["memory"]["swap_free_percent_ok"] is False

        threshold_override = make_case(root, "threshold-override")
        write_meminfo(
            threshold_override / "meminfo",
            available_mib=96,
            total_mib=400,
            free_mib=200,
        )
        result = run_tool(
            threshold_override,
            "--min-mem-available-mib",
            "96",
            "--min-swap-free-mib",
            "200",
            "--min-swap-free-percent",
            "50",
        )
        assert result.returncode == 0, result.stdout

        no_swap = make_case(root, "no-swap")
        write_meminfo(no_swap / "meminfo", available_mib=128, total_mib=0, free_mib=0)
        result = run_tool(no_swap)
        assert result.returncode == 1
        no_swap_memory = result_json(result)["checks"]["memory"]
        assert no_swap_memory["swap_free_percent"] == 100.0
        assert no_swap_memory["swap_free_mib_ok"] is False
        assert no_swap_memory["swap_free_percent_ok"] is True
        assert no_swap_memory["swap_free_ok"] is False

        tiny_swap = make_case(root, "tiny-swap")
        write_meminfo(
            tiny_swap / "meminfo", available_mib=256, total_mib=128, free_mib=128
        )
        result = run_tool(tiny_swap)
        assert result.returncode == 1
        tiny_swap_memory = result_json(result)["checks"]["memory"]
        assert tiny_swap_memory["swap_free_mib_ok"] is False
        assert tiny_swap_memory["swap_free_percent_ok"] is True
        assert tiny_swap_memory["swap_free_ok"] is False

        malformed = make_case(root, "malformed")
        (malformed / "meminfo").write_text(
            "MemAvailable: 200000 kB\nSwapTotal: 100000 kB\n", encoding="utf-8"
        )
        result = run_tool(malformed)
        assert result.returncode == 1
        payload = result_json(result)
        assert payload["ready"] is False
        assert "missing meminfo entries" in payload["checks"]["memory"]["error"]

        audit = make_case(root, "audit")
        (audit / "dpkg-audit").write_text(
            "The following packages are only half configured:\n hidloom-core\n",
            encoding="utf-8",
        )
        result = run_tool(audit)
        assert result.returncode == 1
        payload = result_json(result)
        assert payload["failures"] == ["dpkg_audit"]
        assert payload["checks"]["dpkg_audit"]["ok"] is False

        process = make_case(root, "process")
        add_process(process, 123, "apt-get")
        result = run_tool(process)
        assert result.returncode == 1
        payload = result_json(result)
        assert payload["failures"] == ["package_processes"]
        assert payload["checks"]["package_processes"]["active"][0]["pid"] == 123

        zombie = make_case(root, "zombie")
        add_process(zombie, 124, "dpkg", state="Z")
        add_process(zombie, 125, "ssh")
        result = run_tool(zombie)
        assert result.returncode == 0, result.stdout

        lock = make_case(root, "lock")
        details = (lock / "dpkg-lock").stat()
        (lock / "proc-locks").write_text(
            "1: POSIX  ADVISORY  WRITE 777 "
            f"{os.major(details.st_dev):02x}:{os.minor(details.st_dev):02x}:"
            f"{details.st_ino} 0 EOF\n",
            encoding="utf-8",
        )
        result = run_tool(lock)
        assert result.returncode == 1
        payload = result_json(result)
        assert payload["failures"] == ["package_locks"]
        active = payload["checks"]["package_locks"]["active"]
        assert active == [
            {
                "access": "WRITE",
                "blocked": False,
                "kind": "POSIX",
                "path": str(lock / "dpkg-lock"),
                "pid": 777,
            }
        ]

        missing_sources = make_case(root, "missing-sources")
        (missing_sources / "proc-locks").unlink()
        (missing_sources / "dpkg-audit").unlink()
        result = run_tool(missing_sources)
        assert result.returncode == 1
        payload = result_json(result)
        assert set(payload["failures"]) == {"package_locks", "dpkg_audit"}

        invalid = run_tool(safe, "--min-swap-free-percent", "101")
        assert invalid.returncode == 2
        assert "percentage must be between 0 and 100" in invalid.stderr

    print("ok: low-memory package-install preflight tool")


if __name__ == "__main__":
    main()
