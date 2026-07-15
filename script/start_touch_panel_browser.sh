#!/usr/bin/env bash
set -euo pipefail

HTTPD_URL="${HIDLOOM_TOUCH_PANEL_URL:-}"
if [[ -z "$HTTPD_URL" ]]; then
    HTTPD_URL="https://127.0.0.1/?keyboard=1"
fi

start_delay="${HIDLOOM_TOUCH_PANEL_BROWSER_START_DELAY_SEC:-20}"
if [[ "$start_delay" =~ ^[0-9]+$ ]] && [[ "$start_delay" -gt 0 ]]; then
    sleep "$start_delay"
fi

chromium_window_size=()
chromium_remote_debugging=()
output_transform="${HIDLOOM_TOUCH_PANEL_OUTPUT_TRANSFORM:-}"
output_name="${HIDLOOM_TOUCH_PANEL_OUTPUT:-DSI-1}"
runtime_dir="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
wayland_display="${WAYLAND_DISPLAY:-wayland-0}"
export XDG_RUNTIME_DIR="$runtime_dir"
export WAYLAND_DISPLAY="$wayland_display"
if [[ -n "$output_transform" ]] && command -v wlr-randr >/dev/null 2>&1; then
    wlr-randr --output "$output_name" --transform "$output_transform" || true
fi

window_size="${HIDLOOM_TOUCH_PANEL_WINDOW_SIZE:-}"
if [[ -z "$window_size" ]] && command -v wlr-randr >/dev/null 2>&1; then
    output_info="$(
        wlr-randr 2>/dev/null \
            | awk -v output="$output_name" '
                $1 == output { in_output = 1; next }
                /^[^[:space:]]/ { in_output = 0 }
                in_output && /current/ {
                    for (i = 1; i <= NF; i++) {
                        if ($i ~ /^[0-9]+x[0-9]+$/) {
                            mode = $i
                        }
                    }
                }
                in_output && /Transform:/ {
                    transform = $2
                }
                END {
                    if (mode != "") {
                        print mode " " transform
                    }
                }
            ' || true
    )"
    if [[ "$output_info" =~ ^([0-9]+)x([0-9]+)[[:space:]]+([^[:space:]]+)$ ]]; then
        width="${BASH_REMATCH[1]}"
        height="${BASH_REMATCH[2]}"
        active_transform="${BASH_REMATCH[3]}"
        if [[ "$active_transform" == "90" || "$active_transform" == "270" ]]; then
            window_size="${height},${width}"
        else
            window_size="${width},${height}"
        fi
    fi
fi
if [[ "$window_size" =~ ^[0-9]+[,x][0-9]+$ ]]; then
    chromium_window_size=(--window-size="${window_size/x/,}")
fi

remote_debugging_port="${HIDLOOM_TOUCH_PANEL_REMOTE_DEBUGGING_PORT:-}"
remote_debugging_address="${HIDLOOM_TOUCH_PANEL_REMOTE_DEBUGGING_ADDRESS:-127.0.0.1}"
if [[ "$remote_debugging_port" =~ ^[0-9]+$ ]] && [[ "$remote_debugging_port" -gt 0 ]]; then
    chromium_remote_debugging=(
        --remote-debugging-address="$remote_debugging_address"
        --remote-debugging-port="$remote_debugging_port"
    )
fi

repair_kiosk_navigation() {
    if [[ -z "$remote_debugging_port" ]]; then
        return 0
    fi

    local repair_delay="${HIDLOOM_TOUCH_PANEL_BROWSER_REPAIR_DELAY_SEC:-8}"
    local repair_attempts="${HIDLOOM_TOUCH_PANEL_BROWSER_REPAIR_ATTEMPTS:-5}"
    local repair_interval="${HIDLOOM_TOUCH_PANEL_BROWSER_REPAIR_INTERVAL_SEC:-2}"
    if [[ ! "$repair_delay" =~ ^[0-9]+$ ]]; then
        repair_delay=8
    fi
    if [[ ! "$repair_attempts" =~ ^[0-9]+$ ]] || [[ "$repair_attempts" -lt 1 ]]; then
        repair_attempts=5
    fi
    if [[ ! "$repair_interval" =~ ^[0-9]+$ ]]; then
        repair_interval=2
    fi

    (
        sleep "$repair_delay"
        HIDLOOM_TOUCH_PANEL_REPAIR_URL="$HTTPD_URL" \
        HIDLOOM_TOUCH_PANEL_REPAIR_ADDRESS="$remote_debugging_address" \
        HIDLOOM_TOUCH_PANEL_REPAIR_PORT="$remote_debugging_port" \
        HIDLOOM_TOUCH_PANEL_REPAIR_ATTEMPTS="$repair_attempts" \
        HIDLOOM_TOUCH_PANEL_REPAIR_INTERVAL="$repair_interval" \
        python3 - <<'PY'
import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request

try:
    import websockets
except Exception as exc:  # pragma: no cover - depends on target OS packages
    print(f"touch-panel browser repair skipped: websockets unavailable: {exc}", file=sys.stderr)
    raise SystemExit(0)

target_url = os.environ["HIDLOOM_TOUCH_PANEL_REPAIR_URL"]
address = os.environ.get("HIDLOOM_TOUCH_PANEL_REPAIR_ADDRESS", "127.0.0.1")
port = int(os.environ["HIDLOOM_TOUCH_PANEL_REPAIR_PORT"])
attempts = int(os.environ.get("HIDLOOM_TOUCH_PANEL_REPAIR_ATTEMPTS", "5"))
interval = int(os.environ.get("HIDLOOM_TOUCH_PANEL_REPAIR_INTERVAL", "2"))
json_url = f"http://{address}:{port}/json/list"


def load_tabs():
    with urllib.request.urlopen(json_url, timeout=3) as response:
        return json.load(response)


async def call_cdp(ws_url, method, params=None, timeout=6):
    async with websockets.connect(ws_url, open_timeout=4, ping_interval=None) as conn:
        await conn.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
        while True:
            message = json.loads(await asyncio.wait_for(conn.recv(), timeout=timeout))
            if message.get("id") == 1:
                return message


async def page_state(ws_url):
    response = await call_cdp(ws_url, "Runtime.evaluate", {
        "expression": """
(() => ({
  href: location.href,
  title: document.title,
  readyState: document.readyState,
  bodyLength: document.body ? document.body.innerHTML.length : 0
}))()
""",
        "returnByValue": True,
    })
    return response.get("result", {}).get("result", {}).get("value", {}) or {}


def main():
    last_error = None
    for _ in range(attempts):
        try:
            tabs = load_tabs()
            if not tabs:
                time.sleep(interval)
                continue
            tab = next((item for item in tabs if item.get("type") == "page"), tabs[0])
            current_url = tab.get("url") or ""
            ws_url = tab.get("webSocketDebuggerUrl")
            state = {}
            if ws_url:
                state = asyncio.run(page_state(ws_url))
            actual_url = state.get("href") or current_url
            body_length = int(state.get("bodyLength") or 0)
            if actual_url == target_url and body_length > 0:
                return
            if (
                actual_url in ("", "about:blank")
                or str(actual_url).startswith("chrome-error://")
                or (actual_url == target_url and body_length == 0)
            ) and ws_url:
                asyncio.run(call_cdp(ws_url, "Page.navigate", {"url": target_url}))
                print(
                    "touch-panel browser repair: navigated from "
                    f"{actual_url or current_url or '<empty>'} to {target_url}",
                    file=sys.stderr,
                )
                time.sleep(interval)
                continue
        except (OSError, urllib.error.URLError, TimeoutError, asyncio.TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(interval)
    if last_error is not None:
        print(f"touch-panel browser repair did not complete: {last_error}", file=sys.stderr)


main()
PY
    ) &
}

CHROMIUM_BIN="${HIDLOOM_TOUCH_PANEL_BROWSER:-}"
if [[ -z "$CHROMIUM_BIN" ]]; then
    for candidate in /usr/lib/chromium/chromium chromium chromium-browser; do
        if command -v "$candidate" >/dev/null 2>&1; then
            CHROMIUM_BIN="$(command -v "$candidate")"
            break
        fi
    done
fi

if [[ -z "$CHROMIUM_BIN" ]]; then
    echo "No Chromium browser found" >&2
    exit 1
fi

for _ in {1..60}; do
    if curl -k -fsS -o /dev/null "$HTTPD_URL"; then
        break
    fi
    sleep 1
done

profile_dir="${HIDLOOM_TOUCH_PANEL_BROWSER_PROFILE:-$HOME/.config/hidloom/chromium-kiosk}"
rm -rf "$profile_dir"
mkdir -p "$profile_dir"

"$CHROMIUM_BIN" \
    --ozone-platform=wayland \
    --kiosk \
    --no-first-run \
    --no-default-browser-check \
    --noerrdialogs \
    --disable-infobars \
    --disable-extensions \
    --disable-component-extensions-with-background-pages \
    --disable-translate \
    --disable-session-crashed-bubble \
    --disable-gpu \
    --disable-vulkan \
    --disable-features=Vulkan \
    --password-store=basic \
    --ignore-certificate-errors \
    --touch-events=enabled \
    "${chromium_window_size[@]}" \
    "${chromium_remote_debugging[@]}" \
    --user-data-dir="$profile_dir" \
    "$HTTPD_URL" &
browser_pid="$!"

repair_kiosk_navigation
wait "$browser_pid"
