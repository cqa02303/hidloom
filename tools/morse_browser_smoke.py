#!/usr/bin/env python3
"""Headless Chromium smoke test for the Morse Interaction UI.

Run this from a workstation or other host with enough memory, pointing --url at
the keyboard HTTP UI. Do not run it on the 512MB Raspberry Pi device unless you
explicitly pass --allow-low-memory-device.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any


LOW_MEMORY_DEVICE_LIMIT_MIB = 1024


def total_memory_mib() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    except Exception:
        return None
    return None


def refuse_low_memory_device(args: argparse.Namespace) -> None:
    if args.allow_low_memory_device:
        return
    mem_mib = total_memory_mib()
    if mem_mib is not None and mem_mib < LOW_MEMORY_DEVICE_LIMIT_MIB:
        raise SystemExit(
            "refusing to start Chromium on a low-memory device "
            f"({mem_mib} MiB RAM). Run this helper from a workstation with --url "
            "pointing at the keyboard, or pass --allow-low-memory-device explicitly."
        )


class CdpClient:
    def __init__(self, ws_url: str) -> None:
        host_path = ws_url[len("ws://"):]
        host, path = host_path.split("/", 1)
        self.path = "/" + path
        self.host = host
        socket_host, socket_port = host.rsplit(":", 1) if ":" in host else (host, "80")
        self.sock = socket.create_connection((socket_host, int(socket_port)), timeout=10)
        self.sock.settimeout(None)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            response += self.sock.recv(4096)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError(response.decode(errors="ignore"))
        self._next_id = 0

    def close(self) -> None:
        self.sock.close()

    def _send_frame(self, text: str) -> None:
        payload = text.encode("utf-8")
        header = bytearray([0x81])
        size = len(payload)
        if size < 126:
            header.append(0x80 | size)
        elif size < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", size))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", size))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def _read_exact(self, size: int) -> bytes:
        data = b""
        while len(data) < size:
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                raise EOFError("websocket closed")
            data += chunk
        return data

    def _recv_frame(self) -> dict[str, Any]:
        first, second = self._read_exact(2)
        opcode = first & 0x0F
        size = second & 0x7F
        if size == 126:
            size = struct.unpack("!H", self._read_exact(2))[0]
        elif size == 127:
            size = struct.unpack("!Q", self._read_exact(8))[0]
        mask = self._read_exact(4) if second & 0x80 else b""
        payload = self._read_exact(size)
        if mask:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        if opcode == 8:
            raise EOFError("websocket close frame")
        if opcode == 9:
            return self._recv_frame()
        return json.loads(payload.decode("utf-8", errors="replace"))

    def call(self, method: str, params: dict[str, Any] | None = None, *, timeout: float = 60.0) -> dict[str, Any]:
        self._next_id += 1
        msg_id = self._next_id
        self._send_frame(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.sock.settimeout(max(0.2, min(5.0, deadline - time.time())))
            try:
                message = self._recv_frame()
            except socket.timeout:
                continue
            if message.get("id") == msg_id:
                return message
        raise TimeoutError(method)

    def evaluate(self, expression: str, *, timeout: float = 60.0) -> Any:
        response = self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True},
            timeout=timeout,
        )
        result = response.get("result", {})
        if "exceptionDetails" in result:
            raise RuntimeError(result["exceptionDetails"])
        return result.get("result", {}).get("value")


def wait_for_devtools(port: int, proc: subprocess.Popen[Any], timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"chromium exited: {proc.returncode}")
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1).read()
            return
        except Exception:
            time.sleep(0.2)
    raise TimeoutError("chromium devtools did not start")


def first_page_ws_url(port: int, *, timeout: float = 60.0) -> str:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            targets = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10).read().decode())
            for target in targets:
                if target.get("type") == "page":
                    return str(target["webSocketDebuggerUrl"])
        except Exception as exc:
            last_error = exc
        time.sleep(0.5)
    raise RuntimeError(f"no page target: {last_error}")


def wait_eval(client: CdpClient, expression: str, *, timeout: float = 60.0) -> Any:
    deadline = time.time() + timeout
    last: Any = None
    while time.time() < deadline:
        last = client.evaluate(expression, timeout=timeout)
        if last:
            return last
        time.sleep(0.5)
    raise TimeoutError(f"condition did not become true: {expression!r}; last={last!r}")


def run(args: argparse.Namespace) -> dict[str, Any]:
    user_data = tempfile.mkdtemp(prefix="hidloom-chrome-")
    stderr_target = subprocess.DEVNULL
    stderr_file = None
    if args.chromium_log:
        stderr_file = open(args.chromium_log, "w", encoding="utf-8")
        stderr_target = stderr_file
    proc = subprocess.Popen(
        [
            args.chromium,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-component-update",
            "--ignore-certificate-errors",
            f"--remote-debugging-port={args.port}",
            f"--user-data-dir={user_data}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=stderr_target,
    )
    client: CdpClient | None = None
    try:
        wait_for_devtools(args.port, proc, timeout=args.startup_timeout)
        client = CdpClient(first_page_ws_url(args.port, timeout=args.startup_timeout))
        client.call("Page.enable")
        client.call("Runtime.enable")
        client.call("Network.enable")
        token = base64.b64encode(f"{args.username}:{args.password}".encode("utf-8")).decode("ascii")
        client.call("Network.setExtraHTTPHeaders", {"headers": {"Authorization": f"Basic {token}"}})
        client.call("Emulation.setDeviceMetricsOverride", {
            "width": args.width,
            "height": args.height,
            "deviceScaleFactor": 1,
            "mobile": False,
        })
        client.call("Page.navigate", {"url": args.url})
        wait_eval(client, "document.readyState === 'complete'", timeout=args.page_timeout)
        client.evaluate("setActiveTab('interaction')", timeout=args.page_timeout)
        wait_eval(client, "!!document.getElementById('interaction-morse-name')", timeout=args.page_timeout)
        wait_eval(
            client,
            r"""(() => {
              const editor = document.getElementById("interaction-editor");
              if (!editor || !editor.value || !editor.value.trim().startsWith("{")) return false;
              try {
                const parsed = JSON.parse(editor.value);
                return parsed && typeof parsed === "object" && !Array.isArray(parsed);
              } catch (_err) {
                return false;
              }
            })()""",
            timeout=args.page_timeout,
        )

        result = client.evaluate(
            r"""(() => {
              const set = (id, value) => {
                const el = document.getElementById(id);
                if (!el) throw new Error(id + " missing");
                el.value = value;
                el.dispatchEvent(new Event("input", {bubbles: true}));
              };
              window.prompt = () => "ui_smoke";
              const selector = document.getElementById("interaction-morse-existing");
              selector.value = "__add_morse__";
              selector.dispatchEvent(new Event("change", {bubbles: true}));
              set("interaction-morse-dot", "0.180");
              set("interaction-morse-timeout", "0.330");
              set("interaction-morse-fallback", "KC_ESC");
              set("interaction-morse-force", ".-");
              set("interaction-morse-map", ".=KC_E\n-=KC_T\n.-=KC_A");
              applyMorseBehaviorBuilder();
              copyMorseActionForBuilder();
              const settings = JSON.parse(document.getElementById("interaction-editor").value);
              const def = settings.morse_behaviors && settings.morse_behaviors.ui_smoke;
              const count = (selector) => document.querySelectorAll(selector).length;
              return {
                hasDefinition: !!def,
                mapDot: def && def.map["."],
                mapDash: def && def.map["-"],
                mapA: def && def.map[".-"],
                force: def && def.force_commit && def.force_commit[0],
                fallback: def && def.fallback_action,
                status: document.getElementById("interaction-status")?.textContent?.trim(),
                copyStatus: document.getElementById("interaction-status")?.textContent?.trim(),
                rowCount: document.querySelectorAll(".interaction-morse-row").length,
                prefixRows: count(".interaction-morse-row.morse-prefix"),
                leafRows: count(".interaction-morse-row.morse-leaf"),
                forceRows: count(".interaction-morse-row.morse-force_commit"),
                cancelRows: count(".interaction-morse-row.morse-cancel"),
                inspector: document.getElementById("interaction-morse-inspector")?.textContent
                  ?.replace(/\s+/g, " ").trim().slice(0, 300),
              };
            })()""",
            timeout=args.page_timeout,
        )
        if args.screenshot:
            metrics = client.call("Page.getLayoutMetrics")["result"]["cssContentSize"]
            shot = client.call(
                "Page.captureScreenshot",
                {
                    "format": "png",
                    "captureBeyondViewport": True,
                    "clip": {
                        "x": 0,
                        "y": 0,
                        "width": min(metrics["width"], args.width),
                        "height": min(metrics["height"], args.screenshot_height),
                        "scale": 1,
                    },
                },
                timeout=args.page_timeout,
            )
            Path(args.screenshot).write_bytes(base64.b64decode(shot["result"]["data"]))
        return result
    finally:
        if client is not None:
            client.close()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(user_data, ignore_errors=True)
        if stderr_file is not None:
            stderr_file.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://127.0.0.1/")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="<keyboard-host>")
    parser.add_argument("--chromium", default="chromium")
    parser.add_argument("--port", type=int, default=9455)
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=1100)
    parser.add_argument("--screenshot-height", type=int, default=2200)
    parser.add_argument("--startup-timeout", type=float, default=90.0)
    parser.add_argument("--page-timeout", type=float, default=90.0)
    parser.add_argument("--screenshot", default="")
    parser.add_argument("--chromium-log", default="")
    parser.add_argument("--allow-low-memory-device", action="store_true")
    args = parser.parse_args()
    refuse_low_memory_device(args)
    result = run(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    expected = {
        "hasDefinition": True,
        "mapDot": "KC_E",
        "mapDash": "KC_T",
        "mapA": "KC_A",
        "force": ".-",
        "fallback": "KC_ESC",
    }
    failures = {key: (result.get(key), value) for key, value in expected.items() if result.get(key) != value}
    if "MORSE(ui_smoke)" not in str(result.get("copyStatus") or ""):
        failures["copyStatus"] = (result.get("copyStatus"), "contains MORSE(ui_smoke)")
    for key in ["rowCount", "prefixRows", "leafRows", "forceRows", "cancelRows"]:
        if int(result.get(key) or 0) <= 0:
            failures[key] = (result.get(key), "> 0")
    if failures:
        raise SystemExit(f"unexpected browser smoke result: {failures}")


if __name__ == "__main__":
    main()
