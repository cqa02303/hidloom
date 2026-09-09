"""Runtime JSON selection and atomic persistence; packaged defaults are read only."""
from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path

from hidloom_paths import default_config_file, runtime_file


def mutable_path(default_or_override: Path) -> Path:
    """Route a packaged path to runtime, retaining explicit non-default overrides."""
    path = Path(default_or_override)
    return runtime_file(path.name) if path == default_config_file(path.name) else path


def effective_source(path: Path) -> Path:
    path = Path(path)
    if path == runtime_file(path.name) and not path.exists():
        return default_config_file(path.name)
    return path


def load_json(path: Path) -> dict:
    data = json.loads(effective_source(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config root must be an object")
    return data


def atomic_write_json(path: Path, data: dict) -> None:
    path = Path(path)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    source = effective_source(path)
    mode = stat.S_IMODE(source.stat().st_mode) if source.exists() else 0o644
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
