"""Helpers for importing Vial macro buffers from .vil files.

The HTTP route should stay focused on request/response flow.  The macro buffer
conversion and config update are low-frequency .vil import details and live here.
"""
from __future__ import annotations

import base64
import binascii
import json
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DAEMON_ROOT = _REPO_ROOT / "daemon"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_DAEMON_ROOT) not in sys.path:
    sys.path.insert(0, str(_DAEMON_ROOT))

from viald.dynamic_protocol import vial_macros_from_buffer
from viald.keycode_codec import KeycodeCodec
from viald.protocol_defs import DEFAULT_MACRO_BUFFER_SIZE, DEFAULT_MACRO_COUNT


@dataclass(frozen=True)
class VialMacroImportResult:
    macro_count: int
    buffer_size: int


def apply_vial_macro_buffer(config_json: Path, encoded_buffer: str) -> VialMacroImportResult:
    """Store a Vial macro buffer in config and expand it to project macros.

    Existing non-VIAL macros are preserved.  Existing VIAL* macros are replaced by
    macros decoded from the imported buffer.
    """
    try:
        cfg = json.loads(config_json.read_text(encoding="utf-8"))
        macro_buffer = base64.b64decode(encoded_buffer.encode("ascii"), validate=True)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"macro import failed: {exc}") from exc
    except (ValueError, binascii.Error, UnicodeEncodeError) as exc:
        raise ValueError(f"macro import failed: invalid macro buffer: {exc}") from exc
    if not isinstance(cfg, dict):
        raise RuntimeError("macro import failed: config root is not object")
    cfg.setdefault("settings", {})
    cfg["settings"]["vial_macro_buffer"] = encoded_buffer
    if len(macro_buffer) < DEFAULT_MACRO_BUFFER_SIZE:
        macro_buffer += b"\x00" * (DEFAULT_MACRO_BUFFER_SIZE - len(macro_buffer))
    existing_macros = cfg.get("macros", {})
    if not isinstance(existing_macros, dict):
        existing_macros = {}
    decoded_macros = vial_macros_from_buffer(
        macro_buffer[:DEFAULT_MACRO_BUFFER_SIZE],
        macro_count=DEFAULT_MACRO_COUNT,
        codec=KeycodeCodec(),
    )
    cfg["macros"] = {
        **{key: value for key, value in existing_macros.items() if not str(key).startswith("VIAL")},
        **decoded_macros,
    }
    config_json.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return VialMacroImportResult(macro_count=len(decoded_macros), buffer_size=len(macro_buffer))
