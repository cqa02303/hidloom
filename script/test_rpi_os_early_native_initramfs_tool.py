#!/usr/bin/env python3
"""Focused regression checks for the optional Raspberry Pi OS E3 overlay."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "rpi_os_early_initramfs.py"
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "script"))

import rpi_os_early_initramfs as early  # noqa: E402
import test_rpi_os_early_initramfs_tool as e1_fixture  # noqa: E402


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and completed.returncode:
        raise AssertionError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def expect_failure(command: list[str], phrase: str) -> None:
    completed = run(command, check=False)
    assert completed.returncode != 0, f"command unexpectedly passed: {' '.join(command)}"
    output = completed.stdout + completed.stderr
    assert phrase.lower() in output.lower(), (phrase, output)


def compile_binary(
    compiler: str,
    directory: Path,
    name: str,
    *,
    static: bool,
) -> Path:
    source = directory / f"{name}.c"
    output = directory / name
    source.write_text(
        "#include <stdint.h>\n"
        f"static const char identity[] __attribute__((used)) = \"hidloom-e3-{name}\";\n"
        "int main(void) { return identity[0] == (char)0xff; }\n",
        encoding="utf-8",
    )
    command = [compiler, "-std=c11", "-Os"]
    if static:
        command.append("-static")
    command += [str(source), "-o", str(output)]
    run(command)
    return output


def native_arguments(paths: dict[str, Path]) -> list[str]:
    return [
        "--hidd",
        str(paths["hidd"]),
        "--outputd",
        str(paths["outputd"]),
        "--logicd-core",
        str(paths["logicd_core"]),
        "--matrixd",
        str(paths["matrixd"]),
        "--keymap",
        str(paths["keymap"]),
        "--keycodes",
        str(paths["keycodes"]),
        "--logicd-config",
        str(paths["logicd_config"]),
        "--matrixd-config",
        str(paths["matrixd_config"]),
        "--gpiomem",
        str(paths["gpiomem"]),
    ]


def native_base_prerequisite_entries(
    *, omit: str | None = None
) -> dict[str, tuple[int, bytes]]:
    """Create the minimal archive inventory used by the pinned E3 shell code."""
    entries: dict[str, tuple[int, bytes]] = {
        "bin": (0o120777, b"usr/bin"),
        "usr": (0o040755, b""),
        "usr/bin": (0o040755, b""),
        "usr/sbin": (0o040755, b""),
    }
    for absolute_path in early.NATIVE_BASE_REQUIRED_COMMAND_PATHS:
        archive_path = absolute_path.lstrip("/")
        if archive_path.startswith("bin/"):
            archive_path = "usr/" + archive_path
        if absolute_path != omit:
            entries[archive_path] = (0o100755, b"fixture executable payload\n")
    return entries


def native_build_command(
    *,
    base: Path,
    output: Path,
    manifest: Path,
    helper: Path,
    libcomposite: Path,
    usb_f_hid: Path,
    identity: Path,
    native: dict[str, Path],
) -> list[str]:
    return e1_fixture.build_command(
        base=base,
        output=output,
        manifest=manifest,
        helper=helper,
        libcomposite=libcomposite,
        usb_f_hid=usb_f_hid,
        identity=identity,
    ) + native_arguments(native)


def without_option(command: list[str], option: str) -> list[str]:
    index = command.index(option)
    return command[:index] + command[index + 2 :]


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def update_outer_hashes(manifest: dict, image_path: Path, image: bytes) -> None:
    boundary = manifest["base"]["zstd_offset"]
    overlay_end = boundary + manifest["overlay"]["size"]
    manifest["overlay"]["sha256"] = hashlib.sha256(
        image[boundary:overlay_end]
    ).hexdigest()
    manifest["output"].update(
        {
            "name": image_path.name,
            "size": len(image),
            "sha256": hashlib.sha256(image).hexdigest(),
        }
    )


FAKE_NATIVE_DAEMON = r"""#!/usr/bin/python3
import json
import os
from pathlib import Path
import signal
import socket
import sys
import time

running = True
def stop(_signum, _frame):
    global running
    running = False

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
name = Path(sys.argv[0]).name
sockets = []
if name == "hidloom-hidd":
    path = Path(os.environ["HIDD_STATUS_PATH"])
    payload = {"startup_release_reports": 2}
elif name == "hidloom-outputd":
    path = Path(os.environ["OUTPUTD_STATUS_PATH"])
    payload = {"target": "usb"}
elif name == "hidloom-logicd-core":
    path = Path(os.environ["LOGICD_CORE_STATUS_PATH"])
    payload = {"output_enabled": True}
    for variable in ("LOGICD_CORE_MATRIX_SOCKET", "LOGICD_CORE_CTRL_SOCKET"):
        socket_path = os.environ[variable]
        try:
            os.unlink(socket_path)
        except FileNotFoundError:
            pass
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(socket_path)
        listener.listen(1)
        sockets.append((listener, socket_path))
else:
    path = Path(os.environ["MATRIXD_STATUS_PATH"])
    payload = {"connected": True}
path.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
while running:
    time.sleep(0.01)
for listener, socket_path in sockets:
    listener.close()
    try:
        os.unlink(socket_path)
    except FileNotFoundError:
        pass
"""


def launcher_failure_cleanup_fixture(root: Path, *, endpoint_failure: bool) -> None:
    live = root / "live"
    runtime = live / "runtime"
    official = root / "run"
    gadget = root / "configfs/cqa02303v5"
    for path in (runtime, official, gadget):
        path.mkdir(parents=True, mode=0o700)
    launcher = runtime / "hidloom-early-input-launch"
    launcher.write_bytes(early.NATIVE_LAUNCHER_TEMPLATE)
    launcher.chmod(0o700)
    for name in ("hidloom-hidd", "hidloom-outputd", "hidloom-logicd-core", "matrixd"):
        daemon = runtime / name
        daemon.write_text(FAKE_NATIVE_DAEMON, encoding="utf-8")
        daemon.chmod(0o700)
    for name in ("keymap.json", "keycodes.json", "config.json", "matrixd.json"):
        (runtime / name).write_text("{}\n", encoding="utf-8")
    hidg0 = root / "hidg0"
    hidg2 = root / "hidg2"
    if endpoint_failure:
        hidg0.mkdir()
        hidg2.mkdir()
    else:
        hidg0.write_bytes(b"stale-main")
        hidg2.write_bytes(b"stale-us")
    udc = gadget / "UDC"
    udc.write_text("fixture.udc\n", encoding="ascii")
    (official / "gadget-bound.json").write_text("{}\n", encoding="utf-8")
    (official / "e1-gadget.ready").touch()
    environment = {
        **os.environ,
        "HIDLOOM_EARLY_LIVE": str(live),
        "HIDLOOM_EARLY_RUN": str(official),
        "HIDLOOM_EARLY_HIDG0": str(hidg0),
        "HIDLOOM_EARLY_HIDG2": str(hidg2),
        "HIDLOOM_EARLY_GADGET_PATH": str(gadget),
        "HIDLOOM_EARLY_RUN_MOVE_POLLS": "100",
    }
    process = subprocess.Popen(
        ["dash", str(launcher)],
        cwd=root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    pidfds: list[int] = []
    try:
        deadline = time.monotonic() + 3
        pid_paths = [
            live / "hidd.pid",
            live / "outputd.pid",
            live / "logicd-core.pid",
            live / "matrixd.pid",
        ]
        while not all(path.exists() for path in pid_paths):
            assert process.poll() is None, process.communicate()
            assert time.monotonic() < deadline
            time.sleep(0.005)
        pidfds = [os.pidfd_open(int(path.read_text(encoding="ascii")), 0) for path in pid_paths]
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 0, (stdout, stderr)
        for pidfd in pidfds:
            poller = select.poll()
            poller.register(pidfd, select.POLLIN)
            assert poller.poll(0), "native launcher left an early daemon alive"
        assert (live / "cleanup.state").read_text(encoding="ascii").strip() in (
            "released",
            "unbound",
        )
        assert not (live / "chain-staged").exists()
        if endpoint_failure:
            assert udc.read_text(encoding="ascii").strip() == ""
            assert not (official / "gadget-bound.json").exists()
            assert not (official / "e1-gadget.ready").exists()
            assert (live / "gadget-fallback-unbound").exists()
        else:
            assert hidg0.read_bytes() == bytes.fromhex("010000000000000000")
            assert hidg2.read_bytes() == bytes(8)
            assert udc.read_text(encoding="ascii") == "fixture.udc\n"
            assert (official / "gadget-bound.json").exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
        for pidfd in pidfds:
            os.close(pidfd)


OUTER_HOOK_STUB_LAUNCHER = r"""#!/bin/sh
record=${HIDLOOM_OUTER_RECORD:?}
printf '%s\n' "$$" >"$record/launcher.pid"
/usr/bin/sleep 60 &
child=$!
printf '%s\n' "$child" >"$record/child.pid"
[ "${HIDLOOM_STUB_STAGE:-0}" = 1 ] && : >"${HIDLOOM_OUTER_LIVE:?}/chain-staged"
if [ "${HIDLOOM_STUB_LEAVE_CHILD:-0}" = 1 ]; then
    trap 'exit 0' TERM
else
    trap 'kill "$child" >/dev/null 2>&1 || true; wait "$child" >/dev/null 2>&1 || true; exit 0' TERM
fi
while :; do :; done
"""


OUTER_HOOK_DELAYED_SETSID = r"""#!/usr/bin/python3
import os
import signal
import sys
import time

if os.environ.get("HIDLOOM_OUTER_SETSID_IGNORE_TERM", "0") == "1":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
time.sleep(float(os.environ.get("HIDLOOM_OUTER_SETSID_DELAY", "0.05")))
os.execv("/usr/bin/setsid", ["/usr/bin/setsid", *sys.argv[1:]])
"""


def replace_fixture_fragment(payload: bytes, old: bytes, new: bytes) -> bytes:
    """Apply one explicit host-only hook rewrite, rejecting template drift."""
    assert payload.count(old) == 1, old
    return payload.replace(old, new, 1)


def outer_hook_host_bytes(*, remove_group_handshake: bool = False) -> bytes:
    hook_data = early.native_hook_bytes(e1_fixture.KERNEL_RELEASE, "0" * 64)
    hook_data = replace_fixture_fragment(
        hook_data,
        b'''case " $(/bin/cat /proc/cmdline 2>/dev/null) " in\n    *" hidloom.early=e1 "*) ;;\n    *) exit 0 ;;\nesac''',
        b": # host fixture accepts the E3 boot selector",
    )
    hook_data = replace_fixture_fragment(
        hook_data, b"run=/run/hidloom-early", b"run=${HIDLOOM_OUTER_RUN:?}"
    )
    hook_data = replace_fixture_fragment(
        hook_data,
        b'[ ! -e /dev/gpiomem ]',
        b'[ ! -e "$root/dev/gpiomem" ]',
    )
    hook_data = replace_fixture_fragment(
        hook_data,
        b'udc=/sys/kernel/config/usb_gadget/cqa02303v5/UDC',
        b'udc=${HIDLOOM_OUTER_UDC:?}',
    )
    hook_data = replace_fixture_fragment(
        hook_data,
        b'"/usr/lib/hidloom/early/$name"',
        b'"$HIDLOOM_OUTER_SOURCE/$name"',
    )
    hook_data = replace_fixture_fragment(
        hook_data,
        b'/usr/bin/setsid /usr/sbin/chroot "$root" /bin/sh     '
        b'/dev/hidloom-early/runtime/hidloom-early-input-launch &',
        b'''"$HIDLOOM_OUTER_SETSID" /bin/sh "$runtime/hidloom-early-input-launch" &''',
    )
    hook_data = replace_fixture_fragment(
        hook_data,
        b"launcher=$!\n",
        b'''launcher=$!
printf '%s\n' "$launcher" >"$HIDLOOM_OUTER_RECORD/spawn.pid"
[ -z "${HIDLOOM_OUTER_POST_SPAWN_DELAY:-}" ] || \
    /usr/bin/sleep "$HIDLOOM_OUTER_POST_SPAWN_DELAY"
''',
    )
    if remove_group_handshake:
        hook_data = replace_fixture_fragment(
            hook_data,
            b'''group_ready=0
count=0
while [ "$count" -lt 100 ]; do
    leader_alive || break
    if group_alive && leader_alive; then
        group_ready=1
        break
    fi
    /usr/bin/sleep 0.01
    count=$((count + 1))
done
count=0
if [ "$group_ready" -eq 1 ]; then
    while [ "$count" -lt 300 ]; do
        if [ -e "$live/chain-staged" ]; then
            printf '%s
' chain-staged-before-run-move >"$state"
            exit 0
        fi
        group_alive || break
        /usr/bin/sleep 0.01
        count=$((count + 1))
    done
fi''',
            b'''count=0
while [ "$count" -lt 300 ]; do
    if [ -e "$live/chain-staged" ]; then
        printf '%s
' chain-staged-before-run-move >"$state"
        exit 0
    fi
    group_alive || break
    /usr/bin/sleep 0.01
    count=$((count + 1))
done''',
        )
    else:
        hook_data = replace_fixture_fragment(
            hook_data,
            b'while [ "$count" -lt 100 ]; do',
            b'while [ "$count" -lt "${HIDLOOM_OUTER_GROUP_POLLS:-100}" ]; do',
        )
    hook_data = replace_fixture_fragment(
        hook_data,
        b'while [ "$count" -lt 300 ]; do',
        b'while [ "$count" -lt "${HIDLOOM_OUTER_STAGE_POLLS:-300}" ]; do',
    )
    hook_data = replace_fixture_fragment(
        hook_data,
        b'while launcher_or_group_alive && [ "$count" -lt 100 ]; do',
        b'while launcher_or_group_alive && [ "$count" -lt "${HIDLOOM_OUTER_TERM_POLLS:-100}" ]; do',
    )
    hook_data = replace_fixture_fragment(
        hook_data,
        b'while launcher_or_group_alive && [ "$count" -lt 50 ]; do',
        b'while launcher_or_group_alive && [ "$count" -lt "${HIDLOOM_OUTER_KILL_POLLS:-50}" ]; do',
    )
    syntax = subprocess.run(
        ["dash", "-n"], input=hook_data, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    assert syntax.returncode == 0, syntax.stderr.decode()
    return hook_data


def outer_hook_failure_cleanup_fixture(root: Path, *, mode: str) -> None:
    """Execute the generated init-bottom failure path outside an initramfs."""
    assert mode in ("released", "residual-unbind", "unsafe")
    real_root = root / "root"
    device = real_root / "dev"
    live = device / "hidloom-early"
    source = root / "source"
    official = root / "run"
    record = root / "record"
    gadget = root / "configfs/cqa02303v5"
    for path in (device, source, official, record, gadget):
        path.mkdir(parents=True, mode=0o700)
    (device / "gpiomem").touch()
    (official / "e1-gadget.ready").touch()
    (official / "gadget-bound.json").write_text("{}\n", encoding="utf-8")

    (source / "hidloom-early-input-launch").write_text(
        OUTER_HOOK_STUB_LAUNCHER, encoding="utf-8"
    )
    delayed_setsid = root / "delayed-setsid"
    delayed_setsid.write_text(OUTER_HOOK_DELAYED_SETSID, encoding="utf-8")
    delayed_setsid.chmod(0o700)
    for name in ("hidloom-hidd", "hidloom-outputd", "hidloom-logicd-core", "matrixd"):
        (source / name).write_text("fixture executable\n", encoding="utf-8")
    for name in ("keymap.json", "keycodes.json", "config.json", "matrixd.json"):
        (source / name).write_text("{}\n", encoding="utf-8")

    hidg0 = device / "hidg0"
    hidg2 = device / "hidg2"
    udc = gadget / "UDC"
    if mode == "unsafe":
        hidg0.mkdir()
        hidg2.mkdir()
        udc.mkdir()
    else:
        hidg0.write_bytes(b"stale-main")
        hidg2.write_bytes(b"stale-us")
        udc.write_text("fixture.udc\n", encoding="ascii")

    hook_data = outer_hook_host_bytes()
    hook = root / "hidloom-early-input"
    hook.write_bytes(hook_data)
    hook.chmod(0o700)

    environment = {
        **os.environ,
        "rootmnt": str(real_root),
        "HIDLOOM_OUTER_RUN": str(official),
        "HIDLOOM_OUTER_SOURCE": str(source),
        "HIDLOOM_OUTER_UDC": str(udc),
        "HIDLOOM_OUTER_RECORD": str(record),
        "HIDLOOM_OUTER_LIVE": str(live),
        "HIDLOOM_OUTER_SETSID": str(delayed_setsid),
        "HIDLOOM_OUTER_SETSID_DELAY": "0.05",
        "HIDLOOM_OUTER_GROUP_POLLS": "100",
        "HIDLOOM_OUTER_STAGE_POLLS": "20",
        "HIDLOOM_OUTER_TERM_POLLS": "10",
        "HIDLOOM_OUTER_KILL_POLLS": "20",
        "HIDLOOM_STUB_LEAVE_CHILD": "1" if mode == "residual-unbind" else "0",
    }
    process = subprocess.Popen(
        ["dash", str(hook)],
        cwd=root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    pidfds: list[int] = []
    launcher_pid: int | None = None
    try:
        pid_paths = (record / "launcher.pid", record / "child.pid")
        deadline = time.monotonic() + 3
        while not all(path.exists() for path in pid_paths):
            assert process.poll() is None, process.communicate()
            assert time.monotonic() < deadline
            time.sleep(0.002)
        launcher_pid = int(pid_paths[0].read_text(encoding="ascii"))
        pids = (launcher_pid, int(pid_paths[1].read_text(encoding="ascii")))
        pidfds = [os.pidfd_open(pid, 0) for pid in pids]
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 0, (stdout, stderr)
        for pidfd in pidfds:
            poller = select.poll()
            poller.register(pidfd, select.POLLIN)
            assert poller.poll(1000), "outer hook left a fixture process alive"

        cleanup_state = (live / "cleanup.state").read_text(encoding="ascii").strip()
        outer_state = (live / "outer-cleanup.state").read_text(encoding="ascii").strip()
        assert cleanup_state == outer_state
        assert not (live / "chain-ready").exists()
        state = (official / "e3-input.state").read_text(encoding="ascii").strip()
        assert state == f"launcher-failed:{cleanup_state}"
        if mode == "released":
            assert cleanup_state == "released"
            assert hidg0.read_bytes() == bytes.fromhex("010000000000000000")
            assert hidg2.read_bytes() == bytes(8)
            assert udc.read_text(encoding="ascii") == "fixture.udc\n"
            assert (official / "e1-gadget.ready").exists()
            assert not (live / "chain-staged").exists()
        elif mode == "residual-unbind":
            assert cleanup_state == "unbound"
            assert hidg0.read_bytes() == b"stale-main"
            assert hidg2.read_bytes() == b"stale-us"
            assert udc.read_text(encoding="ascii").strip() == ""
            assert (live / "gadget-fallback-unbound").exists()
            assert not (official / "e1-gadget.ready").exists()
            assert not (official / "gadget-bound.json").exists()
            assert not (live / "chain-staged").exists()
        else:
            assert cleanup_state == "unsafe-release-and-unbind-failed"
            assert (live / "chain-staged").exists()
            assert (official / "e1-gadget.ready").exists()
            assert (official / "gadget-bound.json").exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
        if launcher_pid is not None:
            try:
                os.killpg(launcher_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for pidfd in pidfds:
            os.close(pidfd)


def prepare_outer_hook_handshake_fixture(root: Path) -> dict[str, Path]:
    real_root = root / "root"
    device = real_root / "dev"
    live = device / "hidloom-early"
    source = root / "source"
    official = root / "run"
    record = root / "record"
    gadget = root / "configfs/cqa02303v5"
    for path in (device, source, official, record, gadget):
        path.mkdir(parents=True, mode=0o700)
    (device / "gpiomem").touch()
    (official / "e1-gadget.ready").touch()
    (official / "gadget-bound.json").write_text("{}\n", encoding="utf-8")
    (source / "hidloom-early-input-launch").write_text(
        OUTER_HOOK_STUB_LAUNCHER, encoding="utf-8"
    )
    for name in ("hidloom-hidd", "hidloom-outputd", "hidloom-logicd-core", "matrixd"):
        (source / name).write_text("fixture executable\n", encoding="utf-8")
    for name in ("keymap.json", "keycodes.json", "config.json", "matrixd.json"):
        (source / name).write_text("{}\n", encoding="utf-8")
    delayed_setsid = root / "delayed-setsid"
    delayed_setsid.write_text(OUTER_HOOK_DELAYED_SETSID, encoding="utf-8")
    delayed_setsid.chmod(0o700)
    hidg0 = device / "hidg0"
    hidg2 = device / "hidg2"
    hidg0.write_bytes(b"stale-main")
    hidg2.write_bytes(b"stale-us")
    udc = gadget / "UDC"
    udc.write_text("fixture.udc\n", encoding="ascii")
    return {
        "real_root": real_root,
        "live": live,
        "source": source,
        "official": official,
        "record": record,
        "delayed_setsid": delayed_setsid,
        "hidg0": hidg0,
        "hidg2": hidg2,
        "udc": udc,
    }


def outer_hook_pgid_handshake_fixture(root: Path) -> None:
    """Prove the bounded PGID handshake closes the post-fork setsid race."""
    legacy_root = root / "legacy"
    legacy = prepare_outer_hook_handshake_fixture(legacy_root)
    legacy_hook = legacy_root / "hidloom-early-input"
    legacy_hook.write_bytes(outer_hook_host_bytes(remove_group_handshake=True))
    legacy_hook.chmod(0o700)
    legacy_environment = {
        **os.environ,
        "rootmnt": str(legacy["real_root"]),
        "HIDLOOM_OUTER_RUN": str(legacy["official"]),
        "HIDLOOM_OUTER_SOURCE": str(legacy["source"]),
        "HIDLOOM_OUTER_UDC": str(legacy["udc"]),
        "HIDLOOM_OUTER_RECORD": str(legacy["record"]),
        "HIDLOOM_OUTER_LIVE": str(legacy["live"]),
        "HIDLOOM_OUTER_SETSID": str(legacy["delayed_setsid"]),
        "HIDLOOM_OUTER_SETSID_DELAY": "0.30",
        "HIDLOOM_OUTER_POST_SPAWN_DELAY": "0.10",
        "HIDLOOM_OUTER_STAGE_POLLS": "20",
        "HIDLOOM_OUTER_TERM_POLLS": "10",
        "HIDLOOM_OUTER_KILL_POLLS": "20",
        "HIDLOOM_STUB_STAGE": "1",
    }
    legacy_process = subprocess.Popen(
        ["dash", str(legacy_hook)],
        cwd=legacy_root,
        env=legacy_environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    legacy_spawn_pidfd: int | None = None
    legacy_spawn_pid: int | None = None
    try:
        spawn_path = legacy["record"] / "spawn.pid"
        deadline = time.monotonic() + 2
        while not spawn_path.exists():
            assert legacy_process.poll() is None, legacy_process.communicate()
            assert time.monotonic() < deadline
            time.sleep(0.002)
        legacy_spawn_pid = int(spawn_path.read_text(encoding="ascii"))
        legacy_spawn_pidfd = os.pidfd_open(legacy_spawn_pid, 0)
        stdout, stderr = legacy_process.communicate(timeout=5)
        assert legacy_process.returncode == 0, (stdout, stderr)
        poller = select.poll()
        poller.register(legacy_spawn_pidfd, select.POLLIN)
        assert poller.poll(1000), "legacy delayed setsid wrapper survived cleanup"
        assert not (legacy["record"] / "launcher.pid").exists()
        assert not (legacy["record"] / "child.pid").exists()
        assert not (legacy["live"] / "chain-staged").exists()
        assert (legacy["live"] / "cleanup.state").read_text(
            encoding="ascii"
        ).strip() == "released"
        assert (legacy["official"] / "e3-input.state").read_text(
            encoding="ascii"
        ).strip() == "launcher-failed:released"
        assert legacy["hidg0"].read_bytes() == bytes.fromhex("010000000000000000")
        assert legacy["hidg2"].read_bytes() == bytes(8)
        assert legacy["udc"].read_text(encoding="ascii") == "fixture.udc\n"
    finally:
        if legacy_process.poll() is None:
            legacy_process.kill()
            legacy_process.wait(timeout=2)
        if legacy_spawn_pid is not None:
            try:
                os.killpg(legacy_spawn_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if legacy_spawn_pidfd is not None:
            os.close(legacy_spawn_pidfd)

    timeout_root = root / "group-timeout"
    timeout_fixture = prepare_outer_hook_handshake_fixture(timeout_root)
    timeout_hook = timeout_root / "hidloom-early-input"
    timeout_hook.write_bytes(outer_hook_host_bytes())
    timeout_hook.chmod(0o700)
    timeout_environment = {
        **os.environ,
        "rootmnt": str(timeout_fixture["real_root"]),
        "HIDLOOM_OUTER_RUN": str(timeout_fixture["official"]),
        "HIDLOOM_OUTER_SOURCE": str(timeout_fixture["source"]),
        "HIDLOOM_OUTER_UDC": str(timeout_fixture["udc"]),
        "HIDLOOM_OUTER_RECORD": str(timeout_fixture["record"]),
        "HIDLOOM_OUTER_LIVE": str(timeout_fixture["live"]),
        "HIDLOOM_OUTER_SETSID": str(timeout_fixture["delayed_setsid"]),
        "HIDLOOM_OUTER_SETSID_DELAY": "0.50",
        "HIDLOOM_OUTER_SETSID_IGNORE_TERM": "1",
        "HIDLOOM_OUTER_POST_SPAWN_DELAY": "0.05",
        "HIDLOOM_OUTER_GROUP_POLLS": "5",
        "HIDLOOM_OUTER_STAGE_POLLS": "20",
        "HIDLOOM_OUTER_TERM_POLLS": "5",
        "HIDLOOM_OUTER_KILL_POLLS": "20",
        "HIDLOOM_STUB_STAGE": "1",
    }
    timeout_process = subprocess.Popen(
        ["dash", str(timeout_hook)],
        cwd=timeout_root,
        env=timeout_environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    timeout_spawn_pidfd: int | None = None
    timeout_spawn_pid: int | None = None
    try:
        spawn_path = timeout_fixture["record"] / "spawn.pid"
        deadline = time.monotonic() + 2
        while not spawn_path.exists():
            assert timeout_process.poll() is None, timeout_process.communicate()
            assert time.monotonic() < deadline
            time.sleep(0.002)
        timeout_spawn_pid = int(spawn_path.read_text(encoding="ascii"))
        timeout_spawn_pidfd = os.pidfd_open(timeout_spawn_pid, 0)
        stdout, stderr = timeout_process.communicate(timeout=5)
        assert timeout_process.returncode == 0, (stdout, stderr)
        poller = select.poll()
        poller.register(timeout_spawn_pidfd, select.POLLIN)
        assert poller.poll(1000), "TERM-ignoring pre-PGID launcher survived SIGKILL"
        assert not (timeout_fixture["record"] / "launcher.pid").exists()
        assert not (timeout_fixture["record"] / "child.pid").exists()
        assert (timeout_fixture["live"] / "cleanup.state").read_text(
            encoding="ascii"
        ).strip() == "unbound"
        assert (timeout_fixture["live"] / "outer-cleanup.state").read_text(
            encoding="ascii"
        ).strip() == "unbound"
        assert (timeout_fixture["official"] / "e3-input.state").read_text(
            encoding="ascii"
        ).strip() == "launcher-failed:unbound"
        assert (timeout_fixture["live"] / "gadget-fallback-unbound").exists()
        assert not (timeout_fixture["live"] / "chain-staged").exists()
        assert not (timeout_fixture["official"] / "e1-gadget.ready").exists()
        assert not (timeout_fixture["official"] / "gadget-bound.json").exists()
        assert timeout_fixture["hidg0"].read_bytes() == b"stale-main"
        assert timeout_fixture["hidg2"].read_bytes() == b"stale-us"
        assert timeout_fixture["udc"].read_text(encoding="ascii").strip() == ""
        time.sleep(0.55)
        assert not (timeout_fixture["record"] / "launcher.pid").exists()
        assert not (timeout_fixture["record"] / "child.pid").exists()
    finally:
        if timeout_process.poll() is None:
            timeout_process.kill()
            timeout_process.wait(timeout=2)
        if timeout_spawn_pid is not None:
            try:
                os.killpg(timeout_spawn_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if timeout_spawn_pidfd is not None:
            os.close(timeout_spawn_pidfd)

    fixed_root = root / "fixed"
    fixed = prepare_outer_hook_handshake_fixture(fixed_root)
    fixed_hook = fixed_root / "hidloom-early-input"
    fixed_hook.write_bytes(outer_hook_host_bytes())
    fixed_hook.chmod(0o700)
    fixed_environment = {
        **os.environ,
        "rootmnt": str(fixed["real_root"]),
        "HIDLOOM_OUTER_RUN": str(fixed["official"]),
        "HIDLOOM_OUTER_SOURCE": str(fixed["source"]),
        "HIDLOOM_OUTER_UDC": str(fixed["udc"]),
        "HIDLOOM_OUTER_RECORD": str(fixed["record"]),
        "HIDLOOM_OUTER_LIVE": str(fixed["live"]),
        "HIDLOOM_OUTER_SETSID": str(fixed["delayed_setsid"]),
        "HIDLOOM_OUTER_SETSID_DELAY": "0.05",
        "HIDLOOM_OUTER_GROUP_POLLS": "100",
        "HIDLOOM_OUTER_STAGE_POLLS": "100",
        "HIDLOOM_OUTER_TERM_POLLS": "10",
        "HIDLOOM_OUTER_KILL_POLLS": "20",
        "HIDLOOM_STUB_STAGE": "1",
    }
    fixed_process = subprocess.Popen(
        ["dash", str(fixed_hook)],
        cwd=fixed_root,
        env=fixed_environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    fixed_pidfds: list[int] = []
    fixed_launcher_pid: int | None = None
    try:
        pid_paths = (
            fixed["record"] / "launcher.pid",
            fixed["record"] / "child.pid",
        )
        deadline = time.monotonic() + 3
        while not all(path.exists() for path in pid_paths):
            assert fixed_process.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.002)
        fixed_launcher_pid = int(pid_paths[0].read_text(encoding="ascii"))
        fixed_pidfds = [
            os.pidfd_open(int(path.read_text(encoding="ascii")), 0)
            for path in pid_paths
        ]
        assert fixed_process.wait(timeout=5) == 0
        assert (fixed["official"] / "e3-input.state").read_text(
            encoding="ascii"
        ).strip() == "chain-staged-before-run-move"
        assert (fixed["live"] / "chain-staged").exists()
        assert not (fixed["live"] / "cleanup.state").exists()
        assert not (fixed["live"] / "outer-cleanup.state").exists()
        assert fixed["hidg0"].read_bytes() == b"stale-main"
        assert fixed["hidg2"].read_bytes() == b"stale-us"
        assert fixed["udc"].read_text(encoding="ascii") == "fixture.udc\n"
        for pidfd in fixed_pidfds:
            poller = select.poll()
            poller.register(pidfd, select.POLLIN)
            assert not poller.poll(0), "staged fixture process exited prematurely"
    finally:
        if fixed_process.poll() is None:
            fixed_process.kill()
            fixed_process.wait(timeout=2)
        if fixed_launcher_pid is not None:
            try:
                os.killpg(fixed_launcher_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for pidfd in fixed_pidfds:
            poller = select.poll()
            poller.register(pidfd, select.POLLIN)
            assert poller.poll(1000), "fixture teardown left a staged process alive"
            os.close(pidfd)


def main() -> None:
    commands = e1_fixture.require_commands()
    compiler = commands["aarch64-linux-gnu-gcc"]
    descriptors = e1_fixture.production_descriptors()

    with tempfile.TemporaryDirectory(prefix="hidloom-e3-initramfs-test-") as temporary:
        fixture = Path(temporary)
        helper = e1_fixture.compile_helper(
            commands, fixture, "gadget-helper", descriptors, static=True
        )
        libcomposite = e1_fixture.compile_module(
            commands,
            fixture,
            "libcomposite",
            kernel_release=e1_fixture.KERNEL_RELEASE,
            depends="",
        )
        usb_f_hid = e1_fixture.compile_module(
            commands,
            fixture,
            "usb_f_hid",
            kernel_release=e1_fixture.KERNEL_RELEASE,
            depends="libcomposite",
        )
        gpiomem = e1_fixture.compile_module(
            commands,
            fixture,
            "raspberrypi_gpiomem",
            kernel_release=e1_fixture.KERNEL_RELEASE,
            depends="",
        )
        identity = fixture / "usb-identity.env"
        identity.write_text(e1_fixture.IDENTITY_TEXT, encoding="utf-8")
        base = fixture / "base-initramfs8"
        base.write_bytes(
            e1_fixture.base_bytes(
                commands, main_extra=native_base_prerequisite_entries()
            )
        )

        native: dict[str, Path] = {
            name: compile_binary(compiler, fixture, f"native-{name}", static=True)
            for name in ("hidd", "outputd", "logicd_core", "matrixd")
        }
        native["gpiomem"] = gpiomem
        native["keymap"] = fixture / "keymap.json"
        native["keycodes"] = fixture / "keycodes.json"
        native["logicd_config"] = fixture / "config.json"
        native["matrixd_config"] = fixture / "matrixd.json"
        write_json(native["keymap"], {"layers": [{"0,0": "KC_A"}]})
        write_json(native["keycodes"], {"KC_A": {"type": "keyboard", "code": 4}})
        write_json(native["logicd_config"], {"schema": "hidloom.fixture.logicd.v1"})
        write_json(
            native["matrixd_config"],
            {
                "ipc": {
                    "socket_path": "/dev/hidloom-early/matrix-events.sock",
                    "tap_socket_path": "none",
                },
                "matrix": {"gpio_enabled": True},
            },
        )

        # The optional extension is fail-closed: there is no partial E3 image.
        complete_command = native_build_command(
            base=base,
            output=fixture / "all-or-none" / "initramfs-hidloom-e3",
            manifest=fixture / "all-or-none" / "early-image.json",
            helper=helper,
            libcomposite=libcomposite,
            usb_f_hid=usb_f_hid,
            identity=identity,
            native=native,
        )
        option_names = [
            "--hidd",
            "--outputd",
            "--logicd-core",
            "--matrixd",
            "--keymap",
            "--keycodes",
            "--logicd-config",
            "--matrixd-config",
            "--gpiomem",
        ]
        for option in option_names:
            expect_failure(without_option(complete_command, option), "all-or-none")

        # The E3 hook/launcher command inventory is extracted from the pinned
        # templates and every resolved base member must be executable.  A
        # missing utility is fatal for native mode, but does not alter E1.
        assert early.native_template_command_paths() == (
            early.NATIVE_BASE_REQUIRED_COMMAND_PATHS
        )
        missing_prerequisite_base = fixture / "base-missing-setsid"
        missing_prerequisite_base.write_bytes(
            e1_fixture.base_bytes(
                commands,
                main_extra=native_base_prerequisite_entries(
                    omit="/usr/bin/setsid"
                ),
            )
        )
        missing_result = run(
            native_build_command(
                base=missing_prerequisite_base,
                output=fixture / "missing-prerequisite" / "initramfs-hidloom-e3",
                manifest=fixture / "missing-prerequisite" / "early-image.json",
                helper=helper,
                libcomposite=libcomposite,
                usb_f_hid=usb_f_hid,
                identity=identity,
                native=native,
            ),
            check=False,
        )
        assert missing_result.returncode != 0
        missing_output = missing_result.stdout + missing_result.stderr
        assert "native base prerequisites failed" in missing_output.lower()
        assert "/usr/bin/setsid" in missing_output

        builds: list[tuple[Path, Path]] = []
        for number in (1, 2):
            image = fixture / f"build-{number}" / "initramfs-hidloom-e3"
            manifest = fixture / f"build-{number}" / "early-image.json"
            result = json.loads(
                run(
                    native_build_command(
                        base=base,
                        output=image,
                        manifest=manifest,
                        helper=helper,
                        libcomposite=libcomposite,
                        usb_f_hid=usb_f_hid,
                        identity=identity,
                        native=native,
                    )
                ).stdout
            )
            assert result["status"] == "pass"
            builds.append((image, manifest))

        (image, manifest_path), (second_image, second_manifest_path) = builds
        assert image.read_bytes() == second_image.read_bytes()
        assert manifest_path.read_bytes() == second_manifest_path.read_bytes()
        deep = json.loads(
            run(e1_fixture.verify_command(base, image, manifest_path)).stdout
        )
        assert deep["status"] == "pass"

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        image_data = image.read_bytes()
        boundary = manifest["base"]["zstd_offset"]
        overlay_end = boundary + manifest["overlay"]["size"]
        records = early.overlay_records(
            image_data[boundary:overlay_end], early.ALL_FILE_MODES
        )
        assert set(records) == early.NATIVE_EXPECTED_PATHS
        assert set(manifest["modules"]) == {
            "libcomposite",
            "usb_f_hid",
            "raspberrypi_gpiomem",
        }
        assert manifest["modules"]["raspberrypi_gpiomem"]["depends"] == []
        contract = manifest["native_input"]
        assert contract["schema"] == early.NATIVE_INPUT_SCHEMA
        assert contract["start_order"] == ["hidd", "outputd", "logicd_core", "matrixd"]
        assert contract["startup_release"] == {
            "main_report_hex": "010000000000000000",
            "main_report_size": 9,
            "us_sub_report_hex": "0000000000000000",
            "us_sub_report_size": 8,
        }
        assert contract["handoff_release"] == {
            "keyboard_report_dedup": False,
            "required_endpoint_zero_writes": ["main", "us_sub"],
        }
        assert manifest["runtime_contract"]["native_input"] == contract
        assert b"export USBD_KEYBOARD_REPORT_DEDUP=0" in records[
            "usr/lib/hidloom/early/hidloom-early-input-launch"
        ]["data"]
        for key, filename in {
            "hidd": "hidloom-hidd",
            "outputd": "hidloom-outputd",
            "logicd_core": "hidloom-logicd-core",
            "matrixd": "matrixd",
        }.items():
            payload = records[f"usr/lib/hidloom/early/{filename}"]["data"]
            early.verify_arm64_static_elf(payload, filename)
            assert contract["binaries"][key]["sha256"] == hashlib.sha256(payload).hexdigest()
            assert contract["binaries"][key]["static"] is True
        for key, filename in {
            "keymap": "keymap.json",
            "keycodes": "keycodes.json",
            "logicd_config": "config.json",
            "matrixd_config": "matrixd.json",
        }.items():
            payload = records[f"usr/lib/hidloom/early/{filename}"]["data"]
            assert isinstance(json.loads(payload), dict)
            assert contract["configs"][key]["sha256"] == hashlib.sha256(payload).hexdigest()
        early.verify_early_matrix_config(
            records["usr/lib/hidloom/early/matrixd.json"]["data"]
        )
        for shell_path in (
            "scripts/init-premount/hidloom-early-gadget",
            "scripts/init-bottom/hidloom-early-input",
            "usr/lib/hidloom/early/hidloom-early-input-launch",
        ):
            result = subprocess.run(
                ["dash", "-n"],
                input=records[shell_path]["data"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            assert result.returncode == 0, (shell_path, result.stderr.decode())
        launcher_failure_cleanup_fixture(
            fixture / "launcher-cleanup-release", endpoint_failure=False
        )
        launcher_failure_cleanup_fixture(
            fixture / "launcher-cleanup-unbind", endpoint_failure=True
        )
        outer_hook_pgid_handshake_fixture(fixture / "outer-hook-pgid-handshake")
        outer_hook_failure_cleanup_fixture(
            fixture / "outer-hook-cleanup-release", mode="released"
        )
        outer_hook_failure_cleanup_fixture(
            fixture / "outer-hook-cleanup-residual", mode="residual-unbind"
        )
        outer_hook_failure_cleanup_fixture(
            fixture / "outer-hook-cleanup-unsafe", mode="unsafe"
        )

        # Preserve valid outer hashes so verification reaches the embedded-file guard.
        tampered_image = fixture / "tampered-initramfs-hidloom-e3"
        tampered_manifest = fixture / "tampered-early-image.json"
        tampered_data = bytearray(image_data)
        embedded_hidd = records["usr/lib/hidloom/early/hidloom-hidd"]["data"]
        hidd_offset = tampered_data.find(embedded_hidd, boundary, overlay_end)
        assert hidd_offset >= 0
        tampered_data[hidd_offset + len(embedded_hidd) - 17] ^= 1
        tampered_image.write_bytes(tampered_data)
        tampered = json.loads(json.dumps(manifest))
        update_outer_hashes(tampered, tampered_image, bytes(tampered_data))
        write_json(tampered_manifest, tampered)
        expect_failure(
            e1_fixture.verify_command(
                base, tampered_image, tampered_manifest, deep=False
            ),
            "embedded file hash",
        )

        contract_manifest = fixture / "tampered-native-contract.json"
        contract_tamper = json.loads(json.dumps(manifest))
        contract_tamper["native_input"]["start_order"] = [
            "outputd",
            "hidd",
            "logicd_core",
            "matrixd",
        ]
        write_json(contract_manifest, contract_tamper)
        expect_failure(
            e1_fixture.verify_command(base, image, contract_manifest, deep=False),
            "native input manifest contract",
        )

        # Every executable and the GPIO module are independently architecture-bound.
        dynamic_hidd = compile_binary(
            compiler, fixture, "native-hidd-dynamic", static=False
        )
        dynamic_native = {**native, "hidd": dynamic_hidd}
        expect_failure(
            native_build_command(
                base=base,
                output=fixture / "dynamic" / "initramfs-hidloom-e3",
                manifest=fixture / "dynamic" / "early-image.json",
                helper=helper,
                libcomposite=libcomposite,
                usb_f_hid=usb_f_hid,
                identity=identity,
                native=dynamic_native,
            ),
            "dynamically linked",
        )
        wrong_arch_matrix = fixture / "native-matrixd-wrong-arch"
        wrong_arch_data = bytearray(native["matrixd"].read_bytes())
        struct.pack_into("<H", wrong_arch_data, 18, 62)
        wrong_arch_matrix.write_bytes(wrong_arch_data)
        wrong_arch_native = {**native, "matrixd": wrong_arch_matrix}
        expect_failure(
            native_build_command(
                base=base,
                output=fixture / "wrong-arch" / "initramfs-hidloom-e3",
                manifest=fixture / "wrong-arch" / "early-image.json",
                helper=helper,
                libcomposite=libcomposite,
                usb_f_hid=usb_f_hid,
                identity=identity,
                native=wrong_arch_native,
            ),
            "ARM64",
        )
        wrong_arch_gpiomem = fixture / "raspberrypi_gpiomem-wrong-arch.ko"
        wrong_module_data = bytearray(gpiomem.read_bytes())
        struct.pack_into("<H", wrong_module_data, 18, 62)
        wrong_arch_gpiomem.write_bytes(wrong_module_data)
        wrong_module_native = {**native, "gpiomem": wrong_arch_gpiomem}
        expect_failure(
            native_build_command(
                base=base,
                output=fixture / "wrong-module" / "initramfs-hidloom-e3",
                manifest=fixture / "wrong-module" / "early-image.json",
                helper=helper,
                libcomposite=libcomposite,
                usb_f_hid=usb_f_hid,
                identity=identity,
                native=wrong_module_native,
            ),
            "ARM64",
        )

        bad_matrix = fixture / "matrixd-wrong-socket.json"
        write_json(
            bad_matrix,
            {
                "ipc": {
                    "socket_path": "/tmp/matrix-events.sock",
                    "tap_socket_path": "none",
                },
                "matrix": {"gpio_enabled": True},
            },
        )
        bad_matrix_native = {**native, "matrixd_config": bad_matrix}
        expect_failure(
            native_build_command(
                base=base,
                output=fixture / "wrong-socket" / "initramfs-hidloom-e3",
                manifest=fixture / "wrong-socket" / "early-image.json",
                helper=helper,
                libcomposite=libcomposite,
                usb_f_hid=usb_f_hid,
                identity=identity,
                native=bad_matrix_native,
            ),
            "pinned early matrix socket",
        )

        # The original E1-only CLI remains supported and omits every native payload.
        e1_image = fixture / "e1-backward" / "initramfs-hidloom-e1"
        e1_manifest_path = fixture / "e1-backward" / "early-image.json"
        run(
            e1_fixture.build_command(
                base=missing_prerequisite_base,
                output=e1_image,
                manifest=e1_manifest_path,
                helper=helper,
                libcomposite=libcomposite,
                usb_f_hid=usb_f_hid,
                identity=identity,
            )
        )
        e1_manifest = json.loads(e1_manifest_path.read_text(encoding="utf-8"))
        assert "native_input" not in e1_manifest
        assert "raspberrypi_gpiomem" not in e1_manifest["modules"]
        e1_boundary = e1_manifest["base"]["zstd_offset"]
        e1_overlay_end = e1_boundary + e1_manifest["overlay"]["size"]
        e1_records = early.overlay_records(
            e1_image.read_bytes()[e1_boundary:e1_overlay_end]
        )
        assert set(e1_records) == early.BASE_EXPECTED_PATHS
        assert not (set(e1_records) & set(early.NATIVE_FILE_MODES))
        assert json.loads(
            run(
                e1_fixture.verify_command(
                    missing_prerequisite_base,
                    e1_image,
                    e1_manifest_path,
                    deep=False,
                )
            ).stdout
        )["status"] == "pass"

    print("ok: Raspberry Pi OS E3 native initramfs extension")


if __name__ == "__main__":
    main()
