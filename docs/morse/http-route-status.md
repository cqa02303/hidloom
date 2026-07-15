# MORSE inspector HTTP route status

更新日: 2026-07-15

`/api/interaction/morse-inspector`は`daemon/http/morse_inspector.py`から登録される
read-only endpointです。`/api/interaction/morse-feedback`は
`daemon/http/morse_feedback_api.py`から登録され、logicd ctrl socketの
`MORSE_FEEDBACK`をHTTPからdrainします。

Web UIはJSON editorの内容からbrowser側でもMorse Treeを生成します。
HTTP routeは外部確認、回帰test、inspector API用に維持します。

## 登録内容

`daemon/http/httpd.py`のimport:

```python
from morse_inspector import register_morse_inspector_route
from morse_feedback_api import register_morse_feedback_route
```

`create_app()`のInteraction route:

```python
app.router.add_get("/api/interaction", handle_interaction_get)
app.router.add_put("/api/interaction", handle_interaction_put)
app.router.add_post("/api/interaction/validate", handle_interaction_validate)
register_morse_inspector_route(app, CONFIG_JSON, VIAL_JSON)
register_morse_feedback_route(app, _send_ctrl_command)
```

## 検証済み契約

- [x] inspector routeを`create_app()`へ登録する。
- [x] feedback routeからctrl socket `MORSE_FEEDBACK`をdrainする。
- [x] `schema.route`が`/api/interaction/morse-inspector`である。
- [x] `schema.editor`が`read_only`である。
- [x] pending / commit / cancel / fallback feedbackをOLED alertへ接続する。
- [x] pending / commit / cancel / fallback feedbackをLED flashへ接続する。
- [x] browser-side Morse Treeとbuilder操作をNode DOM smokeで検証する。
- [x] workstationから実機Web UIへbrowser smokeを実行できる。

関連する回帰testとhelper:

- `script/test_morse_inspector.py`
- `script/test_morse_feedback_api.py`
- `script/test_morse_browser_smoke_tool.py`
- `tools/morse_browser_smoke.py`

## 運用境界

inspector routeはread-onlyのためCSRF tokenを要求しません。
設定変更は既存の`PUT /api/interaction`だけを使用します。
feedback routeはdrain endpointなので、呼び出すたびにbuffered feedbackを空にします。
512MB Raspberry Pi実機ではChromiumを起動せず、workstationまたはNode DOM smokeを使用します。

## 関連

- [behavior-current.md](behavior-current.md)
- `daemon/http/morse_inspector.py`
- `daemon/http/morse_feedback_api.py`
- `daemon/http/httpd.py`
