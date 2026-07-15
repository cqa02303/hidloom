#!/usr/bin/env python3
"""Behavior and documentation checks for keymap CLI helpers."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
from typing import Any

from socket_test_helpers import UNIX_SOCKET_PATH_MAX_BYTES, temporary_unix_socket_path

ROOT = Path(__file__).resolve().parents[1]


class UnixJsonFixture:
    def __init__(self, socket_path: Path, response: dict[str, Any]) -> None:
        self.socket_path = socket_path
        self.response = response
        self.request: dict[str, Any] | None = None
        self.error: BaseException | None = None
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)

    def _serve(self) -> None:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                server.bind(str(self.socket_path))
                server.listen(1)
                self.ready.set()
                connection, _ = server.accept()
                with connection:
                    data = b""
                    while not data.endswith(b"\n"):
                        chunk = connection.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                    self.request = json.loads(data.decode("utf-8"))
                    payload = json.dumps(self.response, separators=(",", ":")).encode("utf-8") + b"\n"
                    connection.sendall(payload)
        except BaseException as exc:
            self.error = exc
            self.ready.set()

    def start(self) -> None:
        self.thread.start()
        assert self.ready.wait(timeout=2), "Unix socket fixture did not start"
        if self.error is not None:
            raise self.error

    def finish(self) -> dict[str, Any]:
        self.thread.join(timeout=2)
        assert not self.thread.is_alive(), "Unix socket fixture did not finish"
        if self.error is not None:
            raise self.error
        assert self.request is not None
        return self.request


def run_helper(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5,
        check=False,
    )


def test_getkeymap() -> None:
    response = {
        "t": "keymap",
        "layers": [{"7,0": "KC_ESC"}],
        "mode": "jp",
        "output_target": "auto",
        "active": {"momentary": [], "toggled": [], "locked": [], "all": [0]},
    }
    with temporary_unix_socket_path("ctrl.sock") as socket_path:
        assert len(os.fsencode(socket_path)) <= UNIX_SOCKET_PATH_MAX_BYTES
        fixture = UnixJsonFixture(socket_path, response)
        fixture.start()
        result = run_helper([str(ROOT / "getkeymap.sh"), "--socket", str(socket_path)])
        request = fixture.finish()
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == response
    assert request == {"t": "G"}

    missing = run_helper([str(ROOT / "getkeymap.sh"), "--socket", "/tmp/hidloom-missing-getkeymap.sock"])
    assert missing.returncode != 0
    assert "Socket not found" in missing.stderr


def test_setkeycode() -> None:
    with temporary_unix_socket_path("ctrl.sock") as socket_path:
        fixture = UnixJsonFixture(socket_path, {"t": "M", "result": "ok"})
        fixture.start()
        result = run_helper(
            [
                str(ROOT / "setkeycode.sh"),
                "--socket",
                str(socket_path),
                "--layer",
                "2",
                "3,4",
                "LT(1,KC_A)",
            ]
        )
        request = fixture.finish()
    assert result.returncode == 0, result.stderr
    assert "Success: Layer 2, position 3,4 set to LT(1,KC_A)" in result.stdout
    assert request == {"t": "M", "l": 2, "r": 3, "c": 4, "a": "LT(1,KC_A)"}

    with temporary_unix_socket_path("ctrl.sock") as socket_path:
        fixture = UnixJsonFixture(socket_path, {"t": "M", "result": "error", "msg": "out of range"})
        fixture.start()
        failed = run_helper([str(ROOT / "setkeycode.sh"), "--socket", str(socket_path), "99,99", "KC_A"])
        failed_request = fixture.finish()
    assert failed.returncode != 0
    assert "out of range" in failed.stderr
    assert failed_request == {"t": "M", "l": 0, "r": 99, "c": 99, "a": "KC_A"}

    invalid = run_helper([str(ROOT / "setkeycode.sh"), "7", "KC_A"])
    assert invalid.returncode != 0
    assert "Invalid position format" in invalid.stderr


def test_sources_and_docs() -> None:
    getkeymap = (ROOT / "getkeymap.sh").read_text(encoding="utf-8")
    setkeycode = (ROOT / "setkeycode.sh").read_text(encoding="utf-8")
    get_doc = (ROOT / "GETKEYMAP.md").read_text(encoding="utf-8")
    set_doc = (ROOT / "SETKEYCODE.md").read_text(encoding="utf-8")

    for name, text in {"getkeymap.sh": getkeymap, "setkeycode.sh": setkeycode}.items():
        assert "python3" in text, name
        assert "socket.AF_UNIX" in text, name
        assert "nc -U" not in text, name
        assert "netcat" not in text.lower(), name

    assert "hidloom-ctrl keymap" in get_doc
    assert '"t":"G"' in get_doc
    assert "hidloom-logicd-core logicd-companion" in get_doc
    assert "hidloom-ctrl save" in set_doc
    assert "/mnt/p3/keymap.json" in set_doc
    assert '"t":"M"' in set_doc and '"t":"S"' in set_doc
    assert "LT(1,KC_A)" in set_doc

    forbidden = [
        "http/httpd.py",
        "http/static/",
        "logicd/logicd.py",
        "logicd/README.md",
        "test_getkeymap.sh",
        "test_setkeycode.sh",
        "@app.route",
        "Flask",
    ]
    for name, text in {"GETKEYMAP.md": get_doc, "SETKEYCODE.md": set_doc}.items():
        assert "python3" in text or "hidloom-ctrl" in text, name
        assert "netcat" not in text.lower(), name
        for stale in forbidden:
            assert stale not in text, f"{name}: {stale}"

    assert not (ROOT / "test_getkeymap.sh").exists()
    assert not (ROOT / "test_setkeycode.sh").exists()
    export_config = json.loads((ROOT / "config/public-export.json").read_text(encoding="utf-8"))
    include_files = set(export_config["include_files"])
    assert "test_getkeymap.sh" not in include_files
    assert "test_setkeycode.sh" not in include_files


def main() -> None:
    temporary_root = Path(tempfile.mkdtemp(prefix="hl-kh-", dir="/tmp"))
    deep_tmpdir = temporary_root / ("deep-path-" * 10)
    deep_tmpdir.mkdir()
    previous_tmpdir = os.environ.get("TMPDIR")
    previous_tempdir = tempfile.tempdir
    try:
        os.environ["TMPDIR"] = str(deep_tmpdir)
        tempfile.tempdir = None
        assert len(os.fsencode(deep_tmpdir / "hidloom-setkeycode-error-xxxxxxxx" / "ctrl.sock")) > 107
        test_getkeymap()
        test_setkeycode()
    finally:
        if previous_tmpdir is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = previous_tmpdir
        tempfile.tempdir = previous_tempdir
        shutil.rmtree(temporary_root)
    test_sources_and_docs()
    print("ok: keymap CLI helpers use tested Python Unix socket requests")


if __name__ == "__main__":
    main()
