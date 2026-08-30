#!/usr/bin/env python3
"""Regression tests for matrixd's bounded, privacy-safe RAM trace writer."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include "trace.h"

int main(int argc, char **argv)
{
    if (argc != 2)
        return 2;
    MatrixdTrace trace;
    if (matrixd_trace_start(&trace, argv[1], 4096) < 0)
        return 3;
    for (int i = 0; i < 120; i++) {
        char line[512];
        const char *kind = (i % 2) ? "dispatch" : "debounce";
        int written = snprintf(
            line, sizeof(line),
            "{\"schema\":\"matrixd.trace.v1\",\"kind\":\"%s\","
            "\"realtime_us\":%d,\"monotonic_us\":%d,\"scan\":%d,"
            "\"row\":1,\"col\":2,\"confirmed\":\"%c\","
            "\"primary\":\"%s\",\"committed\":%s}\n",
            kind, i + 1000, i + 2000, i, (i % 3) ? 'P' : 'R',
            (i == 90) ? "failed" : "sent", (i == 90) ? "false" : "true");
        if (written <= 0 || (size_t)written >= sizeof(line))
            return 4;
        while (matrixd_trace_emit(&trace, line, (size_t)written) < 0) {
            struct timespec pause = {0, 1000000};
            nanosleep(&pause, NULL);
        }
    }
    matrixd_trace_stop(&trace);
    return 0;
}
'''


def main() -> None:
    source = (ROOT / "daemon/matrixd/matrixd.c").read_text(encoding="utf-8")
    unit = (ROOT / "system/systemd/matrixd.service").read_text(encoding="utf-8")
    forbidden = ("mapped_keycode", "keycode", "hid_payload", "packet", "script_content", "credential")
    for value in forbidden:
        assert f'\\"{value}\\"' not in source
    scan_loop = source[source.index("MatrixdDebounceKey before = key_state") :]
    assert scan_loop.index("matrixd_trace_debounce(") < scan_loop.index("sock_send_event(")
    failed_send = scan_loop[scan_loop.index("if (sock_send_event(sock_fd") :]
    assert failed_send.index('"failed", "not_attempted", 0') < failed_send.index("goto next_scan")
    successful_send = failed_send[failed_send.index("const char *tap_result") :]
    assert successful_send.index('"sent", tap_result, 1') < successful_send.index(
        "matrixd_debounce_commit_event"
    )
    assert "User=root" in unit
    assert "MATRIXD_EVENT_LOG_PATH=/run/hidloom/matrixd-trace.jsonl" in unit
    assert "MATRIXD_EVENT_LOG_MAX_BYTES=4194304" in unit
    trace_source = (ROOT / "daemon/matrixd/trace.c").read_text(encoding="utf-8")
    assert 'prctl(PR_SET_NAME, "matrixd-trace"' in trace_source
    assert "O_NOFOLLOW" in trace_source
    build_bundle = (ROOT / "tools/package/build_release_bundle.sh").read_text(encoding="utf-8")
    buildroot_package = (
        ROOT / "build/buildroot/hidloom-external/package/hidloom-matrixd/hidloom-matrixd.mk"
    ).read_text(encoding="utf-8")
    makefile = (ROOT / "daemon/matrixd/Makefile").read_text(encoding="utf-8")
    assert '"$REPO_ROOT/daemon/matrixd/trace.c"' in build_bundle
    assert "$(@D)/trace.c" in buildroot_package
    assert "trace.c" in makefile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        harness = tmp_path / "trace_harness.c"
        binary = tmp_path / "trace_harness"
        trace_path = tmp_path / "matrixd-trace.jsonl"
        unrelated = tmp_path / "unrelated.log"
        unrelated.write_text("keep me\n", encoding="utf-8")
        harness.write_text(HARNESS, encoding="utf-8")
        subprocess.run(
            [
                "gcc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                "-D_POSIX_C_SOURCE=200809L", "-I", str(ROOT / "daemon/matrixd"),
                str(harness), str(ROOT / "daemon/matrixd/trace.c"), "-o", str(binary),
            ],
            check=True,
        )
        subprocess.run([str(binary), str(trace_path)], check=True)

        rotated = tmp_path / "matrixd-trace.1.jsonl"
        assert trace_path.exists()
        assert rotated.exists()
        assert trace_path.stat().st_size <= 4096
        assert rotated.stat().st_size <= 4096
        assert trace_path.stat().st_size + rotated.stat().st_size <= 8192
        assert stat.S_IMODE(trace_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(rotated.stat().st_mode) == 0o600
        assert trace_path.stat().st_uid == os.geteuid()
        assert rotated.stat().st_uid == os.geteuid()
        assert unrelated.read_text(encoding="utf-8") == "keep me\n"

        records: list[dict[str, object]] = []
        for path in (rotated, trace_path):
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise AssertionError(f"invalid JSONL in {path.name}: {line!r}") from exc
                assert record["schema"] == "matrixd.trace.v1"
                assert record["kind"] in {"debounce", "dispatch"}
                assert isinstance(record["realtime_us"], int)
                assert isinstance(record["monotonic_us"], int)
                assert isinstance(record["row"], int)
                assert isinstance(record["col"], int)
                assert not forbidden & record.keys()
                records.append(record)
        scans = [int(record["scan"]) for record in records]
        assert scans == sorted(scans)
        failed = [record for record in records if record.get("primary") == "failed"]
        assert len(failed) == 1
        assert failed[0]["committed"] is False

    print("ok: matrixd trace is bounded, private, ordered, and fail-open")


if __name__ == "__main__":
    main()
