#!/usr/bin/env python3
"""Export reviewable schematic and PCB fabrication-layer PDFs with KiCad."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT_DIR = ROOT / "kicad" / "cqa02303v5rpi"
SCHEMA = "hidloom.hardware-pdf-exports.v1"
SCHEMATIC_PDF = "cqa02303v5rpi-schematic.pdf"
PCB_PDF = "cqa02303v5rpi-pcb-fabrication-layers.pdf"
PROVENANCE_JSON = "cqa02303v5rpi-hardware-pdf-exports.json"
SOURCE_FILES = (
    "cqa02303v5rpi.kicad_pro",
    "cqa02303v5rpi.kicad_sch",
    "keymap.kicad_sch",
    "led.kicad_sch",
    "mouse_sch.kicad_sch",
    "other.kicad_sch",
    "cqa02303v5rpi.kicad_pcb",
)
PCB_LAYERS = (
    "F.Cu",
    "F.Mask",
    "F.Silkscreen",
    "F.Paste",
    "B.Cu",
    "B.Mask",
    "B.Silkscreen",
    "B.Paste",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_regular_file(path: Path, description: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"{description} is missing or unsafe: {path}")


def run(command: list[str], *, cwd: Path) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="strict",
    )
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip()
        raise SystemExit(
            f"command failed ({result.returncode}): {' '.join(command)}"
            + (f"\n{detail}" if detail else "")
        )
    return result.stdout.strip()


def require_pdf(path: Path) -> None:
    require_regular_file(path, "generated PDF")
    data = path.read_bytes()
    if len(data) < 1024 or not data.startswith(b"%PDF-") or b"%%EOF" not in data[-1024:]:
        raise SystemExit(f"generated PDF is malformed: {path}")


def build_payload(
    project_dir: Path,
    generated: dict[str, Path],
    kicad_version: str,
) -> dict[str, object]:
    sources = {
        name: {
            "path": name,
            "size": (project_dir / name).stat().st_size,
            "sha256": sha256(project_dir / name),
        }
        for name in SOURCE_FILES
    }
    outputs = {
        role: {
            "path": path.name,
            "size": path.stat().st_size,
            "sha256": sha256(path),
        }
        for role, path in generated.items()
    }
    return {
        "schema": SCHEMA,
        "generator": "tools/export_hardware_pdfs.py",
        "kicad_version": kicad_version,
        "project": project_dir.name,
        "sources": sources,
        "outputs": outputs,
        "schematic_contract": {
            "all_hierarchical_pages": True,
            "black_and_white": True,
            "background_color": False,
        },
        "pcb_contract": {
            "layers": list(PCB_LAYERS),
            "common_layers": ["Edge.Cuts"],
            "multipage": True,
            "black_and_white": True,
            "drill_shape": "actual",
            "border_and_title_block": True,
            "manufacturing_output": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", type=Path, default=DEFAULT_PROJECT_DIR)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--kicad-cli-command",
        nargs="+",
        default=["kicad-cli"],
        metavar="COMMAND",
        help="KiCad CLI command prefix; defaults to kicad-cli",
    )
    args = parser.parse_args()

    project_dir = args.project_dir.resolve()
    output_dir = (args.output_dir or project_dir).resolve()
    for name in SOURCE_FILES:
        require_regular_file(project_dir / name, "KiCad source")
    output_dir.mkdir(parents=True, exist_ok=True)

    destinations = {
        "schematic": output_dir / SCHEMATIC_PDF,
        "pcb_fabrication_layers": output_dir / PCB_PDF,
    }
    provenance = output_dir / PROVENANCE_JSON
    existing = [path for path in [*destinations.values(), provenance] if path.exists()]
    if existing and not args.force:
        raise SystemExit("refusing to overwrite existing output: " + ", ".join(map(str, existing)))
    for path in [*destinations.values(), provenance]:
        if path.is_symlink():
            raise SystemExit(f"refusing to replace symlink output: {path}")

    cli = list(args.kicad_cli_command)
    kicad_version = run([*cli, "version"], cwd=ROOT).splitlines()[0].strip()
    with tempfile.TemporaryDirectory(prefix=".hardware-pdf-export-", dir=output_dir) as temporary:
        stage = Path(temporary)
        staged = {
            "schematic": stage / SCHEMATIC_PDF,
            "pcb_fabrication_layers": stage / PCB_PDF,
        }
        run(
            [
                *cli,
                "sch",
                "export",
                "pdf",
                "--output",
                str(staged["schematic"]),
                "--black-and-white",
                "--no-background-color",
                str(project_dir / "cqa02303v5rpi.kicad_sch"),
            ],
            cwd=ROOT,
        )
        run(
            [
                *cli,
                "pcb",
                "export",
                "pdf",
                "--output",
                str(staged["pcb_fabrication_layers"]),
                "--layers",
                ",".join(PCB_LAYERS),
                "--common-layers",
                "Edge.Cuts",
                "--mode-multipage",
                "--black-and-white",
                "--drill-shape-opt",
                "2",
                "--include-border-title",
                str(project_dir / "cqa02303v5rpi.kicad_pcb"),
            ],
            cwd=ROOT,
        )
        for path in staged.values():
            require_pdf(path)
        payload = build_payload(project_dir, staged, kicad_version)
        staged_provenance = stage / PROVENANCE_JSON
        staged_provenance.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        for role, destination in destinations.items():
            os.replace(staged[role], destination)
        os.replace(staged_provenance, provenance)

    for role, path in destinations.items():
        print(f"{role}: {path} sha256={sha256(path)} size={path.stat().st_size}")
    print(f"provenance: {provenance}")


if __name__ == "__main__":
    main()
