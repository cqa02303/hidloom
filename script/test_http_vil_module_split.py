#!/usr/bin/env python3
"""Static checks for VIL import/export helper split."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon" / "http"))
sys.path.insert(0, str(ROOT))

import vil_api  # noqa: E402
import vil_apply  # noqa: E402
import vil_macro_import  # noqa: E402
import vil_response  # noqa: E402


def main() -> None:
    assert hasattr(vil_macro_import, "apply_vial_macro_buffer")
    assert hasattr(vil_macro_import, "VialMacroImportResult")
    assert vil_api.apply_vial_macro_buffer is vil_macro_import.apply_vial_macro_buffer
    assert vil_api.safe_header_filename_part is vil_response.safe_header_filename_part
    assert vil_api.attachment_content_disposition is vil_response.attachment_content_disposition
    assert hasattr(vil_apply, "apply_vil_remaps")
    assert hasattr(vil_apply, "apply_vil_interaction_settings")
    assert hasattr(vil_apply, "apply_vil_macro_settings")

    vil_api_source = (ROOT / "daemon" / "http" / "vil_api.py").read_text(encoding="utf-8")
    apply_helper_source = (ROOT / "daemon" / "http" / "vil_apply.py").read_text(encoding="utf-8")
    macro_helper_source = (ROOT / "daemon" / "http" / "vil_macro_import.py").read_text(encoding="utf-8")
    response_helper_source = (ROOT / "daemon" / "http" / "vil_response.py").read_text(encoding="utf-8")

    assert "from vil_macro_import import apply_vial_macro_buffer" in vil_api_source
    assert "from vil_response import attachment_content_disposition, safe_header_filename_part" in vil_api_source
    assert "from vil_apply import apply_vil_interaction_settings, apply_vil_macro_settings, apply_vil_remaps" in vil_api_source
    assert "apply_vial_macro_buffer(config_json, plan.vial_macro_buffer)" not in vil_api_source
    assert "save_interaction_settings(config_json, vial_json, plan.interaction_settings)" not in vil_api_source
    assert "await send_ctrl_command({\"t\": \"M\"" not in vil_api_source
    assert "await send_ctrl_command({\"t\": \"S\"})" not in vil_api_source
    assert "base64.b64decode" not in vil_api_source
    assert "vial_macros_from_buffer" not in vil_api_source
    assert "DEFAULT_MACRO_BUFFER_SIZE" not in vil_api_source
    assert "KeycodeCodec" not in vil_api_source
    assert "re.sub" not in vil_api_source

    assert "def safe_header_filename_part" in response_helper_source
    assert "def attachment_content_disposition" in response_helper_source
    assert "re.sub" in response_helper_source

    assert "async def apply_vil_remaps" in apply_helper_source
    assert "async def apply_vil_interaction_settings" in apply_helper_source
    assert "async def apply_vil_macro_settings" in apply_helper_source
    assert "save_interaction_settings" in apply_helper_source
    assert "apply_vial_macro_buffer" in apply_helper_source
    assert "await send_ctrl_command({" in apply_helper_source

    assert "base64.b64decode" in macro_helper_source
    assert "vial_macros_from_buffer" in macro_helper_source
    assert "DEFAULT_MACRO_BUFFER_SIZE" in macro_helper_source
    assert "KeycodeCodec" in macro_helper_source
    assert "Existing non-VIAL macros are preserved" in macro_helper_source
    print("ok: VIL apply, macro import, and response helpers are split out of vil_api")


if __name__ == "__main__":
    main()
