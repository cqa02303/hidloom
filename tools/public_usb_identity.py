#!/usr/bin/env python3
"""Validate HIDloom USB identity profiles and render guarded profile bundles."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import shlex
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = Path("config/public-usb-identity.json")
SCHEMA = "hidloom.public-usb-identity.v5"
PROFILE_PLAN_SCHEMA = "hidloom.public-usb-profile-plan.v2"
PROFILE_NAMES = {"development_compatibility", "public_formal"}
IDENTITY_ENV_BUNDLE_NAME = "usb-identity.env"
IDENTITY_ENV_INSTALL_PATH = "/etc/hidloom/usb-identity.env"
IDENTITY_ENV_UNITS = [
    "system/systemd/hidloom-usb-gadget.service",
    "system/systemd/btd.service",
]
HEX_U16_RE = re.compile(r"[0-9A-Fa-f]{4}")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
DATE_RE = re.compile(r"20\d{2}-\d{2}-\d{2}")
ORIGIN_HEAD_RE = re.compile(r"refs/remotes/origin/[A-Za-z0-9][A-Za-z0-9._/-]*")


class ContractError(ValueError):
    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__("; ".join(issues))


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def normalize_u16(value: object, label: str, issues: list[str]) -> str:
    text = str(value)
    if not HEX_U16_RE.fullmatch(text):
        issues.append(f"{label}-invalid")
        return ""
    return text.upper()


def object_value(parent: dict[str, Any], key: str, label: str, issues: list[str]) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        issues.append(f"{label}-not-object")
        return {}
    return value


def string_value(parent: dict[str, Any], key: str, label: str, issues: list[str]) -> str:
    value = parent.get(key)
    if not isinstance(value, str) or not value.strip():
        issues.append(f"{label}-missing")
        return ""
    if "\0" in value or "\n" in value or "\r" in value:
        issues.append(f"{label}-unsafe")
        return ""
    return value


def call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def env_u16_call(node: ast.AST) -> tuple[str, int] | None:
    if not isinstance(node, ast.Call) or call_name(node.func) != "_env_u16":
        return None
    if len(node.args) != 2 or node.keywords:
        return None
    name, default = node.args
    if not (
        isinstance(name, ast.Constant)
        and isinstance(name.value, str)
        and isinstance(default, ast.Constant)
        and isinstance(default.value, int)
    ):
        return None
    return name.value, default.value


def validate_ble_gatt_identity(
    root: Path,
    relative: str,
    development_vid: str,
    development_pid: str,
    issues: list[str],
) -> None:
    try:
        tree = ast.parse((root / relative).read_text(encoding="utf-8"), filename=relative)
    except (OSError, SyntaxError, UnicodeError):
        issues.append("ble-gatt-identity-unreadable")
        return
    pnp_assignment = next(
        (
            node.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "PNP_ID" for target in node.targets)
        ),
        None,
    )
    if not (
        isinstance(pnp_assignment, ast.Call)
        and call_name(pnp_assignment.func) == "build_pnp_id"
        and len(pnp_assignment.args) == 2
        and not pnp_assignment.keywords
    ):
        issues.append("ble-gatt-pnp-binding-invalid")
        return
    bindings = [env_u16_call(argument) for argument in pnp_assignment.args]
    expected = [
        ("HIDLOOM_USB_VENDOR_ID", int(development_vid, 16)),
        ("HIDLOOM_USB_PRODUCT_ID", int(development_pid, 16)),
    ]
    if bindings != expected:
        issues.append("ble-gatt-development-identity-drift")


def validate_systemd_identity_environment(
    root: Path,
    binding: dict[str, Any],
    issues: list[str],
) -> None:
    install_path = binding.get("path")
    units = binding.get("units")
    if install_path != IDENTITY_ENV_INSTALL_PATH:
        issues.append("systemd-identity-environment-path-invalid")
    if units != IDENTITY_ENV_UNITS:
        issues.append("systemd-identity-environment-units-invalid")
        return
    expected = f"EnvironmentFile=-{IDENTITY_ENV_INSTALL_PATH}"
    for relative in units:
        try:
            text = (root / relative).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            issues.append(f"systemd-identity-environment-unreadable:{relative}")
            continue
        if text.count(expected) != 1:
            issues.append(f"systemd-identity-environment-missing:{relative}")


def validate_contract(root: Path) -> dict[str, Any]:
    issues: list[str] = []
    try:
        contract = load_json(root / CONTRACT_PATH)
    except (OSError, json.JSONDecodeError, ValueError):
        raise ContractError(["contract-unreadable"])

    if contract.get("schema") != SCHEMA:
        issues.append("unsupported-schema")
    active_profile = contract.get("active_runtime_profile")
    public_profile = contract.get("public_release_profile")
    if active_profile != "development_compatibility":
        issues.append("active-runtime-profile-invalid")
    if public_profile != "public_formal":
        issues.append("public-release-profile-invalid")

    assignment = object_value(contract, "assignment", "assignment", issues)
    if assignment.get("registry") != "pid.codes":
        issues.append("registry-invalid")
    if assignment.get("registry_repository") != "https://github.com/pidcodes/pidcodes.github.com":
        issues.append("registry-repository-invalid")
    assignment_status = assignment.get("status")
    if assignment_status not in {"candidate-unassigned", "assigned"}:
        issues.append("assignment-status-invalid")
    assignment_vid = normalize_u16(assignment.get("vid"), "assignment-vid", issues)
    assignment_pid = normalize_u16(assignment.get("pid"), "assignment-pid", issues)
    if assignment_vid and assignment_vid != "1209":
        issues.append("assignment-vid-not-pid-codes")
    if assignment_pid and int(assignment_pid, 16) < 0x2000:
        issues.append("assignment-pid-reserved")
    if assignment.get("activate_only_after_pid_codes_merge") is not True:
        issues.append("assignment-activation-guard-missing")
    if assignment.get("recheck_availability_before_request") is not True:
        issues.append("assignment-recheck-guard-missing")

    availability = object_value(
        assignment, "availability_evidence", "availability-evidence", issues
    )
    if not DATE_RE.fullmatch(str(availability.get("checked_date", ""))):
        issues.append("availability-date-invalid")
    if not COMMIT_RE.fullmatch(str(availability.get("upstream_commit", ""))):
        issues.append("availability-commit-invalid")
    origin_head_ref = str(availability.get("origin_head_ref", ""))
    if (
        not ORIGIN_HEAD_RE.fullmatch(origin_head_ref)
        or ".." in origin_head_ref
        or "//" in origin_head_ref
    ):
        issues.append("availability-origin-head-ref-invalid")
    if availability.get("checkout_clean") is not True:
        issues.append("availability-checkout-not-clean")
    if availability.get("head_matches_origin_head") is not True:
        issues.append("availability-head-not-origin-head")
    remote_head_commit = str(availability.get("remote_head_commit", ""))
    if not COMMIT_RE.fullmatch(remote_head_commit):
        issues.append("availability-remote-head-commit-invalid")
    elif remote_head_commit != availability.get("upstream_commit"):
        issues.append("availability-remote-head-commit-mismatch")
    if availability.get("origin_head_matches_remote_head") is not True:
        issues.append("availability-origin-head-not-remote-head")
    if availability.get("candidate_path_absent") is not True:
        issues.append("availability-candidate-path-not-absent")
    if availability.get("owner_path_absent") is not True:
        issues.append("availability-owner-path-not-absent")

    allocation = assignment.get("allocation_evidence")
    if assignment_status == "candidate-unassigned":
        if allocation is not None:
            issues.append("candidate-allocation-evidence-must-be-null")
    elif assignment_status == "assigned":
        if not isinstance(allocation, dict):
            issues.append("assigned-allocation-evidence-missing")
        else:
            if not DATE_RE.fullmatch(str(allocation.get("merged_date", ""))):
                issues.append("allocation-date-invalid")
            if not COMMIT_RE.fullmatch(str(allocation.get("upstream_commit", ""))):
                issues.append("allocation-commit-invalid")
            if allocation.get("candidate_path_present") is not True:
                issues.append("allocation-candidate-path-not-present")
            expected_candidate_path = f"{assignment_vid}/{assignment_pid}/index.md"
            if allocation.get("candidate_path") != expected_candidate_path:
                issues.append("allocation-candidate-path-mismatch")

    detection = object_value(contract, "vial_detection", "vial-detection", issues)
    serial_magic = string_value(
        detection, "serial_magic", "vial-serial-magic", issues
    )
    if serial_magic and serial_magic != "vial:f64c2b3c":
        issues.append("vial-serial-magic-invalid")
    if detection.get("match_policy") != "substring":
        issues.append("vial-match-policy-invalid")
    vial_upstream_commit = str(detection.get("upstream_commit", ""))
    if not COMMIT_RE.fullmatch(vial_upstream_commit):
        issues.append("vial-upstream-commit-invalid")
    vial_source = str(detection.get("upstream_source", ""))
    expected_vial_source = (
        "https://github.com/vial-kb/vial-gui/blob/"
        f"{vial_upstream_commit}/src/main/python/util.py"
    )
    if vial_source != expected_vial_source:
        issues.append("vial-upstream-source-not-pinned")
    if not DATE_RE.fullmatch(str(detection.get("checked_date", ""))):
        issues.append("vial-upstream-date-invalid")

    bindings = object_value(contract, "source_bindings", "source-bindings", issues)
    usb_config_path = bindings.get("usb_config")
    if usb_config_path != "config/default/config.json":
        issues.append("usb-config-binding-invalid")
    ble_gatt_path = bindings.get("ble_gatt_identity")
    if ble_gatt_path != "daemon/btd/gatt_hid.py":
        issues.append("ble-gatt-binding-invalid")
    systemd_identity_environment = object_value(
        bindings,
        "systemd_identity_environment",
        "systemd-identity-environment",
        issues,
    )
    validate_systemd_identity_environment(root, systemd_identity_environment, issues)
    vial_paths = bindings.get("vial_definitions")
    expected_vial_paths = [
        "config/default/vial.json",
        "config/boards/ver0.1/conf/vial.json",
        "config/boards/ver1.0/conf/vial.json",
    ]
    if vial_paths != expected_vial_paths:
        issues.append("vial-definition-bindings-invalid")

    profiles = object_value(contract, "profiles", "profiles", issues)
    if set(profiles) != PROFILE_NAMES:
        issues.append("profile-set-invalid")
    development = object_value(
        profiles, "development_compatibility", "development-profile", issues
    )
    formal = object_value(profiles, "public_formal", "public-profile", issues)
    development_usb = object_value(development, "usb", "development-usb", issues)
    development_vial = object_value(development, "vial", "development-vial", issues)
    formal_usb = object_value(formal, "usb", "public-usb", issues)
    formal_vial = object_value(formal, "vial", "public-vial", issues)

    development_vid = normalize_u16(
        development_usb.get("vid"), "development-vid", issues
    )
    development_pid = normalize_u16(
        development_usb.get("pid"), "development-pid", issues
    )
    if development_vid and development_vid != "1D6B":
        issues.append("development-vid-drift")
    if development_pid and development_pid != "0105":
        issues.append("development-pid-drift")
    if development_usb.get("manufacturer") != "__HOSTNAME__":
        issues.append("development-manufacturer-invalid")
    if development_usb.get("product_name") != "__HOSTNAME__":
        issues.append("development-product-name-invalid")
    if development_usb.get("serial_number") != "vial:f64c2b3c":
        issues.append("development-serial-number-invalid")
    if development_usb.get("hid_country_code") != 0:
        issues.append("development-hid-country-code-invalid")
    if development.get("status") != "active-private-compatibility":
        issues.append("development-status-invalid")
    if development.get("public_release_allowed") is not False:
        issues.append("development-public-release-must-be-blocked")
    if ble_gatt_path == "daemon/btd/gatt_hid.py" and development_vid and development_pid:
        validate_ble_gatt_identity(
            root,
            ble_gatt_path,
            development_vid,
            development_pid,
            issues,
        )

    formal_vid = normalize_u16(formal_usb.get("vid"), "public-vid", issues)
    formal_pid = normalize_u16(formal_usb.get("pid"), "public-pid", issues)
    if formal_vid and assignment_vid and formal_vid != assignment_vid:
        issues.append("public-vid-assignment-mismatch")
    if formal_pid and assignment_pid and formal_pid != assignment_pid:
        issues.append("public-pid-assignment-mismatch")
    if formal_usb.get("manufacturer") != "HIDloom":
        issues.append("public-manufacturer-invalid")
    if formal_usb.get("product_name") != "HIDloom Keyboard":
        issues.append("public-product-name-invalid")
    if formal_usb.get("serial_number") != "vial:f64c2b3c:hidloom":
        issues.append("public-serial-number-invalid")
    if formal_usb.get("hid_country_code") != 0:
        issues.append("public-hid-country-code-invalid")
    if formal_vial.get("name") != "HIDloom Keyboard (cqa02303v5)":
        issues.append("public-vial-name-invalid")
    if formal_vial.get("uid_policy") != "preserve-layout-identity":
        issues.append("public-vial-uid-policy-invalid")
    if development_vial.get("uid_policy") != "preserve-layout-identity":
        issues.append("development-vial-uid-policy-invalid")
    development_uid = development_vial.get("uid")
    formal_uid = formal_vial.get("uid")
    if development_vial.get("name") != "CQA02303v5 Keyboard":
        issues.append("development-vial-name-invalid")
    if development_uid != 4850729948911185980:
        issues.append("development-vial-uid-invalid")
    if formal_uid != development_uid:
        issues.append("public-vial-uid-must-be-preserved")

    if assignment_status == "candidate-unassigned":
        if formal.get("status") != "blocked-until-pid-codes-merge":
            issues.append("candidate-public-profile-status-invalid")
        if formal.get("public_release_allowed") is not False:
            issues.append("candidate-public-release-must-be-blocked")
    elif assignment_status == "assigned":
        if formal.get("status") != "assigned-ready":
            issues.append("assigned-public-profile-status-invalid")
        if formal.get("public_release_allowed") is not True:
            issues.append("assigned-public-release-not-enabled")

    expected_device = {
        "vendor_id": f"0x{development_vid.lower()}" if development_vid else "",
        "product_id": f"0x{development_pid.lower()}" if development_pid else "",
        "manufacturer": development_usb.get("manufacturer"),
        "product_name": development_usb.get("product_name"),
        "serial_number": development_usb.get("serial_number"),
        "hid_country_code": development_usb.get("hid_country_code"),
    }
    if usb_config_path == "config/default/config.json":
        try:
            runtime_device = load_json(root / usb_config_path).get("device")
        except (OSError, json.JSONDecodeError, ValueError):
            runtime_device = None
        if not isinstance(runtime_device, dict) or any(
            runtime_device.get(key) != value for key, value in expected_device.items()
        ):
            issues.append("development-usb-runtime-drift")
    if vial_paths == expected_vial_paths:
        expected_vial = {
            "name": development_vial.get("name"),
            "uid": development_vial.get("uid"),
        }
        for relative in vial_paths:
            if not isinstance(relative, str):
                issues.append("vial-definition-binding-not-string")
                continue
            try:
                vial_definition = load_json(root / relative)
            except (OSError, json.JSONDecodeError, ValueError):
                issues.append(f"vial-definition-unreadable:{relative}")
                continue
            if any(vial_definition.get(key) != value for key, value in expected_vial.items()):
                issues.append(f"development-vial-runtime-drift:{relative}")

    if issues:
        raise ContractError(sorted(set(issues)))
    return contract


def render_profile(contract: dict[str, Any], profile_name: str) -> dict[str, Any]:
    if profile_name not in PROFILE_NAMES:
        raise ContractError([f"unknown-profile:{profile_name}"])
    profile = contract["profiles"][profile_name]
    usb = profile["usb"]
    vial = profile["vial"]
    assignment = contract["assignment"]
    activation_allowed = profile_name == contract["active_runtime_profile"] or (
        profile_name == contract["public_release_profile"]
        and assignment["status"] == "assigned"
        and profile["status"] == "assigned-ready"
        and profile["public_release_allowed"] is True
        and isinstance(assignment.get("allocation_evidence"), dict)
    )
    device_config = {
        "vendor_id": f"0x{usb['vid'].lower()}",
        "product_id": f"0x{usb['pid'].lower()}",
        "manufacturer": usb["manufacturer"],
        "product_name": usb["product_name"],
        "serial_number": usb["serial_number"],
        "hid_country_code": usb["hid_country_code"],
    }
    environment = {
        "HIDLOOM_USB_VENDOR_ID": device_config["vendor_id"],
        "HIDLOOM_USB_PRODUCT_ID": device_config["product_id"],
        "HIDLOOM_USB_MANUFACTURER": usb["manufacturer"],
        "HIDLOOM_USB_PRODUCT_NAME": usb["product_name"],
        "HIDLOOM_USB_SERIAL": usb["serial_number"],
        "HIDLOOM_USB_SERIAL_SUFFIX": "",
        "HIDLOOM_USB_HID_COUNTRY_CODE": str(usb["hid_country_code"]),
    }
    return {
        "schema": PROFILE_PLAN_SCHEMA,
        "profile": profile_name,
        "profile_status": profile["status"],
        "assignment_status": assignment["status"],
        "activation_allowed": activation_allowed,
        "activation_blocker": None if activation_allowed else "pid-codes-merge-required",
        "public_release_allowed": profile["public_release_allowed"],
        "device_config": device_config,
        "vial_identity": {"name": vial["name"], "uid": vial["uid"]},
        "environment": environment,
        "runtime_environment": {
            "bundle_name": IDENTITY_ENV_BUNDLE_NAME,
            "install_path": contract["source_bindings"]["systemd_identity_environment"]["path"],
            "consumers": contract["source_bindings"]["systemd_identity_environment"]["units"],
        },
    }


def write_bundle(plan: dict[str, Any], output: Path, *, force: bool) -> None:
    if not plan["activation_allowed"]:
        raise SystemExit(
            f"profile activation is blocked: {plan['profile']} ({plan['activation_blocker']})"
        )
    expected_files = {
        Path("PROFILE_PLAN.json"),
        Path("usb-device.json"),
        Path(IDENTITY_ENV_BUNDLE_NAME),
        Path("vial-identity.json"),
    }
    if output.exists():
        if not force:
            raise SystemExit(f"output already exists: {output}")
        if not output.is_dir():
            raise SystemExit(f"output is not a directory: {output}")
        symlinks = sorted(
            path.relative_to(output) for path in output.rglob("*") if path.is_symlink()
        )
        if symlinks:
            raise SystemExit(
                "refusing to replace output containing symlinks: "
                + ", ".join(path.as_posix() for path in symlinks)
            )
        actual_files = {
            path.relative_to(output) for path in output.rglob("*") if not path.is_dir()
        }
        unexpected = sorted(actual_files - expected_files)
        if unexpected:
            raise SystemExit(
                "refusing to replace output with unexpected files: "
                + ", ".join(path.as_posix() for path in unexpected)
            )
    output.mkdir(parents=True, exist_ok=True)
    json_files = {
        "PROFILE_PLAN.json": plan,
        "usb-device.json": plan["device_config"],
        "vial-identity.json": plan["vial_identity"],
    }
    for filename, payload in json_files.items():
        destination = output / filename
        destination.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        destination.chmod(0o644)
    env_lines = [
        f"{name}={shlex.quote(value)}" for name, value in sorted(plan["environment"].items())
    ]
    environment_path = output / IDENTITY_ENV_BUNDLE_NAME
    environment_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    environment_path.chmod(0o644)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--profile")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    try:
        contract = validate_contract(root)
        profile_name = args.profile or contract["public_release_profile"]
        plan = render_profile(contract, profile_name)
    except ContractError as exc:
        raise SystemExit("public USB identity validation failed:\n- " + "\n- ".join(exc.issues))
    if args.output:
        output = args.output.resolve()
        if output == Path(output.anchor) or output == root or root in output.parents:
            raise SystemExit("output must be outside the HIDloom source repository")
        write_bundle(plan, output, force=args.force)
        plan["output"] = str(output)
    print(json.dumps(plan, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
