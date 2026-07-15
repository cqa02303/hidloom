"""HTTP Basic auth and TLS helpers for httpd.

This module contains low-frequency authentication and certificate path logic so
httpd.py can stay focused on app wiring and route handlers.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import socket
import ssl
from pathlib import Path
from typing import Callable

from aiohttp import web


def http_basic_auth_file(config_json: Path) -> Path:
    configured = os.environ.get("HTTPD_BASIC_AUTH_FILE")
    if configured:
        return Path(configured)
    runtime_path = Path("/mnt/p3/http_basic_auth.json")
    if runtime_path.parent.exists():
        return runtime_path
    return config_json.parent / "http_basic_auth.local.json"


def hash_http_basic_auth_password(password: str, *, iterations: int = 200_000) -> str:
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"


def verify_http_basic_auth_password(password: str, stored: str) -> bool:
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, iterations_text, salt_hex, digest_hex = stored.split("$", 3)
            iterations = int(iterations_text)
            expected = bytes.fromhex(digest_hex)
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), iterations)
            return hmac.compare_digest(actual, expected)
        except (ValueError, TypeError):
            return False
    return hmac.compare_digest(password, stored)


def resolve_initial_http_basic_auth_password(value: str | None) -> str:
    if value == "__HOSTNAME__":
        return socket.gethostname()
    if isinstance(value, str):
        return value
    return socket.gethostname()


def load_http_basic_auth(config_json: Path, auth_file: Callable[[], Path], log) -> tuple[str, str]:
    username = "admin"
    password = socket.gethostname()
    try:
        cfg = json.loads(config_json.read_text(encoding="utf-8"))
        auth_cfg = cfg.get("settings", {}).get("http_basic_auth", {})
        if isinstance(auth_cfg.get("username"), str) and auth_cfg["username"]:
            username = auth_cfg["username"]
        if "password" in auth_cfg:
            password = resolve_initial_http_basic_auth_password(auth_cfg.get("password"))
        if isinstance(auth_cfg.get("password_hash"), str):
            password = auth_cfg["password_hash"]
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Cannot load HTTP Basic auth config: %s", exc)
    try:
        path = auth_file()
        if path.exists():
            auth_data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(auth_data.get("username"), str) and auth_data["username"]:
                username = auth_data["username"]
            if isinstance(auth_data.get("password"), str):
                password = auth_data["password"]
            if isinstance(auth_data.get("password_hash"), str):
                password = auth_data["password_hash"]
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Cannot load HTTP Basic auth override: %s", exc)
    return username, password


def write_http_basic_auth_file(
    username: str,
    password: str,
    *,
    auth_file: Callable[[], Path],
    hash_password: Callable[[str], str],
) -> tuple[Path, str]:
    path = auth_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    password_hash = hash_password(password)
    tmp_path.write_text(
        json.dumps({"username": username, "password_hash": password_hash}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, path)
    return path, password_hash


def load_tls_paths(config_json: Path, log) -> tuple[Path, Path]:
    cert = os.environ.get("HTTPD_TLS_CERT")
    key = os.environ.get("HTTPD_TLS_KEY")
    if cert and key:
        return Path(cert), Path(key)
    try:
        cfg = json.loads(config_json.read_text(encoding="utf-8"))
        tls_cfg = cfg.get("settings", {}).get("http_tls", {})
        if isinstance(tls_cfg, dict):
            cert = cert or tls_cfg.get("cert")
            key = key or tls_cfg.get("key")
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Cannot load HTTP TLS config: %s", exc)
    return Path(cert or "/mnt/p3/httpd.crt"), Path(key or "/mnt/p3/httpd.key")


def build_ssl_context(config_json: Path, log) -> ssl.SSLContext:
    cert_path, key_path = load_tls_paths(config_json, log)
    if not cert_path.exists() or not key_path.exists():
        raise FileNotFoundError(f"TLS certificate/key not found: cert={cert_path} key={key_path}")
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(cert_path), str(key_path))
    return context


async def basic_auth_allowed(
    request: web.Request,
    *,
    username: str,
    password_hash: str,
    verify_password: Callable[[str, str], bool],
) -> bool:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(auth_header.removeprefix("Basic ").strip(), validate=True).decode("utf-8")
        request_username, request_password = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError):
        return False
    return hmac.compare_digest(request_username, username) and verify_password(request_password, password_hash)
