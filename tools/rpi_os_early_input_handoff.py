#!/usr/bin/env python3
"""Release and retire the E3 early input chain before normal systemd starts.

The helper has two deliberately separate phases:

``prepare``
    Authenticate the initramfs contract and every early daemon identity, stop
    matrix input, release all logical state, prove that a zero report reached
    both keyboard endpoints, and retire the remaining early daemons.

``finalize``
    After the normal input services have started, prove that their status is
    ready and publish a separate completion record.

The successful handoff path never opens configfs or writes a UDC attribute.
Only fail-closed recovery may verified-unbind the existing gadget when exact
terminal reports cannot be proven.  Normal gadget adoption remains the
responsibility of ``rpi_os_early_gadget_adopt.py`` and its service wrapper.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import stat
import sys
import time
from typing import Any, Callable


EXIT_UNSAFE = 78
READY_SCHEMA = "hidloom.early-input.v1"
CONTRACT_SCHEMA = "hidloom.rpi-os-early-runtime-contract.e1.v1"
NATIVE_SCHEMA = "hidloom.rpi-os-early-native-input.e3.v1"
PREPARE_SCHEMA = "hidloom.rpi-os-early-input-handoff.prepare.v1"
COMPLETE_SCHEMA = "hidloom.rpi-os-early-input-handoff.complete.v1"
FAILURE_SCHEMA = "hidloom.rpi-os-early-input-handoff.failure.v1"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
PID_RECORD_RE = re.compile(r"([1-9][0-9]*) ([1-9][0-9]*) ([1-9][0-9]*) ([1-9][0-9]*)\n?\Z")
LABELS = ("hidd", "outputd", "logicd-core", "matrixd")
CONTRACT_BINARY_KEYS = {
    "hidd": "hidd",
    "outputd": "outputd",
    "logicd-core": "logicd_core",
    "matrixd": "matrixd",
}
HIDD_ERROR_COUNTERS = ("invalid_frames", "write_errors", "dropped_reports")
OUTPUTD_ERROR_COUNTERS = ("invalid_frames", "forward_errors", "release_errors")


class HandoffError(RuntimeError):
    """The handoff cannot be proven safe."""


class HandoffArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise HandoffError(f"command line: {message}")


def strict_json_loads(data: bytes | str, label: str) -> object:
    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise HandoffError(f"{label} contains duplicate key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise HandoffError(f"{label} contains non-finite number: {value}")

    return json.loads(data, object_pairs_hook=object_pairs, parse_constant=reject_constant)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HandoffError(f"{label} must be an object")
    return value


def require_bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise HandoffError(f"{label} must be a boolean")
    return value


def require_nonnegative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise HandoffError(f"{label} must be a non-negative integer")
    return value


def require_positive_int(value: object, label: str) -> int:
    result = require_nonnegative_int(value, label)
    if result == 0:
        raise HandoffError(f"{label} must be positive")
    return result


def require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise HandoffError(f"{label} must be a non-empty string")
    return value


def require_sha256(value: object, label: str) -> str:
    text = require_string(value, label)
    if not SHA256_RE.fullmatch(text):
        raise HandoffError(f"{label} is not a lowercase SHA-256")
    return text


def require_secure_regular(path: Path, label: str, owner_uid: int) -> os.stat_result:
    try:
        details = path.lstat()
    except OSError as exc:
        raise HandoffError(f"cannot stat {label}: {path}: {exc}") from exc
    if not stat.S_ISREG(details.st_mode):
        raise HandoffError(f"{label} is not a regular file: {path}")
    if details.st_uid != owner_uid:
        raise HandoffError(
            f"{label} owner mismatch: {path}: {details.st_uid} != {owner_uid}"
        )
    if details.st_mode & 0o022:
        raise HandoffError(f"{label} is group/world writable: {path}")
    return details


def read_secure_bytes(
    path: Path, label: str, owner_uid: int, *, max_bytes: int = 8 * 1024 * 1024
) -> bytes:
    details = require_secure_regular(path, label, owner_uid)
    if details.st_size > max_bytes:
        raise HandoffError(f"{label} is unexpectedly large: {details.st_size} bytes")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise HandoffError(f"cannot read {label}: {path}: {exc}") from exc
    # Detect a replacement between lstat and read.  All producers publish by
    # rename, so callers can retry status files but contract files must be stable.
    after = require_secure_regular(path, label, owner_uid)
    if (details.st_dev, details.st_ino) != (after.st_dev, after.st_ino):
        raise HandoffError(f"{label} changed while being read: {path}")
    return data


def read_secure_json(path: Path, label: str, owner_uid: int) -> tuple[dict[str, Any], bytes]:
    data = read_secure_bytes(path, label, owner_uid)
    try:
        value = strict_json_loads(data, label)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise HandoffError(f"cannot parse {label}: {path}: {exc}") from exc
    return require_object(value, label), data


def read_status_json(path: Path, label: str, owner_uid: int) -> dict[str, Any]:
    # Daemons atomically replace their status file.  A single inode-race is not
    # an unsafe condition; retry it briefly before surfacing a stable failure.
    last_error: Exception | None = None
    for _ in range(5):
        try:
            return read_secure_json(path, label, owner_uid)[0]
        except HandoffError as exc:
            last_error = exc
            time.sleep(0.005)
    assert last_error is not None
    raise last_error


def ensure_secure_parent(path: Path, owner_uid: int) -> Path:
    try:
        parent = path.parent.resolve(strict=True)
        details = parent.stat()
    except OSError as exc:
        raise HandoffError(f"cannot resolve evidence parent: {path.parent}: {exc}") from exc
    if not stat.S_ISDIR(details.st_mode):
        raise HandoffError(f"evidence parent is not a directory: {parent}")
    if details.st_uid != owner_uid:
        raise HandoffError(
            f"evidence parent owner mismatch: {parent}: {details.st_uid} != {owner_uid}"
        )
    if details.st_mode & 0o022:
        raise HandoffError(f"evidence parent is group/world writable: {parent}")
    return parent


def write_atomic_exclusive(path: Path, payload: dict[str, Any], owner_uid: int) -> bytes:
    """Publish complete 0600 JSON with no overwrite window."""
    parent = ensure_secure_parent(path, owner_uid)
    destination = parent / path.name
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    temporary = parent / f".{path.name}.tmp.{os.getpid()}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd: int | None = None
    try:
        fd = os.open(temporary, flags, 0o600)
        os.fchmod(fd, 0o600)
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise HandoffError(f"short write while creating evidence: {temporary}")
            view = view[written:]
        os.fsync(fd)
        os.close(fd)
        fd = None
        # link(2) publishes the already complete inode and refuses an existing
        # destination.  Unlike rename(2), it cannot overwrite prior evidence.
        os.link(temporary, destination, follow_symlinks=False)
        temporary.unlink()
        dir_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except FileExistsError as exc:
        raise HandoffError(f"refusing to overwrite existing evidence: {destination}") from exc
    except OSError as exc:
        raise HandoffError(f"cannot atomically publish evidence {destination}: {exc}") from exc
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
    return data


def canonical_existing(path: Path, label: str) -> Path:
    try:
        return path.resolve(strict=True)
    except OSError as exc:
        raise HandoffError(f"cannot resolve {label}: {path}: {exc}") from exc


def wait_for_ready(args: argparse.Namespace) -> bool:
    if args.ready.exists() or args.ready.is_symlink():
        return True
    chain_ready = args.discovery_live_root / "chain-ready"
    chain_staged = args.discovery_live_root / "chain-staged"
    if (
        not chain_ready.exists()
        and not chain_ready.is_symlink()
        and not chain_staged.exists()
        and not chain_staged.is_symlink()
    ):
        return False
    # Once the init-bottom hook has observed chain-staged it may return and
    # permit /run to move.  systemd must not interpret that short transition as
    # a normal boot and start a second input owner.  Wait for official ready, or
    # for the launcher's authenticated terminal cleanup record.
    cleanup_state = args.discovery_live_root / "cleanup.state"
    deadline = time.monotonic() + args.discovery_timeout
    while time.monotonic() < deadline:
        if args.ready.exists() or args.ready.is_symlink():
            return True
        if cleanup_state.exists() or cleanup_state.is_symlink():
            raw = read_secure_bytes(
                cleanup_state,
                "early launcher cleanup state",
                args.expected_owner_uid,
                max_bytes=128,
            )
            try:
                state = raw.decode("ascii").strip()
            except UnicodeError as exc:
                raise HandoffError("early launcher cleanup state is not ASCII") from exc
            if state in ("released", "unbound"):
                return False
            raise HandoffError(f"early launcher cleanup is unsafe: {state!r}")
        time.sleep(args.poll_interval)
    raise HandoffError(
        f"early chain was staged but official ready or safe cleanup did not appear: {args.ready}"
    )


def proc_stat_starttime(path: Path, label: str) -> int:
    try:
        raw = path.read_text(encoding="ascii")
    except (OSError, UnicodeError) as exc:
        raise HandoffError(f"cannot read {label} process stat: {path}: {exc}") from exc
    closing = raw.rfind(")")
    if closing < 0:
        raise HandoffError(f"malformed {label} process stat: {path}")
    fields = raw[closing + 1 :].strip().split()
    if len(fields) <= 19 or not fields[19].isdigit():
        raise HandoffError(f"malformed {label} process starttime: {path}")
    return int(fields[19])


def proc_effective_uid(path: Path, label: str) -> int:
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError) as exc:
        raise HandoffError(f"cannot read {label} process status: {path}: {exc}") from exc
    for line in lines:
        if line.startswith("Uid:"):
            fields = line.split()
            if len(fields) == 5 and all(field.isdigit() for field in fields[1:]):
                return int(fields[2])
    raise HandoffError(f"malformed {label} process Uid: {path}")


def read_pid_record(path: Path, label: str, owner_uid: int) -> dict[str, int]:
    raw = read_secure_bytes(path, f"{label} PID record", owner_uid, max_bytes=256)
    try:
        text = raw.decode("ascii")
    except UnicodeError as exc:
        raise HandoffError(f"{label} PID record is not ASCII: {path}") from exc
    match = PID_RECORD_RE.fullmatch(text)
    if match is None:
        raise HandoffError(
            f"{label} PID record must contain pid starttime exe_dev exe_ino: {path}"
        )
    pid, starttime, exe_dev, exe_ino = (int(value) for value in match.groups())
    return {"pid": pid, "starttime": starttime, "exe_dev": exe_dev, "exe_ino": exe_ino}


def verify_process_identity(
    proc_root: Path,
    label: str,
    record: dict[str, int],
    expected_exe: Path,
    owner_uid: int,
) -> dict[str, Any]:
    pid = record["pid"]
    process_root = proc_root / str(pid)
    starttime = proc_stat_starttime(process_root / "stat", label)
    if starttime != record["starttime"]:
        raise HandoffError(
            f"{label} process starttime mismatch: {starttime} != {record['starttime']}"
        )
    effective_uid = proc_effective_uid(process_root / "status", label)
    if effective_uid != owner_uid:
        raise HandoffError(
            f"{label} process effective UID mismatch: {effective_uid} != {owner_uid}"
        )
    exe_link = process_root / "exe"
    try:
        link_details = exe_link.lstat()
        exe_details = exe_link.stat()
        live_exe = exe_link.resolve(strict=True)
    except OSError as exc:
        raise HandoffError(f"cannot authenticate {label} executable: {exe_link}: {exc}") from exc
    if not stat.S_ISLNK(link_details.st_mode) or not stat.S_ISREG(exe_details.st_mode):
        raise HandoffError(f"{label} executable link is unsafe: {exe_link}")
    if (exe_details.st_dev, exe_details.st_ino) != (record["exe_dev"], record["exe_ino"]):
        raise HandoffError(
            f"{label} executable inode mismatch: "
            f"{exe_details.st_dev}:{exe_details.st_ino} != "
            f"{record['exe_dev']}:{record['exe_ino']}"
        )
    canonical_expected = canonical_existing(expected_exe, f"{label} expected executable")
    if live_exe != canonical_expected:
        raise HandoffError(
            f"{label} executable path mismatch: {live_exe} != {canonical_expected}"
        )
    try:
        expected_details = canonical_expected.stat()
    except OSError as exc:
        raise HandoffError(
            f"cannot stat {label} contract executable: {canonical_expected}: {exc}"
        ) from exc
    if not stat.S_ISREG(expected_details.st_mode) or (
        expected_details.st_dev,
        expected_details.st_ino,
    ) != (record["exe_dev"], record["exe_ino"]):
        raise HandoffError(
            f"{label} contract executable no longer names the running inode"
        )
    return {
        **record,
        "exe": str(live_exe),
        "effective_uid": effective_uid,
    }


def pidfd_has_exited(pidfd: int) -> bool:
    """Return whether the process bound to ``pidfd`` has exited.

    A pidfd is pollable once its process exits.  This does not consult the
    numeric PID, so PID reuse cannot turn an exit check into a check of a new
    process.
    """
    import select

    poller = select.poll()
    poller.register(pidfd, select.POLLIN)
    return bool(poller.poll(0))


def open_verified_process_identity(
    proc_root: Path,
    label: str,
    record: dict[str, int],
    expected_exe: Path,
    owner_uid: int,
) -> dict[str, Any]:
    """Bind a pidfd, then authenticate that exact process before any action."""
    if proc_root.resolve() != Path("/proc"):
        raise HandoffError("pidfd authentication requires the real /proc")
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        raise HandoffError("safe handoff requires pidfd_open and pidfd_send_signal")
    try:
        pidfd = os.pidfd_open(record["pid"], 0)
    except OSError as exc:
        raise HandoffError(f"cannot bind {label} process with pidfd_open: {exc}") from exc
    try:
        identity = verify_process_identity(
            proc_root, label, record, expected_exe, owner_uid
        )
        if pidfd_has_exited(pidfd):
            raise HandoffError(f"{label} process exited during pidfd authentication")
    except Exception:
        os.close(pidfd)
        raise
    identity["_pidfd"] = pidfd
    return identity


def verify_live_status_process(
    proc_root: Path,
    payload: dict[str, Any],
    label: str,
    expected_exe: Path,
    owner_uid: int,
) -> dict[str, Any]:
    """Bind and authenticate the live process named by a normal status file."""
    if proc_root.resolve() != Path("/proc") or not hasattr(os, "pidfd_open"):
        raise HandoffError("normal status identity requires pidfd_open and the real /proc")
    pid = require_positive_int(payload.get("pid"), f"{label} status PID")
    try:
        pidfd = os.pidfd_open(pid, 0)
    except OSError as exc:
        raise HandoffError(f"cannot bind {label} status PID with pidfd_open: {exc}") from exc
    try:
        process_root = proc_root / str(pid)
        starttime = proc_stat_starttime(process_root / "stat", label)
        effective_uid = proc_effective_uid(process_root / "status", label)
        if effective_uid != owner_uid:
            raise HandoffError(
                f"{label} status process effective UID mismatch: {effective_uid} != {owner_uid}"
            )
        exe_link = process_root / "exe"
        link_details = exe_link.lstat()
        exe_details = exe_link.stat()
        live_exe = exe_link.resolve(strict=True)
        canonical_expected = canonical_existing(expected_exe, f"{label} expected executable")
        if not stat.S_ISLNK(link_details.st_mode) or not stat.S_ISREG(exe_details.st_mode):
            raise HandoffError(f"{label} status executable link is unsafe")
        if live_exe != canonical_expected:
            raise HandoffError(
                f"{label} status executable path mismatch: {live_exe} != {canonical_expected}"
            )
        expected_details = canonical_expected.stat()
        if (exe_details.st_dev, exe_details.st_ino) != (
            expected_details.st_dev,
            expected_details.st_ino,
        ):
            raise HandoffError(
                f"{label} expected executable no longer names the running inode"
            )
        if pidfd_has_exited(pidfd):
            raise HandoffError(f"{label} status process exited during authentication")
        return {
            "pid": pid,
            "starttime": starttime,
            "exe": str(live_exe),
            "exe_dev": exe_details.st_dev,
            "exe_ino": exe_details.st_ino,
            "effective_uid": effective_uid,
            "_pidfd": pidfd,
        }
    except (HandoffError, OSError) as exc:
        os.close(pidfd)
        if isinstance(exc, HandoffError):
            raise
        raise HandoffError(f"cannot authenticate {label} status process: {exc}") from exc


def close_identity_pidfd(identity: dict[str, Any]) -> None:
    pidfd = identity.pop("_pidfd", None)
    if isinstance(pidfd, int) and not isinstance(pidfd, bool):
        try:
            os.close(pidfd)
        except OSError:
            pass


def public_process_identity(identity: dict[str, Any]) -> dict[str, Any]:
    """Return the authenticated fields that may be persisted as evidence."""
    return {key: value for key, value in identity.items() if not key.startswith("_")}


def identity_is_live(proc_root: Path, identity: dict[str, Any]) -> bool:
    pid = int(identity["pid"])
    try:
        process_root = proc_root / str(pid)
        if proc_stat_starttime(process_root / "stat", "recorded") != int(
            identity["starttime"]
        ):
            return False
        executable = (process_root / "exe").stat()
        return (executable.st_dev, executable.st_ino) == (
            int(identity["exe_dev"]),
            int(identity["exe_ino"]),
        )
    except (HandoffError, OSError, TypeError, ValueError):
        return False


def stop_identity(
    proc_root: Path,
    identity: dict[str, Any],
    label: str,
    timeout: float,
    poll_interval: float,
) -> str:
    if proc_root.resolve() != Path("/proc"):
        raise HandoffError("signals require the real /proc; fixture proc roots are read-only")
    pidfd = identity.get("_pidfd")
    if not isinstance(pidfd, int) or isinstance(pidfd, bool):
        raise HandoffError(f"{label} process has no authenticated pidfd")
    if pidfd_has_exited(pidfd):
        raise HandoffError(f"{label} process disappeared before its ordered stop")
    try:
        signal.pidfd_send_signal(pidfd, signal.SIGTERM)
    except OSError as exc:
        raise HandoffError(f"cannot stop {label} with pidfd SIGTERM: {exc}") from exc
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pidfd_has_exited(pidfd):
            return "SIGTERM"
        time.sleep(poll_interval)
    try:
        signal.pidfd_send_signal(pidfd, signal.SIGKILL)
    except OSError as exc:
        raise HandoffError(f"cannot stop {label} with pidfd SIGKILL: {exc}") from exc
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pidfd_has_exited(pidfd):
            return "SIGKILL"
        time.sleep(poll_interval)
    raise HandoffError(f"{label} retained its pidfd identity after SIGKILL")


def require_socket(path: Path, label: str, owner_uid: int) -> None:
    try:
        details = path.lstat()
    except OSError as exc:
        raise HandoffError(f"cannot stat {label}: {path}: {exc}") from exc
    if not stat.S_ISSOCK(details.st_mode):
        raise HandoffError(f"{label} is not a Unix socket: {path}")
    if details.st_uid != owner_uid:
        raise HandoffError(f"{label} owner mismatch: {details.st_uid} != {owner_uid}")


def require_character_node(path: Path, label: str, owner_uid: int) -> Path:
    try:
        details = path.lstat()
        canonical = path.resolve(strict=True)
    except OSError as exc:
        raise HandoffError(f"cannot stat {label}: {path}: {exc}") from exc
    if not stat.S_ISCHR(details.st_mode):
        raise HandoffError(f"{label} is not a character device: {path}")
    if details.st_uid != owner_uid:
        raise HandoffError(f"{label} owner mismatch: {details.st_uid} != {owner_uid}")
    return canonical


def require_owned_unix_socket(
    proc_root: Path,
    identity: dict[str, Any],
    path: Path,
    label: str,
    owner_uid: int,
    *,
    socket_type: str,
    listening: bool,
) -> None:
    """Prove that one pathname socket is open by the authenticated process.

    A pathname's filesystem inode is not the kernel socket inode exposed by
    ``/proc/net/unix``.  Select exactly one bound datagram or listening stream
    record, allowing the additional same-path records created by accepted
    stream connections, then require its ``socket:[inode]`` fd in the
    pidfd-bound process.  This prevents a root-owned stale or foreign socket
    node from satisfying a topology check.
    """
    require_socket(path, label, owner_uid)
    if proc_root.resolve() != Path("/proc"):
        raise HandoffError("Unix socket ownership requires the real /proc")
    expected_type = {"stream": "0001", "datagram": "0002"}.get(socket_type)
    if expected_type is None:
        raise HandoffError(f"unsupported Unix socket type for {label}: {socket_type}")
    try:
        with (proc_root / "net/unix").open("rb") as stream:
            raw = stream.read(4 * 1024 * 1024 + 1)
    except OSError as exc:
        raise HandoffError(f"cannot read /proc/net/unix for {label}: {exc}") from exc
    if len(raw) > 4 * 1024 * 1024:
        raise HandoffError("/proc/net/unix is unexpectedly large")
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeError as exc:
        raise HandoffError("/proc/net/unix is not ASCII") from exc
    path_records: list[tuple[str, str, str]] = []
    for line in lines[1:]:
        fields = line.split(maxsplit=7)
        if len(fields) == 8 and fields[7] == str(path):
            path_records.append((fields[3], fields[4], fields[6]))
    candidates: list[tuple[str, str, str]] = []
    for flags, actual_type, inode in path_records:
        try:
            accepts_connections = bool(int(flags, 16) & 0x00010000)
        except ValueError as exc:
            raise HandoffError(f"{label} has malformed /proc/net/unix flags") from exc
        if actual_type == expected_type and (not listening or accepts_connections):
            candidates.append((flags, actual_type, inode))
    if len(candidates) != 1:
        raise HandoffError(
            f"{label} must have exactly one matching /proc/net/unix record: "
            f"{path}: found {len(candidates)} among {len(path_records)} path records"
        )
    flags, actual_type, inode = candidates[0]
    if actual_type != expected_type or not inode.isdigit() or int(inode) <= 0:
        raise HandoffError(
            f"{label} has an unexpected /proc/net/unix type/inode: "
            f"type={actual_type} inode={inode}"
        )
    pidfd = identity.get("_pidfd")
    if not isinstance(pidfd, int) or isinstance(pidfd, bool) or pidfd_has_exited(pidfd):
        raise HandoffError(f"{label} owner has no live authenticated pidfd")
    fd_root = proc_root / str(identity["pid"]) / "fd"
    target = f"socket:[{inode}]"
    try:
        entries = list(fd_root.iterdir())
    except OSError as exc:
        raise HandoffError(f"cannot inspect {label} owner fds: {exc}") from exc
    owns_socket = False
    for entry in entries:
        try:
            if os.readlink(entry) == target:
                owns_socket = True
                break
        except OSError:
            continue
    if not owns_socket:
        raise HandoffError(
            f"{label} is not owned by authenticated PID {identity['pid']}: {path}"
        )
    if pidfd_has_exited(pidfd):
        raise HandoffError(f"{label} owner exited during socket authentication")


def require_owned_character_fd(
    proc_root: Path,
    identity: dict[str, Any],
    path: Path,
    label: str,
    owner_uid: int,
) -> Path:
    """Prove that the pidfd-bound process holds the exact character node open."""
    canonical = require_character_node(path, label, owner_uid)
    try:
        expected = path.lstat()
    except OSError as exc:
        raise HandoffError(f"cannot restat {label}: {path}: {exc}") from exc
    pidfd = identity.get("_pidfd")
    if not isinstance(pidfd, int) or isinstance(pidfd, bool) or pidfd_has_exited(pidfd):
        raise HandoffError(f"{label} owner has no live authenticated pidfd")
    fd_root = proc_root / str(identity["pid"]) / "fd"
    try:
        entries = list(fd_root.iterdir())
    except OSError as exc:
        raise HandoffError(f"cannot inspect {label} owner fds: {exc}") from exc
    owns_node = False
    for entry in entries:
        try:
            opened = entry.stat()
        except OSError:
            continue
        if stat.S_ISCHR(opened.st_mode) and (
            opened.st_dev,
            opened.st_ino,
            opened.st_rdev,
        ) == (expected.st_dev, expected.st_ino, expected.st_rdev):
            owns_node = True
            break
    if not owns_node:
        raise HandoffError(
            f"{label} is not open in authenticated PID {identity['pid']}: {path}"
        )
    if pidfd_has_exited(pidfd):
        raise HandoffError(f"{label} owner exited during endpoint authentication")
    return canonical


def control_request(
    path: Path, label: str, owner_uid: int, request: dict[str, Any], timeout: float
) -> dict[str, Any]:
    require_socket(path, label, owner_uid)
    encoded = (json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n").encode()
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect(str(path))
        client.sendall(encoded)
        response = bytearray()
        while b"\n" not in response:
            chunk = client.recv(65536)
            if not chunk:
                break
            response.extend(chunk)
            if len(response) > 1024 * 1024:
                raise HandoffError(f"{label} response is unexpectedly large")
    except OSError as exc:
        raise HandoffError(f"{label} request failed: {exc}") from exc
    finally:
        client.close()
    line = bytes(response).split(b"\n", 1)[0]
    if not line:
        raise HandoffError(f"{label} returned an empty response")
    try:
        value = strict_json_loads(line, f"{label} response")
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise HandoffError(f"{label} returned invalid JSON: {exc}") from exc
    result = require_object(value, f"{label} response")
    if result.get("result") != "ok":
        raise HandoffError(f"{label} rejected release_all: {result}")
    return result


def wait_for(
    description: str,
    timeout: float,
    poll_interval: float,
    probe: Callable[[], dict[str, Any] | None],
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while True:
        try:
            result = probe()
            if result is not None:
                return result
        except (HandoffError, OSError, UnicodeError, json.JSONDecodeError) as exc:
            last_error = exc
        if time.monotonic() >= deadline:
            suffix = f": {last_error}" if last_error is not None else ""
            raise HandoffError(f"timed out waiting for {description}{suffix}")
        time.sleep(poll_interval)


def validate_core_ready(
    payload: dict[str, Any], label: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    if payload.get("schema") != "logicd-core.status.v1" or payload.get("process") is not True:
        raise HandoffError(f"{label} status is not running v1")
    state = require_object(payload.get("state"), f"{label} state")
    for key in ("pressed_matrix", "injected_keys", "pressed_keys", "modifier"):
        require_nonnegative_int(state.get(key), f"{label} state.{key}")
    routing = require_object(payload.get("routing"), f"{label} routing")
    route_state = require_object(routing.get("state"), f"{label} routing.state")
    for key in (
        "us_sub_key_active",
        "primary_key_active",
        "primary_modifier_mirror_active",
        "zenkaku_hankaku_active",
    ):
        require_bool(route_state.get(key), f"{label} routing.state.{key}")
    return state, route_state


def validate_core_zero(payload: dict[str, Any]) -> None:
    state, route_state = validate_core_ready(payload, "early logicd-core")
    for key in ("pressed_matrix", "injected_keys", "pressed_keys", "modifier"):
        if state[key] != 0:
            raise HandoffError(f"early logicd-core state.{key} is not zero")
    for key in (
        "us_sub_key_active",
        "primary_key_active",
        "primary_modifier_mirror_active",
        "zenkaku_hankaku_active",
    ):
        if route_state[key]:
            raise HandoffError(f"early logicd-core routing.state.{key} remains active")


def error_counters(payload: dict[str, Any], keys: tuple[str, ...], label: str) -> dict[str, int]:
    counters = require_object(payload.get("counters"), f"{label} counters")
    return {
        key: require_nonnegative_int(counters.get(key), f"{label} counters.{key}")
        for key in keys
    }


def status_counter(payload: dict[str, Any], key: str, label: str) -> int:
    counters = require_object(payload.get("counters"), f"{label} counters")
    return require_nonnegative_int(counters.get(key), f"{label} counters.{key}")


def require_zero_errors(payload: dict[str, Any], keys: tuple[str, ...], label: str) -> None:
    counters = error_counters(payload, keys, label)
    nonzero = {key: value for key, value in counters.items() if value != 0}
    if nonzero:
        raise HandoffError(f"{label} has pre-existing or new errors: {nonzero}")


def recovery_stop_identity(
    identity: dict[str, Any], label: str, timeout: float, poll_interval: float
) -> dict[str, Any]:
    """Best-effort pidfd stop used only after an ordered handoff action fails."""
    pidfd = identity.get("_pidfd")
    if not isinstance(pidfd, int) or isinstance(pidfd, bool):
        return {"status": "error", "error": "authenticated pidfd unavailable"}
    try:
        if pidfd_has_exited(pidfd):
            return {"status": "already-exited"}
        signal.pidfd_send_signal(pidfd, signal.SIGTERM)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if pidfd_has_exited(pidfd):
                return {"status": "stopped", "signal": "SIGTERM"}
            time.sleep(poll_interval)
        signal.pidfd_send_signal(pidfd, signal.SIGKILL)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if pidfd_has_exited(pidfd):
                return {"status": "stopped", "signal": "SIGKILL"}
            time.sleep(poll_interval)
        return {"status": "error", "error": "pidfd remained live after SIGKILL"}
    except OSError as exc:
        return {"status": "error", "error": f"pidfd signal failed: {exc}"}


def write_terminal_report(path: Path, payload: bytes, owner_uid: int) -> dict[str, Any]:
    """Write one bounded nonblocking report to an authenticated HID character node."""
    try:
        before = path.lstat()
        if not stat.S_ISCHR(before.st_mode):
            raise HandoffError(f"recovery endpoint is not a character device: {path}")
        if before.st_uid != owner_uid:
            raise HandoffError(
                f"recovery endpoint owner mismatch: {path}: {before.st_uid} != {owner_uid}"
            )
        flags = os.O_WRONLY | os.O_NONBLOCK
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            opened = os.fstat(fd)
            if not stat.S_ISCHR(opened.st_mode) or (
                opened.st_dev,
                opened.st_ino,
            ) != (before.st_dev, before.st_ino):
                raise HandoffError(f"recovery endpoint changed while opening: {path}")
            written = os.write(fd, payload)
            if written != len(payload):
                raise HandoffError(
                    f"short recovery endpoint report write: {path}: {written} != {len(payload)}"
                )
        finally:
            os.close(fd)
        return {"status": "written", "path": str(path), "bytes": len(payload)}
    except (HandoffError, OSError) as exc:
        return {"status": "error", "path": str(path), "error": str(exc)}


def verified_udc_unbind(path: Path, owner_uid: int) -> dict[str, Any]:
    """Fail-safe disconnect after terminal HID reports cannot be proven."""
    try:
        before = require_secure_regular(path, "recovery UDC attribute", owner_uid)
        flags = (
            os.O_WRONLY
            | os.O_TRUNC
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        fd = os.open(path, flags)
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise HandoffError("recovery UDC attribute changed while opening")
            if os.write(fd, b"\n") != 1:
                raise HandoffError("short recovery UDC unbind write")
        finally:
            os.close(fd)
        after = require_secure_regular(path, "recovery UDC attribute", owner_uid)
        if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
            raise HandoffError("recovery UDC attribute changed after unbind")
        if path.read_text(encoding="ascii").strip():
            raise HandoffError("recovery UDC attribute remained bound")
        return {"status": "unbound", "path": str(path)}
    except (HandoffError, OSError, UnicodeError) as exc:
        return {"status": "error", "path": str(path), "error": str(exc)}


def recover_after_action_failure(
    args: argparse.Namespace, context: dict[str, Any], original_error: HandoffError
) -> dict[str, Any]:
    identities: dict[str, dict[str, Any]] = context["identities"]
    stops = {
        label: recovery_stop_identity(
            identities[label], label, args.stop_timeout, args.poll_interval
        )
        for label in ("matrixd", "logicd-core", "outputd", "hidd")
    }
    all_dead = all(
        isinstance(identity.get("_pidfd"), int)
        and pidfd_has_exited(int(identity["_pidfd"]))
        for identity in identities.values()
    )
    endpoint_release: dict[str, Any] = {"status": "not-attempted"}
    if all_dead:
        main = write_terminal_report(
            args.recovery_hidg0,
            bytes.fromhex("010000000000000000"),
            args.expected_owner_uid,
        )
        us_sub = write_terminal_report(
            args.recovery_hidg2, bytes(8), args.expected_owner_uid
        )
        endpoint_release = {
            "status": (
                "released"
                if main.get("status") == "written" and us_sub.get("status") == "written"
                else "error"
            ),
            "main": main,
            "us_sub": us_sub,
        }
    udc = {"status": "not-required"}
    if endpoint_release.get("status") != "released":
        udc = verified_udc_unbind(args.recovery_udc, args.expected_owner_uid)
    safe_status = (
        "released"
        if endpoint_release.get("status") == "released"
        else "unbound"
        if udc.get("status") == "unbound"
        else "unsafe"
    )
    payload = {
        "schema": FAILURE_SCHEMA,
        "status": safe_status,
        "created_unix_ns": time.time_ns(),
        "error": str(original_error),
        "ready_sha256": context["ready_sha256"],
        "runtime_contract_sha256": context["contract_sha256"],
        "processes": {
            label: public_process_identity(identity)
            for label, identity in identities.items()
        },
        "stops": stops,
        "all_processes_dead": all_dead,
        "endpoint_release": endpoint_release,
        "udc": udc,
    }
    try:
        evidence = write_atomic_exclusive(
            args.failure_evidence, payload, args.expected_owner_uid
        )
        payload["evidence"] = str(args.failure_evidence)
        payload["evidence_sha256"] = sha256_bytes(evidence)
    except HandoffError as exc:
        payload["evidence_error"] = str(exc)
    return payload


def recover_discovery_failure(
    args: argparse.Namespace, original_error: HandoffError, *, phase: str = "discovery"
) -> dict[str, Any]:
    """Disconnect a staged early gadget whose launcher never became authenticatable."""
    udc = verified_udc_unbind(args.recovery_udc, args.expected_owner_uid)
    status = "unbound" if udc.get("status") == "unbound" else "unsafe"
    payload = {
        "schema": FAILURE_SCHEMA,
        "status": status,
        "created_unix_ns": time.time_ns(),
        "phase": phase,
        "error": str(original_error),
        "udc": udc,
    }
    try:
        evidence = write_atomic_exclusive(
            args.failure_evidence, payload, args.expected_owner_uid
        )
        payload["evidence"] = str(args.failure_evidence)
        payload["evidence_sha256"] = sha256_bytes(evidence)
    except HandoffError as exc:
        payload["evidence_error"] = str(exc)
    return payload


def load_context(args: argparse.Namespace) -> dict[str, Any]:
    ready, ready_bytes = read_secure_json(args.ready, "early input ready marker", args.expected_owner_uid)
    if ready.get("schema") != READY_SCHEMA or ready.get("state") != "ready":
        raise HandoffError("early input ready marker schema/state mismatch")
    contract, contract_bytes = read_secure_json(
        args.runtime_contract, "early runtime contract", args.expected_owner_uid
    )
    if contract.get("schema") != CONTRACT_SCHEMA:
        raise HandoffError("early runtime contract schema mismatch")
    contract_hash = sha256_bytes(contract_bytes)
    if require_sha256(ready.get("runtime_contract_sha256"), "ready contract hash") != contract_hash:
        raise HandoffError("early ready marker does not bind the runtime contract")
    if require_string(ready.get("kernel_release"), "ready kernel release") != require_string(
        contract.get("kernel_release"), "contract kernel release"
    ):
        raise HandoffError("early ready/contract kernel release mismatch")
    native = require_object(contract.get("native_input"), "native input contract")
    if native.get("schema") != NATIVE_SCHEMA:
        raise HandoffError("native input contract schema mismatch")
    handoff_release = require_object(
        native.get("handoff_release"), "native input handoff release contract"
    )
    if handoff_release.get("keyboard_report_dedup") is not False:
        raise HandoffError(
            "native input handoff requires keyboard_report_dedup=false"
        )
    if handoff_release.get("required_endpoint_zero_writes") != ["main", "us_sub"]:
        raise HandoffError(
            "native input handoff must require exact main and US-sub zero writes"
        )
    marker_live_root = Path(require_string(ready.get("live_root"), "ready live root"))
    if not marker_live_root.is_absolute():
        raise HandoffError("ready live root is not absolute")
    live_root = args.live_root if args.live_root is not None else marker_live_root
    canonical_live = canonical_existing(live_root, "early live root")
    canonical_marker_live = canonical_existing(marker_live_root, "ready live root")
    if canonical_live != canonical_marker_live:
        raise HandoffError(
            f"early live root override does not match ready marker: {canonical_live} != {canonical_marker_live}"
        )
    binaries = require_object(native.get("binaries"), "native input binaries")
    ready_pids = require_object(ready.get("pids"), "ready PIDs")
    identities: dict[str, dict[str, Any]] = {}
    try:
        for label in LABELS:
            record = read_pid_record(
                args.pid_dir / f"{label}.pid", label, args.expected_owner_uid
            )
            if (
                require_positive_int(ready_pids.get(label), f"ready PID {label}")
                != record["pid"]
            ):
                raise HandoffError(f"ready/PID record mismatch for {label}")
            binary = require_object(
                binaries.get(CONTRACT_BINARY_KEYS[label]), f"native input binary {label}"
            )
            expected_exe = Path(
                require_string(binary.get("path"), f"{label} binary path")
            )
            identities[label] = open_verified_process_identity(
                args.proc_root,
                label,
                record,
                expected_exe,
                args.expected_owner_uid,
            )
    except Exception:
        for identity in identities.values():
            close_identity_pidfd(identity)
        raise
    return {
        "ready": ready,
        "ready_sha256": sha256_bytes(ready_bytes),
        "contract": contract,
        "contract_sha256": contract_hash,
        "live_root": canonical_live,
        "identities": identities,
    }


def require_reported_path(value: object, expected: Path, label: str) -> Path:
    reported = Path(require_string(value, label))
    if reported != expected:
        raise HandoffError(f"{label} mismatch: {reported} != {expected}")
    return reported


def validate_early_topology(
    args: argparse.Namespace,
    context: dict[str, Any],
    hidd: dict[str, Any],
    outputd: dict[str, Any],
    core: dict[str, Any],
    matrix: dict[str, Any],
) -> None:
    """Bind every early status and live socket to the authenticated chain."""
    identities: dict[str, dict[str, Any]] = context["identities"]
    status_payloads = {
        "hidd": (hidd, "hidd.status.v1"),
        "outputd": (outputd, "hidloom.outputd.status.v1"),
        "logicd-core": (core, "logicd-core.status.v1"),
        "matrixd": (matrix, "matrixd.status.v1"),
    }
    status_pids: list[int] = []
    for label, (payload, schema) in status_payloads.items():
        if payload.get("schema") != schema or payload.get("process") is not True:
            raise HandoffError(f"early {label} status is not running {schema}")
        status_pid = require_positive_int(payload.get("pid"), f"early {label} status PID")
        if status_pid != identities[label]["pid"]:
            raise HandoffError(
                f"early {label} status PID does not match authenticated identity: "
                f"{status_pid} != {identities[label]['pid']}"
            )
        status_pids.append(status_pid)
    if len(set(status_pids)) != len(LABELS):
        raise HandoffError("early status files do not identify four distinct processes")

    live_root: Path = context["live_root"]
    hidd_socket_path = live_root / "usbd-hid-reports.sock"
    output_report_path = live_root / "output-reports.sock"
    output_ctrl_path = live_root / "output-ctrl.sock"
    core_matrix_path = live_root / "matrix-events.sock"
    core_ctrl_path = live_root / "logicd-core-ctrl.sock"

    hidd_socket = require_object(hidd.get("socket"), "early hidd socket")
    if hidd_socket.get("listening") is not True:
        raise HandoffError("early hidd socket is not listening")
    require_reported_path(
        hidd_socket.get("path"), hidd_socket_path, "early hidd socket path"
    )
    require_owned_unix_socket(
        args.proc_root,
        identities["hidd"],
        hidd_socket_path,
        "early hidd report socket",
        args.expected_owner_uid,
        socket_type="datagram",
        listening=False,
    )
    endpoints = require_object(hidd.get("endpoints"), "early hidd endpoints")
    for endpoint, expected_path, recovery_path in (
        ("hidg0", args.early_hidg0, args.recovery_hidg0),
        ("hidg2", args.early_hidg2, args.recovery_hidg2),
    ):
        endpoint_state = require_object(
            endpoints.get(endpoint), f"early hidd {endpoint} endpoint"
        )
        if endpoint_state.get("open") is not True or endpoint_state.get(
            "last_error"
        ) not in (None, ""):
            raise HandoffError(f"early hidd {endpoint} endpoint is not healthy")
        reported = require_character_node(
            Path(
                require_string(
                    endpoint_state.get("path"), f"early hidd {endpoint} path"
                )
            ),
            f"early hidd {endpoint}",
            args.expected_owner_uid,
        )
        expected = require_character_node(
            expected_path,
            f"expected early {endpoint}",
            args.expected_owner_uid,
        )
        if reported != expected:
            raise HandoffError(
                f"early hidd {endpoint} path mismatch: {reported} != {expected}"
            )
        recovery = require_character_node(
            recovery_path,
            f"recovery {endpoint}",
            args.expected_owner_uid,
        )
        if recovery != expected:
            raise HandoffError(
                f"recovery {endpoint} path mismatch: {recovery} != {expected}"
            )
        require_owned_character_fd(
            args.proc_root,
            identities["hidd"],
            expected_path,
            f"early hidd {endpoint}",
            args.expected_owner_uid,
        )

    if outputd.get("target") != "usb" or outputd.get("last_error") not in (None, ""):
        raise HandoffError("early outputd is not healthy on the fixed USB target")
    output_sockets = require_object(outputd.get("sockets"), "early outputd sockets")
    require_reported_path(
        output_sockets.get("report"),
        output_report_path,
        "early outputd report socket path",
    )
    require_reported_path(
        output_sockets.get("ctrl"),
        output_ctrl_path,
        "early outputd control socket path",
    )
    require_reported_path(
        output_sockets.get("usb"),
        hidd_socket_path,
        "early outputd USB socket path",
    )
    require_owned_unix_socket(
        args.proc_root,
        identities["outputd"],
        output_report_path,
        "early outputd report socket",
        args.expected_owner_uid,
        socket_type="datagram",
        listening=False,
    )
    require_owned_unix_socket(
        args.proc_root,
        identities["outputd"],
        output_ctrl_path,
        "early outputd control socket",
        args.expected_owner_uid,
        socket_type="stream",
        listening=True,
    )

    validate_core_ready(core, "early logicd-core")
    if core.get("output_enabled") is not True:
        raise HandoffError("early logicd-core output is disabled")
    core_matrix = require_object(core.get("matrix_socket"), "early core matrix socket")
    core_ctrl = require_object(core.get("ctrl_socket"), "early core control socket")
    if core_matrix.get("listening") is not True or core_ctrl.get("listening") is not True:
        raise HandoffError("early logicd-core sockets are not listening")
    require_reported_path(
        core_matrix.get("path"), core_matrix_path, "early core matrix socket path"
    )
    require_reported_path(
        core_ctrl.get("path"), core_ctrl_path, "early core control socket path"
    )
    require_owned_unix_socket(
        args.proc_root,
        identities["logicd-core"],
        core_matrix_path,
        "early core matrix socket",
        args.expected_owner_uid,
        socket_type="stream",
        listening=True,
    )
    require_owned_unix_socket(
        args.proc_root,
        identities["logicd-core"],
        core_ctrl_path,
        "early core control socket",
        args.expected_owner_uid,
        socket_type="stream",
        listening=True,
    )
    broker = require_object(core.get("broker_socket"), "early core broker socket")
    if broker.get("available") not in (True, False) or broker.get("last_error") not in (
        None,
        "",
    ):
        raise HandoffError("early logicd-core broker is unhealthy")
    require_reported_path(
        broker.get("path"), output_report_path, "early core broker socket path"
    )

    if matrix.get("configured") is not True or matrix.get("gpio_ready") is not True:
        raise HandoffError("early matrixd is not configured with GPIO ready")
    matrix_logic = require_object(matrix.get("logic_socket"), "early matrixd logic socket")
    if matrix_logic.get("connected") is not True:
        raise HandoffError("early matrixd is not connected to logicd-core")
    require_reported_path(
        matrix_logic.get("path"), core_matrix_path, "early matrixd logic socket path"
    )


def run_prepare(args: argparse.Namespace) -> dict[str, Any]:
    try:
        ready = wait_for_ready(args)
    except HandoffError as exc:
        recovery = recover_discovery_failure(args, exc)
        raise HandoffError(
            f"{exc}; staged discovery recovery={recovery.get('status')}"
        ) from exc
    if not ready:
        return {"schema": PREPARE_SCHEMA, "status": "not-applicable"}
    try:
        context = load_context(args)
    except HandoffError as exc:
        recovery = recover_discovery_failure(args, exc, phase="authentication")
        raise HandoffError(
            f"{exc}; authentication recovery={recovery.get('status')}"
        ) from exc
    try:
        try:
            return run_prepare_with_context(args, context)
        except HandoffError as exc:
            if context.get("action_started") is True:
                recovery = recover_after_action_failure(args, context, exc)
                raise HandoffError(
                    f"{exc}; post-action recovery={recovery.get('status')}"
                ) from exc
            recovery = recover_discovery_failure(args, exc, phase="pre-action")
            raise HandoffError(
                f"{exc}; pre-action recovery={recovery.get('status')}"
            ) from exc
    finally:
        for identity in context["identities"].values():
            close_identity_pidfd(identity)


def run_prepare_with_context(
    args: argparse.Namespace, context: dict[str, Any]
) -> dict[str, Any]:
    live_root: Path = context["live_root"]
    identities: dict[str, dict[str, Any]] = context["identities"]
    hidd_path = live_root / "hidd-status.json"
    outputd_path = live_root / "outputd-status.json"
    core_path = live_root / "logicd-core-status.json"
    matrix_path = live_root / "matrixd-status.json"
    hidd_before = read_status_json(hidd_path, "early hidd status", args.expected_owner_uid)
    outputd_before = read_status_json(outputd_path, "early outputd status", args.expected_owner_uid)
    core_before = read_status_json(core_path, "early logicd-core status", args.expected_owner_uid)
    matrix_before = read_status_json(
        matrix_path, "early matrixd status", args.expected_owner_uid
    )
    validate_early_topology(
        args,
        context,
        hidd_before,
        outputd_before,
        core_before,
        matrix_before,
    )
    if hidd_before.get("schema") != "hidd.status.v1" or hidd_before.get("process") is not True:
        raise HandoffError("early hidd status is not running v1")
    if (
        outputd_before.get("schema") != "hidloom.outputd.status.v1"
        or outputd_before.get("process") is not True
    ):
        raise HandoffError("early outputd status is not running v1")
    if outputd_before.get("target") != "usb":
        raise HandoffError("early outputd must use the fixed USB target during handoff")
    hidd_before_errors = error_counters(hidd_before, HIDD_ERROR_COUNTERS, "early hidd")
    outputd_before_errors = error_counters(
        outputd_before, OUTPUTD_ERROR_COUNTERS, "early outputd"
    )
    require_zero_errors(hidd_before, HIDD_ERROR_COUNTERS, "early hidd")
    require_zero_errors(outputd_before, OUTPUTD_ERROR_COUNTERS, "early outputd")
    releases_before = status_counter(outputd_before, "release_frames", "early outputd")
    controls_before = status_counter(outputd_before, "ctrl_requests", "early outputd")
    if releases_before != 0 or controls_before != 0:
        raise HandoffError("early outputd was controlled before the authenticated handoff")
    if (
        status_counter(outputd_before, "frames_to_uinput", "early outputd") != 0
        or status_counter(outputd_before, "frames_to_bt", "early outputd") != 0
    ):
        raise HandoffError("early outputd routed frames outside USB before handoff")

    stopped: dict[str, str] = {}
    context["action_started"] = True
    stopped["matrixd"] = stop_identity(
        args.proc_root,
        identities["matrixd"],
        "matrixd",
        args.stop_timeout,
        args.poll_interval,
    )
    core_response = control_request(
        live_root / "logicd-core-ctrl.sock",
        "early logicd-core control socket",
        args.expected_owner_uid,
        {"t": "release_all"},
        args.control_timeout,
    )

    def core_zero_probe() -> dict[str, Any] | None:
        payload = read_status_json(core_path, "early logicd-core status", args.expected_owner_uid)
        validate_core_zero(payload)
        broker_socket = require_object(
            payload.get("broker_socket"), "early logicd-core broker socket"
        )
        if broker_socket.get("available") is not True or broker_socket.get("last_error") not in (
            None,
            "",
        ):
            raise HandoffError("early logicd-core broker is not healthy after release")
        status_counter(payload, "broker_frames_sent", "early logicd-core")
        return payload

    core_zero = wait_for(
        "early logicd-core zero state",
        args.status_timeout,
        args.poll_interval,
        core_zero_probe,
    )
    core_frames_sent = status_counter(
        core_zero, "broker_frames_sent", "early logicd-core"
    )
    # No equality observed while logicd-core is live is stable: the producer
    # may enqueue another datagram immediately afterwards.  Retire the sole
    # authenticated producer first, then prove both downstream queues caught
    # up before asking outputd to append the final endpoint-zero reports.
    stopped["logicd-core"] = stop_identity(
        args.proc_root,
        identities["logicd-core"],
        "logicd-core",
        args.stop_timeout,
        args.poll_interval,
    )

    def queued_frames_drained_probe() -> dict[str, Any] | None:
        outputd = read_status_json(
            outputd_path, "early outputd status", args.expected_owner_uid
        )
        hidd = read_status_json(hidd_path, "early hidd status", args.expected_owner_uid)
        if (
            outputd.get("schema") != "hidloom.outputd.status.v1"
            or outputd.get("process") is not True
            or outputd.get("target") != "usb"
            or outputd.get("last_error") not in (None, "")
        ):
            raise HandoffError("early outputd became unhealthy while draining queued frames")
        if hidd.get("schema") != "hidd.status.v1" or hidd.get("process") is not True:
            raise HandoffError("early hidd became unhealthy while draining queued frames")
        require_zero_errors(outputd, OUTPUTD_ERROR_COUNTERS, "early outputd")
        require_zero_errors(hidd, HIDD_ERROR_COUNTERS, "early hidd")
        received = status_counter(outputd, "frames_received", "early outputd")
        to_usb = status_counter(outputd, "frames_to_usb", "early outputd")
        to_uinput = status_counter(outputd, "frames_to_uinput", "early outputd")
        to_bt = status_counter(outputd, "frames_to_bt", "early outputd")
        releases = status_counter(outputd, "release_frames", "early outputd")
        hidd_received = status_counter(hidd, "frames_received", "early hidd")
        expected_hidd = core_frames_sent
        if received > core_frames_sent or to_usb > core_frames_sent:
            raise HandoffError("early outputd counters exceed the retired core frame total")
        if to_uinput != 0 or to_bt != 0:
            raise HandoffError("early outputd routed frames outside USB")
        if releases != releases_before:
            raise HandoffError("early outputd release counter changed before final release")
        if status_counter(outputd, "ctrl_requests", "early outputd") != controls_before:
            raise HandoffError("early outputd control counter changed before final release")
        if hidd_received > expected_hidd:
            raise HandoffError("early hidd received unaccounted frames before final release")
        if (
            received < core_frames_sent
            or to_usb < core_frames_sent
            or hidd_received < expected_hidd
        ):
            return None
        return {"outputd": outputd, "hidd": hidd}

    drained = wait_for(
        "early outputd and hidd queues to drain after core stop",
        args.status_timeout,
        args.poll_interval,
        queued_frames_drained_probe,
    )
    main_zero_before = status_counter(
        drained["hidd"], "keyboard_zero_reports", "early hidd"
    )
    us_zero_before = status_counter(
        drained["hidd"], "us_sub_keyboard_zero_reports", "early hidd"
    )
    outputd_response = control_request(
        live_root / "output-ctrl.sock",
        "early outputd control socket",
        args.expected_owner_uid,
        {"t": "release_all"},
        args.control_timeout,
    )
    release = require_object(outputd_response.get("release"), "outputd release acknowledgement")
    if (
        require_nonnegative_int(release.get("attempted"), "release attempted") != 2
        or require_nonnegative_int(release.get("delivered"), "release delivered") != 2
        or require_nonnegative_int(release.get("errors"), "release errors") != 0
    ):
        raise HandoffError(f"outputd did not acknowledge both endpoint releases: {release}")

    def outputd_release_probe() -> dict[str, Any] | None:
        outputd = read_status_json(outputd_path, "early outputd status", args.expected_owner_uid)
        if (
            outputd.get("schema") != "hidloom.outputd.status.v1"
            or outputd.get("process") is not True
            or outputd.get("target") != "usb"
            or outputd.get("last_error") not in (None, "")
        ):
            raise HandoffError("early outputd became unhealthy during final release")
        require_zero_errors(outputd, OUTPUTD_ERROR_COUNTERS, "early outputd")
        if status_counter(outputd, "frames_received", "early outputd") != core_frames_sent:
            raise HandoffError("early outputd received frames after its drain barrier")
        if status_counter(outputd, "frames_to_usb", "early outputd") != core_frames_sent:
            raise HandoffError("early outputd USB frame count changed after its drain barrier")
        if (
            status_counter(outputd, "frames_to_uinput", "early outputd") != 0
            or status_counter(outputd, "frames_to_bt", "early outputd") != 0
        ):
            raise HandoffError("early outputd routed final frames outside USB")
        if status_counter(outputd, "ctrl_requests", "early outputd") != controls_before + 1:
            raise HandoffError("early outputd final release control count is not exact")
        release_frames = status_counter(outputd, "release_frames", "early outputd")
        if release_frames > releases_before + 2:
            raise HandoffError("early outputd emitted excess final release frames")
        if release_frames < releases_before + 2:
            return None
        return outputd

    outputd_released = wait_for(
        "early outputd final release status",
        args.status_timeout,
        args.poll_interval,
        outputd_release_probe,
    )
    stopped["outputd"] = stop_identity(
        args.proc_root,
        identities["outputd"],
        "outputd",
        args.stop_timeout,
        args.poll_interval,
    )

    expected_final_hidd_frames = core_frames_sent + 2

    def endpoint_release_probe() -> dict[str, Any] | None:
        hidd = read_status_json(hidd_path, "early hidd status", args.expected_owner_uid)
        if hidd.get("schema") != "hidd.status.v1" or hidd.get("process") is not True:
            raise HandoffError("early hidd became unhealthy during final release")
        require_zero_errors(hidd, HIDD_ERROR_COUNTERS, "early hidd")
        received = status_counter(hidd, "frames_received", "early hidd")
        main_zero = status_counter(hidd, "keyboard_zero_reports", "early hidd")
        us_zero = status_counter(hidd, "us_sub_keyboard_zero_reports", "early hidd")
        if received > expected_final_hidd_frames:
            raise HandoffError("early hidd received frames after outputd stopped")
        if (
            received < expected_final_hidd_frames
            or main_zero < main_zero_before + 1
            or us_zero < us_zero_before + 1
        ):
            return None
        return hidd

    hidd_released = wait_for(
        "final zero reports after outputd stop",
        args.status_timeout,
        args.poll_interval,
        endpoint_release_probe,
    )
    stopped["hidd"] = stop_identity(
        args.proc_root,
        identities["hidd"],
        "hidd",
        args.stop_timeout,
        args.poll_interval,
    )
    for label, identity in identities.items():
        if identity_is_live(args.proc_root, identity):
            raise HandoffError(f"early {label} process identity remains after handoff prepare")

    payload = {
        "schema": PREPARE_SCHEMA,
        "status": "prepared",
        "created_unix_ns": time.time_ns(),
        "ready_sha256": context["ready_sha256"],
        "runtime_contract_sha256": context["contract_sha256"],
        "live_root": str(live_root),
        "processes": {
            label: public_process_identity(identity)
            for label, identity in identities.items()
        },
        "stop_order": ["matrixd", "logicd-core", "outputd", "hidd"],
        "stop_signals": stopped,
        "release": {
            "logicd_core_response": core_response,
            "logicd_core_status_sha256": sha256_bytes(
                (json.dumps(core_zero, sort_keys=True, separators=(",", ":")) + "\n").encode()
            ),
            "outputd_response": outputd_response,
            "queue_barrier": {
                "core_broker_frames_sent": core_frames_sent,
                "outputd_release_frames_before": releases_before,
                "outputd_control_requests_before": controls_before,
                "outputd_frames_received": status_counter(
                    drained["outputd"], "frames_received", "early outputd"
                ),
                "outputd_frames_to_usb": status_counter(
                    drained["outputd"], "frames_to_usb", "early outputd"
                ),
                "hidd_frames_received_before_release": status_counter(
                    drained["hidd"], "frames_received", "early hidd"
                ),
                "hidd_frames_received_after_release": status_counter(
                    hidd_released, "frames_received", "early hidd"
                ),
            },
            "hidd_zero_before": {
                "main": main_zero_before,
                "us_sub": us_zero_before,
            },
            "hidd_zero_after": {
                "main": status_counter(
                    hidd_released, "keyboard_zero_reports", "early hidd"
                ),
                "us_sub": status_counter(
                    hidd_released, "us_sub_keyboard_zero_reports", "early hidd"
                ),
            },
            "hidd_errors_before": hidd_before_errors,
            "hidd_errors_after": error_counters(
                hidd_released, HIDD_ERROR_COUNTERS, "early hidd"
            ),
            "outputd_errors_before": outputd_before_errors,
            "outputd_errors_after": error_counters(
                outputd_released, OUTPUTD_ERROR_COUNTERS, "early outputd"
            ),
        },
    }
    evidence_bytes = write_atomic_exclusive(
        args.prepare_evidence, payload, args.expected_owner_uid
    )
    return {
        "schema": PREPARE_SCHEMA,
        "status": "prepared",
        "evidence": str(args.prepare_evidence),
        "evidence_sha256": sha256_bytes(evidence_bytes),
    }


def normal_status_probe(args: argparse.Namespace) -> dict[str, Any] | None:
    hidd = read_status_json(args.normal_hidd_status, "normal hidd status", args.expected_owner_uid)
    outputd = read_status_json(
        args.normal_outputd_status, "normal outputd status", args.expected_owner_uid
    )
    core = read_status_json(args.normal_core_status, "normal logicd-core status", args.expected_owner_uid)
    matrix = read_status_json(
        args.normal_matrix_status, "normal matrixd status", args.expected_owner_uid
    )
    if hidd.get("schema") != "hidd.status.v1" or hidd.get("process") is not True:
        return None
    hidd_socket = require_object(hidd.get("socket"), "normal hidd socket")
    endpoints = require_object(hidd.get("endpoints"), "normal hidd endpoints")
    if hidd_socket.get("listening") is not True:
        return None
    hidd_socket_path = Path(
        require_string(hidd_socket.get("path"), "normal hidd socket path")
    )
    require_socket(
        hidd_socket_path,
        "normal hidd live socket",
        args.expected_owner_uid,
    )
    expected_endpoints = {"hidg0": args.normal_hidg0, "hidg2": args.normal_hidg2}
    for endpoint in ("hidg0", "hidg2"):
        state = require_object(endpoints.get(endpoint), f"normal hidd {endpoint}")
        if state.get("open") is not True or state.get("last_error") not in (None, ""):
            return None
        reported = require_character_node(
            Path(require_string(state.get("path"), f"normal hidd {endpoint} path")),
            f"normal hidd {endpoint}",
            args.expected_owner_uid,
        )
        expected = require_character_node(
            expected_endpoints[endpoint],
            f"expected normal {endpoint}",
            args.expected_owner_uid,
        )
        if reported != expected:
            raise HandoffError(f"normal hidd {endpoint} path mismatch: {reported} != {expected}")
    if outputd.get("schema") != "hidloom.outputd.status.v1" or outputd.get("process") is not True:
        return None
    if outputd.get("target") not in ("usb", "auto") or outputd.get("last_error") not in (None, ""):
        return None
    require_zero_errors(hidd, HIDD_ERROR_COUNTERS, "normal hidd")
    require_zero_errors(outputd, OUTPUTD_ERROR_COUNTERS, "normal outputd")
    if status_counter(hidd, "startup_release_reports", "normal hidd") < 2:
        return None
    if (
        status_counter(hidd, "keyboard_zero_reports", "normal hidd") < 1
        or status_counter(hidd, "us_sub_keyboard_zero_reports", "normal hidd") < 1
    ):
        return None
    output_sockets = require_object(outputd.get("sockets"), "normal outputd sockets")
    output_report_path = Path(
        require_string(output_sockets.get("report"), "normal outputd report socket path")
    )
    output_ctrl_path = Path(
        require_string(output_sockets.get("ctrl"), "normal outputd ctrl socket path")
    )
    for key in ("report", "ctrl"):
        require_socket(
            Path(require_string(output_sockets.get(key), f"normal outputd {key} socket path")),
            f"normal outputd live {key} socket",
            args.expected_owner_uid,
        )
    if Path(require_string(output_sockets.get("usb"), "normal outputd USB socket path")) != hidd_socket_path:
        raise HandoffError("normal outputd USB route does not target the authenticated hidd socket")
    if core.get("schema") != "logicd-core.status.v1" or core.get("process") is not True:
        return None
    # Readiness is independent of whether the operator is currently holding a
    # key.  E4 only requires zero state while retiring the early chain; the
    # normal chain may already be processing legitimate input during finalize.
    validate_core_ready(core, "normal logicd-core")
    if core.get("output_enabled") is not True:
        return None
    core_broker = require_object(core.get("broker_socket"), "normal core broker socket")
    # logicd-core deliberately publishes broker available=false at startup and
    # only changes it after the first report/control request.  An idle keyboard
    # can therefore be fully ready without having exercised the broker yet.
    # Authenticate the live outputd route/socket below and reject an actual
    # broker error, but do not require traffic as a readiness side effect.
    if core_broker.get("available") not in (True, False) or core_broker.get(
        "last_error"
    ) not in (None, ""):
        return None
    if Path(require_string(core_broker.get("path"), "normal core broker socket path")) != output_report_path:
        raise HandoffError("normal core broker does not target the authenticated outputd socket")
    core_matrix = require_object(core.get("matrix_socket"), "normal core matrix socket")
    if core_matrix.get("listening") is not True:
        return None
    core_ctrl = require_object(core.get("ctrl_socket"), "normal core ctrl socket")
    if core_ctrl.get("listening") is not True:
        return None
    core_matrix_path = Path(
        require_string(core_matrix.get("path"), "normal core matrix socket path")
    )
    core_ctrl_path = Path(
        require_string(core_ctrl.get("path"), "normal core ctrl socket path")
    )
    require_socket(core_matrix_path, "normal core live matrix socket", args.expected_owner_uid)
    require_socket(
        core_ctrl_path,
        "normal core live ctrl socket",
        args.expected_owner_uid,
    )
    if matrix.get("schema") != "matrixd.status.v1" or matrix.get("process") is not True:
        return None
    if matrix.get("configured") is not True or matrix.get("gpio_ready") is not True:
        return None
    matrix_logic = require_object(matrix.get("logic_socket"), "normal matrixd logic socket")
    if matrix_logic.get("connected") is not True:
        return None
    if Path(require_string(matrix_logic.get("path"), "normal matrixd logic socket path")) != core_matrix_path:
        raise HandoffError("normal matrixd is connected to an unexpected core socket")
    process_identities: dict[str, dict[str, Any]] = {}
    process_specs = (
        ("hidd", hidd, args.normal_hidd_exe),
        ("outputd", outputd, args.normal_outputd_exe),
        ("logicd-core", core, args.normal_core_exe),
        ("matrixd", matrix, args.normal_matrix_exe),
    )
    try:
        for label, status_payload, expected_exe in process_specs:
            process_identities[label] = verify_live_status_process(
                args.proc_root,
                status_payload,
                f"normal {label}",
                expected_exe,
                args.expected_owner_uid,
            )
    except Exception:
        for identity in process_identities.values():
            close_identity_pidfd(identity)
        raise
    if len({identity["pid"] for identity in process_identities.values()}) != len(LABELS):
        for identity in process_identities.values():
            close_identity_pidfd(identity)
        raise HandoffError("normal status files do not identify four distinct processes")
    try:
        require_owned_unix_socket(
            args.proc_root,
            process_identities["hidd"],
            hidd_socket_path,
            "normal hidd report socket",
            args.expected_owner_uid,
            socket_type="datagram",
            listening=False,
        )
        require_owned_unix_socket(
            args.proc_root,
            process_identities["outputd"],
            output_report_path,
            "normal outputd report socket",
            args.expected_owner_uid,
            socket_type="datagram",
            listening=False,
        )
        require_owned_unix_socket(
            args.proc_root,
            process_identities["outputd"],
            output_ctrl_path,
            "normal outputd control socket",
            args.expected_owner_uid,
            socket_type="stream",
            listening=True,
        )
        require_owned_unix_socket(
            args.proc_root,
            process_identities["logicd-core"],
            core_matrix_path,
            "normal core matrix socket",
            args.expected_owner_uid,
            socket_type="stream",
            listening=True,
        )
        require_owned_unix_socket(
            args.proc_root,
            process_identities["logicd-core"],
            core_ctrl_path,
            "normal core control socket",
            args.expected_owner_uid,
            socket_type="stream",
            listening=True,
        )
        require_owned_character_fd(
            args.proc_root,
            process_identities["hidd"],
            args.normal_hidg0,
            "normal hidd hidg0",
            args.expected_owner_uid,
        )
        require_owned_character_fd(
            args.proc_root,
            process_identities["hidd"],
            args.normal_hidg2,
            "normal hidd hidg2",
            args.expected_owner_uid,
        )
    except Exception:
        for identity in process_identities.values():
            close_identity_pidfd(identity)
        raise
    return {
        "statuses": {
            "hidd": hidd,
            "outputd": outputd,
            "logicd_core": core,
            "matrixd": matrix,
        },
        "processes": process_identities,
    }


def run_finalize(args: argparse.Namespace) -> dict[str, Any]:
    if not args.prepare_evidence.exists() and not args.prepare_evidence.is_symlink():
        return {"schema": COMPLETE_SCHEMA, "status": "not-applicable"}
    prepared, prepared_bytes = read_secure_json(
        args.prepare_evidence, "handoff prepare evidence", args.expected_owner_uid
    )
    if prepared.get("schema") != PREPARE_SCHEMA or prepared.get("status") != "prepared":
        raise HandoffError("handoff prepare evidence schema/status mismatch")
    ready, ready_bytes = read_secure_json(args.ready, "early input ready marker", args.expected_owner_uid)
    contract, contract_bytes = read_secure_json(
        args.runtime_contract, "early runtime contract", args.expected_owner_uid
    )
    if prepared.get("ready_sha256") != sha256_bytes(ready_bytes):
        raise HandoffError("prepare evidence no longer matches early ready marker")
    if prepared.get("runtime_contract_sha256") != sha256_bytes(contract_bytes):
        raise HandoffError("prepare evidence no longer matches runtime contract")
    if ready.get("schema") != READY_SCHEMA or contract.get("schema") != CONTRACT_SCHEMA:
        raise HandoffError("ready/runtime contract schema changed before finalize")
    processes = require_object(prepared.get("processes"), "prepared processes")
    for label in LABELS:
        identity = require_object(processes.get(label), f"prepared process {label}")
        if identity_is_live(args.proc_root, identity):
            raise HandoffError(f"early {label} identity is live during finalize")
    normal_proof = wait_for(
        "normal input chain ready status",
        args.status_timeout,
        args.poll_interval,
        lambda: normal_status_probe(args),
    )
    statuses = require_object(normal_proof.get("statuses"), "normal status proof")
    normal_processes = require_object(
        normal_proof.get("processes"), "normal process proof"
    )
    try:
        payload = {
            "schema": COMPLETE_SCHEMA,
            "status": "complete",
            "created_unix_ns": time.time_ns(),
            "prepare_evidence_sha256": sha256_bytes(prepared_bytes),
            "ready_sha256": sha256_bytes(ready_bytes),
            "runtime_contract_sha256": sha256_bytes(contract_bytes),
            "normal_processes": {
                label: public_process_identity(identity)
                for label, identity in normal_processes.items()
            },
            "normal_status_sha256": {
                label: sha256_bytes(
                    (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
                )
                for label, value in statuses.items()
            },
        }
        for label, identity in normal_processes.items():
            pidfd = identity.get("_pidfd")
            if not isinstance(pidfd, int) or pidfd_has_exited(pidfd):
                raise HandoffError(
                    f"normal {label} exited before complete evidence publication"
                )
        evidence_bytes = write_atomic_exclusive(
            args.complete_evidence, payload, args.expected_owner_uid
        )
        return {
            "schema": COMPLETE_SCHEMA,
            "status": "complete",
            "evidence": str(args.complete_evidence),
            "evidence_sha256": sha256_bytes(evidence_bytes),
        }
    finally:
        for identity in normal_processes.values():
            close_identity_pidfd(identity)


def add_common_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--ready", type=Path, default=Path("/run/hidloom-early/e3-input.ready"))
    parser.add_argument(
        "--runtime-contract", type=Path, default=Path("/run/hidloom-early/contract.json")
    )
    parser.add_argument(
        "--prepare-evidence",
        type=Path,
        default=Path("/run/hidloom-early/e4-handoff.prepare.json"),
    )
    parser.add_argument("--proc-root", type=Path, default=Path("/proc"))
    parser.add_argument("--expected-owner-uid", type=int, default=0)
    parser.add_argument("--status-timeout", type=float, default=3.0)
    parser.add_argument("--poll-interval", type=float, default=0.01)


def build_parser() -> argparse.ArgumentParser:
    parser = HandoffArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare", help="release and retire authenticated early daemons")
    add_common_paths(prepare)
    prepare.add_argument("--pid-dir", type=Path, default=Path("/run/hidloom-early/pids"))
    prepare.add_argument("--live-root", type=Path)
    prepare.add_argument(
        "--discovery-live-root", type=Path, default=Path("/dev/hidloom-early")
    )
    prepare.add_argument("--discovery-timeout", type=float, default=3.0)
    prepare.add_argument("--control-timeout", type=float, default=2.0)
    prepare.add_argument("--stop-timeout", type=float, default=2.0)
    prepare.add_argument(
        "--failure-evidence",
        type=Path,
        default=Path("/run/hidloom-early/e4-handoff.failure.json"),
    )
    prepare.add_argument("--recovery-hidg0", type=Path, default=Path("/dev/hidg0"))
    prepare.add_argument("--recovery-hidg2", type=Path, default=Path("/dev/hidg2"))
    prepare.add_argument("--early-hidg0", type=Path, default=Path("/dev/hidg0"))
    prepare.add_argument("--early-hidg2", type=Path, default=Path("/dev/hidg2"))
    prepare.add_argument(
        "--recovery-udc",
        type=Path,
        default=Path("/sys/kernel/config/usb_gadget/cqa02303v5/UDC"),
    )
    finalize = subparsers.add_parser("finalize", help="prove the normal input chain ready")
    add_common_paths(finalize)
    finalize.add_argument(
        "--complete-evidence",
        type=Path,
        default=Path("/run/hidloom-early/e4-handoff.complete.json"),
    )
    finalize.add_argument(
        "--normal-hidd-status", type=Path, default=Path("/run/hidloom/hidd-status.json")
    )
    finalize.add_argument(
        "--normal-outputd-status", type=Path, default=Path("/run/hidloom/outputd-status.json")
    )
    finalize.add_argument(
        "--normal-core-status", type=Path, default=Path("/run/hidloom/logicd-core-status.json")
    )
    finalize.add_argument(
        "--normal-matrix-status", type=Path, default=Path("/run/hidloom/matrixd-status.json")
    )
    finalize.add_argument(
        "--normal-hidd-exe", type=Path, default=Path("/usr/lib/hidloom/bin/hidloom-hidd")
    )
    finalize.add_argument(
        "--normal-outputd-exe",
        type=Path,
        default=Path("/usr/lib/hidloom/bin/hidloom-outputd"),
    )
    finalize.add_argument(
        "--normal-core-exe",
        type=Path,
        default=Path("/usr/lib/hidloom/bin/hidloom-logicd-core"),
    )
    finalize.add_argument(
        "--normal-matrix-exe",
        type=Path,
        default=Path("/usr/lib/hidloom/daemon/matrixd/matrixd"),
    )
    finalize.add_argument("--normal-hidg0", type=Path, default=Path("/dev/hidg0"))
    finalize.add_argument("--normal-hidg2", type=Path, default=Path("/dev/hidg2"))
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if args.expected_owner_uid < 0:
        raise HandoffError("expected owner UID must be non-negative")
    for name in ("status_timeout", "poll_interval"):
        if getattr(args, name) <= 0:
            raise HandoffError(f"{name.replace('_', ' ')} must be positive")
    if args.command == "prepare":
        for name in ("discovery_timeout", "control_timeout", "stop_timeout"):
            if getattr(args, name) <= 0:
                raise HandoffError(f"{name.replace('_', ' ')} must be positive")


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        validate_args(args)
        result = run_prepare(args) if args.command == "prepare" else run_finalize(args)
        print(json.dumps(result, sort_keys=True))
        return 0
    except HandoffError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_UNSAFE


if __name__ == "__main__":
    raise SystemExit(main())
