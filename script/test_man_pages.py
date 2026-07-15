#!/usr/bin/env python3
"""Regression checks for packaged manual page sources."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAN_ROOT = ROOT / "docs" / "man"

EXPECTED = {
    "man1": {
        "hidloom-key.1",
        "hidloom-keytext.1",
        "hidloom-ctrl.1",
        "hidloom-oled.1",
        "hidloom-notify.1",
    },
    "man5": {
        "hidloom-keymap.5",
        "hidloom-matrixd.5",
        "hidloom-ledd.5",
    },
    "man8": {
        "hidloom-hidd.8",
        "hidloom-uidd.8",
        "hidloom-outputd.8",
        "hidloom-logicd-core.8",
        "matrixd.8",
        "logicd.8",
        "usbd.8",
        "viald.8",
        "httpd.8",
        "i2cd.8",
        "ledd.8",
        "ledd-shutdown.8",
        "btd.8",
        "spid.8",
        "sessiond.8",
    },
}


def main() -> None:
    readme = (MAN_ROOT / "README.md").read_text(encoding="utf-8")
    assert "@HIDLOOM_GIT_SHA@" in readme
    assert "/usr/share/man" in readme

    for section, names in EXPECTED.items():
        actual = {path.name for path in (MAN_ROOT / section).glob(f"*.{section[-1]}")}
        assert names <= actual, f"{section} missing: {sorted(names - actual)}"
        for name in names:
            path = MAN_ROOT / section / name
            text = path.read_text(encoding="utf-8")
            assert text.startswith(".TH "), path
            assert '"HIDloom"' in text.splitlines()[0], path
            assert ".SH NAME" in text, path
            assert ".SH SEE ALSO" in text, path
            assert "@HIDLOOM_VERSION@" in text, path
            assert "@HIDLOOM_GIT_SHA@" in text, path
            assert "https://github.com/cqa02303/hidloom/tree/@HIDLOOM_GIT_SHA@/docs" in text, path

    build_deb = (ROOT / "tools" / "package" / "build_deb_package.sh").read_text(encoding="utf-8")
    assert "MAN_SRC=\"$TMP_DIR/docs/man\"" in build_deb
    assert "usr/share/man/man$section" in build_deb
    assert "gzip -9n" in build_deb
    assert "@HIDLOOM_VERSION@" in build_deb
    assert "@HIDLOOM_GIT_SHA@" in build_deb

    candidate = (ROOT / "tools" / "package" / "release_candidate_check.sh").read_text(encoding="utf-8")
    assert "usr/share/man/man1/hidloom-key" in candidate
    assert "usr/share/man/man5/hidloom-keymap" in candidate
    assert "usr/share/man/man8/hidloom-logicd-core" in candidate

    print("ok: manual page sources are packaged and linked")


if __name__ == "__main__":
    main()
