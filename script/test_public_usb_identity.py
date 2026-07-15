#!/usr/bin/env python3
"""Regression checks for guarded public USB identity profiles."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/public_usb_identity.py"


def run(*args: str, root: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(TOOL), "--root", str(root), *args],
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def copy_fixture(destination: Path) -> None:
    contract = json.loads((ROOT / "config/public-usb-identity.json").read_text(encoding="utf-8"))
    systemd_binding = contract["source_bindings"]["systemd_identity_environment"]
    paths = [
        "config/public-usb-identity.json",
        contract["source_bindings"]["usb_config"],
        contract["source_bindings"]["ble_gatt_identity"],
        *systemd_binding["units"],
        *contract["source_bindings"]["vial_definitions"],
    ]
    for relative in paths:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)


def main() -> None:
    contract = json.loads(
        (ROOT / "config/public-usb-identity.json").read_text(encoding="utf-8")
    )
    assert contract["schema"] == "hidloom.public-usb-identity.v5"
    assert contract["assignment"]["availability_evidence"] == {
        "checked_date": "2026-07-15",
        "upstream_commit": "a454efc3291bba72162ac3878cdda0942dd8efa7",
        "origin_head_ref": "refs/remotes/origin/master",
        "remote_head_commit": "a454efc3291bba72162ac3878cdda0942dd8efa7",
        "checkout_clean": True,
        "head_matches_origin_head": True,
        "origin_head_matches_remote_head": True,
        "candidate_path_absent": True,
        "owner_path_absent": True,
    }
    plan = json.loads(run().stdout)
    assert plan["schema"] == "hidloom.public-usb-profile-plan.v2"
    assert plan["runtime_environment"] == {
        "bundle_name": "usb-identity.env",
        "install_path": "/etc/hidloom/usb-identity.env",
        "consumers": [
            "system/systemd/hidloom-usb-gadget.service",
            "system/systemd/btd.service",
        ],
    }
    assert plan["profile"] == "public_formal"
    assert plan["assignment_status"] == "candidate-unassigned"
    assert plan["activation_allowed"] is False
    assert plan["activation_blocker"] == "pid-codes-merge-required"
    assert plan["public_release_allowed"] is False
    assert plan["device_config"] == {
        "vendor_id": "0x1209",
        "product_id": "0x484c",
        "manufacturer": "HIDloom",
        "product_name": "HIDloom Keyboard",
        "serial_number": "vial:f64c2b3c:hidloom",
        "hid_country_code": 0,
    }
    assert plan["vial_identity"] == {
        "name": "HIDloom Keyboard (cqa02303v5)",
        "uid": 4850729948911185980,
    }

    with tempfile.TemporaryDirectory() as temporary:
        temporary_path = Path(temporary)
        invalid_evidence_root = temporary_path / "invalid-evidence-root"
        copy_fixture(invalid_evidence_root)
        invalid_evidence_path = (
            invalid_evidence_root / "config/public-usb-identity.json"
        )
        invalid_evidence = json.loads(
            invalid_evidence_path.read_text(encoding="utf-8")
        )
        invalid_evidence["assignment"]["availability_evidence"][
            "checkout_clean"
        ] = False
        invalid_evidence_path.write_text(
            json.dumps(invalid_evidence, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        rejected_evidence = run(root=invalid_evidence_root, check=False)
        assert rejected_evidence.returncode != 0
        assert "availability-checkout-not-clean" in rejected_evidence.stderr

        copy_fixture(invalid_evidence_root)
        invalid_evidence = json.loads(
            invalid_evidence_path.read_text(encoding="utf-8")
        )
        invalid_evidence["assignment"]["availability_evidence"][
            "remote_head_commit"
        ] = "1" * 40
        invalid_evidence_path.write_text(
            json.dumps(invalid_evidence, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        rejected_remote_evidence = run(root=invalid_evidence_root, check=False)
        assert rejected_remote_evidence.returncode != 0
        assert (
            "availability-remote-head-commit-mismatch"
            in rejected_remote_evidence.stderr
        )

        blocked_output = temporary_path / "blocked"
        blocked = run("--output", str(blocked_output), check=False)
        assert blocked.returncode != 0
        assert "profile activation is blocked" in blocked.stderr
        assert not blocked_output.exists()

        compatibility_output = temporary_path / "compatibility"
        compatibility = json.loads(
            run(
                "--profile",
                "development_compatibility",
                "--output",
                str(compatibility_output),
            ).stdout
        )
        assert compatibility["activation_allowed"] is True
        expected_vendor = "0x" + "1d6b"
        assert compatibility["device_config"]["vendor_id"] == expected_vendor
        assert json.loads(
            (compatibility_output / "usb-device.json").read_text(encoding="utf-8")
        ) == compatibility["device_config"]
        assert json.loads(
            (compatibility_output / "vial-identity.json").read_text(encoding="utf-8")
        ) == compatibility["vial_identity"]
        environment_path = compatibility_output / "usb-identity.env"
        env_text = environment_path.read_text(encoding="utf-8")
        assert f"HIDLOOM_USB_VENDOR_ID={expected_vendor}" in env_text
        assert "HIDLOOM_USB_SERIAL=vial:f64c2b3c" in env_text
        assert "HIDLOOM_USB_SERIAL_SUFFIX=''" in env_text
        assert not (compatibility_output / "usb-gadget.env").exists()
        for path in compatibility_output.iterdir():
            assert path.stat().st_mode & 0o777 == 0o644, path

        exists = run(
            "--profile",
            "development_compatibility",
            "--output",
            str(compatibility_output),
            check=False,
        )
        assert exists.returncode != 0
        assert "output already exists" in exists.stderr
        unexpected_path = compatibility_output / "DO_NOT_DELETE.txt"
        unexpected_path.write_text("preserve\n", encoding="utf-8")
        unexpected = run(
            "--profile",
            "development_compatibility",
            "--output",
            str(compatibility_output),
            "--force",
            check=False,
        )
        assert unexpected.returncode != 0
        assert "unexpected files" in unexpected.stderr
        assert unexpected_path.read_text(encoding="utf-8") == "preserve\n"
        unexpected_path.unlink()
        plan_path = compatibility_output / "PROFILE_PLAN.json"
        plan_path.unlink()
        plan_path.symlink_to(compatibility_output / "usb-device.json")
        symlinked = run(
            "--profile",
            "development_compatibility",
            "--output",
            str(compatibility_output),
            "--force",
            check=False,
        )
        assert symlinked.returncode != 0
        assert "containing symlinks" in symlinked.stderr

        source_output = run(
            "--profile",
            "development_compatibility",
            "--output",
            str(ROOT / "build/public-usb-profile"),
            check=False,
        )
        assert source_output.returncode != 0
        assert "outside the HIDloom source repository" in source_output.stderr

        fixture = temporary_path / "assigned-root"
        copy_fixture(fixture)
        contract_path = fixture / "config/public-usb-identity.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["assignment"]["status"] = "assigned"
        contract["assignment"]["allocation_evidence"] = {
            "merged_date": "2026-07-15",
            "upstream_commit": "1" * 40,
            "candidate_path": "1209/484C/index.md",
            "candidate_path_present": True,
        }
        contract["profiles"]["public_formal"]["status"] = "assigned-ready"
        contract["profiles"]["public_formal"]["public_release_allowed"] = True
        contract_path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        formal_output = temporary_path / "formal"
        formal = json.loads(run("--output", str(formal_output), root=fixture).stdout)
        assert formal["activation_allowed"] is True
        assert formal["assignment_status"] == "assigned"
        assert formal["public_release_allowed"] is True
        formal_env = (formal_output / "usb-identity.env").read_text(encoding="utf-8")
        assert "HIDLOOM_USB_MANUFACTURER=HIDloom" in formal_env
        assert "HIDLOOM_USB_PRODUCT_NAME='HIDloom Keyboard'" in formal_env
        assert "HIDLOOM_USB_SERIAL=vial:f64c2b3c:hidloom" in formal_env

        contract["profiles"]["public_formal"]["usb"]["product_name"] = "Unreviewed"
        contract_path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        invalid_formal = run(root=fixture, check=False)
        assert invalid_formal.returncode != 0
        assert "public-product-name-invalid" in invalid_formal.stderr

        copy_fixture(fixture)
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["profiles"]["development_compatibility"]["usb"][
            "product_name"
        ] = "coordinated-drift"
        contract_path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        config_path = fixture / "config/default/config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["device"]["product_name"] = "coordinated-drift"
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        coordinated_drift = run(root=fixture, check=False)
        assert coordinated_drift.returncode != 0
        assert "development-product-name-invalid" in coordinated_drift.stderr

        copy_fixture(fixture)
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["device"]["product_name"] = "runtime-drift"
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        drift = run(root=fixture, check=False)
        assert drift.returncode != 0
        assert "development-usb-runtime-drift" in drift.stderr

        copy_fixture(fixture)
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["source_bindings"]["usb_config"] = "../../etc/passwd"
        contract_path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        unsafe_binding = run(root=fixture, check=False)
        assert unsafe_binding.returncode != 0
        assert "usb-config-binding-invalid" in unsafe_binding.stderr

        copy_fixture(fixture)
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["source_bindings"]["ble_gatt_identity"] = "daemon/btd/other.py"
        contract_path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        invalid_gatt_binding = run(root=fixture, check=False)
        assert invalid_gatt_binding.returncode != 0
        assert "ble-gatt-binding-invalid" in invalid_gatt_binding.stderr

        copy_fixture(fixture)
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["source_bindings"]["systemd_identity_environment"]["path"] = (
            "/tmp/usb-identity.env"
        )
        contract_path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        invalid_environment_path = run(root=fixture, check=False)
        assert invalid_environment_path.returncode != 0
        assert "systemd-identity-environment-path-invalid" in invalid_environment_path.stderr

        copy_fixture(fixture)
        unit_path = fixture / "system/systemd/btd.service"
        unit_path.write_text(
            unit_path.read_text(encoding="utf-8").replace(
                "EnvironmentFile=-/etc/hidloom/usb-identity.env\n", ""
            ),
            encoding="utf-8",
        )
        missing_environment_consumer = run(root=fixture, check=False)
        assert missing_environment_consumer.returncode != 0
        assert (
            "systemd-identity-environment-missing:system/systemd/btd.service"
            in missing_environment_consumer.stderr
        )

        copy_fixture(fixture)
        gatt_path = fixture / "daemon/btd/gatt_hid.py"
        gatt_source = gatt_path.read_text(encoding="utf-8").replace(
            '_env_u16("HIDLOOM_USB_PRODUCT_ID", 0x0105)',
            '_env_u16("HIDLOOM_USB_PRODUCT_ID", 0x9999)',
        )
        gatt_path.write_text(gatt_source, encoding="utf-8")
        gatt_drift = run(root=fixture, check=False)
        assert gatt_drift.returncode != 0
        assert "ble-gatt-development-identity-drift" in gatt_drift.stderr

    print("ok: public USB identity profiles, Vial identity, and activation guard")


if __name__ == "__main__":
    main()
