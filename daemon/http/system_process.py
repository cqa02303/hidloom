from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from typing import Any, Dict

_DAEMON_KEYWORDS: Dict[str, list] = {
    "httpd": ["httpd.py"],
    "logicd": ["-m", "logicd.logicd"],
    "logicd-core": ["hidloom-logicd-core"],
    "logicd-companion": ["-m logicd.logicd"],
    "matrixd": ["/matrixd"],
    "ledd": ["-m", "ledd.ledd"],
    "viald": ["viald"],
    "usbd": ["-m", "usbd.usbd"],
    "hidd": ["hidloom-hidd"],
    "outputd": ["hidloom-outputd"],
    "uidd": ["hidloom-uidd"],
    "i2cd": ["-m", "i2cd.i2cd"],
    "btd": ["-m btd.btd"],
    "spid": ["-m", "spid.spid"],
}

_SERVICE_UNITS: Dict[str, str] = {
    "httpd": "httpd.service",
    "logicd": "logicd.service",
    "logicd-core": "hidloom-logicd-core.service",
    "logicd-companion": "logicd-companion.service",
    "matrixd": "matrixd.service",
    "ledd": "ledd.service",
    "viald": "viald.service",
    "usbd": "usbd.service",
    "hidd": "hidloom-hidd.service",
    "outputd": "hidloom-outputd.service",
    "uidd": "hidloom-uidd.service",
    "i2cd": "i2cd.service",
    "btd": "btd.service",
    "spid": "spid.service",
}


def check_process(keywords: list) -> bool:
    try:
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                raw = Path(f"/proc/{pid}/cmdline").read_bytes()
                cmdline = raw.replace(b"\x00", b" ").decode(errors="replace")
                if all(kw in cmdline for kw in keywords):
                    return True
            except OSError:
                continue
    except OSError:
        pass
    return False


def _match_process_statuses(cmdlines: list[str]) -> Dict[str, bool]:
    return {
        name: any(all(kw in cmdline for kw in keywords) for cmdline in cmdlines)
        for name, keywords in _DAEMON_KEYWORDS.items()
    }


def _parse_systemd_active_states(text: str) -> Dict[str, bool]:
    states: Dict[str, bool] = {}
    current_id = ""
    current_state = ""
    for line in [*text.splitlines(), ""]:
        if not line:
            if current_id:
                states[current_id] = current_state == "active"
            current_id = ""
            current_state = ""
            continue
        key, sep, value = line.partition("=")
        if not sep:
            continue
        if key == "Id":
            current_id = value.strip()
        elif key == "ActiveState":
            current_state = value.strip()
    return states


def _systemd_active_statuses() -> Dict[str, bool]:
    units = list(_SERVICE_UNITS.values())
    try:
        proc = subprocess.run(
            ["systemctl", "show", "-p", "Id", "-p", "ActiveState", *units],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=1.5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if proc.returncode not in {0, 1}:
        return {}
    by_unit = _parse_systemd_active_states(proc.stdout)
    return {name: by_unit[unit] for name, unit in _SERVICE_UNITS.items() if unit in by_unit}


def _proc_cmdlines() -> list[str]:
    cmdlines: list[str] = []
    try:
        pids = os.listdir("/proc")
    except OSError:
        return cmdlines
    for pid in pids:
        if not pid.isdigit():
            continue
        try:
            raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        except OSError:
            continue
        cmdlines.append(raw.replace(b"\x00", b" ").decode(errors="replace"))
    return cmdlines


def hid_gadget_status(hid_device: str) -> Dict[str, Any]:
    udc_state = "unknown"
    try:
        for udc_dir in Path("/sys/class/udc").iterdir():
            udc_state = (udc_dir / "state").read_text().strip()
            break
    except OSError:
        pass
    return {
        "device": hid_device,
        "exists": Path(hid_device).exists(),
        "udc_state": udc_state,
        "connected": udc_state == "configured",
    }


def process_statuses() -> Dict[str, bool]:
    fallback = _match_process_statuses(_proc_cmdlines())
    systemd = _systemd_active_statuses()
    return {name: systemd.get(name, fallback[name]) for name in _DAEMON_KEYWORDS}


def _socket_file_status(path_text: str) -> Dict[str, Any]:
    """Return a small status object for a Unix socket path.

    Design intent:
    HTTP status should show connection prerequisites without actively connecting
    to daemon sockets. This avoids side effects in the status endpoint and keeps
    checks safe when daemons are restarting.
    """
    path = Path(path_text)
    try:
        st = path.stat()
    except FileNotFoundError:
        return {"path": path_text, "exists": False, "is_socket": False, "mode": None}
    except OSError as exc:
        return {"path": path_text, "exists": False, "is_socket": False, "mode": None, "error": str(exc)}
    return {
        "path": path_text,
        "exists": True,
        "is_socket": stat.S_ISSOCK(st.st_mode),
        "mode": oct(stat.S_IMODE(st.st_mode)),
    }
