# cqa02303v5rpi Hardware

This directory contains the editable KiCad schematic and PCB sources for the
HIDloom cqa02303v5 keyboard hardware.

## Review PDFs

- [Schematic PDF](cqa02303v5rpi-schematic.pdf) contains all four hierarchical
  schematic pages.
- [PCB fabrication-layer PDF](cqa02303v5rpi-pcb-fabrication-layers.pdf) contains
  eight bookmarked pages in this order: `F.Cu`, `F.Mask`, `F.Silkscreen`,
  `F.Paste`, `B.Cu`, `B.Mask`, `B.Silkscreen`, and `B.Paste`. `Edge.Cuts` and
  actual drill shapes are shown on every page.

These PDFs are review aids, not manufacturing outputs. Generate and inspect
fresh Gerber and Excellon files from the editable KiCad sources before PCB
fabrication.

## Regeneration

The checked-in PDFs were exported with KiCad 10.0.1. Regenerate both files and
their source/output checksum record with:

```console
python3 tools/export_hardware_pdfs.py --force --kicad-cli-command kicad-cli
```

On Windows, quote the complete `kicad-cli.exe` path if it is not on `PATH`.
The generator stages and validates both PDFs before replacing existing output.
