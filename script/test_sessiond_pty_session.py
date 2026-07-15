#!/usr/bin/env python3
"""Smoke-test the local PTY wrapper without HID or logicd wiring."""
from __future__ import annotations

import sys
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "daemon") not in sys.path:
    sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from sessiond.pty_mirror import PtyMirrorSession  # noqa: E402


def _fd_count() -> int | None:
    fd_dir = Path("/proc/self/fd")
    if not fd_dir.exists():
        return None
    return len(os.listdir(fd_dir))


def main() -> None:
    session = PtyMirrorSession("/bin/sh", rows=35, columns=120)
    session.start()
    try:
        assert session.active is True
        session.read_text_until_quiet(timeout=0.2)
        session.write(b"printf PTY_OK\\n")
        session.write_key_action("KC_ENTER")
        output = session.read_text_until_quiet(timeout=1.0)
        assert "PTY_OK" in output, output
        session.write(b"printf '%s/%s\\n' \"$LC_ALL\" \"$LANG\"")
        session.write_key_action("KC_ENTER")
        locale_output = session.read_text_until_quiet(timeout=1.0)
        assert "C/C" in locale_output, locale_output

        for action in ("KC_E", "KC_X", "KC_I", "KC_T", "KC_ENTER"):
            session.write_key_action(action)
        exit_output = session.read_text_until_quiet(timeout=1.0)
        code = session.wait(timeout=1.0)
        assert code == 0, (code, exit_output)
        assert session.active is False
    finally:
        session.terminate()

    before = _fd_count()
    for _index in range(3):
        failed = PtyMirrorSession("/definitely/missing/pty-mirror-shell", rows=35, columns=120)
        try:
            failed.start()
        except FileNotFoundError:
            pass
        else:
            raise AssertionError("missing shell should fail to start")
        finally:
            failed.close()
    after = _fd_count()
    if before is not None and after is not None:
        assert after <= before, (before, after)

    before = _fd_count()
    for _index in range(3):
        malformed = PtyMirrorSession("bash 'unterminated", rows=35, columns=120)
        try:
            malformed.start()
        except ValueError:
            pass
        else:
            raise AssertionError("malformed shell command should fail before PTY start")
        finally:
            malformed.close()
    after = _fd_count()
    if before is not None and after is not None:
        assert after <= before, (before, after)

    print("ok: sessiond PTY session wrapper starts shell, writes input, and exits")


if __name__ == "__main__":
    main()
