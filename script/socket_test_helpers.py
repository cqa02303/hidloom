#!/usr/bin/env python3
"""Shared Unix socket assertions for daemon smoke tests."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import os
import sys
import tempfile
from pathlib import Path


UNIX_SOCKET_PATH_MAX_BYTES = 107


@contextmanager
def temporary_unix_socket_path(filename: str = "socket.sock") -> Iterator[Path]:
    """Create a filesystem socket path independent of checkout/TMPDIR depth."""
    short_root = Path("/tmp")
    directory = short_root if short_root.is_dir() and os.access(short_root, os.W_OK) else None
    with tempfile.TemporaryDirectory(prefix="hl-s-", dir=directory) as temporary:
        socket_path = Path(temporary) / filename
        encoded_length = len(os.fsencode(socket_path))
        if encoded_length > UNIX_SOCKET_PATH_MAX_BYTES:
            raise RuntimeError(
                f"temporary Unix socket path is {encoded_length} bytes; "
                f"maximum is {UNIX_SOCKET_PATH_MAX_BYTES}: {socket_path}"
            )
        yield socket_path


def assert_socket_mode(path: Path, expected: int) -> None:
    actual = path.stat().st_mode & 0o777
    if sys.platform == "cygwin":
        # MSYS2/Cygwin noacl mounts can report sockets as 0644 even after
        # chmod(0666); keep Linux/Pi validation strict below.
        assert actual in (expected, 0o644), f"socket mode {actual:o} != {expected:o}"
    else:
        assert actual == expected, f"socket mode {actual:o} != {expected:o}"
