#!/usr/bin/env python3
"""Stage and verify a guarded USB identity in a generated M6 target tree."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex

from public_usb_identity import ROOT, render_profile, validate_contract

GADGET = 'usr/bin/hidloom-hid-gadget-m4'
TEMPLATE = 'build/buildroot/hidloom-external/board/hidloom/rootfs_overlay_m4/usr/bin/hidloom-hid-gadget-m4'
RECEIPT = 'usr/share/hidloom/USB_IDENTITY_PLAN.json'


def expected_gadget(root: Path, plan: dict) -> str:
    text = (root / TEMPLATE).read_text(encoding='utf-8')
    if plan['profile'] == 'development_compatibility':
        return text
    values = plan['device_config']
    replacements = {
        "printf '0x1d6b\\n' > idVendor": ('idVendor', values['vendor_id']),
        "printf '0x0105\\n' > idProduct": ('idProduct', values['product_id']),
        "printf 'vial:f64c2b3c\\n' > strings/0x409/serialnumber": ('strings/0x409/serialnumber', values['serial_number']),
        "printf 'hidloom\\n' > strings/0x409/manufacturer": ('strings/0x409/manufacturer', values['manufacturer']),
        "printf 'CQA02303v5 M4 JP+US Keyboard\\n' > strings/0x409/product": ('strings/0x409/product', values['product_name']),
    }
    for old, (destination, value) in replacements.items():
        if text.count(old) != 1:
            raise ValueError(f'M6 identity template drift: {destination}')
        text = text.replace(old, f"printf '%s\\n' {shlex.quote(value)} > {destination}")
    return text


def plan_for(root: Path, profile: str) -> dict:
    plan = render_profile(validate_contract(root), profile)
    if not plan['activation_allowed']:
        raise ValueError('M6 identity activation blocked: pid.codes allocation required')
    return plan


def stage(root: Path, target: Path, profile: str) -> None:
    plan = plan_for(root, profile)
    gadget = expected_gadget(root, plan)
    destination = target / GADGET
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(gadget, encoding='utf-8')
    destination.chmod(0o755)
    if profile == 'public_formal':
        for relative in ['mnt/p3/config.json', 'usr/share/hidloom/config/default/config.json']:
            path = target / relative
            payload = json.loads(path.read_text(encoding='utf-8'))
            payload['device'].update(plan['device_config'])
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        contract = validate_contract(root)
        for relative in ['mnt/p3/vial.json', *('usr/share/hidloom/' + p for p in contract['source_bindings']['vial_definitions'])]:
            path = target / relative
            payload = json.loads(path.read_text(encoding='utf-8'))
            payload.update(plan['vial_identity'])
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (target / RECEIPT).write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    verify(root, target, profile)


def verify(root: Path, target: Path, profile: str) -> list[str]:
    plan = plan_for(root, profile)
    if (target / GADGET).read_text(encoding='utf-8') != expected_gadget(root, plan):
        raise ValueError('M6 gadget identity differs from selected profile')
    if json.loads((target / RECEIPT).read_text()) != plan:
        raise ValueError('M6 identity receipt differs from selected profile')
    paths = [GADGET, RECEIPT]
    if profile == 'public_formal':
        for relative in ['mnt/p3/config.json', 'usr/share/hidloom/config/default/config.json']:
            device = json.loads((target / relative).read_text())['device']
            if any(device.get(k) != v for k, v in plan['device_config'].items()):
                raise ValueError(f'M6 device identity mismatch: {relative}')
            paths.append(relative)
        contract = validate_contract(root)
        for relative in ['mnt/p3/vial.json', *('usr/share/hidloom/' + p for p in contract['source_bindings']['vial_definitions'])]:
            vial = json.loads((target / relative).read_text())
            if any(vial.get(k) != v for k, v in plan['vial_identity'].items()):
                raise ValueError(f'M6 Vial identity mismatch: {relative}')
            paths.append(relative)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--profile', choices=['development_compatibility', 'public_formal'], default='development_compatibility')
    args = parser.parse_args()
    stage(ROOT, args.target, args.profile)


if __name__ == '__main__':
    main()
