"""Script execution helpers for the HTTP script editor API."""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Dict


def script_check_env(repo_root: Path) -> Dict[str, str]:
    env = os.environ.copy()
    bin_dir = str(repo_root / "bin")
    parts = [part for part in env.get("PATH", "").split(os.pathsep) if part]
    if bin_dir not in parts:
        env["PATH"] = os.pathsep.join([bin_dir, *parts])
    env.setdefault("HIDLOOM_REPO_ROOT", str(repo_root))
    return env


def trim_script_output(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n... truncated ..."


async def run_script_path(script_path: Path, *, repo_root: Path, timeout: float = 20.0) -> dict[str, object]:
    """Run a script and return the normalized result payload fields.

    The HTTP layer owns request validation, response status, and audit logging.
    This helper owns subprocess environment setup, timeout handling, and output
    trimming so ``scripts_api.py`` can stay focused on route behavior.
    """

    proc = await asyncio.create_subprocess_exec(
        str(script_path),
        cwd=str(repo_root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=script_check_env(repo_root),
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        timed_out = False
    except asyncio.TimeoutError:
        proc.kill()
        stdout_b, stderr_b = await proc.communicate()
        timed_out = True

    exit_code = -1 if timed_out else (proc.returncode if proc.returncode is not None else -1)
    return {
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stdout": trim_script_output(stdout_b.decode(errors="replace")),
        "stderr": trim_script_output(stderr_b.decode(errors="replace")),
    }


async def run_script_content(
    keycode: str,
    content: str,
    *,
    repo_root: Path,
    timeout: float = 20.0,
) -> dict[str, object]:
    """Write unsaved script content to a temporary executable and run it."""

    with tempfile.TemporaryDirectory(prefix=f"hidloom-script-check-{keycode}-") as tmpdir:
        script_path = Path(tmpdir) / f"{keycode}.sh"
        script_path.write_text(content, encoding="utf-8")
        os.chmod(script_path, 0o755)
        return await run_script_path(script_path, repo_root=repo_root, timeout=timeout)
