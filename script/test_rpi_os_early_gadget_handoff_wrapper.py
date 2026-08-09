#!/usr/bin/env python3
"""Exercise the USB gadget wrapper's fail-closed early handoff routing."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "system/install/hidloom_usb_gadget_start.sh"
ADOPTER = ROOT / "tools/rpi_os_early_gadget_adopt.py"
USB_UNIT = ROOT / "system/systemd/hidloom-usb-gadget.service"
HIDD_UNIT = ROOT / "system/systemd/hidloom-hidd.service"


def write_executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def run_case(
    root: Path,
    *,
    marker: bool,
    gadget: bool,
    adopter_status: int,
    backend_status: int,
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    case = root / f"case-{int(marker)}-{int(gadget)}-{adopter_status}-{backend_status}"
    case.mkdir()
    wrapper = case / "system/install/hidloom_usb_gadget_start.sh"
    wrapper.parent.mkdir(parents=True)
    shutil.copy2(WRAPPER, wrapper)
    adopter_log = case / "adopter.log"
    backend_log = case / "backend.log"
    marker_path = case / "run/gadget-bound.json"
    configfs_root = case / "configfs"
    if marker:
        marker_path.parent.mkdir(parents=True)
        marker_path.write_text("marker\n", encoding="utf-8")
    if gadget:
        (configfs_root / "cqa02303v5").mkdir(parents=True)
    write_executable(
        case / "tools/rpi_os_early_gadget_adopt.py",
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "open(os.environ['ADOPTER_LOG'], 'w', encoding='utf-8').write('\\n'.join(sys.argv[1:]))\n"
        "raise SystemExit(int(os.environ['ADOPTER_STATUS']))\n",
    )
    write_executable(
        case / "setup_usb_gadget.sh",
        "#!/bin/sh\n"
        ": >\"$BACKEND_LOG\"\n"
        "exit \"$BACKEND_STATUS\"\n",
    )
    environment = {
        **os.environ,
        "HIDLOOM_USB_GADGET_SETUP_BACKEND": "shell",
        "HIDLOOM_EARLY_GADGET_MARKER": str(marker_path),
        "HIDLOOM_EARLY_ACCEPTED_MANIFEST": str(case / "accepted.json"),
        "HIDLOOM_EARLY_RUNTIME_CONTRACT": str(case / "contract.json"),
        "HIDLOOM_EARLY_CONFIGFS_ROOT": str(configfs_root),
        "HIDLOOM_EARLY_PROC_ROOT": str(case / "proc"),
        "HIDLOOM_EARLY_SYS_ROOT": str(case / "sys"),
        "HIDLOOM_EARLY_DEV_ROOT": str(case / "dev"),
        "HIDLOOM_EARLY_PACKAGE_ROOT": str(case / "package"),
        "HIDLOOM_EARLY_PROFILE_ROOT": str(case / "profiles"),
        "HIDLOOM_EARLY_RUNTIME_PROFILE_MARKER": str(case / "profile.json"),
        "HIDLOOM_EARLY_INSTALLED_HELPER": str(case / "helper"),
        "HIDLOOM_EARLY_EXPECTED_OWNER_UID": str(os.getuid()),
        "ADOPTER_LOG": str(adopter_log),
        "ADOPTER_STATUS": str(adopter_status),
        "BACKEND_LOG": str(backend_log),
        "BACKEND_STATUS": str(backend_status),
    }
    result = subprocess.run(
        [str(wrapper)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        check=False,
    )
    return result, adopter_log, backend_log


def run_restart_case(root: Path) -> None:
    case = root / "restart-after-adopt"
    wrapper = case / "system/install/hidloom_usb_gadget_start.sh"
    wrapper.parent.mkdir(parents=True)
    shutil.copy2(WRAPPER, wrapper)
    adopter = case / "tools/rpi_os_early_gadget_adopt.py"
    adopter.parent.mkdir(parents=True)
    shutil.copy2(ADOPTER, adopter)
    backend_log = case / "backend.log"
    write_executable(
        case / "setup_usb_gadget.sh",
        "#!/bin/sh\n"
        ": >\"$BACKEND_LOG\"\n"
        "exit \"$BACKEND_STATUS\"\n",
    )

    marker = case / "run/hidloom-early/gadget-bound.json"
    runtime_contract = case / "run/hidloom-early/contract.json"
    runtime_payload = {
        "schema": "hidloom.rpi-os-early-runtime-contract.e1.v1",
        "kernel_release": "6.18.34+rpt-rpi-v8",
    }
    runtime_bytes = (json.dumps(runtime_payload, indent=2, sort_keys=True) + "\n").encode()
    runtime_contract.parent.mkdir(parents=True)
    runtime_contract.write_bytes(runtime_bytes)
    marker.write_text(
        json.dumps(
            {
                "schema": "hidloom.early-gadget-bound.v1",
                "state": "bound",
                "kernel_release": runtime_payload["kernel_release"],
                "runtime_contract_sha256": hashlib.sha256(runtime_bytes).hexdigest(),
                "ready_uptime_seconds": 2.5,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    configfs_root = case / "configfs"
    udc = configfs_root / "cqa02303v5/UDC"
    udc.parent.mkdir(parents=True)
    udc.write_text("20980000.usb\n", encoding="utf-8")

    environment = {
        **os.environ,
        "HIDLOOM_EARLY_GADGET_MARKER": str(marker),
        "HIDLOOM_EARLY_RUNTIME_CONTRACT": str(runtime_contract),
        "HIDLOOM_EARLY_CONFIGFS_ROOT": str(configfs_root),
        "HIDLOOM_EARLY_EXPECTED_OWNER_UID": str(os.getuid()),
        "BACKEND_LOG": str(backend_log),
        "BACKEND_STATUS": "29",
    }
    stopped = subprocess.run(
        [str(wrapper), "--stop"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        check=False,
    )
    assert stopped.returncode == 0, (stopped.stdout, stopped.stderr)
    assert json.loads(stopped.stdout)["status"] == "marker-cleared"
    assert not marker.exists()
    assert not udc.read_text(encoding="utf-8").strip()

    restarted = subprocess.run(
        [str(wrapper)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        check=False,
    )
    assert restarted.returncode == 29, (restarted.stdout, restarted.stderr)
    assert backend_log.exists()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="hidloom-early-handoff-") as directory:
        root = Path(directory)

        # Ordinary boot bypasses Python and retains the existing backend path.
        result, adopter, backend = run_case(
            root, marker=False, gadget=False, adopter_status=99, backend_status=23
        )
        assert result.returncode == 23, (result.stdout, result.stderr)
        assert not adopter.exists()
        assert backend.exists()

        # Exact adoption never invokes a backend that could unbind the UDC.
        result, adopter, backend = run_case(
            root, marker=True, gadget=True, adopter_status=0, backend_status=24
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert adopter.exists()
        assert not backend.exists()
        arguments = adopter.read_text(encoding="utf-8").splitlines()
        assert arguments[0] == "verify"
        assert "--accepted-manifest" in arguments
        assert "--runtime-contract" in arguments

        # Exit 10 is the sole state allowed to fall through to normal creation.
        result, adopter, backend = run_case(
            root, marker=True, gadget=True, adopter_status=10, backend_status=25
        )
        assert result.returncode == 25, (result.stdout, result.stderr)
        assert adopter.exists()
        assert backend.exists()

        # Any unsafe or unexpected exit is propagated and the backend stays idle.
        for status in (1, 78, 126):
            result, adopter, backend = run_case(
                root, marker=True, gadget=False, adopter_status=status, backend_status=26
            )
            assert result.returncode == status, (status, result.stdout, result.stderr)
            assert adopter.exists()
            assert not backend.exists()
            assert "refusing to recreate" in result.stderr

        run_restart_case(root)

    wrapper_text = WRAPPER.read_text(encoding="utf-8")
    assert "-L \"$EARLY_MARKER\"" in wrapper_text
    assert "-L \"$EARLY_GADGET_PATH\"" in wrapper_text
    hidd = HIDD_UNIT.read_text(encoding="utf-8")
    assert "After=hidloom-usb-gadget.service" in hidd
    assert "Requires=hidloom-usb-gadget.service" in hidd
    usb_unit = USB_UNIT.read_text(encoding="utf-8")
    assert "ExecStart=@HIDLOOM_REPO_ROOT@/system/install/hidloom_usb_gadget_start.sh" in usb_unit
    assert (
        "ExecStop=@HIDLOOM_REPO_ROOT@/system/install/hidloom_usb_gadget_start.sh --stop"
        in usb_unit
    )
    print("ok: Raspberry Pi OS early gadget handoff wrapper")


if __name__ == "__main__":
    main()
