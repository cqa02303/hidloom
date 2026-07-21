#!/usr/bin/env python3
"""Validate the dependency-free HTTP UI internationalization foundation."""
from __future__ import annotations

import http.server
import json
import re
import shutil
import socketserver
import subprocess
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "daemon/http/static/index.html"
I18N = ROOT / "daemon/http/static/i18n.js"
DESIGN = ROOT / "docs/feature/http-ui-internationalization-design.md"
STATIC = ROOT / "daemon/http/static"


def audit_dynamic_literals(source: str) -> None:
    pattern = re.compile(r'''(["'`])((?:\\.|(?!\1).)*[ぁ-んァ-ヶ一-龠](?:\\.|(?!\1).)*)\1''')
    values: list[str] = []
    for path in STATIC.glob("*.js"):
        if path == I18N:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith(("//", "*")):
                continue
            values.extend(match.group(2) for match in pattern.finditer(line))
    values = list(dict.fromkeys(values))
    node = f'''const vm=require("vm");
const ctx={{window:{{location:{{search:"?lang=en"}},localStorage:{{getItem:()=>null,setItem:()=>{{}}}},confirm:()=>true,prompt:()=>null,alert:()=>{{}},dispatchEvent:()=>{{}}}},navigator:{{languages:["en-US"],language:"en-US"}},document:{{addEventListener:()=>{{}},documentElement:{{}},querySelectorAll:()=>[]}},URLSearchParams,CustomEvent:function(){{}}}};
vm.createContext(ctx);vm.runInContext({json.dumps(source)},ctx);
const unresolved={json.dumps(values, ensure_ascii=False)}.filter(x=>!x.trim().startsWith("<")).map(x=>ctx.window.hidloomI18n.translateJapanese(x)).filter(x=>/[ぁ-んァ-ヶ一-龠]/.test(x));
if(unresolved.length){{console.error(JSON.stringify(unresolved,null,2));process.exit(1);}}'''
    subprocess.run(["node"], input=node, text=True, check=True)


def browser_smoke() -> None:
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome:
        return

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, _format: str, *args: object) -> None:
            pass

    handler = lambda *args, **kwargs: QuietHandler(  # noqa: E731
        *args, directory=str(ROOT / "daemon/http"), **kwargs
    )
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            rendered: dict[str, str] = {}
            for language in ("en", "ja"):
                result = subprocess.run(
                    [chrome, "--headless", "--no-sandbox", "--disable-gpu",
                     "--disable-dev-shm-usage", "--virtual-time-budget=3000", "--dump-dom",
                     f"http://127.0.0.1:{server.server_address[1]}/static/index.html?lang={language}"],
                    check=True, capture_output=True, text=True,
                )
                rendered[language] = result.stdout
        finally:
            server.shutdown()
            thread.join()

    assert '<html lang="en"' in rendered["en"]
    assert ">Keyboard<" in rendered["en"]
    assert not re.search(r"[ぁ-んァ-ヶ一-龠]", rendered["en"])
    assert '<html lang="ja"' in rendered["ja"]
    assert ">キーボード<" in rendered["ja"]


def main() -> None:
    index = INDEX.read_text(encoding="utf-8")
    source = I18N.read_text(encoding="utf-8")
    design = DESIGN.read_text(encoding="utf-8")

    assert index.index('/static/i18n.js') < index.index('/static/csrf.js')
    assert 'id="ui-language"' in index
    assert 'value="auto"' in index
    assert 'data-i18n="tabs.keyboard"' in index
    assert 'data-i18n="tabs.keymap"' in index
    assert 'data-i18n-title="actions.reload"' in index
    assert 'data-i18n-aria-label="language.selectLabel"' in index

    for required in (
        'const HIDLOOM_I18N_FALLBACK = "en"',
        "navigator.languages",
        "navigator.language",
        'new URLSearchParams(window.location.search).get("lang")',
        "window.localStorage.getItem(HIDLOOM_I18N_STORAGE_KEY)",
        "document.documentElement.lang = _hidloomLanguage",
        'window.dispatchEvent(new CustomEvent("hidloomlanguagechange"',
        "window.hidloomI18n",
    ):
        assert required in source

    assert "保存データ、keycode、API schema、daemon messageは翻訳せず" in design
    assert "未対応言語がない場合" not in design
    assert "対応言語がない場合は英語へfallback" in design

    subprocess.run(["node", "--check", str(I18N)], check=True)
    audit_dynamic_literals(source)
    browser_smoke()
    print("ok: HTTP UI i18n resolution, dynamic strings, and browser rendering")


if __name__ == "__main__":
    main()
