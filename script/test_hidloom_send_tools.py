#!/usr/bin/env python3
"""Regression tests for the lightweight C socket helper commands."""
from __future__ import annotations

import socket
import subprocess
import tempfile
import threading
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL_DIR = ROOT / "tools" / "hidloom_send"
COMMAND_DIR = TOOL_DIR / ".build"


def _collect_from_unix_socket(command: list[str], expected_len: int) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        sock_path = Path(tmp) / "test.sock"
        ready = threading.Event()
        received = bytearray()
        errors: list[BaseException] = []

        def serve() -> None:
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                    server.bind(str(sock_path))
                    server.listen(1)
                    ready.set()
                    conn, _ = server.accept()
                    with conn:
                        while len(received) < expected_len:
                            chunk = conn.recv(expected_len - len(received))
                            if not chunk:
                                break
                            received.extend(chunk)
            except BaseException as exc:  # pragma: no cover - surfaced below
                errors.append(exc)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        assert ready.wait(2.0), "test socket server did not start"
        subprocess.run([*command[:1], "--socket", str(sock_path), *command[1:]], check=True)
        thread.join(2.0)
        assert not thread.is_alive(), "command did not close socket"
        assert not errors, errors
        return bytes(received)


def _request_response_unix_socket(command: list[str], response: bytes) -> tuple[bytes, bytes]:
    with tempfile.TemporaryDirectory() as tmp:
        sock_path = Path(tmp) / "test.sock"
        ready = threading.Event()
        received = bytearray()
        errors: list[BaseException] = []

        def serve() -> None:
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                    server.bind(str(sock_path))
                    server.listen(1)
                    ready.set()
                    conn, _ = server.accept()
                    with conn:
                        while b"\n" not in received:
                            chunk = conn.recv(256)
                            if not chunk:
                                break
                            received.extend(chunk)
                        conn.sendall(response)
            except BaseException as exc:  # pragma: no cover - surfaced below
                errors.append(exc)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        assert ready.wait(2.0), "test socket server did not start"
        completed = subprocess.run(
            [*command[:1], "--socket", str(sock_path), *command[1:]],
            check=True,
            stdout=subprocess.PIPE,
        )
        thread.join(2.0)
        assert not thread.is_alive(), "command did not close socket"
        assert not errors, errors
        return bytes(received), completed.stdout


def test_hidloom_key_tap_packet() -> None:
    data = _collect_from_unix_socket(
        [
            str(COMMAND_DIR / "hidloom-key"),
            "--hold-us",
            "1000",
            "--gap-us",
            "1000",
            "tap",
            "0x0204",
        ],
        8,
    )
    assert data == bytes([0x50, 0x04, 0x02, 0x00, 0x52, 0x04, 0x02, 0x00])


def test_hidloom_key_tap_sequence() -> None:
    data = _collect_from_unix_socket(
        [
            str(COMMAND_DIR / "hidloom-key"),
            "--hold-us",
            "1000",
            "--gap-us",
            "1000",
            "tap",
            "0x0204",
            "0x05",
        ],
        16,
    )
    assert data == bytes(
        [
            0x50,
            0x04,
            0x02,
            0x00,
            0x52,
            0x04,
            0x02,
            0x00,
            0x50,
            0x05,
            0x00,
            0x00,
            0x52,
            0x05,
            0x00,
            0x00,
        ]
    )


def test_hidloom_key_press_chord_packet() -> None:
    data = _collect_from_unix_socket(
        [
            str(COMMAND_DIR / "hidloom-key"),
            "press",
            "0x0204",
        ],
        4,
    )
    assert data == bytes([0x50, 0x04, 0x02, 0x00])


def test_hidloom_keytext_ascii_mapping() -> None:
    data = _collect_from_unix_socket(
        [
            str(COMMAND_DIR / "hidloom-keytext"),
            "--hold-us",
            "1000",
            "--gap-us",
            "1000",
            "A\\n",
        ],
        16,
    )
    assert data == bytes(
        [
            0x50,
            0x04,
            0x02,
            0x00,
            0x52,
            0x04,
            0x02,
            0x00,
            0x50,
            0x28,
            0x00,
            0x00,
            0x52,
            0x28,
            0x00,
            0x00,
        ]
    )


def test_hidloom_oled_warning_json() -> None:
    expected = b'{"t":"warning","msg":"Hi\\nThere","sec":1.500}\n'
    data = _collect_from_unix_socket(
        [
            str(COMMAND_DIR / "hidloom-oled"),
            "warning",
            "Hi\nThere",
            "1.5",
        ],
        len(expected),
    )
    assert data == expected


def test_hidloom_notify_warning_json() -> None:
    expected = b'{"t":"warning","msg":"Script failed","sec":3.000}\n'
    data = _collect_from_unix_socket(
        [
            str(COMMAND_DIR / "hidloom-notify"),
            "warning",
            "Script failed",
            "3",
        ],
        len(expected),
    )
    assert data == expected


def test_hidloom_ctrl_json_roundtrip() -> None:
    sent, stdout = _request_response_unix_socket(
        [
            str(COMMAND_DIR / "hidloom-ctrl"),
            "json",
            '{"t":"G"}',
        ],
        b'{"t":"keymap","result":"ok"}\n',
    )
    assert sent == b'{"t":"G"}\n'
    assert stdout == b'{"t":"keymap","result":"ok"}\n'


def test_hidloom_ctrl_layer_shortcuts() -> None:
    sent, stdout = _request_response_unix_socket(
        [
            str(COMMAND_DIR / "hidloom-ctrl"),
            "layer",
            "clear",
            "2",
        ],
        b'{"t":"LAYER_CLEAR","result":"ok","layer":2}\n',
    )
    assert sent == b'{"t":"LAYER_CLEAR","l":2}\n'
    assert stdout == b'{"t":"LAYER_CLEAR","result":"ok","layer":2}\n'


def test_hidloom_ctrl_runtime_shortcuts() -> None:
    sent, stdout = _request_response_unix_socket(
        [
            str(COMMAND_DIR / "hidloom-ctrl"),
            "output",
            "bt",
        ],
        b'{"t":"OUTPUT","result":"ok","target":"bt"}\n',
    )
    assert sent == b'{"t":"OUTPUT","target":"bt"}\n'
    assert stdout == b'{"t":"OUTPUT","result":"ok","target":"bt"}\n'

    sent, stdout = _request_response_unix_socket(
        [
            str(COMMAND_DIR / "hidloom-ctrl"),
            "bt",
            "pairing-toggle",
        ],
        b'{"t":"BT","result":"ok","action":"BT_PAIRING_TOGGLE"}\n',
    )
    assert sent == b'{"t":"BT","action":"BT_PAIRING_TOGGLE"}\n'
    assert stdout == b'{"t":"BT","result":"ok","action":"BT_PAIRING_TOGGLE"}\n'

    sent, stdout = _request_response_unix_socket(
        [
            str(COMMAND_DIR / "hidloom-ctrl"),
            "led",
            "effect",
            "40",
            "128",
            "175",
            "77",
            "160",
        ],
        b'{"t":"LED","result":"ok"}\n',
    )
    assert sent == b'{"t":"LED","op":"vialrgb","mode":40,"speed":128,"h":175,"s":77,"v":160}\n'
    assert stdout == b'{"t":"LED","result":"ok"}\n'


def test_hidloom_send_policy_docs() -> None:
    policy = (TOOL_DIR / "POLICY.md").read_text(encoding="utf-8")
    readme = (TOOL_DIR / "README.md").read_text(encoding="utf-8")

    assert "`hidloom-notify` は同じ OLED message を送り" in policy
    assert "`hidloom-ctrl layer ...` / `output ...` / `bt ...` / `led ...`" in policy
    assert "実運用でよく使う操作が見えてから増やす" in policy
    bin_readme = (ROOT / "bin" / "README.md").read_text(encoding="utf-8")
    assert "### hidloom-notify" in readme
    assert "bin/hidloom-ctrl led effect 40 128 175 77 160" in readme
    assert "`bin/hidloom-notify`" in bin_readme
    assert "`bin/hidloom-ctrl`" in bin_readme
    assert "`PATH` の先頭" in bin_readme


def main() -> None:
    global COMMAND_DIR

    if os.name == "nt" or not hasattr(socket, "AF_UNIX"):
        test_hidloom_send_policy_docs()
        print("skip: hidloom_send native helper smoke requires POSIX shell and Unix sockets")
        return

    with tempfile.TemporaryDirectory() as tmp:
        env = os.environ.copy()
        env["BIN_DIR"] = tmp
        subprocess.run([str(TOOL_DIR / "build.sh")], check=True, env=env)
        COMMAND_DIR = Path(tmp)
        for name in ["hidloom-key", "hidloom-keytext", "hidloom-oled", "hidloom-notify", "hidloom-ctrl"]:
            assert (COMMAND_DIR / name).exists(), name
        test_hidloom_key_tap_packet()
        test_hidloom_key_tap_sequence()
        test_hidloom_key_press_chord_packet()
        test_hidloom_keytext_ascii_mapping()
        test_hidloom_oled_warning_json()
        test_hidloom_notify_warning_json()
        test_hidloom_ctrl_json_roundtrip()
        test_hidloom_ctrl_layer_shortcuts()
        test_hidloom_ctrl_runtime_shortcuts()
        test_hidloom_send_policy_docs()
    print("ok: hidloom_send C helper commands")


if __name__ == "__main__":
    main()
