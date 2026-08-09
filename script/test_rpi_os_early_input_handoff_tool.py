#!/usr/bin/env python3
"""Host-only fixtures for the E4 early-input handoff helper."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import select
import shutil
import signal
import socket
import stat
import subprocess
import tempfile
import threading
import time
import tty
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/rpi_os_early_input_handoff.py"
SPEC = importlib.util.spec_from_file_location("rpi_os_early_input_handoff", TOOL)
assert SPEC is not None and SPEC.loader is not None
HANDOFF = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HANDOFF)


def write_json(path: Path, payload: dict[str, Any]) -> bytes:
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{threading.get_ident()}")
    temporary.write_bytes(data)
    temporary.chmod(0o600)
    temporary.replace(path)
    return data


def zero_core_status(*, pressed: bool, broker_frames_sent: int = 4) -> dict[str, Any]:
    count = 1 if pressed else 0
    return {
        "schema": "logicd-core.status.v1",
        "process": True,
        "output_enabled": True,
        "matrix_socket": {"path": "/fixture/matrix.sock", "listening": True},
        "ctrl_socket": {"path": "/fixture/ctrl.sock", "listening": True},
        "broker_socket": {
            "path": "/fixture/output.sock",
            "available": True,
            "last_error": "",
        },
        "state": {
            "pressed_matrix": count,
            "injected_keys": count,
            "pressed_keys": count,
            "modifier": count,
        },
        "routing": {
            "state": {
                "us_sub_key_active": pressed,
                "primary_key_active": pressed,
                "primary_modifier_mirror_active": pressed,
                "zenkaku_hankaku_active": pressed,
            }
        },
        "counters": {"broker_frames_sent": broker_frames_sent},
    }


def hidd_status(main_zero: int, us_zero: int, *, frames_received: int = 4) -> dict[str, Any]:
    return {
        "schema": "hidd.status.v1",
        "process": True,
        "socket": {"path": "/fixture/hidd.sock", "listening": True},
        "endpoints": {
            "hidg0": {"path": "/dev/hidg0", "open": True, "last_error": ""},
            "hidg2": {"path": "/dev/hidg2", "open": True, "last_error": ""},
        },
        "counters": {
            "frames_received": frames_received,
            "startup_release_reports": 2,
            "keyboard_zero_reports": main_zero,
            "us_sub_keyboard_zero_reports": us_zero,
            "invalid_frames": 0,
            "write_errors": 0,
            "dropped_reports": 0,
        },
    }


def outputd_status(
    releases: int,
    *,
    frames_received: int = 4,
    frames_to_usb: int = 4,
    ctrl_requests: int = 0,
) -> dict[str, Any]:
    return {
        "schema": "hidloom.outputd.status.v1",
        "process": True,
        "target": "usb",
        "last_error": "",
        "counters": {
            "frames_received": frames_received,
            "frames_to_usb": frames_to_usb,
            "frames_to_uinput": 0,
            "frames_to_bt": 0,
            "release_frames": releases,
            "invalid_frames": 0,
            "forward_errors": 0,
            "release_errors": 0,
            "ctrl_requests": ctrl_requests,
        },
    }


class ControlServer:
    def __init__(self, path: Path, handler: Any, listener: socket.socket | None = None) -> None:
        self.path = path
        self.handler = handler
        self.listener = listener or socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        if listener is None:
            self.listener.bind(str(path))
            self.listener.listen(1)
        self.listener.settimeout(0.1)
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self) -> None:
        while not self.stopping.is_set():
            try:
                connection, _ = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with connection:
                request = bytearray()
                while b"\n" not in request:
                    chunk = connection.recv(65536)
                    if not chunk:
                        break
                    request.extend(chunk)
                response = self.handler(json.loads(bytes(request).split(b"\n", 1)[0]))
                connection.sendall((json.dumps(response, sort_keys=True) + "\n").encode())

    def close(self) -> None:
        self.stopping.set()
        self.listener.close()
        self.thread.join(timeout=1)


class Fixture:
    def __init__(
        self,
        root: Path,
        *,
        failure: str | None = None,
        foreign_socket: str | None = None,
    ) -> None:
        self.root = root
        self.uid = os.getuid()
        self.run = root / "run"
        self.live = root / "live"
        self.pids = self.run / "pids"
        self.runtime = self.live / "runtime"
        for path in (self.run, self.live, self.pids, self.runtime):
            path.mkdir(parents=True, exist_ok=True)
            path.chmod(0o700)
        self.ready = self.run / "e3-input.ready"
        self.contract = self.run / "contract.json"
        self.prepare = self.run / "e4-handoff.prepare.json"
        self.complete = self.run / "e4-handoff.complete.json"
        self.failure_evidence = self.run / "e4-handoff.failure.json"
        self.failure = failure
        self.runners: list[subprocess.Popen[bytes]] = []
        self.normal_processes: list[subprocess.Popen[bytes]] = []
        self.normal_sockets: list[socket.socket] = []
        self.normal_connections: list[socket.socket] = []
        self.workers: list[threading.Thread] = []
        self.identities: dict[str, dict[str, int]] = {}
        self.cleanup_pidfds: dict[str, int] = {}
        self.recovery_ptys: list[tuple[int, int]] = [os.openpty(), os.openpty()]
        for _, slave in self.recovery_ptys:
            tty.setraw(slave)
        self.recovery_hidg0 = Path(os.ttyname(self.recovery_ptys[0][1]))
        self.recovery_hidg2 = Path(os.ttyname(self.recovery_ptys[1][1]))
        self.early_hidg0 = self.recovery_hidg0
        self.early_hidg2 = self.recovery_hidg2
        self.recovery_udc = self.run / "fixture-UDC"
        self.recovery_udc.write_text("fixture.udc\n", encoding="ascii")
        self.recovery_udc.chmod(0o600)
        self.socket_paths = {
            "hidd": self.live / "usbd-hid-reports.sock",
            "output_report": self.live / "output-reports.sock",
            "output_ctrl": self.live / "output-ctrl.sock",
            "core_matrix": self.live / "matrix-events.sock",
            "core_ctrl": self.live / "logicd-core-ctrl.sock",
        }
        self.early_sockets: dict[str, socket.socket] = {}
        for key, path in self.socket_paths.items():
            kind = (
                socket.SOCK_STREAM
                if key in ("output_ctrl", "core_matrix", "core_ctrl")
                else socket.SOCK_DGRAM
            )
            live_socket = socket.socket(socket.AF_UNIX, kind)
            live_socket.bind(str(path))
            if kind == socket.SOCK_STREAM:
                live_socket.listen(4)
            self.early_sockets[key] = live_socket
        # Linux exposes an accepted stream connection with the listener's path
        # as a second /proc/net/unix record.  The ownership verifier must select
        # the one SOCK_ACCEPTCON listener record, not require one path row total.
        matrix_client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        matrix_client.connect(str(self.socket_paths["core_matrix"]))
        matrix_accepted, _ = self.early_sockets["core_matrix"].accept()
        self.early_connections = [matrix_client, matrix_accepted]
        socket_owners = {
            "hidd": "hidd",
            "output_report": "outputd",
            "output_ctrl": "outputd",
            "core_matrix": "logicd-core",
            "core_ctrl": "logicd-core",
        }
        if foreign_socket is not None:
            assert foreign_socket in socket_owners
            socket_owners[foreign_socket] = "matrixd"
        binaries: dict[str, Any] = {}
        # The workspace's `sleep` is a basename-dispatched coreutils multicall
        # binary.  dash keeps its behavior when copied under per-daemon names.
        source = Path("/bin/dash")
        keys = {
            "hidd": "hidd",
            "outputd": "outputd",
            "logicd-core": "logicd_core",
            "matrixd": "matrixd",
        }
        ready_pids: dict[str, int] = {}
        for label, key in keys.items():
            binary = self.runtime / label
            shutil.copy2(source, binary)
            binary.chmod(0o700)
            child_pid_file = self.root / f"child-{label}.pid"
            inherited_fds = [
                live_socket.fileno()
                for socket_key, live_socket in self.early_sockets.items()
                if socket_owners[socket_key] == label
            ]
            if label == "hidd":
                inherited_fds.extend(slave for _, slave in self.recovery_ptys)
            runner = subprocess.Popen(
                [
                    "/bin/sh",
                    "-c",
                    '"$1" -c \'trap "exit 0" TERM; while :; do /bin/sleep 0.05; done\' '
                    '& child=$!; printf "%s\\n" "$child" >"$2"; wait "$child"',
                    "fixture-reaper",
                    str(binary),
                    str(child_pid_file),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                pass_fds=tuple(inherited_fds),
            )
            self.runners.append(runner)
            deadline = time.monotonic() + 3
            pid = None
            while pid is None:
                assert time.monotonic() < deadline, child_pid_file
                try:
                    raw_pid = child_pid_file.read_text(encoding="ascii").strip()
                    candidate_pid = int(raw_pid)
                    if candidate_pid > 0:
                        pid = candidate_pid
                except (FileNotFoundError, ValueError):
                    pass
                time.sleep(0.005)
            proc = Path("/proc") / str(pid)
            expected_exe = binary.resolve(strict=True)
            deadline = time.monotonic() + 3
            while True:
                assert time.monotonic() < deadline, (label, pid, expected_exe)
                try:
                    live_exe = (proc / "exe").resolve(strict=True)
                    exe = (proc / "exe").stat()
                except (FileNotFoundError, PermissionError):
                    live_exe = None
                if live_exe == expected_exe:
                    break
                # The reaper publishes the forked child PID before that child
                # execs the copied per-daemon binary.  Never record the outer
                # /bin/sh inode from that bounded pre-exec window.
                time.sleep(0.005)
            starttime = HANDOFF.proc_stat_starttime(proc / "stat", label)
            record = {
                "pid": pid,
                "starttime": starttime,
                "exe_dev": exe.st_dev,
                "exe_ino": exe.st_ino,
            }
            self.identities[label] = record
            self.cleanup_pidfds[label] = os.pidfd_open(pid, 0)
            ready_pids[label] = pid
            (self.pids / f"{label}.pid").write_text(
                f"{pid} {starttime} {exe.st_dev} {exe.st_ino}\n", encoding="ascii"
            )
            (self.pids / f"{label}.pid").chmod(0o600)
            binaries[key] = {"path": str(binary)}
        contract_payload = {
            "schema": "hidloom.rpi-os-early-runtime-contract.e1.v1",
            "kernel_release": "fixture-kernel",
            "native_input": {
                "schema": "hidloom.rpi-os-early-native-input.e3.v1",
                "binaries": binaries,
                "handoff_release": {
                    "keyboard_report_dedup": False,
                    "required_endpoint_zero_writes": ["main", "us_sub"],
                },
            },
        }
        contract_bytes = write_json(self.contract, contract_payload)
        ready_payload = {
            "schema": "hidloom.early-input.v1",
            "state": "ready",
            "kernel_release": "fixture-kernel",
            "runtime_contract_sha256": hashlib.sha256(contract_bytes).hexdigest(),
            "ready_uptime_seconds": 1.25,
            "live_root": str(self.live),
            "pids": ready_pids,
        }
        write_json(self.ready, ready_payload)
        (self.live / "chain-ready").touch(mode=0o600)

        def early_hidd_status(
            main_zero: int, us_zero: int, *, frames_received: int
        ) -> dict[str, Any]:
            payload = hidd_status(
                main_zero, us_zero, frames_received=frames_received
            )
            payload["pid"] = ready_pids["hidd"]
            payload["socket"] = {
                "path": str(self.socket_paths["hidd"]),
                "listening": True,
            }
            payload["endpoints"]["hidg0"]["path"] = str(self.early_hidg0)
            payload["endpoints"]["hidg2"]["path"] = str(self.early_hidg2)
            return payload

        def early_outputd_status(
            releases: int,
            *,
            frames_received: int,
            frames_to_usb: int,
            ctrl_requests: int = 0,
        ) -> dict[str, Any]:
            payload = outputd_status(
                releases,
                frames_received=frames_received,
                frames_to_usb=frames_to_usb,
                ctrl_requests=ctrl_requests,
            )
            payload["pid"] = ready_pids["outputd"]
            payload["sockets"] = {
                "report": str(self.socket_paths["output_report"]),
                "ctrl": str(self.socket_paths["output_ctrl"]),
                "usb": str(self.socket_paths["hidd"]),
                "uidd": str(self.live / "disabled-uidd.sock"),
                "bt": str(self.live / "disabled-btd.sock"),
            }
            return payload

        def early_core_status(*, pressed: bool, broker_frames_sent: int) -> dict[str, Any]:
            payload = zero_core_status(
                pressed=pressed, broker_frames_sent=broker_frames_sent
            )
            payload["pid"] = ready_pids["logicd-core"]
            payload["matrix_socket"] = {
                "path": str(self.socket_paths["core_matrix"]),
                "listening": True,
            }
            payload["ctrl_socket"] = {
                "path": str(self.socket_paths["core_ctrl"]),
                "listening": True,
            }
            payload["broker_socket"]["path"] = str(
                self.socket_paths["output_report"]
            )
            return payload

        initial_hidd = early_hidd_status(2, 3, frames_received=4)
        write_json(self.live / "hidd-status.json", initial_hidd)
        initial_outputd = early_outputd_status(
            0, frames_received=4, frames_to_usb=4
        )
        write_json(
            self.live / "outputd-status.json",
            initial_outputd,
        )
        initial_core = early_core_status(pressed=True, broker_frames_sent=4)
        write_json(
            self.live / "logicd-core-status.json",
            initial_core,
        )
        write_json(
            self.live / "matrixd-status.json",
            {
                "schema": "matrixd.status.v1",
                "process": True,
                "configured": True,
                "gpio_ready": True,
                "logic_socket": {
                    "path": str(self.socket_paths["core_matrix"]),
                    "connected": True,
                },
                "pid": ready_pids["matrixd"],
            },
        )

        def core_handler(request: dict[str, Any]) -> dict[str, Any]:
            assert request == {"t": "release_all"}
            if self.failure == "core-control-endpoint-unavailable":
                for master, slave in self.recovery_ptys:
                    os.close(master)
                    os.close(slave)
                self.recovery_ptys.clear()
                return {"result": "error", "error": "injected_endpoint_unavailable"}
            if self.failure == "core-control":
                return {"result": "error", "error": "injected_core_control_failure"}
            write_json(
                self.live / "logicd-core-status.json",
                early_core_status(
                    pressed=self.failure == "core-status",
                    broker_frames_sent=6,
                ),
            )

            def publish_drain_only_after_core_death() -> None:
                deadline = time.monotonic() + 2
                while HANDOFF.identity_is_live(
                    Path("/proc"), self.identities["logicd-core"]
                ):
                    assert time.monotonic() < deadline
                    time.sleep(0.002)
                if self.failure in ("core-status", "queue-drain"):
                    return
                # Two reports remain queued when the core release status is
                # published.  Advancing only after core death makes a transient
                # equality check, or release-before-stop ordering, fail.
                write_json(
                    self.live / "outputd-status.json",
                    early_outputd_status(
                        0, frames_received=6, frames_to_usb=6
                    ),
                )
                write_json(
                    self.live / "hidd-status.json",
                    early_hidd_status(2, 3, frames_received=6),
                )

            worker = threading.Thread(
                target=publish_drain_only_after_core_death, daemon=True
            )
            self.workers.append(worker)
            worker.start()
            return {"result": "ok", "released": True}

        def output_handler(request: dict[str, Any]) -> dict[str, Any]:
            assert request == {"t": "release_all"}
            if self.failure == "output-control":
                return {"result": "error", "error": "injected_output_control_failure"}
            if HANDOFF.identity_is_live(Path("/proc"), self.identities["logicd-core"]):
                return {"result": "error", "error": "core_still_live"}
            output_status = json.loads(
                (self.live / "outputd-status.json").read_text(encoding="utf-8")
            )
            hidd = json.loads(
                (self.live / "hidd-status.json").read_text(encoding="utf-8")
            )
            if (
                output_status["counters"]["frames_received"] != 6
                or output_status["counters"]["frames_to_usb"] != 6
                or hidd["counters"]["frames_received"] != 6
            ):
                return {"result": "error", "error": "queued_frames_not_drained"}
            if self.failure != "output-status":
                write_json(
                    self.live / "outputd-status.json",
                    early_outputd_status(
                        2, frames_received=6, frames_to_usb=6, ctrl_requests=1
                    ),
                )

            def publish_final_only_after_outputd_death() -> None:
                deadline = time.monotonic() + 2
                while HANDOFF.identity_is_live(Path("/proc"), self.identities["outputd"]):
                    assert time.monotonic() < deadline
                    time.sleep(0.002)
                if self.failure in ("output-status", "hidd-final"):
                    return
                # The hidd equality is only stable after its sole producer is
                # dead; expose the two endpoint zeros at that point.
                write_json(
                    self.live / "hidd-status.json",
                    early_hidd_status(3, 4, frames_received=8),
                )

            worker = threading.Thread(
                target=publish_final_only_after_outputd_death, daemon=True
            )
            self.workers.append(worker)
            worker.start()
            return {
                "result": "ok",
                "release": {"attempted": 2, "delivered": 2, "errors": 0},
            }

        self.servers = [
            ControlServer(
                self.socket_paths["core_ctrl"],
                core_handler,
                self.early_sockets["core_ctrl"],
            ),
            ControlServer(
                self.socket_paths["output_ctrl"],
                output_handler,
                self.early_sockets["output_ctrl"],
            ),
        ]

    def args(self, command: str) -> list[str]:
        common = [
            str(TOOL),
            command,
            "--ready",
            str(self.ready),
            "--runtime-contract",
            str(self.contract),
            "--prepare-evidence",
            str(self.prepare),
            "--proc-root",
            "/proc",
            "--expected-owner-uid",
            str(self.uid),
            "--status-timeout",
            "0.2" if self.failure is not None else "2",
            "--poll-interval",
            "0.005",
        ]
        if command == "prepare":
            return common + [
                "--pid-dir",
                str(self.pids),
                "--live-root",
                str(self.live),
                "--discovery-live-root",
                str(self.live),
                "--stop-timeout",
                "1",
                "--failure-evidence",
                str(self.failure_evidence),
                "--recovery-hidg0",
                str(self.recovery_hidg0),
                "--recovery-hidg2",
                str(self.recovery_hidg2),
                "--early-hidg0",
                str(self.early_hidg0),
                "--early-hidg2",
                str(self.early_hidg2),
                "--recovery-udc",
                str(self.recovery_udc),
            ]
        normal = self.root / "normal"
        return common + [
            "--complete-evidence",
            str(self.complete),
            "--normal-hidd-status",
            str(normal / "hidd.json"),
            "--normal-outputd-status",
            str(normal / "outputd.json"),
            "--normal-core-status",
            str(normal / "core.json"),
            "--normal-matrix-status",
            str(normal / "matrix.json"),
            "--normal-hidd-exe",
            "/bin/sleep",
            "--normal-outputd-exe",
            "/bin/sleep",
            "--normal-core-exe",
            "/bin/sleep",
            "--normal-matrix-exe",
            "/bin/sleep",
            "--normal-hidg0",
            str(self.recovery_hidg0),
            "--normal-hidg2",
            str(self.recovery_hidg2),
        ]

    def write_normal_status(
        self,
        *,
        pressed: bool = False,
        foreign_socket: str | None = None,
        foreign_endpoint: bool = False,
    ) -> None:
        normal = self.root / "normal"
        normal.mkdir(mode=0o700)
        socket_paths = {
            "hidd": normal / "hidd.sock",
            "output_report": normal / "output-report.sock",
            "output_ctrl": normal / "output-ctrl.sock",
            "core_matrix": normal / "matrix-events.sock",
            "core_ctrl": normal / "core-ctrl.sock",
        }
        normal_socket_objects: dict[str, socket.socket] = {}
        for key, path in socket_paths.items():
            kind = (
                socket.SOCK_STREAM
                if key in ("output_ctrl", "core_matrix", "core_ctrl")
                else socket.SOCK_DGRAM
            )
            live_socket = socket.socket(socket.AF_UNIX, kind)
            live_socket.bind(str(path))
            if kind == socket.SOCK_STREAM:
                live_socket.listen(1)
            self.normal_sockets.append(live_socket)
            normal_socket_objects[key] = live_socket
        matrix_client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        matrix_client.connect(str(socket_paths["core_matrix"]))
        matrix_accepted, _ = normal_socket_objects["core_matrix"].accept()
        self.normal_connections.extend((matrix_client, matrix_accepted))
        socket_owners = {
            "hidd": "hidd",
            "output_report": "outputd",
            "output_ctrl": "outputd",
            "core_matrix": "logicd-core",
            "core_ctrl": "logicd-core",
        }
        if foreign_socket is not None:
            assert foreign_socket in socket_owners
            socket_owners[foreign_socket] = "matrixd"
        endpoint_owner = "matrixd" if foreign_endpoint else "hidd"
        normal_pids: dict[str, int] = {}
        for label in ("hidd", "outputd", "logicd-core", "matrixd"):
            inherited_fds = [
                live_socket.fileno()
                for socket_key, live_socket in normal_socket_objects.items()
                if socket_owners[socket_key] == label
            ]
            if label == endpoint_owner:
                inherited_fds.extend(slave for _, slave in self.recovery_ptys)
            process = subprocess.Popen(
                ["/bin/sleep", "30"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                pass_fds=tuple(inherited_fds),
            )
            self.normal_processes.append(process)
            normal_pids[label] = process.pid

        hidd = hidd_status(10, 10)
        hidd["pid"] = normal_pids["hidd"]
        hidd["socket"] = {"path": str(socket_paths["hidd"]), "listening": True}
        hidd["endpoints"]["hidg0"]["path"] = str(self.recovery_hidg0)
        hidd["endpoints"]["hidg2"]["path"] = str(self.recovery_hidg2)
        write_json(normal / "hidd.json", hidd)
        output = outputd_status(10)
        output["target"] = "auto"
        output["pid"] = normal_pids["outputd"]
        output["sockets"] = {
            "report": str(socket_paths["output_report"]),
            "ctrl": str(socket_paths["output_ctrl"]),
            "usb": str(socket_paths["hidd"]),
            "uidd": str(normal / "uidd.sock"),
            "bt": str(normal / "bt.sock"),
        }
        write_json(normal / "outputd.json", output)
        core = zero_core_status(pressed=pressed)
        core["pid"] = normal_pids["logicd-core"]
        core["matrix_socket"] = {
            "path": str(socket_paths["core_matrix"]),
            "listening": True,
        }
        core["ctrl_socket"] = {
            "path": str(socket_paths["core_ctrl"]),
            "listening": True,
        }
        core["broker_socket"]["path"] = str(socket_paths["output_report"])
        # Real logicd-core starts in this state and only flips available after
        # its first report/control request.  Finalize must accept an idle boot.
        core["broker_socket"]["available"] = False
        write_json(normal / "core.json", core)
        write_json(
            normal / "matrix.json",
            {
                "schema": "matrixd.status.v1",
                "process": True,
                "configured": True,
                "gpio_ready": True,
                "logic_socket": {
                    "path": str(socket_paths["core_matrix"]),
                    "connected": True,
                },
                "pid": normal_pids["matrixd"],
            },
        )

    def close(self) -> None:
        for server in self.servers:
            server.close()
        for early_socket in self.early_sockets.values():
            early_socket.close()
        for connection in self.early_connections:
            connection.close()
        for label, pidfd in self.cleanup_pidfds.items():
            try:
                if not HANDOFF.pidfd_has_exited(pidfd):
                    signal.pidfd_send_signal(pidfd, signal.SIGKILL)
            except OSError:
                pass
            finally:
                os.close(pidfd)
        for runner in self.runners:
            try:
                runner.wait(timeout=2)
            except subprocess.TimeoutExpired:
                runner.kill()
                runner.wait(timeout=2)
        for worker in self.workers:
            worker.join(timeout=2)
        for live_socket in self.normal_sockets:
            live_socket.close()
        for connection in self.normal_connections:
            connection.close()
        for process in self.normal_processes:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=2)
        for master, slave in self.recovery_ptys:
            os.close(master)
            os.close(slave)


def run(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", *arguments],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def read_exact_fd(fd: int, size: int, timeout: float = 2.0) -> bytes:
    result = bytearray()
    deadline = time.monotonic() + timeout
    while len(result) < size:
        remaining = deadline - time.monotonic()
        assert remaining > 0, (size, bytes(result))
        readable, _, _ = select.select([fd], [], [], remaining)
        assert readable, (size, bytes(result))
        result.extend(os.read(fd, size - len(result)))
    return bytes(result)


def successful_handoff(root: Path) -> None:
    fixture = Fixture(root / "success")
    try:
        unix_rows = [
            line
            for line in Path("/proc/net/unix").read_text(encoding="ascii").splitlines()
            if line.split(maxsplit=7)[-1] == str(fixture.socket_paths["core_matrix"])
        ]
        assert len(unix_rows) >= 2, unix_rows
        udc = fixture.root / "configfs/cqa02303v5/UDC"
        udc.parent.mkdir(parents=True)
        udc.write_text("fixture.udc\n", encoding="ascii")
        prepared = run(fixture.args("prepare"))
        assert prepared.returncode == 0, (prepared.stdout, prepared.stderr)
        assert json.loads(prepared.stdout)["status"] == "prepared"
        evidence = json.loads(fixture.prepare.read_text(encoding="utf-8"))
        assert evidence["status"] == "prepared"
        assert all("_pidfd" not in process for process in evidence["processes"].values())
        assert evidence["stop_order"] == ["matrixd", "logicd-core", "outputd", "hidd"]
        assert evidence["release"]["hidd_zero_before"] == {"main": 2, "us_sub": 3}
        assert evidence["release"]["hidd_zero_after"] == {"main": 3, "us_sub": 4}
        assert evidence["release"]["outputd_response"]["release"] == {
            "attempted": 2,
            "delivered": 2,
            "errors": 0,
        }
        assert evidence["release"]["queue_barrier"] == {
            "core_broker_frames_sent": 6,
            "outputd_release_frames_before": 0,
            "outputd_control_requests_before": 0,
            "outputd_frames_received": 6,
            "outputd_frames_to_usb": 6,
            "hidd_frames_received_before_release": 6,
            "hidd_frames_received_after_release": 8,
        }
        assert stat_mode(fixture.prepare) == 0o600
        assert udc.read_text(encoding="ascii") == "fixture.udc\n"

        # Finalize is a readiness gate, not an idle-state gate.  A legitimate
        # key may already be held after the normal input chain takes over.
        fixture.write_normal_status(pressed=True)
        finalize_args = HANDOFF.build_parser().parse_args(fixture.args("finalize")[1:])
        hidd_path = fixture.root / "normal/hidd.json"
        valid_hidd = json.loads(hidd_path.read_text(encoding="utf-8"))
        stale_hidd = json.loads(json.dumps(valid_hidd))
        stale_hidd["pid"] = 2_000_000_000
        write_json(hidd_path, stale_hidd)
        try:
            HANDOFF.normal_status_probe(finalize_args)
        except HANDOFF.HandoffError as exc:
            assert "pidfd_open" in str(exc)
        else:
            raise AssertionError("stale normal hidd status was accepted")
        write_json(hidd_path, valid_hidd)

        core_path = fixture.root / "normal/core.json"
        valid_core = json.loads(core_path.read_text(encoding="utf-8"))
        disabled_core = json.loads(json.dumps(valid_core))
        disabled_core["output_enabled"] = False
        write_json(core_path, disabled_core)
        assert HANDOFF.normal_status_probe(finalize_args) is None
        write_json(core_path, valid_core)

        broker_error_core = json.loads(json.dumps(valid_core))
        broker_error_core["broker_socket"]["last_error"] = "fixture broker failure"
        write_json(core_path, broker_error_core)
        assert HANDOFF.normal_status_probe(finalize_args) is None
        write_json(core_path, valid_core)

        not_released_hidd = json.loads(json.dumps(valid_hidd))
        not_released_hidd["counters"]["startup_release_reports"] = 0
        write_json(hidd_path, not_released_hidd)
        assert HANDOFF.normal_status_probe(finalize_args) is None
        write_json(hidd_path, valid_hidd)

        output_path = fixture.root / "normal/outputd.json"
        valid_output = json.loads(output_path.read_text(encoding="utf-8"))
        wrong_route = json.loads(json.dumps(valid_output))
        wrong_route["sockets"]["usb"] = wrong_route["sockets"]["report"]
        write_json(output_path, wrong_route)
        try:
            HANDOFF.normal_status_probe(finalize_args)
        except HANDOFF.HandoffError as exc:
            assert "USB route" in str(exc)
        else:
            raise AssertionError("mismatched normal USB route was accepted")
        write_json(output_path, valid_output)

        wrong_endpoint = json.loads(json.dumps(valid_hidd))
        wrong_endpoint["endpoints"]["hidg0"]["path"] = str(fixture.recovery_hidg2)
        write_json(hidd_path, wrong_endpoint)
        try:
            HANDOFF.normal_status_probe(finalize_args)
        except HANDOFF.HandoffError as exc:
            assert "hidg0 path mismatch" in str(exc)
        else:
            raise AssertionError("mismatched normal endpoint was accepted")
        write_json(hidd_path, valid_hidd)
        completed = run(fixture.args("finalize"))
        assert completed.returncode == 0, (completed.stdout, completed.stderr)
        assert json.loads(completed.stdout)["status"] == "complete"
        complete = json.loads(fixture.complete.read_text(encoding="utf-8"))
        assert complete["status"] == "complete"
        assert complete["prepare_evidence_sha256"] == hashlib.sha256(
            fixture.prepare.read_bytes()
        ).hexdigest()
        assert stat_mode(fixture.complete) == 0o600

        retried = run(fixture.args("finalize"))
        assert retried.returncode == 78
        assert "refusing to overwrite existing evidence" in retried.stderr
    finally:
        fixture.close()


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def identity_mismatch_is_action_free(root: Path) -> None:
    fixture = Fixture(root / "identity-negative")
    try:
        path = fixture.pids / "outputd.pid"
        fields = path.read_text(encoding="ascii").split()
        fields[3] = str(int(fields[3]) + 1)
        path.write_text(" ".join(fields) + "\n", encoding="ascii")
        path.chmod(0o600)
        result = run(fixture.args("prepare"))
        assert result.returncode == 78, (result.stdout, result.stderr)
        assert "executable inode mismatch" in result.stderr
        assert "authentication recovery=unbound" in result.stderr
        assert not fixture.prepare.exists()
        assert fixture.recovery_udc.read_text(encoding="ascii").strip() == ""
        assert json.loads(fixture.failure_evidence.read_text(encoding="utf-8"))[
            "status"
        ] == "unbound"
        for identity in fixture.identities.values():
            assert HANDOFF.identity_is_live(Path("/proc"), identity)
    finally:
        fixture.close()


def release_contract_is_required(root: Path) -> None:
    fixture = Fixture(root / "release-contract-negative")
    try:
        contract = json.loads(fixture.contract.read_text(encoding="utf-8"))
        del contract["native_input"]["handoff_release"]
        contract_bytes = write_json(fixture.contract, contract)
        ready = json.loads(fixture.ready.read_text(encoding="utf-8"))
        ready["runtime_contract_sha256"] = hashlib.sha256(contract_bytes).hexdigest()
        write_json(fixture.ready, ready)
        result = run(fixture.args("prepare"))
        assert result.returncode == 78, (result.stdout, result.stderr)
        assert "handoff release contract" in result.stderr
        assert "authentication recovery=unbound" in result.stderr
        assert not fixture.prepare.exists()
        assert fixture.recovery_udc.read_text(encoding="ascii").strip() == ""
        for identity in fixture.identities.values():
            assert HANDOFF.identity_is_live(Path("/proc"), identity)
    finally:
        fixture.close()


def post_action_failures_release_or_disconnect(root: Path) -> None:
    for failure in (
        "core-control",
        "core-status",
        "queue-drain",
        "output-control",
        "output-status",
        "hidd-final",
    ):
        fixture = Fixture(root / f"post-action-{failure}", failure=failure)
        try:
            result = run(fixture.args("prepare"))
            assert result.returncode == 78, (failure, result.stdout, result.stderr)
            assert "post-action recovery=released" in result.stderr
            evidence = json.loads(fixture.failure_evidence.read_text(encoding="utf-8"))
            assert evidence["schema"] == HANDOFF.FAILURE_SCHEMA
            assert evidence["status"] == "released"
            assert evidence["all_processes_dead"] is True
            assert evidence["udc"] == {"status": "not-required"}
            assert read_exact_fd(fixture.recovery_ptys[0][0], 9) == bytes.fromhex(
                "010000000000000000"
            )
            assert read_exact_fd(fixture.recovery_ptys[1][0], 8) == bytes(8)
            assert fixture.recovery_udc.read_text(encoding="ascii") == "fixture.udc\n"
            for identity in fixture.identities.values():
                assert not HANDOFF.identity_is_live(Path("/proc"), identity)
        finally:
            fixture.close()

    fixture = Fixture(
        root / "post-action-unbind",
        failure="core-control-endpoint-unavailable",
    )
    try:
        result = run(fixture.args("prepare"))
        assert result.returncode == 78, (result.stdout, result.stderr)
        assert "post-action recovery=unbound" in result.stderr
        evidence = json.loads(fixture.failure_evidence.read_text(encoding="utf-8"))
        assert evidence["status"] == "unbound"
        assert evidence["endpoint_release"]["status"] == "error"
        assert evidence["udc"]["status"] == "unbound"
        assert fixture.recovery_udc.read_text(encoding="ascii").strip() == ""
    finally:
        fixture.close()


def early_topology_failures_are_action_free(root: Path) -> None:
    def wrong_status_pid(fixture: Fixture) -> None:
        path = fixture.live / "hidd-status.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["pid"] = fixture.identities["outputd"]["pid"]
        write_json(path, payload)

    def wrong_usb_route(fixture: Fixture) -> None:
        path = fixture.live / "outputd-status.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["sockets"]["usb"] = payload["sockets"]["report"]
        write_json(path, payload)

    def wrong_endpoint(fixture: Fixture) -> None:
        path = fixture.live / "hidd-status.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["endpoints"]["hidg0"]["path"] = str(fixture.early_hidg2)
        write_json(path, payload)

    cases = (
        ("status-pid", None, wrong_status_pid, "status PID"),
        ("usb-route", None, wrong_usb_route, "USB socket path mismatch"),
        ("endpoint", None, wrong_endpoint, "hidg0 path mismatch"),
        ("foreign-owner", "hidd", None, "not owned by authenticated PID"),
    )
    for name, foreign_socket, mutate, error_fragment in cases:
        fixture = Fixture(
            root / f"early-topology-{name}", foreign_socket=foreign_socket
        )
        try:
            if mutate is not None:
                mutate(fixture)
            result = run(fixture.args("prepare"))
            assert result.returncode == 78, (name, result.stdout, result.stderr)
            assert error_fragment in result.stderr, (name, result.stderr)
            assert "pre-action recovery=unbound" in result.stderr
            assert not fixture.prepare.exists()
            assert fixture.recovery_udc.read_text(encoding="ascii").strip() == ""
            evidence = json.loads(
                fixture.failure_evidence.read_text(encoding="utf-8")
            )
            assert evidence["phase"] == "pre-action"
            assert evidence["status"] == "unbound"
            for identity in fixture.identities.values():
                assert HANDOFF.identity_is_live(Path("/proc"), identity)
        finally:
            fixture.close()


def normal_owner_failures_are_rejected(root: Path) -> None:
    cases = (
        ("foreign-socket", {"foreign_socket": "hidd"}, "not owned by authenticated PID"),
        ("foreign-endpoint", {"foreign_endpoint": True}, "is not open in authenticated PID"),
    )
    for name, options, error_fragment in cases:
        fixture = Fixture(root / f"normal-owner-{name}")
        try:
            prepared = run(fixture.args("prepare"))
            assert prepared.returncode == 0, (name, prepared.stdout, prepared.stderr)
            fixture.write_normal_status(**options)
            finalize_args = HANDOFF.build_parser().parse_args(
                fixture.args("finalize")[1:]
            )
            try:
                proof = HANDOFF.normal_status_probe(finalize_args)
            except HANDOFF.HandoffError as exc:
                assert error_fragment in str(exc), (name, str(exc))
            else:
                raise AssertionError(
                    f"foreign normal owner was accepted for {name}: {proof}"
                )
            assert not fixture.complete.exists()
            for process in fixture.normal_processes:
                assert process.poll() is None
        finally:
            fixture.close()


def numeric_pid_without_pidfd_is_action_free() -> None:
    process = subprocess.Popen(
        ["/bin/sleep", "30"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        proc = Path("/proc") / str(process.pid)
        identity = {
            "pid": process.pid,
            "starttime": HANDOFF.proc_stat_starttime(proc / "stat", "pidfd-negative"),
            "exe_dev": (proc / "exe").stat().st_dev,
            "exe_ino": (proc / "exe").stat().st_ino,
        }
        try:
            HANDOFF.stop_identity(Path("/proc"), identity, "pidfd-negative", 0.1, 0.005)
        except HANDOFF.HandoffError as exc:
            assert "no authenticated pidfd" in str(exc)
        else:
            raise AssertionError("numeric PID was accepted without a pidfd")
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=2)


def discovery_paths(root: Path) -> None:
    absent = root / "absent"
    absent.mkdir(mode=0o700)
    result = run(
        [
            str(TOOL),
            "prepare",
            "--ready",
            str(absent / "ready.json"),
            "--discovery-live-root",
            str(absent / "live"),
            "--expected-owner-uid",
            str(os.getuid()),
        ]
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert json.loads(result.stdout)["status"] == "not-applicable"

    racing = root / "race"
    racing.mkdir(mode=0o700)
    live = racing / "live"
    live.mkdir(mode=0o700)
    assert stat.S_IMODE(racing.stat().st_mode) == 0o700
    assert stat.S_IMODE(live.stat().st_mode) == 0o700
    (live / "chain-ready").touch(mode=0o600)
    recovery_udc = racing / "UDC"
    recovery_udc.write_text("fixture.udc\n", encoding="ascii")
    recovery_udc.chmod(0o600)
    result = run(
        [
            str(TOOL),
            "prepare",
            "--ready",
            str(racing / "ready.json"),
            "--discovery-live-root",
            str(live),
            "--discovery-timeout",
            "0.05",
            "--poll-interval",
            "0.005",
            "--expected-owner-uid",
            str(os.getuid()),
            "--failure-evidence",
            str(racing / "failure.json"),
            "--recovery-udc",
            str(recovery_udc),
        ]
    )
    assert result.returncode == 78, (result.stdout, result.stderr)
    assert "official ready or safe cleanup did not appear" in result.stderr
    assert "staged discovery recovery=unbound" in result.stderr
    assert recovery_udc.read_text(encoding="ascii").strip() == ""
    assert json.loads((racing / "failure.json").read_text(encoding="utf-8"))[
        "status"
    ] == "unbound"

    staged = root / "staged-transition"
    staged.mkdir(mode=0o700)
    staged_live = staged / "live"
    staged_live.mkdir(mode=0o700)
    (staged_live / "chain-staged").touch(mode=0o600)
    staged_ready = staged / "ready.json"
    wait_args = argparse.Namespace(
        ready=staged_ready,
        discovery_live_root=staged_live,
        discovery_timeout=0.3,
        poll_interval=0.005,
        expected_owner_uid=os.getuid(),
    )

    def publish_ready() -> None:
        time.sleep(0.03)
        write_json(staged_ready, {"state": "fixture"})

    publisher = threading.Thread(target=publish_ready, daemon=True)
    publisher.start()
    assert HANDOFF.wait_for_ready(wait_args) is True
    publisher.join(timeout=1)

    staged_ready.unlink()
    (staged_live / "cleanup.state").write_text("released\n", encoding="ascii")
    (staged_live / "cleanup.state").chmod(0o600)
    assert HANDOFF.wait_for_ready(wait_args) is False

    finalize = run(
        [
            str(TOOL),
            "finalize",
            "--prepare-evidence",
            str(absent / "prepare.json"),
            "--expected-owner-uid",
            str(os.getuid()),
        ]
    )
    assert finalize.returncode == 0, (finalize.stdout, finalize.stderr)
    assert json.loads(finalize.stdout)["status"] == "not-applicable"


def unit_contract() -> None:
    usb = (ROOT / "system/systemd/hidloom-usb-gadget.service").read_text(encoding="utf-8")
    outputd = (ROOT / "system/systemd/hidloom-outputd.service").read_text(encoding="utf-8")
    core = (ROOT / "system/systemd/hidloom-logicd-core.service").read_text(encoding="utf-8")
    matrix = (ROOT / "system/systemd/matrixd.service").read_text(encoding="utf-8")
    prepare = (
        ROOT / "system/systemd/hidloom-early-input-handoff-prepare.service"
    ).read_text(encoding="utf-8")
    finalize = (
        ROOT / "system/systemd/hidloom-early-input-handoff-finalize.service"
    ).read_text(encoding="utf-8")
    assert "Requires=hidloom-early-input-handoff-prepare.service" in usb
    assert "After=hidloom-early-input-handoff-prepare.service" in usb
    for unit in (outputd, core, matrix):
        assert "Requires=hidloom-early-input-handoff-prepare.service" in unit
        assert "After=hidloom-early-input-handoff-prepare.service" in unit
    assert "Before=hidloom-usb-gadget.service" in prepare
    assert "ConditionPathExists" not in prepare
    assert "Wants=hidloom-early-input-handoff-finalize.service" in matrix
    assert "After=hidloom-logicd-core.service matrixd.service" in finalize
    assert "ConditionPathExists" not in finalize
    for option in (
        "--normal-hidd-exe @HIDLOOM_REPO_ROOT@/bin/hidloom-hidd",
        "--normal-outputd-exe @HIDLOOM_REPO_ROOT@/bin/hidloom-outputd",
        "--normal-core-exe @HIDLOOM_REPO_ROOT@/bin/hidloom-logicd-core",
        "--normal-matrix-exe @HIDLOOM_REPO_ROOT@/daemon/matrixd/matrixd",
    ):
        assert option in finalize
    source = TOOL.read_text(encoding="utf-8")
    assert "keyboard_zero_reports" in source
    assert "us_sub_keyboard_zero_reports" in source
    assert "exe_dev" in source and "exe_ino" in source
    assert "os.pidfd_open" in source
    assert "signal.pidfd_send_signal" in source
    assert "os.kill(" not in source
    assert "verified_udc_unbind" in source
    assert "post-action recovery" in source
    success_body = source.split("def run_prepare_with_context", 1)[1].split(
        "def normal_status_probe", 1
    )[0]
    assert "verified_udc_unbind" not in success_body


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="hidloom-early-input-handoff-") as directory:
        root = Path(directory)
        successful_handoff(root)
        identity_mismatch_is_action_free(root)
        release_contract_is_required(root)
        early_topology_failures_are_action_free(root)
        post_action_failures_release_or_disconnect(root)
        normal_owner_failures_are_rejected(root)
        discovery_paths(root)
    numeric_pid_without_pidfd_is_action_free()
    unit_contract()
    print("ok: Raspberry Pi OS E4 early input handoff")


if __name__ == "__main__":
    main()
