#!/usr/bin/env python3
"""Static checks for HTTP security/auth module split."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon" / "http"))
sys.path.insert(0, str(ROOT))

import auth_tls  # noqa: E402
import security_api  # noqa: E402
import security_middleware  # noqa: E402


def main() -> None:
    assert security_api.basic_auth_allowed is auth_tls.basic_auth_allowed
    assert security_api.build_ssl_context is auth_tls.build_ssl_context
    assert security_api.http_basic_auth_file is auth_tls.http_basic_auth_file
    assert security_api.csrf_token_valid is security_middleware.csrf_token_valid
    assert security_api.remote_ip_allowed is security_middleware.remote_ip_allowed
    assert security_api.audit_field is security_middleware.audit_field

    auth_source = (ROOT / "daemon" / "http" / "auth_tls.py").read_text(encoding="utf-8")
    middleware_source = (ROOT / "daemon" / "http" / "security_middleware.py").read_text(encoding="utf-8")
    facade_source = (ROOT / "daemon" / "http" / "security_api.py").read_text(encoding="utf-8")
    httpd_source = (ROOT / "daemon" / "http" / "httpd.py").read_text(encoding="utf-8")

    assert "def basic_auth_allowed" in auth_source
    assert "def build_ssl_context" in auth_source
    assert "def load_http_basic_auth" in auth_source
    assert "def csrf_token_valid" in middleware_source
    assert "def remote_ip_allowed" in middleware_source
    assert "def audit_log" in middleware_source
    assert "from auth_tls import" in facade_source
    assert "from security_middleware import" in facade_source
    assert "def basic_auth_allowed" not in facade_source
    assert "def csrf_token_valid" not in facade_source
    assert "Compatibility exports" in facade_source
    assert "from security_api import" in httpd_source
    print("ok: HTTP security/auth helpers are split behind compatibility facade")


if __name__ == "__main__":
    main()
