#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "export_hardware_pdfs.py"
PROJECT = ROOT / "kicad" / "cqa02303v5rpi"
PDFS = (
    "cqa02303v5rpi-schematic.pdf",
    "cqa02303v5rpi-pcb-fabrication-layers.pdf",
)
PROVENANCE = "cqa02303v5rpi-hardware-pdf-exports.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_tool(project: Path, output: Path, fake: Path, *, force: bool = False) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(TOOL),
        "--project-dir",
        str(project),
        "--output-dir",
        str(output),
    ]
    if force:
        command.append("--force")
    command.extend(["--kicad-cli-command", sys.executable, str(fake)])
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True)


def main() -> None:
    for name in PDFS:
        path = PROJECT / name
        assert path.is_file() and not path.is_symlink(), name
        data = path.read_bytes()
        assert len(data) > 100_000, name
        assert data.startswith(b"%PDF-") and b"%%EOF" in data[-1024:], name
    provenance = json.loads((PROJECT / PROVENANCE).read_text(encoding="utf-8"))
    assert provenance["schema"] == "hidloom.hardware-pdf-exports.v1"
    assert provenance["pcb_contract"]["layers"] == [
        "F.Cu",
        "F.Mask",
        "F.Silkscreen",
        "F.Paste",
        "B.Cu",
        "B.Mask",
        "B.Silkscreen",
        "B.Paste",
    ]
    assert provenance["pcb_contract"]["common_layers"] == ["Edge.Cuts"]
    assert provenance["pcb_contract"]["manufacturing_output"] is False
    for role, name in zip(("schematic", "pcb_fabrication_layers"), PDFS, strict=True):
        record = provenance["outputs"][role]
        assert record["path"] == name
        assert record["size"] == (PROJECT / name).stat().st_size
        assert record["sha256"] == digest(PROJECT / name)
    readme = (PROJECT / "README.md").read_text(encoding="utf-8")
    assert all(f"]({name})" in readme for name in PDFS)
    assert "not manufacturing outputs" in readme

    with tempfile.TemporaryDirectory() as temporary:
        fixture = Path(temporary)
        project = fixture / "project"
        output = fixture / "output"
        project.mkdir()
        for name in provenance["sources"]:
            (project / name).write_text(f"fixture {name}\n", encoding="utf-8")
        log = fixture / "calls.jsonl"
        fake = fixture / "fake_kicad.py"
        fake.write_text(
            """from pathlib import Path
import json
import os
import sys

args = sys.argv[1:]
with Path(os.environ['FAKE_KICAD_LOG']).open('a', encoding='utf-8') as stream:
    stream.write(json.dumps(args) + '\\n')
if args == ['version']:
    print('10.0.1-test')
    raise SystemExit(0)
output = Path(args[args.index('--output') + 1])
body = json.dumps(args, sort_keys=True).encode('utf-8')
output.write_bytes(b'%PDF-1.7\\n' + body + b'\\n' + b'x' * 2048 + b'\\n%%EOF\\n')
sys.stdout.buffer.write('export complete: 完了\\n'.encode('utf-8'))
""",
            encoding="utf-8",
            newline="\n",
        )
        previous = os.environ.get("FAKE_KICAD_LOG")
        os.environ["FAKE_KICAD_LOG"] = str(log)
        try:
            created = run_tool(project, output, fake)
            assert created.returncode == 0, created.stdout + created.stderr
            calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            assert calls[0] == ["version"]
            assert calls[1][0:3] == ["sch", "export", "pdf"]
            assert calls[2][0:3] == ["pcb", "export", "pdf"]
            assert calls[2][calls[2].index("--layers") + 1] == ",".join(
                provenance["pcb_contract"]["layers"]
            )
            assert calls[2][calls[2].index("--common-layers") + 1] == "Edge.Cuts"
            first_hashes = {name: digest(output / name) for name in PDFS}
            blocked = run_tool(project, output, fake)
            assert blocked.returncode != 0
            assert "refusing to overwrite existing output" in blocked.stderr
            assert len(log.read_text(encoding="utf-8").splitlines()) == 3
            assert {name: digest(output / name) for name in PDFS} == first_hashes
            replaced = run_tool(project, output, fake, force=True)
            assert replaced.returncode == 0, replaced.stdout + replaced.stderr
            assert len(log.read_text(encoding="utf-8").splitlines()) == 6
        finally:
            if previous is None:
                os.environ.pop("FAKE_KICAD_LOG", None)
            else:
                os.environ["FAKE_KICAD_LOG"] = previous

    print("ok: hardware PDF exports, provenance, and overwrite boundary")


if __name__ == "__main__":
    main()
