#!/usr/bin/env python3
"""Freshness checks for HTTP split notes in docs/architecture/module-structure.md."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "architecture" / "module-structure.md"


def main() -> None:
    text = DOC.read_text(encoding="utf-8")
    required = [
        "更新日: 2026-06-25",
        "`daemon/http/security_api.py` | 互換 facade",
        "`daemon/http/auth_tls.py` | HTTP Basic auth",
        "`daemon/http/security_middleware.py` | private-network allowlist",
        "`daemon/http/vil_apply.py` | `.vil` import 時の remap / interaction settings / macro buffer 適用 helper",
        "`daemon/http/vil_macro_import.py` | `.vil` import 時の Vial macro buffer",
        "`daemon/http/vil_response.py` | `.vil` export response の安全な filename / Content-Disposition helper",
        "`daemon/http/scripts_api.py` | Script editor API の request validation、audit logging、HTTP response 組み立て",
        "`daemon/http/script_store.py` | `KC_SHn.sh` の探索、label、runtime script 書き込み・削除、path 設定 helper",
        "`daemon/http/script_runner.py` | script subprocess 実行、check-run 一時 script 作成、timeout、実行環境、stdout / stderr trim",
        "`daemon/http/static/lighting_role_preview_controls.js`",
        "HTTP data retention notes",
        "`settings.vial_macro_buffer` は `.vil` round-trip / Vial 互換のための raw buffer として保持します。",
        "`macros` は project runtime / script 表示で使いやすい展開済み表現として保持します。",
        "runtime script は `/mnt/p3/script` を優先するユーザー編集データとして扱います。",
        "`daemon/i2cd/connectivity.py` | OLED connectivity icon row 用の read-only status snapshot helper",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        raise AssertionError(
            f"architecture/module-structure.md is missing expected HTTP split notes: {missing!r}"
        )
    print("ok: module structure HTTP split docs are current")


if __name__ == "__main__":
    main()
