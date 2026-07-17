#!/usr/bin/env python3
"""Regression tests for HTTP OLED customization and runtime overrides."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import types
from contextlib import contextmanager


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daemon" / "http"))
sys.path.insert(0, str(ROOT / "daemon"))
sys.path.insert(0, str(ROOT))

from i2cd.icons import BITMAP_FILE, default_icon_payload, icon_bitmap, reload_icon_bitmaps  # noqa: E402
from i2cd.oled_customization import (  # noqa: E402
    LAYOUT_FILE,
    READY_ITEM_CATALOG,
    atomic_write_document,
    default_document,
    icon_group_catalog,
    invalidate_cache,
    load_effective_document,
    normalize_document,
    reset_document,
)
from oled_api import oled_get_response, oled_put_response, oled_reset_response  # noqa: E402


class JsonRequest:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


def response_json(response) -> dict:
    return json.loads(response.text)


def test_schema_and_persistence() -> None:
    layout_source = json.loads(LAYOUT_FILE.read_text(encoding="utf-8"))
    assert layout_source["schema"] == "hidloom.oled.layout.v1"
    assert [item["id"] for item in layout_source["ready"]["items"]] == [entry["id"] for entry in READY_ITEM_CATALOG]
    defaults = default_icon_payload()
    document = default_document(defaults)
    normalized = normalize_document(document, defaults)
    assert normalized == document
    assert [item["id"] for item in normalized["ready"]["items"]] == [entry["id"] for entry in READY_ITEM_CATALOG]

    changed = json.loads(json.dumps(document))
    changed["icons"]["bt"]["rows"][0] = "111111"
    changed["ready"]["items"][0]["enabled"] = False
    changed["ready"]["items"][1], changed["ready"]["items"][2] = (
        changed["ready"]["items"][2],
        changed["ready"]["items"][1],
    )
    normalized = normalize_document(changed, defaults)
    assert normalized["icons"]["bt"]["rows"][0] == "111111"
    assert normalized["ready"]["items"][0]["enabled"] is False
    assert normalized["ready"]["items"][1]["id"] == "output_mode"

    invalid = json.loads(json.dumps(document))
    invalid["icons"]["bt"]["rows"][0] = "222222"
    try:
        normalize_document(invalid, defaults)
    except ValueError as exc:
        assert "only 0/1" in str(exc)
    else:
        raise AssertionError("non-binary icon accepted")

    duplicate = json.loads(json.dumps(document))
    duplicate["ready"]["items"][1]["id"] = duplicate["ready"]["items"][0]["id"]
    try:
        normalize_document(duplicate, defaults)
    except ValueError as exc:
        assert "duplicated" in str(exc)
    else:
        raise AssertionError("duplicate Ready item accepted")

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "oled_customization.json"
        atomic_write_document(path, normalized)
        loaded, source, errors = load_effective_document(defaults, path)
        assert loaded == normalized
        assert source == "runtime"
        assert errors == []
        assert path.stat().st_mode & 0o777 == 0o644
        assert reset_document(path) is True
        loaded, source, errors = load_effective_document(defaults, path)
        assert loaded == document
        assert source == "default"
        assert errors == []


def test_icon_group_catalog() -> None:
    defaults = default_icon_payload()
    groups = icon_group_catalog(defaults)
    assert [group["id"] for group in groups] == ["daemon_status", "output_mode", "other"]
    assert [item["name"] for item in groups[0]["items"]] == [
        "mtx", "core", "cmp", "out", "uid", "led", "btd", "web", "hid", "vial",
    ]
    assert [item["name"] for item in groups[1]["items"]] == [
        "auto", "usb", "bt", "pi", "wifi0", "wifi3",
    ]
    assert groups[2]["items"] == [{"name": "lgc", "label": "Combined logicd"}]
    grouped_names = [item["name"] for group in groups for item in group["items"]]
    assert len(grouped_names) == len(set(grouped_names))
    assert set(grouped_names) == set(defaults)


def test_runtime_icon_override() -> None:
    defaults = default_icon_payload()
    document = default_document(defaults)
    original_env = os.environ.get("HIDLOOM_OLED_CUSTOMIZATION_FILE")
    original_rows = icon_bitmap("bt").rows
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "oled_customization.json"
            os.environ["HIDLOOM_OLED_CUSTOMIZATION_FILE"] = str(path)
            document["icons"]["bt"]["rows"][0] = "111111"
            atomic_write_document(path, normalize_document(document, defaults))
            invalidate_cache()
            assert icon_bitmap("bt").rows[0] == "111111"
            assert icon_bitmap("http") is icon_bitmap("web")
            assert icon_bitmap("usbd") is icon_bitmap("hid")
            reset_document(path)
            invalidate_cache()
            assert icon_bitmap("bt").rows == original_rows
    finally:
        if original_env is None:
            os.environ.pop("HIDLOOM_OLED_CUSTOMIZATION_FILE", None)
        else:
            os.environ["HIDLOOM_OLED_CUSTOMIZATION_FILE"] = original_env
        invalidate_cache()
        reload_icon_bitmaps(BITMAP_FILE)


def test_i2cd_ready_layout_override() -> None:
    sys.modules.setdefault("luma", types.ModuleType("luma"))
    sys.modules.setdefault("luma.core", types.ModuleType("luma.core"))
    sys.modules["luma.core.interface"] = types.ModuleType("luma.core.interface")
    sys.modules["luma.core.interface.serial"] = types.SimpleNamespace(i2c=lambda *args, **kwargs: object())
    sys.modules["luma.oled"] = types.ModuleType("luma.oled")
    sys.modules["luma.oled.device"] = types.SimpleNamespace(sh1107=lambda *args, **kwargs: object())
    sys.modules["luma.core.render"] = types.SimpleNamespace(canvas=lambda _device: None)
    sys.modules["luma.core.error"] = types.SimpleNamespace(DeviceNotFoundError=RuntimeError)
    from i2cd import i2cd as i2cd_daemon

    class Draw:
        def __init__(self):
            self.texts: list[str] = []

        def rectangle(self, *_args, **_kwargs):
            return None

        def line(self, *_args, **_kwargs):
            return None

        def text(self, _position, value, **_kwargs):
            self.texts.append(str(value))

        def point(self, *_args, **_kwargs):
            return None

    class Font:
        def getlength(self, value):
            return len(str(value)) * 6

    class Device:
        width = 64
        height = 128

    defaults = default_icon_payload()
    document = default_document(defaults)
    for item in document["ready"]["items"]:
        item["enabled"] = item["id"] in {"cpu", "layer"}
        item["separator_after"] = False
    document["ready"]["items"].sort(key=lambda item: {"cpu": 0, "layer": 1}.get(item["id"], 2))
    original_env = os.environ.get("HIDLOOM_OLED_CUSTOMIZATION_FILE")
    original_canvas = i2cd_daemon.canvas
    draw = Draw()

    @contextmanager
    def fake_canvas(_device):
        yield draw

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "oled_customization.json"
            os.environ["HIDLOOM_OLED_CUSTOMIZATION_FILE"] = str(path)
            atomic_write_document(path, normalize_document(document, defaults))
            invalidate_cache()
            i2cd_daemon.canvas = fake_canvas
            i2cd_daemon._draw_ready(
                Device(),
                Font(),
                2,
                [2],
                True,
                True,
                system_status={"cpu_percent": 34, "cpu_temp": 50},
            )
            assert draw.texts == ["CPU:34 %", "Layer: 2"], draw.texts
    finally:
        i2cd_daemon.canvas = original_canvas
        if original_env is None:
            os.environ.pop("HIDLOOM_OLED_CUSTOMIZATION_FILE", None)
        else:
            os.environ["HIDLOOM_OLED_CUSTOMIZATION_FILE"] = original_env
        invalidate_cache()


async def test_http_api() -> None:
    defaults = default_icon_payload()
    document = default_document(defaults)
    notifications: list[str] = []

    async def notify(socket_path: str) -> dict:
        notifications.append(socket_path)
        return {"result": "ok", "mode": "test"}

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        customization_file = root / "oled_customization.json"
        i2cd_json = root / "i2cd.json"
        i2cd_json.write_text(json.dumps({
            "oled": {"width": 64, "height": 128},
            "ipc": {"i2c_socket": str(root / "i2c.sock")},
        }), encoding="utf-8")

        get_data = response_json(oled_get_response(customization_file, i2cd_json))
        assert get_data["result"] == "ok"
        assert get_data["source"] == "default"
        assert get_data["display"] == {"width": 64, "height": 128}
        assert len(get_data["item_catalog"]) == len(READY_ITEM_CATALOG)
        assert get_data["icon_groups"] == icon_group_catalog(defaults)

        document["ready"]["items"][-1]["enabled"] = False
        put_response = await oled_put_response(
            JsonRequest(document),
            customization_file,
            i2cd_json,
            notify_i2cd=notify,
        )
        put_data = response_json(put_response)
        assert put_response.status == 200
        assert put_data["source"] == "runtime"
        assert put_data["apply"] == {"result": "ok", "mode": "test"}
        assert put_data["customization"]["ready"]["items"][-1]["enabled"] is False
        assert notifications == [str(root / "i2c.sock")]

        bad = json.loads(json.dumps(document))
        bad["icons"]["usb"]["rows"][0] = "bad"
        bad_response = await oled_put_response(
            JsonRequest(bad),
            customization_file,
            i2cd_json,
            notify_i2cd=notify,
        )
        assert bad_response.status == 400

        reset_response = await oled_reset_response(
            customization_file,
            i2cd_json,
            notify_i2cd=notify,
        )
        reset_data = response_json(reset_response)
        assert reset_response.status == 200
        assert reset_data["source"] == "default"
        assert reset_data["removed"] is True
        assert not customization_file.exists()


def test_http_assets() -> None:
    index = (ROOT / "daemon/http/static/index.html").read_text(encoding="utf-8")
    tabs = (ROOT / "daemon/http/static/tabs.js").read_text(encoding="utf-8")
    panel = (ROOT / "daemon/http/static/oled_panel.js").read_text(encoding="utf-8")
    css = (ROOT / "daemon/http/static/oled_panel.css").read_text(encoding="utf-8")
    httpd = (ROOT / "daemon/http/httpd.py").read_text(encoding="utf-8")
    assert 'data-app-tab="oled"' in index
    assert 'id="oled-panel"' in index
    assert 'src="/static/oled_panel.js"' in index
    assert 'href="/static/oled_panel.css"' in index
    assert '"oled"' in tabs
    assert "fetchOledCustomization();" in tabs
    assert 'fetch("/api/oled"' in panel
    assert 'csrfFetch("/api/oled"' in panel
    assert 'csrfFetch("/api/oled/reset"' in panel
    assert "左クリック" in index
    assert "右クリック" in index
    assert 'id="oled-tool-pen"' not in index
    assert 'id="oled-tool-eraser"' not in index
    assert "function oledPaintValueForPointerButton" in panel
    assert 'if (pointerButton === 0) return "1"' in panel
    assert 'if (pointerButton === 2) return "0"' in panel
    assert 'grid.addEventListener("contextmenu", event => event.preventDefault())' in panel
    assert "function stopOledPainting" in panel
    assert "function oledPointerButtonIsPressed" in panel
    assert "function handleOledPointerOver" in panel
    assert "if (!oledPointerButtonIsPressed(event))" in panel
    assert 'window.addEventListener("pointerup", stopOledPainting, true)' in panel
    assert 'window.addEventListener("pointercancel", stopOledPainting, true)' in panel
    assert 'window.addEventListener("blur", stopOledPainting)' in panel
    assert 'cell.classList.toggle("on", _oledEditorState.paintValue === "1")' in panel
    assert "setOledTool" not in panel
    assert "eraser" not in panel
    assert "function floodFillOledIcon" in panel
    assert "data.icon_groups" in panel
    assert 'section.className = "oled-icon-group"' in panel
    assert 'choices.className = "oled-icon-group-list"' in panel
    assert "Object.entries(_oledEditorState.customization.icons)" not in panel
    assert "function moveOledLayoutItem" in panel
    assert "function renderOledScreenPreview" in panel
    assert 'class="oled-ready-column"' in index
    assert index.index('class="oled-card oled-screen-preview-card"') < index.index('class="oled-card oled-layout-editor"')
    assert "document.createElement(\"style\")" not in panel
    assert ".oled-pixel-grid" in css
    assert ".oled-icon-group + .oled-icon-group" in css
    assert ".oled-icon-group-list" in css
    assert ".oled-ready-column" in css
    assert ".oled-layout-row" in css
    assert 'app.router.add_get("/api/oled"' in httpd
    assert 'app.router.add_put("/api/oled"' in httpd
    assert 'app.router.add_post("/api/oled/reset"' in httpd


def main() -> None:
    test_schema_and_persistence()
    test_icon_group_catalog()
    test_runtime_icon_override()
    test_i2cd_ready_layout_override()
    asyncio.run(test_http_api())
    test_http_assets()
    print("ok: OLED HTTP customization")


if __name__ == "__main__":
    main()
