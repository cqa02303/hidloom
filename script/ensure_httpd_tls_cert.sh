#!/usr/bin/env bash
set -euo pipefail

CERT_PATH="${1:-/mnt/p3/httpd.crt}"
KEY_PATH="${2:-/mnt/p3/httpd.key}"
COMMON_NAME="${HTTPD_TLS_COMMON_NAME:-cqa02303v5.local}"
DAYS="${HTTPD_TLS_DAYS:-3650}"

if [[ -s "$CERT_PATH" && -s "$KEY_PATH" ]]; then
    chmod 0644 "$CERT_PATH" || true
    chmod 0600 "$KEY_PATH" || true
    exit 0
fi

if ! command -v openssl >/dev/null 2>&1; then
    echo "openssl is required to generate HTTPS certificate" >&2
    exit 1
fi

install -d -m 0755 "$(dirname "$CERT_PATH")" "$(dirname "$KEY_PATH")"
tmp_cert="$(mktemp "${CERT_PATH}.XXXXXX")"
tmp_key="$(mktemp "${KEY_PATH}.XXXXXX")"
rm -f "$tmp_cert" "$tmp_key"

alt_names="DNS:$COMMON_NAME,DNS:$(hostname),IP:127.0.0.1"
for ip in $(hostname -I 2>/dev/null || true); do
    case "$ip" in
        *:*) ;; # IPv6 の表記揺れは避け、LAN IPv4 を優先する
        *) alt_names="${alt_names},IP:${ip}" ;;
    esac
done
if [[ -n "${HTTPD_TLS_ALT_NAMES:-}" ]]; then
    alt_names="${alt_names},${HTTPD_TLS_ALT_NAMES}"
fi

openssl req \
    -x509 \
    -newkey rsa:2048 \
    -nodes \
    -sha256 \
    -days "$DAYS" \
    -keyout "$tmp_key" \
    -out "$tmp_cert" \
    -subj "/CN=$COMMON_NAME" \
    -addext "subjectAltName=$alt_names"

chmod 0644 "$tmp_cert"
chmod 0600 "$tmp_key"
mv "$tmp_cert" "$CERT_PATH"
mv "$tmp_key" "$KEY_PATH"
